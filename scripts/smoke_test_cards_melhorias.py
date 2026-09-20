"""Testa as melhorias dos cards de "Todas as Propostas": (1) 2a linha
"Equipamento . Banco" que diferencia propostas do mesmo cliente na mesma data,
(2) tempo no card ("ha 7 dias"/"Encerrado"), (3) contagem por status no topo,
(4) paginacao de 30 em 30 com o card "Carregar mais". Dados FICTICIOS.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_cards_melhorias.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# sem tela o Qt nao acha fontes e desenha TODO caractere como o mesmo quadradinho - os
# testes que comparam o desenho dos cards usam as fontes do Windows quando existem (e,
# por garantia, textos de comprimentos diferentes, que tambem se distinguem sem fontes)
if Path(r"C:\Windows\Fonts").exists():
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import openpyxl
import pandas as pd
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

try:  # o verificador de modelos do proprio Qt (pega insercao/remocao de linhas inconsistente)
    from PySide6.QtTest import QAbstractItemModelTester
except ImportError:  # pragma: no cover - depende da versao do PySide6
    QAbstractItemModelTester = None

import config
config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
from core import clientes as clientes_mod
from core import data_store as bd
from core import equipamentos as equipamentos_mod
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import vendedores as vendedores_mod
from desktop.screens.propostas_screen import PropostasScreen, resumo_por_etapa
from desktop.widgets.lista_cartoes import (
    TAMANHO_PAGINA,
    ListaCartoes,
    ModeloCartoes,
    linha_data_e_tempo,
    linha_equipamento_banco,
)
from desktop.widgets.expansor_proposta import ExpansorDeProposta
from desktop.widgets.formulario_proposta import FormularioProposta


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _ciclos(app: QApplication, n: int = 4) -> None:
    for _ in range(n):  # o layout da grade e adiado: precisa de mais de um ciclo de eventos
        app.processEvents()


def _item(i: int, cliente: str = "CLIENTE", status: str = "Em Análise", equipamento: str = "", banco: str = "", tempo: str = "", etapa=None) -> dict:
    return {
        "indice": i, "cliente": cliente, "status": status, "data": "11/09/2026", "equipamento": equipamento,
        "banco": banco, "tempo": tempo, "etapa": etapa if etapa is not None else propostas_mod.etapa_status(status),
    }


def _imagem_do_card(lista: ListaCartoes, linha_: int):
    retangulo = lista.visualRect(lista.model().index(linha_))
    return lista.viewport().grab().toImage().copy(lista._delegate.retangulo_do_cartao(retangulo))


def _pixels_diferentes(a, b, tolerancia: int = 24) -> int:
    """Quantos pixels diferem de forma PERCEPTIVEL entre dois cards. Comparar as
    imagens byte a byte nao serve: o mesmo card desenhado em outra posicao tem
    1-2 pixels de antialiasing (nos cantos arredondados) com 1 unidade de cor a
    mais ou a menos."""
    def matriz(imagem):
        bruto = np.frombuffer(bytes(imagem.constBits()), dtype=np.uint8)
        return bruto.reshape(imagem.height(), imagem.width(), 4).astype(int)

    return int((np.abs(matriz(a) - matriz(b)) > tolerancia).any(axis=2).sum())


# ---------------------------------------------------------------------------
# 1) segunda linha  /  2) tempo

def testar_linhas_do_card() -> None:
    linha("1) Segunda linha do card: 'Equipamento · Banco'")
    assert linha_equipamento_banco({"equipamento": "HAKON", "banco": "SANTANDER"}) == "HAKON · SANTANDER"
    assert linha_equipamento_banco({"equipamento": "  HAKON ", "banco": ""}) == "HAKON"
    assert linha_equipamento_banco({"equipamento": None, "banco": "SANTANDER"}) == "SANTANDER"
    assert linha_equipamento_banco({"equipamento": "", "banco": ""}) == "—", "a linha nunca some (cards da mesma altura)"
    print("OK: 'HAKON · SANTANDER'; se falta um dos dois mostra só o outro; sem nenhum, '—'.")

    assert linha_data_e_tempo({"data": "11/09/2026", "tempo": "há 7 dias"}) == "11/09/2026 · há 7 dias"
    assert linha_data_e_tempo({"data": "11/09/2026", "tempo": "Encerrado"}) == "11/09/2026 · Encerrado"
    assert linha_data_e_tempo({"data": "11/09/2026", "tempo": ""}) == "11/09/2026"
    print("OK: '11/09/2026 · há 7 dias' / '· Encerrado'; sem tempo, só a data.")


def testar_cards_diferenciaveis(app: QApplication) -> None:
    linha("1b) O problema real: mesmo cliente, mesma data, mesmo status - agora dá pra diferenciar")
    lista = ListaCartoes()
    modelo = ModeloCartoes()
    lista.setModel(modelo)
    lista.resize(1100, 500)
    lista.show()

    def desenhar(itens: list[dict]) -> list:
        modelo.definir_itens(itens)
        _ciclos(app)
        return [_imagem_do_card(lista, i) for i in range(len(itens))]

    # antes da 2a linha: 3 propostas do mesmo cliente/data/status eram IDENTICAS na tela
    sem_produto = desenhar([_item(i, "CLARA EXEMPLO DE OLIVEIRA") for i in range(3)])
    assert _pixels_diferentes(sem_produto[0], sem_produto[1]) < 5 and _pixels_diferentes(sem_produto[0], sem_produto[2]) < 5, \
        "sem equipamento/banco os cards saem idênticos (o problema)"
    com_produto = desenhar([
        _item(0, "CLARA EXEMPLO DE OLIVEIRA", equipamento="CRIODERMIS 2.0", banco="PORTOBANK"),
        _item(1, "CLARA EXEMPLO DE OLIVEIRA", equipamento="CRIODERMIS 2.0", banco="SMART"),
        _item(2, "CLARA EXEMPLO DE OLIVEIRA", equipamento="CRIOSCULPT", banco="PORTOBANK"),
    ])
    diferencas = [_pixels_diferentes(com_produto[a], com_produto[b]) for a, b in ((0, 1), (0, 2), (1, 2))]
    assert all(d > 40 for d in diferencas), f"com equipamento + banco, cada card fica visualmente diferente: {diferencas}"
    print("OK: 3 propostas do mesmo cliente/data/status: sem a 2ª linha os cards saem idênticos; com ela, os 3 são diferentes.")

    linha("2) Tempo no card")
    mesmo_produto = desenhar([_item(0, tempo="hoje"), _item(1, tempo="há 15 dias"), _item(2, tempo="Encerrado"), _item(3, tempo="")])
    pares = [_pixels_diferentes(mesmo_produto[a], mesmo_produto[b]) for a in range(4) for b in range(a + 1, 4)]
    assert all(d > 10 for d in pares), f"cada tempo diferente muda o desenho do card: {pares}"
    lista.close()
    print("OK: o tempo aparece no card (cards que só diferem no tempo ficam diferentes).")


# ---------------------------------------------------------------------------
# 3) contagem  /  4) paginacao (na tela)

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


def _df(linhas: list[tuple]) -> pd.DataFrame:
    """(cliente, status, data, equipamento, banco, tempo) -> propostas em memoria
    (o indice e a "posicao real no arquivo")."""
    return pd.DataFrame(
        [
            {"DATA": data, "VENDEDOR": "ANA", "CLIENTE": cliente, "CPF": f"{i:011d}", "EQUIPAMENTO": equip, "BANCO": banco,
             "VALOR (R$)": 1000.0 + i, "MESES": 12, "STATUS": status, "TEMPO": tempo, "OBSERVAÇÕES": ""}
            for i, (cliente, status, data, equip, banco, tempo) in enumerate(linhas)
        ]
    )


def _nomes(tela: PropostasScreen) -> list[str]:
    return [tela._modelo.data(tela._modelo.index(i)) for i in range(tela._modelo.rowCount()) if not tela._modelo.eh_mais(i)]


class _Stubs:
    def __enter__(self):
        self.orig = (QMessageBox.warning, QMessageBox.critical, QMessageBox.information, QMessageBox.question,
                     ExpansorDeProposta.alternar, propostas_mod.listar_propostas)
        alternar_original = ExpansorDeProposta.alternar
        self.dialogos: list[FormularioProposta] = []
        self.textos: list[str] = []

        def _msg(*args, **kwargs):
            self.textos.append(str(args[2]) if len(args) > 2 else "")
            return QMessageBox.StandardButton.Ok

        def _alternar(expansor, linha):
            # expande o card de verdade e entrega o formulario ao teste; depois recolhe (o mesmo que o
            # exec() simulado de antes, que devolvia Rejected)
            antes = expansor.formulario()
            alternar_original(expansor, linha)
            if expansor.formulario() is not None and expansor.formulario() is not antes:
                self.dialogos.append(expansor.formulario())
                expansor.descartar()

        QMessageBox.warning = QMessageBox.critical = QMessageBox.information = staticmethod(_msg)
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
        ExpansorDeProposta.alternar = _alternar
        return self

    def usar_propostas(self, df: pd.DataFrame) -> None:
        propostas_mod.listar_propostas = lambda: df

    def __exit__(self, *_):
        (QMessageBox.warning, QMessageBox.critical, QMessageBox.information, QMessageBox.question,
         ExpansorDeProposta.alternar, propostas_mod.listar_propostas) = self.orig


def _clicar_no_card(lista: ListaCartoes, linha_: int) -> None:
    retangulo = lista.visualRect(lista.model().index(linha_))
    QTest.mouseClick(lista.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(retangulo.left() + 40, retangulo.top() + 30))


def _duplo_clique(widget, ponto: QPoint) -> None:
    """Um duplo clique como o Windows o manda: press, release, press (que o Qt
    entrega como "DblClick") e release. O QTest.mouseDClick sozinho manda so o
    DblClick, sem os cliques do meio."""
    QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=ponto)
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=ponto)
    evento = QMouseEvent(
        QEvent.Type.MouseButtonDblClick, QPointF(ponto), QPointF(widget.mapToGlobal(ponto)),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(widget, evento)
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=ponto)


DATA = pd.Timestamp(2026, 3, 10)
DEZ_PROPOSTAS = [
    ("ANA A", "Em Análise", DATA, "LASER", "SANTANDER", "3 dias"),
    ("ANA A", "Em Análise", DATA, "LASER", "PORTOBANK", "3 dias"),  # mesmo cliente/data/status/equipamento: so o banco muda
    ("BIA B", "Aprovado", DATA, "MESA", "SMART", "4 dias"),
    ("BIA B", "APROVADO", DATA, "CADEIRA", "SMART", "4 dias"),  # grafia antiga: conta junto com "Aprovado"
    ("CAI C", "Efetivado", DATA, "LASER", "SANTANDER", "Encerrado"),
    ("DAN D", "Negado", DATA, "MESA", "SMART", "Encerrado"),
    ("DAN D", "Negado", DATA, "LASER", "HUBCRED BV", "Encerrado"),
    ("DAN D", "Negado", DATA, "BISTURI", "MOVA HTM", "Encerrado"),
    ("EVA E", "Garantia Assinada", DATA, "LASER", "SMART", "0 dias"),
    ("FLA F", "", DATA, "", "", ""),
]


def testar_contagem(app: QApplication, stubs: _Stubs) -> PropostasScreen:
    linha("3) Contagem por status no topo")
    assert resumo_por_etapa({"em_analise": 12, "aprovado": 5, "negado": 30}) == "12 em análise · 5 aprovadas · 30 negadas"
    assert resumo_por_etapa({"negado": 1, "aprovado": 1, "efetivado": 1, "em_analise": 1}) == "1 em análise · 1 aprovada · 1 efetivada · 1 negada"
    assert resumo_por_etapa({"em_analise": 0, "negado": 2}) == "2 negadas", "zeros não aparecem"
    assert resumo_por_etapa({}) == ""
    assert resumo_por_etapa({"garantia": 2, "nota_fiscal": 1, "desconhecida": 1, "": 3}) == \
        "1 com nota fiscal anexada · 2 com garantia assinada · 1 com status não reconhecido · 3 sem status", "ordem do funil"
    print("OK: '12 em análise · 5 aprovadas · 30 negadas' (singular/plural, na ordem do funil, sem zeros).")

    stubs.usar_propostas(_df(DEZ_PROPOSTAS))
    tela = PropostasScreen()
    tela.resize(1300, 720)
    tela.show()
    _ciclos(app)
    esperado = "10 proposta(s) · 2 em análise · 2 aprovadas · 1 com garantia assinada · 1 efetivada · 3 negadas · 1 sem status"
    assert tela._contador.text() == esperado, tela._contador.text()
    tela._busca.setText("laser")  # a contagem acompanha o que esta sendo mostrado
    assert tela._contador.text() == "5 proposta(s) · 2 em análise · 1 com garantia assinada · 1 efetivada · 1 negada", tela._contador.text()
    tela._busca.setText("")
    tela._filtro_status.setCurrentText("Negado")
    assert tela._contador.text() == "3 proposta(s) · 3 negadas"
    tela._filtro_status.setCurrentText("Todos")
    assert tela._contador.text() == esperado
    print("OK: a contagem por status aparece no topo e acompanha a busca/filtro.")
    return tela


# ---------------------------------------------------------------------------
# 4) paginacao

def testar_paginacao_modelo(app: QApplication) -> None:
    linha("4) Paginação: modelo")
    modelo = ModeloCartoes()
    verificador = None
    if QAbstractItemModelTester is not None:
        verificador = QAbstractItemModelTester(modelo, QAbstractItemModelTester.FailureReportingMode.Fatal)
    inseridas: list[tuple[int, int]] = []
    removidas: list[tuple[int, int]] = []
    modelo.rowsInserted.connect(lambda _p, a, b: inseridas.append((a, b)))
    modelo.rowsRemoved.connect(lambda _p, a, b: removidas.append((a, b)))

    modelo.definir_itens([_item(i, f"CLIENTE {i:02d}") for i in range(65)])
    assert (modelo.total(), modelo.visiveis(), modelo.restantes(), modelo.proximos()) == (65, TAMANHO_PAGINA, 35, 30)
    assert modelo.rowCount() == 31 and modelo.eh_mais(30) and not modelo.eh_mais(29)
    assert modelo.indice_real(29) == 29 and modelo.indice_real(30) is None, "o card 'Carregar mais' não é uma proposta"
    mais = modelo.data(modelo.index(30), Qt.ItemDataRole.UserRole)
    assert mais["tipo"] == "mais" and mais["proximos"] == 30 and mais["visiveis"] == 30 and mais["total"] == 65
    assert modelo.data(modelo.index(30)) == "Carregar mais 30" and "30 de 65" in modelo.data(modelo.index(30), Qt.ItemDataRole.ToolTipRole)
    assert modelo.linha_do_indice_real(40) is None, "proposta fora da página atual"

    modelo.mostrar_mais()
    assert (modelo.visiveis(), modelo.rowCount(), modelo.proximos()) == (60, 61, 5) and inseridas == [(30, 59)] and removidas == []
    assert modelo.data(modelo.index(60), Qt.ItemDataRole.UserRole)["proximos"] == 5 and modelo.linha_do_indice_real(40) == 40
    modelo.mostrar_mais()
    assert (modelo.visiveis(), modelo.rowCount()) == (65, 65) and inseridas == [(30, 59), (60, 64)] and removidas == [(65, 65)]
    assert not modelo.eh_mais(65) and modelo.indice_real(64) == 64
    modelo.mostrar_mais()  # sem "carregar mais" nao ha nada a fazer
    assert modelo.rowCount() == 65 and len(inseridas) == 2
    print("OK: 65 propostas -> 30 + 'Carregar mais 30' -> 60 + 'Carregar mais 5' -> 65 (sem o card); "
          "linhas inseridas/removidas do jeito certo" + (" (validado pelo QAbstractItemModelTester do Qt)." if verificador else "."))

    modelo.definir_itens([_item(i) for i in range(65)])
    assert modelo.visiveis() == 30, "recarregar sem manter volta pra primeira página"
    modelo.mostrar_mais()
    modelo.definir_itens([_item(i) for i in range(65)], manter_limite=True)
    assert modelo.visiveis() == 60, "manter_limite: recarregar não perde o que já tinha sido carregado"
    modelo.definir_itens([_item(i) for i in range(65)], garantir_visivel=50)
    assert modelo.visiveis() == 60 and modelo.linha_do_indice_real(50) == 50, "garantir_visivel expande até incluir a proposta"
    modelo.definir_itens([_item(i) for i in range(65)], garantir_visivel=10)
    assert modelo.visiveis() == 30, "já visível: não expande à toa"
    for total, tem_mais in ((0, False), (10, False), (30, False), (31, True), (60, True), (61, True)):
        modelo.definir_itens([_item(i) for i in range(total)])
        assert (modelo.rowCount() > modelo.visiveis()) == tem_mais, f"{total} itens: card 'Carregar mais' {'deveria' if tem_mais else 'não deveria'} existir"
    modelo.definir_itens([_item(i) for i in range(31)])
    assert modelo.data(modelo.index(30)) == "Carregar mais 1"
    print("OK: recarregar mantém/volta a página conforme pedido; garantir_visivel expande só quando preciso; "
          "0, 10 e 30 itens não têm 'Carregar mais' (31 tem, com 'Carregar mais 1').")


def testar_paginacao_view(app: QApplication) -> None:
    linha("4b) Paginação: clique, duplo clique e Enter no 'Carregar mais'")
    lista = ListaCartoes()
    modelo = ModeloCartoes()
    lista.setModel(modelo)
    modelo.definir_itens([_item(i, f"CLIENTE {i:02d}") for i in range(65)])
    lista.resize(1000, 500)
    lista.show()
    _ciclos(app)
    acionados: list[int] = []
    lista.acionado.connect(acionados.append)

    barra = lista.verticalScrollBar()
    barra.setValue(barra.maximum())
    _ciclos(app)
    valor_antes = barra.value()
    assert valor_antes > 0
    assert lista.visualRect(modelo.index(30)).isValid()
    _clicar_no_card(lista, 30)
    _ciclos(app)
    assert acionados == [], "clicar em 'Carregar mais' não abre proposta nenhuma"
    assert modelo.visiveis() == 60 and modelo.rowCount() == 61
    assert barra.value() >= valor_antes - 1, "a rolagem fica onde estava (não volta pro topo)"
    print("OK: clicar no 'Carregar mais' mostra os próximos 30, não aciona nenhuma proposta e não joga a rolagem pro topo.")

    lista.setCurrentIndex(modelo.index(60))  # o novo 'Carregar mais' (5 restantes)
    QTest.keyClick(lista, Qt.Key.Key_Return)
    _ciclos(app)
    assert acionados == [] and modelo.visiveis() == 65 and modelo.rowCount() == 65
    lista.setCurrentIndex(modelo.index(3))
    QTest.keyClick(lista, Qt.Key.Key_Return)
    assert acionados == [3], "Enter num card de verdade continua abrindo"
    print("OK: Enter no 'Carregar mais' também carrega; Enter num card de proposta continua abrindo a proposta.")

    # duplo clique (na sequencia real do Windows) no "Carregar mais": o 1o clique carrega e um card novo
    # passa a ocupar o lugar dele - o 2o clique nao pode abrir nem selecionar essa proposta
    modelo.definir_itens([_item(i, f"CLIENTE {i:02d}") for i in range(65)])
    acionados.clear()
    lista.clearSelection()
    barra.setValue(barra.maximum())
    _ciclos(app)
    retangulo = lista.visualRect(modelo.index(30))
    _duplo_clique(lista.viewport(), QPoint(retangulo.left() + 40, retangulo.top() + 30))
    _ciclos(app)
    assert modelo.visiveis() == 60, f"duplo clique no 'Carregar mais' carrega UMA vez só (30 -> {modelo.visiveis()})"
    assert acionados == [], "e não abre a proposta que passou a ocupar o lugar dele"
    assert modelo.indice_real(lista.linha_atual()) is None, "nem a seleciona (o atual segue sendo o 'Carregar mais')"
    # um duplo clique em OUTRO card, logo em seguida, continua abrindo normalmente
    barra.setValue(0)
    _ciclos(app)
    outro = lista.visualRect(modelo.index(5))
    _duplo_clique(lista.viewport(), QPoint(outro.left() + 40, outro.top() + 30))
    assert acionados == [5], "duplo clique num card qualquer não é engolido"
    lista.close()
    print("OK: duplo clique no 'Carregar mais' carrega uma vez só, sem abrir nem selecionar proposta; "
          "duplo clique em outro card logo depois abre normalmente.")


def testar_paginacao_tela(app: QApplication, stubs: _Stubs, tela: PropostasScreen) -> None:
    linha("4c) Paginação na tela")
    tela._limpar_selecao()  # um card selecionado alem da 1a pagina expandiria a pagina de proposito (testado mais abaixo)
    linhas = [
        (f"CLIENTE {i:02d}", ("Em Análise", "Aprovado", "Negado")[i % 3], DATA, f"EQUIP {i % 5}", f"BANCO {i % 4}", "Encerrado" if i % 3 == 2 else "5 dias")
        for i in range(65)
    ]
    stubs.usar_propostas(_df(linhas))
    tela._busca.setText("")
    tela._filtro_status.setCurrentIndex(0)
    tela._carregar_dados()
    _ciclos(app)
    assert (tela._modelo.total(), tela._modelo.visiveis()) == (65, 30) and tela._modelo.eh_mais(30)
    tela._modelo.mostrar_mais()
    assert tela._modelo.visiveis() == 60

    tela._carregar_dados()  # "Atualizar" / depois de editar: nao volta pra pagina 1
    assert tela._modelo.visiveis() == 60, "recarregar mantém o que já tinha sido carregado"
    tela._busca.setText("CLIENTE")  # mudar a busca volta pra pagina 1...
    assert tela._modelo.visiveis() == 30, "mudar a busca volta pra primeira página"
    tela._busca.setText("")
    tela._modelo.mostrar_mais()
    # (mesma data em todas: a cadastrada por ultimo vem primeiro, entao a de indice real 10 esta na 55a linha, alem da 1a pagina)
    tela._lista.setCurrentIndex(tela._modelo.index(tela._modelo.linha_do_indice_real(10)))
    tela._busca.setText("CLIENTE")  # ...mas o card selecionado nunca some por causa disso
    assert tela._modelo.visiveis() == 60 and tela._indice_real_selecionado() == 10, "o card selecionado continua visível e selecionado"
    tela._filtro_status.setCurrentText("Negado")
    assert tela._modelo.total() == 21 and tela._modelo.visiveis() == 21 and not tela._modelo.eh_mais(21), "menos de 30: sem 'Carregar mais'"
    tela._filtro_status.setCurrentText("Todos")
    tela._busca.setText("")
    print("OK: na tela, a lista vem de 30 em 30; recarregar mantém a página, mudar busca/filtro volta à primeira, "
          "e o card selecionado nunca some.")


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
    testar_linhas_do_card()
    testar_cards_diferenciaveis(app)
    testar_paginacao_modelo(app)
    testar_paginacao_view(app)

    pasta = Path(tempfile.mkdtemp(prefix="_smoke_cards_melhorias_"))
    arquivo = pasta / "controle.xlsx"
    _criar_planilha_vazia(arquivo)
    for modulo in (clientes_mod, propostas_mod, vendedores_mod, equipamentos_mod):
        modulo.CAMINHO_XLSX = arquivo
    try:
        with _Stubs() as stubs:
            tela = testar_contagem(app, stubs)
            testar_paginacao_tela(app, stubs, tela)
            tela.close()
        linha("TUDO OK")
    finally:
        for modulo in (clientes_mod, propostas_mod, vendedores_mod, equipamentos_mod):
            modulo.CAMINHO_XLSX = config.CAMINHO_XLSX
        sessao_mod.encerrar()
        shutil.rmtree(pasta, ignore_errors=True)


if __name__ == "__main__":
    main()
