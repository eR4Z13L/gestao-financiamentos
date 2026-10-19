"""Testa a venda num card (sem janela) e o "+ Nova proposta" escolhendo a venda (plano aprovado em 05/10/2026):

- core: as vendas EM ABERTO do cliente (Aguardando bancos e Em andamento; a mais recente primeiro) e o rotulo de cada;
- o card "Nova venda" no topo da lista de vendas: criar, cancelar, validar cliente/equipamento, um por vez, o digitado
  nao se perde (busca, filtro, reler, abrir outro card pergunta), e criada, o card dela abre com o primeiro banco;
- o mesmo banco mais de uma vez na mesma venda (permitido);
- o "Editar a venda" no proprio card aberto (Gravar/Cancelar, validacao, pergunta antes de descartar);
- o "+ Nova proposta" de Todas as Propostas: cliente, venda (em aberto, a mais recente marcada; ou venda nova),
  gravando na venda escolhida ou criando a venda junto;
- o VENDEDOR sem nada disso.
(Os caminhos da barra lateral e da Ficha: smoke_test_barra_lateral.py e smoke_test_ficha_vendas.py.)

Planilha 100% ficticia em pasta temporaria, preferencias isoladas e o Google desligado (qualquer acesso derruba).

Rodar com: venv/Scripts/python.exe scripts/smoke_test_venda_num_card.py
"""

from __future__ import annotations

import dataclasses
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QFrame, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False
import fixture_ficticia as fx
from ambiente_de_teste import Mensagens
from core import bancos as bancos_mod
from core import data_store as bd
from core import data_store_sheets as nuvem
from core import equipamentos as equipamentos_mod
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import sheets_sync
from core import vendas as v
from desktop.screens import propostas_screen as propostas_tela_mod
from desktop.screens import vendas_screen as tela_mod
from desktop.theme import TEMA_ESCURO, build_stylesheet
from desktop.widgets.campos_da_venda import FormularioDaVenda, LinhasDeEquipamento
from desktop.widgets.card_da_proposta import CardNovaProposta
from desktop.widgets.card_da_venda import EDITAR_VENDA, NOVA, CardNovaVenda
from desktop.widgets.formulario_proposta import VENDA_NOVA_COM_A_PROPOSTA, FormularioProposta, _CaixasDeEquipamento
from desktop.widgets.lista_de_propostas import ListaDePropostas
from desktop.widgets.lista_de_vendas import AVISO_VENDA_CRIADA, ListaDeVendas

ADMIN = sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador")
SIM, NAO = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No


class JanelasSoltas(QObject):
    """Anota toda janela que aparece fora as esperadas: nada destas telas pode abrir janela (nem piscar solto)."""

    def __init__(self):
        super().__init__()
        self.esperadas: tuple = ()
        self.vistas: list[str] = []

    def eventFilter(self, objeto, evento) -> bool:
        if evento.type() == QEvent.Type.Show and objeto.isWidgetType() and objeto.isWindow() and objeto not in self.esperadas:
            self.vistas.append(type(objeto).__name__)
        return False


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _processar() -> None:
    for _ in range(4):
        QApplication.processEvents()


def _pedido(banco: str, valor: float = 50000) -> dict:
    return {"BANCO": banco, "VALOR (R$)": valor, "MESES": 36}


def _venda(id_venda: str) -> pd.Series:
    vendas = bd.ler_vendas(v._caminho())
    return vendas[vendas["ID_VENDA"] == id_venda].iloc[0]


def _rotulo(cpf: str) -> str:
    """O rotulo do cliente na busca ("NOME — CPF")."""
    clientes = bd.ler_clientes(v._caminho())
    c = clientes[clientes["CPF/CNPJ"] == cpf].iloc[0]
    return f"{c['CLIENTE']} — {c['CPF/CNPJ']}"


def _tecla(widget: QWidget, tecla) -> None:
    QApplication.sendEvent(widget, QKeyEvent(QEvent.Type.KeyPress, tecla, Qt.KeyboardModifier.NoModifier))


def _opcoes(combo) -> list[str]:
    return [combo.itemText(i) for i in range(combo.count())]


