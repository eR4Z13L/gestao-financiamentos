"""Testa Todas as Propostas com o card de proposta (passo 3, desenhado com o usuario em 04/10/2026):

1) um card por proposta (as das vendas e as de antes delas), em colunas que encaixam;
2) a ordem de quando a tela abre - as que esperam resposta ha mais tempo primeiro, os dias contados pelo HISTÓRICO
   (sem historico, pela DATA) -, e o "Carregar mais" que nunca esconde o card aberto;
3) as acoes rapidas no proprio card (bolinhas, ↩, anel, Efetivado…, a lista da etiqueta) gravando e relendo, e a
   rolagem que nao volta ao topo ao gravar;
4) dois cliques abrem a PROPRIA proposta no lugar (a largura da coluna, cresce para baixo, ninguem troca de coluna) e
   dois cliques no topo fecham; edicao nao salva pergunta; a proposta aberta nao some com a busca; a protecao contra
   gravar por cima de outra; excluir so de dentro do formulario, com confirmacao; a roda do mouse nao troca valor;
5) "Ver na venda →" abre a venda certa na tela Vendas, e o filtro que vem do Dashboard (o chip) continua valendo;
6) o VENDEDOR so le; nenhuma janela solta pisca; a grade do formulario; e o card antigo nao existe mais.

Dados FICTICIOS (scripts/fixture_ficticia.py), numa pasta temporaria; preferencias isoladas; o Google bloqueado.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_todas_as_propostas.py
"""

from __future__ import annotations

import importlib
import os
import sys
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

import config
config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
import fixture_ficticia as fx
from ambiente_de_teste import Ambiente, Mensagens
from core import bancos as bancos_mod
from core import dashboard as dashboard_mod
from core import data_store as bd
from core import equipamentos as equipamentos_mod
from core import propostas as propostas_mod
from core import vendas as v
from desktop.main_window import PAGINA_PROPOSTAS, PAGINA_VENDAS, MainWindow
from desktop.theme import TEMA_ESCURO
from desktop.widgets.card_da_proposta import CardDaProposta, CardNovaProposta, texto_da_espera
from desktop.widgets.card_da_venda import EFETIVAR, LARGURA_CARD
from desktop.widgets.formulario_proposta import FormularioProposta
from desktop.widgets.lista_de_propostas import chave_da_proposta

SIM, NAO = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No


class JanelasSoltas(QObject):
    """Anota toda janela que aparece fora a janela do app (um pedaco de card mostrado antes de ter dono pisca solto)."""

    def __init__(self):
        super().__init__()
        self.esperadas: list = []
        self.vistas: list[str] = []

    def eventFilter(self, objeto, evento) -> bool:
        if (evento.type() == QEvent.Type.Show and objeto.isWidgetType() and objeto.isWindow()
                and not isinstance(objeto, MainWindow) and objeto not in self.esperadas):
            self.vistas.append(type(objeto).__name__)
        return False


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _processar(n: int = 4) -> None:
    for _ in range(n):
        QApplication.processEvents()


def _cards(tela) -> list[CardDaProposta]:
    return [c for c in tela.lista.cards if isinstance(c, CardDaProposta)]


def _card(tela, chave: str) -> CardDaProposta:
    return next(c for c in _cards(tela) if chave_da_proposta(c.item) == chave)


def _item(tela, chave: str) -> v.PropostaNaLista:
    return next(i for i in tela.propostas_visiveis() if chave_da_proposta(i) == chave)


def _status(id_proposta: str) -> str:
    propostas = bd.ler_propostas(v._caminho())
    return propostas.loc[propostas["ID_PROPOSTA"] == id_proposta, "STATUS"].iloc[0]


def _duplo_clique(widget, ponto: QPoint) -> None:
    """Um duplo clique como o Windows o manda: press, release, press (que o Qt entrega como DblClick) e release."""
    QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=ponto)
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=ponto)
    evento = QMouseEvent(QEvent.Type.MouseButtonDblClick, QPointF(ponto), QPointF(widget.mapToGlobal(ponto)),
                         Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, evento)
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=ponto)


def _no_topo(card: CardDaProposta) -> QPoint:
    """Um ponto no topo do card (na altura do banco, longe dos botoes da direita)."""
    return QPoint(card.banco.geometry().left() + 4, card.banco.geometry().center().y())


