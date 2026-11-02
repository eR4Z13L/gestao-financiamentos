"""Prova a correcao 1 da 1.6: depois de gravar, a tela troca so o card da venda tocada (e nao relê e remonta a lista
inteira). Tres partes:
1) core: resumo_da_venda(id) e IGUAL ao item da lista completa (listar_vendas), campo a campo, na planilha com todos os
   casos (a mesma da prova de listar_vendas); antes e depois de gravar; venda que nao existe vira ErroVenda.
2) tela Vendas: o card tocado e trocado no lugar (os outros sao os mesmos objetos), o card aberto continua aberto com o
   formulario e o que foi digitado, a rolagem nao se mexe, contador e aviso atualizam, a lista nao e relida; a venda que
   sai do filtro some (sem reler o arquivo); e nos casos de duvida (arquivo mudou por fora, releitura da venda falhou,
   card nao esta na lista) rele tudo como antes.
3) Ficha de Cliente: mesma troca, com o resumo do topo atualizado.

Planilha 100% ficticia em pasta temporaria, preferencias isoladas, Google desligado (qualquer acesso derruba).

Rodar com: venv/Scripts/python.exe scripts/smoke_test_card_so_o_tocado.py
"""

from __future__ import annotations

import dataclasses
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False
import fixture_ficticia as fx
import smoke_test_listar_vendas_igual as lista_igual
from ambiente_de_teste import Mensagens
from core import bancos as bancos_mod
from core import data_store as bd
from core import data_store_sheets as nuvem
from core import equipamentos as equipamentos_mod
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import sheets_sync
from core import vendas as v
from desktop.screens import vendas_screen as tela_mod
from desktop.screens.ficha_cliente_screen import FichaClienteScreen
from desktop.theme import TEMA_ESCURO, build_stylesheet

ADMIN = sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador")


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _processar() -> None:
    for _ in range(4):
        QApplication.processEvents()


def _pedido(banco: str, valor: float = 40000) -> dict:
    return {"BANCO": banco, "VALOR (R$)": valor, "MESES": 36}


def _card(lista, id_venda: str):
    return next(c for c in lista.cards if c.venda.id == id_venda)


def _proposta(card, id_proposta: str):
    return next(p for p in card.venda.propostas if p.id == id_proposta)


def _ordem_das_colunas(lista) -> list[list[str]]:
    """Os ID_VENDA de cada coluna, de cima para baixo (a ordem real do layout, nao so a lista de cards)."""
    return [[pilha.itemAt(i).widget().venda.id for i in range(pilha.count()) if pilha.itemAt(i).widget() is not None]
            for pilha in lista._pilhas]


def _contador_certo(tela, listar) -> str:
    """O texto que o contador deve ter, calculado das vendas lidas do arquivo (sem contar como releitura da tela)."""
    from desktop.widgets.lista_de_vendas import resumo_por_status
    vendas = [x for x in listar.original() if x.id in {c.venda.id for c in tela.lista.cards}]
    resumo = resumo_por_status(vendas)
    return f"{len(vendas)} venda(s)" + (f" · {resumo}" if resumo else "")


def _cards_vivos(lista) -> int:
    """Quantos cards de venda a lista tem como filhos de verdade (um card velho esquecido na tela contaria a mais)."""
    from desktop.widgets.card_da_venda import CardDaVenda
    _processar()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)  # os deleteLater pendentes de verdade
    return len(lista.findChildren(CardDaVenda))


class Contador:
    """Conta as chamadas de uma funcao de um modulo (sem mudar o que ela faz)."""

    def __init__(self, modulo, nome: str):
        self.modulo, self.nome, self.original, self.chamadas = modulo, nome, getattr(modulo, nome), 0
        setattr(modulo, nome, self)

    def __call__(self, *a, **k):
        self.chamadas += 1
        return self.original(*a, **k)

    def zerar(self) -> None:
        self.chamadas = 0

    def restaurar(self) -> None:
        setattr(self.modulo, self.nome, self.original)


