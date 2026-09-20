"""Testa o CARD EXPANSIVEL de proposta (o que substituiu o painel lateral) e o "Duplicar":

1) o modelo com o card "Nova proposta" (rascunho) na linha 0 (validado pelo QAbstractItemModelTester);
2) a geometria: o duplo clique expande o PROPRIO card numa linha inteira da grade e EMPURRA os de baixo -
   nada fica coberto -, so um por vez, recolher devolve tudo onde estava, o formulario cabe dentro do card;
3) a grade compacta do formulario (Data/Meses/Status, Valor/Equipamento/Banco, Observacoes em largura toda);
4) as DUAS telas (Ficha de Cliente e Todas as Propostas) com o mesmo roteiro: clique so seleciona, duplo
   clique/Enter expande, leitura, Editar, Cancel volta pra leitura, Recolher, gravar, duplicar, nova proposta,
   excluir, aviso de edicao nao salva, proposta que sai da lista, e a protecao contra gravar por cima de outra;
5) VENDEDOR le mas nao edita nem duplica; nada do painel lateral/popup antigo existe mais.

Dados FICTICIOS, numa planilha temporaria.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_cartao_expansivel.py
"""

from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if Path(r"C:\Windows\Fonts").exists():  # sem tela o Qt nao acha fontes (todo caractere vira o mesmo quadradinho)
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl
import pandas as pd
from PySide6.QtCore import QDate, QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QMouseEvent, QWheelEvent
from PySide6.QtTest import QAbstractItemModelTester, QTest
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QLabel, QMessageBox, QVBoxLayout

import config
config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
from core import clientes as clientes_mod
from core import data_store as bd
from core import equipamentos as equipamentos_mod
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import vendedores as vendedores_mod
from core.validators import _digito_verificador_cpf, apenas_digitos
from desktop import settings as settings_mod
from desktop.screens.ficha_cliente_screen import FichaClienteScreen
from desktop.screens.propostas_screen import PropostasScreen
from desktop.theme import CORES_STATUS, TEMA_CLARO, TEMA_ESCURO, build_stylesheet
from desktop.widgets.expansor_proposta import ExpansorDeProposta
from desktop.widgets.formulario_proposta import FormularioProposta
from desktop.widgets.lista_cartoes import ALTURA_CABECALHO, ALTURA_CARTAO, ESPACO, RASCUNHO, ListaCartoes, ModeloCartoes


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _ciclos(app: QApplication, n: int = 6) -> None:
    for _ in range(n):
        app.processEvents()


def _cpf(n: int) -> str:
    base = f"{400000000 + n:09d}"
    return base + _digito_verificador_cpf(base)


def _duplo_clique(widget, ponto: QPoint) -> None:
    """Um duplo clique como o Windows o manda: press, release, press (que o Qt entrega
    como DblClick) e release."""
    QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=ponto)
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=ponto)
    evento = QMouseEvent(
        QEvent.Type.MouseButtonDblClick, QPointF(ponto), QPointF(widget.mapToGlobal(ponto)),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(widget, evento)
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=ponto)


def _item(indice: int, banco: str = "BANCO", status: str = "Negado", cor: str = "negado") -> dict:
    return {"indice": indice, "cliente": f"CLIENTE {indice}", "status": status, "data": "01/01/2026", "equipamento": "EQUIP",
            "banco": f"{banco} {indice}", "tempo": "Encerrado", "etapa": cor, "cor": cor}


def _formulario_de_teste(altura: int = 180) -> QFrame:
    """Um widget com tamanho proprio (sizeHint), no lugar do formulario, pros testes da lista."""
    quadro = QFrame()
    camada = QVBoxLayout(quadro)
    camada.setContentsMargins(0, 0, 0, 0)
    rotulo = QLabel("formulario")
    rotulo.setFixedHeight(altura)
    camada.addWidget(rotulo)
    return quadro


# ---------------------------------------------------------------------------
# 1) o modelo com o card "Nova proposta"

def testar_modelo_com_rascunho() -> None:
    linha("1) Modelo: o card 'Nova proposta' na linha 0, fora da paginação e sem índice")
    modelo = ModeloCartoes(tamanho_pagina=5)
    testador = QAbstractItemModelTester(modelo, QAbstractItemModelTester.FailureReportingMode.Fatal)
    modelo.definir_itens([_item(i) for i in range(12)])
    assert modelo.rowCount() == 6 and modelo.eh_mais(5) and modelo.indice_real(0) == 0

    modelo.definir_rascunho({"tipo": "rascunho", "titulo": "Nova proposta", "status": "", "cor": "neutro"})
    assert modelo.tem_rascunho() and modelo.eh_rascunho(0) and not modelo.eh_rascunho(1)
    assert modelo.rowCount() == 7, "o rascunho e uma linha a mais (os 5 itens + 'Carregar mais' seguem)"
    assert modelo.indice_real(0) is None, "o rascunho nao e uma proposta do arquivo"
    assert modelo.indice_real(1) == 0 and modelo.indice_real(5) == 4
    assert modelo.eh_mais(6) and not modelo.eh_mais(5), "o 'Carregar mais' desceu uma linha"
    assert modelo.linha_do_indice_real(0) == 1 and modelo.linha_da_chave(RASCUNHO) == 0 and modelo.linha_da_chave(3) == 4
    assert modelo.visiveis() == 5 and modelo.total() == 12, "o rascunho nao conta na paginacao"
    assert modelo.data(modelo.index(0)) == "Nova proposta"
    print("OK: o rascunho ocupa a linha 0; as propostas e o 'Carregar mais' descem uma linha; nao entra na contagem.")

    modelo.mostrar_mais()  # com o rascunho la em cima
    assert modelo.visiveis() == 10 and modelo.rowCount() == 12 and modelo.eh_mais(11) and modelo.indice_real(10) == 9
    modelo.definir_itens([_item(i) for i in range(12)], manter_limite=True)  # recarregar: o rascunho fica
    assert modelo.tem_rascunho() and modelo.rowCount() == 12
    modelo.mostrar_mais()
    assert modelo.rowCount() == 13 and not modelo.eh_mais(12) and modelo.indice_real(12) == 11
    modelo.definir_rascunho(None)
    assert not modelo.tem_rascunho() and modelo.rowCount() == 12 and modelo.indice_real(0) == 0
    modelo.definir_rascunho(None)  # tirar de novo nao faz nada
    assert modelo.rowCount() == 12
    print("OK: 'Carregar mais' e recarregar funcionam com o rascunho la em cima; tirar o rascunho devolve as linhas.")
    del testador


# ---------------------------------------------------------------------------
# 2) a geometria do card expandido

def _retangulos(lista: ListaCartoes, n: int) -> list[QRect]:
    return [lista.visualRect(lista.model().index(i)) for i in range(n)]


def _cartoes(lista: ListaCartoes, n: int) -> list[QRect]:
    """O desenho de cada card (a celula sem o espaco depois dele)."""
    return [lista._delegate.retangulo_do_cartao(r, lista._delegate.eh_expandido(lista.model().index(i)))
            for i, r in enumerate(_retangulos(lista, n))]