def _montar_dados() -> dict:
    """Duas vendas por cima das propostas de antes das vendas da fixture. As propostas das vendas tem a DATA de 20
    dias atras, mas o HISTÓRICO diz que foram enviadas hoje: a espera conta do historico."""
    for nome in ("Cadeira Exemplo", "Laser Exemplo"):
        equipamentos_mod.cadastrar({"EQUIPAMENTO": nome})
    b1, b2 = "Santander", "Portobank"
    antigo = pd.Timestamp(date.today() - timedelta(days=20))
    id_a, pa1 = v.criar_venda(fx.CPF_MARIA, ["Cadeira Exemplo"], {"BANCO": b1, "VALOR (R$)": 40000, "MESES": 36,
                                                                 "DATA": antigo})
    pa2 = v.mandar_a_outro_banco(id_a, {"BANCO": b2, "VALOR (R$)": 42000, "MESES": 48, "DATA": antigo,
                                        "CARÊNCIA (DIAS)": 60, "PARCELA (R$)": 1200.5})
    v.mudar_status_proposta(pa2, propostas_mod.STATUS_PRE_APROVADO)
    id_b, pb = v.criar_venda(fx.CPF_JOAO, ["Laser Exemplo"], {"BANCO": b1, "VALOR (R$)": 30000, "MESES": 24,
                                                             "DATA": antigo})
    v.mudar_status_proposta(pb, propostas_mod.STATUS_APROVADO)
    antigas = propostas_mod.listar_propostas()
    antigas = antigas[antigas["ID_VENDA"] == ""]
    return {"id_a": id_a, "pa1": pa1, "pa2": pa2, "id_b": id_b, "pb": pb, "antigas": list(antigas.index)}


def testar_cards_e_ordem(tela, dados: dict) -> None:
    linha("1) Um card por proposta, em colunas que encaixam; a ordem de quando a tela abre")
    todas = propostas_mod.listar_propostas()
    assert tela.lista.total() == len(todas) and len(_cards(tela)) == len(todas)
    assert sorted(c.item.proposta.indice for c in _cards(tela)) == sorted(todas.index), "cada proposta, uma vez"
    assert tela.lista._colunas >= 2 and {tela.lista.coluna_do_card(c) for c in _cards(tela)} == set(range(tela.lista._colunas))
    largura = _cards(tela)[0].width()
    assert all(abs(c.width() - largura) <= 1 for c in _cards(tela)) and largura >= LARGURA_CARD, "colunas iguais"
    assert tela._ordenacao.currentData() == propostas_mod.ORDENACAO_ESPERANDO

    a1, a2, b = (_card(tela, dados[k]) for k in ("pa1", "pa2", "pb"))
    assert (a1.banco.text(), a1.pilula.text()) == ("Santander", "Em Análise")
    assert a1.cliente.text() == f"{a1.item.cliente} · Cadeira Exemplo" and a1.item.cliente, a1.cliente.text()
    assert a2.condicoes.text() == "R$ 42.000 · 48x · 1ª em 60 dias · parcela R$ 1.200,50", a2.condicoes.text()
    assert a1.sem_venda is None and a1.pilula.clicavel and len(a1.controles["bolinhas"]) == 2, "na venda: as ações rápidas"
    assert b.controles["anel"] is not None and not b.controles["anel"].fechado, "aprovada: o anel para marcar como fechado"
    assert a1.espera.text() == texto_da_espera(0) == "esperando desde hoje", "a espera conta do HISTÓRICO (enviada hoje)"
    assert a1.espera.property("role") == "secundario", "esperando há pouco: sem destaque"
    parada = next(c for c in _cards(tela) if c.item.proposta.dias_esperando is not None
                  and c.item.proposta.dias_esperando >= v.DIAS_PARA_ALERTA)
    assert parada.espera.property("role") == "aviso", f"parada há {parada.item.proposta.dias_esperando} dias: destacada"
    # o limite: 7 dias ja e "parada" (destacada); 6, ainda nao
    for dias, papel in ((v.DIAS_PARA_ALERTA, "aviso"), (v.DIAS_PARA_ALERTA - 1, "secundario")):
        proposta = v.PropostaNaVenda("", 0, "Banco", propostas_mod.STATUS_EM_ANALISE, 1.0, 12, None, "E", False, dias)
        card = CardDaProposta(v.PropostaNaLista(proposta, None, fx.CPF_ANA, "CLIENTE", "ANA"))
        assert card.espera.text() == texto_da_espera(dias) and card.espera.property("role") == papel, (dias, papel)
        card.deleteLater()
    assert v.DIAS_PARA_ALERTA == 7

    ordem = [i.proposta.indice for i in tela.propostas_visiveis()]
    itens = {i.proposta.indice: i for i in tela.propostas_visiveis()}
    esperando = [i for i in ordem if itens[i].proposta.dias_esperando is not None]
    assert ordem[: len(esperando)] == esperando, "primeiro as que esperam resposta"
    dias = [itens[i].proposta.dias_esperando for i in esperando]
    assert dias == sorted(dias, reverse=True), f"da que espera há mais tempo para a de menos: {dias}"
    indice_a1 = itens_por_id(tela)[dados["pa1"]].proposta.indice
    joao_em_analise = next(i for i in dados["antigas"] if itens[i].proposta.dias_esperando and itens[i].proposta.dias_esperando > 0)
    assert ordem.index(joao_em_analise) < ordem.index(indice_a1), \
        "a da venda (DATA de 20 dias atrás, mas enviada hoje pelo histórico) vem depois de uma antiga que espera há dias"
    print(f"OK: {len(todas)} cards em {tela.lista._colunas} colunas iguais; banco, cliente e equipamento, condições, "
          f"espera; abre com as que esperam há mais tempo (pelo histórico; sem ele, pela data): {dias}.")


