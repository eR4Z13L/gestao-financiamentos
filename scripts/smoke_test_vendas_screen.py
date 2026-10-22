"""Testa a tela Vendas (desktop/screens/vendas_screen.py) e o que a etapa 3 mudou em volta dela: cards de venda com
as linhas de banco, a troca rapida de status pelos menus das etiquetas (com Desfazer e as confirmacoes), "Nova venda"
e "Mandar a outro banco" (inclusive o pedido de parte da venda), o aviso das propostas sem venda, filtros e busca, o
formulario de proposta criando a venda, e a trava de excluir um banco fechado.

Planilha 100% ficticia em pasta temporaria, preferencias isoladas e o Google desligado (qualquer acesso derruba).

Rodar com: venv/Scripts/python.exe scripts/smoke_test_vendas_screen.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False
import fixture_ficticia as fx
from ambiente_de_teste import Mensagens
from core import bancos as bancos_mod
from core import equipamentos as equipamentos_mod
from core import data_store as bd
from core import data_store_sheets as nuvem
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import sheets_sync
from core import vendas as v
from desktop.screens import vendas_screen as tela_mod
from desktop.widgets import card_da_venda as card_mod
from desktop.widgets.card_da_venda import NOVA
from desktop.theme import TEMA_ESCURO, build_stylesheet
from desktop.widgets.campos_da_venda import FormularioDaVenda
from desktop.widgets.formulario_proposta import FormularioProposta
from desktop.widgets.lista_de_vendas import AVISO_VENDA_CRIADA

ADMIN = sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador")


class JanelasSoltas(QObject):
    """Anota toda janela que aparece fora as esperadas (um pedaco de card mostrado antes de ter dono pisca solto)."""

    def __init__(self, *esperadas):
        super().__init__()
        self.esperadas = esperadas
        self.vistas: list[str] = []

    def eventFilter(self, objeto, evento) -> bool:
        if evento.type() == QEvent.Type.Show and objeto.isWidgetType() and objeto.isWindow() and objeto not in self.esperadas:
            self.vistas.append(type(objeto).__name__)
        return False


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _processar() -> None:
    for _ in range(3):
        QApplication.processEvents()


def _acoes(menu) -> dict[str, object]:
    """Texto -> QAction de um menu (e dos submenus, com o texto do submenu na frente)."""
    resultado = {}
    for acao in menu.actions():
        if acao.isSeparator() and not acao.text():
            continue
        resultado[acao.text()] = acao
        if acao.menu() is not None:
            for texto, sub in _acoes(acao.menu()).items():
                resultado[f"{acao.text()} > {texto}"] = sub
    return resultado


def _nomes(tela) -> list[str]:
    return [c.venda.cliente.split()[0] for c in tela.lista.cards]


def _card(tela, cliente: str):
    cards = [c for c in tela.lista.cards if c.venda.cliente.split()[0] == cliente]
    assert len(cards) == 1, (cliente, [c.venda.cliente for c in tela.lista.cards])
    return cards[0]


def _venda(id_venda: str) -> pd.Series:
    vendas = bd.ler_vendas(v._caminho())
    return vendas[vendas["ID_VENDA"] == id_venda].iloc[0]


def _resumo(id_venda: str) -> v.ResumoDaVenda:
    return next(r for r in v.listar_vendas() if r.id == id_venda)


def _colunas_que_encaixam(tela, conferir_distribuicao: bool = True) -> None:
    """As colunas dividem a largura toda (8 px entre elas, nada sobrando na lateral); cada uma empilha os seus cards
    com 8 px entre eles (sem buraco embaixo de um card curto); e, com todos fechados, cada card foi para a coluna
    que estava mais curta."""
    lista = tela.lista
    xs = sorted({c.x() for c in lista.cards})
    assert len(xs) == lista._colunas, (xs, lista._colunas)
    largura_da = {}
    for c in lista.cards:
        largura_da.setdefault(c.x(), set()).add(c.width())
    assert all(len(l) == 1 for l in largura_da.values()), f"cada coluna, uma largura: {largura_da}"
    larguras = [largura_da[x].pop() for x in xs]
    assert max(larguras) - min(larguras) <= 1, f"as colunas dividem a largura por igual (±1 px): {larguras}"
    assert all(xs[i + 1] - (xs[i] + larguras[i]) == 8 for i in range(len(xs) - 1)), f"8 px entre as colunas: {xs} / {larguras}"
    assert xs[0] == 0 and xs[-1] + larguras[-1] == lista.width(), "as colunas vão de uma borda à outra"
    for x in xs:
        pilha = sorted((c for c in lista.cards if c.x() == x), key=lambda c: c.y())
        assert pilha[0].y() == 0 and all(b.y() == a.y() + a.height() + 8 for a, b in zip(pilha, pilha[1:])), \
            f"coluna em x={x}: cards empilhados com 8 px, sem buraco"
    if conferir_distribuicao:
        fundos = dict.fromkeys(xs, 0)
        for c in lista.cards:  # na ordem da lista (a mais recente primeiro)
            assert fundos[c.x()] <= min(fundos.values()) + 4, f"{c.venda.cliente}: foi para a coluna mais curta"
            fundos[c.x()] = c.y() + c.height() + 8


def _pedido(banco: str, valor: float = 50000) -> dict:
    return {"BANCO": banco, "VALOR (R$)": valor, "MESES": 36}


def main() -> None:
    def _sem_rede(*_a, **_k):
        raise AssertionError("o teste tentou acessar o Google de verdade")

    rede_original = (nuvem._obter_cliente, sheets_sync._obter_cliente)
    nuvem._obter_cliente = sheets_sync._obter_cliente = _sem_rede
    pasta = Path(tempfile.mkdtemp(prefix="_smoke_vendas_tela_"))
    registro_antes = fx.instantaneo_do_registro()
    fx.isolar_preferencias(pasta)
    caminho = fx.criar(pasta)
    fx.apontar_modulos_para(caminho)
    sessao_mod.iniciar(ADMIN)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(build_stylesheet(TEMA_ESCURO))
    soltas = JanelasSoltas()
    try:
        with Mensagens() as msgs:
            bancos = bancos_mod.nomes_ativos()
            assert len(bancos) >= 2, bancos
            b1, b2 = bancos[0], bancos[1]
            for nome in ("Cadeira Exemplo", "Laser Exemplo", "Mesa Exemplo", "Mesa Exemplo Nova"):
                equipamentos_mod.cadastrar({"EQUIPAMENTO": nome})  # a lista fechada do campo Equipamento

            linha("1) Sem vendas: a lista vazia (e nenhum aviso de propostas antigas: saiu no plano 1.3)")
            tela = tela_mod.VendasScreen()
            soltas.esperadas = (tela,)
            app.installEventFilter(soltas)
            tela.resize(1100, 760)
            tela.show()
            _processar()
            assert bd.ler_propostas(caminho)["ID_VENDA"].eq("").all(), "a fixture tem propostas sem venda"
            assert not hasattr(tela, "aviso_sem_venda") and not hasattr(tela, "_juntar_em_vendas"), "a tela Vendas não junta mais"
            assert tela.lista.cards == [] and "Nenhuma venda ainda" in tela.lista.vazio.text() and not tela.lista.vazio.isHidden()
            print("OK: sem vendas, a lista vazia e nenhum aviso nem botão 'Juntar em vendas…'.")

            linha("2) Nova venda: um card no topo da lista (sem janela); criada, o card dela abre com o primeiro banco")
            tela.botao_nova.click()
            _processar()
            novo = tela.lista.card_da_nova_venda()
            assert novo is not None and tela.lista.cards[0] is novo and tela.lista.vazio.isHidden()
            d = novo.formulario
            assert isinstance(d, FormularioDaVenda) and d.botao_gravar.text() == "Criar venda"
            assert not hasattr(d, "_banco"), "a venda nasce sem pedido a banco"
            assert not d.gravar() and "Cliente não encontrado" in msgs.ultima()[1]
            rotulo_maria = next(r for r, c in d.campos._clientes_por_rotulo.items() if c == fx.CPF_MARIA)
            d.campos.cliente.setCurrentText(rotulo_maria)
            assert not d.gravar() and "Equipamento em branco" in msgs.ultima()[1]
            assert v.listar_vendas() == [], "recusada: nada gravado"
            equipamentos = d.campos.equipamentos
            assert equipamentos.linhas[0].currentIndex() == -1, "nenhum equipamento escolhido sozinho"
            equipamentos.linhas[0].setCurrentText("Cadeira Exemplo")
            equipamentos.mais.click()
            equipamentos.linhas[1].setCurrentText("Laser Exemplo")
            equipamentos.mais.click()
            equipamentos.linhas[2].setCurrentText("Mesa Exemplo")
            equipamentos.tirar(equipamentos.linhas[2])  # o ✕ tira
            assert equipamentos.equipamentos() == ["Cadeira Exemplo", "Laser Exemplo"]
            d.campos.observacoes.setPlainText("primeira visita")
            msgs.limpar()
            assert d.gravar()
            _processar()
            msgs.exigir_vazio("nova venda válida")
            id_maria = tela.lista.aberta
            assert id_maria and tela.lista.rascunho is None and tela.lista.card_da_nova_venda() is None
            assert v.propostas_da_venda(id_maria).empty and _venda(id_maria)["STATUS"] == v.VENDA_AGUARDANDO
            assert _venda(id_maria)["OBSERVAÇÕES"] == "primeira visita"
            assert tela.texto_aviso.text() == AVISO_VENDA_CRIADA and not tela.faixa_aviso.isHidden()
            card = _card(tela, "MARIA")
            assert card.aberto and card.editando == NOVA and isinstance(card.formulario, FormularioProposta), (
                "o card da venda nova abre com o formulário do primeiro banco")
            assert card.formulario._equipamento.currentText() == "Cadeira Exemplo + Laser Exemplo"
            card.formulario._cancelar_edicao()  # dá pra deixar a venda sem proposta
            _processar()
            card = _card(tela, "MARIA")
            assert card.aberto and card.formulario is None and card.linhas_de_banco == [] and len(v.listar_vendas()) == 1
            assert tela.lista.fechar_venda()
            _processar()
            card = _card(tela, "MARIA")
            assert card.venda.equipamentos == "Cadeira Exemplo + Laser Exemplo" and card.linhas_de_banco == []
            assert card.adicionar_vazio is not None and not card.aberto
            print("OK: o card 'Nova venda' no topo; sem cliente e sem equipamento recusa com o motivo; criada, abre com o "
                  "primeiro banco (cancelável: fica 'Nenhuma proposta ainda').")

            linha("3) + Adicionar proposta: o formulário de sempre, dentro do card aberto")
            card.adicionar_vazio.click()
            _processar()
            card = _card(tela, "MARIA")
            assert card.aberto and card.editando == NOVA and card.formulario is not None
            f = card.formulario
            assert f._equipamento.currentText() == "Cadeira Exemplo + Laser Exemplo", "cobre a venda toda"
            f._banco.setCurrentText(b1)
            f._valor.setValue(80000)
            f._meses.setValue(48)
            f._salvar()
            _processar()
            card = _card(tela, "MARIA")
            assert card.aberto and card.formulario is None, "gravou: o card continua aberto, sem o formulário"
            assert [(l["proposta"].banco, l["proposta"].status) for l in card.linhas_de_banco] == [(b1, propostas_mod.STATUS_EM_ANALISE)]
            card.adicionar.click()  # o segundo banco: parte do último pedido
            _processar()
            f = _card(tela, "MARIA").formulario
            assert f._valor.value() == 80000 and f._meses.value() == 48 and f._banco.currentText() == ""
            f._banco.setCurrentText(b2)
            f._equipamento.setCurrentText("Cadeira Exemplo")  # um pedido só de parte da venda
            f._salvar()
            _processar()
            card = _card(tela, "MARIA")
            assert [l["proposta"].banco for l in card.linhas_de_banco] == [b1, b2]
            assert card.linhas_de_banco[1]["proposta"].equipamento == "Cadeira Exemplo"
            assert "só Cadeira Exemplo" in card.linhas_de_banco[1]["condicoes"].text()
            assert tela.lista.fechar_venda() and not _card(tela, "MARIA").aberto
            print("OK: '+ Adicionar proposta' abre o formulário no card; o 2º banco parte de valor e meses do 1º; pedido de parte da venda.")

            linha("4) Banco sem resposta: bolinhas Aprovado/Negado (sem Pré-aprovado); a etiqueta abre os 4; ↩ volta")
            card = _card(tela, "MARIA")
            assert card.bolinha is None, "a venda não tem bolinha: quem avança são os bancos"
            assert card.voltar is None and card.convite is None, "sem status anterior; nenhum banco aprovou ainda"
            assert all(l["anel"] is None for l in card.linhas_de_banco), "sem aprovação, nenhum anel"
            l1 = card.linhas_de_banco[0]
            p1 = l1["proposta"]
            assert [b.destino for b in l1["bolinhas"]] == [propostas_mod.STATUS_APROVADO, propostas_mod.STATUS_NEGADO]
            assert l1["voltar"] is None
            menu_p = _acoes(tela.lista.controle.montar_menu_da_proposta(card.venda, p1))
            assert [t for t in menu_p if t in v.STATUS_DA_PROPOSTA] == v.STATUS_DA_PROPOSTA
            assert menu_p[propostas_mod.STATUS_EM_ANALISE].isChecked()
            menu_p[propostas_mod.STATUS_PRE_APROVADO].trigger()  # Pré-aprovado só pela lista
            card = _card(tela, "MARIA")
            l1 = card.linhas_de_banco[0]
            assert l1["proposta"].status == propostas_mod.STATUS_PRE_APROVADO and len(l1["bolinhas"]) == 2
            assert "Pré-aprovado" in tela.texto_aviso.text() and not tela.faixa_aviso.isHidden()
            l1["bolinhas"][0].click()  # → Aprovado
            card = _card(tela, "MARIA")
            l1 = card.linhas_de_banco[0]
            assert l1["proposta"].status == propostas_mod.STATUS_APROVADO and l1["bolinhas"] == []
            assert l1["voltar"].anterior == propostas_mod.STATUS_PRE_APROVADO
            l1["voltar"].click()
            l1 = _card(tela, "MARIA").linhas_de_banco[0]
            assert l1["proposta"].status == propostas_mod.STATUS_PRE_APROVADO
            assert l1["voltar"].anterior == propostas_mod.STATUS_EM_ANALISE, "↩ de novo recua mais um passo"
            l1["voltar"].click()
            l1 = _card(tela, "MARIA").linhas_de_banco[0]
            assert l1["proposta"].status == propostas_mod.STATUS_EM_ANALISE and l1["voltar"] is None
            print("OK: bolinhas só Aprovado/Negado; Pré-aprovado pela lista; ↩ recua um passo por vez até o início.")

            linha("5) Anel: marcar os bancos que fecharam (vários, sem repetir equipamento); o ✓ desmarca")
            l1["bolinhas"][0].click()  # o 1º banco aprova (cobre a venda toda)
            card = _card(tela, "MARIA")
            card.linhas_de_banco[1]["bolinhas"][0].click()  # o 2º aprova (só a Cadeira)
            card = _card(tela, "MARIA")
            assert card.convite is not None and "2 bancos aprovaram" in card.convite.text()
            aneis = [l["anel"] for l in card.linhas_de_banco]
            assert all(a is not None and not a.fechado for a in aneis) and aneis[0].dica.startswith("Marcar como fechado")
            aneis[0].click()
            venda = _venda(id_maria)
            assert venda["STATUS"] == v.VENDA_EM_ANDAMENTO and v.fechadas_da_venda(venda["BANCO_ESCOLHIDO"]) == [p1.id]
            card = _card(tela, "MARIA")
            l1, l2 = card.linhas_de_banco
            assert l1["anel"].fechado and not l2["anel"].fechado and card.bolinha is None, "a venda não tem bolinha"
            assert [b.destino for b in l1["bolinhas"]] == ["Assinado"], "banco fechado: a bolinha é a próxima etapa (1.2-B)"
            assert l1["bolinhas"][0].dica == "Avançar para Assinado"
            menu_p = _acoes(tela.lista.controle.montar_menu_da_proposta(card.venda, l1["proposta"]))
            assert not menu_p[propostas_mod.STATUS_NEGADO].isEnabled() and menu_p[propostas_mod.STATUS_APROVADO].isEnabled()
            assert card_mod.EFETIVAR in menu_p and "Assinado" in menu_p and "NF enviada" in menu_p, "a lista tem todas as etapas"
            l2["anel"].click()  # a Cadeira já está no pedido do 1º banco
            assert "já está coberto" in msgs.ultima()[2] and v.fechadas_da_venda(_venda(id_maria)["BANCO_ESCOLHIDO"]) == [p1.id]
            l1["voltar"].click()  # o ↩ (para Em Análise) de um banco fechado é recusado
            assert "Desmarque o anel" in msgs.ultima()[2]
            _card(tela, "MARIA").linhas_de_banco[0]["anel"].click()  # o ✓ desmarca
            venda = _venda(id_maria)
            assert venda["STATUS"] == v.VENDA_AGUARDANDO and venda["BANCO_ESCOLHIDO"] == ""
            assert _card(tela, "MARIA").linhas_de_banco[0]["voltar"].anterior == propostas_mod.STATUS_EM_ANALISE,                 "marcar/desmarcar o anel não é troca de status: o ↩ continua apontando pro status de antes"
            _card(tela, "MARIA").linhas_de_banco[1]["anel"].click()  # agora a Cadeira, pelo 2º banco
            assert v.fechadas_da_venda(_venda(id_maria)["BANCO_ESCOLHIDO"]) == [card.linhas_de_banco[1]["proposta"].id]
            print("OK: o anel marca os bancos que fecharam; um equipamento já coberto é recusado com o motivo; o fechado "
                  "não muda de resposta nem volta; o ✓ desmarca; a venda fica Em andamento / Aguardando bancos sozinha.")

            linha("6) Cada banco fechado efetiva sozinho; a venda fica Efetivada quando todos efetivam")
            p_laser = v.mandar_a_outro_banco(id_maria, {**_pedido(b1), "EQUIPAMENTO": "Laser Exemplo"})
            v.mudar_status_proposta(p_laser, propostas_mod.STATUS_APROVADO)
            tela.carregar()
            linha_de = lambda id_: next(l for l in _card(tela, "MARIA").linhas_de_banco if l["proposta"].id == id_)  # noqa: E731
            linha_de(p_laser)["anel"].click()
            p_cadeira = _card(tela, "MARIA").linhas_de_banco[1]["proposta"].id
            assert v.fechadas_da_venda(_venda(id_maria)["BANCO_ESCOLHIDO"]) == [p_cadeira, p_laser], "dois bancos fechados"
            status_de = lambda id_: bd.ler_propostas(caminho).loc[v.indice_da_proposta(id_), "STATUS"]  # noqa: E731
            for esperado in ("Assinado", "NF enviada"):  # a bolinha avança UMA etapa de cada vez
                linha_de(p_cadeira)["bolinhas"][0].click()
                assert status_de(p_cadeira) == esperado
            assert linha_de(p_cadeira)["bolinhas"][0].destino == "Efetivado"
            msgs.resposta_pergunta = QMessageBox.StandardButton.No
            linha_de(p_cadeira)["bolinhas"][0].click()
            assert status_de(p_cadeira) == "NF enviada", "'Não' no 'saiu o financiamento?': nada muda"
            msgs.resposta_pergunta = QMessageBox.StandardButton.Yes
            linha_de(p_cadeira)["bolinhas"][0].click()
            assert _venda(id_maria)["STATUS"] == v.VENDA_EM_ANDAMENTO, "falta o outro banco"
            assert "1 de 2 bancos efetivados" in _card(tela, "MARIA").andamento.text()
            for _ in range(2):
                linha_de(p_laser)["bolinhas"][0].click()  # Assinado, NF enviada
            linha_de(p_laser)["bolinhas"][0].click()
            assert _venda(id_maria)["STATUS"] == v.VENDA_EFETIVADA and "A venda está Efetivada" in tela.texto_aviso.text()
            assert all(c.venda.id != id_maria for c in tela.lista.cards), "efetivada sai de 'Em andamento'"
            tela.filtro.setCurrentText(tela_mod.FILTRO_EFETIVADAS)
            card = _card(tela, "MARIA")
            assert linha_de(p_cadeira)["anel"].dica.startswith("Fechado\n") and "clique para desmarcar" not in linha_de(p_cadeira)["anel"].dica
            menu_v = _acoes(tela.lista.controle.montar_menu_da_venda(card.venda))
            assert f"{v.VENDA_NAO_EFETIVADA}…" in menu_v and not any(t.startswith("Reabrir") for t in menu_v)
            tela.lista.abrir_venda(card.venda)
            assert _card(tela, "MARIA").adicionar is not None, "Efetivada ainda aceita outro pedido"
            tela.lista.fechar_venda()
            linha_de(p_laser)["voltar"].click()  # ↩: o laser volta a Aprovado
            assert _venda(id_maria)["STATUS"] == v.VENDA_EM_ANDAMENTO
            v.efetivar_proposta(p_laser)
            tela.filtro.setCurrentText(tela_mod.FILTRO_EM_ANDAMENTO)
            print("OK: bolinha Efetivado só confirmando; 1 de 2 → Em andamento, os 2 → Efetivada; o ↩ de um banco reabre o "
                  "andamento; Efetivada ainda aceita pedido.")

            linha("7) Todos os bancos negaram: o app pergunta, nunca decide sozinho")
            id_joao, id_pj = v.criar_venda(fx.CPF_JOAO, ["Mesa Exemplo"], _pedido(b1))
            id_ana, id_pa = v.criar_venda(fx.CPF_ANA, ["Mesa Exemplo"], _pedido(b2))
            tela.carregar()
            msgs.resposta_pergunta = QMessageBox.StandardButton.No
            card = _card(tela, "JOÃO")
            _acoes(tela.lista.controle.montar_menu_da_proposta(card.venda, card.linhas_de_banco[0]["proposta"]))[propostas_mod.STATUS_NEGADO].trigger()
            assert "Todos os bancos" in msgs.ultima()[1] and _venda(id_joao)["STATUS"] == v.VENDA_AGUARDANDO
            msgs.resposta_pergunta = QMessageBox.StandardButton.Yes
            card = _card(tela, "ANA")
            _acoes(tela.lista.controle.montar_menu_da_proposta(card.venda, card.linhas_de_banco[0]["proposta"]))[propostas_mod.STATUS_NEGADO].trigger()
            venda = _venda(id_ana)
            assert venda["STATUS"] == v.VENDA_PERDIDA and venda["MOTIVO"] == "Todos os bancos negaram"
            print("OK: a última negativa pergunta 'Perdida?': Não deixa aguardando; Sim marca Perdida com o motivo.")

            linha("8) Desfecho com motivo opcional (Não efetivada)")
            card = _card(tela, "JOÃO")
            exec_original = card_mod.DesfechoDialog.exec

            def _escolhe_desistiu(dialogo):
                dialogo.motivo.setCurrentIndex(dialogo.motivo.findData("Desistiu"))
                return QDialog.DialogCode.Accepted

            card_mod.DesfechoDialog.exec = _escolhe_desistiu
            try:
                _acoes(tela.lista.controle.montar_menu_da_venda(card.venda))[f"{v.VENDA_NAO_EFETIVADA}…"].trigger()
            finally:
                card_mod.DesfechoDialog.exec = exec_original
            venda = _venda(id_joao)
            assert venda["STATUS"] == v.VENDA_NAO_EFETIVADA and venda["MOTIVO"] == "Desistiu"
            tela.filtro.setCurrentText(tela_mod.FILTRO_PERDIDAS)
            assert set(_nomes(tela)) == {"JOÃO", "ANA"}
            assert any("Motivo: Desistiu" == w.text() for w in _card(tela, "JOÃO").findChildren(type(tela.contador)))
            print("OK: Não efetivada pede confirmação e o motivo (opcional) aparece no card; 'Perdidas e não efetivadas' filtra.")

            linha("9) Busca e contagem")
            tela.filtro.setCurrentText(tela_mod.FILTRO_TODAS)
            assert len(tela.lista.cards) == 3 and tela.contador.text().startswith("3 venda(s)")
            tela.busca.setText("joão")
            assert _nomes(tela) == ["JOÃO"]
            tela.busca.setText(fx.CPF_ANA.replace(".", "").replace("-", "")[:6])
            assert _nomes(tela) == ["ANA"]
            tela.busca.setText(b2.lower())
            assert set(_nomes(tela)) == {"MARIA", "ANA"}, "acha pelo banco"
            tela.busca.clear()
            print("OK: busca por nome (sem diferenciar maiúsculas), por CPF e pelo banco; a contagem é só do que aparece.")

            linha("10) Venda parada há 7 dias ou mais")
            listar_original = v.listar_vendas
            v.listar_vendas = lambda hoje=None: listar_original(date.today() + timedelta(days=propostas_mod.DIAS_PROPOSTA_PARADA))
            try:
                id_parada, _ = v.criar_venda(fx.CPF_ANA, ["Cadeira Exemplo"], _pedido(b1))
                tela.filtro.setCurrentText(tela_mod.FILTRO_PARADAS)
                tela.carregar()
                parados = [c for c in tela.lista.cards if c.venda.id == id_parada]
                assert len(parados) == 1 and parados[0].andamento.parada == "parada há 7 dias"
                assert "parada há 7 dias" in parados[0].andamento.texto
            finally:
                v.listar_vendas = listar_original
            tela.filtro.setCurrentText(tela_mod.FILTRO_EM_ANDAMENTO)
            tela.carregar()
            assert all(c.andamento.parada == "" for c in tela.lista.cards), "hoje nada está parado"
            print("OK: 7 dias sem mudar de etapa: o card mostra 'parada há 7 dias' no texto e entra no filtro 'Paradas'.")

            linha("11) Equipamento só da lista; o formulário solto cria a venda; numa venda, as caixinhas dela")
            antes = len(bd.ler_vendas(caminho))
            f = FormularioProposta(fx.CPF_JOAO, "JOÃO")
            assert [f._status.itemText(i) for i in range(f._status.count())] == v.STATUS_DA_PROPOSTA
            assert not f._equipamento.isEditable(), "o equipamento não se digita: vem do cadastro"
            itens = [f._equipamento.itemText(i) for i in range(f._equipamento.count())]
            assert "Laser Exemplo" in itens and "Mesa Exemplo" in itens
            f._valor.setValue(40000)
            f._equipamento.setCurrentText("Laser Exemplo")
            f._salvar()
            assert "Banco em branco" in msgs.ultima()[1], "proposta nova exige o banco"
            f._banco.setCurrentText(b1)
            msgs.limpar()
            f._salvar()
            msgs.exigir_vazio("proposta nova pelo formulário")
            vendas = bd.ler_vendas(caminho)
            assert len(vendas) == antes + 1 and vendas.iloc[-1]["EQUIPAMENTOS"] == "Laser Exemplo"
            nova = bd.ler_propostas(caminho).loc[f.indice_gravado]
            assert nova["ID_VENDA"] == vendas.iloc[-1]["ID_VENDA"] and nova["BANCO"] == b1
            v.editar_venda(nova["ID_VENDA"], ["Laser Exemplo", "Mesa Exemplo"], "")  # a venda ganhou outro equipamento
            base = propostas_mod.dados_para_duplicar(nova.to_dict())
            assert base["ID_VENDA"] == nova["ID_VENDA"] and base["BANCO"] == ""
            dup = FormularioProposta(fx.CPF_JOAO, "JOÃO", base={**base, "EQUIPAMENTO": ""})
            caixas = dup._equipamento.caixas
            assert [c.text() for c in caixas] == ["Laser Exemplo", "Mesa Exemplo"] and all(c.isChecked() for c in caixas),                 "numa venda: uma caixinha por equipamento dela, todas marcadas"
            caixas[0].setChecked(False)  # este banco só financia a mesa
            dup._banco.setCurrentText(b2)
            dup._salvar()
            assert len(bd.ler_vendas(caminho)) == antes + 1, "não cria outra venda"
            da_venda = v.propostas_da_venda(nova["ID_VENDA"])
            assert len(da_venda) == 2 and da_venda.iloc[-1]["EQUIPAMENTO"] == "Mesa Exemplo"
            todas_desmarcadas = FormularioProposta(fx.CPF_JOAO, "JOÃO", base={**base, "EQUIPAMENTO": ""})
            for caixa in todas_desmarcadas._equipamento.caixas:
                caixa.setChecked(False)
            todas_desmarcadas._banco.setCurrentText(b1)
            todas_desmarcadas._salvar()
            assert "equipamento" in msgs.ultima()[2], "sem nenhuma caixinha marcada não grava"
            existente = FormularioProposta(fx.CPF_JOAO, "JOÃO", proposta=nova.to_dict(), indice=f.indice_gravado)
            assert existente._botao_editar.text() == "Editar" and not hasattr(existente, "_botao_duplicar")
            assert [c.isChecked() for c in existente._equipamento.caixas] == [True, False], "marca só o que ela cobre"
            assert all(not c.isEnabled() for c in existente._equipamento.caixas), "na leitura, travadas"
            print("OK: lista fechada fora da venda (cria a venda); numa venda, uma caixinha por equipamento dela, todas "
                  "marcadas de início, travadas na leitura; nenhuma marcada não grava.")

            linha("12) Não exclui um banco fechado de uma venda")
            try:
                propostas_mod.remover_proposta(v.indice_da_proposta(p_cadeira))
                raise AssertionError("deveria recusar")
            except propostas_mod.ErroProposta as exc:
                assert "fechado" in str(exc)
            propostas_mod.remover_proposta(v.indice_da_proposta(p1.id))  # o 1º banco não fechou: pode sair
            assert p1.id not in set(v.propostas_da_venda(id_maria)["ID_PROPOSTA"])
            print("OK: excluir um banco fechado é recusado com o motivo; os outros da venda podem ser excluídos.")

            linha("13) A setinha ↩ nunca leva a um status impossível; na venda, reabre")
            id_rx, px = v.criar_venda(fx.CPF_JOAO, ["Cadeira Exemplo"], _pedido(b1))
            v.mudar_status_proposta(px, propostas_mod.STATUS_APROVADO)
            v.fechar_proposta(px)
            v.mudar_status_venda(id_rx, v.VENDA_PERDIDA, motivo="Desistiu")
            tela.filtro.setCurrentText(tela_mod.FILTRO_TODAS)
            tela.carregar()
            card = next(c for c in tela.lista.cards if c.venda.id == id_rx)
            assert card.voltar.anterior == v.VENDA_EM_ANDAMENTO, "reabrir volta ao calculado pelos bancos"
            assert card.linhas_de_banco[0]["anel"].fechado and card.linhas_de_banco[0]["bolinhas"] == [], "perdida: nada avança"
            msgs.resposta_pergunta = QMessageBox.StandardButton.No
            card.voltar.click()
            assert "Reabrir" in msgs.ultima()[1] and _venda(id_rx)["STATUS"] == v.VENDA_PERDIDA
            msgs.resposta_pergunta = QMessageBox.StandardButton.Yes
            card.voltar.click()
            assert _venda(id_rx)["STATUS"] == v.VENDA_EM_ANDAMENTO and _venda(id_rx)["MOTIVO"] == ""
            assert next(c for c in tela.lista.cards if c.venda.id == id_rx).voltar is None, "fora de um desfecho, a venda não tem ↩"
            # uma venda Efetivada com pendencia aberta (1.2-B) continua Efetivada: sem ↩ e sem item de "voltar" no menu
            id_rp, pp = v.criar_venda(fx.CPF_JOAO, ["Mesa Exemplo"], _pedido(b1))
            v.mudar_status_proposta(pp, propostas_mod.STATUS_APROVADO)
            v.fechar_proposta(pp)
            v.efetivar_proposta(pp)
            v.adicionar_pendencia(id_rp, "Aguardando a obra")
            tela.carregar()
            card = next(c for c in tela.lista.cards if c.venda.id == id_rp)
            assert card.venda.status == v.VENDA_EFETIVADA and card.venda.pendencias_abertas == 1 and card.voltar is None
            menu_p = _acoes(tela.lista.controle.montar_menu_da_venda(card.venda))
            assert not any(t.startswith(("Voltar a venda", "Reabrir")) for t in menu_p)
            # proposta com status de antes das vendas: depois de trocar, o ↩ não oferece voltar a ele
            id_ry, py_ = v.criar_venda(fx.CPF_ANA, ["Laser Exemplo"], _pedido(b2))
            propostas_mod.atualizar_proposta(v.indice_da_proposta(py_), {"STATUS": "Nota Fiscal Anexada"})
            v.mudar_status_proposta(py_, propostas_mod.STATUS_APROVADO)
            tela.carregar()
            card = next(c for c in tela.lista.cards if c.venda.id == id_ry)
            assert card.linhas_de_banco[0]["proposta"].status == propostas_mod.STATUS_APROVADO
            assert card.linhas_de_banco[0]["voltar"] is None, "não volta a um status de antes das vendas"
            tela.filtro.setCurrentText(tela_mod.FILTRO_EM_ANDAMENTO)
            print("OK: o ↩ da venda só existe num desfecho e reabre (perguntando); nunca volta a um status de antes das vendas.")

            linha("14) Colunas que encaixam; o card abre para baixo na própria coluna; editar no formulário; um aberto por vez")
            id_x, px = v.criar_venda(fx.CPF_MARIA, ["Mesa Exemplo"], _pedido(b1))
            px2 = v.mandar_a_outro_banco(id_x, _pedido(b2))
            tela.filtro.setCurrentText(tela_mod.FILTRO_TODAS)
            tela.carregar()
            _processar()
            assert tela.lista._colunas == 2, f"a tela de teste cabe 2 colunas ({tela.lista._colunas})"
            achar = lambda id_: next(c for c in tela.lista.cards if c.venda.id == id_)  # noqa: E731
            _colunas_que_encaixam(tela)
            lugar_antes = {c.venda.id: c.x() for c in tela.lista.cards}
            card = achar(id_x)
            largura_fechado, altura_fechado = card.width(), card.height()
            assert card.linhas_de_banco[0]["lapis"] is None and card.abrir_ficha is None, "fechado: sem ✎ nem rodapé"
            QTest.mouseDClick(card, Qt.MouseButton.LeftButton, pos=card.rect().topLeft() + QPoint(30, 12))
            _processar()
            card = achar(id_x)
            assert card.aberto and tela.lista.aberta == id_x
            assert card.width() == largura_fechado and card.height() > altura_fechado, "aberto: mesma largura, cresce para baixo"
            assert {c.venda.id: c.x() for c in tela.lista.cards} == lugar_antes, "abrir não tira ninguém da coluna"
            _colunas_que_encaixam(tela, conferir_distribuicao=False)
            assert all(l["lapis"] is not None for l in card.linhas_de_banco) and card.abrir_ficha is not None
            fichas = []
            tela.ficha_pedida.connect(fichas.append)
            card.abrir_ficha.click()
            assert fichas == [fx.CPF_MARIA], "'Abrir a ficha' só no card aberto"
            tela.busca.setText("nenhuma venda tem isto")
            _processar()
            assert [c.venda.id for c in tela.lista.cards] == [id_x] and tela.lista.card_aberto() is not None, \
                "o card aberto continua na lista mesmo fora da busca (não some no meio da edição)"
            sozinho = achar(id_x).width()
            assert abs(sozinho - (tela.lista.width() - 8) / 2) <= 8, \
                f"sozinho na lista, o card continua do tamanho de uma coluna (não da linha toda): {sozinho} / {tela.lista.width()}"
            tela.busca.clear()
            _processar()
            card = achar(id_x)
            linha_x = card.linhas_de_banco[0]["widget"]
            QTest.mouseDClick(linha_x, Qt.MouseButton.LeftButton, pos=QPoint(60, 8))
            _processar()
            card = achar(id_x)
            assert card.editando == px and card.formulario is not None and card.botao_excluir is not None
            assert card.width() == largura_fechado and {c.venda.id: c.x() for c in tela.lista.cards} == lugar_antes, \
                "com o formulário aberto (o card bem mais alto), ninguém troca de coluna"
            # mesmo se, ao remontar (gravou algo, releu), um card do topo medir bem mais alto, ninguém troca de coluna
            primeiro = tela.lista.cards[0].venda.id
            altura_de_verdade = card_mod.CardDaVenda.heightForWidth
            card_mod.CardDaVenda.heightForWidth = lambda c, w: 3000 if c.venda.id == primeiro else altura_de_verdade(c, w)
            try:
                tela.carregar()
                _processar()
                assert {c.venda.id: c.x() for c in tela.lista.cards} == lugar_antes, "remontar não redistribui as colunas"
            finally:
                card_mod.CardDaVenda.heightForWidth = altura_de_verdade
            # o que foi digitado sobrevive a montagem: a busca, o filtro e reler (depois de gravar outro card)
            digitado = achar(id_x).formulario
            digitado._valor.setValue(12345)
            for mudar in (lambda: tela.busca.setText("nenhuma venda tem isto"), tela.busca.clear,
                          lambda: tela.filtro.setCurrentText(tela_mod.FILTRO_EFETIVADAS),
                          lambda: tela.filtro.setCurrentText(tela_mod.FILTRO_TODAS), tela.carregar):
                mudar()
                _processar()
                card = achar(id_x)
                assert card.formulario is digitado and card.editando == px, "o mesmo formulário volta ao card"
                assert digitado._valor.value() == 12345 and digitado.isVisible(), "com o que já foi digitado, à vista"
            assert tela.tem_edicao_pendente()
            print("OK: com o formulário aberto, mudar a busca, o filtro ou reler não apaga o que foi digitado.")
            card = achar(id_x)
            f = card.formulario
            assert not f._modo_leitura and [f._status.itemText(i) for i in range(f._status.count())] == v.STATUS_DA_PROPOSTA
            f._valor.setValue(90000)
            f._status.setCurrentText(propostas_mod.STATUS_APROVADO)
            f._salvar()
            _processar()
            gravada = bd.ler_propostas(caminho).loc[v.indice_da_proposta(px)]
            assert gravada["VALOR (R$)"] == 90000 and gravada["STATUS"] == propostas_mod.STATUS_APROVADO
            hist = bd.ler_historico(caminho)
            assert ((hist["ID"] == px) & (hist["PARA"] == propostas_mod.STATUS_APROVADO)).any(), "editar no formulário vai pro histórico"
            print("OK: dois cliques abre o card na linha toda (✎ e rodapé só aberto); dois cliques no banco abre o formulário; "
                  "gravar valor e status passa pelo histórico.")

            linha("15) Card aberto: nada digitado se perde; cancelar; excluir; editar a venda")
            card = achar(id_x)
            card.linhas_de_banco[1]["lapis"].click()
            _processar()
            f = achar(id_x).formulario
            f._valor.setValue(12345)
            assert tela.tem_edicao_pendente()
            outra = next(c for c in tela.lista.cards if c.venda.id != id_x)
            msgs.resposta_pergunta = QMessageBox.StandardButton.No
            assert tela.lista.abrir_venda(outra.venda) is False and tela.lista.aberta == id_x
            assert "não foram salvas" in msgs.ultima()[2] and achar(id_x).formulario._valor.value() == 12345
            v.editar_venda(outra.venda.id, outra.venda.equipamentos.split(" + "), "mudou por fora")  # outra tela gravou
            assert tela.recarregar_se_mudou() is False, "com algo digitado, o arquivo mudar por fora não relê a tela"
            assert achar(id_x).formulario._valor.value() == 12345
            msgs.resposta_pergunta = QMessageBox.StandardButton.Yes
            achar(id_x).formulario._cancelar_edicao()
            _processar()
            card = achar(id_x)
            assert card.aberto and card.formulario is None, "Cancel fecha o formulário; o card continua aberto"
            card.linhas_de_banco[1]["lapis"].click()
            _processar()
            achar(id_x).botao_excluir.click()
            _processar()
            assert [p.id for p in achar(id_x).venda.propostas] == [px], "excluída (depois de confirmar)"
            achar(id_x).editar_venda.click()  # no próprio card, sem janela
            _processar()
            card = achar(id_x)
            assert card.editando == card_mod.EDITAR_VENDA and isinstance(card.formulario, FormularioDaVenda)
            assert card.editar_venda.isHidden() and card.formulario.campos.cliente is None, "o cliente não muda"
            card.formulario.campos.equipamentos.linhas[0].setCurrentText("Mesa Exemplo Nova")
            card.formulario.campos.observacoes.setPlainText("cliente pediu urgência")
            assert card.formulario.gravar()
            _processar()
            venda = _venda(id_x)
            assert venda["EQUIPAMENTOS"] == "Mesa Exemplo Nova" and venda["OBSERVAÇÕES"] == "cliente pediu urgência"
            card = achar(id_x)
            assert any("cliente pediu urgência" in w.text() for w in card.findChildren(type(tela.contador)))
            assert tela.lista.fechar_venda() and tela.lista.aberta is None
            tela.filtro.setCurrentText(tela_mod.FILTRO_EM_ANDAMENTO)
            print("OK: trocar de card com algo digitado pergunta (Não mantém); Cancel fecha o formulário; excluir confirma; "
                  "'Editar a venda' troca equipamentos e observações.")

            linha("16) Gravar não leva a lista pro topo (o card continua à vista)")
            for i in range(12):
                v.criar_venda((fx.CPF_MARIA, fx.CPF_JOAO, fx.CPF_ANA)[i % 3], [f"Equipamento Rolagem {i}"],
                              _pedido((b1, b2)[i % 2], 1000 + i))
            tela.filtro.setCurrentText(tela_mod.FILTRO_TODAS)
            tela.carregar()
            _processar()
            barra = tela.rolagem.verticalScrollBar()
            barra.setValue(barra.maximum())
            _processar()
            antes = barra.value()
            assert antes > 200, f"a lista precisa rolar pro teste valer ({antes})"
            ultimo = next(c for c in reversed(tela.lista.cards) if c.linhas_de_banco and c.linhas_de_banco[0]["bolinhas"])
            id_ultimo = ultimo.venda.id
            ultimo.linhas_de_banco[0]["bolinhas"][0].click()
            _processar()
            assert barra.value() == antes, f"a rolagem foi de {antes} para {barra.value()}"
            assert tela.rolagem.widget().minimumHeight() == 0, "a altura da lista fica solta de novo (senão não encolhe mais)"
            card = next(c for c in tela.lista.cards if c.venda.id == id_ultimo)
            topo = card.mapTo(tela.rolagem.viewport(), card.rect().topLeft()).y()
            assert 0 <= topo < tela.rolagem.viewport().height(), "o card clicado continua na tela"
            tela.filtro.setCurrentText(tela_mod.FILTRO_EM_ANDAMENTO)
            print(f"OK: clicar na bolinha de uma venda lá embaixo mantém a rolagem ({antes}) e o card à vista.")

            linha("16b) As colunas acompanham a janela (quantas couberem sem espremer o card)")
            # uma venda de texto bem comprido: o card dela não pode alargar a coluna (nem empurrar a janela)
            comprido = " + ".join(f"Equipamento de Demonstração Bem Comprido Número {n}" for n in range(1, 7))
            v.criar_venda(fx.CPF_ANA, [comprido], _pedido(b1))
            tela.filtro.setCurrentText(tela_mod.FILTRO_TODAS)
            tela.carregar()
            _processar()
            for largura_janela, esperadas in ((1700, 3), (1100, 2), (760, 1), (1700, 3)):
                tela.resize(largura_janela, 760)
                for _ in range(3):
                    _processar()
                assert tela.lista._colunas == esperadas, (largura_janela, tela.lista._colunas, esperadas)
                visivel = tela.rolagem.viewport().width()
                assert max(c.geometry().right() for c in tela.lista.cards) < visivel, \
                    f"{largura_janela}: nenhum card cortado na borda ({visivel})"
                assert min(c.width() for c in tela.lista.cards) >= card_mod.LARGURA_CARD, "nenhum card espremido"
                _colunas_que_encaixam(tela)
            tela.resize(1100, 760)
            _processar()
            tela.filtro.setCurrentText(tela_mod.FILTRO_EM_ANDAMENTO)
            print("OK: 3 colunas numa janela larga, 2 na média, 1 na estreita (e de volta a 3), sem cortar nem espremer.")

            linha("17) Nenhuma janela solta piscou")
            _processar()
            assert soltas.vistas == [], soltas.vistas
            print("OK: nenhum pedaço de card apareceu como janela solta.")
        linha("TUDO OK")
    finally:
        app.removeEventFilter(soltas)
        nuvem._obter_cliente, sheets_sync._obter_cliente = rede_original
        fx.restaurar_modulos()
        sessao_mod.encerrar()
        assert fx.instantaneo_do_registro() == registro_antes, "o teste mexeu nas preferências reais"


if __name__ == "__main__":
    main()