def testar_geometria_da_lista(app: QApplication) -> None:
    linha("2) Lista: o card expande numa linha inteira e EMPURRA os de baixo (nada fica coberto)")
    modelo = ModeloCartoes()
    lista = ListaCartoes()
    lista.setModel(modelo)
    modelo.definir_itens([_item(i) for i in range(11)])
    lista.resize(1000, 700)
    lista.show()
    _ciclos(app)
    colunas = lista.colunas()
    assert colunas == 3, colunas
    antes = _retangulos(lista, 11)

    perdidos: list = []
    lista.expansao_perdida.connect(perdidos.append)
    # 1o: o card 4 (2a coluna da 2a linha): na sua linha, antes dele, so o card 3
    corpo = _formulario_de_teste(180)
    assert lista.expandir(4, corpo) and lista.chave_expandida() == 4 and lista.widget_expandido() is corpo
    _ciclos(app)
    depois = _retangulos(lista, 11)
    exp = depois[4]
    assert exp.x() == 0 and exp.width() == colunas * (lista.largura_do_cartao() + ESPACO), "o card expandido ocupa a linha toda da grade"
    assert lista.largura_do_cartao_expandido() == exp.width() - ESPACO, "e termina na borda direita do último card de uma linha"
    assert exp.height() == ALTURA_CABECALHO + corpo.sizeHint().height() + 12 + ESPACO, exp.height()
    for i in range(4):
        assert depois[i] == antes[i], f"os cards ANTES do expandido nao se mexem (card {i})"
    for i in range(5, 11):
        assert depois[i].top() >= exp.bottom(), f"card {i}: desceu pra baixo do expandido"
    cartoes = _cartoes(lista, 11)
    for i in range(11):
        for j in range(i + 1, 11):
            assert not cartoes[i].intersects(cartoes[j]), f"cards {i} e {j} se sobrepoem"
    area = corpo.geometry()
    assert cartoes[4].contains(area) and area.top() >= cartoes[4].top() + ALTURA_CABECALHO, "o formulario cabe dentro do card, abaixo do cabecalho"
    assert corpo.isVisible() and corpo.parentWidget() is lista.viewport()
    print(f"OK: expandido ocupa a linha toda ({exp.width()} px); os de antes ficam onde estavam, os de baixo descem "
          f"({antes[5].top()} -> {depois[5].top()}), nenhum card se sobrepõe e o formulário cabe no card.")

    # clique no card expandido (cabecalho) o seleciona; no espaco entre cards, nao
    ponto = QPoint(exp.left() + 30, exp.top() + 20)
    assert lista.indexAt(ponto).row() == 4
    assert not lista.indexAt(QPoint(exp.left() + 30, exp.bottom() - 2)).isValid(), "o espaco embaixo do card nao e o card"

    # so um por vez: expandir outro recolhe (e descarta) o anterior
    corpo2 = _formulario_de_teste(120)
    assert lista.expandir(9, corpo2)
    _ciclos(app)
    assert lista.chave_expandida() == 9 and not corpo.isVisible() and corpo2.isVisible(), "so um card expandido por vez"
    assert lista.visualRect(lista.model().index(4)) == antes[4], "o anterior voltou ao tamanho normal"
    assert perdidos == [], "trocar de card expandido nao e 'perder' o card"
    lista.recolher()
    _ciclos(app)
    assert lista.widget_expandido() is None and not corpo2.isVisible() and _retangulos(lista, 11) == antes, "recolher devolve tudo onde estava"
    assert not lista.expandir(99, _formulario_de_teste())  # chave que nao esta na lista
    print("OK: só um card expandido por vez; recolher (ou trocar) devolve os cards exatamente onde estavam.")

    # recarregar o modelo: o widget do card expandido volta pro lugar (ou sai, se a proposta saiu)
    corpo3 = _formulario_de_teste(150)
    lista.expandir(6, corpo3)
    modelo.definir_itens([_item(i) for i in range(11)], manter_limite=True)  # mesmos itens
    _ciclos(app)
    assert lista.chave_expandida() == 6 and corpo3.isVisible() and lista.linha_expandida() == 6, "recarregar mantem o card expandido"
    modelo.definir_itens([_item(i) for i in range(11) if i != 2], manter_limite=True)  # o 2 sumiu: o 6 vira a linha 5
    _ciclos(app)
    assert lista.chave_expandida() == 6 and lista.linha_expandida() == 5 and corpo3.isVisible(), "a linha muda, o card segue o indice real"
    modelo.definir_itens([_item(i) for i in range(11) if i != 6], manter_limite=True)  # o proprio 6 sumiu
    _ciclos(app)
    assert perdidos == [6] and lista.widget_expandido() is None and not corpo3.isVisible(), "a proposta saiu: o card expandido e descartado"
    print("OK: recarregar a lista mantém o card expandido (mesmo se a linha muda); se a proposta sai, avisa (`expansao_perdida`).")

    # o rascunho: um card em cima, expandido
    modelo.definir_itens([_item(i) for i in range(11)])
    corpo4 = _formulario_de_teste(100)
    modelo.definir_rascunho({"tipo": "rascunho", "titulo": "Nova proposta", "linha2": "", "status": "", "data": "", "tempo": "",
                             "etapa": "", "cor": "neutro", "cliente": ""})
    assert lista.expandir(RASCUNHO, corpo4) and lista.linha_expandida() == 0
    _ciclos(app)
    assert lista.visualRect(lista.model().index(0)).top() == 0 and lista.visualRect(lista.model().index(1)).top() >= lista.visualRect(lista.model().index(0)).bottom()
    lista.recolher()
    modelo.definir_rascunho(None)
    lista.close()
    print("OK: o card 'Nova proposta' expande no topo da lista e empurra os outros.")


def testar_altura_automatica_e_rolagem(app: QApplication) -> None:
    linha("2b) Lista sem barra própria (histórico da Ficha): a altura acompanha o card expandido; a outra rola até ele")
    modelo = ModeloCartoes()
    lista = ListaCartoes(altura_automatica=True)
    lista.setModel(modelo)
    modelo.definir_itens([_item(i) for i in range(8)])
    lista.resize(700, 300)
    lista.show()
    _ciclos(app)
    alturas = []
    lista.altura_mudou.connect(alturas.append)

    def altura_real() -> int:
        return max(r.bottom() for r in _retangulos(lista, modelo.rowCount())) + 1 + 2 * lista.frameWidth()

    assert lista.height() == altura_real()
    for chave in (0, 3, 7):
        lista.expandir(chave, _formulario_de_teste(150 + chave * 10))
        _ciclos(app)
        assert lista.height() == altura_real(), f"expandido o card {chave}: lista com {lista.height()}, cards vao ate {altura_real()}"
    assert alturas, "avisa quando a altura muda"
    lista.recolher()
    _ciclos(app)
    assert lista.height() == altura_real()
    lista.close()
    print("OK: sem barra própria, a altura da lista acompanha o card expandido (na 1a, no meio e na última linha) e volta ao recolher.")

    # com barra propria: expandir um card la embaixo rola ate ele
    modelo = ModeloCartoes()
    lista = ListaCartoes()
    lista.setModel(modelo)
    modelo.definir_itens([_item(i) for i in range(30)])
    lista.resize(1000, 320)
    lista.show()
    _ciclos(app)
    lista.expandir(24, _formulario_de_teste(120))
    lista.garantir_visivel(lista.linha_expandida())
    _ciclos(app)
    r = lista.visualRect(modelo.index(24))
    assert r.top() >= 0 and r.bottom() <= lista.viewport().height(), f"o card expandido nao ficou a vista: {r} em {lista.viewport().rect()}"
    lista.close()
    print("OK: expandir um card lá embaixo rola a lista até ele.")