def testar_core(b1: str) -> dict:
    linha("1) core: as vendas em aberto do cliente (as que o '+ Nova proposta' oferece)")
    id_aguardando, _ = v.criar_venda(fx.CPF_MARIA, ["Cadeira Exemplo"])
    id_andamento, p_andamento = v.criar_venda(fx.CPF_MARIA, ["Laser Exemplo", "Mesa Exemplo"], _pedido(b1))
    v.mudar_status_proposta(p_andamento, propostas_mod.STATUS_APROVADO)
    v.fechar_proposta(p_andamento)
    id_efetivada, p_efetivada = v.criar_venda(fx.CPF_MARIA, ["Mesa Exemplo"], _pedido(b1))
    v.mudar_status_proposta(p_efetivada, propostas_mod.STATUS_APROVADO)
    v.fechar_proposta(p_efetivada)
    assert v.efetivar_proposta(p_efetivada) == v.VENDA_EFETIVADA
    id_perdida, _ = v.criar_venda(fx.CPF_MARIA, ["Cadeira Exemplo"], _pedido(b1))
    v.mudar_status_venda(id_perdida, v.VENDA_PERDIDA)
    id_nao, _ = v.criar_venda(fx.CPF_MARIA, ["Laser Exemplo"], _pedido(b1))
    v.mudar_status_venda(id_nao, v.VENDA_NAO_EFETIVADA)
    id_joao, _ = v.criar_venda(fx.CPF_JOAO, ["Laser Exemplo"])
    status = {r.id: r.status for r in v.listar_vendas()}
    assert status[id_aguardando] == v.VENDA_AGUARDANDO and status[id_andamento] == v.VENDA_EM_ANDAMENTO, status

    em_aberto = v.vendas_em_aberto_do_cliente(fx.CPF_MARIA)
    assert [r.id for r in em_aberto] == [id_andamento, id_aguardando], (
        "só Aguardando bancos e Em andamento, a criada por último primeiro (mesmo dia)", [r.status for r in em_aberto])
    assert [r.id for r in v.vendas_em_aberto_do_cliente(fx.CPF_JOAO)] == [id_joao], "só as do cliente"
    assert v.vendas_em_aberto_do_cliente(fx.CPF_ANA) == []
    # em dias diferentes, a data manda (mesmo que a mais antiga tenha sido gravada depois)
    vendas = bd.ler_vendas(v._caminho())
    vendas.loc[vendas["ID_VENDA"] == id_andamento, "DATA_CRIACAO"] = pd.Timestamp(date.today()) - pd.Timedelta(days=3)
    bd.escrever_vendas_e_propostas(v._caminho(), vendas=vendas)
    assert [r.id for r in v.vendas_em_aberto_do_cliente(fx.CPF_MARIA)] == [id_aguardando, id_andamento], \
        "a de 3 dias atrás vem depois da de hoje"

    por_id = {r.id: r for r in v.listar_vendas()}
    hoje = date.today().strftime("%d/%m")
    assert v.rotulo_da_venda(por_id[id_aguardando]) == f"Venda de {hoje} · Cadeira Exemplo · Aguardando bancos · nenhum banco"
    tres_dias = (pd.Timestamp(date.today()) - pd.Timedelta(days=3)).strftime("%d/%m")
    assert v.rotulo_da_venda(por_id[id_andamento]) == \
        f"Venda de {tres_dias} · Laser Exemplo + Mesa Exemplo · Em andamento · 1 banco"
    assert v.rotulo_da_venda(dataclasses.replace(por_id[id_aguardando], data_criacao=None)).startswith("Venda sem data · ")
    v.mandar_a_outro_banco(id_andamento, _pedido(b1, 40000))
    assert v.rotulo_da_venda(next(r for r in v.listar_vendas() if r.id == id_andamento)).endswith(" · 2 bancos")
    print("OK: Efetivada, Perdida e Não efetivada ficam de fora; a mais recente primeiro (no mesmo dia, a criada por "
          "último); 'Venda de dd/mm · equipamentos · status · N bancos'.")
    return {"aguardando": id_aguardando, "andamento": id_andamento, "efetivada": id_efetivada, "joao": id_joao}


