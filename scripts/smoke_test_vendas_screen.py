"""Testa a tela Vendas (desktop/screens/vendas_screen.py) e o que a etapa 3 mudou em volta dela: cards de venda com
as linhas de banco, a troca rapida de status pelos menus das etiquetas (com Desfazer e as confirmacoes), "Nova venda"
e "Mandar a outro banco" (inclusive o pedido de parte da venda), o aviso das propostas sem venda, filtros e busca, o
formulario de proposta criando a venda, e a trava de excluir a proposta do banco escolhido.

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
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

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
from desktop.dialogs.pedido_venda_dialog import PedidoVendaDialog
from desktop.screens import vendas_screen as tela_mod
from desktop.theme import TEMA_ESCURO, build_stylesheet
from desktop.widgets.formulario_proposta import FormularioProposta

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
    return [c.venda.cliente.split()[0] for c in tela.cards]


def _card(tela, cliente: str):
    cards = [c for c in tela.cards if c.venda.cliente.split()[0] == cliente]
    assert len(cards) == 1, (cliente, [c.venda.cliente for c in tela.cards])
    return cards[0]


def _venda(id_venda: str) -> pd.Series:
    vendas = bd.ler_vendas(v._caminho())
    return vendas[vendas["ID_VENDA"] == id_venda].iloc[0]


def _resumo(id_venda: str) -> v.ResumoDaVenda:
    return next(r for r in v.listar_vendas() if r.id == id_venda)


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

            linha("1) Sem vendas: aviso das propostas antigas e a lista vazia")
            tela = tela_mod.VendasScreen()
            soltas.esperadas = (tela,)
            app.installEventFilter(soltas)
            tela.resize(1100, 760)
            tela.show()
            _processar()
            sem_venda = len(bd.ler_propostas(caminho))
            assert not tela.aviso_sem_venda.isHidden() and f"{sem_venda} proposta(s)" in tela.texto_sem_venda.text()
            assert tela.cards == [] and "Nenhuma venda ainda" in tela.vazio.text() and not tela.vazio.isHidden()
            print(f"OK: {sem_venda} propostas antigas aparecem no aviso (com o 'Juntar em vendas…'); nenhuma venda ainda.")

            linha("2) Nova venda: recusas claras e a venda com dois equipamentos")
            d = PedidoVendaDialog(tela)
            d._gravar()
            assert "Cliente não encontrado" in msgs.ultima()[1]
            rotulo_maria = next(r for r in d._clientes_por_rotulo if d._clientes_por_rotulo[r] == fx.CPF_MARIA)
            d._cliente.setCurrentText(rotulo_maria)
            d._gravar()
            assert "Equipamento em branco" in msgs.ultima()[1]
            d._linhas_equipamento[0].setCurrentText("Cadeira Exemplo")
            d._adicionar_equipamento()
            d._linhas_equipamento[1].setCurrentText("Laser Exemplo")
            d._gravar()
            assert "Banco em branco" in msgs.ultima()[1]
            d._banco.setCurrentText(b1)
            d._valor.setValue(80000)
            d._meses.setValue(48)
            msgs.limpar()
            d._gravar()
            msgs.exigir_vazio("nova venda válida")
            assert d.result() == QDialog.DialogCode.Accepted and d.id_venda and d.id_proposta
            id_maria = d.id_venda
            tela.carregar()
            card = _card(tela, "MARIA")
            assert card.venda.equipamentos == "Cadeira Exemplo + Laser Exemplo" and card.pilula.text() == v.VENDA_AGUARDANDO
            assert [(l["proposta"].banco, l["proposta"].status) for l in card.linhas_de_banco] == [(b1, propostas_mod.STATUS_EM_ANALISE)]
            print("OK: sem cliente, sem equipamento e sem banco: recusa com o motivo; válida: 1 card, 2 equipamentos, 1 banco.")

            linha("3) Mandar a outro banco: valor de partida do último pedido; pedido de parte da venda")
            d = PedidoVendaDialog(tela, venda=card.venda)
            assert d._valor.value() == 80000 and d._meses.value() == 48 and len(d._cobre) == 2
            d._banco.setCurrentText(b2)
            d._cobre[1].setChecked(False)
            d._gravar()
            assert d.result() == QDialog.DialogCode.Accepted
            tela.carregar()
            card = _card(tela, "MARIA")
            assert [l["proposta"].banco for l in card.linhas_de_banco] == [b1, b2]
            assert card.linhas_de_banco[1]["proposta"].equipamento == "Cadeira Exemplo"
            assert not card.botao_outro_banco.isHidden()
            print("OK: o pedido ao 2º banco herda valor e meses e cobre só a Cadeira (pedido separado na mesma venda).")

            linha("4) Banco sem resposta: bolinhas Aprovado/Negado (sem Pré-aprovado); a etiqueta abre os 4; ↩ volta")
            card = _card(tela, "MARIA")
            assert card.bolinha is None, "aguardando bancos: o próximo passo é escolher o banco, no anel"
            assert card.voltar is None and card.convite is None, "sem status anterior; nenhum banco aprovou ainda"
            assert all(l["anel"] is None for l in card.linhas_de_banco), "sem aprovação, nenhum anel"
            l1 = card.linhas_de_banco[0]
            p1 = l1["proposta"]
            assert [b.destino for b in l1["bolinhas"]] == [propostas_mod.STATUS_APROVADO, propostas_mod.STATUS_NEGADO]
            assert l1["voltar"] is None
            menu_p = _acoes(tela.montar_menu_da_proposta(card.venda, p1))
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

            linha("5) Anel: escolher e trocar o banco; o ✓ desfaz; o escolhido não vira Negado")
            l1["bolinhas"][0].click()
            card = _card(tela, "MARIA")
            card.linhas_de_banco[1]["bolinhas"][0].click()  # os dois bancos aprovam
            card = _card(tela, "MARIA")
            assert card.convite is not None and "2 bancos aprovaram" in card.convite.text()
            aneis = [l["anel"] for l in card.linhas_de_banco]
            assert all(a is not None and not a.escolhido for a in aneis) and aneis[0].dica == "Escolher este banco"
            aneis[0].click()
            venda = _venda(id_maria)
            assert venda["STATUS"] == v.VENDA_BANCO_ESCOLHIDO and venda["BANCO_ESCOLHIDO"] == p1.id
            card = _card(tela, "MARIA")
            l1, l2 = card.linhas_de_banco
            assert l1["anel"].escolhido and not l2["anel"].escolhido and l2["anel"].dica == "Trocar para este banco"
            menu_p = _acoes(tela.montar_menu_da_proposta(card.venda, l1["proposta"]))
            assert not menu_p[propostas_mod.STATUS_NEGADO].isEnabled() and menu_p[propostas_mod.STATUS_APROVADO].isEnabled()
            l1["voltar"].click()  # o ↩ do banco escolhido (para Em Análise) é recusado
            assert "banco escolhido" in msgs.ultima()[2] and _venda(id_maria)["BANCO_ESCOLHIDO"] == p1.id
            l2["anel"].click()
            p2 = l2["proposta"]
            assert _venda(id_maria)["BANCO_ESCOLHIDO"] == p2.id and "trocado para" in tela.texto_aviso.text()
            card = _card(tela, "MARIA")
            card.linhas_de_banco[1]["anel"].click()  # o ✓ desfaz a escolha
            venda = _venda(id_maria)
            assert venda["STATUS"] == v.VENDA_AGUARDANDO and venda["BANCO_ESCOLHIDO"] == ""
            card = _card(tela, "MARIA")
            assert card.voltar is None, "voltar para 'Banco escolhido' sem banco não existe: escolhe de novo no anel"
            card.linhas_de_banco[0]["anel"].click()
            print("OK: anel em cada aprovado escolhe (venda → Banco escolhido) e troca; ✓ desfaz; o escolhido fica travado.")

            linha("6) Bolinha da venda: Nota fiscal; Efetivada só confirmando; ↩ e reabrir com confirmação")
            card = _card(tela, "MARIA")
            assert card.bolinha.destino == v.VENDA_NOTA_FISCAL and card.voltar.anterior == v.VENDA_AGUARDANDO
            assert v.VENDA_BANCO_ESCOLHIDO not in _acoes(tela.montar_menu_da_venda(card.venda)), "escolhe-se no anel"
            card.bolinha.click()
            card = _card(tela, "MARIA")
            assert _venda(id_maria)["STATUS"] == v.VENDA_NOTA_FISCAL
            assert all(l["anel"] is None or l["anel"].escolhido for l in card.linhas_de_banco), "depois da NF o banco trava"
            card.voltar.click()
            assert _venda(id_maria)["STATUS"] == v.VENDA_BANCO_ESCOLHIDO and _venda(id_maria)["BANCO_ESCOLHIDO"] == p1.id
            _card(tela, "MARIA").bolinha.click()
            _card(tela, "MARIA").bolinha.click()  # Nota fiscal → Garantia
            card = _card(tela, "MARIA")
            assert _venda(id_maria)["STATUS"] == v.VENDA_GARANTIA and card.bolinha.destino == "Efetivada…"
            msgs.resposta_pergunta = QMessageBox.StandardButton.No
            card.bolinha.click()
            assert _venda(id_maria)["STATUS"] == v.VENDA_GARANTIA, "respondeu Não: nada muda"
            msgs.resposta_pergunta = QMessageBox.StandardButton.Yes
            _card(tela, "MARIA").bolinha.click()
            assert _venda(id_maria)["STATUS"] == v.VENDA_EFETIVADA and b1 in msgs.ultima()[2]
            assert all(c.venda.id != id_maria for c in tela.cards), "efetivada sai de 'Em andamento'"
            tela.filtro.setCurrentText(tela_mod.FILTRO_EFETIVADAS)
            card = _card(tela, "MARIA")
            assert card.botao_outro_banco.isHidden() and card.bolinha is None, "venda finalizada: nada a avançar"
            msgs.resposta_pergunta = QMessageBox.StandardButton.No
            card.voltar.click()
            assert "Reabrir" in msgs.ultima()[1] and _venda(id_maria)["STATUS"] == v.VENDA_EFETIVADA
            msgs.resposta_pergunta = QMessageBox.StandardButton.Yes
            tela.filtro.setCurrentText(tela_mod.FILTRO_EM_ANDAMENTO)
            print("OK: bolinha leva à próxima etapa; Efetivada confirma; ↩ volta (reabrir uma fechada pergunta antes).")

            linha("7) Todos os bancos negaram: o app pergunta, nunca decide sozinho")
            id_joao, id_pj = v.criar_venda(fx.CPF_JOAO, ["Mesa Exemplo"], _pedido(b1))
            id_ana, id_pa = v.criar_venda(fx.CPF_ANA, ["Mesa Exemplo"], _pedido(b2))
            tela.carregar()
            msgs.resposta_pergunta = QMessageBox.StandardButton.No
            card = _card(tela, "JOÃO")
            _acoes(tela.montar_menu_da_proposta(card.venda, card.linhas_de_banco[0]["proposta"]))[propostas_mod.STATUS_NEGADO].trigger()
            assert "Todos os bancos" in msgs.ultima()[1] and _venda(id_joao)["STATUS"] == v.VENDA_AGUARDANDO
            msgs.resposta_pergunta = QMessageBox.StandardButton.Yes
            card = _card(tela, "ANA")
            _acoes(tela.montar_menu_da_proposta(card.venda, card.linhas_de_banco[0]["proposta"]))[propostas_mod.STATUS_NEGADO].trigger()
            venda = _venda(id_ana)
            assert venda["STATUS"] == v.VENDA_PERDIDA and venda["MOTIVO"] == "Todos os bancos negaram"
            print("OK: a última negativa pergunta 'Perdida?': Não deixa aguardando; Sim marca Perdida com o motivo.")

            linha("8) Desfecho com motivo opcional (Não efetivada)")
            card = _card(tela, "JOÃO")
            exec_original = tela_mod.DesfechoDialog.exec

            def _escolhe_desistiu(dialogo):
                dialogo.motivo.setCurrentIndex(dialogo.motivo.findData("Desistiu"))
                return QDialog.DialogCode.Accepted

            tela_mod.DesfechoDialog.exec = _escolhe_desistiu
            try:
                _acoes(tela.montar_menu_da_venda(card.venda))[f"{v.VENDA_NAO_EFETIVADA}…"].trigger()
            finally:
                tela_mod.DesfechoDialog.exec = exec_original
            venda = _venda(id_joao)
            assert venda["STATUS"] == v.VENDA_NAO_EFETIVADA and venda["MOTIVO"] == "Desistiu"
            tela.filtro.setCurrentText(tela_mod.FILTRO_PERDIDAS)
            assert set(_nomes(tela)) == {"JOÃO", "ANA"}
            assert any("Motivo: Desistiu" == w.text() for w in _card(tela, "JOÃO").findChildren(type(tela.contador)))
            print("OK: Não efetivada pede confirmação e o motivo (opcional) aparece no card; 'Perdidas e não efetivadas' filtra.")

            linha("9) Busca e contagem")
            tela.filtro.setCurrentText(tela_mod.FILTRO_TODAS)
            assert len(tela.cards) == 3 and tela.contador.text().startswith("3 venda(s)")
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
            v.listar_vendas = lambda hoje=None: listar_original(date.today() + timedelta(days=v.DIAS_PARA_ALERTA))
            try:
                id_parada, _ = v.criar_venda(fx.CPF_ANA, ["Cadeira Exemplo"], _pedido(b1))
                tela.filtro.setCurrentText(tela_mod.FILTRO_PARADAS)
                tela.carregar()
                parados = [c for c in tela.cards if c.venda.id == id_parada]
                assert len(parados) == 1 and parados[0].andamento.property("role") == "aviso"
                assert "parada há 7 dias" in parados[0].andamento.text()
            finally:
                v.listar_vendas = listar_original
            tela.filtro.setCurrentText(tela_mod.FILTRO_EM_ANDAMENTO)
            tela.carregar()
            assert all(c.andamento.property("role") == "secundario" for c in tela.cards), "hoje nada está parado"
            print("OK: 7 dias sem mudar de etapa: o card avisa ('parada há 7 dias') e entra no filtro 'Paradas'.")

            linha("11) O formulário de proposta cria a venda; 'Mandar a outro banco' entra na mesma venda")
            antes = len(bd.ler_vendas(caminho))
            f = FormularioProposta(fx.CPF_JOAO, "JOÃO")
            assert [f._status.itemText(i) for i in range(f._status.count())] == v.STATUS_DA_PROPOSTA
            f._valor.setValue(40000)
            f._equipamento.setCurrentText("Laser Exemplo + Mesa Exemplo")
            f._salvar()
            assert "Banco em branco" in msgs.ultima()[1], "proposta nova exige o banco"
            f._banco.setCurrentText(b1)
            msgs.limpar()
            f._salvar()
            msgs.exigir_vazio("proposta nova pelo formulário")
            vendas = bd.ler_vendas(caminho)
            assert len(vendas) == antes + 1 and vendas.iloc[-1]["EQUIPAMENTOS"] == "Laser Exemplo + Mesa Exemplo"
            nova = bd.ler_propostas(caminho).loc[f.indice_gravado]
            assert nova["ID_VENDA"] == vendas.iloc[-1]["ID_VENDA"] and nova["BANCO"] == b1
            base = propostas_mod.dados_para_duplicar(nova.to_dict())
            assert base["ID_VENDA"] == nova["ID_VENDA"] and base["BANCO"] == ""
            dup = FormularioProposta(fx.CPF_JOAO, "JOÃO", base=base)
            dup._banco.setCurrentText(b2)
            dup._salvar()
            assert len(bd.ler_vendas(caminho)) == antes + 1, "não cria outra venda"
            assert len(v.propostas_da_venda(nova["ID_VENDA"])) == 2
            existente = FormularioProposta(fx.CPF_JOAO, "JOÃO", proposta=nova.to_dict(), indice=f.indice_gravado)
            assert existente._botao_duplicar.text() == "Mandar a outro banco"
            print("OK: 4 status na proposta nova; o equipamento 'A + B' vira uma venda com os dois; a cópia entra na mesma venda.")

            linha("12) Não exclui a proposta do banco escolhido de uma venda")
            indice_escolhida = v.indice_da_proposta(p1.id)
            try:
                propostas_mod.remover_proposta(indice_escolhida)
                raise AssertionError("deveria recusar")
            except propostas_mod.ErroProposta as exc:
                assert "banco escolhido" in str(exc)
            outra = v.indice_da_proposta(v.propostas_da_venda(id_maria).iloc[1]["ID_PROPOSTA"])
            propostas_mod.remover_proposta(outra)
            assert len(v.propostas_da_venda(id_maria)) == 1
            print("OK: excluir a proposta escolhida é recusado com o motivo; as outras da venda podem ser excluídas.")

            linha("13) A setinha ↩ nunca leva a um status impossível")
            id_rx, px = v.criar_venda(fx.CPF_JOAO, ["Cadeira Exemplo"], _pedido(b1))
            v.mudar_status_proposta(px, propostas_mod.STATUS_APROVADO)
            v.mudar_status_venda(id_rx, v.VENDA_BANCO_ESCOLHIDO, proposta_escolhida=px)
            v.mudar_status_venda(id_rx, v.VENDA_NOTA_FISCAL)
            tela.filtro.setCurrentText(tela_mod.FILTRO_TODAS)
            tela.carregar()
            card = next(c for c in tela.cards if c.venda.id == id_rx)
            _acoes(tela.montar_menu_da_venda(card.venda))[v.VENDA_AGUARDANDO].trigger()  # pela lista: limpa o banco
            card = next(c for c in tela.cards if c.venda.id == id_rx)
            assert card.voltar.anterior == v.VENDA_NOTA_FISCAL
            card.voltar.click()
            card = next(c for c in tela.cards if c.venda.id == id_rx)
            assert _venda(id_rx)["STATUS"] == v.VENDA_NOTA_FISCAL and _venda(id_rx)["BANCO_ESCOLHIDO"] == ""
            assert card.voltar is None, "sem banco, 'Banco escolhido' não é para onde voltar (escolhe-se no anel)"
            # proposta com status de antes das vendas: depois de trocar, o ↩ não oferece voltar a ele
            id_ry, py_ = v.criar_venda(fx.CPF_ANA, ["Laser Exemplo"], _pedido(b2))
            propostas_mod.atualizar_proposta(v.indice_da_proposta(py_), {"STATUS": "Nota Fiscal Anexada"})
            v.mudar_status_proposta(py_, propostas_mod.STATUS_APROVADO)
            tela.carregar()
            card = next(c for c in tela.cards if c.venda.id == id_ry)
            assert card.linhas_de_banco[0]["proposta"].status == propostas_mod.STATUS_APROVADO
            assert card.linhas_de_banco[0]["voltar"] is None, "não volta a um status de antes das vendas"
            tela.filtro.setCurrentText(tela_mod.FILTRO_EM_ANDAMENTO)
            print("OK: sem o banco escolhido o ↩ não volta para 'Banco escolhido'; nem para um status de antes das vendas.")

            linha("14) Nenhuma janela solta piscou")
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