def itens_por_id(tela) -> dict[str, v.PropostaNaLista]:
    return {i.proposta.id: i for i in tela.propostas_visiveis() if i.proposta.id}


def testar_acoes_rapidas(tela, dados: dict, msgs: Mensagens) -> None:
    linha("2) As ações rápidas no card gravam e a tela relê")
    pa1, pa2, pb = dados["pa1"], dados["pa2"], dados["pb"]
    card = _card(tela, pa1)
    aprovado = next(b for b in card.controles["bolinhas"] if b.destino == propostas_mod.STATUS_APROVADO)
    aprovado.click()
    _processar()
    assert _status(pa1) == propostas_mod.STATUS_APROVADO
    card = _card(tela, pa1)
    assert card.pilula.text() == "Aprovado" and card.controles["voltar"] is not None and card.espera is None
    assert card.controles["anel"] is not None, "aprovada: ganhou o anel"
    assert "Aprovado" in tela.faixa_aviso.texto.text(), tela.faixa_aviso.texto.text()
    card.controles["voltar"].click()
    _processar()
    assert _status(pa1) == propostas_mod.STATUS_EM_ANALISE and _card(tela, pa1).pilula.text() == "Em Análise"
    print("OK: a bolinha 'Aprovado' grava, o card mostra o novo status (com o anel e a ↩) e a ↩ volta.")

    # a lista da etiqueta: as respostas do banco
    item = itens_por_id(tela)[pa2]
    menu = tela.lista.controle.montar_menu_da_proposta(item.venda, item.proposta)
    next(a for a in menu.actions() if a.text() == propostas_mod.STATUS_NEGADO).trigger()
    _processar()
    assert _status(pa2) == propostas_mod.STATUS_NEGADO and _card(tela, pa2).pilula.text() == "Negado"
    print("OK: a lista da etiqueta troca a resposta do banco (Pré-aprovado → Negado).")

    # o anel (fechou com este banco) e o Efetivado… de um banco fechado
    _card(tela, pb).controles["anel"].click()
    _processar()
    card = _card(tela, pb)
    assert card.controles["anel"].fechado and card.controles["bolinhas"][0].destino == EFETIVAR
    msgs.resposta_pergunta = NAO
    card.controles["bolinhas"][0].click()
    _processar()
    assert _status(pb) == propostas_mod.STATUS_APROVADO, "'Não' no 'saiu o financiamento?': nada muda"
    msgs.resposta_pergunta = SIM
    _card(tela, pb).controles["bolinhas"][0].click()
    _processar()
    assert _status(pb) == v.PROPOSTA_EFETIVADA and _card(tela, pb).pilula.text() == "Efetivado"
    assert next(x for x in v.listar_vendas() if x.id == dados["id_b"]).status == v.VENDA_EFETIVADA
    print("OK: o anel marca o banco como fechado; a bolinha 'Efetivado…' pergunta e efetiva (a venda fica Efetivada).")