def testar_card_nova_venda(msgs: Mensagens, soltas: JanelasSoltas, b1: str, ids: dict) -> tela_mod.VendasScreen:
    linha("2) O card 'Nova venda': no topo, um por vez, o digitado não se perde")
    tela = tela_mod.VendasScreen()
    soltas.esperadas = (tela,)
    tela.resize(1100, 760)
    tela.show()
    _processar()
    lista = tela.lista
    total_antes = len(v.listar_vendas())
    tela.botao_nova.click()
    _processar()
    novo = lista.card_da_nova_venda()
    assert isinstance(novo, CardNovaVenda) and lista.cards[0] is novo and lista.rascunho == {"cpf": None}
    f = novo.formulario
    assert isinstance(f, FormularioDaVenda) and not f.tem_alteracoes() and not tela.tem_edicao_pendente()
    assert f.campos.observacoes is not None and f.botao_cancelar.text() == "Cancelar"
    f.campos.cliente.setCurrentText(_rotulo(fx.CPF_JOAO))
    f.campos.equipamentos.linhas[0].setCurrentText("Mesa Exemplo")
    assert f.tem_alteracoes() and tela.tem_edicao_pendente()
    for mudar in (lambda: tela.busca.setText("nenhuma venda tem isto"), tela.busca.clear,
                  lambda: tela.filtro.setCurrentText(tela_mod.FILTRO_EFETIVADAS),
                  lambda: tela.filtro.setCurrentText(tela_mod.FILTRO_EM_ANDAMENTO), tela.carregar):
        mudar()
        _processar()
        card = lista.card_da_nova_venda()
        assert card is not None and lista.cards[0] is card and card.formulario is f, "o mesmo card, no topo"
        assert f.campos.equipamentos.equipamentos() == ["Mesa Exemplo"] and f.isVisible(), "com o que já foi digitado"
    assert tela.busca.text() == "" and tela.filtro.currentText() == tela_mod.FILTRO_EM_ANDAMENTO
    v.editar_venda(ids["joao"], ["Laser Exemplo"], "mudou por fora")
    assert tela.recarregar_se_mudou() is False, "com algo digitado no card novo, mudar por fora não relê"
    msgs.limpar()
    assert tela.nova_venda() and lista.card_da_nova_venda().formulario is f, "de novo: o mesmo card (um por vez)"
    msgs.exigir_vazio("'+ Nova venda' de novo, com o card novo digitado: nem pergunta")
    assert sum(isinstance(c, CardNovaVenda) for c in lista.cards) == 1
    print("OK: um card no topo; busca, filtro e reler não apagam o digitado; '+ Nova venda' de novo mantém o mesmo.")

    # abrir outra venda com algo digitado pergunta; "Não" fica no card novo
    outra = lista.venda_por_id(ids["aguardando"])
    msgs.limpar()
    msgs.resposta_pergunta = NAO
    assert not lista.abrir_venda(outra)
    assert msgs.ultima()[1] == "Alterações não salvas" and lista.card_da_nova_venda().formulario is f
    msgs.resposta_pergunta = SIM
    assert lista.abrir_venda(outra)
    _processar()
    assert lista.rascunho is None and lista.card_da_nova_venda() is None and lista.aberta == outra.id
    assert lista.fechar_venda()
    # Cancelar (o botão e o Esc) tira o card sem gravar nada
    assert tela.nova_venda()
    _processar()
    lista.card_da_nova_venda().formulario.botao_cancelar.click()
    _processar()
    assert lista.card_da_nova_venda() is None and lista.rascunho is None
    assert tela.nova_venda()
    _processar()
    _tecla(lista.card_da_nova_venda().formulario, Qt.Key.Key_Escape)
    _processar()
    assert lista.card_da_nova_venda() is None and len(v.listar_vendas()) == total_antes, "nada gravado"
    print("OK: abrir outra venda pergunta (Não mantém o card); Cancelar e Esc tiram o card sem gravar.")

    linha("3) Criar a venda: validação, e o card dela abre com o primeiro banco")
    assert tela.nova_venda()
    _processar()
    f = lista.card_da_nova_venda().formulario
    msgs.limpar()
    f.botao_gravar.click()
    assert msgs.ultima()[1] == "Cliente não encontrado"
    f.campos.cliente.setCurrentText("ANA (digitado, sem escolher da lista)")
    f.botao_gravar.click()
    assert msgs.ultima()[1] == "Cliente não encontrado", "só um cliente da lista vale"
    f.campos.cliente.setCurrentText(_rotulo(fx.CPF_ANA))
    f.botao_gravar.click()
    assert msgs.ultima()[1] == "Equipamento em branco"
    assert len(v.listar_vendas()) == total_antes and lista.card_da_nova_venda().formulario is f, "recusada: o card fica"
    equipamentos = f.campos.equipamentos
    assert not equipamentos.linhas[0].parentWidget().findChildren(QPushButton), "o primeiro equipamento não tem o ✕"
    equipamentos.tirar(equipamentos.linhas[0])
    assert len(equipamentos.linhas) == 1, "o primeiro nunca sai (a venda tem pelo menos um)"
    equipamentos.mais.click()
    assert len(equipamentos.linhas) == 2 and equipamentos.linhas[1].parentWidget().findChildren(QPushButton)
    equipamentos.linhas[1].parentWidget().findChildren(QPushButton)[0].click()  # o ✕
    assert len(equipamentos.linhas) == 1
    f.campos.equipamentos.linhas[0].setCurrentText("Laser Exemplo")
    msgs.limpar()
    _tecla(f, Qt.Key.Key_Return)  # Enter cria
    _processar()
    msgs.exigir_vazio("criar a venda")
    assert len(v.listar_vendas()) == total_antes + 1 and lista.rascunho is None
    id_ana = lista.aberta
    assert _venda(id_ana)["CPF"] == fx.CPF_ANA and _venda(id_ana)["EQUIPAMENTOS"] == "Laser Exemplo"
    card = lista.card_aberto()
    assert card.venda.id == id_ana and card.editando == NOVA and isinstance(card.formulario, FormularioProposta)
    assert tela.texto_aviso.text() == AVISO_VENDA_CRIADA
    print("OK: sem cliente da lista e sem equipamento recusa (o card fica); Enter cria; o card da venda abre com o "
          "formulário do primeiro banco.")

    linha("4) O mesmo banco mais de uma vez na mesma venda (permitido)")
    for valor in (30000, 25000):
        if card.formulario is None:
            card.adicionar.click()
            _processar()
            card = lista.card_aberto()
        formulario = card.formulario
        formulario._banco.setCurrentText(b1)
        formulario._valor.setValue(valor)
        msgs.limpar()
        formulario._salvar()
        _processar()
        msgs.exigir_sem_erros(f"o {b1} de novo")
        card = lista.card_aberto()
    propostas = v.propostas_da_venda(id_ana)
    assert list(propostas["BANCO"]) == [b1, b1] and sorted(propostas["VALOR (R$)"]) == [25000, 30000]
    print(f"OK: duas propostas ao {b1} na mesma venda, sem trava nem aviso.")
    return tela


