"""Testa que TROCAR DE PAGINA mostra os dados atuais: quando o arquivo de dados muda por fora da tela
(outra tela gravou, baixou da nuvem, restaurou backup, editou no Excel), a tela rele ao aparecer - sem
precisar do botao Atualizar nem de pesquisar algo. E que nao rele a toa (nada mudou) nem atropela quem esta
editando. Planilha ficticia, sem rede (ambiente_de_teste).

Rodar com: venv/Scripts/python.exe scripts/smoke_test_atualizar_ao_trocar_de_pagina.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
import fixture_ficticia as fx
from ambiente_de_teste import Ambiente, Mensagens
from core import clientes as clientes_mod
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import vendedores as vendedores_mod
from desktop.main_window import PAGINA_ADMINISTRACAO, PAGINA_DASHBOARD, PAGINA_FICHA, PAGINA_PROPOSTAS
from desktop.theme import TEMA_ESCURO
from desktop.vigia_do_arquivo import VigiaDoArquivo


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _ir(janela, chave: str) -> None:
    janela.ir_para(chave)
    QApplication.processEvents()


class _Contador:
    """Conta as chamadas de um metodo de um objeto (sem mudar o que ele faz)."""

    def __init__(self, dono, nome: str):
        self._dono, self._nome = dono, nome
        self._original = getattr(dono, nome)
        self.vezes = 0

        def _contando(*args, **kwargs):
            self.vezes += 1
            return self._original(*args, **kwargs)

        setattr(dono, nome, _contando)

    def desfazer(self) -> None:
        setattr(self._dono, self._nome, self._original)


def _renomear_por_fora(cpf: str, nome: str) -> None:
    """Muda so o nome do cliente direto no arquivo (como outra tela ou um download fariam)."""
    import pandas as pd

    atual = {k: ("" if (not isinstance(v, pd.Timestamp) and pd.isna(v)) else v) for k, v in clientes_mod.buscar_por_cpf(cpf).items()}
    atual["CLIENTE"] = nome
    clientes_mod.atualizar_cliente(cpf, atual)


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    listagem_real = sorted(p.name for p in config.DIRETORIO_DADOS.glob("*")) if config.DIRETORIO_DADOS.exists() else []
    amb = Ambiente(volumoso=True)
    try:
        with Mensagens() as msgs:
            janela = amb.nova_janela("admin", TEMA_ESCURO)
            ficha, propostas, dashboard, adm = (
                janela._tela_ficha, janela._tela_propostas, janela._tela_dashboard, janela._tela_administracao)
            for chave in (PAGINA_FICHA, PAGINA_PROPOSTAS, PAGINA_ADMINISTRACAO, PAGINA_DASHBOARD):
                _ir(janela, chave)  # todas as telas ja apareceram uma vez

            # ------------------------------------------------------------------------------------
            linha("1) Ficha de Cliente: cliente gravado por fora aparece ao voltar, sem pesquisar")
            cpf_novo = fx.cpf_ficticio(500_000_001)
            clientes_mod.adicionar_cliente({"CPF/CNPJ": cpf_novo, "CLIENTE": "CLIENTE GRAVADO POR FORA", "TIPO": "Cliente", "VENDEDOR": "Vendedor Exemplo"})
            assert ficha._lista.linha_do_cpf(cpf_novo) is None, "antes de voltar pra tela, ela ainda mostra a leitura antiga"
            _ir(janela, PAGINA_FICHA)
            assert ficha._busca.text() == "" and ficha._lista.linha_do_cpf(cpf_novo) is not None
            print("OK: voltando pra Ficha, o cliente novo ja esta na lista (sem digitar nada na busca).")

            # ------------------------------------------------------------------------------------
            linha("2) Sem mudanca no arquivo, trocar de pagina NAO rele (continua instantaneo)")
            for chave in (PAGINA_PROPOSTAS, PAGINA_ADMINISTRACAO, PAGINA_DASHBOARD, PAGINA_FICHA):
                _ir(janela, chave)  # cada tela ve (uma vez, com razao) a mudanca do passo 1
            buscas = _Contador(clientes_mod, "buscar")
            recargas = [_Contador(propostas, "_carregar_dados"), _Contador(dashboard, "_carregar_dados"),
                        _Contador(adm, "_carregar_vendedores")]
            try:
                for chave in (PAGINA_DASHBOARD, PAGINA_FICHA, PAGINA_PROPOSTAS, PAGINA_ADMINISTRACAO, PAGINA_FICHA, PAGINA_DASHBOARD):
                    _ir(janela, chave)
                assert buscas.vezes == 0, f"a Ficha releu {buscas.vezes}x sem o arquivo ter mudado"
                assert [c.vezes for c in recargas] == [0, 0, 0], f"recargas sem o arquivo ter mudado: {[c.vezes for c in recargas]}"
            finally:
                buscas.desfazer()
                for c in recargas:
                    c.desfazer()
            print("OK: nada mudou -> nenhuma releitura ao trocar de pagina.")

            # ------------------------------------------------------------------------------------
            linha("3) Ficha ABERTA: relida se esta so em leitura; intocada se esta em edicao")
            _ir(janela, PAGINA_FICHA)
            ficha._mostrar_cliente(cpf_novo)
            assert ficha._campo_nome.text() == "CLIENTE GRAVADO POR FORA"
            _ir(janela, PAGINA_DASHBOARD)
            _renomear_por_fora(cpf_novo, "NOME MUDADO POR FORA")
            _ir(janela, PAGINA_FICHA)
            assert ficha._campo_nome.text() == "NOME MUDADO POR FORA", ficha._campo_nome.text()
            print("OK: a ficha aberta (so leitura) mostra o nome novo ao voltar.")

            ficha._aplicar_modo_edicao_cliente(leitura=False)
            ficha._campo_nome.setText("DIGITANDO AQUI")
            _ir(janela, PAGINA_DASHBOARD)
            _renomear_por_fora(cpf_novo, "OUTRO NOME POR FORA")
            _ir(janela, PAGINA_FICHA)
            assert ficha._campo_nome.text() == "DIGITANDO AQUI", "quem esta editando nao perde o que digitou"
            assert not ficha._modo_leitura_cliente, "e continua em edicao"
            assert ficha._lista.linha_do_cpf(cpf_novo) is not None, "a lista em volta foi atualizada mesmo assim"
            ficha._aplicar_modo_edicao_cliente(leitura=True)
            print("OK: com a ficha em edicao, nada do que foi digitado e perdido (so a lista em volta e relida).")

            # ------------------------------------------------------------------------------------
            linha("4) Todas as Propostas: proposta gravada por fora aparece; card em edicao nao e atropelado")
            _ir(janela, PAGINA_PROPOSTAS)
            antes = len(propostas._todas)
            _ir(janela, PAGINA_DASHBOARD)
            propostas_mod.adicionar_proposta({"CPF": cpf_novo, "STATUS": propostas_mod.STATUS_EM_ANALISE, "BANCO": "Banco Exemplo",
                                              "EQUIPAMENTO": "Equipamento Modelo X", "VALOR (R$)": 1234})
            _ir(janela, PAGINA_PROPOSTAS)
            assert len(propostas._todas) == antes + 1
            print("OK: voltando pra Todas as Propostas, a proposta nova ja esta la.")

            _ir(janela, PAGINA_DASHBOARD)
            propostas_mod.adicionar_proposta({"CPF": cpf_novo, "STATUS": propostas_mod.STATUS_EM_ANALISE, "BANCO": "Banco Exemplo",
                                              "EQUIPAMENTO": "Equipamento Modelo Y", "VALOR (R$)": 999})
            original = propostas._expansor.tem_alteracoes
            propostas._expansor.tem_alteracoes = lambda: True  # um card com edicao nao salva
            try:
                _ir(janela, PAGINA_PROPOSTAS)
                assert len(propostas._todas) == antes + 1, "com edicao pendente, nao rele (o botao Atualizar pergunta)"
            finally:
                propostas._expansor.tem_alteracoes = original
            _ir(janela, PAGINA_DASHBOARD)
            _ir(janela, PAGINA_PROPOSTAS)
            assert len(propostas._todas) == antes + 2, "sem a edicao pendente, a proxima volta rele"
            print("OK: com um card em edicao nao rele; na volta seguinte (sem edicao), rele.")

            # ------------------------------------------------------------------------------------
            linha("5) Dashboard e Administracao tambem acompanham o arquivo")
            _ir(janela, PAGINA_DASHBOARD)
            antes = len(dashboard._propostas)
            _ir(janela, PAGINA_FICHA)
            propostas_mod.adicionar_proposta({"CPF": cpf_novo, "STATUS": propostas_mod.STATUS_APROVADO, "BANCO": "Banco Exemplo",
                                              "EQUIPAMENTO": "Equipamento Modelo X", "VALOR (R$)": 5000})
            _ir(janela, PAGINA_DASHBOARD)
            assert len(dashboard._propostas) == antes + 1
            print("OK: o Dashboard rele ao aparecer se o arquivo mudou.")

            _ir(janela, PAGINA_ADMINISTRACAO)
            _ir(janela, PAGINA_DASHBOARD)
            vendedores_mod.adicionar_vendedor("Vendedora Gravada Por Fora")
            _ir(janela, PAGINA_ADMINISTRACAO)
            nomes = list(adm._modelo_vendedores._df.iloc[:, 0]) if hasattr(adm._modelo_vendedores, "_df") else None
            if nomes is None:
                nomes = [adm._modelo_vendedores.data(adm._modelo_vendedores.index(i, 0)) for i in range(adm._modelo_vendedores.rowCount())]
            assert "Vendedora Gravada Por Fora" in nomes, nomes
            print("OK: a Administracao mostra o vendedor novo ao aparecer.")

            # ------------------------------------------------------------------------------------
            linha("6) VENDEDOR le do Google, nao do arquivo: o vigia nunca pede releitura")
            vigia = VigiaDoArquivo()
            sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_VENDEDOR, nome_usuario="Vendedor Exemplo"))
            assert vigia.mudou_desde_a_leitura() is False
            sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
            assert vigia.mudou_desde_a_leitura() is True, "admin que nunca leu: precisa ler"
            vigia.registrar_leitura()
            assert vigia.mudou_desde_a_leitura() is False
            print("OK: vendedor -> nunca; admin -> so quando o arquivo mudou desde a leitura.")

            # ------------------------------------------------------------------------------------
            linha("7) Botao 'Recarregar' (antes 'Atualizar'): nas 3 telas, e o da Ficha respeita quem edita")
            from PySide6.QtWidgets import QMessageBox, QPushButton

            from desktop.widgets.botao_recarregar import DICA

            assert not [b for b in janela.findChildren(QPushButton) if b.text() == "Atualizar"], "nao sobrou botao 'Atualizar'"
            for tela in (dashboard, propostas, ficha):
                botoes = [b for b in tela.findChildren(QPushButton) if b.text() == "Recarregar"]
                assert len(botoes) == 1 and botoes[0].toolTip() == DICA and "nuvem" in DICA, type(tela).__name__
            botao_ficha = ficha._botao_recarregar
            print("OK: Dashboard, Todas as Propostas e Ficha tem 'Recarregar' (com a dica 'nao mexe na nuvem').")

            _ir(janela, PAGINA_PROPOSTAS)
            antes = len(propostas._todas)
            propostas_mod.adicionar_proposta({"CPF": cpf_novo, "STATUS": propostas_mod.STATUS_EM_ANALISE, "BANCO": "Banco Exemplo",
                                              "EQUIPAMENTO": "Equipamento Modelo X", "VALOR (R$)": 777})
            [b for b in propostas.findChildren(QPushButton) if b.text() == "Recarregar"][0].click()
            assert len(propostas._todas) == antes + 1
            print("OK: 'Recarregar' em Todas as Propostas rele na hora, sem trocar de pagina.")

            _ir(janela, PAGINA_FICHA)
            ficha._mostrar_cliente(cpf_novo)
            cpf_2 = fx.cpf_ficticio(500_000_002)
            clientes_mod.adicionar_cliente({"CPF/CNPJ": cpf_2, "CLIENTE": "OUTRO POR FORA", "TIPO": "Cliente", "VENDEDOR": "Vendedor Exemplo"})
            _renomear_por_fora(cpf_novo, "RENOMEADO ENQUANTO ABERTA")
            msgs.limpar()
            botao_ficha.click()
            assert ficha._lista.linha_do_cpf(cpf_2) is not None and ficha._campo_nome.text() == "RENOMEADO ENQUANTO ABERTA"
            assert not [m for m in msgs.registro if m[0] == "question"], "sem edicao, nao pergunta nada"
            print("OK: sem edicao, 'Recarregar' rele a lista e a ficha aberta, sem trocar de pagina e sem perguntar.")

            ficha._aplicar_modo_edicao_cliente(leitura=False)
            ficha._campo_nome.setText("DIGITADO E NAO SALVO")
            _renomear_por_fora(cpf_novo, "NOME NO DISCO")
            msgs.limpar(); msgs.resposta_pergunta = QMessageBox.StandardButton.No
            botao_ficha.click()
            assert msgs.ultima()[0] == "question" and "não foram salvas" in msgs.ultima()[2]
            assert ficha._campo_nome.text() == "DIGITADO E NAO SALVO" and not ficha._modo_leitura_cliente
            print("OK: em edicao, pergunta; respondendo 'Nao', nada muda (o que foi digitado fica).")

            msgs.limpar(); msgs.resposta_pergunta = QMessageBox.StandardButton.Yes
            botao_ficha.click()
            assert ficha._modo_leitura_cliente and ficha._campo_nome.text() == "NOME NO DISCO"
            print("OK: respondendo 'Sim', descarta a edicao e mostra o que esta no disco (em leitura).")

            ficha._iniciar_novo_cliente()
            assert ficha._modo_novo_cliente
            msgs.limpar(); msgs.resposta_pergunta = QMessageBox.StandardButton.Yes
            botao_ficha.click()
            assert not ficha._modo_novo_cliente and ficha._painel_stack.currentIndex() == 0
            print("OK: cliente novo nao salvo + 'Sim': o rascunho sai e a ficha volta pra pagina vazia.")

            msgs.exigir_sem_erros("trocando de pagina")
        linha("TUDO OK")
    finally:
        amb.encerrar()
        depois = sorted(p.name for p in config.DIRETORIO_DADOS.glob("*")) if config.DIRETORIO_DADOS.exists() else []
        assert depois == listagem_real, f"o teste mexeu na pasta de dados real: {set(depois) ^ set(listagem_real)}"


if __name__ == "__main__":
    main()