def testar_cores_do_card_expandido(app: QApplication) -> None:
    linha("2c) Nos dois temas: a faixa colorida acompanha o card expandido inteiro")
    original = settings_mod.obter_tema
    try:
        for tema in (TEMA_ESCURO, TEMA_CLARO):
            settings_mod.obter_tema = lambda t=tema: t
            app.setStyleSheet(build_stylesheet(tema))
            modelo = ModeloCartoes()
            lista = ListaCartoes()
            lista.setModel(modelo)
            modelo.definir_itens([_item(i, status="Efetivado", cor="efetivado") for i in range(4)])
            lista.resize(1000, 700)
            lista.show()
            _ciclos(app)
            lista.expandir(1, _formulario_de_teste(200))
            _ciclos(app)
            imagem = lista.viewport().grab().toImage()
            cartao = _cartoes(lista, 4)[1]
            faixa = QColor(CORES_STATUS[tema]["efetivado"]["faixa"]).rgb()
            for y in (cartao.top() + 20, cartao.top() + ALTURA_CABECALHO + 80, cartao.bottom() - 20):
                assert imagem.pixelColor(cartao.left() + 3, y).rgb() == faixa, f"{tema}: faixa em y={y} ({imagem.pixelColor(cartao.left() + 3, y).name()})"
            lista.close()
    finally:
        settings_mod.obter_tema = original
        app.setStyleSheet(build_stylesheet(TEMA_ESCURO))
    print("OK (escuro e claro): a faixa de status vai do topo ao fim do card expandido.")


# ---------------------------------------------------------------------------
# 3) as duas telas, o mesmo roteiro

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


def _cadastrar() -> dict[str, str]:
    vendedores_mod.adicionar_vendedor("ANA")
    vendedores_mod.adicionar_vendedor("BIA")
    cpfs = {"alfa": _cpf(0), "beta": _cpf(1), "gama": _cpf(2)}
    clientes_mod.adicionar_cliente({"CPF/CNPJ": cpfs["alfa"], "CLIENTE": "ALFA CLIENTE", "TIPO": "Cliente", "VENDEDOR": "ANA"})
    clientes_mod.adicionar_cliente({"CPF/CNPJ": cpfs["beta"], "CLIENTE": "BETA AVALISTA", "TIPO": "Avalista", "VENDEDOR": "BIA"})
    clientes_mod.adicionar_cliente({"CPF/CNPJ": cpfs["gama"], "CLIENTE": "GAMA SEM PROPOSTA", "TIPO": "Cliente", "VENDEDOR": "ANA"})
    for chave, data, valor, meses, equipamento, banco, status in [
        ("alfa", pd.Timestamp(2026, 3, 1), 75000, 36, "HAKON", "SANTANDER", "Negado"),
        ("alfa", pd.Timestamp(2026, 3, 5), 20000, 12, "MESA", "PORTOBANK", "Em Análise"),
        ("alfa", pd.Timestamp(2026, 3, 6), 31000, 24, "LASER X", "HUBCRED BV", "Aprovado"),
        ("beta", pd.Timestamp(2026, 3, 2), 1500.5, 24, "LASER", "SMART", "Efetivado"),
    ]:
        propostas_mod.adicionar_proposta(
            {"CPF": cpfs[chave], "DATA": data, "VALOR (R$)": valor, "MESES": meses, "EQUIPAMENTO": equipamento,
             "BANCO": banco, "STATUS": status, "OBSERVAÇÕES": f"obs {equipamento}"}
        )
    return cpfs


class _Stubs:
    """Mensagens modais (travariam o teste sem tela) viram registros; `question` responde `resposta`."""

    def __enter__(self):
        self.orig = (QMessageBox.warning, QMessageBox.critical, QMessageBox.information, QMessageBox.question)
        self.textos: list[str] = []
        self.titulos: list[str] = []
        self.resposta = QMessageBox.StandardButton.Yes

        def _msg(*args, **kwargs):
            self.titulos.append(str(args[1]) if len(args) > 1 else "")
            self.textos.append(str(args[2]) if len(args) > 2 else "")
            return QMessageBox.StandardButton.Ok

        def _pergunta(*args, **kwargs):
            self.titulos.append(str(args[1]) if len(args) > 1 else "")
            self.textos.append(str(args[2]) if len(args) > 2 else "")
            return self.resposta

        QMessageBox.warning = QMessageBox.critical = QMessageBox.information = staticmethod(_msg)
        QMessageBox.question = staticmethod(_pergunta)
        return self

    def limpar(self) -> None:
        self.titulos.clear()
        self.textos.clear()

    def __exit__(self, *_):
        QMessageBox.warning, QMessageBox.critical, QMessageBox.information, QMessageBox.question = self.orig


class _Via:
    """O que muda entre as duas telas; o roteiro (`roteiro_da_tela`) e o mesmo pra as duas."""

    nome: str
    cards_depois_de_duplicar: int

    def __init__(self, app: QApplication, cpfs: dict[str, str]):
        self.app = app
        self.cpfs = cpfs

    def abrir_tela(self, tela) -> None:
        tela.resize(1250, 800)
        tela.show()
        _ciclos(self.app)

    def card(self, banco: str) -> int:
        return next(i for i in range(self.modelo.rowCount()) if (self.modelo.item(i) or {}).get(self.chave_do_banco) == banco)

    def retangulo(self, banco: str) -> QRect:
        return self.lista.visualRect(self.modelo.index(self.card(banco)))

    def clicar_card(self, banco: str) -> QPoint:
        retangulo = self.retangulo(banco)
        ponto = QPoint(retangulo.left() + 40, retangulo.top() + 30)
        QTest.mouseClick(self.lista.viewport(), Qt.MouseButton.LeftButton, pos=ponto)
        return ponto

    def duplo_clique_no_card(self, banco: str) -> None:
        _duplo_clique(self.lista.viewport(), self.clicar_card(banco))

    def linhas_selecionadas(self) -> list[int]:
        return sorted(i.row() for i in self.lista.selectionModel().selectedIndexes())

    def bancos_dos_cards(self) -> list[str]:
        return [self.modelo.item(i)[self.chave_do_banco] for i in range(self.modelo.rowCount()) if self.modelo.item(i).get("indice") is not None]


class _Ficha(_Via):
    nome = "Ficha de Cliente"
    chave_do_banco = "titulo"
    cards_depois_de_duplicar = 4  # ALFA tinha 3 propostas

    def __init__(self, app, cpfs):
        super().__init__(app, cpfs)
        self.tela = FichaClienteScreen()
        self.abrir_tela(self.tela)
        self.tela._selecionar_por_cpf(cpfs["alfa"])
        _ciclos(app)
        self.lista, self.modelo, self.expansor = self.tela._lista_historico, self.tela._modelo_historico, self.tela._expansor
        self.botao_nova, self.botao_excluir = self.tela._botao_nova_proposta, self.tela._botao_excluir_proposta
        self.titulo_do_rascunho = "Nova proposta — ALFA CLIENTE"

    def selecionado(self) -> int | None:
        return self.tela._indice_real_proposta_selecionada()

    def recarregar(self) -> None:
        self.tela._recarregar_ficha_atual()