def testar_editar_venda(tela: tela_mod.VendasScreen, msgs: Mensagens, ids: dict) -> None:
    linha("5) 'Editar a venda' no próprio card aberto")
    lista = tela.lista
    assert lista.fechar_venda()
    tela.filtro.setCurrentText(tela_mod.FILTRO_TODAS)
    _processar()
    venda = lista.venda_por_id(ids["aguardando"])
    assert lista.abrir_venda(venda)
    _processar()
    card = lista.card_aberto()
    card.editar_venda.click()
    _processar()
    card = lista.card_aberto()
    f = card.formulario
    assert card.editando == EDITAR_VENDA == lista.editando and isinstance(f, FormularioDaVenda)
    assert f.botao_gravar.text() == "Gravar" and f.campos.cliente is None and card.editar_venda.isHidden()
    assert card._layout.indexOf(card.caixa_do_formulario) < card._layout.indexOf(card._divisor), "acima dos bancos"
    assert f.campos.equipamentos.equipamentos() == ["Cadeira Exemplo"] and not f.tem_alteracoes()
    # Cancelar: nada muda
    f.campos.observacoes.setPlainText("não era pra gravar")
    f.botao_cancelar.click()
    _processar()
    assert lista.editando is None and lista.card_aberto().formulario is None
    assert _venda(ids["aguardando"])["OBSERVAÇÕES"] != "não era pra gravar"
    # com algo digitado, abrir outro card pergunta
    lista.card_aberto().editar_venda.click()
    _processar()
    f = lista.card_aberto().formulario
    f.campos.equipamentos.mais.click()
    f.campos.equipamentos.linhas[1].setCurrentText("Mesa Exemplo")
    assert tela.tem_edicao_pendente()
    msgs.limpar()
    msgs.resposta_pergunta = NAO
    assert not lista.abrir_venda(lista.venda_por_id(ids["joao"]))
    assert msgs.ultima()[1] == "Alterações não salvas" and lista.card_aberto().formulario is f
    msgs.resposta_pergunta = SIM
    tela.busca.setText("nenhuma venda tem isto")  # o aberto fica, com o digitado
    _processar()
    assert lista.card_aberto().formulario is f and f.campos.equipamentos.equipamentos() == ["Cadeira Exemplo", "Mesa Exemplo"]
    tela.busca.clear()
    _processar()
    # validacao: sem equipamento nao grava
    f.campos.equipamentos.linhas[0].setCurrentIndex(-1)
    f.campos.equipamentos.tirar(f.campos.equipamentos.linhas[1])
    msgs.limpar()
    assert not f.gravar() and msgs.ultima()[1] == "Equipamento em branco"
    f.campos.equipamentos.setCurrentText("Cadeira Exemplo + Mesa Exemplo")
    f.campos.observacoes.setPlainText("cliente pediu urgência")
    msgs.limpar()
    assert f.gravar()
    _processar()
    msgs.exigir_vazio("editar a venda")
    venda = _venda(ids["aguardando"])
    assert venda["EQUIPAMENTOS"] == "Cadeira Exemplo + Mesa Exemplo" and venda["OBSERVAÇÕES"] == "cliente pediu urgência"
    card = lista.card_aberto()
    assert card.venda.id == ids["aguardando"] and lista.editando is None and card.formulario is None
    assert "venda alterada" in tela.texto_aviso.text()
    print("OK: os equipamentos e as observações viram campos no card (acima dos bancos); Cancelar não grava; com algo "
          "digitado pergunta antes de trocar de card; sem equipamento recusa; Gravar grava.")
    tela.lista.descartar()
    tela.close()


