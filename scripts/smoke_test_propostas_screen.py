"""Testa a tela Todas as Propostas (filtro, cadastro/edicao/
exclusao), o modo "cliente avulso" do formulario de proposta (card expandido), remover_proposta, e o
menu retratil/seletor de tema da MainWindow.

Os testes que mexem em dados usam copia temporaria do arquivo (nunca o
real). O teste de tema/menu usa uma planilha 100% ficticia (scripts/fixture_ficticia.py) e as
preferencias vao pra um .ini temporario (main() isola e, no fim, confere que o registro do
Windows - onde o app de verdade guarda essas preferencias - ficou igual).

Rodar com: venv/Scripts/python.exe scripts/smoke_test_propostas_screen.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QMessageBox

from config import CAMINHO_XLSX

import config
config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
import fixture_ficticia as fx
from core import clientes as clientes_mod
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import vendedores as vendedores_mod
from core.validators import apenas_digitos
from desktop import settings as settings_mod
from desktop.main_window import MainWindow
from desktop.screens.propostas_screen import _FILTRO_TODOS, PropostasScreen
from desktop.theme import TEMA_CLARO, TEMA_ESCURO
from desktop.widgets.formulario_proposta import FormularioProposta


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _espiar_gravacao(formulario: FormularioProposta) -> list[str]:
    """Lista que recebe "gravada" quando o formulario avisa que gravou (a funcao ligada ao
    sinal captura so a lista, nunca o formulario: seria um ciclo de referencias)."""
    avisos: list[str] = []
    formulario.gravada.connect(lambda: avisos.append("gravada"))
    return avisos


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
    linha("2) FormularioProposta em modo avulso (cpf=None)")

    tmp_path = CAMINHO_XLSX.parent / "_smoke_test_dialogo_avulso.xlsx"
    shutil.copy(CAMINHO_XLSX, tmp_path)
    clientes_mod.CAMINHO_XLSX = tmp_path
    propostas_mod.CAMINHO_XLSX = tmp_path

    with _StubMensagens() as stub:
        try:
            cliente_alvo = clientes_mod.listar_clientes().iloc[0]
            rotulo = f"{cliente_alvo['CLIENTE']} — {cliente_alvo['CPF/CNPJ']}"

            dialogo = FormularioProposta(cpf=None)
            gravou = _espiar_gravacao(dialogo)
            assert dialogo._cliente_combo is not None
            dialogo._cliente_combo.setCurrentText(rotulo)
            dialogo._valor.setValue(12345)
            dialogo._equipamento.setCurrentText("Equip Avulso Teste")
            dialogo._banco.setCurrentText("Banco Avulso Teste")
            dialogo._salvar()
            assert gravou == ["gravada"]

            historico = propostas_mod.historico_por_cpf(cliente_alvo["CPF/CNPJ"])
            assert (historico["EQUIPAMENTO"] == "Equip Avulso Teste").any()
            print(f"OK: proposta avulsa criada para '{cliente_alvo['CLIENTE']}' via busca por cliente.")

            # sem escolher nenhum cliente na caixa de busca -> deve recusar
            dialogo2 = FormularioProposta(cpf=None)
            gravou2 = _espiar_gravacao(dialogo2)
            dialogo2._valor.setValue(500)
            dialogo2._equipamento.setCurrentText("X")
            dialogo2._banco.setCurrentText("Y")
            dialogo2._salvar()
            assert gravou2 == []
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
    vendedores_mod.CAMINHO_XLSX = tmp_path  # a tela le o cadastro de vendedores pro filtro

    with _StubMensagens():
        try:
            tela = PropostasScreen()
            total_inicial = tela._modelo.total()
            assert total_inicial == len(propostas_mod.listar_propostas())
            print(f"OK: carregou {total_inicial} proposta(s), igual a listar_propostas().")

            # filtro por status
            assert tela._filtro_status.count() > 1
            status_alvo = tela._filtro_status.itemText(1)  # indice 0 = "Todos"
            tela._filtro_status.setCurrentText(status_alvo)
            esperado = int((propostas_mod.listar_propostas()["STATUS"] == status_alvo).sum())
            assert tela._modelo.total() == esperado
            print(f"OK: filtro por status '{status_alvo}' -> {tela._modelo.total()} linha(s) (esperado {esperado}).")
            tela._filtro_status.setCurrentText(_FILTRO_TODOS)

            # busca livre por CPF sem pontuacao
            propostas_completo = propostas_mod.listar_propostas()
            cpf_exemplo = propostas_completo.iloc[0]["CPF"]
            tela._busca.setText(apenas_digitos(cpf_exemplo))
            assert tela._modelo.total() >= 1
            print(f"OK: busca por CPF (sem pontuação) encontrou {tela._modelo.total()} linha(s).")
            tela._busca.setText("")
            assert tela._modelo.total() == total_inicial

            # seleciona a primeira linha e edita
            tela._lista.setCurrentIndex(tela._modelo.index(0))  # (nao dispara o clique: so seleciona o card)
            indice_real, proposta_antes = tela._linha_selecionada()
            assert indice_real is not None

            tela._expansor.alternar(tela._lista.linha_atual())  # duplo clique: o proprio card expande
            formulario = tela._expansor.formulario()
            assert tela._expansor.esta_expandido() and formulario._modo_leitura, "proposta existente deveria abrir em modo leitura"
            formulario._habilitar_edicao()
            formulario._observacoes.setPlainText("editado via tela todas propostas")
            formulario._salvar()
            gravado = tela._expansor.formulario()
            assert gravado is not None and gravado is not formulario and gravado._modo_leitura, \
                "gravar volta o card a leitura (continua expandido, ja com o que foi gravado)"
            assert gravado._observacoes.toPlainText() == "editado via tela todas propostas"
            tela._expansor.descartar()

            depois = propostas_mod.listar_propostas()
            assert depois.loc[indice_real, "OBSERVAÇÕES"] == "editado via tela todas propostas"
            print(f"OK: editar pela tela 'Todas as Propostas' funcionou (posição real {indice_real}).")

            # editar recarrega os cards (_carregar_dados) e o MESMO card continua
            # selecionado (mesma proposta no arquivo)
            assert tela._linha_selecionada()[0] == indice_real, "o card editado continua selecionado"
            indice_real_para_excluir, _ = tela._linha_selecionada()
            assert indice_real_para_excluir == indice_real, "deveria continuar sendo a mesma proposta (so 1 linha 0 possivel)"

            total_antes_excluir = tela._modelo.total()
            tela._excluir_selecionada()
            assert tela._modelo.total() == total_antes_excluir - 1
            assert clientes_mod.buscar_por_cpf  # so garante que o import nao foi removido por engano
            print(f"OK: exclusão pela tela funcionou ({total_antes_excluir} -> {tela._modelo.total()}).")

            # nova proposta avulsa (sem cliente pre-selecionado)
            cliente_alvo = clientes_mod.listar_clientes().iloc[0]
            rotulo = f"{cliente_alvo['CLIENTE']} — {cliente_alvo['CPF/CNPJ']}"
            total_antes_add = tela._modelo.total()

            tela._abrir_nova_proposta()
            formulario = tela._expansor.formulario()
            assert tela._expansor.eh_rascunho() and formulario._cliente_combo is not None
            formulario._cliente_combo.setCurrentText(rotulo)
            formulario._valor.setValue(9999)
            formulario._equipamento.setCurrentText("Equip Nova Tela")
            formulario._banco.setCurrentText("Banco Nova Tela")
            formulario._salvar()
            assert not tela._expansor.esta_expandido(), "gravar tira o card 'Nova proposta'"

            assert tela._modelo.total() == total_antes_add + 1
            print(f"OK: nova proposta avulsa criada pela tela ({total_antes_add} -> {tela._modelo.total()}).")

            print("\nOK: PropostasScreen funciona de ponta a ponta.")
        finally:
            clientes_mod.CAMINHO_XLSX = CAMINHO_XLSX
            propostas_mod.CAMINHO_XLSX = CAMINHO_XLSX
            vendedores_mod.CAMINHO_XLSX = CAMINHO_XLSX
            tmp_path.unlink(missing_ok=True)


def testar_sidebar_e_tema(app: QApplication) -> None:
    linha("4) Menu retrátil e seletor de tema (MainWindow)")

    # planilha 100% ficticia (nao a real) e preferencias num .ini temporario (ver main()): o
    # teste nunca le a planilha real nem grava no registro do Windows
    pasta = Path(tempfile.mkdtemp(prefix="sidebar_tema_"))
    fx.apontar_modulos_para(fx.criar(pasta))

    try:
        # so por seguranca: se algo inesperado disparar um QMessageBox aqui, nao trava o teste
        with _StubMensagens():
            janela = MainWindow()
            assert janela._menu_recolhido is False and not janela._menu.esta_recolhido()
            assert "Dashboard" in janela._menu._itens_por_chave["dashboard"].text()
            largura_expandida = janela._sidebar.width()

            janela._alternar_sidebar()
            assert janela._menu_recolhido is True
            assert settings_mod.obter_sidebar_recolhida() is True
            assert janela._menu.esta_recolhido() and janela._sidebar.width() < largura_expandida
            assert "Dashboard" in janela._menu._itens_por_chave["dashboard"].toolTip()  # recolhido, o rotulo vai no tooltip
            print(f"OK: recolher o menu estreita a barra ({largura_expandida} -> {janela._sidebar.width()} px), passa o rotulo pro tooltip e persiste o estado.")

            janela._alternar_sidebar()
            assert janela._menu_recolhido is False
            assert settings_mod.obter_sidebar_recolhida() is False
            assert janela._sidebar.width() == largura_expandida
            print("OK: expandir de novo volta a largura completa e persiste o estado.")

            assert janela._tema_atual == TEMA_ESCURO
            assert "Claro" in janela._botao_tema.text()  # botao mostra a acao: "vire pro claro"
            janela._alternar_tema()
            assert janela._tema_atual == TEMA_CLARO
            assert settings_mod.obter_tema() == TEMA_CLARO
            assert "Escuro" in janela._botao_tema.text()  # agora oferece voltar pro escuro
            print("OK: clicar no botão de tema alterna e persiste a escolha.")

            print("\nOK: menu retrátil e botão de tema funcionam (planilha fictícia e preferências isoladas).")
    finally:
        fx.restaurar_modulos()


def main() -> None:
    registro_antes = fx.instantaneo_do_registro()
    fx.isolar_preferencias(Path(tempfile.mkdtemp(prefix="prefs_propostas_")))
    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
    app = QApplication.instance() or QApplication(sys.argv)
    testar_remover_proposta_core()
    testar_dialogo_cliente_avulso(app)
    testar_propostas_screen(app)
    testar_sidebar_e_tema(app)
    assert fx.instantaneo_do_registro() == registro_antes, "o teste mexeu nas preferencias REAIS do app (registro do Windows)"
    linha("TUDO OK")


if __name__ == "__main__":
    main()
