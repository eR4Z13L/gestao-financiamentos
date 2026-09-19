"""Testa os cards de "Todas as Propostas": cores por status e contraste nos dois
temas, layout responsivo da grade, clique/Enter que abre a tela de leitura,
desenho real (cor da faixa lateral de cada status, inclusive trocando o tema
com o app aberto) e a tela em si (busca, filtro de status, botoes Editar/
Excluir/Nova Proposta, perfil VENDEDOR). Dados FICTICIOS numa planilha temporaria.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_cards_propostas.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl
import pandas as pd
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

import config
config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
from core import clientes as clientes_mod
from core import data_store as bd
from core import equipamentos as equipamentos_mod
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import vendedores as vendedores_mod
from core.validators import _digito_verificador_cpf
from desktop import settings as settings_mod
from desktop.dialogs.proposta_dialog import PropostaDialog
from desktop.screens.propostas_screen import _FILTRO_TODOS, PropostasScreen
from desktop.theme import CORES_STATUS, PALETAS, TEMA_CLARO, TEMA_ESCURO, build_stylesheet
from desktop.widgets.lista_cartoes import (
    ALTURA_CARTAO,
    LARGURA_MINIMA_CARTAO,
    ListaCartoes,
    ModeloCartoes,
    chave_cor_status,
)


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _luminancia(cor_hex: str) -> float:
    c = QColor(cor_hex)

    def canal(v: float) -> float:
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * canal(c.redF()) + 0.7152 * canal(c.greenF()) + 0.0722 * canal(c.blueF())


def _contraste(a: str, b: str) -> float:
    claro, escuro = sorted((_luminancia(a), _luminancia(b)), reverse=True)
    return (claro + 0.05) / (escuro + 0.05)


def _cpf(n: int) -> str:
    base = f"{123456780 + n:09d}"
    return base + _digito_verificador_cpf(base)


def _ciclos(app: QApplication, n: int = 3) -> None:
    for _ in range(n):  # o layout da grade e adiado: precisa de mais de um ciclo de eventos
        app.processEvents()


# ---------------------------------------------------------------------------

def testar_cores() -> None:
    linha("1) Cor de cada status")
    esperado = {
        "Em Análise": "em_analise", "EM ANALISE": "em_analise", "Pré-aprovado": "pre_aprovado", "PRE-APROVADO": "pre_aprovado",
        "Aprovado": "aprovado", "APROVADO": "aprovado", "Nota Fiscal Anexada": "nota_fiscal", "Garantia Assinada": "garantia",
        "Efetivado": "efetivado", "EFETIVADO": "efetivado", "Negado": "negado", "NEGADO": "negado", "Reprovado": "negado",
        "Cancelado": "negado", "": "neutro", "Status Maluco": "neutro",
    }
    for status, chave in esperado.items():
        assert chave_cor_status(status) == chave, (status, chave_cor_status(status))
    for status in propostas_mod.STATUS_OPCOES:
        assert chave_cor_status(status) != "neutro", f"status oficial sem cor propria: {status}"
    print("OK: cada status oficial tem cor própria (grafias antigas em CAIXA ALTA incluídas); vazio/desconhecido = cinza.")

    linha("1b) Contraste nos dois temas (WCAG)")
    for tema in (TEMA_ESCURO, TEMA_CLARO):
        cartao = PALETAS[tema]["bg_card"]
        assert set(CORES_STATUS[tema]) == {"aprovado", "efetivado", "negado", "em_analise", "pre_aprovado", "nota_fiscal", "garantia", "neutro"}
        for chave, cor in CORES_STATUS[tema].items():
            texto_na_pilula = _contraste(cor["texto"], cor["fundo"])
            faixa_no_card = _contraste(cor["faixa"], cartao)
            assert texto_na_pilula >= 4.5, f"{tema}/{chave}: texto da pílula {texto_na_pilula:.2f} < 4.5"
            assert faixa_no_card >= 3.0, f"{tema}/{chave}: faixa sobre o card {faixa_no_card:.2f} < 3"
        faixas = {k: v["faixa"] for k, v in CORES_STATUS[tema].items() if k not in ("efetivado", "neutro")}
        assert len(set(faixas.values())) == len(faixas), f"{tema}: etapas diferentes precisam de cores diferentes"
        assert CORES_STATUS[tema]["aprovado"]["faixa"] == CORES_STATUS[tema]["efetivado"]["faixa"], "Aprovado e Efetivado: os dois verdes"
        assert CORES_STATUS[tema]["efetivado"]["fundo"] != CORES_STATUS[tema]["aprovado"]["fundo"], "Efetivado tem a pílula preenchida"
    print("OK: texto da pílula ≥ 4,5:1 e faixa sobre o card ≥ 3:1 em todas as 8 cores, no escuro e no claro; "
          "Aprovado/Efetivado verdes (Efetivado com pílula preenchida) e as demais etapas com cores distintas.")


def _itens(statuses: list[str], clientes: list[str] | None = None) -> list[dict]:
    return [
        {"indice": 100 + i, "cliente": (clientes[i] if clientes else f"CLIENTE {i}"), "status": s, "data": f"{i + 1:02d}/01/2026"}
        for i, s in enumerate(statuses)
    ]


def testar_modelo_e_layout(app: QApplication) -> None:
    linha("2) Modelo dos cards")
    modelo = ModeloCartoes()
    modelo.definir_itens(_itens(["Aprovado", "Negado"], ["ANA", ""]))
    assert modelo.rowCount() == 2 and modelo.indice_real(1) == 101 and modelo.linha_do_indice_real(101) == 1
    assert modelo.linha_do_indice_real(999) is None
    assert modelo.data(modelo.index(0)) == "ANA" and "Aprovado" in modelo.data(modelo.index(0), Qt.ItemDataRole.ToolTipRole)
    assert "(cliente não encontrado)" in modelo.data(modelo.index(1), Qt.ItemDataRole.ToolTipRole)
    print("OK: modelo guarda a posição real da proposta e mostra tooltip com o nome inteiro.")

    linha("2b) Grade responsiva")
    lista = ListaCartoes()
    grande = ModeloCartoes()
    grande.definir_itens(_itens(["Em Análise"] * 40))
    lista.setModel(grande)
    lista.show()
    # varre muitas larguras (nao so algumas "redondas"): o erro que ja aconteceu foi a grade do Qt
    # quebrar em menos colunas do que o calculo previa numa largura especifica
    colunas_por_largura: list[int] = []
    for largura in range(360, 1900, 5):
        lista.resize(largura, 500)
        _ciclos(app, 2)
        xs = sorted({lista.visualRect(grande.index(i)).x() for i in range(10)})
        assert len(xs) == lista.colunas(), f"largura {largura}: o Qt montou {len(xs)} coluna(s), o cálculo previa {lista.colunas()}"
        if lista.colunas() > 1:
            assert lista._largura_atual >= LARGURA_MINIMA_CARTAO, f"largura {largura}: card de {lista._largura_atual}px"
        assert xs[-1] + lista._largura_atual <= lista.viewport().width(), f"largura {largura}: card estoura a área visível"
        colunas_por_largura.append(len(xs))
    assert colunas_por_largura == sorted(colunas_por_largura), "mais largura nunca pode dar menos colunas"
    assert colunas_por_largura[0] == 1 and colunas_por_largura[-1] >= 5
    print(f"OK: {len(colunas_por_largura)} larguras testadas (de 360 a 1900 px): a grade do Qt sempre bate com o cálculo "
          f"({colunas_por_largura[0]} a {colunas_por_largura[-1]} colunas), cards ≥ {LARGURA_MINIMA_CARTAO}px e nunca estourando a janela.")

    linha("2c) Clique só vale em cima do card (não no espaço entre cards)")
    lista.resize(1150, 600)
    _ciclos(app)
    retangulo = lista.visualRect(grande.index(0))
    assert lista.indexAt(QPoint(retangulo.left() + 20, retangulo.top() + 20)).row() == 0
    assert not lista.indexAt(QPoint(retangulo.left() + lista._largura_atual + 5, retangulo.top() + 20)).isValid(), "vão horizontal"
    assert not lista.indexAt(QPoint(retangulo.left() + 20, retangulo.top() + ALTURA_CARTAO + 5)).isValid(), "vão vertical"
    acionados: list[int] = []
    lista.acionado.connect(acionados.append)
    QTest.mouseClick(lista.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(retangulo.left() + 30, retangulo.top() + 30))
    assert acionados == [0] and lista.linha_atual() == 0, "clicar no card seleciona e aciona"
    QTest.mouseClick(lista.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(retangulo.left() + lista._largura_atual + 5, retangulo.top() + 20))
    assert acionados == [0], "clicar no vão não aciona nada"
    lista.setCurrentIndex(grande.index(3))
    QTest.keyClick(lista, Qt.Key.Key_Return)
    assert acionados == [0, 3], "Enter no card selecionado também aciona"
    lista.clearSelection()
    lista.setCurrentIndex(grande.index(-1))
    QTest.keyClick(lista, Qt.Key.Key_Return)
    assert acionados == [0, 3], "Enter sem card selecionado não aciona nada"
    print("OK: clique no card seleciona e aciona; clique no vão entre cards e Enter sem seleção não fazem nada; Enter aciona.")
    lista.close()


def _pixel(lista: ListaCartoes, linha_: int, dx: int) -> QColor:
    retangulo = lista.visualRect(lista.model().index(linha_))
    imagem = lista.viewport().grab().toImage()
    return imagem.pixelColor(retangulo.left() + dx, retangulo.top() + ALTURA_CARTAO // 2)


def testar_desenho(app: QApplication) -> None:
    linha("3) Desenho: cor da faixa de cada status, nos dois temas e trocando o tema com o app aberto")
    statuses = ["Aprovado", "Efetivado", "Negado", "Em Análise", "Pré-aprovado", "Nota Fiscal Anexada", "Garantia Assinada", ""]
    lista = ListaCartoes()
    modelo = ModeloCartoes()
    modelo.definir_itens(_itens(statuses))
    lista.setModel(modelo)
    lista.resize(1500, 700)
    original_obter = settings_mod.obter_tema
    try:
        for tema in (TEMA_ESCURO, TEMA_CLARO, TEMA_ESCURO):  # termina no escuro: prova a troca nos DOIS sentidos
            settings_mod.obter_tema = lambda t=tema: t  # o app grava o tema antes de reaplicar o stylesheet
            app.setStyleSheet(build_stylesheet(tema))
            lista.show()
            _ciclos(app)
            for i, status in enumerate(statuses):
                esperado = QColor(CORES_STATUS[tema][chave_cor_status(status)]["faixa"])
                obtido = _pixel(lista, i, 3)
                assert obtido.rgb() == esperado.rgb(), f"{tema}/{status!r}: faixa {obtido.name()} != {esperado.name()}"
            fundo_card = _pixel(lista, 0, 120)  # meio do card, longe do texto: cor do card
            assert fundo_card.rgb() == QColor(PALETAS[tema]["bg_card"]).rgb(), f"{tema}: fundo do card {fundo_card.name()}"
    finally:
        settings_mod.obter_tema = original_obter
        app.setStyleSheet("")
    lista.close()
    print("OK: os 8 status pintam a faixa na cor certa e o card no fundo do tema; trocar escuro→claro→escuro com o app "
          "aberto repinta tudo.")


# ---------------------------------------------------------------------------

def _criar_planilha_vazia(caminho: Path) -> None:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for nome, colunas in (
        (bd.ABA_CLIENTES, bd.CLIENTES_COLUNAS),
        (bd.ABA_EQUIPAMENTOS, bd.EQUIPAMENTOS_COLUNAS),
        (bd.ABA_PROPOSTAS, bd.PROPOSTAS_COLUNAS),
        (bd.ABA_VENDEDORES, bd.VENDEDORES_COLUNAS),
    ):
        wb.create_sheet(nome).append(colunas)
    wb.save(caminho)


class _Stubs:
    def __enter__(self):
        self.orig = (QMessageBox.warning, QMessageBox.critical, QMessageBox.information, QMessageBox.question, PropostaDialog.exec)
        self.textos: list[str] = []
        self.dialogos: list[PropostaDialog] = []
        self.acao_exec = None  # funcao(dialogo) chamada dentro do exec simulado

        def _msg(*args, **kwargs):
            self.textos.append(str(args[2]) if len(args) > 2 else "")
            return QMessageBox.StandardButton.Ok

        def _exec(dialogo):
            self.dialogos.append(dialogo)
            if self.acao_exec:
                self.acao_exec(dialogo)
                return dialogo.result()
            return QDialog.DialogCode.Rejected

        QMessageBox.warning = QMessageBox.critical = QMessageBox.information = staticmethod(_msg)
        QMessageBox.question = staticmethod(lambda *a, **k: (self.textos.append(str(a[2])), QMessageBox.StandardButton.Yes)[1])
        PropostaDialog.exec = _exec
        return self

    def __exit__(self, *_):
        QMessageBox.warning, QMessageBox.critical, QMessageBox.information, QMessageBox.question, PropostaDialog.exec = self.orig


def _nomes_dos_cards(tela: PropostasScreen) -> list[str]:
    return [tela._modelo.data(tela._modelo.index(i)) for i in range(tela._modelo.rowCount())]


def testar_tela(app: QApplication, pasta: Path) -> None:
    arquivo = pasta / "controle.xlsx"
    _criar_planilha_vazia(arquivo)
    clientes_mod.CAMINHO_XLSX = propostas_mod.CAMINHO_XLSX = vendedores_mod.CAMINHO_XLSX = equipamentos_mod.CAMINHO_XLSX = arquivo
    vendedores_mod.adicionar_vendedor("ANA")
    vendedores_mod.adicionar_vendedor("BIA")
    clientes_mod.adicionar_cliente({"CPF/CNPJ": _cpf(0), "CLIENTE": "MARIA ANA", "TIPO": "Cliente", "VENDEDOR": "ANA"})
    clientes_mod.adicionar_cliente({"CPF/CNPJ": _cpf(1), "CLIENTE": "JOSE BIA", "TIPO": "Cliente", "VENDEDOR": "BIA"})
    propostas = [
        # (cpf, data, valor, banco, equipamento, status)
        (0, pd.Timestamp(2026, 3, 1), 10000, "Santander", "Laser X", "Em Análise"),
        (0, pd.Timestamp(2026, 3, 5), 20000, "Portobank", "Bisturi Y", "Aprovado"),
        (1, pd.Timestamp(2026, 3, 9), 30000, "Santander", "Laser Z", "Efetivado"),
        (1, pd.Timestamp(2026, 3, 3), 40000, "Hubcred BV", "Mesa W", "Negado"),
        (0, pd.Timestamp(2026, 3, 7), 50000, "Smart", "Cadeira V", "Garantia Assinada"),
    ]
    for cpf_n, data, valor, banco, equip, status in propostas:
        propostas_mod.adicionar_proposta(
            {"CPF": _cpf(cpf_n), "DATA": data, "VALOR (R$)": valor, "MESES": 24, "EQUIPAMENTO": equip, "BANCO": banco,
             "STATUS": status, "OBSERVAÇÕES": f"obs {valor}"}
        )

    with _Stubs() as stubs:
        linha("4) Tela: um card por proposta, com o essencial")
        tela = PropostasScreen()
        tela.resize(1100, 700)
        tela.show()
        _ciclos(app)
        assert tela._modelo.rowCount() == 5 and tela._contador.text().startswith("5 proposta(s)")
        assert "clique em um card" in tela._contador.text()
        # mais recente primeiro (como sempre foi na lista)
        primeiro = tela._modelo.data(tela._modelo.index(0), Qt.ItemDataRole.UserRole)
        assert (primeiro["cliente"], primeiro["status"], primeiro["data"]) == ("JOSE BIA", "Efetivado", "09/03/2026")
        assert [tela._modelo.data(tela._modelo.index(i), Qt.ItemDataRole.UserRole)["data"] for i in range(5)] == [
            "09/03/2026", "07/03/2026", "05/03/2026", "03/03/2026", "01/03/2026"]
        print("OK: 5 cards, do mais recente pro mais antigo, cada um com cliente + status + data.")

        linha("4b) Busca e filtro de status")
        tela._busca.setText("santander")
        assert tela._modelo.rowCount() == 2 and "2 proposta(s)" in tela._contador.text()
        tela._busca.setText("laser z")
        assert _nomes_dos_cards(tela) == ["JOSE BIA"]
        tela._busca.setText("maria")
        assert set(_nomes_dos_cards(tela)) == {"MARIA ANA"} and tela._modelo.rowCount() == 3
        tela._busca.setText(_cpf(1))
        assert set(_nomes_dos_cards(tela)) == {"JOSE BIA"} and tela._modelo.rowCount() == 2, "busca por CPF"
        tela._busca.setText("")
        _ciclos(app)
        assert tela._filtro_status.itemText(0) == _FILTRO_TODOS
        tela._filtro_status.setCurrentText("Negado")
        assert tela._modelo.rowCount() == 1 and _nomes_dos_cards(tela) == ["JOSE BIA"]
        tela._busca.setText("maria")  # combina: JOSE tem o Negado, MARIA nao
        _ciclos(app)
        assert tela._modelo.rowCount() == 0 and tela._lista._mensagem_vazia
        tela.grab()  # desenhar o estado vazio (mensagem) nao pode quebrar
        tela._busca.setText("")
        tela._filtro_status.setCurrentText(_FILTRO_TODOS)
        assert tela._modelo.rowCount() == 5
        print("OK: busca por cliente/banco/equipamento/CPF e filtro de status funcionam nos cards, combinados, "
              "com a contagem e a mensagem de vazio.")

        linha("5) Clicar no card abre a tela de leitura com os detalhes e os botões de copiar")
        retangulo = tela._lista.visualRect(tela._modelo.index(1))  # card 2: MARIA ANA / Garantia Assinada (07/03)
        QTest.mouseClick(tela._lista.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(retangulo.left() + 40, retangulo.top() + 30))
        assert len(stubs.dialogos) == 1
        d = stubs.dialogos[0]
        assert d._modo_leitura and d._cpf == _cpf(0)
        assert (d._banco.currentText(), d._equipamento.currentText(), d._status.currentText()) == ("Smart", "Cadeira V", "Garantia Assinada")
        assert d._valor.value() == 50000 and d._meses.value() == 24 and d._observacoes.toPlainText() == "obs 50000"
        assert len(d._botoes_copiar) == 7, "a mesma tela de leitura de sempre, com copiar em cada campo"
        assert d._botao_habilitar_edicao.isHidden() is False, "ADMIN pode habilitar a edição"
        assert tela._indice_real_selecionado() is not None
        print("OK: o clique abre a leitura da proposta certa (valor, meses, equipamento, banco, observações) "
              "com os 7 botões de copiar.")

        stubs.dialogos.clear()
        tela._lista.setCurrentIndex(tela._modelo.index(0))
        tela._botao_editar.click()
        assert len(stubs.dialogos) == 1 and stubs.dialogos[0]._banco.currentText() == "Santander"
        tela._lista.setCurrentIndex(tela._modelo.index(4))
        QTest.keyClick(tela._lista, Qt.Key.Key_Return)
        assert len(stubs.dialogos) == 2 and stubs.dialogos[1]._equipamento.currentText() == "Laser X", "Enter no card também abre"
        tela._lista.setCurrentIndex(tela._modelo.index(-1))
        tela._botao_editar.click()
        assert len(stubs.dialogos) == 2 and "Clique em um card" in stubs.textos[-1], "sem card selecionado: avisa"
        print("OK: botão Editar e Enter abrem o card selecionado; sem seleção o app avisa em vez de quebrar.")

        linha("6) Editar: o card continua selecionado depois de salvar")
        stubs.dialogos.clear()
        tela._lista.setCurrentIndex(tela._modelo.index(2))  # 05/03: MARIA ANA / Aprovado
        indice_antes = tela._indice_real_selecionado()

        def _editar_e_salvar(dialogo: PropostaDialog) -> None:
            dialogo._habilitar_edicao()
            dialogo._status.setCurrentText("Efetivado")
            dialogo._salvar()

        stubs.acao_exec = _editar_e_salvar
        tela._botao_editar.click()
        stubs.acao_exec = None
        assert tela._indice_real_selecionado() == indice_antes, "mesmo card (mesma proposta) segue selecionado"
        linha_do_card = tela._lista.linha_atual()
        assert tela._modelo.data(tela._modelo.index(linha_do_card), Qt.ItemDataRole.UserRole)["status"] == "Efetivado", "card já mostra o novo status"
        print("OK: depois de editar e salvar, o card mostra o status novo e continua selecionado.")

        linha("7) Excluir e Nova Proposta")
        stubs.textos.clear()
        total = tela._modelo.rowCount()
        tela._lista.setCurrentIndex(tela._modelo.index(0))
        tela._botao_excluir.click()
        assert "Tem certeza" in stubs.textos[-1] and tela._modelo.rowCount() == total - 1
        assert tela._lista.linha_atual() is None, "depois de excluir nenhum card fica selecionado (os índices mudam)"
        tela._botao_excluir.click()
        assert "Clique em um card" in stubs.textos[-1] and tela._modelo.rowCount() == total - 1

        def _nova(dialogo: PropostaDialog) -> None:
            dialogo._cliente_combo.setCurrentText(f"MARIA ANA — {_cpf(0)}")
            dialogo._valor.setValue(77777)
            dialogo._equipamento.setCurrentText("Equip Novo")
            dialogo._banco.setCurrentText("Banco Novo")
            dialogo._salvar()

        stubs.acao_exec = _nova
        tela._botao_nova.click()
        stubs.acao_exec = None
        assert tela._modelo.rowCount() == total, "a proposta nova aparece como um card"
        print("OK: Excluir remove o card selecionado (e avisa se não há nenhum); + Nova Proposta cria um card novo.")
        tela.close()

        linha("8) Perfil VENDEDOR: cards e leitura, sem editar/excluir/criar")
        sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_VENDEDOR, nome_usuario="ANA"))
        fonte_original = propostas_mod._ler_da_fonte_ativa
        propostas_mod._ler_da_fonte_ativa = lambda: sessao_mod.filtrar_por_vendedor_logado(bd.ler_propostas(arquivo))  # sem rede
        equip_original = equipamentos_mod.listar_nomes_equipamento

        def _sem_arquivo_local():
            raise FileNotFoundError("a maquina do vendedor nao tem o .xlsx local")

        equipamentos_mod.listar_nomes_equipamento = _sem_arquivo_local
        try:
            stubs.dialogos.clear()
            tela_v = PropostasScreen()
            tela_v.resize(1100, 700)
            tela_v.show()
            _ciclos(app)
            assert tela_v._botao_editar.isHidden() and tela_v._botao_excluir.isHidden() and tela_v._botao_nova.isHidden()
            assert set(_nomes_dos_cards(tela_v)) == {"MARIA ANA"}, "vendedor só vê as próprias propostas"
            retangulo = tela_v._lista.visualRect(tela_v._modelo.index(0))
            QTest.mouseClick(tela_v._lista.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(retangulo.left() + 40, retangulo.top() + 30))
            assert len(stubs.dialogos) == 1, "vendedor abre o card na leitura"
            dv = stubs.dialogos[0]
            assert dv._modo_leitura and dv._botao_habilitar_edicao.isHidden(), "sem 'Habilitar edição' pro vendedor"
            assert dv._banco.currentText() and dv._valor.value() > 0 and len(dv._botoes_copiar) == 7
            tela_v.close()
        finally:
            propostas_mod._ler_da_fonte_ativa = fonte_original
            equipamentos_mod.listar_nomes_equipamento = equip_original
            sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
        print("OK: o vendedor vê só os próprios cards e lê os detalhes (com copiar) mesmo sem o .xlsx local; "
              "não vê editar/excluir/criar nem 'Habilitar edição'.")
        assert not [t for t in stubs.textos if "Erro" in t], stubs.textos


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
    testar_cores()
    testar_modelo_e_layout(app)
    testar_desenho(app)

    pasta = Path(tempfile.mkdtemp(prefix="_smoke_cards_"))
    try:
        testar_tela(app, pasta)
        linha("TUDO OK")
    finally:
        for modulo in (clientes_mod, propostas_mod, vendedores_mod, equipamentos_mod):
            modulo.CAMINHO_XLSX = config.CAMINHO_XLSX
        sessao_mod.encerrar()
        shutil.rmtree(pasta, ignore_errors=True)


if __name__ == "__main__":
    main()