def testar_nova_proposta(msgs: Mensagens, soltas: JanelasSoltas, b1: str, b2: str, ids: dict) -> None:
    linha("6) Todas as Propostas: '+ Nova proposta' escolhendo a venda")
    tela = propostas_tela_mod.PropostasScreen()
    soltas.esperadas = (tela,)
    tela.resize(1100, 760)
    tela.show()
    _processar()
    assert tela._botao_nova.text() == "+ Nova proposta" and not tela._botao_nova.isHidden()
    tela._botao_nova.click()
    _processar()
    card = tela.lista.cards[0]
    assert isinstance(card, CardNovaProposta) and tela.lista.rascunho["escolher_venda"]
    f = card.formulario
    assert _opcoes(f._venda_combo) == [VENDA_NOVA_COM_A_PROPOSTA], "sem cliente, só a venda nova"
    assert isinstance(f._equipamento.atual, LinhasDeEquipamento)
    assert not f.tem_alteracoes()

    # MARIA: as duas em aberto (a mais recente marcada) e a venda nova; nunca a Efetivada
    f._cliente_combo.setCurrentText(_rotulo(fx.CPF_MARIA))
    por_id = {r.id: r for r in v.listar_vendas()}
    esperadas = [v.rotulo_da_venda(por_id[i]) for i in (ids["aguardando"], ids["andamento"])]
    assert _opcoes(f._venda_combo) == [*esperadas, VENDA_NOVA_COM_A_PROPOSTA], _opcoes(f._venda_combo)
    assert f._venda_combo.currentIndex() == 0 and f._id_venda == ids["aguardando"]
    assert isinstance(f._equipamento.atual, _CaixasDeEquipamento)
    assert [c.text() for c in f._equipamento.atual.caixas] == ["Cadeira Exemplo", "Mesa Exemplo"], "as caixinhas dela"
    assert f.tem_alteracoes() and tela.lista.tem_edicao_pendente()
    f._venda_combo.setCurrentIndex(1)
    assert f._id_venda == ids["andamento"] and [c.text() for c in f._equipamento.atual.caixas] == ["Laser Exemplo", "Mesa Exemplo"]
    f._equipamento.atual.caixas[1].setChecked(False)  # este pedido so cobre o laser
    f._banco.setCurrentText(b2)
    f._valor.setValue(61000)
    antes = len(v.propostas_da_venda(ids["andamento"]))
    total_vendas = len(v.listar_vendas())
    msgs.limpar()
    f._salvar()
    _processar()
    msgs.exigir_sem_erros("nova proposta numa venda em aberto")
    da_venda = v.propostas_da_venda(ids["andamento"])
    assert len(da_venda) == antes + 1 and len(v.listar_vendas()) == total_vendas, "entrou na venda escolhida"
    nova = da_venda.iloc[-1]
    assert nova["BANCO"] == b2 and nova["VALOR (R$)"] == 61000 and nova["EQUIPAMENTO"] == "Laser Exemplo"
    assert tela.lista.rascunho is None
    print("OK: a MARIA mostra as 2 vendas em aberto (a mais recente marcada) e a venda nova; a proposta entra na "
          "venda escolhida, só com o equipamento marcado.")

    linha("7) '+ Nova proposta' com venda nova")
    tela._botao_nova.click()
    _processar()
    f = tela.lista.cards[0].formulario
    f._cliente_combo.setCurrentText(_rotulo(fx.CPF_ANA))
    em_aberto_ana = [r.id for r in v.vendas_em_aberto_do_cliente(fx.CPF_ANA)]
    assert len(em_aberto_ana) == 1 and f._venda_combo.count() == 2, "a ANA tem a venda criada no card (passo 3)"
    f._venda_combo.setCurrentIndex(f._venda_combo.findText(VENDA_NOVA_COM_A_PROPOSTA))
    assert f._id_venda == "" and isinstance(f._equipamento.atual, LinhasDeEquipamento)
    f._banco.setCurrentText(b1)
    f._valor.setValue(15000)
    msgs.limpar()
    f._salvar()
    assert msgs.ultima()[1] == "Equipamento em branco" and len(v.listar_vendas()) == total_vendas
    linhas = f._equipamento.atual
    linhas.linhas[0].setCurrentText("Cadeira Exemplo")
    linhas.mais.click()
    linhas.linhas[1].setCurrentText("Laser Exemplo")
    msgs.limpar()
    f._salvar()
    _processar()
    msgs.exigir_sem_erros("nova proposta com venda nova")
    assert len(v.listar_vendas()) == total_vendas + 1
    nova_venda = next(r for r in v.vendas_em_aberto_do_cliente(fx.CPF_ANA) if r.id not in em_aberto_ana)
    assert nova_venda.equipamentos == "Cadeira Exemplo + Laser Exemplo" and [p.banco for p in nova_venda.propostas] == [b1]
    assert nova_venda.propostas[0].valor == 15000
    print("OK: com '+ Venda nova com esta proposta', as linhas de equipamento; sem equipamento recusa; gravar cria a "
          "venda com a proposta.")

    linha("8) Cliente sem venda em aberto: já vem a venda nova; trocar o cliente troca as vendas")
    tela._botao_nova.click()
    _processar()
    f = tela.lista.cards[0].formulario
    f._cliente_combo.setCurrentText(_rotulo(fx.CPF_JOAO))
    assert f._venda_combo.count() == 2 and f._id_venda == ids["joao"]
    v_joao = v.vendas_em_aberto_do_cliente(fx.CPF_JOAO)[0]
    v.mudar_status_venda(v_joao.id, v.VENDA_PERDIDA)
    f._cliente_combo.setCurrentText(_rotulo(fx.CPF_MARIA))
    f._cliente_combo.setCurrentText(_rotulo(fx.CPF_JOAO))
    assert _opcoes(f._venda_combo) == [VENDA_NOVA_COM_A_PROPOSTA] and f._id_venda == ""
    assert isinstance(f._equipamento.atual, LinhasDeEquipamento), "sem venda em aberto: a venda nova, marcada"
    # o card fica com a busca e o filtro (o digitado nao some), e "+ Nova proposta" de novo mantem o mesmo
    tela._busca.setText("nenhuma proposta tem isto")
    _processar()
    assert tela.lista.cards[0].formulario is f
    tela._busca.clear()
    _processar()
    assert f.tem_alteracoes()
    msgs.limpar()
    tela._botao_nova.click()
    _processar()
    msgs.exigir_vazio("'+ Nova proposta' de novo, com o card digitado: nem pergunta")
    assert tela.lista.cards[0].formulario is f and sum(isinstance(c, CardNovaProposta) for c in tela.lista.cards) == 1
    f._cancelar_edicao()
    _processar()
    assert tela.lista.rascunho is None
    print("OK: sem venda em aberto, só a venda nova; o card sobrevive à busca; um por vez; Cancel tira o card.")
    tela.close()