class _Todas(_Via):
    nome = "Todas as Propostas"
    chave_do_banco = "banco"
    cards_depois_de_duplicar = 5  # havia 4 propostas no total

    def __init__(self, app, cpfs):
        super().__init__(app, cpfs)
        self.tela = PropostasScreen()
        self.abrir_tela(self.tela)
        self.lista, self.modelo, self.expansor = self.tela._lista, self.tela._modelo, self.tela._expansor
        self.botao_nova, self.botao_excluir = self.tela._botao_nova, self.tela._botao_excluir
        self.titulo_do_rascunho = "Nova proposta — ALFA CLIENTE"  # (a duplicata leva o cliente da original)

    def selecionado(self) -> int | None:
        return self.tela._indice_real_selecionado()

    def recarregar(self) -> None:
        self.tela._carregar_dados()


def _dialogos_visiveis(app: QApplication) -> list:
    return [w for w in app.topLevelWidgets() if isinstance(w, QDialog) and w.isVisible()]


def _linhas_editaveis(arquivo: Path) -> list[dict]:
    df = bd.ler_propostas(arquivo)[bd.PROPOSTAS_COLUNAS_EDITAVEIS]
    return [{k: (None if pd.isna(v) else v) for k, v in linha_.items()} for linha_ in df.to_dict("records")]


def _sem_sobreposicao(via: _Via) -> None:
    cartoes = _cartoes(via.lista, via.modelo.rowCount())
    for i in range(len(cartoes)):
        for j in range(i + 1, len(cartoes)):
            assert not cartoes[i].intersects(cartoes[j]), f"{via.nome}: cards {i} e {j} se sobrepoem"