def testar_abrir_e_fechar(tela, dados: dict, msgs: Mensagens) -> None:
    linha("3) Dois cliques abrem a própria proposta no lugar; dois cliques no topo fecham")
    antes = {chave_da_proposta(c.item): (tela.lista.coluna_do_card(c), c.width(), c.y(), c.height()) for c in _cards(tela)}
    card = _card(tela, dados["pa1"])
    QTest.mouseClick(card, Qt.MouseButton.LeftButton, pos=_no_topo(card))
    _processar()
    assert tela.lista.aberta is None, "1 clique não abre"
    _duplo_clique(card, _no_topo(card))
    _processar(6)
    aberto = tela.lista.card_aberto()
    assert aberto is not None and aberto.aberto and chave_da_proposta(aberto.item) == dados["pa1"]
    coluna, largura, y, altura = antes[dados["pa1"]]
    # a largura e a da coluna: a mesma dos outros cards agora (a barra de rolagem que aparece tira uns px de todos)
    assert tela.lista.coluna_do_card(aberto) == coluna and abs(largura - aberto.width()) <= 20, (aberto.width(), largura)
    assert all(abs(c.width() - aberto.width()) <= 1 for c in _cards(tela)), "na largura da coluna, como os outros"
    assert aberto.y() == y and aberto.height() > altura, "cresce para baixo, sem sair do lugar"
    depois = {chave_da_proposta(c.item): tela.lista.coluna_do_card(c) for c in _cards(tela)}
    assert depois == {k: a[0] for k, a in antes.items()}, "ninguém troca de coluna"
    formulario = aberto.formulario
    assert formulario is not None and not formulario._modo_leitura and formulario._banco.currentText() == "Santander"
    assert aberto.ver_na_venda is not None and aberto.abrir_ficha is not None and aberto.botao_excluir is not None
    _duplo_clique(aberto, QPoint(_no_topo(aberto).x(), aberto._divisor.y() + 30))  # abaixo do topo: no formulario
    _processar()
    assert tela.lista.aberta == dados["pa1"], "dois cliques abaixo do topo (no formulário) não fecham"
    _duplo_clique(aberto, _no_topo(aberto))
    _processar()
    assert tela.lista.aberta is None, "dois cliques no topo do card aberto fecham"
    print("OK: 1 clique não abre; dois cliques abrem a própria proposta (formulário em edição, 'Ver na venda →', "
          "'Abrir a ficha', 'Excluir…'), na mesma coluna e largura, crescendo para baixo; dois cliques no topo fecham.")

    # um aberto por vez, e o digitado nunca some sem perguntar
    tela.lista.abrir_proposta(_item(tela, dados["pa1"]))
    tela.lista.card_aberto().formulario._observacoes.setPlainText("digitado e não salvo")
    msgs.limpar()
    msgs.resposta_pergunta = NAO
    assert not tela.lista.abrir_proposta(_item(tela, dados["pa2"]))
    assert msgs.ultima()[1] == "Alterações não salvas" and tela.lista.aberta == dados["pa1"]
    assert tela.lista.card_aberto().formulario._observacoes.toPlainText() == "digitado e não salvo"
    # a busca que tiraria a aberta da lista: ela continua (como na tela Vendas)
    tela._busca.setText("Hubcred que não existe")
    _processar()
    assert tela.lista.aberta == dados["pa1"] and tela.lista.card_aberto() is not None
    assert tela.lista.card_aberto().formulario._observacoes.toPlainText() == "digitado e não salvo", "nada se perdeu"
    assert tela._contador.text().startswith("0 proposta(s)"), "a contagem é a da busca"
    assert tela.lista.card_aberto().formulario.isVisible(), "e à vista"
    tela._busca.setText("")
    _processar()
    msgs.resposta_pergunta = SIM
    assert tela.lista.abrir_proposta(_item(tela, dados["pa2"])) and tela.lista.aberta == dados["pa2"]
    tela.lista.descartar()
    print("OK: outro card com algo digitado pergunta ('Não' segue no que estava); a busca não tira o card aberto da lista.")