def testar_vendedor(caminho: Path) -> None:
    linha("9) O VENDEDOR não tem nada disso")
    vendedor = bd.ler_clientes(caminho)["VENDEDOR"].dropna().iloc[0]
    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_VENDEDOR, nome_usuario=vendedor))
    try:
        rolagem = QScrollArea()
        conteudo = QWidget()
        QVBoxLayout(conteudo)
        rolagem.setWidget(conteudo)
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QFrame.Shape.NoFrame)
        vendas = ListaDeVendas(rolagem, conteudo)
        vendas.definir_vendas(v.listar_vendas())
        assert not vendas.nova_venda() and not vendas.nova_venda(fx.CPF_MARIA) and vendas.rascunho is None
        assert not vendas.editar_venda(v.listar_vendas()[0]) and vendas.editando is None
        propostas = ListaDePropostas(rolagem, lambda _i: None, conteudo)
        assert not propostas.nova_proposta() and propostas.rascunho is None
        assert not any(isinstance(c, (CardNovaVenda, CardNovaProposta)) for c in vendas.cards + propostas.cards)
    finally:
        sessao_mod.iniciar(ADMIN)
    print("OK: para o VENDEDOR, nem o card 'Nova venda', nem o 'Editar a venda', nem a 'Nova proposta'.")