def roteiro_da_tela(app: QApplication, via: _Via, stubs: _Stubs, arquivo: Path) -> None:
    linha(f"4) {via.nome}: o card expande no lugar (clique só seleciona, duplo clique expande, recolher mantém a seleção)")
    expansor: ExpansorDeProposta = via.expansor
    lista = via.lista
    assert type(expansor) is ExpansorDeProposta
    assert not _dialogos_visiveis(app)

    # 1 clique so seleciona
    via.clicar_card("SANTANDER")
    assert not expansor.esta_expandido(), "1 clique nao expande nada"
    indice_santander = via.selecionado()
    assert indice_santander is not None and via.linhas_selecionadas() == [via.card("SANTANDER")]
    via.clicar_card("PORTOBANK")
    assert not expansor.esta_expandido() and via.selecionado() != indice_santander, "outro clique so troca a selecao"
    normais = {b: via.retangulo(b) for b in via.bancos_dos_cards()}

    # duplo clique expande o proprio card, empurrando os de baixo
    via.duplo_clique_no_card("PORTOBANK")
    assert expansor.esta_expandido() and expansor.indice_aberto() == via.selecionado(), "duplo clique expande o card clicado"
    assert not _dialogos_visiveis(app), "nunca abre uma janela/dialogo separado"
    f: FormularioProposta = expansor.formulario()
    assert f._modo_leitura and f._existente
    assert (f._banco.currentText(), f._equipamento.currentText(), f._status.currentText()) == ("PORTOBANK", "MESA", "Em Análise")
    assert f._valor.value() == 20000 and f._meses.value() == 12 and f._observacoes.toPlainText() == "obs MESA"
    assert f._data.texto() == "05/03/2026"
    assert len(f._botoes_copiar) == 7 and all(b.isVisible() for b in f._botoes_copiar), "copiar em cada campo"
    assert f._botao_editar.isVisible() and f._botao_duplicar.isVisible() and f._botao_recolher.isVisible()
    assert not f._botao_ok.isVisible() and not f._botao_cancelar.isVisible()
    assert lista.chave_expandida() == expansor.indice_aberto() and f.isVisible() and f.parentWidget() is lista.viewport()
    expandido = via.retangulo("PORTOBANK")
    assert expandido.height() > ALTURA_CARTAO + ESPACO and expandido.width() > normais["PORTOBANK"].width(), "o card cresceu"
    depois = {b: via.retangulo(b) for b in via.bancos_dos_cards() if b != "PORTOBANK"}
    for banco, r in depois.items():
        if via.card(banco) > via.card("PORTOBANK"):  # vem DEPOIS na lista (mesmo que estivesse na mesma linha da grade)
            assert r.top() >= expandido.bottom(), f"{banco}: nao desceu pra baixo do card expandido"
        else:
            assert r == normais[banco], f"{banco}: estava antes do expandido e nao pode se mexer"
    _sem_sobreposicao(via)
    assert via.selecionado() == expansor.indice_aberto() and via.linhas_selecionadas() == [via.card("PORTOBANK")], "o card expandido segue selecionado"
    print("OK: 1 clique só seleciona; o duplo clique EXPANDE o próprio card (sem abrir janela), com a leitura e os 7 botões de copiar; "
          "os cards de baixo descem e nenhum se sobrepõe.")

    # copiar funciona dentro do card
    f._botoes_copiar[4].click()
    assert QApplication.clipboard().text() == "PORTOBANK"

    # so um card por vez: expandir outro recolhe o anterior
    via.duplo_clique_no_card("SANTANDER")
    assert expansor.esta_expandido() and expansor.formulario() is not f and expansor.formulario()._banco.currentText() == "SANTANDER"
    assert not f.isVisible(), "o anterior foi recolhido"
    for banco in ("PORTOBANK", "HUBCRED BV"):
        assert via.retangulo(banco).height() in (ALTURA_CARTAO + ESPACO, via.retangulo(banco).height()), banco
    assert sum(1 for b in via.bancos_dos_cards() if via.retangulo(b).height() > ALTURA_CARTAO + ESPACO) == 1, "so um card expandido"
    _sem_sobreposicao(via)
    f = expansor.formulario()
    print("OK: expandir um card recolhe o que estava expandido (só um por vez).")

    # Editar mantem o card expandido; Cancel volta pra leitura sem recolher
    altura_leitura = via.retangulo("SANTANDER").height()
    f._botao_editar.click()
    assert expansor.formulario() is f and not f._modo_leitura and lista.chave_expandida() == indice_santander, "Editar mantem o card expandido"
    assert via.retangulo("SANTANDER").height() == altura_leitura, "editar nao muda a altura do card (nada pula)"
    assert f._botao_ok.isVisible() and f._botao_cancelar.isVisible() and not f._botao_editar.isVisible()
    f._observacoes.setPlainText("NAO GRAVAR")
    f._botao_cancelar.click()
    assert expansor.formulario() is f and f._modo_leitura and lista.chave_expandida() == indice_santander, "Cancel volta pra leitura sem recolher"
    assert f._observacoes.toPlainText() == "obs HAKON" and _linhas_editaveis(arquivo)[indice_santander]["OBSERVAÇÕES"] == "obs HAKON"
    f._botao_editar.click()
    QTest.keyClick(f, Qt.Key.Key_Escape)
    assert expansor.formulario() is f and f._modo_leitura, "Esc na edicao age como Cancel"
    print("OK: 'Editar' mantém o card expandido (só destrava os campos, sem mudar a altura); Cancel/Esc voltam pra leitura sem recolher.")

    # Recolher: o card volta ao tamanho normal e segue selecionado
    f._botao_recolher.click()
    assert not expansor.esta_expandido() and lista.widget_expandido() is None
    assert {b: via.retangulo(b) for b in via.bancos_dos_cards()} == normais, "recolher devolve todos os cards onde estavam"
    assert via.selecionado() == indice_santander and via.linhas_selecionadas() == [via.card("SANTANDER")], "recolher nao perde o card selecionado"
    # duplo clique no cabecalho do card expandido tambem recolhe; Esc na leitura, tambem; Enter na lista expande/recolhe
    via.duplo_clique_no_card("SANTANDER")
    assert expansor.esta_expandido()
    ponto = QPoint(via.retangulo("SANTANDER").left() + 40, via.retangulo("SANTANDER").top() + 15)
    _duplo_clique(lista.viewport(), ponto)
    assert not expansor.esta_expandido(), "duplo clique no cabecalho do card expandido recolhe"
    via.duplo_clique_no_card("SANTANDER")
    QTest.keyClick(expansor.formulario(), Qt.Key.Key_Escape)
    assert not expansor.esta_expandido() and via.selecionado() == indice_santander, "Esc na leitura recolhe"
    lista.setFocus()
    QTest.keyClick(lista, Qt.Key.Key_Return)
    assert expansor.indice_aberto() == indice_santander, "Enter no card selecionado expande"
    QTest.keyClick(expansor.formulario(), Qt.Key.Key_Return)  # o Enter, com o foco no formulario, aperta o botao padrao (Recolher)
    assert not expansor.esta_expandido(), "Enter na leitura aperta Recolher"
    # um duplo clique num espaco vazio do formulario nao recolhe (o formulario engole o clique)
    via.duplo_clique_no_card("SANTANDER")
    f = expansor.formulario()
    for tipo in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
        ev = QMouseEvent(tipo, QPointF(5, f.height() - 5), QPointF(f.mapToGlobal(QPoint(5, f.height() - 5))),
                         Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        ev.ignore()
        f.mousePressEvent(ev) if tipo == QEvent.Type.MouseButtonPress else f.mouseDoubleClickEvent(ev)
        assert ev.isAccepted(), "o formulario aceita cliques (nao deixa subir pra lista)"
    assert expansor.esta_expandido()
    f._botao_recolher.click()
    print("OK: recolher devolve todos os cards e mantém a seleção; o cabeçalho (duplo clique), Esc e Enter também recolhem; "
          "clicar num espaço vazio do formulário não faz nada.")

    # a roda do mouse sobre um campo SEM foco rola a lista (nao troca o valor)
    via.duplo_clique_no_card("SANTANDER")
    f = expansor.formulario()
    f._botao_editar.click()
    f._botao_recolher.setFocus()
    meses_antes = f._meses.value()
    roda = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120), Qt.MouseButton.NoButton,
                       Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    for campo in (f._meses, f._valor, f._banco, f._status):
        roda.ignore()
        QApplication.sendEvent(campo, roda)
        assert not roda.isAccepted(), "a roda sobre um campo sem foco nao e consumida (sobe pra lista rolar)"
    assert f._meses.value() == meses_antes
    f._botao_cancelar.click()
    f._botao_recolher.click()
    print("OK: a roda do mouse sobre um campo/combo sem foco não muda o valor (o evento sobe, e a lista rola).")

    # editar e gravar: recarrega, o card volta em leitura (ja com o que foi gravado) e segue selecionado
    via.duplo_clique_no_card("SANTANDER")
    f = expansor.formulario()
    f._botao_editar.click()
    f._status.setCurrentText("Aprovado")
    f._observacoes.setPlainText("editado no card")
    f._botao_ok.click()
    linhas = _linhas_editaveis(arquivo)
    assert linhas[indice_santander]["STATUS"] == "Aprovado" and linhas[indice_santander]["OBSERVAÇÕES"] == "editado no card"
    novo = expansor.formulario()
    assert novo is not None and novo is not f and novo._modo_leitura and expansor.indice_aberto() == indice_santander
    assert novo._status.currentText() == "Aprovado" and novo._observacoes.toPlainText() == "editado no card", "leitura ja com o que foi gravado"
    assert via.selecionado() == indice_santander, "o card editado segue selecionado"
    item = via.modelo.item(via.card("SANTANDER"))
    assert item["status"] == "Aprovado", "o cabecalho do card ja mostra o status novo"
    novo._botao_recolher.click()
    propostas_mod.atualizar_proposta(indice_santander, {"STATUS": "Negado", "OBSERVAÇÕES": "obs HAKON"})  # volta ao estado original
    via.recarregar()
    _ciclos(app)
    print("OK: editar e gravar grava, o card volta em leitura já com o novo valor (sem recolher) e segue selecionado.")

    # edicao NAO salva: trocar de card pergunta antes de descartar
    stubs.limpar()
    via.duplo_clique_no_card("SANTANDER")
    f = expansor.formulario()
    f._botao_editar.click()
    f._banco.setCurrentText("OUTRO BANCO")
    assert f.tem_alteracoes()
    stubs.resposta = QMessageBox.StandardButton.No
    via.duplo_clique_no_card("PORTOBANK")
    assert stubs.titulos == ["Alterações não salvas"], stubs.titulos
    assert expansor.formulario() is f and not f._modo_leitura and f._banco.currentText() == "OUTRO BANCO", "Nao: segue editando, sem perder nada"
    stubs.resposta = QMessageBox.StandardButton.Yes
    via.duplo_clique_no_card("PORTOBANK")
    assert expansor.formulario() is not f and expansor.formulario()._banco.currentText() == "PORTOBANK", "Sim: descarta e expande o outro"
    assert _linhas_editaveis(arquivo)[indice_santander]["BANCO"] == "SANTANDER", "nada foi gravado"
    expansor.formulario()._botao_recolher.click()
    print("OK: trocar de card com edição não salva pergunta; 'Não' continua editando, 'Sim' descarta e expande o outro.")

    # o card expandido em edicao nao recolhe com o duplo clique no cabecalho
    via.duplo_clique_no_card("SANTANDER")
    f = expansor.formulario()
    f._botao_editar.click()
    ret = via.retangulo("SANTANDER")
    _duplo_clique(lista.viewport(), QPoint(ret.left() + 40, ret.top() + 15))
    assert expansor.formulario() is f and not f._modo_leitura, "em edicao, o duplo clique no cabecalho nao recolhe"
    f._botao_cancelar.click()
    f._botao_recolher.click()

    # ---- Duplicar -------------------------------------------------------------------------
    linha(f"4b) {via.nome}: Duplicar proposta (o card 'Nova proposta' no topo, preenchido)")
    stubs.limpar()
    via.duplo_clique_no_card("SANTANDER")
    f = expansor.formulario()
    antes = _linhas_editaveis(arquivo)
    f._botao_duplicar.click()
    n = expansor.formulario()
    modelo = via.modelo
    assert n is not f and expansor.eh_rascunho() and modelo.tem_rascunho() and modelo.eh_rascunho(0)
    assert lista.chave_expandida() == RASCUNHO and lista.linha_expandida() == 0, "o card novo abre no topo, expandido"
    assert not n._existente and not n._modo_leitura, "a duplicata e uma proposta NOVA, em edicao"
    assert modelo.item(0)["titulo"] == via.titulo_do_rascunho, modelo.item(0)["titulo"]
    assert (n._equipamento.currentText(), n._valor.value(), n._meses.value(), n._observacoes.toPlainText()) == ("HAKON", 75000, 36, "obs HAKON")
    assert n._data.texto() == QDate.currentDate().toString("dd/MM/yyyy"), "a data e a de hoje, nao a da original"
    assert n._banco.currentText() == "", "o banco fica em branco pra escolher o novo"
    assert n._status.currentText() == "Em Análise", "o status volta pra Em Análise (a original era Negado)"
    foco = QApplication.focusWidget()
    assert foco is not None and (foco is n._banco or n._banco.isAncestorOf(foco)), "o foco cai no banco: e o que falta escolher"
    assert _linhas_editaveis(arquivo) == antes, "duplicar so abre o formulario: nada e gravado ainda"
    assert not n._botao_duplicar.isVisible() and not n._botao_editar.isVisible() and n._botao_ok.isVisible()
    assert not f.isVisible() and sum(1 for i in range(modelo.rowCount()) if lista.visualRect(modelo.index(i)).height() > ALTURA_CARTAO + ESPACO) == 1, \
        "a original voltou ao tamanho normal: so o card novo esta expandido"
    _sem_sobreposicao(via)
    print("OK: 'Duplicar' põe o card 'Nova proposta' no topo, expandido e preenchido (cliente, equipamento, valor, meses, observações), "
          "com data de hoje, banco em branco (com o foco) e status 'Em Análise'; a original recolhe e nada é gravado.")

    # Cancel volta pra leitura da ORIGINAL
    n._botao_cancelar.click()
    r = expansor.formulario()
    assert not modelo.tem_rascunho() and r is not n and r._modo_leitura and r._existente and expansor.indice_aberto() == indice_santander
    assert (r._banco.currentText(), r._status.currentText(), r._valor.value()) == ("SANTANDER", "Negado", 75000)
    assert _linhas_editaveis(arquivo) == antes
    r._botao_duplicar.click()
    QTest.keyClick(expansor.formulario(), Qt.Key.Key_Escape)
    assert expansor.indice_aberto() == indice_santander and expansor.formulario()._modo_leitura, "Esc na duplicata tambem volta pra original"
    print("OK: Cancel (e Esc) na duplicata tira o card novo e reabre a leitura da proposta original.")

    # sem escolher o banco o app pergunta (regra que ja existia); 'Nao' nao grava
    expansor.formulario()._botao_duplicar.click()
    n = expansor.formulario()
    stubs.resposta = QMessageBox.StandardButton.No
    stubs.limpar()
    n._salvar()
    assert stubs.titulos == ["Campo recomendado em branco"] and expansor.eh_rascunho() and _linhas_editaveis(arquivo) == antes
    stubs.resposta = QMessageBox.StandardButton.Yes

    # escolher o banco e salvar: proposta NOVA e independente; o card novo aparece e fica selecionado
    n._banco.setCurrentText("HUBCRED BV 2")
    n._botao_ok.click()
    assert not expansor.esta_expandido() and not modelo.tem_rascunho(), "gravar tira o card 'Nova proposta'"
    depois = _linhas_editaveis(arquivo)
    assert len(depois) == len(antes) + 1 and depois[:-1] == antes, "as propostas que já existiam ficam exatamente como estavam"
    nova = depois[-1]
    assert apenas_digitos(nova["CPF"]) == apenas_digitos(via.cpfs["alfa"]), "o mesmo cliente"
    assert {**nova, "CPF": None} == {
        "DATA": pd.Timestamp(date.today()), "CPF": None, "VALOR (R$)": 75000.0, "MESES": 36.0,
        "EQUIPAMENTO": "HAKON", "BANCO": "HUBCRED BV 2", "STATUS": "Em Análise", "OBSERVAÇÕES": "obs HAKON",
    }, nova
    assert depois[indice_santander]["BANCO"] == "SANTANDER" and depois[indice_santander]["STATUS"] == "Negado", "a original segue no historico"
    assert via.selecionado() == len(depois) - 1, "o card da proposta nova fica selecionado"
    assert "HUBCRED BV 2" in via.bancos_dos_cards() and "SANTANDER" in via.bancos_dos_cards(), "os dois aparecem"
    assert len(via.bancos_dos_cards()) == via.cards_depois_de_duplicar, via.bancos_dos_cards()
    print("OK: salvar a duplicata cria uma proposta NOVA (banco escolhido, hoje, Em Análise), que aparece na lista e fica selecionada; "
          "a original e as outras ficam exatamente iguais.")

    # ---- + Nova Proposta --------------------------------------------------------------------
    stubs.limpar()
    via.botao_nova.click()
    n = expansor.formulario()
    assert expansor.eh_rascunho() and modelo.eh_rascunho(0) and not n._existente and not n._modo_leitura
    assert n._botao_ok.isVisible() and not n._botao_duplicar.isVisible()
    assert (n._cliente_combo is not None) == (via.nome == "Todas as Propostas"), "avulsa (com campo de cliente) so em Todas as Propostas"
    n._botao_cancelar.click()
    assert not expansor.esta_expandido() and not modelo.tem_rascunho(), "Cancel numa proposta nova (sem leitura pra onde voltar) so a tira"
    via.botao_nova.click()
    QTest.keyClick(expansor.formulario(), Qt.Key.Key_Escape)
    assert not expansor.esta_expandido()
    # nova proposta com edicao no meio: outro '+ Nova Proposta' pergunta antes de recomecar
    via.botao_nova.click()
    expansor.formulario()._valor.setValue(123)
    stubs.resposta = QMessageBox.StandardButton.No
    stubs.limpar()
    via.botao_nova.click()
    assert stubs.titulos == ["Alterações não salvas"] and expansor.formulario()._valor.value() == 123, "'Não': segue no que estava digitando"
    stubs.resposta = QMessageBox.StandardButton.Yes
    expansor.formulario()._botao_cancelar.click()
    print("OK: '+ Nova Proposta' abre o card 'Nova proposta' no topo; Cancel/Esc só o tiram; abrir outro com edição não salva pergunta.")

    # ---- Excluir ----------------------------------------------------------------------------
    linha(f"4c) {via.nome}: Excluir age sobre o card selecionado (mesma confirmação nas duas telas)")
    stubs.limpar()
    total = len(_linhas_editaveis(arquivo))
    via.clicar_card("HUBCRED BV 2")  # a duplicata que acabou de ser criada (1 clique so seleciona)
    indice_excluido = via.selecionado()
    via.duplo_clique_no_card("PORTOBANK")  # ha outro card expandido: excluir recolhe tudo
    via.clicar_card("HUBCRED BV 2")
    via.botao_excluir.click()
    assert stubs.titulos[-1] == "Excluir proposta", stubs.titulos
    assert "Tem certeza que deseja excluir a proposta de 'ALFA CLIENTE' (HUBCRED BV 2, R$ 75.000,00)? Essa ação não pode ser desfeita." == stubs.textos[-1], stubs.textos[-1]
    assert len(_linhas_editaveis(arquivo)) == total - 1 and not expansor.esta_expandido()
    assert "HUBCRED BV 2" not in via.bancos_dos_cards() and via.selecionado() is None, "excluida: some, e nenhum card fica selecionado"
    stubs.limpar()
    via.botao_excluir.click()
    assert "Clique em um card" in stubs.textos[-1] and len(_linhas_editaveis(arquivo)) == total - 1, "sem selecao: avisa em vez de excluir"
    # 'Nao' na confirmacao: nao exclui
    via.clicar_card("PORTOBANK")
    stubs.resposta = QMessageBox.StandardButton.No
    via.botao_excluir.click()
    assert len(_linhas_editaveis(arquivo)) == total - 1
    stubs.resposta = QMessageBox.StandardButton.Yes
    # excluir com edicao nao salva num card: pergunta antes (e 'Nao' cancela tudo)
    via.duplo_clique_no_card("SANTANDER")
    f = expansor.formulario()
    f._botao_editar.click()
    f._observacoes.setPlainText("digitado e nao salvo")
    stubs.limpar()
    stubs.resposta = QMessageBox.StandardButton.No
    via.clicar_card("PORTOBANK")
    via.botao_excluir.click()
    assert stubs.titulos == ["Alterações não salvas"] and expansor.formulario() is f, stubs.titulos
    assert len(_linhas_editaveis(arquivo)) == total - 1, "nada excluido"
    stubs.resposta = QMessageBox.StandardButton.Yes
    f._botao_cancelar.click()
    f._botao_recolher.click()
    print("OK: Excluir age sobre o card selecionado (1 clique), com a mesma confirmação nas duas telas; recolhe o que estava expandido; "
          "sem seleção avisa; 'Não' não exclui; edição não salva pergunta antes.")

    # ---- a posicao ficou velha: nao grava por cima de outra ----------------------------------------
    via.duplo_clique_no_card("PORTOBANK")
    f = expansor.formulario()
    indice_portobank = expansor.indice_aberto()
    f._botao_editar.click()
    f._observacoes.setPlainText("o que eu digitei")
    propostas_mod.atualizar_proposta(indice_portobank, {"OBSERVAÇÕES": "mudou em outra tela"})  # "outra tela" mexeu
    stubs.limpar()
    f._botao_ok.click()
    assert stubs.titulos == ["Não foi possível salvar"] and "alterada ou excluída" in stubs.textos[-1], stubs.titulos
    assert expansor.formulario() is f and not f._modo_leitura, "recusou e o card segue em edicao (nada se perdeu)"
    assert _linhas_editaveis(arquivo)[indice_portobank]["OBSERVAÇÕES"] == "mudou em outra tela", "o que a outra tela gravou fica"
    f._botao_cancelar.click()
    f._botao_recolher.click()
    # excluir essa mesma proposta (que a tela ainda mostra desatualizada) tambem e recusado: nao apaga outra por engano
    via.clicar_card("PORTOBANK")
    stubs.limpar()
    antes_excluir = len(_linhas_editaveis(arquivo))
    via.botao_excluir.click()
    assert stubs.titulos[-1] == "Não foi possível excluir" and "alterada ou excluída" in stubs.textos[-1], (stubs.titulos, stubs.textos)
    assert len(_linhas_editaveis(arquivo)) == antes_excluir, "nada foi excluido"
    via.recarregar()  # a tela le de novo o que a outra tela gravou
    _ciclos(app)
    print("OK: se a proposta mudou desde que o card abriu, gravar e excluir são recusados com aviso (nada é sobrescrito nem apagado por engano).")

    # ---- a lista muda com um card expandido --------------------------------------------------------
    if via.nome == "Todas as Propostas":
        stubs.limpar()
        via.duplo_clique_no_card("SMART")
        f = expansor.formulario()
        f._botao_editar.click()
        f._observacoes.setPlainText("editando SMART")
        via.tela._busca.setText("PORTOBANK")  # o filtro tira a proposta expandida da lista
        _ciclos(app)
        assert not expansor.esta_expandido() and via.tela._lista.widget_expandido() is None
        assert stubs.titulos == ["Alterações descartadas"], stubs.titulos
        via.tela._busca.setText("")
        via.duplo_clique_no_card("SMART")
        via.tela._busca.setText("SMART")  # a proposta segue na lista: o card expandido continua
        _ciclos(app)
        assert expansor.esta_expandido() and expansor.formulario()._banco.currentText() == "SMART"
        via.tela._busca.setText("")
        _ciclos(app)
        assert expansor.esta_expandido(), "filtrar/limpar a busca com o card ainda na lista nao o recolhe"
        expansor.formulario()._botao_recolher.click()
    else:
        stubs.limpar()
        via.duplo_clique_no_card("SANTANDER")
        f = expansor.formulario()
        f._botao_editar.click()
        f._observacoes.setPlainText("editando SANTANDER")
        via.tela._selecionar_por_cpf(via.cpfs["beta"])  # outro cliente: o card expandido era da ALFA
        _ciclos(app)
        assert not expansor.esta_expandido() and stubs.titulos == ["Alterações descartadas"], stubs.titulos
        assert via.tela._nome_label.text() == "BETA AVALISTA" and via.modelo.total() == 1 and not via.modelo.tem_rascunho()
        via.tela._selecionar_por_cpf(via.cpfs["alfa"])
        _ciclos(app)
        # o card 'Nova proposta' e DO cliente: trocar de cliente o descarta (senao apareceria no historico do outro)
        stubs.limpar()
        via.botao_nova.click()
        expansor.formulario()._valor.setValue(999)
        via.tela._selecionar_por_cpf(via.cpfs["beta"])
        _ciclos(app)
        assert not expansor.esta_expandido() and not via.modelo.tem_rascunho() and via.modelo.total() == 1, \
            "o card 'Nova proposta' era da ALFA: nao pode aparecer no historico da BETA"
        assert stubs.titulos == ["Alterações descartadas"], stubs.titulos
        via.tela._selecionar_por_cpf(via.cpfs["alfa"])
        _ciclos(app)
        # cliente SEM propostas: o card 'Nova proposta' aparece mesmo assim (o historico nao pode ficar escondido)
        via.tela._selecionar_por_cpf(via.cpfs["gama"])
        _ciclos(app)
        assert via.modelo.total() == 0 and via.tela._contentor_historico.isHidden() and not via.tela._historico_vazio.isHidden()
        via.botao_nova.click()
        assert expansor.eh_rascunho() and not via.tela._contentor_historico.isHidden() and via.tela._historico_vazio.isHidden(), \
            "com o card 'Nova proposta', o historico aparece (mesmo sem propostas)"
        n = expansor.formulario()
        n._valor.setValue(4321)
        n._equipamento.setCurrentText("Equip Novo")
        n._banco.setCurrentText("Banco Novo")
        n._botao_ok.click()
        assert via.modelo.total() == 1 and via.modelo.item(0)["titulo"] == "Banco Novo" and not expansor.esta_expandido()
        assert via.tela._contentor_historico.isVisible() and via.tela._historico_vazio.isHidden()
        via.tela._selecionar_por_cpf(via.cpfs["alfa"])
        _ciclos(app)
    print("OK: filtro que tira a proposta expandida da lista (ou outro cliente) descarta o card e avisa se havia edição; "
          "se ela continua na lista, o card continua expandido." if via.nome == "Todas as Propostas" else
          "OK: trocar de cliente descarta o card expandido (avisando se havia edição); um cliente sem propostas mostra o card 'Nova proposta'.")
    assert not [t for t in stubs.titulos if t.startswith("Erro")], stubs.titulos


