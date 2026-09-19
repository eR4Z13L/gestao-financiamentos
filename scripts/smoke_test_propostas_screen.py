"""Testa a tela Todas as Propostas (filtro, cadastro/edicao/
exclusao), o modo "cliente avulso" do PropostaDialog, remover_proposta, e o
menu retratil/seletor de tema da MainWindow.

Os testes que mexem em dados usam copia temporaria do arquivo (nunca o
real). O teste de tema/menu substitui as funcoes de desktop/settings.py por
versoes em memoria, pra nao gravar nada no registro do Windows (onde o app
de verdade guarda essas preferencias).

Rodar com: venv/Scripts/python.exe scripts/smoke_test_propostas_screen.py
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from config import CAMINHO_XLSX

import config
config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
from core import clientes as clientes_mod
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core.validators import apenas_digitos
from desktop import settings as settings_mod
from desktop.dialogs.proposta_dialog import PropostaDialog
from desktop.main_window import MainWindow
from desktop.screens.propostas_screen import _FILTRO_TODOS, PropostasScreen
from desktop.theme import TEMA_CLARO, TEMA_ESCURO


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


class _StubMensagens:
    """Troca QMessageBox.warning/critical/information/question por stubs
    (todas modais - travariam o teste headless esperando um clique que nunca
    vem). Guarda o texto de cada chamada em `mensagens`."""

    def __init__(self, resposta_question=QMessageBox.StandardButton.Yes):
        self.mensagens: list[str] = []
        self._resposta_question = resposta_question
        self._originais = (QMessageBox.warning, QMessageBox.critical, QMessageBox.information, QMessageBox.question)

    def __enter__(self):
        def _stub(*args, **kwargs):
            self.mensagens.append(args[2] if len(args) > 2 else "")
            return QMessageBox.StandardButton.Ok

        def _stub_question(*args, **kwargs):
            self.mensagens.append(args[2] if len(args) > 2 else "")
            return self._resposta_question

        QMessageBox.warning = staticmethod(_stub)
        QMessageBox.critical = staticmethod(_stub)
        QMessageBox.information = staticmethod(_stub)
        QMessageBox.question = staticmethod(_stub_question)
        return self

    def __exit__(self, *_exc):
        QMessageBox.warning, QMessageBox.critical, QMessageBox.information, QMessageBox.question = self._originais


def testar_remover_proposta_core() -> None:
    linha("1) core.propostas.remover_proposta")

    tmp_path = CAMINHO_XLSX.parent / "_smoke_test_remover_proposta.xlsx"
    shutil.copy(CAMINHO_XLSX, tmp_path)
    clientes_mod.CAMINHO_XLSX = tmp_path
    propostas_mod.CAMINHO_XLSX = tmp_path

    try:
        antes = propostas_mod.listar_propostas()
        indice_alvo = antes.index[0]
        propostas_mod.remover_proposta(indice_alvo)
        depois = propostas_mod.listar_propostas()
        assert len(depois) == len(antes) - 1
        print(f"OK: proposta removida ({len(antes)} -> {len(depois)} propostas).")

        try:
            propostas_mod.remover_proposta(999_999)
            raise SystemExit("deveria ter rejeitado indice inexistente")
        except propostas_mod.ErroProposta as exc:
            print(f"OK: remover indice inexistente rejeitado -> {exc}")
    finally:
        # restaura o caminho real - senao o proximo teste desta mesma sessao
        # Python herdaria o caminho temporario (ja apagado logo abaixo) e
        # quebraria com FileNotFoundError ao tentar ler
        clientes_mod.CAMINHO_XLSX = CAMINHO_XLSX
        propostas_mod.CAMINHO_XLSX = CAMINHO_XLSX
        tmp_path.unlink(missing_ok=True)


def testar_dialogo_cliente_avulso(app: QApplication) -> None:
    linha("2) PropostaDialog em modo avulso (cpf=None)")

    tmp_path = CAMINHO_XLSX.parent / "_smoke_test_dialogo_avulso.xlsx"
    shutil.copy(CAMINHO_XLSX, tmp_path)
    clientes_mod.CAMINHO_XLSX = tmp_path
    propostas_mod.CAMINHO_XLSX = tmp_path

    with _StubMensagens() as stub:
        try:
            cliente_alvo = clientes_mod.listar_clientes().iloc[0]
            rotulo = f"{cliente_alvo['CLIENTE']} — {cliente_alvo['CPF/CNPJ']}"

            dialogo = PropostaDialog(cpf=None)
            assert dialogo._cliente_combo is not None
            dialogo._cliente_combo.setCurrentText(rotulo)
            dialogo._valor.setValue(12345)
            dialogo._equipamento.setCurrentText("Equip Avulso Teste")
            dialogo._banco.setCurrentText("Banco Avulso Teste")
            dialogo._salvar()
            assert dialogo.result() == QDialog.DialogCode.Accepted

            historico = propostas_mod.historico_por_cpf(cliente_alvo["CPF/CNPJ"])
            assert (historico["EQUIPAMENTO"] == "Equip Avulso Teste").any()
            print(f"OK: proposta avulsa criada para '{cliente_alvo['CLIENTE']}' via busca por cliente.")

            # sem escolher nenhum cliente na caixa de busca -> deve recusar
            dialogo2 = PropostaDialog(cpf=None)
            dialogo2._valor.setValue(500)
            dialogo2._equipamento.setCurrentText("X")
            dialogo2._banco.setCurrentText("Y")
            dialogo2._salvar()
            assert dialogo2.result() != QDialog.DialogCode.Accepted
            assert "cliente" in stub.mensagens[-1].lower()
            print(f"OK: sem selecionar cliente, salvar é recusado -> \"{stub.mensagens[-1]}\"")
        finally:
            clientes_mod.CAMINHO_XLSX = CAMINHO_XLSX
            propostas_mod.CAMINHO_XLSX = CAMINHO_XLSX
            tmp_path.unlink(missing_ok=True)


def testar_propostas_screen(app: QApplication) -> None:
    linha("3) PropostasScreen - filtro, edição, exclusão e nova proposta")

    tmp_path = CAMINHO_XLSX.parent / "_smoke_test_propostas_screen.xlsx"
    shutil.copy(CAMINHO_XLSX, tmp_path)
    clientes_mod.CAMINHO_XLSX = tmp_path
    propostas_mod.CAMINHO_XLSX = tmp_path

    with _StubMensagens():
        try:
            tela = PropostasScreen()
            total_inicial = tela._modelo.rowCount()
            assert total_inicial == len(propostas_mod.listar_propostas())
            print(f"OK: carregou {total_inicial} proposta(s), igual a listar_propostas().")

            # filtro por status
            assert tela._filtro_status.count() > 1
            status_alvo = tela._filtro_status.itemText(1)  # indice 0 = "Todos"
            tela._filtro_status.setCurrentText(status_alvo)
            esperado = int((propostas_mod.listar_propostas()["STATUS"] == status_alvo).sum())
            assert tela._modelo.rowCount() == esperado
            print(f"OK: filtro por status '{status_alvo}' -> {tela._modelo.rowCount()} linha(s) (esperado {esperado}).")
            tela._filtro_status.setCurrentText(_FILTRO_TODOS)

            # busca livre por CPF sem pontuacao
            propostas_completo = propostas_mod.listar_propostas()
            cpf_exemplo = propostas_completo.iloc[0]["CPF"]
            tela._busca.setText(apenas_digitos(cpf_exemplo))
            assert tela._modelo.rowCount() >= 1
            print(f"OK: busca por CPF (sem pontuação) encontrou {tela._modelo.rowCount()} linha(s).")
            tela._busca.setText("")
            assert tela._modelo.rowCount() == total_inicial

            # seleciona a primeira linha e edita
            tela._lista.setCurrentIndex(tela._modelo.index(0))  # (nao dispara o clique: so seleciona o card)
            indice_real, proposta_antes = tela._linha_selecionada()
            assert indice_real is not None

            original_exec = PropostaDialog.exec

            def _exec_edicao(self):
                assert self._modo_leitura, "proposta existente deveria abrir em modo leitura"
                self._habilitar_edicao()
                self._observacoes.setPlainText("editado via tela todas propostas")
                self._salvar()
                return self.result()

            PropostaDialog.exec = _exec_edicao
            try:
                tela._editar_selecionada()
            finally:
                PropostaDialog.exec = original_exec

            depois = propostas_mod.listar_propostas()
            assert depois.loc[indice_real, "OBSERVAÇÕES"] == "editado via tela todas propostas"
            print(f"OK: editar pela tela 'Todas as Propostas' funcionou (posição real {indice_real}).")

            # editar recarrega os cards (_carregar_dados) e o MESMO card continua
            # selecionado (mesma proposta no arquivo)
            assert tela._linha_selecionada()[0] == indice_real, "o card editado continua selecionado"
            indice_real_para_excluir, _ = tela._linha_selecionada()
            assert indice_real_para_excluir == indice_real, "deveria continuar sendo a mesma proposta (so 1 linha 0 possivel)"

            total_antes_excluir = tela._modelo.rowCount()
            tela._excluir_selecionada()
            assert tela._modelo.rowCount() == total_antes_excluir - 1
            assert clientes_mod.buscar_por_cpf  # so garante que o import nao foi removido por engano
            print(f"OK: exclusão pela tela funcionou ({total_antes_excluir} -> {tela._modelo.rowCount()}).")

            # nova proposta avulsa (sem cliente pre-selecionado)
            cliente_alvo = clientes_mod.listar_clientes().iloc[0]
            rotulo = f"{cliente_alvo['CLIENTE']} — {cliente_alvo['CPF/CNPJ']}"
            total_antes_add = tela._modelo.rowCount()

            original_exec2 = PropostaDialog.exec

            def _exec_nova(self):
                assert self._cliente_combo is not None
                self._cliente_combo.setCurrentText(rotulo)
                self._valor.setValue(9999)
                self._equipamento.setCurrentText("Equip Nova Tela")
                self._banco.setCurrentText("Banco Nova Tela")
                self._salvar()
                return self.result()

            PropostaDialog.exec = _exec_nova
            try:
                tela._abrir_nova_proposta()
            finally:
                PropostaDialog.exec = original_exec2

            assert tela._modelo.rowCount() == total_antes_add + 1
            print(f"OK: nova proposta avulsa criada pela tela ({total_antes_add} -> {tela._modelo.rowCount()}).")

            print("\nOK: PropostasScreen funciona de ponta a ponta.")
        finally:
            clientes_mod.CAMINHO_XLSX = CAMINHO_XLSX
            propostas_mod.CAMINHO_XLSX = CAMINHO_XLSX
            tmp_path.unlink(missing_ok=True)


def testar_sidebar_e_tema(app: QApplication) -> None:
    linha("4) Menu retrátil e seletor de tema (MainWindow)")

    # substitui a persistencia real (QSettings/registro do Windows) por
    # versoes em memoria, pra nao alterar a preferencia salva do app de
    # verdade so por causa deste teste
    estado_fake = {"tema": TEMA_ESCURO, "sidebar_recolhida": False}
    originais = (
        settings_mod.obter_tema,
        settings_mod.definir_tema,
        settings_mod.obter_sidebar_recolhida,
        settings_mod.definir_sidebar_recolhida,
    )
    settings_mod.obter_tema = lambda: estado_fake["tema"]
    settings_mod.definir_tema = lambda t: estado_fake.__setitem__("tema", t)
    settings_mod.obter_sidebar_recolhida = lambda: estado_fake["sidebar_recolhida"]
    settings_mod.definir_sidebar_recolhida = lambda r: estado_fake.__setitem__("sidebar_recolhida", r)

    try:
        # so por seguranca: se algo inesperado disparar um QMessageBox aqui
        # (nao deveria, ja que le o arquivo real e valido), nao trava o teste
        with _StubMensagens():
            janela = MainWindow()
            assert janela._menu_recolhido is False
            rotulo_expandido = janela._menu.item(0).text()
            assert "Dashboard" in rotulo_expandido

            janela._alternar_sidebar()
            assert janela._menu_recolhido is True
            assert estado_fake["sidebar_recolhida"] is True
            rotulo_recolhido = janela._menu.item(0).text()
            assert "Dashboard" not in rotulo_recolhido
            print(f"OK: recolher o menu troca o texto ('{rotulo_expandido}' → '{rotulo_recolhido}') e persiste o estado.")

            janela._alternar_sidebar()
            assert janela._menu_recolhido is False
            assert estado_fake["sidebar_recolhida"] is False
            print("OK: expandir de novo volta ao texto completo e persiste o estado.")

            assert janela._tema_atual == TEMA_ESCURO
            assert "Claro" in janela._botao_tema.text()  # botao mostra a acao: "vire pro claro"
            janela._alternar_tema()
            assert janela._tema_atual == TEMA_CLARO
            assert estado_fake["tema"] == TEMA_CLARO
            assert "Escuro" in janela._botao_tema.text()  # agora oferece voltar pro escuro
            print("OK: clicar no botão de tema alterna e persiste a escolha.")

            print("\nOK: menu retrátil e botão de tema funcionam (testados sem tocar no registro real).")
    finally:
        (
            settings_mod.obter_tema,
            settings_mod.definir_tema,
            settings_mod.obter_sidebar_recolhida,
            settings_mod.definir_sidebar_recolhida,
        ) = originais


def main() -> None:
    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
    app = QApplication.instance() or QApplication(sys.argv)
    testar_remover_proposta_core()
    testar_dialogo_cliente_avulso(app)
    testar_propostas_screen(app)
    testar_sidebar_e_tema(app)
    linha("TUDO OK")


if __name__ == "__main__":
    main()