def testar_gravar_por_cima_e_excluir(tela, dados: dict, msgs: Mensagens) -> None:
    linha("4) A proteção contra gravar por cima, e excluir só de dentro do formulário")
    antiga = next(i for i in dados["antigas"] if propostas_mod.listar_propostas().loc[i, "STATUS"] == propostas_mod.STATUS_EM_ANALISE)
    chave = f"#{antiga}"
    tela.lista.abrir_proposta(_item(tela, chave))
    card = tela.lista.card_aberto()
    assert card.sem_venda is not None and card.ver_na_venda is None, "de antes das vendas: sem 'Ver na venda'"
    formulario = card.formulario
    formulario._observacoes.setPlainText("o que eu digitei")
    propostas_mod.atualizar_proposta(antiga, {"OBSERVAÇÕES": "mudou em outra tela"})  # "outra tela" mexeu
    msgs.limpar()
    formulario._salvar()
    _processar()
    assert msgs.ultima()[1] == "Não foi possível salvar" and "alterada ou excluída" in msgs.ultima()[2], msgs.ultima()
    assert tela.lista.aberta == chave and not formulario._modo_leitura, "recusou e o card segue em edição"
    assert propostas_mod.listar_propostas().loc[antiga, "OBSERVAÇÕES"] == "mudou em outra tela"
    tela.lista.descartar()
    tela._carregar_dados()
    print("OK: se a proposta mudou desde que o card abriu, gravar é recusado com aviso (nada é sobrescrito).")

    # gravar de verdade: grava, o card fecha (mostrando o que foi gravado) e a tela avisa
    tela.lista.abrir_proposta(_item(tela, chave))
    tela.lista.card_aberto().formulario._observacoes.setPlainText("gravado no card")
    tela.lista.card_aberto().formulario._salvar()
    _processar()
    assert propostas_mod.listar_propostas().loc[antiga, "OBSERVAÇÕES"] == "gravado no card"
    assert tela.lista.aberta is None and tela.lista.card_aberto() is None, "gravou: o card fecha"
    assert tela.faixa_aviso.texto.text() == "Proposta gravada."
    print("OK: gravar grava, fecha o card e avisa.")

    assert not hasattr(tela, "_botao_excluir") and not hasattr(tela, "_excluir_selecionada")
    total = len(propostas_mod.listar_propostas())
    tela.lista.abrir_proposta(_item(tela, chave))
    msgs.limpar()
    msgs.resposta_pergunta = NAO
    tela.lista.card_aberto().botao_excluir.click()
    _processar()
    assert msgs.ultima()[1] == "Excluir proposta" and len(propostas_mod.listar_propostas()) == total, "'Não' não exclui"
    msgs.resposta_pergunta = SIM
    tela.lista.card_aberto().botao_excluir.click()
    _processar()
    assert len(propostas_mod.listar_propostas()) == total - 1 and tela.lista.aberta is None
    assert "excluída" in tela.faixa_aviso.texto.text()
    # numa venda: o mesmo caminho do card da venda (pelo ID)
    tela.lista.abrir_proposta(_item(tela, dados["pa2"]))
    tela.lista.card_aberto().botao_excluir.click()
    _processar()
    assert dados["pa2"] not in set(bd.ler_propostas(v._caminho())["ID_PROPOSTA"]), "a da venda também"
    assert len(propostas_mod.listar_propostas()) == total - 2
    print("OK: excluir só pelo 'Excluir esta proposta…' do card aberto, com confirmação ('Não' não exclui), de antes "
          "das vendas e de uma venda.")


def testar_roda(tela, dados: dict) -> None:
    linha("5) A roda do mouse sobre um campo não troca o valor")
    tela.lista.abrir_proposta(_item(tela, dados["pa1"]))
    f = tela.lista.card_aberto().formulario
    roda = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120), Qt.MouseButton.NoButton,
                       Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    valores = lambda: (f._meses.value(), f._valor.value(), f._banco.currentText(), f._status.currentText(),  # noqa: E731
                       f._carencia.currentText())
    antes = valores()
    for campo in (f._meses, f._valor, f._banco, f._status, f._carencia):
        for com_foco in (False, True):
            if com_foco:
                campo.setFocus()
            roda.ignore()
            QApplication.sendEvent(campo, roda)
            assert not roda.isAccepted(), f"a roda sobre um campo não é consumida (sobe pra lista rolar); foco={com_foco}"
    assert valores() == antes, "a roda não troca valor nenhum"
    tela.lista.descartar()
    print("OK: a roda do mouse sobre um campo/combo não muda o valor, com ou sem o campo selecionado.")


