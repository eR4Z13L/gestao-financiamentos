"""Testa a tela do Dashboard (desktop/screens/dashboard_screen.py e os widgets dela) sem abrir uma janela de
verdade (QT_QPA_PLATFORM=offscreen), no estilo do Windows 11, nos DOIS temas, como ADMIN e como VENDEDOR
(as duas fontes de leitura simuladas, sem rede). Etapa 2.2: 4 cartoes das vendas, Por banco com a demora e a linha
Todos, resumo para copiar.

Tudo com uma planilha 100% FICTICIA (scripts/fixture_ficticia.py) e vendas criadas pela propria regra do app
(core/vendas.py), preferencias num .ini temporario e o Google desligado (ver scripts/ambiente_de_teste.py) - nada
real. Os numeros das vendas e das tabelas vem de core/dashboard.py (testado a parte, sem Qt, em
smoke_test_dashboard_core.py): aqui se confere que a TELA mostra exatamente isso, que cada cartao e cada linha
clicavel leva a pessoa ao lugar certo, que cabe numa janela de 1366x768 sem rolar e o que so o ADMIN (ou so o
VENDEDOR) ve.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_dashboard_screen.py
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")  # sem tela o Qt nao acha fontes

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QWidget

import fixture_ficticia as fx
from ambiente_de_teste import Ambiente, Mensagens
from core import bancos as bancos_mod
from core import clientes as clientes_mod
from core import dashboard as dash
from core import propostas as propostas_mod
from core import vendas as v
from core.formatting import formatar_reais
from desktop.screens.vendas_screen import FILTRO_COM_PENDENCIAS, FILTRO_PARADAS
from desktop.theme import CORES_STATUS, PALETAS, TEMA_CLARO, TEMA_ESCURO
from desktop.widgets.linha_clicavel import LinhaClicavel
from desktop.widgets.tabela_de_painel import COR_ERRO

TEMAS = (TEMA_ESCURO, TEMA_CLARO)
NOME_DA_OUTRA_VENDEDORA = "Vendedora Teste Dois"
HOJE = date.today()
LARGURA, ALTURA = 1366, 700  # a area util de uma janela maximizada num notebook 1366x768 (sem a barra de titulo e a de tarefas)


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


# -- auxiliares ------------------------------------------------------------------------------------


def _widgets(cartao) -> list[QWidget]:
    return [cartao.corpo.itemAt(i).widget() for i in range(cartao.corpo.count()) if cartao.corpo.itemAt(i).widget() is not None]


def _indices_da_lista(tela_propostas) -> set[int]:
    return {item.proposta.indice for item in tela_propostas.propostas_visiveis()}


def _clicar(widget: QWidget, ponto: QPoint | None = None) -> None:
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ponto if ponto is not None else widget.rect().center())


def _cliques_no_cabecalho(tabela, coluna: int) -> None:
    cabecalho = tabela.horizontalHeader()
    _clicar(cabecalho.viewport(), QPoint(cabecalho.sectionViewportPosition(coluna) + 8, cabecalho.height() // 2))


def _contar_pixels(imagem: QImage, cor: QColor, area: QRect, tolerancia: int = 6) -> int:
    total = 0
    for y in range(max(area.top(), 0), min(area.bottom() + 1, imagem.height())):
        for x in range(max(area.left(), 0), min(area.right() + 1, imagem.width())):
            c = imagem.pixelColor(x, y)
            if abs(c.red() - cor.red()) <= tolerancia and abs(c.green() - cor.green()) <= tolerancia and abs(c.blue() - cor.blue()) <= tolerancia:
                total += 1
    return total


def _pct(valor: float) -> str:
    """Como o Dashboard escreve um percentual (uma casa, virgula): "27,0%". Independente do codigo da tela, de proposito."""
    return f"{valor:.1f}".replace(".", ",") + "%"


def _taxa_do_texto(texto: str) -> float:
    return -1.0 if texto == "—" else float(texto.rstrip("%").replace(",", "."))


def _dashboard(janela):
    return janela._tela_dashboard


def _cartoes(tela):
    return tela._card_andamento, tela._card_paradas, tela._card_efetivadas, tela._card_pendencias


def _linhas_por_banco(tabela) -> dict[str, int]:
    return {tabela.texto_da_celula(i, 0): i for i in range(tabela.total_de_linhas())}


def bd_todas(amb: Ambiente) -> pd.DataFrame:
    """Todas as propostas da planilha fictícia, sem filtro de vendedor (pra comparar com o que o vendedor ve)."""
    from core import data_store as bd

    return bd.ler_propostas(amb.caminho)


class Vendas:
    """As vendas que o teste cria (pela regra do app, como ADMIN) e o que cada uma deve render nos cartoes."""

    def __init__(self, amb: Ambiente):
        amb.entrar_como("admin")
        self.banco1, self.banco2 = bancos_mod.nomes_ativos()[:2]

        def pedido(banco: str, status: str, valor: int, dias: int) -> dict:
            return {"BANCO": banco, "VALOR (R$)": valor, "MESES": 12, "DATA": pd.Timestamp(HOJE - timedelta(days=dias)), "STATUS": status}

        # em andamento: banco 1 respondeu (Aprovado) 10 dias depois do envio e o cliente fechou com ele
        self.andamento, p = v.criar_venda(fx.CPF_MARIA, ["Torno A"], pedido(self.banco1, propostas_mod.STATUS_EM_ANALISE, 10000, 10))
        v.mudar_status_proposta(p, propostas_mod.STATUS_APROVADO)
        v.fechar_proposta(p)
        # aguardando bancos
        self.aguardando, _ = v.criar_venda(fx.CPF_JOAO, ["Torno B"], pedido(self.banco2, propostas_mod.STATUS_EM_ANALISE, 4000, 4))
        # efetivada hoje (a proposta ja nasceu Aprovada: a efetivacao nao e "resposta do banco")
        self.efetivada, p = v.criar_venda(fx.CPF_ANA, ["Torno C"], pedido(self.banco1, propostas_mod.STATUS_APROVADO, 8000, 2))
        v.fechar_proposta(p)
        v.efetivar_proposta(p)
        # aguardando bancos, com uma pendencia aberta
        self.com_pendencia, _ = v.criar_venda(fx.CPF_JOAO, ["Torno D"], pedido(self.banco2, propostas_mod.STATUS_EM_ANALISE, 2000, 1))
        v.adicionar_pendencia(self.com_pendencia, "Equipamento ainda na fábrica")


# -- testes ---------------------------------------------------------------------------------------------


def testar_os_4_cartoes(amb: Ambiente, msgs: Mensagens, tema: str, vendas: Vendas) -> None:
    linha(f"1) Os 4 cartoes das vendas [{tema}]")
    janela = amb.nova_janela("admin", tema)
    tela = _dashboard(janela)
    andamento, paradas, efetivadas, pendencias = _cartoes(tela)

    dias = propostas_mod.DIAS_PROPOSTA_PARADA
    assert [c.titulo() for c in _cartoes(tela)] == ["Vendas em andamento", f"Paradas há {dias}+ dias", "Efetivadas no mês", "Com pendências"]
    assert andamento.valor() == "3" and andamento.detalhe() == f"{formatar_reais(10000)} em propostas fechadas", "as 3 vendas abertas; so o banco FECHADO da 1a conta no valor"
    assert paradas.valor() == "0" and paradas.detalhe() == "Nenhuma venda parada" and not paradas.valor_em_aviso() and not paradas.detalhe_em_aviso()
    assert efetivadas.valor() == "1" and efetivadas.detalhe() == formatar_reais(8000)
    assert pendencias.valor() == "1" and pendencias.detalhe() == "" and not pendencias.detalhe_em_aviso()
    assert [c.eh_clicavel() for c in _cartoes(tela)] == [False, True, False, True], "so Paradas e Com pendencias levam a Vendas"
    assert paradas.acao() == pendencias.acao() == "Ver na tela Vendas →" and andamento.acao() == ""
    print("OK: em andamento 3 (R$ 10.000,00 nos bancos fechados), paradas 0, efetivadas no mes 1 (R$ 8.000,00), com pendencias 1.")

    # daqui a 7 dias: as 3 vendas abertas passam do limite; a efetivada so conta se o mes nao virou
    tela._hoje = lambda: HOJE + timedelta(days=dias)
    tela._carregar_dados()
    assert paradas.valor() == "3" and paradas.valor_em_aviso() and paradas.detalhe_em_aviso() and paradas.detalhe() == "Precisam de atenção"
    mesmo_mes = (HOJE + timedelta(days=dias)).month == HOJE.month
    assert efetivadas.valor() == ("1" if mesmo_mes else "0")
    assert andamento.valor() == "3" and pendencias.valor() == "1"
    imagem = paradas._valor.grab().toImage()
    ambar = QColor(CORES_STATUS[tema]["em_analise"]["texto"])
    assert _contar_pixels(imagem, ambar, imagem.rect(), 10) > 10, "o numero das paradas e desenhado em ambar"
    imagem_zero = andamento._valor.grab().toImage()
    assert _contar_pixels(imagem_zero, ambar, imagem_zero.rect(), 10) == 0, "so as paradas ficam em ambar"
    del tela._hoje
    tela._carregar_dados()
    assert paradas.valor() == "0" and not paradas.valor_em_aviso()
    imagem = paradas._valor.grab().toImage()
    assert _contar_pixels(imagem, ambar, imagem.rect(), 10) == 0, "voltando a 0 o numero deixa de ser ambar"
    print("OK: com 7 dias a mais as 3 vendas abertas ficam paradas (numero em ambar); voltando, o ambar some.")

    # o periodo NAO mexe nos cartoes (so no Por banco e no resumo)
    antes = [(c.valor(), c.detalhe()) for c in _cartoes(tela)]
    tela.definir_periodo("hoje")
    assert [(c.valor(), c.detalhe()) for c in _cartoes(tela)] == antes
    tela.definir_periodo("tudo")
    print("OK: trocar o periodo (Hoje) nao muda nenhum dos 4 numeros.")
    msgs.exigir_sem_erros("cartoes")


def testar_cliques_dos_cartoes(amb: Ambiente, msgs: Mensagens, tema: str, vendas: Vendas) -> None:
    linha(f"2) Clicar nos cartoes leva a Vendas ja filtrada [{tema}]")
    janela = amb.nova_janela("admin", tema)
    tela = _dashboard(janela)
    tela_vendas = janela._tela_vendas
    andamento, paradas, efetivadas, pendencias = _cartoes(tela)

    # so Paradas e Com pendencias reagem; soltar o mouse fora do cartao ou clicar com o botao direito nao abre
    reagiram = []
    for cartao in _cartoes(tela):
        cartao.clicado.connect(lambda c=cartao: reagiram.append(c.titulo()))
    _clicar(andamento)
    _clicar(efetivadas)
    QTest.mousePress(paradas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, paradas.rect().center())
    QTest.mouseRelease(paradas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(-30, -30))
    QTest.mouseClick(paradas, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, paradas.rect().center())
    QTest.keyClick(andamento, Qt.Key.Key_Return)
    assert reagiram == [] and janela.chave_atual() == "dashboard", reagiram
    print("OK: Em andamento e Efetivadas nao sao clicaveis; soltar fora ou clicar com o direito no cartao tambem nao abre nada.")

    tela_vendas.busca.setText("algo que escondia tudo")  # a busca digitada antes nao pode esconder as vendas do cartao
    _clicar(pendencias)
    assert janela.chave_atual() == "vendas" and tela_vendas.filtro.currentText() == FILTRO_COM_PENDENCIAS
    assert tela_vendas.busca.text() == "" and [x.id for x in tela_vendas.vendas_visiveis()] == [vendas.com_pendencia]
    assert tela_vendas.contador.text().startswith("1 venda(s)")
    print("OK: 'Com pendencias' abre Vendas no filtro certo, sem a busca, so com a venda que tem pendencia.")

    janela.ir_para("dashboard")
    _clicar(paradas)
    assert janela.chave_atual() == "vendas" and tela_vendas.filtro.currentText() == FILTRO_PARADAS
    assert tela_vendas.contador.text().startswith("0 venda(s)"), "hoje nao ha venda parada"
    print("OK: 'Paradas' abre Vendas no filtro 'Paradas ha 7 dias ou mais'.")

    # com um card ABERTO fora do filtro e a lista rolada: o cartao "Paradas: 3" mostra exatamente 3 vendas, no inicio
    class _Daqui7Dias(date):
        @classmethod
        def today(cls):
            return HOJE + timedelta(days=propostas_mod.DIAS_PROPOSTA_PARADA)

    date_original, v.date = v.date, _Daqui7Dias
    try:
        tela._hoje = lambda: _Daqui7Dias.today()
        tela._carregar_dados()
        assert paradas.valor() == "3"
        janela.ir_para("vendas")
        tela_vendas.filtro.setCurrentText("Todas")
        efetivada = next(x for x in tela_vendas._vendas if x.id == vendas.efetivada)
        assert tela_vendas.lista.abrir_venda(efetivada) and tela_vendas.lista.aberta == vendas.efetivada
        assert len(tela_vendas.lista.cards) >= 4
        janela.resize(1366, 420)  # janela baixa: a lista rola, e a pessoa estava la embaixo
        for _ in range(4):
            QApplication.processEvents()
        barra = tela_vendas.rolagem.verticalScrollBar()
        barra.setValue(barra.maximum())
        assert barra.value() > 0, "o teste precisa de uma lista rolada"
        janela.ir_para("dashboard")
        _clicar(paradas)
        assert janela.chave_atual() == "vendas" and tela_vendas.filtro.currentText() == FILTRO_PARADAS
        assert tela_vendas.lista.aberta is None, "o card aberto fecha: ele apareceria mesmo fora do filtro"
        assert len(tela_vendas.lista.cards) == 3 and tela_vendas.contador.text().startswith("3 venda(s)")
        assert {c.venda.id for c in tela_vendas.lista.cards} == {vendas.andamento, vendas.aguardando, vendas.com_pendencia}
        assert not any(c.aberto for c in tela_vendas.lista.cards)
        assert tela_vendas.rolagem.verticalScrollBar().value() == 0, "volta ao inicio da lista"
    finally:
        v.date = date_original
        del tela._hoje
    tela._carregar_dados()
    print("OK: com um card aberto, clicar em 'Paradas: 3' fecha o card e mostra exatamente as 3 vendas, no inicio da lista.")

    # teclado: Tab chega no cartao e Enter/Espaco abrem
    for tecla in (Qt.Key.Key_Return, Qt.Key.Key_Space):
        janela.ir_para("dashboard")
        tela_vendas.filtro.setCurrentText("Todas")
        pendencias.setFocus()
        QTest.keyClick(pendencias, tecla)
        assert janela.chave_atual() == "vendas" and tela_vendas.filtro.currentText() == FILTRO_COM_PENDENCIAS
    assert pendencias.focusPolicy() == Qt.FocusPolicy.TabFocus
    print("OK: pelo teclado (foco + Enter ou Espaco) o cartao tambem abre.")

    # com edicao NAO salva em algum card: pergunta antes de sair do que esta editando
    janela.ir_para("propostas")
    tela_propostas = janela._tela_propostas
    tela_propostas.lista.abrir_proposta(tela_propostas.propostas_visiveis()[0])
    tela_propostas.lista.card_aberto().formulario._observacoes.setPlainText("rascunho de teste")
    assert janela.tem_edicao_pendente()
    janela.ir_para("dashboard")
    msgs.limpar()
    msgs.resposta_pergunta = QMessageBox.StandardButton.No
    _clicar(paradas)
    assert janela.chave_atual() == "dashboard" and msgs.ultima()[0] == "question" and "não foram salvas" in msgs.ultima()[2]
    msgs.resposta_pergunta = QMessageBox.StandardButton.Yes
    _clicar(paradas)
    assert janela.chave_atual() == "vendas" and tela_vendas.filtro.currentText() == FILTRO_PARADAS
    print("OK: com uma edicao nao salva, o clique pergunta antes (Não = continua no Dashboard, Sim = segue para Vendas).")

    # as outras telas continuam como eram: o filtro invalido e erro explicito
    try:
        tela_vendas.aplicar_filtro("nao existe")
    except ValueError as exc:
        assert "nao existe" in str(exc)
    else:
        raise AssertionError("filtro desconhecido tem que dar erro")
    msgs.exigir_sem_erros("cliques dos cartoes")


def testar_por_banco(amb: Ambiente, msgs: Mensagens, tema: str, vendas: Vendas) -> None:
    linha(f"3) Por banco: periodo, demora, linha Todos, ordenacao e cliques [{tema}]")
    janela = amb.nova_janela("admin", tema)
    tela = _dashboard(janela)
    tabela = tela._tabela_bancos
    propostas = propostas_mod.listar_propostas()
    esperado = dash.por_banco(propostas)

    assert [tabela._modelo.headerData(c, Qt.Orientation.Horizontal) for c in range(tabela._modelo.columnCount())] == [
        "Banco", "Enviadas", "Aprovadas", "Negadas", "Em análise", "Taxa", "Demora para responder"], "sem a coluna Aviso"
    enviadas = [int(t) for t in tabela.textos_da_coluna(1)]
    assert sorted(enviadas, reverse=True) == enviadas and sum(enviadas) == len(propostas), "mais enviadas primeiro; nenhuma proposta some"
    assert sorted(tabela.textos_da_coluna(0)) == sorted(esperado["Banco"])
    rodape = tabela.textos_do_rodape()
    total = dash.total_por_banco(propostas)
    assert rodape[:5] == ["Todos", str(total["Enviadas"]), str(total["Aprovadas"]), str(total["Negadas"]), str(total["Em Análise"])]
    assert rodape[5] == _pct(total["Taxa (%)"]) and int(rodape[1]) == len(propostas)
    assert tabela._modelo.item(tabela.total_de_linhas(), 0).font().bold() and not tabela._modelo.item(0, 0).font().bold(), "o rodape em negrito"
    print("OK: as linhas do core, mais enviadas primeiro, e a linha 'Todos' (em negrito) fecha com o total de propostas.")

    # a demora: a unica proposta que o banco 1 respondeu levou 10 dias (Em Analise -> Aprovado); o banco 2 ainda nao respondeu
    linhas = _linhas_por_banco(tabela)
    assert tabela.texto_da_celula(linhas[vendas.banco1], 6) == "10 dias", "mediana de uma so resposta"
    assert tabela.texto_da_celula(linhas[vendas.banco2], 6) == "—", "banco sem resposta"
    assert rodape[6] == "10 dias"
    print("OK: 'Demora para responder' = 10 dias no banco que respondeu, '—' no que nao respondeu; Todos = 10 dias.")

    # a linha Todos fica por ultimo, em qualquer ordenacao, e nao e clicavel
    def rodape_no_fim() -> None:
        assert tabela.textos_do_rodape()[0] == "Todos" and tabela.total_de_linhas() == len(esperado)
        assert tabela.texto_da_celula(tabela.total_de_linhas(), 0) == "Todos", "o rodape e a ultima linha do modelo"

    _cliques_no_cabecalho(tabela, 0)
    nomes = [n.casefold() for n in tabela.textos_da_coluna(0)]
    assert nomes == sorted(nomes), "1o clique no cabecalho: A-Z"
    rodape_no_fim()
    _cliques_no_cabecalho(tabela, 0)
    nomes = [n.casefold() for n in tabela.textos_da_coluna(0)]
    assert nomes == sorted(nomes, reverse=True), "2o clique: Z-A"
    rodape_no_fim()
    _cliques_no_cabecalho(tabela, 5)
    taxas = [_taxa_do_texto(t) for t in tabela.textos_da_coluna(5)]
    assert taxas == sorted(taxas), f"a taxa ordena como NUMERO, veio {taxas}"
    rodape_no_fim()
    _cliques_no_cabecalho(tabela, 5)
    taxas = [_taxa_do_texto(t) for t in tabela.textos_da_coluna(5)]
    assert taxas == sorted(taxas, reverse=True)
    rodape_no_fim()
    _cliques_no_cabecalho(tabela, 6)
    rodape_no_fim()
    print("OK: clicar no cabecalho ordena as linhas dos bancos (texto e numero, nos dois sentidos); 'Todos' nunca sai do fim.")

    pedidos = []
    tela.filtro_pedido.connect(pedidos.append)
    _clicar(tabela.viewport(), tabela.centro_da_linha(_linhas_por_banco(tabela)[vendas.banco1]))
    assert len(pedidos) == 1 and pedidos[0].chave == dash.FILTRO_BANCO and pedidos[0].parametro == vendas.banco1.upper()
    pedidos.clear()
    janela.ir_para("dashboard")  # o clique no banco levou a Todas as Propostas
    _clicar(tabela.viewport(), tabela.visualRect(tabela._modelo.index(tabela.total_de_linhas(), 0)).center())
    assert pedidos == [], "clicar na linha 'Todos' nao filtra nada"
    assert janela.chave_atual() == "dashboard"
    print("OK: clicar num banco pede o filtro daquele banco; a linha 'Todos' nao e clicavel.")

    # o periodo vale para Por banco e para o resumo
    tela.definir_periodo("hoje")
    hoje_ = pd.Timestamp(HOJE)
    de_hoje = propostas[pd.to_datetime(propostas["DATA"]).dt.normalize() == hoje_]
    assert tabela.textos_do_rodape()[1] == str(len(de_hoje)) and tabela.total_de_linhas() == len(dash.por_banco(de_hoje))
    assert "hoje" in tela._rotulo_do_resumo.text().splitlines()[1]
    tela.definir_periodo("tudo")
    print("OK: o periodo Hoje refaz o Por banco e o resumo.")

    # "Todos" e "(sem banco)" viram 'revisar' (nome em vermelho) e ficam fora da taxa
    tela._propostas = fx.montar_propostas(
        dict(BANCO="Todos", STATUS="Aprovado"), dict(BANCO="", STATUS="Negado"), dict(BANCO="Mova HTM", STATUS="Aprovado"), dict(BANCO="Santander", STATUS="Aprovado"),
        dict(BANCO="Santander", STATUS="Negado"),
    )
    tela._atualizar()
    linhas = _linhas_por_banco(tabela)
    assert "Todos" not in linhas, "o 'Todos' digitado como banco nao se confunde com a linha 'Todos' do rodape"
    assert tabela.textos_do_rodape()[0] == "Todos"
    for nome in ("Todos (banco digitado)", dash.ROTULO_SEM_BANCO):
        i = linhas[nome]
        assert tabela.texto_da_celula(i, 5) == "—" and tabela.barra_da_celula(i, 5) is None and tabela.cor_da_celula(i, 0) == COR_ERRO
    assert tabela.texto_da_celula(linhas["Mova HTM"], 5) == "100,0%" and tabela.texto_da_celula(linhas["Santander"], 5) == "50,0%"
    assert tabela.textos_do_rodape()[1] == "5" and tabela.textos_do_rodape()[5] == _pct(60), "Todos soma tambem o 'Todos' digitado e a sem banco"

    # a mini-barra e DESENHADA: verde proporcional na celula da taxa; sem taxa nao ha barra
    QApplication.processEvents()
    assert tabela.isVisible(), "a tela do Dashboard tem que estar na frente (senao a foto do widget sai incompleta)"
    imagem = tabela.viewport().grab().toImage()
    verde = QColor(CORES_STATUS[tema]["aprovado"]["faixa"])

    def barra_em(linha_: int) -> int:
        retangulo = tabela.visualRect(tabela._modelo.index(linha_, 5))
        return _contar_pixels(imagem, verde, QRect(retangulo.left(), retangulo.bottom() - 12, retangulo.width(), 10), 8)

    assert barra_em(linhas["Mova HTM"]) > barra_em(linhas["Santander"]) > barra_em(linhas["Todos (banco digitado)"]) == 0
    print("OK: 'Todos' e '(sem banco)' ficam fora da taxa (nome em vermelho); a mini-barra tem o tamanho proporcional.")
    msgs.exigir_sem_erros("por banco")


def testar_resumo(amb: Ambiente, msgs: Mensagens, tema: str, vendas: Vendas) -> None:
    linha(f"4) Resumo para copiar [{tema}]")
    janela = amb.nova_janela("admin", tema)
    tela = _dashboard(janela)
    propostas = propostas_mod.listar_propostas()

    mes = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"][HOJE.month - 1]
    primeira = tela._rotulo_do_resumo.text().splitlines()[0]
    assert primeira == f"Vendas ({mes} de {HOJE.year}): 3 em andamento, 0 paradas há 7+ dias, 1 efetivada no mês ({formatar_reais(8000)}), 1 com pendência."
    assert tela._rotulo_do_resumo.text() == tela._texto_do_resumo
    linhas = tela._rotulo_do_resumo.text().splitlines()
    assert linhas[1] == "Bancos em todo o período:" and linhas[-1].startswith("- Todos: ") and len(linhas) == 2 + len(dash.por_banco(propostas)) + 1
    assert f"- {vendas.banco1}: " in tela._rotulo_do_resumo.text() and "responde em 10 dias" in tela._rotulo_do_resumo.text()
    nomes = [c for c in clientes_mod.listar_clientes()["CLIENTE"] if c]
    assert nomes and not [n for n in nomes if n.upper() in tela._texto_do_resumo.upper()], "nenhum nome de cliente no resumo"
    QApplication.clipboard().setText("antes")
    tela._botao_copiar_resumo.click()
    assert QApplication.clipboard().text() == tela._texto_do_resumo
    tela.definir_periodo("7d")
    tela._botao_copiar_resumo.click()
    assert QApplication.clipboard().text() == tela._texto_do_resumo and linhas[1] != tela._texto_do_resumo.splitlines()[1]
    assert tela._texto_do_resumo.splitlines()[1] == "Bancos nos últimos 7 dias:"
    assert tela._texto_do_resumo.splitlines()[0] == primeira, "a linha das vendas nao segue o periodo"
    tela.definir_periodo("tudo")
    print("OK: o resumo e o texto do core, o botao Copiar copia exatamente ele; so a parte dos bancos segue o periodo; sem nomes de clientes.")
    msgs.exigir_sem_erros("resumo")


def testar_cabe_sem_rolar_e_aparencia(amb: Ambiente, msgs: Mensagens, tema: str, vendas: Vendas) -> None:
    linha(f"5) Cabe em 1366x768 sem rolagem; rotulos sem fundo; cores e troca de tema [{tema}]")
    janela = amb.nova_janela("admin", tema)
    janela.resize(LARGURA, ALTURA)
    tela = _dashboard(janela)
    janela.ir_para("dashboard")
    for _ in range(4):
        QApplication.processEvents()
    barra = tela._rolagem.verticalScrollBar()
    assert barra.maximum() == 0, f"o Dashboard rola {barra.maximum()}px em {LARGURA}x{ALTURA}"
    assert tela._rolagem.horizontalScrollBar().maximum() == 0
    conteudo = tela._rolagem.widget()
    assert conteudo.minimumSizeHint().height() <= tela._rolagem.viewport().height(), (conteudo.minimumSizeHint().height(), tela._rolagem.viewport().height())
    rotulo = tela._rotulo_do_resumo
    assert rotulo.height() >= rotulo.heightForWidth(rotulo.width()), "o texto do resumo aparece inteiro (nao e espremido)"
    assert len({(c._legenda.y(), c._legenda.height(), c._valor.y()) for c in _cartoes(tela)}) == 1, "o titulo e o numero dos 4 cartoes alinhados (o texto nao desce no cartao mais folgado)"
    cartoes = _cartoes(tela)
    assert all(c.isVisible() for c in cartoes) and len({c.height() for c in cartoes}) == 1, "os 4 cartoes na mesma altura"
    print(f"OK: em {LARGURA}x{ALTURA} nao ha rolagem (sobram {tela._rolagem.viewport().height() - conteudo.minimumSizeHint().height()}px).")

    # rotulos sem fundo proprio (senao aparece uma faixa atras do texto, sobre o card)
    sem_fundo = [
        l.text()
        for l in tela.findChildren(QLabel)
        if l.isVisible() and l.width() > 4 and l.property("role") not in ("campo_rotulo", "campo_valor") and l.grab().toImage().pixelColor(0, 0).alpha() != 0
    ]
    assert not sem_fundo, f"rotulos com fundo proprio (faixa escura atras do texto): {sem_fundo[:5]}"
    paleta = PALETAS[tema]
    card = tela._card_andamento
    legenda = card._valor
    imagem = card.grab().toImage()
    ponto = legenda.mapTo(card, QPoint(legenda.width() - 3, 3))
    assert imagem.pixelColor(ponto).name() == QColor(paleta["bg_card"]).name(), "atras do texto aparece a cor do proprio card"
    print("OK: nenhum rotulo tem fundo proprio e, onde nao ha letra, o fundo do cartao e o do card.")

    # trocar o tema refaz as cores dos desenhos (tabela, ambar do numero)
    tela._hoje = lambda: HOJE + timedelta(days=propostas_mod.DIAS_PROPOSTA_PARADA)
    tela._carregar_dados()
    assert tela._card_paradas.valor_em_aviso()
    inicial = janela._tema_atual
    janela._alternar_tema()
    novo = TEMA_CLARO if inicial == TEMA_ESCURO else TEMA_ESCURO
    assert tela._tabela_bancos._delegado._paleta is PALETAS[novo]
    imagem = tela._card_paradas._valor.grab().toImage()
    assert _contar_pixels(imagem, QColor(CORES_STATUS[novo]["em_analise"]["texto"]), imagem.rect(), 10) > 10, "o numero ambar muda de cor com o tema"
    janela._alternar_tema()
    del tela._hoje
    print("OK: trocar o tema refaz a paleta da tabela e a cor ambar do numero.")

    # gravar em outra tela marca o Dashboard como desatualizado; voltar a ele relê os dados
    janela.ir_para("dashboard")
    assert tela._card_andamento.valor() == "3"
    v.mudar_status_venda(vendas.aguardando, v.VENDA_PERDIDA, motivo="Desistiu")
    tela.marcar_como_desatualizado()
    janela.ir_para("propostas")
    janela.ir_para("dashboard")
    assert not tela._desatualizado and tela._card_andamento.valor() == "2", "ao voltar, o Dashboard releu as vendas (uma perdida a menos)"
    v.reabrir_venda(vendas.aguardando)  # devolve a fixture ao que era
    tela.marcar_como_desatualizado()
    janela.ir_para("propostas")
    janela.ir_para("dashboard")
    assert tela._card_andamento.valor() == "3"
    print("OK: marcado como desatualizado, ao voltar o Dashboard releu (uma venda perdida = 2 em andamento; reaberta, 3).")
    msgs.exigir_sem_erros("aparencia")


def testar_visao_do_vendedor(amb: Ambiente, msgs: Mensagens, tema: str, vendas: Vendas | None) -> None:
    linha(f"6) Visao do VENDEDOR: so o dele, sem nome de outro vendedor [{tema}]")
    for nome, outro in (("Vendedor Exemplo", NOME_DA_OUTRA_VENDEDORA), (NOME_DA_OUTRA_VENDEDORA, "Vendedor Exemplo")):
        janela = amb.nova_janela("vendedor", tema, nome=nome)
        tela = _dashboard(janela)
        minhas = propostas_mod.listar_propostas()  # ja filtrada pelo vendedor logado (a "rede" e simulada pelo Ambiente)
        assert 0 < len(minhas) < len(bd_todas(amb)), "o vendedor so ve as proprias propostas"

        for ausente in ("_card_andamento", "_card_paradas", "_card_efetivadas", "_card_pendencias", "_cartao_atencao", "_cartao_qualidade",
                        "_tabela_vendedores", "_cartao_vendedores", "_funil", "_cartao_funil", "_card_taxa", "_card_mediano"):
            assert not hasattr(tela, ausente), f"o vendedor nao tem {ausente}"
            assert tela._tabela_bancos.isColumnHidden(6), "a leitura do vendedor nao tem o historico: sem a coluna da demora"
        assert tela._vendas == [] and tela._historico is None, "a leitura do vendedor nao tem as vendas nem o historico: a tela nao tenta le-los"
        assert tela._texto_do_resumo == dash.resumo_para_copiar(minhas) and "Vendas (" not in tela._texto_do_resumo

        # as tres listas dele
        for cartao, etapa in ((tela._cartao_minhas_em_analise, propostas_mod.ETAPA_EM_ANALISE), (tela._cartao_minhas_a_efetivar, propostas_mod.ETAPA_APROVADO)):
            itens = dash.propostas_da_etapa(minhas, etapa)
            linhas = [w for w in _widgets(cartao) if isinstance(w, LinhaClicavel)]
            assert len(linhas) == min(len(itens), 8)
            if itens:
                assert linhas[0].text().startswith(itens[0].cliente), "a mais parada primeiro"
                assert itens[0].equipamento in linhas[0].toolTip(), "o equipamento vai no tooltip"
        sem_proposta = dash.clientes_sem_proposta(clientes_mod.listar_clientes(), minhas)
        linhas_clientes = [w for w in _widgets(tela._cartao_meus_clientes) if isinstance(w, LinhaClicavel)]
        assert [l.text() for l in linhas_clientes] == [n for _, n in sem_proposta[:8]]

        # NENHUM texto da tela cita o outro vendedor
        textos = [l.text() for l in tela.findChildren(QLabel)] + [l.text() for l in tela.findChildren(LinhaClicavel)] + [l.toolTip() for l in tela.findChildren(LinhaClicavel)]
        tabela = tela._tabela_bancos
        for coluna in range(7):
            textos += tabela.textos_da_coluna(coluna) + [tabela.textos_do_rodape()[coluna]]
        assert not [t for t in textos if outro.upper() in t.upper()], f"{nome}: a tela cita '{outro}'"
        assert tabela.textos_do_rodape()[1] == str(len(minhas)), "'Todos' soma so as propostas dele"
        print(f"OK: {nome}: as listas dele, Por banco sem demora, o resumo das propostas e nenhuma citacao a '{outro}'.")

        # cliques do vendedor: 'Ver todas' e uma linha (abre a ficha do cliente)
        if dash.propostas_da_etapa(minhas, propostas_mod.ETAPA_EM_ANALISE):
            tela._botao_ver_em_analise.click()
            esperado = {int(i) for i in minhas.index[minhas["STATUS"].map(propostas_mod.etapa_status) == propostas_mod.ETAPA_EM_ANALISE]}
            assert janela.chave_atual() == "propostas" and _indices_da_lista(janela._tela_propostas) == esperado
            janela._tela_propostas._botao_limpar_filtros.click()
            janela.ir_para("dashboard")
            [w for w in _widgets(tela._cartao_minhas_em_analise) if isinstance(w, LinhaClicavel)][0].click()
            assert janela.chave_atual() == "ficha" and janela._tela_ficha._cpf_selecionado is not None
        if linhas_clientes:
            janela.ir_para("dashboard")
            linhas_clientes[0].click()
            assert janela.chave_atual() == "ficha" and janela._tela_ficha._campo_nome.text() == sem_proposta[0][1]
        print("OK: 'Ver todas' filtra por etapa (sem reler a 'rede'); uma linha abre a ficha do cliente.")
        janela.ir_para("dashboard")
    msgs.exigir_sem_erros("visao do vendedor")


def testar_bordas_do_vendedor(amb: Ambiente, msgs: Mensagens, tema: str, vendas: Vendas | None) -> None:
    linha(f"7) Bordas: vendedor sem nenhuma proposta [{tema}]")
    # o app inteiro abre pra um vendedor recem-cadastrado (antes o Dashboard quebrava e a janela nao abria)
    janela = amb.nova_janela("vendedor", tema, nome="Fulano Sem Propostas")
    tela = _dashboard(janela)
    assert tela._texto_do_resumo == "Nenhuma proposta." and tela._tabela_bancos.total_de_linhas() == 0
    assert tela._tabela_bancos.textos_do_rodape()[:6] == ["Todos", "0", "0", "0", "0", "—"]
    assert [w.text() for w in _widgets(tela._cartao_meus_clientes) if isinstance(w, QLabel)] == ["Todos os seus clientes têm proposta"]
    assert tela._botao_ver_em_analise.isHidden(), "sem propostas nao ha 'Ver todas'"
    print("OK: um vendedor sem nenhuma proposta abre a janela e o Dashboard mostra tudo zerado.")
    msgs.exigir_sem_erros("bordas do vendedor")


def testar_bordas_do_admin(amb: Ambiente, msgs: Mensagens, tema: str, vendas: Vendas) -> None:
    linha(f"8) Bordas: planilha sem propostas nem vendas, pendencia ilegivel, efetivada sem data [{tema}]")
    admin = amb.nova_janela("admin", tema)
    tela = _dashboard(admin)
    tela._propostas = fx.propostas_vazias()
    tela._vendas = []
    tela._atualizar()
    assert [c.valor() for c in _cartoes(tela)] == ["0", "0", "0", "0"]
    assert [c.detalhe() for c in _cartoes(tela)] == ["Nenhuma venda em andamento", "Nenhuma venda parada", "Nenhuma venda efetivada neste mês", "Nenhuma pendência aberta"]
    assert tela._tabela_bancos.total_de_linhas() == 0 and tela._texto_do_resumo.splitlines()[1] == "Nenhuma proposta enviada a bancos no período."
    print("OK: sem propostas e sem vendas nenhum bloco quebra e cada um mostra a sua mensagem.")

    # uma venda com a celula de pendencias ilegivel aparece como aviso (nunca some calada)
    resumo = v.ResumoDaVenda("V-x", "", "C", "V", "EQ", v.VENDA_AGUARDANDO, "", (), None, 1, "", (), None, (), "celula ilegivel")
    tela._vendas = [resumo]
    tela._atualizar()
    assert tela._card_pendencias.detalhe_em_aviso() and "ilegível" in tela._card_pendencias.detalhe()
    def efetivada(id_: str, valor: float) -> v.ResumoDaVenda:
        banco = v.PropostaNaVenda(f"P-{id_}", 0, "B", propostas_mod.STATUS_EFETIVADO, valor, 12, None, "EQ", True, None)
        return v.ResumoDaVenda(f"V-{id_}", "", "C", "V", "EQ", v.VENDA_EFETIVADA, "", (banco.id,), None, 1, "", (banco,), None, (), "")

    def historico(*linhas) -> pd.DataFrame:
        return pd.DataFrame([{"QUANDO": pd.Timestamp(q), "TIPO": tipo, "ID": i, "DE": "Aprovado", "PARA": "Efetivado", "MOTIVO": "", "COMPUTADOR": ""}
                             for i, q, tipo in linhas], columns=["QUANDO", "TIPO", "ID", "DE", "PARA", "MOTIVO", "COMPUTADOR"])

    # convertida dos dados antigos: so ha a linha de CONVERSAO, de hoje - nao e a data da efetivacao
    tela._vendas = [efetivada("y", 700.0)]
    tela._historico = historico(("P-y", HOJE, v.TIPO_CONVERSAO))
    tela._atualizar()
    assert tela._card_efetivadas.valor() == "0" and tela._card_efetivadas.detalhe_em_aviso()
    assert tela._card_efetivadas.detalhe() == "Nenhuma venda efetivada neste mês · 1 sem data de efetivação (fora da conta)", tela._card_efetivadas.detalhe()
    # uma no mes (com historico) e uma convertida: o texto inteiro, com o separador
    tela._vendas = [efetivada("y", 700.0), efetivada("z", 500.0)]
    tela._historico = historico(("P-y", HOJE, v.TIPO_CONVERSAO), ("P-z", HOJE, v.TIPO_PROPOSTA))
    tela._atualizar()
    assert tela._card_efetivadas.valor() == "1"
    assert tela._card_efetivadas.detalhe() == f"{formatar_reais(500)} · 1 sem data de efetivação (fora da conta)", tela._card_efetivadas.detalhe()
    print("OK: pendencia ilegivel e efetivada sem data aparecem como aviso nos cartoes.")
    msgs.exigir_sem_erros("bordas do admin")


def _uma_venda_para_o_vendedor_nao_ler(amb: Ambiente) -> None:
    """Ha uma venda e um historico no arquivo: a leitura do VENDEDOR (nuvem) nao os tem, e a tela dele nao os le."""
    from core import data_store as bd

    amb.entrar_como("admin")
    cpf = bd.ler_clientes(amb.caminho)["CPF/CNPJ"].iloc[0]
    v.criar_venda(cpf, ["Torno V"], {"BANCO": bancos_mod.nomes_ativos()[0], "VALOR (R$)": 100, "MESES": 12, "DATA": pd.Timestamp(HOJE),
                                     "STATUS": propostas_mod.STATUS_EM_ANALISE})
    assert v.listar_vendas(), "o teste precisa de uma venda no arquivo"


def _rodar(amb: Ambiente, msgs: Mensagens, testes, vendas: Vendas | None) -> None:
    for tema in TEMAS:
        for teste in testes:
            msgs.limpar()
            msgs.resposta_pergunta = QMessageBox.StandardButton.Yes
            amb.resetar_preferencias()  # senao a "ultima tela" do teste anterior abre a janela em outra tela
            teste(amb, msgs, tema, vendas)
            amb.limpar_janelas()


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    estilo_original = app.style().objectName()
    app.setStyle("windows11")  # o app real usa este estilo; o padrao sem tela (Fusion) esconderia diferencas
    try:
        with Mensagens() as msgs:
            amb = Ambiente()  # o ADMIN: a planilha pequena, com as vendas que o teste cria
            try:
                vendas = Vendas(amb)
                _rodar(amb, msgs, (testar_os_4_cartoes, testar_cliques_dos_cartoes, testar_por_banco, testar_resumo,
                                   testar_cabe_sem_rolar_e_aparencia, testar_bordas_do_admin), vendas)
            finally:
                amb.encerrar()
            amb = Ambiente(volumoso=True)  # o VENDEDOR: varios vendedores, pra ver que so as propostas dele aparecem
            try:
                _uma_venda_para_o_vendedor_nao_ler(amb)
                _rodar(amb, msgs, (testar_visao_do_vendedor, testar_bordas_do_vendedor), None)
            finally:
                amb.encerrar()
        ativos = [m for m in sys.modules if m.endswith(("funil_de_etapas", "linha_de_qualidade"))]
        assert not ativos, f"o Dashboard enxuto nao usa mais estes widgets (ficam no disco, sem uso): {ativos}"
        linha("TUDO OK")
    finally:
        app.setStyle(estilo_original)
        app.setStyleSheet("")


if __name__ == "__main__":
    main()
