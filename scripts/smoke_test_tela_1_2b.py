"""Testa a tela das etapas e das pendencias (plano 1.2-B, parte 2): no card da venda e no da proposta, a linha de cada
banco fechado (etiqueta com a cor da etapa, trilha de 4 pontos, "desde 15/10 · há 3 dias" (parado: "parada há 9 dias" em âmbar, sem caixinha), a bolinha
que avanca UMA etapa, a lista da etiqueta com todas as etapas, o ↩); as pendencias (etiqueta "N pendências" no card
fechado, "+ Pendência", lista com "Resolvida" no card aberto, filtro "Com pendências"); o nome antigo "Nota fiscal
enviada" mostrado como "NF enviada"; e as observacoes no topo do
card fechado (ate 2 linhas).

Planilha 100% ficticia em pasta temporaria, preferencias isoladas e o Google desligado.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_tela_1_2b.py
"""

from __future__ import annotations

import dataclasses
import os
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractButton, QApplication, QHBoxLayout, QLabel, QMessageBox, QWidget

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False
import fixture_ficticia as fx
from ambiente_de_teste import Mensagens
from core import bancos as bancos_mod
from core import data_store as bd
from core import data_store_sheets as nuvem
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import sheets_sync
from core import vendas as v
from core import vendedores as vendedores_mod
from core.formatting import formatar_data
from desktop import settings as settings_mod
from desktop.screens import vendas_screen as tela_mod
from desktop.theme import CORES_STATUS, TEMA_CLARO, TEMA_ESCURO, build_stylesheet
from desktop.widgets import card_da_venda as card_mod
from desktop.widgets.card_da_proposta import CardDaProposta
from desktop.widgets.formulario_proposta import FormularioProposta
from desktop.widgets.lista_cartoes import chave_cor_status

ADMIN = sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador")
APROVADO, ASSINADO, NOTA, EFETIVADO = (propostas_mod.STATUS_APROVADO, propostas_mod.STATUS_ASSINADO,
                                       propostas_mod.STATUS_NOTA_ENVIADA, propostas_mod.STATUS_EFETIVADO)


class _Relogio(datetime):
    agora_combinado = datetime(2026, 1, 1)

    @classmethod
    def now(cls, tz=None):
        return cls.agora_combinado


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _processar() -> None:
    for _ in range(4):
        QApplication.processEvents()


def _acoes(menu) -> dict:
    return {a.text(): a for a in menu.actions() if a.text()}


def _pedido(banco: str, valor: float = 50000, **extra) -> dict:
    return {"BANCO": banco, "VALOR (R$)": valor, "MESES": 36, "CARÊNCIA (DIAS)": 60, **extra}