def testar_pagina_e_rolagem(tela, dados: dict) -> None:
    linha("6) Muitas propostas: 'Carregar mais' não esconde o card aberto, e gravar não leva a lista pro topo")
    hoje = date.today()
    for i in range(40):  # propostas pequenas e antigas, encerradas: enchem a lista
        propostas_mod.adicionar_proposta({"CPF": fx.CPF_ANA, "DATA": pd.Timestamp(hoje - timedelta(days=60 + i)),
                                          "STATUS": propostas_mod.STATUS_NEGADO, "BANCO": "Smart",
                                          "EQUIPAMENTO": "Equipamento Modelo X", "VALOR (R$)": 100 + i})
    tela._carregar_dados()
    _processar()
    assert tela.lista.total() > 30 and len(_cards(tela)) == 30 and not tela.lista.botao_mais.isHidden()
    ultima = tela.propostas_visiveis()[-1]
    assert tela.lista.abrir_proposta(ultima)
    _processar()
    assert tela.lista.card_aberto() is not None and len(_cards(tela)) == tela.lista.total(), "carrega até o card aberto"
    tela.lista.descartar()
    tela._ordenacao.setCurrentIndex(tela._ordenacao.findData(propostas_mod.ORDENACAO_VALOR_MENOR))  # a da venda, lá embaixo
    _processar(6)
    tela.lista.botao_mais.click()
    _processar(6)
    card = _card(tela, dados["pa1"])
    tela.rolagem.ensureWidgetVisible(card, 0, 60)
    _processar()
    barra = tela.rolagem.verticalScrollBar()
    antes = barra.value()
    assert antes > 200, f"a lista precisa rolar pro teste valer ({antes})"
    next(b for b in card.controles["bolinhas"] if b.destino == propostas_mod.STATUS_NEGADO).click()
    _processar(6)
    assert _status(dados["pa1"]) == propostas_mod.STATUS_NEGADO
    assert barra.value() == antes, f"a rolagem foi de {antes} para {barra.value()}"
    assert tela.rolagem.widget().minimumHeight() == 0, "a altura fica solta de novo (senão não encolhe mais)"
    tela._ordenacao.setCurrentIndex(0)
    _processar()
    print(f"OK: abrir uma proposta além da página carrega até ela; a bolinha num card lá embaixo mantém a rolagem ({antes}).")


