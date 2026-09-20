"""Testa a Ficha de Cliente com CARDS: (1) a lista de clientes (nome em destaque,
Tipo num badge colorido de cores fora das dos status, vendedor, bolinha "Em aberto"
pra quem tem proposta nao encerrada, SEM o CPF/CNPJ no card, selecao por clique
unico com destaque) e (2) o historico de propostas (banco em destaque, "Equipamento .
Valor", status com as mesmas cores de "Todas as Propostas", tempo e data; um clique
seleciona, o duplo clique abre). Dados FICTICIOS, numa planilha temporaria.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_ficha_cards.py
"""

from __future__ import annotations

import math
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if Path(r"C:\Windows\Fonts").exists():  # sem tela o Qt nao acha fontes (todo caractere vira o mesmo quadradinho)
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl
import pandas as pd
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QMouseEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

try:  # o verificador de modelos do proprio Qt
    from PySide6.QtTest import QAbstractItemModelTester
except ImportError:  # pragma: no cover
    QAbstractItemModelTester = None

import config
config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
from core import clientes as clientes_mod
from core import data_store as bd
from core import equipamentos as equipamentos_mod
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import vendedores as vendedores_mod
from core.formatting import formatar_equipamento_e_valor
from core.validators import _digito_verificador_cpf, apenas_digitos
from desktop import settings as settings_mod
from desktop.screens import propostas_screen as propostas_screen_mod
from desktop.screens.ficha_cliente_screen import FichaClienteScreen, _montar_item_historico
from desktop.theme import COR_EM_ABERTO, CORES_STATUS, CORES_TIPO, PALETAS, TEMA_CLARO, TEMA_ESCURO, build_stylesheet
from desktop.widgets.lista_cartoes import ALTURA_CARTAO, chave_cor_status
from desktop.widgets.lista_clientes import (
    ALTURA_CARTAO_CLIENTE,
    ListaClientes,
    ModeloClientes,
    chave_cor_tipo,
    rotulo_do_tipo,
    textos_do_cliente,
)
from desktop.widgets.expansor_proposta import ExpansorDeProposta
from desktop.widgets.formulario_proposta import FormularioProposta


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _ciclos(app: QApplication, n: int = 5) -> None:
    for _ in range(n):
        app.processEvents()


def _cpf(n: int) -> str:
    base = f"{400000000 + n:09d}"
    return base + _digito_verificador_cpf(base)


# ---------------------------------------------------------------------------
# cores (CIE Lab e WCAG)