def main() -> None:
    def _sem_rede(*_a, **_k):
        raise AssertionError("o teste tentou acessar o Google de verdade")

    rede_original = (nuvem._obter_cliente, sheets_sync._obter_cliente)
    nuvem._obter_cliente = sheets_sync._obter_cliente = _sem_rede
    datetime_original = v.datetime
    pasta = Path(tempfile.mkdtemp(prefix="_smoke_tela_1_2b_"))
    registro_antes = fx.instantaneo_do_registro()
    fx.isolar_preferencias(pasta)
    caminho = fx.criar(pasta)
    fx.apontar_modulos_para(caminho)
    sessao_mod.iniciar(ADMIN)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(build_stylesheet(TEMA_ESCURO))
    try:
        with Mensagens() as msgs:
            b1, b2 = bancos_mod.nomes_ativos()[:2]

            def venda_(id_):
                return bd.ler_vendas(caminho).set_index("ID_VENDA").loc[id_]

            def status_de(id_):
                return bd.ler_propostas(caminho).set_index("ID_PROPOSTA").loc[id_, "STATUS"]

            def card_de(tela, id_venda):
                cards = [c for c in tela.lista.cards if c.venda.id == id_venda]
                assert len(cards) == 1, id_venda
                return cards[0]

            def linha_do(card, id_proposta):
                return next(l for l in card.linhas_de_banco if l["proposta"].id == id_proposta)

            tela = tela_mod.VendasScreen()
            tela.resize(1100, 760)
            tela.show()
            tela.filtro.setCurrentText(tela_mod.FILTRO_TODAS)
            _processar()

            linha("1) Um banco fechado: a bolinha avanca UMA etapa; trilha, cor da etiqueta e data acompanham")
            hoje = date.today()
            v.datetime = _Relogio
            _Relogio.agora_combinado = datetime.combine(hoje - timedelta(days=5), datetime.min.time()) + timedelta(hours=10)
            id_a, p_a = v.criar_venda(fx.CPF_MARIA, ["Cadeira Exemplo"], _pedido(b1, EQUIPAMENTO="Cadeira Exemplo"))
            v.mudar_status_proposta(p_a, APROVADO)
            v.fechar_proposta(p_a)
            _Relogio.agora_combinado = datetime.combine(hoje - timedelta(days=3), datetime.min.time()) + timedelta(hours=10)
            v.mudar_status_proposta(p_a, ASSINADO)
            v.datetime = datetime_original
            tela.carregar()
            _processar()
            card = card_de(tela, id_a)
            l = linha_do(card, p_a)
            assert l["pilula"].text() == "Assinado" and l["pilula"].cor == "garantia", "Assinado: ciano"
            assert [b.destino for b in l["bolinhas"]] == ["NF enviada"] and l["bolinhas"][0].dica == "Avançar para NF enviada"
            assert l["bolinhas"][0].cor == "nota_fiscal", "a bolinha tem a cor da PRÓXIMA etapa"
            assert l["voltar"] is not None and l["voltar"].anterior == APROVADO
            trilha = l["trilha"]
            assert trilha is not None and trilha.atual == 1
            assert trilha.dica_do_ponto(0) == f"Aprovado em {hoje - timedelta(days=5):%d/%m}"
            assert trilha.dica_do_ponto(1) == f"Assinado em {hoje - timedelta(days=3):%d/%m}"
            assert trilha.dica_do_ponto(3) == "Efetivado", "etapa que ainda não chegou: só o nome"
            assert l["data"].text() == f"desde {hoje - timedelta(days=3):%d/%m} · há 3 dias", l["data"].text()
            assert l["data"].parada == "" and card.andamento.parada == "", "3 dias: não está parada"
            assert chave_cor_status("NF enviada") == "nota_fiscal" and chave_cor_status("Nota fiscal enviada") == "nota_fiscal"
            assert chave_cor_status(APROVADO) == "aprovado" and chave_cor_status(EFETIVADO) == "efetivado"
            # a lista da etiqueta: todas as etapas (pular etapa so por aqui); a atual marcada e sem efeito
            menu = _acoes(tela.lista.controle.montar_menu_da_proposta(card.venda, l["proposta"]))
            for etapa in ("Assinado", "NF enviada", "Efetivado…"):
                assert etapa in menu, list(menu)
            assert menu["Assinado"].isChecked() and not menu["Assinado"].isEnabled() and menu["NF enviada"].isEnabled()
            assert not menu[propostas_mod.STATUS_NEGADO].isEnabled() and menu[APROVADO].isEnabled()
            # um clique: Assinado -> NF enviada (so uma etapa) e a tela relê
            l["bolinhas"][0].click()
            _processar()
            assert status_de(p_a) == NOTA
            card = card_de(tela, id_a)
            l = linha_do(card, p_a)
            assert l["pilula"].text() == "NF enviada" and l["trilha"].atual == 2
            assert l["data"].text() == "desde " + f"{hoje:%d/%m}" + " · hoje"
            assert [b.destino for b in l["bolinhas"]] == ["Efetivado"] and "pede confirmação" in l["bolinhas"][0].dica
            assert l["voltar"].anterior == ASSINADO
            # pular etapa: pela lista (NF enviada -> Aprovado -> Efetivado… com confirmacao)
            msgs.resposta_pergunta = QMessageBox.StandardButton.Yes
            l["bolinhas"][0].click()
            _processar()
            assert status_de(p_a) == EFETIVADO and venda_(id_a)["STATUS"] == v.VENDA_EFETIVADA
            card = card_de(tela, id_a)
            l = linha_do(card, p_a)
            assert l["pilula"].text() == "Efetivado" and l["bolinhas"] == [] and l["trilha"].atual == 3
            assert l["data"].text() == f"desde {hoje:%d/%m}", "Efetivado: só 'desde', sem 'há N dias'"
            assert l["voltar"].anterior == NOTA, "o ↩ funciona também a partir de Efetivado"
            l["voltar"].click()
            _processar()
            assert status_de(p_a) == NOTA
            # pular etapa pela lista: Aprovado -> Efetivado nao e oferecido pela bolinha, mas a lista aceita
            menu = _acoes(tela.lista.controle.montar_menu_da_proposta(card_de(tela, id_a).venda,
                                                                     linha_do(card_de(tela, id_a), p_a)["proposta"]))
            menu[APROVADO].trigger()
            _processar()
            assert status_de(p_a) == APROVADO and [b.destino for b in linha_do(card_de(tela, id_a), p_a)["bolinhas"]] == ["Assinado"]
            print("OK: a bolinha avança uma etapa (cor da próxima), a trilha e a data acompanham, a lista tem todas as "
                  "etapas e o ↩ volta (também de Efetivado).")

            linha("2) Selo de parada: so etapa (banco parado e, no topo, a maior parada); nunca pendencia")
            _Relogio.agora_combinado = datetime.combine(hoje - timedelta(days=12), datetime.min.time()) + timedelta(hours=9)
            v.datetime = _Relogio
            id_b, p_b1 = v.criar_venda(fx.CPF_JOAO, ["Laser Exemplo", "Mesa Exemplo"],
                                       _pedido(b1, EQUIPAMENTO="Laser Exemplo"))
            p_b2 = v.mandar_a_outro_banco(id_b, _pedido(b2, 31000, EQUIPAMENTO="Mesa Exemplo"))
            for p in (p_b1, p_b2):
                v.mudar_status_proposta(p, APROVADO)
                v.fechar_proposta(p)
            _Relogio.agora_combinado = datetime.combine(hoje - timedelta(days=9), datetime.min.time()) + timedelta(hours=9)
            v.mudar_status_proposta(p_b1, ASSINADO)
            _Relogio.agora_combinado = datetime.combine(hoje - timedelta(days=2), datetime.min.time()) + timedelta(hours=9)
            v.mudar_status_proposta(p_b2, ASSINADO)
            v.adicionar_pendencia(id_b, "Equipamento ainda não chegou")  # antiga: nao conta
            v.datetime = datetime_original
            tela.carregar()
            _processar()
            card = card_de(tela, id_b)
            l1, l2 = linha_do(card, p_b1), linha_do(card, p_b2)
            # a parada e TEXTO (ambar, negrito, sem caixinha) dentro da linha de baixo; sem o selo de caixinha
            assert not hasattr(card_mod, "Selo") and not hasattr(card, "selo")
            assert l1["data"].parada == "parada há 9 dias" and l2["data"].parada == ""
            assert l1["data"].texto == f"desde {hoje - timedelta(days=9):%d/%m} · parada há 9 dias", l1["data"].texto
            assert l2["data"].texto == f"desde {hoje - timedelta(days=2):%d/%m} · há 2 dias"
            assert card.andamento.parada == f"{b1} parado em Assinado há 9 dias", "no topo, o banco e a etapa da maior parada"
            assert card.andamento.texto == (f"desde {formatar_data(card.venda.data_criacao)} · {b1} parado em Assinado há 9 dias"
                                            f" · 0 de 2 bancos efetivados"), card.andamento.texto
            assert "Em andamento" not in card.andamento.texto, "nao diz 'parada em Em andamento'"
            for texto in (card.andamento.texto, l1["data"].texto):
                assert texto.count("há") == 1, "a informação não se repete na mesma linha"
            for rotulo in (card.andamento, l1["data"]):
                cor = CORES_STATUS[TEMA_ESCURO]["em_analise"]["texto"]
                assert rotulo.textFormat() == Qt.TextFormat.RichText and cor in rotulo.text() and "<b " in rotulo.text()
            assert "<b" not in l2["data"].text() and l2["data"].textFormat() == Qt.TextFormat.PlainText
            # fora o status (pilula) e as pendencias, nenhuma caixinha no topo: so Pilula (clicavel ou nao) la dentro
            quem_diz_parada = [w for w in (*card.findChildren(QLabel), *card.findChildren(QAbstractButton))
                               if "parada" in w.text() or "parado em" in w.text()]
            assert quem_diz_parada and all(isinstance(w, card_mod.TextoComParada) for w in quem_diz_parada), quem_diz_parada
            # texto com "<" ou "&" (um status digitado) aparece como esta, sem virar formatacao
            esquisito = card_mod.TextoComParada("a · ", "parada há 9 dias", ' em "<i>x</i> & y"')
            assert "&lt;i&gt;x&lt;/i&gt; &amp; y" in esquisito.text() and "<i>" not in esquisito.text()
            esquisito.close()
            # o tema claro troca a cor ao desenhar (o app muda de tema com os cards na tela)
            settings_mod.definir_tema(TEMA_CLARO)
            app.setStyleSheet(build_stylesheet(TEMA_CLARO))
            card.andamento.grab()
            assert CORES_STATUS[TEMA_CLARO]["em_analise"]["texto"] in card.andamento.text()
            settings_mod.definir_tema(TEMA_ESCURO)
            app.setStyleSheet(build_stylesheet(TEMA_ESCURO))
            # venda sem banco parado e com pendencia aberta antiga: sem parada
            assert card_de(tela, id_a).andamento.parada == ""
            assert "parada" not in card_de(tela, id_a).andamento.texto and "<b" not in card_de(tela, id_a).andamento.text()
            tela.filtro.setCurrentText(tela_mod.FILTRO_PARADAS)
            assert [c.venda.id for c in tela.lista.cards] == [id_b]
            tela.filtro.setCurrentText(tela_mod.FILTRO_TODAS)
            # desfecho: os bancos de uma venda perdida nao alertam
            v.mudar_status_venda(id_b, v.VENDA_PERDIDA, motivo="Desistiu")
            tela.carregar()
            card = card_de(tela, id_b)
            assert card.andamento.parada == "" and linha_do(card, p_b1)["data"].parada == ""
            v.reabrir_venda(id_b)
            tela.carregar()
            _processar()
            print("OK: parada em âmbar no banco parado há 9 dias e, no topo, a maior (sem caixinha, sem repetir); nada para o banco recente nem para a pendência "
                  "antiga; venda perdida não mostra parada; o filtro 'Paradas' acha só a parada.")

            linha("3) Pendencias: etiqueta no card fechado, +Pendencia, lista com Resolvida no card aberto, filtro")
            card = card_de(tela, id_b)
            assert card.etiqueta_pendencias is not None and card.etiqueta_pendencias.text() == "1 pendência"
            assert "Equipamento ainda não chegou" in card.etiqueta_pendencias.toolTip()
            assert card.pilula.text() == v.VENDA_EM_ANDAMENTO, "a pendência é uma etiqueta, não um status"
            assert card_de(tela, id_a).etiqueta_pendencias is None
            assert card.nova_pendencia is not None and card.nova_pendencia.text() == "+ Pendência", "o atalho no card fechado"
            # "+ Pendência": pede o texto (aqui, respondido sem janela); cancelar nao grava
            pedidos = []
            respostas = ["Falta comprovante de renda", None, "   "]

            def _pedir(venda):
                pedidos.append(venda.id)
                return respostas.pop(0)

            tela.lista.controle._pedir_pendencia = _pedir
            card.nova_pendencia.click()
            _processar()
            assert pedidos == [id_b] and [p.texto for p in v.pendencias_da_venda(id_b)] == [
                "Equipamento ainda não chegou", "Falta comprovante de renda"]
            assert "pendência adicionada" in tela.texto_aviso.text()
            card = card_de(tela, id_b)
            assert card.etiqueta_pendencias.text() == "2 pendências"
            msgs.limpar()
            card.nova_pendencia.click()  # cancelou
            _processar()
            msgs.exigir_vazio("cancelar não grava nem avisa")
            assert len(v.pendencias_da_venda(id_b)) == 2
            msgs.limpar()
            card_de(tela, id_b).nova_pendencia.click()  # so espacos: o core recusa com mensagem, nada grava
            _processar()
            assert "Diga o que está pendente" in msgs.ultima()[2] and len(v.pendencias_da_venda(id_b)) == 2
            msgs.limpar()
            # o status e o selo seguem so pelos bancos
            assert venda_(id_b)["STATUS"] == v.VENDA_EM_ANDAMENTO
            # filtro "Com pendencias"
            tela.filtro.setCurrentText(tela_mod.FILTRO_COM_PENDENCIAS)
            assert [c.venda.id for c in tela.lista.cards] == [id_b]
            assert tela_mod.FILTRO_COM_PENDENCIAS in tela_mod.FILTROS
            tela.filtro.setCurrentText(tela_mod.FILTRO_TODAS)
            # clicar na etiqueta abre o card, com a lista; o card fechado nao tem a lista
            assert card_de(tela, id_b).pendencias_na_lista == []
            card_de(tela, id_b).etiqueta_pendencias.click()
            _processar()
            card = card_de(tela, id_b)
            assert card.aberto and tela.lista.aberta == id_b
            textos = [x["texto"].text() for x in card.pendencias_na_lista]
            assert textos == ["• Equipamento ainda não chegou", "• Falta comprovante de renda"], textos
            assert all(x["botao"] is not None and x["botao"].text() == "Resolvida" for x in card.pendencias_na_lista)
            assert card.nova_pendencia is not None and card.nova_pendencia.text() == "+ Pendência", "o rodapé do card aberto"
            # Resolvida: grava, a etiqueta cai para 1 e a resolvida fica em cinza (sem botao)
            card.pendencias_na_lista[0]["botao"].click()
            _processar()
            assert [p.aberta for p in v.pendencias_da_venda(id_b)] == [False, True] and "pendência resolvida" in tela.texto_aviso.text()
            card = card_de(tela, id_b)
            assert card.etiqueta_pendencias.text() == "1 pendência" and card.aberto
            assert [x["texto"].text() for x in card.pendencias_na_lista] == ["• Falta comprovante de renda",
                                                                              "✓ Equipamento ainda não chegou"]
            assert [x["botao"] is None for x in card.pendencias_na_lista] == [False, True]
            card.pendencias_na_lista[0]["botao"].click()
            _processar()
            card = card_de(tela, id_b)
            assert card.etiqueta_pendencias is None and not any(x["botao"] for x in card.pendencias_na_lista)
            tela.lista.fechar_venda()  # (o card aberto fica na lista mesmo fora do filtro)
            tela.filtro.setCurrentText(tela_mod.FILTRO_COM_PENDENCIAS)
            assert tela.lista.total() == 0, "nenhuma aberta: o filtro esvazia"
            tela.filtro.setCurrentText(tela_mod.FILTRO_TODAS)
            msgs.exigir_sem_erros("pendências")
            print("OK: etiqueta 'N pendência(s)' + atalho no card fechado, lista com 'Resolvida' no aberto, filtro "
                  "'Com pendências'; o status da venda não muda.")

            linha("4) Observacoes no topo do card fechado: ate 2 linhas; inteiras no aberto")
            id_c, p_c = v.criar_venda(fx.CPF_ANA, ["Autoclave Exemplo"], _pedido(b2, EQUIPAMENTO="Autoclave Exemplo"))
            longa = ("Cliente pediu entrega só depois do dia 25. Contrato assinado em papel, falta digitalizar e anexar a "
                     "biometria do avalista. " * 3).strip()
            v.editar_venda(id_c, ["Autoclave Exemplo"], longa)
            id_d, _ = v.criar_venda(fx.CPF_ANA, ["Mesa Exemplo"], _pedido(b1, EQUIPAMENTO="Mesa Exemplo"))
            v.editar_venda(id_d, ["Mesa Exemplo"], "Só uma linha.")
            id_e, _ = v.criar_venda(fx.CPF_ANA, ["Item Sem Obs"], _pedido(b1, EQUIPAMENTO="Item Sem Obs"))
            tela.carregar()
            _processar()
            card = card_de(tela, id_c)
            assert card.observacoes is not None and card.observacoes.completo == f"Observações: {longa}"
            linhas = card.observacoes.fontMetrics().lineSpacing()
            assert card.observacoes.text().endswith("…") and len(card.observacoes.text()) < len(longa)
            assert card.observacoes.height() <= 2 * linhas + 2, "no máximo 2 linhas"
            assert card.observacoes.toolTip() == f"Observações: {longa}", "o texto inteiro fica na dica"
            assert card_de(tela, id_d).observacoes.text() == "Observações: Só uma linha."
            assert card_de(tela, id_e).observacoes is None
            # logo abaixo do equipamento (antes da linha de andamento) no layout do card
            lay = card._layout
            ordem = [lay.itemAt(i).widget() for i in range(lay.count()) if lay.itemAt(i).widget() is not None]
            assert ordem.index(card.observacoes) < ordem.index(card.andamento)
            tela.lista.abrir_venda(card.venda)
            _processar()
            aberto = card_de(tela, id_c)
            assert aberto.aberto and aberto.observacoes.text() == f"Observações: {longa}", "aberto: inteiras"
            tela.lista.fechar_venda()
            _processar()
            print("OK: observações logo abaixo do equipamento: até 2 linhas com '…' (texto inteiro na dica) no fechado, "
                  "inteiras no aberto; sem observação, sem linha.")

            linha("5) O card da proposta tem a mesma trilha, data e selo")
            _Relogio.agora_combinado = datetime.combine(hoje - timedelta(days=8), datetime.min.time()) + timedelta(hours=9)
            v.datetime = _Relogio
            id_f, p_f = v.criar_venda(fx.CPF_JOAO, ["Item F"], _pedido(b1, EQUIPAMENTO="Item F"))
            v.mudar_status_proposta(p_f, APROVADO)
            v.fechar_proposta(p_f)
            v.datetime = datetime_original
            itens = v.propostas_na_lista_do_arquivo(bd.ler_propostas(caminho))
            item = next(i for i in itens.values() if i.proposta.id == p_f)
            cartao = CardDaProposta(item)
            cartao.show()
            assert cartao.controles["trilha"] is not None and cartao.controles["trilha"].atual == 0
            assert cartao.controles["data"].texto == f"desde {hoje - timedelta(days=8):%d/%m} · parada há 8 dias"
            assert cartao.controles["data"].parada == "parada há 8 dias" and "selo" not in cartao.controles
            assert [b.destino for b in cartao.controles["bolinhas"]] == ["Assinado"]
            solto = next(i for i in itens.values() if not i.proposta.fechada)
            c2 = CardDaProposta(solto)
            assert c2.controles["trilha"] is None and c2.controles["data"] is None
            cartao.close()
            c2.close()
            print("OK: no card da proposta, banco fechado tem trilha, data (com a parada em texto) e a bolinha da próxima etapa; os outros não.")

            linha("6) Os dois temas pintam as etapas com as cores do esboço")
            for tema in (TEMA_CLARO, TEMA_ESCURO):
                assert CORES_STATUS[tema]["garantia"]["faixa"] and CORES_STATUS[tema]["nota_fiscal"]["faixa"]
            print("OK: Assinado (ciano) e NF enviada (roxo) existem nos dois temas.")

            linha("7) Efetivada com pendencia aberta segue em 'Em andamento'; celula ilegivel nao derruba a tela; resumo que nao abre avisa")
            id_g, p_g = v.criar_venda(fx.CPF_ANA, ["Item G"], _pedido(b1, EQUIPAMENTO="Item G"))
            v.mudar_status_proposta(p_g, APROVADO)
            v.fechar_proposta(p_g)
            v.efetivar_proposta(p_g)
            tela.filtro.setCurrentText(tela_mod.FILTRO_EM_ANDAMENTO)
            tela.carregar()
            ids_em_andamento = lambda: {c.venda.id for c in tela.lista.cards}  # noqa: E731
            assert id_g not in ids_em_andamento(), "Efetivada sem pendencia: fora do 'Em andamento'"
            id_pd = v.adicionar_pendencia(id_g, "Falta entregar o equipamento")
            tela.carregar()
            assert id_g in ids_em_andamento() and card_de(tela, id_g).venda.status == v.VENDA_EFETIVADA
            v.resolver_pendencia(id_g, id_pd)
            tela.carregar()
            assert id_g not in ids_em_andamento(), "resolvida a pendencia, sai do filtro"
            tela.filtro.setCurrentText(tela_mod.FILTRO_TODAS)
            # celula PENDENCIAS ilegivel: a tela abre, o card avisa e so as pendencias dele bloqueiam
            vendas = bd.ler_vendas(caminho)
            vendas.loc[vendas["ID_VENDA"] == id_g, "PENDENCIAS"] = "lixo digitado a mão"
            bd.escrever_vendas_e_propostas(caminho, vendas=vendas)
            msgs.limpar()
            assert tela.carregar() is True
            msgs.exigir_sem_erros("tela com uma celula PENDENCIAS ilegivel")
            card = card_de(tela, id_g)
            assert card.aviso_pendencias is not None and "avise o suporte" in card.aviso_pendencias.text()
            assert "apague" not in card.aviso_pendencias.text().lower() and card.etiqueta_pendencias is None
            assert all(c.aviso_pendencias is None for c in tela.lista.cards if c.venda.id != id_g)
            antes_ilegivel = bd.ler_vendas(caminho).set_index("ID_VENDA").loc[id_g, "PENDENCIAS"]
            tela.lista.controle._pedir_pendencia = lambda venda: "tentativa"
            card.nova_pendencia.click()
            _processar()
            assert "ilegível" in msgs.ultima()[2] and "apague" not in msgs.ultima()[2].lower()
            assert bd.ler_vendas(caminho).set_index("ID_VENDA").loc[id_g, "PENDENCIAS"] == antes_ilegivel, "nada gravou"
            vendas = bd.ler_vendas(caminho)
            vendas.loc[vendas["ID_VENDA"] == id_g, "PENDENCIAS"] = ""
            bd.escrever_vendas_e_propostas(caminho, vendas=vendas)
            tela.carregar()
            # o dialogo do resumo que nao abre: a mensagem do erro, nunca um traceback mudo
            listar_original = vendedores_mod.listar_vendedores

            def _falha():
                raise RuntimeError("a planilha de vendedores não abriu")

            vendedores_mod.listar_vendedores = _falha
            mostrados = []
            tela._mostrar_dialogo = mostrados.append
            tela.dialogo_resumo = None
            msgs.limpar()
            try:
                assert tela.abrir_resumo() is None and mostrados == [] and tela.dialogo_resumo is None
            finally:
                vendedores_mod.listar_vendedores = listar_original
            tipo, titulo, texto = msgs.ultima()
            assert tipo == "critical" and "resumo" in titulo and "RuntimeError" in texto and "a planilha de vendedores não abriu" in texto
            print("OK: Efetivada com pendência aberta fica no 'Em andamento'; célula ilegível: a tela abre, o card avisa e só as "
                  "pendências dele bloqueiam; o resumo que não abre mostra o erro.")

            linha("8) Planilha com o nome antigo 'Nota fiscal enviada': a tela mostra 'NF enviada'; ao gravar, grava 'NF enviada'")
            ANTIGO = propostas_mod.STATUS_NOTA_ENVIADA_ANTIGO
            id_h, p_h = v.criar_venda(fx.CPF_ANA, ["Item H"], _pedido(b1, EQUIPAMENTO="Item H"))
            v.mudar_status_proposta(p_h, APROVADO)
            v.fechar_proposta(p_h)
            v.mudar_status_proposta(p_h, ASSINADO)
            propostas = bd.ler_propostas(caminho)
            propostas.loc[propostas["ID_PROPOSTA"] == p_h, "STATUS"] = ANTIGO  # (a planilha convertida antes do renome)
            bd.escrever_vendas_e_propostas(caminho, propostas=propostas)
            assert status_de(p_h) == ANTIGO and propostas_mod.nome_oficial(ANTIGO) == NOTA
            for variante in ("nota fiscal enviada", "  NOTA  FISCAL ENVIADA "):
                assert propostas_mod.nome_oficial(variante) == NOTA, variante
            for igual in (NOTA, ASSINADO, "Em Análise", "", None, "Nota Fiscal Anexada"):
                assert propostas_mod.nome_oficial(igual) == igual, "só o nome antigo é trocado"
            tela.carregar()
            _processar()
            card = card_de(tela, id_h)
            l = linha_do(card, p_h)
            assert l["proposta"].status == NOTA and l["pilula"].text() == NOTA, l["pilula"].text()
            assert l["trilha"].atual == 2 and l["pilula"].cor == "nota_fiscal"
            assert [b.destino for b in l["bolinhas"]] == ["Efetivado"]
            # o card da proposta (Todas as Propostas, Ficha) mostra o mesmo
            itens = v.propostas_na_lista_do_arquivo(bd.ler_propostas(caminho))
            cartao = CardDaProposta(next(i for i in itens.values() if i.proposta.id == p_h))
            assert cartao.pilula.text() == NOTA
            cartao.close()
            # a etiqueta tambem corrige sozinha um status cru (objeto montado sem passar pela leitura)
            cru = dataclasses.replace(l["proposta"], status=ANTIGO)
            caixa = QWidget()
            controles: dict = {}
            card_mod.por_controles_de_status(QHBoxLayout(caixa), card, card.venda, cru, caixa, controles)
            assert controles["pilula"].text() == NOTA and controles["pilula"].cor == "nota_fiscal"
            caixa.close()
            # o formulario abre com 'NF enviada' e sem alteracao; gravar outra coisa deixa o nome novo na planilha, sem
            # reiniciar a etapa (nenhuma linha nova no historico)
            bruto = bd.ler_propostas(caminho).set_index("ID_PROPOSTA").loc[p_h].to_dict() | {"ID_PROPOSTA": p_h}
            form = FormularioProposta(fx.CPF_ANA, "ANA", proposta=bruto, indice=l["proposta"].indice)
            assert form._status.currentText() == NOTA and [form._status.itemText(i) for i in range(form._status.count())].count(NOTA) == 1
            assert not form.tem_alteracoes()
            linhas_antes = len(bd.ler_historico(caminho))
            v.editar_proposta(p_h, {"STATUS": NOTA, "OBSERVAÇÕES": "conferido"}, esperado=bruto)
            assert status_de(p_h) == NOTA and len(bd.ler_historico(caminho)) == linhas_antes, "sem troca de etapa no historico"
            assert linha_do((tela.carregar(), card_de(tela, id_h))[1], p_h)["pilula"].text() == NOTA
            # trocar de etapa por cima do nome antigo: o historico registra de 'NF enviada' (nunca do nome antigo)
            propostas = bd.ler_propostas(caminho)
            propostas.loc[propostas["ID_PROPOSTA"] == p_h, "STATUS"] = ANTIGO
            bd.escrever_vendas_e_propostas(caminho, propostas=propostas)
            v.mudar_status_proposta(p_h, EFETIVADO)
            historico = bd.ler_historico(caminho)
            ultima = historico[(historico["ID"] == p_h) & (historico["TIPO"] == v.TIPO_PROPOSTA)].iloc[-1]
            assert ultima["ID"] == p_h and ultima["DE"] == NOTA and ultima["PARA"] == EFETIVADO, dict(ultima)
            assert status_de(p_h) == EFETIVADO
            print("OK: 'Nota fiscal enviada' na planilha aparece como 'NF enviada' (etiqueta, trilha, bolinha, card da proposta, "
                  "formulário); gravar deixa 'NF enviada' sem reiniciar a etapa.")

            linha("9) Banco aprovado, ainda nao fechado: dica ao lado do circulo; o circulo e a trilha explicam")
            EXPLICACAO = ("Círculo: marque quando o cliente fechar com este banco. "
                          "Pontinhos: Aprovado → Assinado → NF enviada → Efetivado.")
            assert card_mod.EXPLICACAO_DA_TRILHA == EXPLICACAO
            id_i, p_i = v.criar_venda(fx.CPF_JOAO, ["Item I"], _pedido(b1, EQUIPAMENTO="Item I"))
            v.mudar_status_proposta(p_i, APROVADO)
            tela.carregar()
            _processar()
            card = card_de(tela, id_i)
            l = linha_do(card, p_i)
            dica = l["dica_fechar"]
            assert dica is not None and dica.text() == "cliente fechou? marque o círculo" and not l["anel"].fechado
            assert dica.property("role") == "dica" and dica.textFormat() != Qt.TextFormat.RichText, "texto pequeno, sem fundo"
            for tema in (TEMA_CLARO, TEMA_ESCURO):  # a regra existe nos dois temas: 11 px (menor que os 13 do texto), sem fundo
                css = build_stylesheet(tema)
                regra = css[css.index('QLabel[role="dica"]'):].split("}")[0]
                assert "font-size: 11px" in regra and "background-color: transparent" in regra and "border" not in regra
            assert "Marcar como fechado" in l["anel"].dica and EXPLICACAO in l["anel"].dica and l["anel"].toolTip() == l["anel"].dica
            assert dica.toolTip() == EXPLICACAO
            # no layout, a dica fica na mesma linha do circulo, depois do nome do banco
            linha_layout = l["widget"].layout().itemAt(0).layout()
            ordem = [linha_layout.itemAt(i).widget() for i in range(linha_layout.count()) if linha_layout.itemAt(i).widget()]
            assert ordem.index(l["anel"]) < ordem.index(dica) < ordem.index(l["pilula"])
            # o card da proposta tem a mesma dica
            itens = v.propostas_na_lista_do_arquivo(bd.ler_propostas(caminho))
            cartao = CardDaProposta(next(i for i in itens.values() if i.proposta.id == p_i))
            assert cartao.controles["dica_fechar"] is not None and cartao.controles["dica_fechar"].text() == dica.text()
            cartao.close()
            # marcado como fechado: a dica some, a trilha aparece e a explicacao fica no circulo e na trilha
            l["anel"].click()
            _processar()
            card = card_de(tela, id_i)
            l = linha_do(card, p_i)
            assert l["anel"].fechado and l["dica_fechar"] is None
            assert EXPLICACAO in l["anel"].dica
            trilha = l["trilha"]
            assert trilha.dica_completa(0).startswith("Aprovado") and trilha.dica_completa(0).endswith("\n" + EXPLICACAO)
            assert trilha.dica_completa(None) == EXPLICACAO
            # banco nao aprovado (Em Analise): sem circulo e sem dica; negado, idem
            id_j, p_j = v.criar_venda(fx.CPF_JOAO, ["Item J"], _pedido(b2, EQUIPAMENTO="Item J"))
            tela.carregar()
            _processar()
            lj = linha_do(card_de(tela, id_j), p_j)
            assert lj["anel"] is None and lj["dica_fechar"] is None
            # venda perdida: o circulo nao e oferecido, entao a dica tambem nao
            v.mudar_status_proposta(p_j, APROVADO)
            v.mudar_status_venda(id_j, v.VENDA_PERDIDA, motivo="Desistiu")
            tela.carregar()
            _processar()
            lj = linha_do(card_de(tela, id_j), p_j)
            assert lj["anel"] is None and lj["dica_fechar"] is None
            print("OK: banco aprovado e ainda não fechado: dica pequena 'cliente fechou? marque o círculo' ao lado do círculo; "
                  "círculo e trilha explicam círculo e pontinhos; some ao fechar, e não aparece em banco sem círculo.")

            linha("TUDO OK")
    finally:
        v.datetime = datetime_original
        nuvem._obter_cliente, sheets_sync._obter_cliente = rede_original
        fx.restaurar_modulos()
        sessao_mod.encerrar()
        assert fx.instantaneo_do_registro() == registro_antes, "o teste mexeu nas preferencias REAIS do app"


if __name__ == "__main__":
    main()