def testar_ver_na_venda_e_dashboard(janela: MainWindow, tela, dados: dict) -> None:
    linha("7) 'Ver na venda →' abre a venda na tela Vendas; o filtro do Dashboard (o chip) continua")
    for i in range(31):  # mais de uma pagina de vendas: a venda pedida (das mais antigas) fica alem da primeira
        v.criar_venda(fx.CPF_ANA, ["Cadeira Exemplo"], {"BANCO": "Smart", "VALOR (R$)": 500 + i, "MESES": 12})
    if next(x for x in v.listar_vendas() if x.id == dados["id_a"]).status in v.DESFECHOS_DA_VENDA:
        v.reabrir_venda(dados["id_a"])  # (todos os bancos dela negaram la atras e a pergunta respondeu "Perdida")
    pa3 = v.mandar_a_outro_banco(dados["id_a"], {"BANCO": "Smart", "VALOR (R$)": 41000, "MESES": 36})  # 2o banco na venda
    tela._carregar_dados()
    _processar()
    tela.lista.abrir_proposta(_item(tela, dados["pb"]))
    tela.lista.card_aberto().ver_na_venda.click()
    _processar()
    assert janela.chave_atual() == PAGINA_VENDAS
    aberto = janela._tela_vendas.lista.card_aberto()
    assert aberto is not None and aberto.venda.id == dados["id_b"], "a venda certa, aberta"
    assert aberto.editando == dados["pb"] and aberto.formulario is not None, "já com o formulário da proposta de origem"

    # numa venda com dois bancos: o formulario e o da proposta de onde veio, logo embaixo da linha DELE
    janela.ir_para(PAGINA_PROPOSTAS)
    tela.lista.abrir_proposta(_item(tela, dados["pa1"]))
    tela.lista.card_aberto().ver_na_venda.click()
    _processar()
    aberto = janela._tela_vendas.lista.card_aberto()
    assert aberto.venda.id == dados["id_a"] and [p.id for p in aberto.venda.propostas] == [dados["pa1"], pa3]
    assert aberto.editando == dados["pa1"] and aberto.formulario._banco.currentText() == "Santander", "não o do outro banco"
    linha_pa1 = next(l for l in aberto.linhas_de_banco if l["proposta"].id == dados["pa1"])
    assert aberto._layout.indexOf(aberto.caixa_do_formulario) == aberto._layout.indexOf(linha_pa1["widget"]) + 1,         "logo embaixo da linha do banco"
    janela._tela_vendas.lista.descartar()
    print("OK: 'Ver na venda →' leva à tela Vendas com o card da venda certa aberto, já com o formulário da proposta "
          "de origem logo embaixo da linha do banco dela (mesmo além da primeira página).")

    # "+ Nova proposta" (no lugar do "+ Nova venda"): o card no topo, na propria tela (os detalhes:
    # smoke_test_venda_num_card.py)
    janela.ir_para(PAGINA_PROPOSTAS)
    assert tela._botao_nova.text() == "+ Nova proposta"
    tela._botao_nova.click()
    _processar()
    novo = tela.lista.card_aberto()
    assert isinstance(novo, CardNovaProposta) and tela.lista.cards[0] is novo and janela.chave_atual() == PAGINA_PROPOSTAS
    assert novo.formulario._cliente_combo is not None and novo.formulario._venda_combo is not None
    novo.formulario._cancelar_edicao()
    _processar()
    assert tela.lista.rascunho is None and not any(isinstance(c, CardNovaProposta) for c in tela.lista.cards)
    print("OK: '+ Nova proposta' abre o card no topo (cliente e venda); Cancel tira o card.")

    filtro = dashboard_mod.FiltroDoDashboard(chave=dashboard_mod.FILTRO_ETAPA, rotulo="Em análise",
                                             parametro=propostas_mod.ETAPA_EM_ANALISE)
    janela.abrir_propostas_filtradas(filtro)
    _processar()
    assert janela.chave_atual() == PAGINA_PROPOSTAS and tela.chip_do_filtro_visivel()
    esperadas = dashboard_mod.indices_do_filtro(propostas_mod.listar_propostas(), filtro)
    assert {i.proposta.indice for i in tela.propostas_visiveis()} == esperadas and esperadas
    tela._remover_filtro_do_dashboard()
    assert not tela.chip_do_filtro_visivel() and tela.lista.total() == len(propostas_mod.listar_propostas())
    print("OK: o filtro do Dashboard mostra só as propostas dele (com o chip) e '✕ Remover filtro' volta tudo.")


def testar_vendedor(amb: Ambiente) -> None:
    linha("8) O VENDEDOR só lê: cards sem ações, a proposta abre travada")
    janela = amb.nova_janela("vendedor", TEMA_ESCURO)
    janela.ir_para(PAGINA_PROPOSTAS)
    tela = janela._tela_propostas
    _processar()
    assert _cards(tela) and tela._botao_nova.isHidden()
    assert all(not c.pilula.clicavel and not c.controles["bolinhas"] and c.controles["anel"] is None
               and c.controles["voltar"] is None for c in _cards(tela)), "nenhuma ação"
    card = _cards(tela)[0]
    _duplo_clique(card, _no_topo(card))
    _processar()
    aberto = tela.lista.card_aberto()
    assert aberto is not None and aberto.formulario._modo_leitura and aberto.formulario._botao_editar.isHidden()
    assert aberto.botao_excluir is None and aberto.ver_na_venda is None
    aberto.formulario._salvar()  # mesmo por codigo: em leitura nao grava
    aberto.formulario._botao_recolher.click()
    _processar()
    assert tela.lista.aberta is None
    print("OK: o vendedor vê os cards sem ações; dois cliques abrem a proposta só para ler (sem excluir).")