def _rgb(hex_: str) -> tuple[int, int, int]:
    h = hex_.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _linear(v: int) -> float:
    v /= 255
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _lab(hex_: str) -> tuple[float, float, float]:
    r, g, b = map(_linear, _rgb(hex_))
    x, y, z = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047, 0.2126 * r + 0.7152 * g + 0.0722 * b, (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116  # noqa: E731
    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def _distancia(a: str, b: str) -> float:
    return math.dist(_lab(a), _lab(b))


def _luminancia(hex_: str) -> float:
    r, g, b = map(_linear, _rgb(hex_))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contraste(a: str, b: str) -> float:
    claro, escuro = sorted((_luminancia(a), _luminancia(b)), reverse=True)
    return (claro + 0.05) / (escuro + 0.05)


# ---------------------------------------------------------------------------
# 1) regras (core)

def testar_regras() -> None:
    linha("1) Regras: proposta em aberto e a linha 'Equipamento · Valor'")
    for status in ("Em Análise", "Pré-aprovado", "Aprovado", "APROVADO", "Nota Fiscal Anexada", "Garantia Assinada",
                   "", "   ", None, "Status Novo"):
        assert propostas_mod.esta_em_aberto(status), f"{status!r} não está encerrada: é em aberto"
    for status in ("Efetivado", "EFETIVADO", " efetivada ", "Negado", "NEGADA", "Reprovado", "cancelado"):
        assert not propostas_mod.esta_em_aberto(status), f"{status!r} é um desfecho final"
    print("OK: em aberto = tudo que não é desfecho final (Aprovado segue em aberto até virar Efetivado; sem status também).")

    def com_propostas(linhas: list[tuple[str, str]]) -> pd.DataFrame:
        return pd.DataFrame(linhas, columns=["CPF", "STATUS"])

    original = propostas_mod._ler_da_fonte_ativa
    try:
        propostas_mod._ler_da_fonte_ativa = lambda: com_propostas([
            ("111.444.777-35", "Em Análise"),  # o mesmo CPF com pontuacao diferente nas duas propostas
            ("11144477735", "Negado"),
            ("529.982.247-25", "Efetivado"),  # so desfechos finais: nao conta
            ("529.982.247-25", "Negado"),
            ("390.533.447-05", "Aprovado"),
            ("", "Em Análise"),  # sem CPF: ignorada
        ])
        assert propostas_mod.cpfs_com_proposta_em_aberto() == {"11144477735", "39053344705"}
        propostas_mod._ler_da_fonte_ativa = lambda: com_propostas([])
        assert propostas_mod.cpfs_com_proposta_em_aberto() == set(), "sem nenhuma proposta: conjunto vazio (nao um erro de coluna)"
        propostas_mod._ler_da_fonte_ativa = lambda: com_propostas([("529.982.247-25", "Negado")])
        assert propostas_mod.cpfs_com_proposta_em_aberto() == set(), "so propostas encerradas: ninguém em aberto"
    finally:
        propostas_mod._ler_da_fonte_ativa = original
    print("OK: CPFs só com dígitos (pontuação diferente conta como o mesmo cliente); uma aberta basta; "
          "planilha sem proposta nenhuma devolve conjunto vazio.")

    nan = float("nan")
    assert formatar_equipamento_e_valor("HAKON", 75000.0) == "HAKON · R$ 75.000,00"
    assert formatar_equipamento_e_valor("  HAKON ", nan) == "HAKON"
    assert formatar_equipamento_e_valor("", 1500.5) == "R$ 1.500,50"
    assert formatar_equipamento_e_valor(None, None) == "—" and formatar_equipamento_e_valor("", nan) == "—"
    print("OK: 'HAKON · R$ 75.000,00'; o que falta fica de fora; sem nenhum dos dois, '—' (a linha nunca some).")


def testar_cores_do_tipo() -> None:
    linha("2) Cores do Tipo (Cliente/Avalista) e da bolinha: diferentes das dos status")
    for tema in (TEMA_ESCURO, TEMA_CLARO):
        status = CORES_STATUS[tema]
        blocos_de_status = {f"{k}.{c}": v[c] for k, v in status.items() for c in ("faixa", "fundo")}
        blocos_de_status["destaque"] = PALETAS[tema]["destaque"]
        tipos = CORES_TIPO[tema]
        assert set(tipos) == {"cliente", "avalista", "neutro"}
        for chave, cor in tipos.items():
            assert _contraste(cor["texto"], cor["fundo"]) >= 4.5, f"{tema}/{chave}: texto do badge sem contraste"
        for chave in ("cliente", "avalista"):
            for nome, cor_status in blocos_de_status.items():
                distancia = _distancia(tipos[chave]["fundo"], cor_status)
                assert distancia >= 25, f"{tema}: Tipo '{chave}' ({tipos[chave]['fundo']}) parece com {nome} ({cor_status}): ΔE={distancia:.1f}"
        assert _distancia(tipos["cliente"]["fundo"], tipos["avalista"]["fundo"]) >= 25, f"{tema}: Cliente e Avalista se confundem"
        bolinha = COR_EM_ABERTO[tema]
        assert _contraste(bolinha, PALETAS[tema]["bg_card"]) >= 3, f"{tema}: bolinha 'Em aberto' some no fundo do card"
        for nome, cor in {**blocos_de_status, "cliente": tipos["cliente"]["fundo"], "avalista": tipos["avalista"]["fundo"]}.items():
            assert _distancia(bolinha, cor) >= 25, f"{tema}: a bolinha parece com {nome} ({cor})"
    print("OK: nos dois temas, Cliente (índigo/azul-marinho) e Avalista (fúcsia) ficam a ΔE ≥ 25 de qualquer cor de status "
          "(faixa/fundo) e entre si, com texto ≥ 4,5:1; a bolinha (lima) também, e com contraste ≥ 3:1 no card.")
    assert chave_cor_tipo("Cliente") == "cliente" and chave_cor_tipo(" AVALISTA ") == "avalista"
    assert chave_cor_tipo("") == "neutro" and chave_cor_tipo("Outro") == "neutro" and chave_cor_tipo(None) == "neutro"
    print("OK: 'Cliente'/'Avalista' (sem diferenciar maiúsculas) têm cor própria; vazio ou desconhecido = cinza.")


# ---------------------------------------------------------------------------
# 3) o card de cliente (widget)

ITENS = [
    {"cpf": "111.444.777-35", "cliente": "ALFA CLIENTE", "tipo": "Cliente", "vendedor": "ANA"},
    {"cpf": "529.982.247-25", "cliente": "BETA AVALISTA", "tipo": "Avalista", "vendedor": "BIA"},
    {"cpf": "390.533.447-05", "cliente": "SEM TIPO NEM VENDEDOR", "tipo": "", "vendedor": ""},
]


POUCOS = 25  # pixels: o "quase nenhum" do antialiasing; um badge de verdade tem centenas


def _pontos_da_cor(imagem, retangulo, cor_hex: str, tolerancia: int = 6) -> int:
    alvo = _rgb(cor_hex)
    n = 0
    for x in range(max(0, retangulo.left()), min(imagem.width(), retangulo.right() + 1)):
        for y in range(max(0, retangulo.top()), min(imagem.height(), retangulo.bottom() + 1)):
            c = imagem.pixelColor(x, y)
            if abs(c.red() - alvo[0]) <= tolerancia and abs(c.green() - alvo[1]) <= tolerancia and abs(c.blue() - alvo[2]) <= tolerancia:
                n += 1
    return n


def _clicar_no_card(lista: ListaClientes, linha_: int) -> QPoint:
    retangulo = lista.visualRect(lista.model().index(linha_))
    ponto = QPoint(retangulo.left() + 30, retangulo.top() + 30)
    QTest.mouseClick(lista.viewport(), Qt.MouseButton.LeftButton, pos=ponto)
    return ponto


def testar_card_de_cliente(app: QApplication) -> None:
    linha("3) O card de cliente: sem CPF, badge do Tipo, vendedor, bolinha 'Em aberto'")
    # -- textos: nunca o CPF/CNPJ
    for item in ITENS:
        digitos = apenas_digitos(item["cpf"])
        textos = textos_do_cliente({**item, "em_aberto": True})
        assert not any(digitos in apenas_digitos(t) or item["cpf"] in t for t in textos.values()), f"CPF vazou pro card: {textos}"
    textos = textos_do_cliente({**ITENS[0], "em_aberto": True})
    assert textos == {"nome": "ALFA CLIENTE", "tipo": "Cliente", "vendedor": "Vendedor: ANA", "em_aberto": "Em aberto"}
    vazio = textos_do_cliente({**ITENS[2], "em_aberto": False})
    assert vazio == {"nome": "SEM TIPO NEM VENDEDOR", "tipo": "", "vendedor": "Sem vendedor", "em_aberto": ""}
    assert textos_do_cliente({"cliente": "  "})["nome"] == "(sem nome)"
    # a planilha tem "CLIENTE" (maiusculas) e "Avalista": o badge mostra o rotulo padrao dos dois
    assert [rotulo_do_tipo(t) for t in ("CLIENTE", "cliente", " Cliente ", "AVALISTA", "Avalista", "", None, "Outro")] == \
        ["Cliente", "Cliente", "Cliente", "Avalista", "Avalista", "", "", "Outro"]
    assert textos_do_cliente({"cliente": "X", "tipo": "CLIENTE"})["tipo"] == "Cliente"

    modelo = ModeloClientes()
    verificador = QAbstractItemModelTester(modelo, QAbstractItemModelTester.FailureReportingMode.Fatal) if QAbstractItemModelTester else None
    modelo.definir_itens(ITENS)
    modelo.definir_em_aberto({"11144477735"})  # so digitos, como sai de cpfs_com_proposta_em_aberto
    assert [modelo.esta_em_aberto(i) for i in range(3)] == [True, False, False], "o CPF com pontuação casa pelos dígitos"
    for i, item in enumerate(ITENS):
        dica = modelo.data(modelo.index(i), Qt.ItemDataRole.ToolTipRole)
        assert item["cpf"] not in dica and apenas_digitos(item["cpf"]) not in dica, "o tooltip também não mostra o CPF"
        assert modelo.data(modelo.index(i)) == item["cliente"]
    assert "Tem proposta em aberto" in modelo.data(modelo.index(0), Qt.ItemDataRole.ToolTipRole)
    assert "Tem proposta em aberto" not in modelo.data(modelo.index(1), Qt.ItemDataRole.ToolTipRole)
    mudancas: list[tuple[int, int]] = []
    modelo.dataChanged.connect(lambda a, b, _r=None: mudancas.append((a.row(), b.row())))
    modelo.definir_em_aberto({"11144477735"})
    assert mudancas == [], "mesmo conjunto: nada é repintado"
    modelo.definir_em_aberto({"52998224725"})
    assert mudancas == [(0, 2)] and [modelo.esta_em_aberto(i) for i in range(3)] == [False, True, False]
    print("OK: os textos e o tooltip nunca trazem o CPF/CNPJ; a bolinha casa o CPF pelos dígitos; só repinta quando muda"
          + (" (modelo validado pelo QAbstractItemModelTester)." if verificador else "."))

    # -- desenho, nos dois temas
    original_obter = settings_mod.obter_tema
    lista = None
    try:
        for tema in (TEMA_ESCURO, TEMA_CLARO):
            settings_mod.obter_tema = lambda t=tema: t
            app.setStyleSheet(build_stylesheet(tema))
            lista = ListaClientes()
            lista.resize(420, 400)
            lista.show()
            lista.definir_itens(ITENS)
            lista.definir_em_aberto({"11144477735"})
            _ciclos(app)
            paleta, tipos = PALETAS[tema], CORES_TIPO[tema]
            imagem = lista.viewport().grab().toImage()
            cartoes = [lista.visualRect(lista.model().index(i)) for i in range(3)]
            for c in cartoes:
                assert c.height() == ALTURA_CARTAO_CLIENTE + 8
            # o badge fica na ponta direita da 1a linha: la o pixel e a cor do Tipo (ou, sem Tipo, a do card)
            no_badge = lambda i: imagem.pixelColor(cartoes[i].left() + lista._delegate._largura - 1 - 14 - 3, cartoes[i].top() + 23).name()  # noqa: E731
            assert no_badge(0) == QColor(tipos["cliente"]["fundo"]).name(), f"{tema}: badge Cliente ({no_badge(0)})"
            assert no_badge(1) == QColor(tipos["avalista"]["fundo"]).name(), f"{tema}: badge Avalista ({no_badge(1)})"
            assert no_badge(2) == QColor(paleta["bg_card"]).name(), f"{tema}: sem tipo, sem badge ({no_badge(2)})"
            assert _pontos_da_cor(imagem, cartoes[0], tipos["cliente"]["fundo"]) > 300 and _pontos_da_cor(imagem, cartoes[1], tipos["avalista"]["fundo"]) > 300
            assert _pontos_da_cor(imagem, cartoes[0], COR_EM_ABERTO[tema]) > 20, f"{tema}: bolinha 'Em aberto' do 1º"
            assert _pontos_da_cor(imagem, cartoes[1], COR_EM_ABERTO[tema]) < POUCOS and _pontos_da_cor(imagem, cartoes[2], COR_EM_ABERTO[tema]) < POUCOS
            # nenhuma cor de status no card de cliente (a faixa/pilula so existem nos cards de proposta)
            for nome, cor in CORES_STATUS[tema].items():
                assert _pontos_da_cor(imagem, cartoes[0], cor["faixa"], tolerancia=2) < POUCOS, f"{tema}: cor de status '{nome}' no card de cliente"

            # selecao: fundo azulado + borda de destaque (e so nesse card)
            fundo = lambda i: imagem.pixelColor(cartoes[i].left() + 120, cartoes[i].top() + 36).name()  # noqa: E731  (entre as duas linhas de texto)
            assert fundo(0) == fundo(1) == QColor(paleta["bg_card"]).name(), f"{tema}: card normal com o fundo do card"
            _clicar_no_card(lista, 1)
            _ciclos(app)
            imagem = lista.viewport().grab().toImage()
            assert fundo(1) != QColor(paleta["bg_card"]).name() and fundo(0) == QColor(paleta["bg_card"]).name(), f"{tema}: só o selecionado muda"
            borda = imagem.pixelColor(cartoes[1].left() + 120, cartoes[1].top())
            alvo = QColor(paleta["destaque"])
            assert all(abs(a - b) <= 3 for a, b in zip((borda.red(), borda.green(), borda.blue()), (alvo.red(), alvo.green(), alvo.blue()))), \
                f"{tema}: borda do selecionado {borda.name()}"
            lista.close()
            lista = None
    finally:
        if lista is not None:
            lista.close()
        settings_mod.obter_tema = original_obter
        app.setStyleSheet("")
    print("OK (escuro e claro): badge sólido do Tipo (Cliente ≠ Avalista; sem tipo, sem badge), bolinha lima só em quem tem "
          "proposta em aberto, nenhuma cor de status no card, e o selecionado com fundo azulado + borda de destaque.")


def testar_lista_de_clientes(app: QApplication) -> None:
    linha("4) A lista de clientes: um clique seleciona, teclado navega, filtrar mantém a seleção sem reabrir")
    lista = ListaClientes()
    lista.resize(420, 300)
    lista.show()
    avisos: list[str] = []
    lista.cliente_mudou.connect(avisos.append)
    assert lista.definir_itens(ITENS) is False and lista.count() == 3 and lista.linha_atual() is None
    _ciclos(app)

    _clicar_no_card(lista, 1)
    assert avisos == [ITENS[1]["cpf"]] and lista.linha_atual() == 1, "1 clique seleciona e avisa o CPF"
    _clicar_no_card(lista, 1)
    assert avisos == [ITENS[1]["cpf"]], "clicar de novo no mesmo card não reabre nada"
    retangulo = lista.visualRect(lista.model().index(1))
    QTest.mouseClick(lista.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(retangulo.left() + 30, retangulo.top() + ALTURA_CARTAO_CLIENTE + 4))
    assert avisos == [ITENS[1]["cpf"]] and lista.linha_atual() == 1, "o vão entre os cards não seleciona"
    QTest.keyClick(lista, Qt.Key.Key_Down)
    assert avisos[-1] == ITENS[2]["cpf"] and lista.linha_atual() == 2, "seta pra baixo seleciona o próximo"
    QTest.keyClick(lista, Qt.Key.Key_Up)
    assert avisos[-1] == ITENS[1]["cpf"]
    print("OK: 1 clique seleciona (e avisa o CPF do cliente, uma vez); o vão entre cards não conta; as setas do teclado navegam.")

    avisos.clear()
    assert lista.definir_itens(list(reversed(ITENS)), ITENS[1]["cpf"]) is True and avisos == [], "reordenar mantém a seleção sem avisar"
    assert lista.cpf_da_linha(lista.linha_atual()) == ITENS[1]["cpf"]
    assert lista.definir_itens(ITENS[:1], ITENS[1]["cpf"]) is False and lista.linha_atual() is None and avisos == []
    assert lista.definir_itens([]) is False and lista.count() == 0
    lista.definir_mensagem_vazia("Nenhum cliente encontrado")
    lista.grab()  # o estado vazio (mensagem) nao pode quebrar o desenho
    lista.close()
    print("OK: reordenar/filtrar mantém o card selecionado (sem reabrir a ficha); se o cliente sai da lista, nada fica selecionado.")


# ---------------------------------------------------------------------------
# 5) a tela

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
        self.orig = (QMessageBox.warning, QMessageBox.critical, QMessageBox.information, QMessageBox.question,
                     ExpansorDeProposta.alternar, ExpansorDeProposta.nova)
        alternar_original, nova_original = ExpansorDeProposta.alternar, ExpansorDeProposta.nova
        self.titulos: list[str] = []
        self.textos: list[str] = []
        self.dialogos: list[FormularioProposta] = []
        self.acao_exec = None  # funcao(formulario) chamada logo depois de o card expandir

        def _msg(*args, **kwargs):
            self.titulos.append(str(args[1]) if len(args) > 1 else "")
            self.textos.append(str(args[2]) if len(args) > 2 else "")
            return QMessageBox.StandardButton.Ok

        def _entregar(expansor):
            # entrega o formulario do card expandido ao teste; depois recolhe (o mesmo que o exec() simulado de
            # antes, que devolvia Rejected): nada fica expandido entre um passo e outro
            formulario = expansor.formulario()
            self.dialogos.append(formulario)
            if self.acao_exec:
                self.acao_exec(formulario)
            expansor.descartar()

        def _alternar(expansor, linha):
            antes = expansor.formulario()
            alternar_original(expansor, linha)
            if expansor.formulario() is not None and expansor.formulario() is not antes:
                _entregar(expansor)

        def _nova(expansor, cpf, nome_cliente=None):
            nova_original(expansor, cpf, nome_cliente)
            if expansor.formulario() is not None:
                _entregar(expansor)

        QMessageBox.warning = QMessageBox.critical = QMessageBox.information = staticmethod(_msg)
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
        ExpansorDeProposta.alternar, ExpansorDeProposta.nova = _alternar, _nova
        return self

    def __exit__(self, *_):
        (QMessageBox.warning, QMessageBox.critical, QMessageBox.information, QMessageBox.question,
         ExpansorDeProposta.alternar, ExpansorDeProposta.nova) = self.orig


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


def _cadastrar(arquivo: Path) -> dict[str, str]:
    """ALFA (Cliente/ANA): 1 aberta + 1 negada; BETA (Avalista/BIA): so encerradas; DELTA
    (Cliente/BIA): 1 aprovada (segue em aberto); GAMA (Cliente/ANA): nenhuma proposta."""
    vendedores_mod.adicionar_vendedor("ANA")
    vendedores_mod.adicionar_vendedor("BIA")
    cpfs = {}
    for n, (chave, nome, tipo, vendedor) in enumerate([
        ("alfa", "ALFA CLIENTE", "Cliente", "ANA"),
        ("beta", "BETA AVALISTA", "Avalista", "BIA"),
        ("delta", "DELTA APROVADO", "Cliente", "BIA"),
        ("gama", "GAMA SEM PROPOSTA", "Cliente", "ANA"),
    ]):
        cpfs[chave] = _cpf(n)
        clientes_mod.adicionar_cliente({"CPF/CNPJ": cpfs[chave], "CLIENTE": nome, "TIPO": tipo, "VENDEDOR": vendedor})
    propostas = [
        ("alfa", pd.Timestamp(2026, 3, 1), 75000, "HAKON", "SANTANDER", "Em Análise"),
        ("alfa", pd.Timestamp(2026, 3, 5), 20000, "MESA", "PORTOBANK", "Negado"),
        ("beta", pd.Timestamp(2026, 3, 2), 1500.5, "LASER", "SMART", "Efetivado"),
        ("beta", pd.Timestamp(2026, 3, 3), 900, "CADEIRA", "MOVA HTM", "Negado"),
        ("delta", pd.Timestamp(2026, 3, 4), 30000, "PTOLOMEU", "HUBCRED BV", "Aprovado"),
    ]
    for chave, data, valor, equipamento, banco, status in propostas:
        propostas_mod.adicionar_proposta(
            {"CPF": cpfs[chave], "DATA": data, "VALOR (R$)": valor, "MESES": 12, "EQUIPAMENTO": equipamento, "BANCO": banco,
             "STATUS": status, "OBSERVAÇÕES": f"obs {equipamento}"}
        )
    return cpfs


def _nomes(tela: FichaClienteScreen) -> list[str]:
    return [tela._lista.nome_da_linha(i) for i in range(tela._lista.count())]


def _em_aberto(tela: FichaClienteScreen) -> dict[str, bool]:
    return {tela._lista.nome_da_linha(i): tela._lista.esta_em_aberto(i) for i in range(tela._lista.count())}


def _selecionar_card_do_historico(tela: FichaClienteScreen, linha_: int) -> QPoint:
    lista = tela._lista_historico
    retangulo = lista.visualRect(lista.model().index(linha_))
    ponto = QPoint(retangulo.left() + 40, retangulo.top() + 30)
    QTest.mouseClick(lista.viewport(), Qt.MouseButton.LeftButton, pos=ponto)
    return ponto


def testar_tela(app: QApplication, stubs: _Stubs, cpfs: dict[str, str]) -> None:
    linha("5) A tela: cards de cliente com a bolinha 'Em aberto' e a busca por CPF")
    leituras = {"n": 0}
    original_leitura = propostas_mod.cpfs_com_proposta_em_aberto

    def _contando():
        leituras["n"] += 1
        return original_leitura()

    propostas_mod.cpfs_com_proposta_em_aberto = _contando
    tela = None
    try:
        tela = FichaClienteScreen()
        tela.resize(1250, 800)
        tela.show()
        _ciclos(app)
        assert _nomes(tela) == ["ALFA CLIENTE", "BETA AVALISTA", "DELTA APROVADO", "GAMA SEM PROPOSTA"]
        assert _em_aberto(tela) == {"ALFA CLIENTE": True, "BETA AVALISTA": False, "DELTA APROVADO": True, "GAMA SEM PROPOSTA": False}, _em_aberto(tela)
        itens = [tela._lista._modelo.data(tela._lista._modelo.index(i), Qt.ItemDataRole.UserRole) for i in range(4)]
        assert [(i["tipo"], i["vendedor"]) for i in itens] == [("Cliente", "ANA"), ("Avalista", "BIA"), ("Cliente", "BIA"), ("Cliente", "ANA")]
        print("OK: um card por cliente (nome, Tipo, vendedor); 'Em aberto' só em ALFA (Em Análise) e DELTA (Aprovado) - BETA tem só "
              "propostas encerradas e GAMA nenhuma.")

        # a busca continua achando pelo CPF/CNPJ (so nao aparece no card)
        antes = leituras["n"]
        tela._busca.setText(apenas_digitos(cpfs["beta"]))
        assert _nomes(tela) == ["BETA AVALISTA"]
        tela._busca.setText(cpfs["alfa"])
        assert _nomes(tela) == ["ALFA CLIENTE"]
        tela._busca.setText("gama")
        assert _nomes(tela) == ["GAMA SEM PROPOSTA"]
        tela._busca.setText("")
        assert _nomes(tela) == ["ALFA CLIENTE", "BETA AVALISTA", "DELTA APROVADO", "GAMA SEM PROPOSTA"]
        assert leituras["n"] == antes, f"buscar/filtrar não relê as propostas de novo ({leituras['n'] - antes} leituras a mais)"
        print("OK: a busca por CPF/CNPJ (com ou sem pontuação) e por nome segue funcionando; buscar não relê as propostas a cada tecla.")

        # 1 clique num card abre a ficha (a selecao por clique unico que ja existia)
        _clicar_no_card(tela._lista, 1)
        assert tela._painel_stack.currentIndex() == 1 and tela._nome_label.text() == "BETA AVALISTA"
        assert tela._cpf_selecionado == cpfs["beta"] and tela._lista.linha_atual() == 1
        tela._busca.setText("a")  # filtrar com a ficha aberta: o cliente segue na lista, selecionado
        assert tela._cpf_selecionado == cpfs["beta"] and tela._painel_stack.currentIndex() == 1
        tela._busca.setText("")
        print("OK: 1 clique no card seleciona e abre a ficha; a busca não fecha a ficha do cliente que continua na lista.")

        # quando muda a lista, so relê no que pode ter mudado
        antes = leituras["n"]
        tela.hide()
        tela.show()  # trocar de tela no app dispara showEvent
        _ciclos(app)
        assert leituras["n"] == antes + 1, "ao voltar pra tela, relê quem tem proposta em aberto (mudou em outra tela?)"
        print("OK: ao voltar para a tela, a marca 'Em aberto' é relida (as propostas podem ter mudado em outra tela).")
    finally:
        propostas_mod.cpfs_com_proposta_em_aberto = original_leitura
        if tela is not None:
            tela.close()

    linha("5b) A bolinha acompanha lançar/editar proposta e o erro de leitura avisa")
    tela = FichaClienteScreen()
    tela.resize(1250, 800)
    tela.show()
    _ciclos(app)
    try:
        # editar a unica proposta aberta da ALFA pra Efetivado: a bolinha some
        tela._selecionar_por_cpf(cpfs["alfa"])
        _ciclos(app)
        modelo = tela._modelo_historico
        assert [modelo.item(i)["titulo"] for i in range(modelo.total())] == ["PORTOBANK", "SANTANDER"]
        card_aberto = next(i for i in range(modelo.total()) if modelo.item(i)["status"] == "Em Análise")
        _selecionar_card_do_historico(tela, card_aberto)

        def _efetivar(dialogo: FormularioProposta) -> None:
            dialogo._habilitar_edicao()
            dialogo._status.setCurrentText("Efetivado")
            dialogo._salvar()

        stubs.acao_exec = _efetivar
        tela._expansor.alternar(tela._lista_historico.linha_atual())  # duplo clique no card selecionado
        stubs.acao_exec = None
        assert _em_aberto(tela)["ALFA CLIENTE"] is False, "sem proposta aberta a bolinha some, sem refazer a lista"
        assert tela._lista.linha_atual() == 0 and tela._cpf_selecionado == cpfs["alfa"], "a lista e a seleção seguem onde estavam"
        assert modelo.item(tela._lista_historico.linha_atual())["status"] == "Efetivado", "o card editado segue selecionado, com o status novo"

        # lancar uma proposta nova (aberta) na GAMA: a bolinha aparece
        tela._selecionar_por_cpf(cpfs["gama"])
        _ciclos(app)

        def _nova(dialogo: FormularioProposta) -> None:
            dialogo._valor.setValue(4321)
            dialogo._equipamento.setCurrentText("Equip Novo")
            dialogo._banco.setCurrentText("Banco Novo")
            dialogo._status.setCurrentText("Em Análise")
            dialogo._salvar()

        stubs.acao_exec = _nova
        tela._botao_nova_proposta.click()
        stubs.acao_exec = None
        assert _em_aberto(tela)["GAMA SEM PROPOSTA"] is True
        assert modelo.total() == 1 and modelo.item(0)["titulo"] == "Banco Novo"
        print("OK: efetivar a única proposta aberta apaga a bolinha; lançar uma nova acende - sem refazer a lista nem perder a seleção.")

        # erro ao ler as propostas: avisa (uma vez) e a lista segue funcionando sem a marca
        def _falha():
            raise RuntimeError("planilha bloqueada")

        original = propostas_mod.cpfs_com_proposta_em_aberto
        propostas_mod.cpfs_com_proposta_em_aberto = _falha
        try:
            stubs.titulos.clear()
            tela.hide()
            tela.show()
            _ciclos(app)
            assert stubs.titulos.count("Erro ao carregar as propostas em aberto") == 1, stubs.titulos
            assert "planilha bloqueada" in stubs.textos[-1]
            assert not any(_em_aberto(tela).values()) and len(_nomes(tela)) == 4, "a lista segue, sem a marca"
            tela._busca.setText("a")
            tela._busca.setText("")
            assert stubs.titulos.count("Erro ao carregar as propostas em aberto") == 1, "digitar na busca não repete o aviso"
        finally:
            propostas_mod.cpfs_com_proposta_em_aberto = original
        print("OK: se a leitura falha, avisa (uma vez só) e a lista de clientes segue funcionando sem a marca.")
    finally:
        stubs.acao_exec = None
        tela.close()


def testar_historico_em_cards(app: QApplication, stubs: _Stubs, cpfs: dict[str, str]) -> None:
    linha("6) Histórico em cards: banco em destaque, 'Equipamento · Valor', cores de status iguais às de Todas as Propostas")
    original_obter = settings_mod.obter_tema
    tela = None
    try:
        for tema in (TEMA_ESCURO, TEMA_CLARO):
            settings_mod.obter_tema = lambda t=tema: t
            app.setStyleSheet(build_stylesheet(tema))
            tela = FichaClienteScreen()
            tela.resize(1250, 800)
            tela.show()
            tela._selecionar_por_cpf(cpfs["beta"])
            _ciclos(app)
            modelo, lista = tela._modelo_historico, tela._lista_historico
            # BETA: 03/03 Negado (MOVA HTM / CADEIRA / R$ 900) e 02/03 Efetivado (SMART / LASER / R$ 1.500,50)
            item0, item1 = modelo.item(0), modelo.item(1)
            assert (item0["titulo"], item0["linha2"], item0["status"], item0["data"], item0["tempo"]) == \
                ("MOVA HTM", "CADEIRA · R$ 900,00", "Negado", "03/03/2026", "Encerrado")
            assert (item1["titulo"], item1["linha2"], item1["status"], item1["data"]) == \
                ("SMART", "LASER · R$ 1.500,50", "Efetivado", "02/03/2026")
            assert "titulo" in item0 and modelo.data(modelo.index(0)) == "MOVA HTM", "o destaque do card é o banco"
            assert "MOVA HTM" in modelo.data(modelo.index(0), Qt.ItemDataRole.ToolTipRole) and \
                "CADEIRA · R$ 900,00" in modelo.data(modelo.index(0), Qt.ItemDataRole.ToolTipRole)

            # a faixa de cada card tem a mesma cor do status (a mesma tabela de "Todas as Propostas")
            imagem = lista.viewport().grab().toImage()
            for i, chave in ((0, "negado"), (1, "efetivado")):
                r = lista.visualRect(modelo.index(i))
                pixel = imagem.pixelColor(r.left() + 3, r.top() + ALTURA_CARTAO // 2)
                assert pixel.rgb() == QColor(CORES_STATUS[tema][chave]["faixa"]).rgb(), f"{tema}: faixa do card {i} ({pixel.name()})"
            tela.close()
            tela = None
        print("OK (escuro e claro): o card mostra o banco em destaque, 'CADEIRA · R$ 900,00', data e tempo; a faixa tem a cor do "
              "status (a mesma de Todas as Propostas).")
    finally:
        if tela is not None:
            tela.close()
        settings_mod.obter_tema = original_obter
        app.setStyleSheet("")

    # o mesmo status pinta igual nas duas telas (mesma funcao de cor)
    for status in ("Em Análise", "Pré-aprovado", "Aprovado", "Nota Fiscal Anexada", "Garantia Assinada", "Efetivado", "Negado", "APROVADO", "", "Status Novo"):
        do_historico = _montar_item_historico(0, "B", "E", 1.0, status, pd.Timestamp(2026, 1, 1), "1 dias")
        de_propostas = propostas_screen_mod._montar_item(0, "CLIENTE", status, pd.Timestamp(2026, 1, 1), "E", "B", "1 dias")
        assert do_historico["cor"] == de_propostas["cor"], status
        assert do_historico["cor"] == chave_cor_status(status) and do_historico["etapa"] == de_propostas["etapa"]
    vazio = _montar_item_historico(0, "", "", float("nan"), "", pd.NaT, "")
    assert (vazio["titulo"], vazio["titulo_vazio"], vazio["linha2"], vazio["status"], vazio["data"]) == ("", "(sem banco)", "—", "", "—")
    print("OK: cada status tem a mesma cor no histórico e em Todas as Propostas; banco/equipamento/valor em branco não quebram o card.")

    linha("6b) Histórico: 1 clique seleciona, duplo clique (ou Enter) expande o card, 'Excluir Proposta Selecionada' age no selecionado")
    tela = FichaClienteScreen()
    tela.resize(1250, 800)
    tela.show()
    tela._selecionar_por_cpf(cpfs["beta"])
    _ciclos(app)
    lista, modelo = tela._lista_historico, tela._modelo_historico
    stubs.dialogos.clear()
    stubs.textos.clear()
    tela._botao_excluir_proposta.click()
    assert stubs.dialogos == [] and "Clique em um card" in stubs.textos[-1], "sem card selecionado: avisa"
    assert not hasattr(tela, "_botao_editar_proposta"), "'Editar Proposta Selecionada' saiu: a edição é dentro do card expandido"
    ponto = _selecionar_card_do_historico(tela, 1)
    assert stubs.dialogos == [], "1 clique só seleciona (não abre a proposta)"
    assert tela._indice_real_proposta_selecionada() == modelo.indice_real(1)
    _selecionar_card_do_historico(tela, 0)
    assert stubs.dialogos == [] and tela._indice_real_proposta_selecionada() == modelo.indice_real(0), "outro clique só troca a seleção"
    ponto0 = _selecionar_card_do_historico(tela, 0)
    _duplo_clique(lista.viewport(), ponto0)
    assert len(stubs.dialogos) == 1, "o duplo clique abre a proposta, uma vez só"
    dialogo = stubs.dialogos[0]
    assert dialogo._modo_leitura and dialogo._banco.currentText() == "MOVA HTM" and dialogo._equipamento.currentText() == "CADEIRA"
    assert dialogo._valor.value() == 900 and dialogo._observacoes.toPlainText() == "obs CADEIRA", "meses/observações estão na leitura"
    stubs.dialogos.clear()
    lista.setCurrentIndex(modelo.index(1))
    QTest.keyClick(lista, Qt.Key.Key_Return)
    assert len(stubs.dialogos) == 1 and stubs.dialogos[0]._banco.currentText() == "SMART", "Enter abre a proposta selecionada"
    print("OK: 1 clique seleciona; o duplo clique (e o Enter) expande o card em leitura, com meses/observações; "
          "'Excluir Proposta Selecionada' avisa se não há seleção.")

    # trocar de cliente comeca limpo; recarregar o mesmo cliente mantem o card selecionado
    _selecionar_card_do_historico(tela, 0)
    tela._selecionar_por_cpf(cpfs["alfa"])
    assert tela._indice_real_proposta_selecionada() is None, "outro cliente: nenhum card do histórico selecionado"
    _selecionar_card_do_historico(tela, 1)
    escolhido = tela._indice_real_proposta_selecionada()
    tela._recarregar_ficha_atual()
    assert tela._indice_real_proposta_selecionada() == escolhido, "recarregar o mesmo cliente mantém o card selecionado"
    print("OK: abrir outro cliente limpa a seleção do histórico; recarregar o mesmo cliente a mantém.")

    linha("6c) Histórico: alinhado com o cartão de dados, sem barra própria, rola junto com o painel")
    tela._selecionar_por_cpf(cpfs["beta"])
    cartao = tela._nome_label.parentWidget()
    direita = lambda w: w.mapTo(tela, QPoint(w.width(), 0)).x()  # noqa: E731
    for largura in (1250, 900, 700):
        tela.resize(largura, 800)
        _ciclos(app, 8)
        colunas = lista.colunas()
        ultimo = lista.visualRect(modelo.index(min(colunas, modelo.total()) - 1))
        borda_do_card = lista.mapTo(tela, QPoint(ultimo.x() + lista.largura_do_cartao(), 0)).x()
        assert abs(borda_do_card - direita(cartao)) <= 3, f"{largura}px: histórico termina em {borda_do_card}, o cartão de dados em {direita(cartao)}"
        assert lista.height() == -(-modelo.total() // colunas) * (ALTURA_CARTAO + 12), f"{largura}px: {colunas} coluna(s), altura {lista.height()}"
    assert lista.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff, "o histórico não tem barra própria"
    print("OK: em 3 larguras (2 colunas e 1), o último card termina na borda do cartão de dados (±3 px) e a lista tem a altura das linhas.")

    tela.setMinimumSize(100, 100)
    tela.resize(1250, 420)  # baixa: o painel precisa rolar
    _ciclos(app, 8)
    barra = tela._rolagem_ficha.verticalScrollBar()
    assert barra.maximum() > 0 and barra.value() == 0
    def roda_sobre(widget, ponto: QPoint) -> QWheelEvent:
        evento = QWheelEvent(
            QPointF(ponto), QPointF(widget.mapToGlobal(ponto)), QPoint(0, 0), QPoint(0, -240),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False,
        )
        QApplication.sendEvent(widget, evento)
        return evento

    # (um sendEvent num FILHO nao propaga pro painel - nem num QScrollArea puro do Qt; a propagacao real e dos eventos
    # do sistema. O que da pra conferir com fidelidade: a lista IGNORA a roda - ela nao a prende - e o painel a usa.)
    ignorado = not roda_sobre(lista.viewport(), QPoint(60, 40)).isAccepted()
    assert ignorado, "a lista de cards do histórico não pode consumir a roda do mouse (senão o painel não rolaria sobre ela)"
    roda_sobre(tela._rolagem_ficha.viewport(), QPoint(50, 50))
    _ciclos(app)
    assert barra.value() > 0, "e o painel rola com a roda"
    print("OK: a lista de cards do histórico não prende a roda do mouse (ignora o evento, que segue pro painel); o painel rola com ela.")
    tela.close()


def testar_vendedor(app: QApplication, stubs: _Stubs, cpfs: dict[str, str], arquivo: Path) -> None:
    linha("7) Perfil VENDEDOR: só os próprios clientes, sem botões de editar - mas abre a proposta em leitura")
    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_VENDEDOR, nome_usuario="ANA"))
    fontes = (clientes_mod._ler_da_fonte_ativa, propostas_mod._ler_da_fonte_ativa)
    clientes_mod._ler_da_fonte_ativa = lambda: sessao_mod.filtrar_por_vendedor_logado(bd.ler_clientes(arquivo))  # sem rede
    propostas_mod._ler_da_fonte_ativa = lambda: sessao_mod.filtrar_por_vendedor_logado(bd.ler_propostas(arquivo))
    tela = None
    try:
        tela = FichaClienteScreen()
        tela.resize(1250, 800)
        tela.show()
        _ciclos(app)
        assert _nomes(tela) == ["ALFA CLIENTE", "GAMA SEM PROPOSTA"], "o vendedor só vê os próprios clientes"
        assert _em_aberto(tela) == {"ALFA CLIENTE": False, "GAMA SEM PROPOSTA": True}, "a marca é só das propostas dele: " + str(_em_aberto(tela))
        assert tela._botao_novo_cliente.isHidden() and tela._botao_excluir_proposta.isHidden() and tela._botao_nova_proposta.isHidden()
        tela._selecionar_por_cpf(cpfs["alfa"])
        _ciclos(app)
        assert tela._modelo_historico.total() == 2
        stubs.dialogos.clear()
        ponto = _selecionar_card_do_historico(tela, 0)
        assert stubs.dialogos == [], "1 clique só seleciona"
        _duplo_clique(tela._lista_historico.viewport(), ponto)
        assert len(stubs.dialogos) == 1, "o duplo clique abre a proposta pro vendedor também"
        dialogo = stubs.dialogos[0]
        assert dialogo._modo_leitura and dialogo._botao_editar.isHidden() and dialogo._botao_duplicar.isHidden(), "só leitura: sem 'Editar' nem 'Duplicar'"
        assert dialogo._valor.value() > 0 and dialogo._observacoes.toPlainText().startswith("obs "), "vê meses/observações pela leitura"
    finally:
        if tela is not None:
            tela.close()
        clientes_mod._ler_da_fonte_ativa, propostas_mod._ler_da_fonte_ativa = fontes
        sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
    print("OK: o vendedor vê só os próprios clientes e a marca só das propostas dele; sem botões de editar; o duplo clique num "
          "card abre a proposta em leitura (é por ela que ele vê meses e observações).")


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
    testar_regras()
    testar_cores_do_tipo()
    testar_card_de_cliente(app)
    testar_lista_de_clientes(app)

    pasta = Path(tempfile.mkdtemp(prefix="_smoke_ficha_cards_"))
    arquivo = pasta / "controle.xlsx"
    _criar_planilha_vazia(arquivo)
    for modulo in (clientes_mod, propostas_mod, vendedores_mod, equipamentos_mod):
        modulo.CAMINHO_XLSX = arquivo
    try:
        cpfs = _cadastrar(arquivo)
        with _Stubs() as stubs:
            testar_tela(app, stubs, cpfs)
            testar_historico_em_cards(app, stubs, cpfs)
            # o teste da tela editou/lancou propostas: o vendedor ve o estado de agora
            testar_vendedor(app, stubs, cpfs, arquivo)
        linha("TUDO OK")
    finally:
        for modulo in (clientes_mod, propostas_mod, vendedores_mod, equipamentos_mod):
            modulo.CAMINHO_XLSX = config.CAMINHO_XLSX
        sessao_mod.encerrar()
        shutil.rmtree(pasta, ignore_errors=True)


if __name__ == "__main__":
    main()
