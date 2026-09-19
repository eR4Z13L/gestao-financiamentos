"""Dialogo de lancamento/edicao de proposta.

Mesmo formulario serve pra tres casos:
- cpf fixo + proposta=None -> nova proposta pra um cliente ja conhecido
  (aberto a partir da Ficha de Cliente)
- cpf fixo + proposta+indice -> abrir uma proposta existente
- cpf=None -> nova proposta "avulsa" (aberto a partir da tela Todas as
  Propostas, que nao tem um cliente pre-selecionado): mostra um campo de
  cliente pesquisavel em vez do titulo com o nome fixo.

Uma proposta existente abre primeiro em MODO LEITURA (campos travados - mesma
caixa da edicao, mas so pra ler/selecionar -, com um botao de copiar ao lado
de cada um, e os botoes Fechar e "Habilitar edicao"). So depois de "Habilitar
edicao" o formulario vira o de edicao de sempre, com OK/Cancelar - e Cancelar
descarta o que foi digitado e VOLTA pra leitura (so "Fechar" fecha o dialogo).
Proposta nova abre direto em edicao (nao ha o que "voltar"): Cancelar fecha.
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QCompleter,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QMessageBox,
    QPlainTextEdit,
    QSpinBox,
    QWidget,
)

from config import BANCOS_CONHECIDOS
from core import clientes as clientes_mod
from core import data_store as bd
from core import equipamentos as equipamentos_mod
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from desktop.widgets.botao_copiar import BotaoCopiar
from desktop.widgets.combo_travavel import ComboTravavel


class PropostaDialog(QDialog):
    def __init__(
        self,
        cpf: str | None,
        nome_cliente: str | None = None,
        proposta: dict | None = None,
        indice: int | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._cpf = cpf
        self._indice = indice
        self._nome_cliente = nome_cliente
        self._existente = proposta is not None
        self._proposta_original = proposta  # o que "Cancelar" restaura
        self._modo_leitura = False
        self._fechando = False  # True quando a janela esta sendo fechada de verdade (botao X)
        self._botoes_copiar: list[BotaoCopiar] = []
        self._clientes_por_rotulo: dict[str, str] = {}

        self.setMinimumWidth(520)

        layout = QFormLayout(self)

        if cpf is None:
            self._cliente_combo = QComboBox()
            self._cliente_combo.setEditable(True)
            for _, c in clientes_mod.listar_clientes().iterrows():
                rotulo = f"{c['CLIENTE']} — {c['CPF/CNPJ']}"
                self._clientes_por_rotulo[rotulo] = c["CPF/CNPJ"]
            self._cliente_combo.addItems(sorted(self._clientes_por_rotulo.keys()))
            self._cliente_combo.setCurrentText("")
            completador = QCompleter(list(self._clientes_por_rotulo.keys()), self)
            completador.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completador.setFilterMode(Qt.MatchFlag.MatchContains)
            self._cliente_combo.setCompleter(completador)
            layout.addRow("Cliente *", self._cliente_combo)
        else:
            self._cliente_combo = None

        self._data = QDateEdit()
        self._data.setCalendarPopup(True)
        self._data.setDisplayFormat("dd/MM/yyyy")
        self._adicionar_linha(layout, "Data", self._data, lambda c: c.date().toString("dd/MM/yyyy"))

        self._valor = QDoubleSpinBox()
        self._valor.setRange(0, 10_000_000)
        self._valor.setDecimals(2)
        self._valor.setPrefix("R$ ")
        self._valor.setGroupSeparatorShown(True)
        # sem o "R$ " (cleanText) - quem cola isso num sistema de banco quase
        # nunca quer o prefixo; 0 = campo nao preenchido, entao nao ha o que copiar
        self._adicionar_linha(layout, "Valor solicitado *", self._valor, lambda c: c.cleanText() if c.value() else "")

        self._meses = QSpinBox()
        self._meses.setRange(0, 120)
        self._adicionar_linha(layout, "Meses", self._meses, lambda c: str(c.value()) if c.value() else "")

        self._equipamento = ComboTravavel()
        self._equipamento.setEditable(True)
        self._equipamento.addItems(equipamentos_mod.listar_nomes_equipamento())
        self._adicionar_linha(layout, "Equipamento *", self._equipamento, lambda c: c.currentText().strip())

        self._banco = ComboTravavel()
        self._banco.setEditable(True)
        self._banco.addItems(BANCOS_CONHECIDOS)
        self._adicionar_linha(layout, "Banco/financeira *", self._banco, lambda c: c.currentText().strip())

        self._status = ComboTravavel()
        opcoes_status = list(propostas_mod.STATUS_OPCOES)
        status_atual = (proposta.get("STATUS") if proposta else "") or ""
        if status_atual and status_atual not in opcoes_status:
            # dados antigos tem status em CAIXA ALTA ("APROVADO", "NEGADO")
            # que nao batem com a lista oficial ("Aprovado", "Negado") - sem
            # isso, editar uma proposta assim mudaria o status dela pra "Em
            # Análise" (o primeiro item) sem o usuario perceber.
            opcoes_status.insert(0, status_atual)
        self._status.addItems(opcoes_status)
        self._adicionar_linha(layout, "Status", self._status, lambda c: c.currentText().strip())

        self._observacoes = QPlainTextEdit()
        self._observacoes.setFixedHeight(70)
        self._adicionar_linha(layout, "Observações", self._observacoes, lambda c: c.toPlainText().strip(), alinhar_topo=True)

        self._preencher_campos(proposta)

        # travados, data/valor/meses ganham a caixa dos combos (mais alta que o
        # visual nativo deles - ver theme.py); a mesma altura minima sempre
        # evita que as linhas "pulem" ao alternar entre leitura e edicao
        self._banco.ensurePolished()
        altura_caixa = self._banco.sizeHint().height()
        for campo in (self._data, self._valor, self._meses):
            campo.setMinimumHeight(altura_caixa)

        # Ok/Cancelar so aparecem em modo edicao; Fechar/"Habilitar edicao" so
        # em modo leitura - _aplicar_modo() alterna a visibilidade
        self._botoes = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Close
        )
        # o Qt so traduz os botoes padrao se um QTranslator estiver carregado
        # (nao esta) - Ok/Cancelar ficam como o app ja mostrava, mas "Fechar"
        # e novo e deve aparecer em portugues
        self._botoes.button(QDialogButtonBox.StandardButton.Close).setText("Fechar")
        self._botao_habilitar_edicao = self._botoes.addButton("Habilitar edição", QDialogButtonBox.ButtonRole.ActionRole)
        self._botao_habilitar_edicao.setAutoDefault(False)
        self._botao_habilitar_edicao.clicked.connect(self._habilitar_edicao)
        self._botoes.accepted.connect(self._salvar)
        # nao usa o sinal rejected (Cancelar e Fechar o emitem igual): cada um
        # faz uma coisa diferente - Cancelar volta pra leitura, Fechar fecha
        self._botoes.button(QDialogButtonBox.StandardButton.Cancel).clicked.connect(self._cancelar_edicao)
        self._botoes.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.reject)
        layout.addRow(self._botoes)

        self._aplicar_modo(leitura=self._existente)

    def _preencher_campos(self, proposta: dict | None) -> None:
        """Poe em cada campo o valor da proposta (ou o padrao de uma proposta
        nova, se `proposta` for None) - usado ao abrir e tambem ao cancelar a
        edicao, pra descartar o que foi digitado."""
        data_atual = proposta.get("DATA") if proposta else None
        if isinstance(data_atual, pd.Timestamp) and not pd.isna(data_atual):
            self._data.setDate(QDate(data_atual.year, data_atual.month, data_atual.day))
        else:
            self._data.setDate(QDate.currentDate())

        valor = proposta.get("VALOR (R$)") if proposta else None
        self._valor.setValue(float(valor) if valor is not None and not pd.isna(valor) else 0)

        meses = proposta.get("MESES") if proposta else None
        self._meses.setValue(int(meses) if meses is not None and not pd.isna(meses) else 0)

        self._equipamento.setCurrentText(proposta.get("EQUIPAMENTO", "") if proposta else "")
        self._banco.setCurrentText(proposta.get("BANCO", "") if proposta else "")

        status_atual = (proposta.get("STATUS") if proposta else "") or ""
        if status_atual:
            self._status.setCurrentText(status_atual)

        self._observacoes.setPlainText(proposta.get("OBSERVAÇÕES", "") if proposta else "")

    def _adicionar_linha(self, layout: QFormLayout, rotulo: str, campo: QWidget, texto_do_campo, alinhar_topo: bool = False) -> None:
        """Poe `campo` no formulario com um botao Copiar ao lado - o botao so
        aparece em modo leitura (ver _aplicar_modo). `texto_do_campo` recebe
        o proprio campo e devolve o texto a copiar; nao pode capturar `self`
        (o dialogo): dialogo -> botao -> funcao -> dialogo seria um ciclo de
        referencias, e um dialogo sem pai so seria destruido pelo coletor de
        lixo, em momento arbitrario (ja causou crash "Aborted" nos testes)."""
        botao = BotaoCopiar(lambda: texto_do_campo(campo))
        self._botoes_copiar.append(botao)
        linha = QHBoxLayout()
        linha.setContentsMargins(0, 0, 0, 0)
        linha.addWidget(campo, stretch=1)
        alinhamento = Qt.AlignmentFlag.AlignTop if alinhar_topo else Qt.AlignmentFlag.AlignVCenter
        linha.addWidget(botao, alignment=alinhamento)
        layout.addRow(rotulo, linha)

    def _campos_editaveis(self) -> tuple[QWidget, ...]:
        # o campo de cliente (so existe em proposta nova, que nunca abre em
        # modo leitura) fica de fora de proposito
        return (self._data, self._valor, self._meses, self._equipamento, self._banco, self._status, self._observacoes)

    def _aplicar_modo(self, leitura: bool) -> None:
        self._modo_leitura = leitura

        if self._existente:
            titulo = "Proposta" if leitura else "Editar proposta"
        else:
            titulo = "Nova proposta"
        self.setWindowTitle(titulo + (f" — {self._nome_cliente}" if self._cpf else ""))

        self._travar_campos(leitura)

        for botao in self._botoes_copiar:
            botao.setVisible(leitura)

        ok = self._botoes.button(QDialogButtonBox.StandardButton.Ok)
        cancelar = self._botoes.button(QDialogButtonBox.StandardButton.Cancel)
        fechar = self._botoes.button(QDialogButtonBox.StandardButton.Close)
        ok.setVisible(not leitura)
        cancelar.setVisible(not leitura)
        fechar.setVisible(leitura)
        # VENDEDOR nunca escreve nada (core/sessao.py) - nao faz sentido nem
        # oferecer o botao; a barreira de verdade continua sendo a do core/
        self._botao_habilitar_edicao.setVisible(leitura and sessao_mod.eh_admin())
        # sem isso, Enter em modo leitura poderia cair em "Habilitar edicao"
        (fechar if leitura else ok).setDefault(True)
        if leitura:
            # o foco inicial cairia no primeiro campo (Data), que ja abriria
            # com um pedaco do texto destacado
            fechar.setFocus()

    def _travar_campos(self, travar: bool) -> None:
        """Somente leitura (nao "desabilitado"): o campo mantem a mesma caixa da
        edicao e o texto continua selecionavel/copiavel, mas nada muda."""
        for campo in (self._data, self._valor, self._meses):
            campo.setReadOnly(travar)
            # setas de "sobe/desce" (e a de calendario, no QDateEdit) so fazem
            # sentido editando
            campo.setButtonSymbols(
                QAbstractSpinBox.ButtonSymbols.NoButtons if travar else QAbstractSpinBox.ButtonSymbols.UpDownArrows
            )
        # NoButtons sozinho nao esconde a seta do calendario - so desligar o popup
        self._data.setCalendarPopup(not travar)
        self._observacoes.setReadOnly(travar)
        # o QSS (desktop/theme.py) so da caixa a estes quatro quando travados
        for campo in (self._data, self._valor, self._meses, self._observacoes):
            campo.setProperty("travado", travar)
            campo.style().unpolish(campo)
            campo.style().polish(campo)
        for combo in (self._equipamento, self._banco, self._status):
            combo.definir_travado(travar)

    def _habilitar_edicao(self) -> None:
        self._aplicar_modo(leitura=False)
        self._data.setFocus()

    def _cancelar_edicao(self) -> None:
        """Cancelar: descarta o que foi digitado e VOLTA pra leitura sem fechar
        o dialogo. Numa proposta nova nao ha leitura pra onde voltar - fecha."""
        if not self._existente:
            self.reject()
            return
        self._preencher_campos(self._proposta_original)
        self._aplicar_modo(leitura=True)

    def reject(self) -> None:
        # Esc em modo edicao age como o botao Cancelar (volta pra leitura) em
        # vez de fechar; em modo leitura, ou fechando a janela, fecha mesmo
        if self._existente and not self._modo_leitura and not self._fechando:
            self._cancelar_edicao()
            return
        super().reject()

    def closeEvent(self, evento) -> None:
        # o botao X da janela sempre fecha de verdade, mesmo em modo edicao
        # (senao cairia no reject() acima e so voltaria pra leitura)
        self._fechando = True
        super().closeEvent(evento)

    def _resolver_cpf(self) -> str | None:
        if self._cpf is not None:
            return self._cpf
        rotulo = self._cliente_combo.currentText().strip()
        cpf = self._clientes_por_rotulo.get(rotulo)
        if cpf is None:
            QMessageBox.warning(
                self, "Cliente não encontrado", "Selecione um cliente da lista (comece a digitar o nome ou CPF)."
            )
        return cpf

    def _confirmar(self, titulo: str, mensagem: str) -> bool:
        resposta = QMessageBox.question(
            self,
            titulo,
            mensagem,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return resposta == QMessageBox.StandardButton.Yes

    def _duplicata_provavel(self, cpf: str, data: pd.Timestamp, valor) -> bool:
        """Mesmo cliente + mesma data + mesmo valor de outra proposta ja
        lancada (ignorando a que esta sendo editada agora) - um sinal comum
        de duplicidade por engano (ex: clique duplo em "Salvar")."""
        try:
            historico = propostas_mod.historico_por_cpf(cpf)
        except Exception:
            return False  # checagem extra nao pode impedir o salvamento normal
        if self._indice is not None:
            historico = historico[historico.index != self._indice]
        if historico.empty or valor in (None, ""):
            return False
        mesma_data = historico["DATA"] == data
        mesmo_valor = (historico["VALOR (R$)"] - float(valor)).abs() < 0.01
        return bool((mesma_data & mesmo_valor).any())

    def _salvar(self) -> None:
        if self._modo_leitura:
            return  # nao ha botao Ok em modo leitura; garante que nenhum outro caminho grave nesse modo
        cpf = self._resolver_cpf()
        if cpf is None:
            return

        banco = self._banco.currentText().strip()
        status = self._status.currentText().strip()
        faltando = [rotulo for rotulo, valor in (("Banco/financeira", banco), ("Status", status)) if not valor]
        if faltando:
            plural = len(faltando) > 1
            if not self._confirmar(
                "Campo recomendado em branco",
                f"{' e '.join(faltando)} não {'foram preenchidos' if plural else 'foi preenchido'}. "
                "Deseja salvar assim mesmo?",
            ):
                return

        qdate = self._data.date()
        data_proposta = pd.Timestamp(qdate.year(), qdate.month(), qdate.day())
        valor_informado = self._valor.value() or ""  # 0 = campo nao preenchido (mesma convencao de MESES)

        if self._duplicata_provavel(cpf, data_proposta, valor_informado):
            if not self._confirmar(
                "Possível duplicata",
                "Já existe uma proposta deste cliente com a mesma data e o mesmo valor. "
                "Deseja salvar mesmo assim?",
            ):
                return

        campos = {
            "DATA": data_proposta,
            "CPF": cpf,
            "VALOR (R$)": valor_informado,
            "MESES": self._meses.value() or "",
            "EQUIPAMENTO": self._equipamento.currentText().strip(),
            "BANCO": banco,
            "STATUS": status,
            "OBSERVAÇÕES": self._observacoes.toPlainText().strip(),
        }
        try:
            if self._indice is None:
                propostas_mod.adicionar_proposta(campos)
            else:
                propostas_mod.atualizar_proposta(self._indice, campos)
        except propostas_mod.ErroProposta as exc:
            QMessageBox.warning(self, "Não foi possível salvar", str(exc))
            return
        except sessao_mod.PermissaoNegada as exc:
            QMessageBox.warning(self, "Ação não permitida", str(exc))
            return
        except bd.ErroArquivoBloqueado as exc:
            QMessageBox.critical(self, "Arquivo bloqueado", str(exc))
            return
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro inesperado ao salvar", str(exc))
            return

        self.accept()