def parte_core() -> None:
    linha("1) core: resumo_da_venda(id) e igual ao item da lista completa, em todos os casos")
    pasta = Path(tempfile.mkdtemp(prefix="_smoke_card_tocado_core_"))
    fx.isolar_preferencias(pasta)
    caminho = fx.criar(pasta)
    fx.apontar_modulos_para(caminho)
    sessao_mod.iniciar(ADMIN)
    try:
        lista_igual.montar_planilha(caminho)
        hoje = lista_igual.HOJE
        completa = v.listar_vendas(hoje)
        assert len(completa) == 10
        for r in completa:
            um = v.resumo_da_venda(r.id, hoje)
            assert um == r and repr(um) == repr(r), f"venda {r.id!r} difere:\n  uma:    {um!r}\n  lista:  {r!r}"
        print(f"OK: as {len(completa)} vendas (todos os status, propostas sem ID, venda sem ID, datas ausentes...) iguais.")

        listar_original = v.listar_vendas

        def _proibida(*_a, **_k):
            raise AssertionError("resumo_da_venda nao pode montar a lista inteira")

        v.listar_vendas = _proibida
        try:
            v.resumo_da_venda("V-2", hoje)
        finally:
            v.listar_vendas = listar_original
        print("OK: monta so a venda pedida (nao passa pela lista inteira).")

        v.mudar_status_proposta("P-b1", propostas_mod.STATUS_PRE_APROVADO)
        v.fechar_proposta("P-b3")
        v.adicionar_pendencia("V-3", "texto da pendencia")
        v.mudar_status_venda("V-2", v.VENDA_PERDIDA, motivo="Desistiu")
        for r in v.listar_vendas():
            assert v.resumo_da_venda(r.id) == r, f"depois de gravar, venda {r.id!r} difere da lista"
        print("OK: depois de mudar status, fechar, pendencia e desfecho, cada uma continua igual a da lista.")

        try:
            v.resumo_da_venda("V-NAO-EXISTE")
        except v.ErroVenda as exc:
            assert "não encontrada" in str(exc)
        else:
            raise AssertionError("venda inexistente deveria dar ErroVenda")
        print("OK: venda que nao existe mais -> ErroVenda com mensagem.")
    finally:
        fx.restaurar_modulos()
        sessao_mod.encerrar()


