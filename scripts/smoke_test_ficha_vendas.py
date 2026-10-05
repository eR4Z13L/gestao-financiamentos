"""Testa a Ficha de Cliente com as vendas (passo 2): "Vendas do cliente" com os mesmos cards da tela Vendas, "+ Nova
venda" ja com o cliente, o resumo contando vendas, as propostas de antes das vendas a parte, um formulario aberto por
vez na ficha, gravar numa venda sem mexer nos dados do cliente em edicao, e o VENDEDOR vendo o historico de sempre.

Planilha 100% ficticia em pasta temporaria, preferencias isoladas e o Google desligado (qualquer acesso derruba).

Rodar com: venv/Scripts/python.exe scripts/smoke_test_ficha_vendas.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False
import fixture_ficticia as fx
from ambiente_de_teste import Mensagens
from core import bancos as bancos_mod
from core import clientes as clientes_mod
from core import data_store as bd
from core import data_store_sheets as nuvem
from core import equipamentos as equipamentos_mod
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import sheets_sync
from core import vendas as v
from core.formatting import formatar_reais
from core.validators import apenas_digitos
from desktop.dialogs.venda_dialog import VendaDialog
from desktop.screens.ficha_cliente_screen import FichaClienteScreen, _resumo_com_vendas
from desktop.theme import TEMA_ESCURO, build_stylesheet
from desktop.widgets import card_da_venda as card_mod
from desktop.widgets.card_da_venda import NOVA
from desktop.widgets.lista_de_vendas import FaixaDeAviso

ADMIN = sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador")
SIM, NAO = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No


class JanelasSoltas(QObject):
    """Anota toda janela que aparece fora as esperadas (um pedaco de card mostrado antes de ter dono pisca solto)."""

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


def _pedido(banco: str, valor: float) -> dict:
    return {"BANCO": banco, "VALOR (R$)": valor, "MESES": 36}


def _card(tela: FichaClienteScreen, id_venda: str):
    return next(c for c in tela.lista_vendas.cards if c.venda.id == id_venda)


def _status(id_proposta: str) -> str:
    propostas = bd.ler_propostas(v._caminho())
    return propostas.loc[propostas["ID_PROPOSTA"] == id_proposta, "STATUS"].iloc[0]


def main() -> None:
    def _sem_rede(*_a, **_k):
        raise AssertionError("o teste tentou acessar o Google de verdade")

    rede_original = (nuvem._obter_cliente, sheets_sync._obter_cliente)
    nuvem._obter_cliente = sheets_sync._obter_cliente = _sem_rede
    pasta = Path(tempfile.mkdtemp(prefix="_smoke_ficha_vendas_"))
    registro_antes = fx.instantaneo_do_registro()
    fx.isolar_preferencias(pasta)
    caminho = fx.criar(pasta)
    fx.apontar_modulos_para(caminho)
    sessao_mod.iniciar(ADMIN)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(build_stylesheet(TEMA_ESCURO))
    soltas = JanelasSoltas()
    exec_original = VendaDialog.exec
    fontes = (clientes_mod._ler_da_fonte_ativa, propostas_mod._ler_da_fonte_ativa)
    try:
        with Mensagens() as msgs:
            b1, b2 = bancos_mod.nomes_ativos()[:2]
            for nome in ("Cadeira Exemplo", "Laser Exemplo", "Mesa Exemplo"):
                equipamentos_mod.cadastrar({"EQUIPAMENTO": nome})
            id_a, pa = v.criar_venda(fx.CPF_MARIA, ["Cadeira Exemplo"], _pedido(b1, 40000))
            v.mandar_a_outro_banco(id_a, _pedido(b2, 42000))
            id_b, pb = v.criar_venda(fx.CPF_MARIA, ["Laser Exemplo"], _pedido(b1, 30000))
            v.mudar_status_proposta(pb, propostas_mod.STATUS_APROVADO)
            v.fechar_proposta(pb)
            v.efetivar_proposta(pb)
            id_j, _ = v.criar_venda(fx.CPF_JOAO, ["Mesa Exemplo"], _pedido(b2, 10000))  # de outro cliente

            linha("1) A ficha mostra as vendas do cliente e, à parte, só as propostas de antes das vendas")
            tela = FichaClienteScreen()
            soltas.esperadas = (tela,)
            app.installEventFilter(soltas)
            tela.resize(1250, 800)
            tela.show()
            _processar()
            tela._selecionar_por_cpf(fx.CPF_MARIA)
            _processar()
            assert sorted(c.venda.id for c in tela.lista_vendas.cards) == sorted([id_a, id_b]), "só as vendas da MARIA"
            historico = propostas_mod.historico_por_cpf(fx.CPF_MARIA)
            nas_vendas = {p.indice for c in tela.lista_vendas.cards for p in c.venda.propostas}
            modelo = tela._modelo_historico
            antigas = [modelo.indice_real(i) for i in range(modelo.total())]
            assert antigas and not nas_vendas & set(antigas), "proposta de venda não aparece entre as antigas"
            assert sorted(antigas) == sorted(set(historico.index) - nas_vendas), "e toda antiga aparece"
            for parte in (tela._titulo_vendas, tela.lista_vendas, tela._titulo_historico, tela._dica_antigas,
                          tela._contentor_historico, tela._botao_excluir_proposta, tela._botao_nova_venda):
                assert not parte.isHidden(), parte
            assert tela._historico_vazio.isHidden() and tela._titulo_historico.text() == "Propostas de antes das vendas"
            esperado = (f"2 vendas (1 aguardando bancos, 1 efetivada) · {formatar_reais(30000)} efetivado · "
                        f"{len(antigas)} propostas de antes das vendas · última atividade hoje")
            assert tela._resumo_label.text() == esperado, tela._resumo_label.text()
            print(f"OK: 2 vendas da MARIA (a do JOÃO fica de fora), {len(antigas)} propostas antigas à parte; "
                  f"resumo: {tela._resumo_label.text()!r}")

            linha("2) O resumo contando vendas")
            vendas_maria = v.vendas_do_cliente(fx.CPF_MARIA)
            so_a = [x for x in vendas_maria if x.id == id_a]
            vazio = historico.iloc[0:0]
            assert _resumo_com_vendas([], vazio, 0) == "Nenhuma venda registrada ainda."
            assert _resumo_com_vendas(so_a, vazio, 0) == "1 venda aguardando bancos · última atividade hoje"
            assert _resumo_com_vendas([], vazio, 1).startswith("nenhuma venda ainda · 1 proposta de antes das vendas · ")
            assert "efetivado" not in _resumo_com_vendas(so_a, vazio, 0), "sem nada efetivado, sem o valor"
            faixa = FaixaDeAviso(tela)
            faixa.avisar("")
            assert faixa.isHidden(), "gravar sem aviso (ex.: 'Juntar em vendas') não mostra uma faixa vazia"
            faixa.avisar("Gravado.")
            faixa.avisar("")
            assert not faixa.isHidden() and faixa.texto.text() == "Gravado.", "nem apaga o aviso que está à vista"
            faixa.deleteLater()
            print("OK: nenhuma venda / 1 venda (sem o '1 1') / só antigas (singular) / valor efetivado só quando há; "
                  "aviso vazio não aparece.")

            linha("3) O card aberto na ficha: na largura toda e sem 'Abrir a ficha' (já se está nela)")
            assert tela.lista_vendas.abrir_venda(_card(tela, id_a).venda)
            _processar()
            aberto = tela.lista_vendas.card_aberto()
            assert aberto.venda.id == id_a and aberto.abrir_ficha is not None and aberto.abrir_ficha.isHidden()
            largura_toda = tela.lista_vendas.width()
            assert all(c.x() == 0 and c.width() == largura_toda for c in tela.lista_vendas.cards), \
                "uma coluna só: todo card (aberto ou fechado) na largura toda"
            fechado = next(c for c in tela.lista_vendas.cards if not c.aberto)
            borda = lambda c: c.grab().toImage().pixelColor(c.width() // 2, 0).name()  # noqa: E731
            assert borda(aberto) == borda(fechado), "o aberto tem a mesma borda do fechado (sem o contorno azul)"
            tela.resize(1900, 800)  # caberiam 2 colunas: a ficha continua com uma
            _processar()
            assert tela.lista_vendas.width() >= 2 * card_mod.LARGURA_CARD + 8
            assert all(c.x() == 0 and c.width() == tela.lista_vendas.width() for c in tela.lista_vendas.cards)
            tela.resize(1250, 800)
            _processar()
            # dois cliques ABAIXO do topo (onde ficam os bancos) não fecham; no topo (cliente, status), fecham
            aberto = tela.lista_vendas.card_aberto()
            QTest.mouseDClick(aberto, Qt.MouseButton.LeftButton, pos=QPoint(40, aberto._divisor.y() + 12))
            _processar()
            assert tela.lista_vendas.aberta == id_a, "dois cliques abaixo do topo não fecham o card"
            aberto = tela.lista_vendas.card_aberto()
            QTest.mouseDClick(aberto, Qt.MouseButton.LeftButton, pos=QPoint(40, 12))
            _processar()
            assert tela.lista_vendas.aberta is None and tela.lista_vendas.card_aberto() is None, "dois cliques no topo fecham"
            print("OK: na ficha, uma coluna só, todo card na largura toda; aberto, sem o 'Abrir a ficha' e sem borda azul; "
                  "dois cliques no topo do card aberto o fecham.")

            linha("4) Gravar numa venda relê as vendas sem mexer nos dados do cliente que estão sendo editados")
            sinais: list[int] = []
            tela.dados_atualizados.connect(lambda: sinais.append(1))
            tela._alternar_edicao_cliente()
            tela._campo_nome.setText("MARIA EDITANDO")
            # a roda do mouse passando pelas caixas de escolha (selecionadas ou não) rola a ficha, não troca a opção
            for combo in (tela._campo_tipo, tela._campo_vendedor, tela._campo_uf):
                antes = combo.currentText()
                for com_foco in (False, True):
                    if com_foco:
                        combo.setFocus()
                    roda = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, -120), Qt.MouseButton.NoButton,
                                       Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
                    QApplication.sendEvent(combo, roda)
                    assert not roda.isAccepted() and combo.currentText() == antes, (combo.objectName(), com_foco)
            linha_a = next(l for l in _card(tela, id_a).linhas_de_banco if l["proposta"].id == pa)
            msgs.limpar()
            linha_a["bolinhas"][0].click()  # Em Análise -> Aprovado
            _processar()
            msgs.exigir_sem_erros("bolinha na ficha")
            assert _status(pa) == propostas_mod.STATUS_APROVADO
            assert tela._campo_nome.text() == "MARIA EDITANDO" and not tela._modo_leitura_cliente, "o digitado ficou"
            assert sinais, "avisa quem mostra dado derivado (Dashboard, selo)"
            assert not tela._faixa_aviso.isHidden() and propostas_mod.STATUS_APROVADO in tela._faixa_aviso.texto.text()
            nova_linha = next(l for l in _card(tela, id_a).linhas_de_banco if l["proposta"].id == pa)
            assert nova_linha["proposta"].status == propostas_mod.STATUS_APROVADO, "o card mostra o status novo"
            tela._cancelar_edicao_cliente()
            assert tela._modo_leitura_cliente and tela._campo_nome.text() != "MARIA EDITANDO"
            print("OK: a bolinha grava, o card e o aviso mostram o status novo, e o nome em edição continua lá.")

            linha("5) '+ Nova venda' já vem com o cliente da ficha e abre o card novo")
            recebidos: list[str] = []

            def _cria(dialogo):
                recebidos.append(dialogo._clientes_por_rotulo.get(dialogo._cliente.currentText()))
                dialogo._linhas_equipamento[0].setCurrentText("Mesa Exemplo")
                dialogo._gravar()
                return dialogo.result()

            VendaDialog.exec = _cria
            tela._botao_nova_venda.click()
            VendaDialog.exec = exec_original
            _processar()
            assert recebidos == [clientes_mod.buscar_por_cpf(fx.CPF_MARIA)["CPF/CNPJ"]], recebidos
            nova = tela.lista_vendas.card_aberto()
            assert nova is not None and nova.venda.equipamentos == "Mesa Exemplo" and nova.venda.propostas == ()
            assert len(tela.lista_vendas.cards) == 3 and tela._resumo_label.text().startswith("3 vendas (")
            assert "Venda criada" in tela._faixa_aviso.texto.text()
            id_nova = nova.venda.id
            print("OK: o diálogo vem com a MARIA escolhida; a venda nova aparece aberta, e o resumo conta 3.")

            linha("6) Um formulário aberto por vez na ficha (o da proposta antiga e o do card de venda)")
            tela._lista_historico.acionado.emit(0)  # o duplo clique numa antiga
            f = tela._expansor.formulario()
            assert f is not None
            f._botao_editar.click()
            f._observacoes.setPlainText("digitando na antiga")
            msgs.limpar()
            msgs.resposta_pergunta = NAO
            assert not tela.lista_vendas.editar_proposta(_card(tela, id_nova).venda, None)
            assert msgs.ultima()[1] == "Alterações não salvas" and tela._expansor.formulario() is f
            assert tela.lista_vendas.editando is None, "'Não': segue na antiga, e o da venda não abre"
            msgs.resposta_pergunta = SIM
            assert tela.lista_vendas.editar_proposta(_card(tela, id_nova).venda, None)
            _processar()
            assert not tela._expansor.esta_expandido() and tela.lista_vendas.editando == NOVA
            tela.lista_vendas.card_aberto().formulario._valor.setValue(777)
            assert tela.tem_edicao_pendente()
            msgs.limpar()
            msgs.resposta_pergunta = NAO
            tela._lista_historico.acionado.emit(0)
            assert msgs.ultima()[1] == "Alterações não salvas" and not tela._expansor.esta_expandido()
            assert tela.lista_vendas.card_aberto().formulario._valor.value() == 777, "'Não': o digitado na venda fica"
            msgs.resposta_pergunta = SIM
            tela._lista_historico.acionado.emit(0)
            _processar()
            assert tela._expansor.esta_expandido() and tela.lista_vendas.editando is None and not tela.tem_edicao_pendente()
            tela._expansor.descartar()
            print("OK: abrir um formulário com outro em edição pergunta antes ('Não' mantém o que estava sendo digitado).")

            linha("7) Recarregar com algo digitado no card da venda pergunta antes")
            tela.lista_vendas.editar_proposta(_card(tela, id_nova).venda, None)
            _processar()
            tela.lista_vendas.card_aberto().formulario._valor.setValue(555)
            msgs.limpar()
            msgs.resposta_pergunta = NAO
            tela._ao_recarregar()
            assert msgs.ultima()[1] == "Alterações não salvas" and tela.tem_edicao_pendente()
            msgs.resposta_pergunta = SIM
            tela._ao_recarregar()
            _processar()
            assert not tela.tem_edicao_pendente() and tela.lista_vendas.editando is None
            print("OK: 'Recarregar' pergunta; 'Sim' descarta o formulário do card de venda.")

            linha("8) 'Duplicar' do Dashboard: proposta de venda vai pro card dela; a antiga, pro card 'Nova proposta'")
            assert tela.abrir_nova_proposta_a_partir_de(fx.CPF_MARIA, v.indice_da_proposta(pa))
            _processar()
            assert tela.lista_vendas.aberta == id_a and tela.lista_vendas.editando == NOVA
            assert not tela._expansor.esta_expandido()
            tela.lista_vendas.descartar()
            assert tela.abrir_nova_proposta_a_partir_de(fx.CPF_MARIA, antigas[0])
            assert tela._expansor.eh_rascunho() and tela.lista_vendas.editando is None
            tela._expansor.descartar()
            print("OK: de uma proposta de venda abre o '+ Adicionar proposta' do card dela; de uma antiga, o card 'Nova proposta'.")

            linha("9) Gravar numa venda lá embaixo não leva a ficha pro topo")
            for i in range(10):
                v.criar_venda(fx.CPF_MARIA, ["Cadeira Exemplo"], _pedido((b1, b2)[i % 2], 1000 + i))
            tela._depois_de_gravar_venda()
            _processar()
            barra = tela._rolagem_ficha.verticalScrollBar()
            barra.setValue(barra.maximum())
            _processar()
            antes = barra.value()
            assert antes > 200, f"a ficha precisa rolar pro teste valer ({antes})"
            ultimo = next(c for c in reversed(tela.lista_vendas.cards) if c.linhas_de_banco and c.linhas_de_banco[0]["bolinhas"])
            ultimo.linhas_de_banco[0]["bolinhas"][0].click()
            _processar()
            assert barra.value() == antes, f"a rolagem foi de {antes} para {barra.value()}"
            assert tela._rolagem_ficha.widget().minimumHeight() == 0, "a altura fica solta de novo (senão não encolhe mais)"
            print(f"OK: a bolinha numa venda lá embaixo mantém a rolagem da ficha ({antes}).")

            linha("10) Ficha fechada ou outro cliente: o formulário do card de venda não fica pendurado")
            tela.lista_vendas.editar_proposta(tela.lista_vendas.cards[0].venda, None)
            _processar()
            tela.lista_vendas.card_aberto().formulario._valor.setValue(321)
            msgs.limpar()
            tela._selecionar_cliente("")  # a lista de clientes ficou sem seleção (ex.: um filtro escondeu a MARIA)
            _processar()
            assert msgs.ultima()[1] == "Alterações descartadas" and not tela.tem_edicao_pendente(), \
                "sem ficha aberta, nada pendente escondido (sairia perguntando por algo que não se vê)"
            tela._selecionar_por_cpf(fx.CPF_MARIA)
            _processar()
            tela.lista_vendas.editar_proposta(tela.lista_vendas.cards[0].venda, None)
            _processar()
            tela.lista_vendas.card_aberto().formulario._valor.setValue(321)
            msgs.limpar()
            tela._selecionar_por_cpf(fx.CPF_JOAO)
            _processar()
            assert msgs.ultima()[1] == "Alterações descartadas" and not tela.tem_edicao_pendente()
            assert [c.venda.id for c in tela.lista_vendas.cards] == [id_j] and barra.value() == 0
            assert tela.lista_vendas.aberta is None
            print("OK: sem cliente na ficha, ou com outro, o formulário que estava aberto é descartado (avisando); "
                  "a ficha do JOÃO mostra só a venda dele, a partir do topo.")

            linha("11) Nenhuma janela solta piscou")
            _processar()
            assert soltas.vistas == [], soltas.vistas
            print("OK: nenhum pedaço de card apareceu como janela solta.")
            tela.close()

            linha("12) Vendedor: o histórico de propostas inteiro, sem os cards de venda (que são de edição)")
            vendedor = bd.ler_clientes(caminho).set_index("CPF/CNPJ").loc[fx.CPF_MARIA, "VENDEDOR"]
            sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_VENDEDOR, nome_usuario=vendedor))
            clientes_mod._ler_da_fonte_ativa = lambda: sessao_mod.filtrar_por_vendedor_logado(bd.ler_clientes(caminho))
            propostas_mod._ler_da_fonte_ativa = lambda: sessao_mod.filtrar_por_vendedor_logado(bd.ler_propostas(caminho))
            tela_v = FichaClienteScreen()
            tela_v.resize(1250, 800)
            tela_v.show()
            tela_v._selecionar_por_cpf(fx.CPF_MARIA)
            _processar()
            for parte in (tela_v._titulo_vendas, tela_v.lista_vendas, tela_v._dica_antigas, tela_v._botao_nova_venda,
                          tela_v._botao_excluir_proposta):
                assert parte.isHidden(), parte
            assert tela_v._titulo_historico.text() == "Histórico de propostas"
            todas = propostas_mod.historico_por_cpf(fx.CPF_MARIA)
            assert tela_v._modelo_historico.total() == len(todas) > len(antigas), "as de venda também, como antes"
            assert "propostas" in tela_v._resumo_label.text() and "venda" not in tela_v._resumo_label.text()
            tela_v.close()
            print(f"OK: o vendedor vê as {len(todas)} propostas da MARIA no histórico, sem os cards de venda.")
        linha("TUDO OK")
    finally:
        VendaDialog.exec = exec_original
        clientes_mod._ler_da_fonte_ativa, propostas_mod._ler_da_fonte_ativa = fontes
        app.removeEventFilter(soltas)
        nuvem._obter_cliente, sheets_sync._obter_cliente = rede_original
        fx.restaurar_modulos()
        sessao_mod.encerrar()
        assert fx.instantaneo_do_registro() == registro_antes, "o teste mexeu nas preferências reais"


if __name__ == "__main__":
    main()