def testar_telas(app: QApplication) -> None:
    for classe in (_Ficha, _Todas):
        pasta = Path(tempfile.mkdtemp(prefix="_smoke_cartao_"))
        arquivo = pasta / "controle.xlsx"
        _criar_planilha_vazia(arquivo)
        for modulo in (clientes_mod, propostas_mod, vendedores_mod, equipamentos_mod):
            modulo.CAMINHO_XLSX = arquivo
        try:
            with _Stubs() as stubs:
                cpfs = _cadastrar()
                via = classe(app, cpfs)
                try:
                    roteiro_da_tela(app, via, stubs, arquivo)
                finally:
                    via.tela.close()
        finally:
            for modulo in (clientes_mod, propostas_mod, vendedores_mod, equipamentos_mod):
                modulo.CAMINHO_XLSX = config.CAMINHO_XLSX
            shutil.rmtree(pasta, ignore_errors=True)


# ---------------------------------------------------------------------------
# 5) a grade compacta do formulario, o vendedor e o que foi removido

def testar_grade_do_formulario(app: QApplication) -> None:
    linha("3) Formulário em grade: campos lado a lado, só as Observações na largura toda")
    f = FormularioProposta("52998224725", "ALFA CLIENTE", proposta={
        "DATA": pd.Timestamp(2026, 3, 1), "CPF": "52998224725", "VALOR (R$)": 75000.0, "MESES": 36.0, "EQUIPAMENTO": "HAKON",
        "BANCO": "SANTANDER", "STATUS": "Negado", "OBSERVAÇÕES": "obs"}, indice=0)
    f.resize(900, 300)
    f.show()
    _ciclos(app)

    def celula(campo):
        w = campo
        while w.parentWidget() is not f and w.parentWidget() is not None:
            w = w.parentWidget()
        return w

    topo = lambda c: celula(c).mapTo(f, QPoint(0, 0)).y()  # noqa: E731
    esquerda = lambda c: celula(c).mapTo(f, QPoint(0, 0)).x()  # noqa: E731
    assert topo(f._data) == topo(f._meses) == topo(f._status), "Data, Meses e Status na mesma linha"
    assert topo(f._valor) == topo(f._equipamento) == topo(f._banco), "Valor, Equipamento e Banco na mesma linha"
    assert topo(f._data) < topo(f._valor) < topo(f._observacoes), "as linhas seguem a ordem"
    assert esquerda(f._data) < esquerda(f._meses) < esquerda(f._status) and esquerda(f._valor) < esquerda(f._equipamento) < esquerda(f._banco)
    assert celula(f._observacoes).width() == f.width(), "as observações ocupam a largura toda"
    for campo, maximo in ((f._data, 190), (f._meses, 120), (f._status, 250), (f._valor, 210), (f._banco, 260)):
        assert celula(campo).width() <= maximo, f"largura do campo: {celula(campo).width()} > {maximo} (so o que o conteudo pede)"
    assert celula(f._equipamento).width() > celula(f._valor).width(), "o equipamento (nome longo) fica com o resto da largura"
    assert f.sizeHint().height() <= 300, f"formulario compacto (menos alto): {f.sizeHint().height()} px"
    largura_minima = f.minimumSizeHint().width()
    assert largura_minima <= 460, f"a grade cabe numa tela estreita: precisa de {largura_minima} px"
    print(f"OK: 3 linhas de campos (Data/Meses/Status, Valor/Equipamento/Banco, Observações inteira), cada um com a largura do "
          f"conteúdo; formulário com {f.sizeHint().height()} px de altura e a grade pede no mínimo {largura_minima} px de largura.")
    f.close()