def parte_telas() -> None:
    pasta = Path(tempfile.mkdtemp(prefix="_smoke_card_tocado_tela_"))
    fx.isolar_preferencias(pasta)
    caminho = fx.criar(pasta)
    fx.apontar_modulos_para(caminho)
    sessao_mod.iniciar(ADMIN)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(build_stylesheet(TEMA_ESCURO))
    listar = Contador(v, "listar_vendas")
    do_cliente = Contador(v, "vendas_do_cliente")
    try:
        with Mensagens() as msgs:
            b1, b2 = bancos_mod.nomes_ativos()[:2]
            for nome in ("Cadeira Exemplo", "Laser Exemplo", "Mesa Exemplo"):
                equipamentos_mod.cadastrar({"EQUIPAMENTO": nome})
            # V_A: andamento (um banco fechado Aprovado + um Em Analise); V_B: aguardando (2 bancos Em Analise);
            # V_C: andamento com o banco fechado em Assinado; V_D e V_E: aguardando (preenchem a lista)
            id_a, pa1 = v.criar_venda(fx.CPF_MARIA, ["Cadeira Exemplo"], _pedido(b1))
            pa2 = v.mandar_a_outro_banco(id_a, _pedido(b2))
            v.mudar_status_proposta(pa1, propostas_mod.STATUS_APROVADO)
            v.fechar_proposta(pa1)
            id_b, pb1 = v.criar_venda(fx.CPF_JOAO, ["Laser Exemplo"], _pedido(b1))
            pb2 = v.mandar_a_outro_banco(id_b, _pedido(b2))
            id_c, pc1 = v.criar_venda(fx.CPF_ANA, ["Mesa Exemplo"], _pedido(b1))
            v.mudar_status_proposta(pc1, propostas_mod.STATUS_APROVADO)
            v.fechar_proposta(pc1)
            v.mudar_status_proposta(pc1, propostas_mod.STATUS_ASSINADO)
            id_d, pd1 = v.criar_venda(fx.CPF_JOAO, ["Mesa Exemplo"], _pedido(b2))
            id_e, pe1 = v.criar_venda(fx.CPF_ANA, ["Cadeira Exemplo"], _pedido(b2))

            linha("2) Tela Vendas: so o card tocado e trocado")
            tela = tela_mod.VendasScreen()
            tela.resize(1100, 420)
            tela.show()
            _processar()
            tela.filtro.setCurrentText(tela_mod.FILTRO_TODAS)
            _processar()
            assert len(tela.lista.cards) == 5
            # um card aberto, com a rolagem no meio
            tela.lista.abrir_venda(_card(tela.lista, id_b).venda)
            _processar()
            barra = tela.rolagem.verticalScrollBar()
            assert barra.maximum() > 0, "a janela baixa precisa ter rolagem para o teste"
            barra.setValue(min(40, barra.maximum()))
            _processar()
            rolagem = barra.value()
            assert rolagem > 0
            antes = list(tela.lista.cards)
            ordem = _ordem_das_colunas(tela.lista)
            emitidos = []
            tela.dados_atualizados.connect(lambda: emitidos.append(1))
            assert _cards_vivos(tela.lista) == len(antes), (_cards_vivos(tela.lista), len(antes))
            listar.zerar()
            tocada = _card(tela.lista, id_a)
            msgs.limpar()
            assert tela.lista.controle.mudar_proposta(tocada.venda, _proposta(tocada, pa2), propostas_mod.STATUS_PRE_APROVADO)
            _processar()
            assert listar.chamadas == 0, "a lista inteira nao pode ser relida para trocar um status"
            depois = list(tela.lista.cards)
            assert len(depois) == len(antes)
            for a, d in zip(antes, depois):
                if a.venda.id == id_a:
                    assert d is not a, "o card tocado e refeito"
                else:
                    assert d is a, f"o card {a.venda.id} nao foi tocado e nao pode ser refeito"
            novo = _card(tela.lista, id_a)
            assert _ordem_das_colunas(tela.lista) == ordem, "o card novo fica na mesma coluna e posicao do velho (e o velho sai)"
            assert tela.lista.venda_por_id(id_a) is novo.venda
            assert emitidos == [1], "quem mostra dado derivado (Dashboard, selo) e avisado"
            assert _cards_vivos(tela.lista) == len(antes), "o card velho nao fica esquecido na tela"
            assert _proposta(novo, pa2).status == propostas_mod.STATUS_PRE_APROVADO and _proposta(novo, pa1).fechada
            assert tela._vendas[[x.id for x in tela._vendas].index(id_a)] is novo.venda
            assert tela.lista.aberta == id_b and tela.lista.card_aberto().venda.id == id_b, "o card aberto continua aberto"
            assert barra.value() == rolagem, "a rolagem nao se mexe"
            assert tela.faixa_aviso.texto.text().endswith('"Em Análise" → "Pré-aprovado".'), tela.faixa_aviso.texto.text()
            assert "5 venda(s)" in tela.contador.text()
            assert not tela._vigia.mudou_desde_a_leitura(), "a propria gravacao nao parece mudanca de fora"
            assert not tela.recarregar_se_mudou() and listar.chamadas == 0
            msgs.exigir_sem_erros("trocar um status")
            print("OK: so o card da venda tocada foi refeito; outros, aberto, rolagem, contador, aviso e vigia ok; lista nao relida.")

            linha("2b) Fechar o banco, pendencia e desfecho tambem trocam so o card")
            tocada = _card(tela.lista, id_d)
            antes = list(tela.lista.cards)
            ordem = _ordem_das_colunas(tela.lista)
            assert any(coluna.index(id_d) > 0 for coluna in ordem if id_d in coluna), "o card tocado nao e o primeiro da coluna"
            tela.lista.controle._pedir_pendencia = lambda venda: "esperando o frete"
            assert tela.lista.controle.adicionar_pendencia(tocada.venda)
            _processar()
            assert [c for c in tela.lista.cards if c.venda.id == id_d][0].venda.pendencias_abertas == 1
            assert [a is d for a, d in zip(antes, tela.lista.cards) if a.venda.id != id_d] == [True] * 4
            assert _ordem_das_colunas(tela.lista) == ordem and _cards_vivos(tela.lista) == len(antes)
            tocada = _card(tela.lista, id_a)
            assert tela.lista.controle.desmarcar_banco(tocada.venda, _proposta(tocada, pa1))  # Aprovado: pode desmarcar
            _processar()
            assert not _card(tela.lista, id_a).venda.fechadas, "desmarcou o banco"
            assert _card(tela.lista, id_a).venda.status == v.VENDA_AGUARDANDO
            assert tela.contador.text() == _contador_certo(tela, listar), tela.contador.text()
            assert tela.lista.controle.fechar_banco(_card(tela.lista, id_a).venda, _proposta(_card(tela.lista, id_a), pa1))
            _processar()
            assert _card(tela.lista, id_a).venda.fechadas == (pa1,)
            assert listar.chamadas == 0
            # o que a lista guarda para "Carregar mais" tambem e o novo: montar de novo mostra o mesmo
            tela.lista._montar()
            assert _card(tela.lista, id_d).venda.pendencias_abertas == 1 and _card(tela.lista, id_a).venda.fechadas == (pa1,)
            assert tela.lista.total() == 5
            # direto na lista: venda que ela nao tem -> False (quem chamou rele tudo); formulario guardado que ninguem quis nao sobra
            assert tela.lista.trocar_venda(dataclasses.replace(_card(tela.lista, id_a).venda, id="V-FORA")) is False
            tela.lista._trocar_item(_card(tela.lista, id_e).venda, ("outra|chave", QWidget()))
            assert tela.lista._guardado is None, "o formulario guardado que o card novo nao quis e descartado"
            print("OK: pendencia, desmarcar e fechar banco: cada um trocou so o card, sem reler a lista.")

            linha("2c) O formulario aberto no card tocado volta com o que foi digitado")
            venda_b = _card(tela.lista, id_b).venda
            assert tela.lista.abrir_venda(venda_b, pb1)
            _processar()
            formulario = tela.lista.card_aberto().formulario
            formulario._observacoes.setPlainText("rascunho que nao pode sumir")
            assert formulario.tem_alteracoes()
            cartao = tela.lista.card_aberto()
            assert tela.lista.controle.mudar_proposta(cartao.venda, _proposta(cartao, pb2), propostas_mod.STATUS_PRE_APROVADO)
            _processar()
            cartao2 = tela.lista.card_aberto()
            assert cartao2 is not cartao and cartao2.venda.id == id_b
            assert cartao2.formulario is formulario and formulario.tem_alteracoes(), "o formulario aberto e o digitado ficam"
            assert formulario._observacoes.toPlainText() == "rascunho que nao pode sumir" and not formulario.isHidden()
            assert tela.lista.editando == pb1 and listar.chamadas == 0
            # e tocar OUTRA venda com esse formulario aberto: o formulario fica onde esta
            outra = _card(tela.lista, id_a)
            assert tela.lista.controle.mudar_proposta(outra.venda, _proposta(outra, pa2), propostas_mod.STATUS_EM_ANALISE)
            _processar()
            assert tela.lista.card_aberto().formulario is formulario and formulario.tem_alteracoes() and not formulario.isHidden()
            assert formulario._observacoes.toPlainText() == "rascunho que nao pode sumir"
            tela.lista.descartar()
            tela.lista.fechar_venda()
            _processar()
            print("OK: formulario aberto e texto digitado seguem no card novo (e ao tocar outra venda).")

            linha("2d) A venda que sai do filtro some da lista (da memoria, sem reler o arquivo)")
            tela.filtro.setCurrentText(tela_mod.FILTRO_EM_ANDAMENTO)
            _processar()
            assert id_c in {c.venda.id for c in tela.lista.cards}
            listar.zerar()
            cartao = _card(tela.lista, id_c)
            assert tela.lista.controle.efetivar_banco(cartao.venda, _proposta(cartao, pc1))  # a pergunta responde Sim
            _processar()
            assert listar.chamadas == 0
            assert id_c not in {c.venda.id for c in tela.lista.cards}, "efetivada sai de 'Em andamento'"
            assert "1 efetivada" not in tela.contador.text() and tela.contador.text().startswith(f"{len(tela.lista.cards)} venda(s)")
            assert next(x for x in tela._vendas if x.id == id_c).status == v.VENDA_EFETIVADA
            print("OK: a venda efetivada saiu do filtro sem reler a lista; contador e cards batem.")

            linha("2e) Em duvida, rele tudo: arquivo mudou por fora, releitura falhou, card fora da lista")
            tela.filtro.setCurrentText(tela_mod.FILTRO_TODAS)
            _processar()
            # (1) alguem mexeu no arquivo por fora (outro PC / outra tela) antes de gravar
            v.mudar_status_proposta(pe1, propostas_mod.STATUS_PRE_APROVADO)  # "por fora": a tela nao sabe
            assert tela._vigia.mudou_desde_a_leitura()
            listar.zerar()
            cartao = _card(tela.lista, id_d)
            assert tela.lista.controle.mudar_proposta(cartao.venda, _proposta(cartao, pd1), propostas_mod.STATUS_PRE_APROVADO)
            _processar()
            assert listar.chamadas == 1, "o arquivo ja tinha mudado: rele a lista inteira"
            assert _proposta(_card(tela.lista, id_e), pe1).status == propostas_mod.STATUS_PRE_APROVADO, "viu a mudanca de fora"
            # (2) a releitura da venda falha: rele tudo (e a lista continua certa)
            original = v.resumo_da_venda
            v.resumo_da_venda = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("falha de leitura"))
            try:
                listar.zerar()
                cartao = _card(tela.lista, id_d)
                assert tela.lista.controle.mudar_proposta(cartao.venda, _proposta(cartao, pd1), propostas_mod.STATUS_EM_ANALISE)
                _processar()
            finally:
                v.resumo_da_venda = original
            assert listar.chamadas == 1 and _proposta(_card(tela.lista, id_d), pd1).status == propostas_mod.STATUS_EM_ANALISE
            # (3) a venda nao esta na lista da tela
            tela._vendas = [x for x in tela._vendas if x.id != id_e]
            listar.zerar()
            tela._depois_de_gravar_venda(id_e, "x")
            assert listar.chamadas == 1 and id_e in {x.id for x in tela._vendas}
            # (4) o card nao esta montado (alem da pagina carregada): troca so o dado, sem erro
            tela.lista._limite = 2
            tela.lista._montar()
            fora = next(x.id for x in tela.lista._vendas if x.id not in {c.venda.id for c in tela.lista.cards})
            listar.zerar()
            tela._depois_de_gravar_venda(fora, "")
            assert listar.chamadas == 0 and fora not in {c.venda.id for c in tela.lista.cards}
            msgs.exigir_sem_erros("os casos de duvida")
            print("OK: arquivo mudou por fora / releitura falhou / venda fora da lista -> rele tudo; card nao montado -> so o dado.")

            linha("2e-bis) Excluir uma proposta rele tudo (as posicoes das outras propostas mudam)")
            id_f, pf1 = v.criar_venda(fx.CPF_ANA, ["Laser Exemplo"], _pedido(b1))
            pf2 = v.mandar_a_outro_banco(id_f, _pedido(b2))
            tela.lista._limite = 30
            tela.carregar()
            listar.zerar()
            cartao = _card(tela.lista, id_f)
            assert tela.lista.controle.excluir_proposta(cartao.venda, _proposta(cartao, pf1))  # a pergunta responde Sim
            _processar()
            assert listar.chamadas == 1, "apagar uma linha muda o indice das propostas de outras vendas: rele tudo"
            for venda in tela._vendas:
                for p in venda.propostas:
                    assert p.indice == v.indice_da_proposta(p.id), f"indice velho em {venda.id}/{p.id}"
            print("OK: excluir proposta rele a lista e nenhum indice fica velho.")

            linha("2f) O tempo (planilha pequena; a medida certa e a de docs/ferramentas/diagnostico_1_6)")
            tela.lista._limite = 30
            tela.lista._montar()
            cartao = _card(tela.lista, id_d)
            t = time.perf_counter()
            tela.lista.controle.mudar_proposta(cartao.venda, _proposta(cartao, pd1), propostas_mod.STATUS_PRE_APROVADO)
            _processar()
            print(f"   clique -> card atualizado: {(time.perf_counter() - t) * 1000:.0f} ms")
            tela.close()

            linha("3) Ficha de Cliente: a mesma troca, com o resumo do topo")
            ficha = FichaClienteScreen()
            ficha.resize(1250, 800)
            ficha.show()
            _processar()
            ficha._selecionar_por_cpf(fx.CPF_JOAO)
            _processar()
            ids_joao = {c.venda.id for c in ficha.lista_vendas.cards}
            assert ids_joao == {id_b, id_d}, ids_joao
            resumo_antes = ficha._resumo_label.text()
            antes = list(ficha.lista_vendas.cards)
            do_cliente.zerar()
            emitidos_ficha = []
            ficha.dados_atualizados.connect(lambda: emitidos_ficha.append(1))
            cartao = _card(ficha.lista_vendas, id_d)
            assert ficha.lista_vendas.controle.mudar_proposta(cartao.venda, _proposta(cartao, pd1), propostas_mod.STATUS_APROVADO)
            _processar()
            assert emitidos_ficha == [1], "a ficha tambem avisa quem mostra dado derivado"
            assert do_cliente.chamadas == 0, "a ficha nao rele as vendas do cliente para trocar um status"
            depois = list(ficha.lista_vendas.cards)
            assert [a is d for a, d in zip(antes, depois) if a.venda.id != id_d] == [True]
            assert _proposta(_card(ficha.lista_vendas, id_d), pd1).status == propostas_mod.STATUS_APROVADO
            assert ficha._vendas_do_cliente[[x.id for x in ficha._vendas_do_cliente].index(id_d)] is _card(ficha.lista_vendas, id_d).venda
            assert not ficha._vigia.mudou_desde_a_leitura() and not ficha.recarregar_se_mudou()
            # fechar e efetivar: o resumo do topo ganha o valor efetivado
            assert ficha.lista_vendas.controle.fechar_banco(_card(ficha.lista_vendas, id_d).venda,
                                                            _proposta(_card(ficha.lista_vendas, id_d), pd1))
            _processar()
            assert ficha.lista_vendas.controle.efetivar_banco(_card(ficha.lista_vendas, id_d).venda,
                                                              _proposta(_card(ficha.lista_vendas, id_d), pd1))
            _processar()
            assert do_cliente.chamadas == 0
            assert "efetivado" in ficha._resumo_label.text() and ficha._resumo_label.text() != resumo_antes, ficha._resumo_label.text()
            assert ficha._resumo_label.text().startswith("2 vendas (1 aguardando bancos, 1 efetivada)"), ficha._resumo_label.text()
            # o arquivo mudou por fora antes de gravar: rele tudo
            v.mudar_status_proposta(pb1, propostas_mod.STATUS_PRE_APROVADO)
            do_cliente.zerar()
            cartao = _card(ficha.lista_vendas, id_b)
            assert ficha.lista_vendas.controle.mudar_proposta(cartao.venda, _proposta(cartao, pb2), propostas_mod.STATUS_NEGADO)
            _processar()
            assert do_cliente.chamadas == 1
            assert _proposta(_card(ficha.lista_vendas, id_b), pb1).status == propostas_mod.STATUS_PRE_APROVADO
            msgs.exigir_sem_erros("a ficha")
            print("OK: ficha troca so o card, atualiza o resumo do topo e rele tudo se o arquivo mudou por fora.")
            ficha.close()
        linha("TUDO OK")
    finally:
        listar.restaurar()
        do_cliente.restaurar()
        fx.restaurar_modulos()
        sessao_mod.encerrar()


def main() -> None:
    def _sem_rede(*_a, **_k):
        raise AssertionError("o teste tentou acessar o Google de verdade")

    rede_original = (nuvem._obter_cliente, sheets_sync._obter_cliente)
    nuvem._obter_cliente = sheets_sync._obter_cliente = _sem_rede
    registro_antes = fx.instantaneo_do_registro()
    try:
        parte_core()
        parte_telas()
    finally:
        nuvem._obter_cliente, sheets_sync._obter_cliente = rede_original
        assert fx.instantaneo_do_registro() == registro_antes, "o teste mexeu nas preferências reais"


if __name__ == "__main__":
    main()
