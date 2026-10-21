"""Testa a tela das etapas e das pendencias (plano 1.2-B, parte 2): no card da venda e no da proposta, a linha de cada
banco fechado (etiqueta com a cor da etapa, trilha de 4 pontos, "desde 15/10 · há 3 dias", selo de parada, a bolinha
que avanca UMA etapa, a lista da etiqueta com todas as etapas, o ↩); as pendencias (etiqueta "N pendências" no card
fechado, "+ Pendência", lista com "Resolvida" no card aberto, filtro "Com pendências"); e as observacoes no topo do
card fechado (ate 2 linhas).

Planilha 100% ficticia em pasta temporaria, preferencias isoladas e o Google desligado.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_tela_1_2b.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from PySide6.QtWidgets import QApplication, QMessageBox

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
from desktop.screens import vendas_screen as tela_mod
from desktop.theme import CORES_STATUS, TEMA_CLARO, TEMA_ESCURO, build_stylesheet
from desktop.widgets import card_da_venda as card_mod
from desktop.widgets.card_da_proposta import CardDaProposta
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
            assert l["selo"] is None and card.selo is None
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
            assert l1["selo"] is not None and l1["selo"].texto == "parada há 9 dias" and l2["selo"] is None
            assert card.selo is not None and card.selo.texto == "parada há 9 dias", "no topo, a maior parada"
            assert "parada" not in card.andamento.text(), "o selo diz; o texto de andamento não repete"
            # venda sem banco parado e com pendencia aberta antiga: sem selo
            assert card_de(tela, id_a).selo is None
            tela.filtro.setCurrentText(tela_mod.FILTRO_PARADAS)
            assert [c.venda.id for c in tela.lista.cards] == [id_b]
            tela.filtro.setCurrentText(tela_mod.FILTRO_TODAS)
            # desfecho: os bancos de uma venda perdida nao alertam
            v.mudar_status_venda(id_b, v.VENDA_PERDIDA, motivo="Desistiu")
            tela.carregar()
            card = card_de(tela, id_b)
            assert card.selo is None and linha_do(card, p_b1)["selo"] is None
            v.reabrir_venda(id_b)
            tela.carregar()
            _processar()
            print("OK: selo no banco parado há 9 dias e, no topo, o maior; nada para o banco recente nem para a pendência "
                  "antiga; venda perdida não mostra selo; o filtro 'Paradas' acha só a parada.")

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
            assert cartao.controles["data"].text() == f"desde {hoje - timedelta(days=8):%d/%m} · há 8 dias"
            assert cartao.controles["selo"] is not None and cartao.controles["selo"].texto == "parada há 8 dias"
            assert [b.destino for b in cartao.controles["bolinhas"]] == ["Assinado"]
            solto = next(i for i in itens.values() if not i.proposta.fechada)
            c2 = CardDaProposta(solto)
            assert c2.controles["trilha"] is None and c2.controles["data"] is None and c2.controles["selo"] is None
            cartao.close()
            c2.close()
            print("OK: no card da proposta, banco fechado tem trilha, data, selo e a bolinha da próxima etapa; os outros não.")

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

            linha("TUDO OK")
    finally:
        v.datetime = datetime_original
        nuvem._obter_cliente, sheets_sync._obter_cliente = rede_original
        fx.restaurar_modulos()
        sessao_mod.encerrar()
        assert fx.instantaneo_do_registro() == registro_antes, "o teste mexeu nas preferencias REAIS do app"


if __name__ == "__main__":
    main()