def testar_vendedor(app: QApplication) -> None:
    linha("5) VENDEDOR só lê: expande o card, sem Editar nem Duplicar")
    pasta = Path(tempfile.mkdtemp(prefix="_smoke_cartao_v_"))
    arquivo = pasta / "controle.xlsx"
    _criar_planilha_vazia(arquivo)
    for modulo in (clientes_mod, propostas_mod, vendedores_mod, equipamentos_mod):
        modulo.CAMINHO_XLSX = arquivo
    fontes = (clientes_mod._ler_da_fonte_ativa, propostas_mod._ler_da_fonte_ativa, equipamentos_mod.listar_nomes_equipamento)
    try:
        with _Stubs():
            cpfs = _cadastrar()
            sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_VENDEDOR, nome_usuario="ANA"))
            clientes_mod._ler_da_fonte_ativa = lambda: sessao_mod.filtrar_por_vendedor_logado(bd.ler_clientes(arquivo))
            propostas_mod._ler_da_fonte_ativa = lambda: sessao_mod.filtrar_por_vendedor_logado(bd.ler_propostas(arquivo))

            def _sem_arquivo_local():
                raise FileNotFoundError("a maquina do vendedor nao tem o .xlsx local")

            equipamentos_mod.listar_nomes_equipamento = _sem_arquivo_local
            try:
                for classe in (_Ficha, _Todas):
                    via = classe(app, cpfs)
                    try:
                        assert set(via.bancos_dos_cards()) == {"SANTANDER", "PORTOBANK", "HUBCRED BV"}, (via.nome, via.bancos_dos_cards())
                        via.duplo_clique_no_card("SANTANDER")
                        assert via.expansor.esta_expandido(), f"{via.nome}: o vendedor expande a proposta"
                        f = via.expansor.formulario()
                        assert f._modo_leitura and f._banco.currentText() == "SANTANDER" and len(f._botoes_copiar) == 7
                        assert f._botao_editar.isHidden() and f._botao_duplicar.isHidden(), f"{via.nome}: vendedor nunca edita nem duplica"
                        assert via.botao_nova.isHidden() and via.botao_excluir.isHidden()
                        f._salvar()  # mesmo por codigo: em leitura nao grava
                        f.duplicacao_pedida.emit()  # nem com o sinal emitido por fora: o expansor recusa (2a trava)
                        assert via.expansor.formulario() is f and f._modo_leitura and not via.modelo.tem_rascunho()
                        f._botao_recolher.click()
                        assert not via.expansor.esta_expandido()
                    finally:
                        via.tela.close()
            finally:
                sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
            print("OK: o vendedor expande o card em leitura (com copiar) nas duas telas, sem 'Editar' nem 'Duplicar', e o expansor recusa duplicar.")
    finally:
        (clientes_mod._ler_da_fonte_ativa, propostas_mod._ler_da_fonte_ativa, equipamentos_mod.listar_nomes_equipamento) = fontes
        for modulo in (clientes_mod, propostas_mod, vendedores_mod, equipamentos_mod):
            modulo.CAMINHO_XLSX = config.CAMINHO_XLSX
        shutil.rmtree(pasta, ignore_errors=True)


def testar_o_que_saiu() -> None:
    linha("6) O painel lateral e o popup antigos não existem mais")
    for modulo in ("desktop.widgets.painel_lateral", "desktop.widgets.painel_proposta", "desktop.dialogs.proposta_dialog"):
        try:
            importlib.import_module(modulo)
        except ModuleNotFoundError:
            continue
        raise AssertionError(f"{modulo} nao deveria existir: as duas telas usam o card expansivel")
    print("OK: sem painel lateral e sem PropostaDialog: nenhuma tela abre a proposta fora do card.")


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
    try:
        testar_modelo_com_rascunho()
        testar_geometria_da_lista(app)
        testar_altura_automatica_e_rolagem(app)
        testar_cores_do_card_expandido(app)
        testar_grade_do_formulario(app)
        testar_telas(app)
        testar_vendedor(app)
        testar_o_que_saiu()
        linha("TUDO OK")
    finally:
        sessao_mod.encerrar()


if __name__ == "__main__":
    main()
