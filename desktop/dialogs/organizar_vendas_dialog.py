"""Juntar as propostas antigas em vendas (uma vez, num computador so): mostra o plano de core/migracao_vendas.py e as
duvidas que so a pessoa sabe responder - cada uma com dois botoes, nenhum marcado. So deixa aplicar com todas
respondidas. Antes de tudo confere se este computador esta em dia com a nuvem: juntar aqui e o outro PC continuar
mexendo nas propostas antigas criaria duas versoes diferentes das mesmas vendas."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QMessageBox,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

import config
from core import data_store as bd
from core import migracao_vendas as migracao_mod
from core import sincronizacao as sincronizacao_mod
from core import vendas as vendas_mod
from desktop.espera import rodar_esperando

_MOTIVO_NAO_EM_DIA = {
    sincronizacao_mod.SITUACAO_SEM_REDE: "Sem conexão com a nuvem agora: não dá para conferir se o outro computador mexeu nas "
                                         "propostas. Conecte à internet e tente de novo.",
    sincronizacao_mod.SITUACAO_NUVEM_MAIS_NOVA: "A nuvem tem alterações mais novas, feitas em outro computador. Baixe da nuvem "
                                                "antes (Administração > Sincronização e backup).",
    sincronizacao_mod.SITUACAO_LOCAL_PENDENTE: "Este computador tem alterações que ainda não foram para a nuvem. Espere a "
                                               "sincronização terminar (o indicador na barra lateral fica verde).",
    sincronizacao_mod.SITUACAO_CONFLITO: "Este computador e a nuvem estão com alterações diferentes. Resolva isso antes "
                                         "(Administração > Sincronização e backup).",
    sincronizacao_mod.SITUACAO_SEM_CONTROLE: "A nuvem ainda não tem controle de versão. Ligue o controle antes "
                                             "(Administração > Sincronização e backup).",
}


def em_dia_com_a_nuvem(parent: QWidget | None) -> bool:
    """Confere (rede!) se da para juntar agora; se nao, explica o que fazer antes."""
    if not config.SINCRONIZACAO_GOOGLE_ATIVADA:
        return True
    try:
        situacao = rodar_esperando(parent, "Conferindo a nuvem…", sincronizacao_mod.verificar_ao_abrir, limite_s=60)
    except Exception as exc:  # nunca falhar em silencio
        QMessageBox.warning(parent, "Não foi possível conferir a nuvem", f"{type(exc).__name__}: {exc}")
        return False
    if situacao.tipo in (sincronizacao_mod.SITUACAO_EM_DIA, sincronizacao_mod.SITUACAO_DESATIVADA):
        return True
    QMessageBox.warning(parent, "Ainda não dá para juntar", _MOTIVO_NAO_EM_DIA.get(situacao.tipo, situacao.detalhe or situacao.tipo))
    return False


class OrganizarVendasDialog(QDialog):
    def __init__(self, plano: migracao_mod.Plano, parent: QWidget | None = None):
        super().__init__(parent)
        self.plano = plano
        self.resultado: dict | None = None
        self.setWindowTitle("Juntar as propostas antigas em vendas")
        self.resize(720, 620)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        r = plano.resumo
        cabecalho = QLabel(
            f"<b>{r['propostas']} propostas antigas</b> viram vendas. O app já juntou sozinho o mesmo cliente com o mesmo "
            f"equipamento mandado com até {migracao_mod.DIAS_MESMA_VENDA} dias de diferença ({r['grupos']} grupos). "
            "O status de cada venda sai das propostas: se todos os bancos negaram, ela fica Perdida; se alguma foi "
            "efetivada, Efetivada; senão, Aguardando bancos.<br><br>"
            + (f"Falta você decidir <b>{r['duvidas']} caso(s)</b> abaixo. Um backup é feito antes de gravar."
               if plano.duvidas else "Não há nenhum caso em dúvida. Um backup é feito antes de gravar.")
        )
        cabecalho.setWordWrap(True)
        layout.addWidget(cabecalho)

        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QFrame.Shape.NoFrame)
        conteudo = QWidget()
        conteudo.setProperty("role", "transparente")
        lista = QVBoxLayout(conteudo)
        lista.setSpacing(10)
        self.respostas: dict[str, QButtonGroup] = {}
        for duvida in plano.duvidas:
            cartao = QFrame(conteudo)
            cartao.setProperty("role", "card")
            corpo = QVBoxLayout(cartao)
            titulo = QLabel(f"<b>{duvida.cliente or 'Cliente sem cadastro'}</b>", cartao)
            titulo.setProperty("role", "transparente")
            corpo.addWidget(titulo)
            pergunta = QLabel(duvida.pergunta, cartao)
            pergunta.setWordWrap(True)
            pergunta.setProperty("role", "transparente")
            corpo.addWidget(pergunta)
            grupo = QButtonGroup(cartao)
            for texto, valor in ((duvida.juntar, 1), (duvida.separar, 0)):
                opcao = QRadioButton(texto, cartao)
                grupo.addButton(opcao, valor)
                corpo.addWidget(opcao)
            grupo.idClicked.connect(self._atualizar_botao)
            self.respostas[duvida.chave] = grupo
            lista.addWidget(cartao)
        lista.addStretch()
        rolagem.setWidget(conteudo)
        layout.addWidget(rolagem, stretch=1)

        self.falta = QLabel("")
        self.falta.setProperty("role", "secundario")
        layout.addWidget(self.falta)
        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.botao_aplicar = botoes.button(QDialogButtonBox.StandardButton.Ok)
        self.botao_aplicar.setText("Juntar em vendas")
        botoes.accepted.connect(self._aplicar)
        botoes.rejected.connect(self.reject)
        layout.addWidget(botoes)
        self._atualizar_botao()

    def decisoes(self) -> dict[str, bool]:
        return {chave: grupo.checkedId() == 1 for chave, grupo in self.respostas.items() if grupo.checkedId() != -1}

    def _atualizar_botao(self, *_args) -> None:
        faltam = len(self.respostas) - len(self.decisoes())
        self.botao_aplicar.setEnabled(faltam == 0)
        self.falta.setText(f"Falta responder {faltam} caso(s)." if faltam else "Tudo respondido.")

    def _aplicar(self) -> None:
        try:
            self.resultado = migracao_mod.aplicar(self.plano, self.decisoes())
        except vendas_mod.ErroVenda as exc:
            QMessageBox.warning(self, "Não foi possível juntar", str(exc))
            return
        except bd.ErroArquivoBloqueado as exc:
            QMessageBox.critical(self, "Arquivo bloqueado", str(exc))
            return
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro inesperado ao juntar", f"{type(exc).__name__}: {exc}")
            return
        por_status = ", ".join(f"{n} {s.lower()}" for s, n in self.resultado["por_status"].items())
        QMessageBox.information(
            self, "Propostas juntadas em vendas",
            f"{self.resultado['propostas']} propostas viraram {self.resultado['vendas']} vendas ({por_status}).\n\n"
            f"O estado de antes foi guardado em:\n{self.resultado['backup']}",
        )
        self.accept()


def organizar(parent: QWidget | None) -> bool:
    """O fluxo completo: confere a nuvem, monta o plano e abre o dialogo. True se juntou."""
    if not em_dia_com_a_nuvem(parent):
        return False
    try:
        plano = migracao_mod.planejar()
    except Exception as exc:  # nunca falhar em silencio
        QMessageBox.critical(parent, "Erro ao montar o plano", f"{type(exc).__name__}: {exc}")
        return False
    if not plano.indices_sem_venda:
        QMessageBox.information(parent, "Nada para juntar", "Todas as propostas já estão em vendas.")
        return False
    dialogo = OrganizarVendasDialog(plano, parent)
    return dialogo.exec() == QDialog.DialogCode.Accepted and dialogo.resultado is not None