def testar_grade_do_formulario(soltas: JanelasSoltas) -> None:
    linha("9) Formulário em grade: campos lado a lado (com carência e parcela), só as Observações na largura toda")
    f = FormularioProposta("52998224725", "ALFA CLIENTE", proposta={
        "DATA": pd.Timestamp(2026, 3, 1), "CPF": "52998224725", "VALOR (R$)": 75000.0, "MESES": 36.0, "EQUIPAMENTO": "HAKON",
        "BANCO": "SANTANDER", "STATUS": "Negado", "OBSERVAÇÕES": "obs"}, indice=0)
    soltas.esperadas.append(f)
    f.resize(900, 300)
    f.show()
    _processar()

    def celula(campo):
        w = campo
        while w.parentWidget() is not f and w.parentWidget() is not None:
            w = w.parentWidget()
        return w

    topo = lambda c: celula(c).mapTo(f, QPoint(0, 0)).y()  # noqa: E731
    esquerda = lambda c: celula(c).mapTo(f, QPoint(0, 0)).x()  # noqa: E731
    assert topo(f._data) == topo(f._meses) == topo(f._status), "Data, Meses e Status na mesma linha"
    assert topo(f._valor) == topo(f._carencia) == topo(f._parcela), "Valor, Carência e Parcela na mesma linha"
    assert topo(f._equipamento) == topo(f._banco), "Equipamento e Banco na mesma linha"
    assert topo(f._data) < topo(f._valor) < topo(f._equipamento) < topo(f._observacoes), "as linhas seguem a ordem"
    assert esquerda(f._data) < esquerda(f._meses) < esquerda(f._status) and esquerda(f._valor) < esquerda(f._carencia) < esquerda(f._parcela)
    assert esquerda(f._equipamento) < esquerda(f._banco)
    assert celula(f._observacoes).width() == f.width(), "as observações ocupam a largura toda"
    for campo, maximo in ((f._data, 190), (f._meses, 120), (f._status, 250), (f._valor, 210), (f._carencia, 140),
                          (f._parcela, 190), (f._banco, 260)):
        assert celula(campo).width() <= maximo, f"largura do campo: {celula(campo).width()} > {maximo} (so o que o conteudo pede)"
    assert celula(f._equipamento).width() > celula(f._banco).width(), "o equipamento (nome longo) fica com o resto da largura"
    assert f.sizeHint().height() <= 350, f"formulario compacto (menos alto): {f.sizeHint().height()} px"
    largura_minima = f.minimumSizeHint().width()
    assert largura_minima <= 460 < LARGURA_CARD, f"a grade cabe no card: precisa de {largura_minima} px"
    print(f"OK: 4 linhas de campos, cada um com a largura do conteúdo; {f.sizeHint().height()} px de altura e no mínimo "
          f"{largura_minima} px de largura (cabe no card de {LARGURA_CARD} px).")
    f.close()


def testar_o_que_saiu() -> None:
    linha("10) O card antigo (lista desenhada + expansor), o painel lateral e o popup antigos não existem mais")
    for modulo in ("desktop.widgets.expansor_proposta", "desktop.widgets.painel_lateral",
                   "desktop.widgets.painel_proposta", "desktop.dialogs.proposta_dialog"):
        try:
            importlib.import_module(modulo)
        except ModuleNotFoundError:
            continue
        raise AssertionError(f"{modulo} nao deveria existir")
    lista_cartoes = importlib.import_module("desktop.widgets.lista_cartoes")
    for nome in ("ListaCartoes", "ModeloCartoes", "DelegateCartao", "ContentorDeListaAutomatica"):
        assert not hasattr(lista_cartoes, nome), f"{nome} saiu com o card antigo"
    print("OK: sem o card expansível antigo, sem painel lateral e sem PropostaDialog; de lista_cartoes ficaram só as cores.")


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyle("windows11")  # o estilo do app real
    soltas = JanelasSoltas()
    with Mensagens() as msgs:
        amb = Ambiente()
        try:
            amb.entrar_como("admin")
            dados = _montar_dados()
            app.installEventFilter(soltas)
            janela = amb.nova_janela("admin", TEMA_ESCURO)
            janela.resize(1500, 950)
            janela.ir_para(PAGINA_PROPOSTAS)
            tela = janela._tela_propostas
            _processar(6)
            testar_cards_e_ordem(tela, dados)
            testar_acoes_rapidas(tela, dados, msgs)
            testar_abrir_e_fechar(tela, dados, msgs)
            testar_gravar_por_cima_e_excluir(tela, dados, msgs)
            testar_roda(tela, dados)
            testar_pagina_e_rolagem(tela, dados)
            testar_ver_na_venda_e_dashboard(janela, tela, dados)
            testar_vendedor(amb)
            testar_grade_do_formulario(soltas)
            testar_o_que_saiu()
            linha("11) Nenhuma janela solta")
            assert soltas.vistas == [], f"apareceram como janela solta: {soltas.vistas}"
            msgs.exigir_sem_erros("todas as propostas")
            print("OK: nenhum pedaço de card apareceu como janela solta; nenhuma mensagem de erro.")
            linha("TUDO OK")
        finally:
            app.removeEventFilter(soltas)
            amb.encerrar()


if __name__ == "__main__":
    main()