def main() -> None:
    def _sem_rede(*_a, **_k):
        raise AssertionError("o teste tentou acessar o Google de verdade")

    rede_original = (nuvem._obter_cliente, sheets_sync._obter_cliente)
    nuvem._obter_cliente = sheets_sync._obter_cliente = _sem_rede
    pasta = Path(tempfile.mkdtemp(prefix="_smoke_venda_num_card_"))
    registro_antes = fx.instantaneo_do_registro()
    fx.isolar_preferencias(pasta)
    caminho = fx.criar(pasta)
    fx.apontar_modulos_para(caminho)
    sessao_mod.iniciar(ADMIN)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(build_stylesheet(TEMA_ESCURO))
    soltas = JanelasSoltas()
    app.installEventFilter(soltas)
    try:
        with Mensagens() as msgs:
            b1, b2 = bancos_mod.nomes_ativos()[:2]
            for nome in ("Cadeira Exemplo", "Laser Exemplo", "Mesa Exemplo"):
                equipamentos_mod.cadastrar({"EQUIPAMENTO": nome})
            ids = testar_core(b1)
            tela = testar_card_nova_venda(msgs, soltas, b1, ids)
            testar_editar_venda(tela, msgs, ids)
            testar_nova_proposta(msgs, soltas, b1, b2, ids)
            testar_vendedor(caminho)
            linha("10) Nenhuma janela abriu")
            _processar()
            assert soltas.vistas == [], soltas.vistas
            print("OK: tudo nos cards; nenhuma janela (nem pedaço de card solto).")
        linha("TUDO OK")
    finally:
        app.removeEventFilter(soltas)
        nuvem._obter_cliente, sheets_sync._obter_cliente = rede_original
        fx.restaurar_modulos()
        sessao_mod.encerrar()
        assert fx.instantaneo_do_registro() == registro_antes, "o teste mexeu nas preferências reais"


if __name__ == "__main__":
    main()
