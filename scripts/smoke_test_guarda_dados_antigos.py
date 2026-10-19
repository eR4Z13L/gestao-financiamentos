"""Testa o que sobrou do jeito antigo depois da conversao (plano 1.3, parte B): o aviso ao abrir quando a planilha ainda
tem proposta sem venda ou com status fora da lista oficial (o app abre assim mesmo e mostra essas propostas como
estao), o aviso que some depois da conversao, o VENDEDOR sem o aviso, o erro de leitura avisado (nunca em silencio) e
as pecas do jeito antigo que saíram da tela ("Juntar em vendas…", "sem venda", o dialogo de encerrar, o excluir das
antigas, os status antigos nas listas do formulario).

Planilha 100% ficticia em pasta temporaria, preferencias isoladas e o Google desligado (qualquer acesso derruba).

Rodar com: venv/Scripts/python.exe scripts/smoke_test_guarda_dados_antigos.py
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
from PySide6.QtWidgets import QApplication, QPushButton

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
import fixture_ficticia as fx
from ambiente_de_teste import Ambiente, Mensagens
from core import data_store as bd
from core import migracao_legado as leg
from core import propostas as propostas_mod
from core import vendas as vendas_mod
from desktop import main as main_mod
from desktop.main_window import PAGINA_PROPOSTAS
from desktop.theme import TEMA_ESCURO
from desktop.widgets.card_da_proposta import CardDaProposta
from desktop.widgets.formulario_proposta import FormularioProposta

STATUS_ANTIGOS = ["Garantia Assinada", "Encerrada", "Nota Fiscal Anexada"]


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


class _AppFalso:
    def quit(self) -> None:
        pass


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    with Mensagens() as msgs:
        amb = Ambiente()
        try:
            caminho = amb.caminho
            amb.entrar_como("admin")

            linha("1) Contar o que ainda esta do jeito antigo (core)")
            total = len(bd.ler_propostas(caminho))
            antes = leg.contar_dados_antigos(caminho)
            assert antes.sem_venda == total and antes.status_fora_da_lista == 0 and bool(antes)
            for i, status in enumerate(STATUS_ANTIGOS):
                propostas_mod.adicionar_proposta({
                    "CPF": fx.CPF_MARIA, "DATA": pd.Timestamp(2026, 3, 1 + i), "VALOR (R$)": 1000 + i, "MESES": 12,
                    "EQUIPAMENTO": f"Equipamento Antigo {i}", "BANCO": "Banco Exemplo", "STATUS": status,
                })
            antes = leg.contar_dados_antigos(caminho)
            assert (antes.sem_venda, antes.status_fora_da_lista) == (total + 3, 3), antes
            texto = antes.texto()
            assert f"{total + 3} proposta(s) que não estão em nenhuma venda" in texto
            assert "3 proposta(s) com status fora da lista do app" in texto and "converter_legado.py" in texto
            vazio = leg.DadosAntigos(0, 0)
            assert not vazio
            print(f"OK: {total + 3} sem venda e 3 com status fora da lista; o texto diz quantas são e que falta a conversão.")

            linha("2) Ao abrir como ADMIN: avisa, e o app abre assim mesmo (as propostas aparecem como estão)")
            janela = amb.nova_janela("admin", TEMA_ESCURO)
            msgs.limpar()
            assert janela.avisar_dados_antigos() is True
            tipo, titulo, corpo = msgs.ultima()
            assert tipo == "warning" and "versão antiga" in titulo
            assert str(total + 3) in corpo and "conversão" in corpo, corpo
            janela.ir_para(PAGINA_PROPOSTAS)
            tela = janela._tela_propostas
            assert tela.lista.total() == total + 3, "as propostas sem venda continuam em Todas as Propostas"
            status_na_lista = {i.proposta.status for i in tela.propostas_visiveis()}
            assert set(STATUS_ANTIGOS) <= status_na_lista, "com o status como está"
            assert "3 com status não reconhecido" in tela._contador.text(), tela._contador.text()
            opcoes = [tela._filtro_status.itemText(i) for i in range(tela._filtro_status.count())]
            assert not set(STATUS_ANTIGOS) & set(opcoes), "o filtro Resposta não oferece os valores crus da planilha"
            print("OK: o aviso diz quantas são; a tela abre e lista as propostas com o status como está (contadas como "
                  "'status não reconhecido'); o filtro Resposta só tem os oficiais.")

            linha("3) A abertura do app (ControladorDaJanela.abrir) chama a guarda")
            msgs.limpar()
            controlador = main_mod.ControladorDaJanela(_AppFalso())
            assert controlador.abrir() is True
            amb.janelas.append(controlador.janela)
            assert [m[1] for m in msgs.registro if m[0] == "warning"] == ["Dados de uma versão antiga"], msgs.registro
            print("OK: ao abrir o app, o aviso aparece uma vez.")

            linha("4) Erro ao conferir: avisa (nunca em silêncio) e o app continua")
            original = leg.contar_dados_antigos
            leg.contar_dados_antigos = lambda _c: (_ for _ in ()).throw(RuntimeError("planilha ilegível de teste"))
            try:
                msgs.limpar()
                with fx.capturar_log("desktop.main_window") as log:
                    assert janela.avisar_dados_antigos() is False
                tipo, titulo, corpo = msgs.ultima()
                assert tipo == "warning" and "Não foi possível conferir" in titulo and "planilha ilegível de teste" in corpo
                assert log.avisos_com_traceback(), "e a falha vai para o log, com o detalhe"
            finally:
                leg.contar_dados_antigos = original
            print("OK: se a conferência falha, a mensagem diz o motivo e devolve False.")

            linha("5) O VENDEDOR não tem o arquivo local: sem aviso")
            vendedor = amb.nova_janela("vendedor", TEMA_ESCURO)
            msgs.limpar()
            assert vendedor.avisar_dados_antigos() is False
            msgs.exigir_vazio("vendedor")
            amb.entrar_como("admin")
            print("OK: o vendedor não vê o aviso.")

            linha("6) Depois da conversão o aviso some")
            plano = leg.planejar(caminho)
            decisoes = {d.chave: d.opcoes[0] for d in plano.duvidas}
            leg.aplicar(plano, decisoes)
            assert not leg.contar_dados_antigos(caminho)
            janela = amb.nova_janela("admin", TEMA_ESCURO)
            msgs.limpar()
            assert janela.avisar_dados_antigos() is False
            msgs.exigir_vazio("convertida")
            print("OK: planilha convertida: nada a avisar.")

            linha("7) O que saiu do jeito antigo")
            for modulo in ("desktop.widgets.encerrar_propostas_da_venda", "desktop.widgets.exclusao_proposta",
                           "desktop.dialogs.organizar_vendas_dialog"):
                assert importlib.util.find_spec(modulo) is None, f"{modulo} deveria ter saído"
            assert not hasattr(propostas_mod, "STATUS_OPCOES") and not hasattr(propostas_mod, "encerrar_propostas")
            assert not hasattr(propostas_mod, "propostas_em_aberto_da_mesma_venda")
            assert not hasattr(vendas_mod, "contar_propostas_sem_venda")
            botoes = [b.text() for b in janela.findChildren(QPushButton)]
            assert not [b for b in botoes if "Juntar em vendas" in b], "nenhum 'Juntar em vendas…' em tela alguma"
            item = vendas_mod.propostas_na_lista(propostas_mod.listar_propostas())
            card = CardDaProposta(next(iter(item.values())))
            assert not hasattr(card, "sem_venda"), "a etiqueta 'sem venda' saiu"
            card.deleteLater()
            assert not hasattr(janela._tela_ficha, "_dica_antigas") and not hasattr(janela._tela_vendas, "aviso_sem_venda")
            print("OK: sem o diálogo de encerrar, o excluir das antigas, o 'Juntar em vendas…', a etiqueta 'sem venda' "
                  "e as funções de 'mesma venda'.")

            linha("8) O formulário não oferece os status antigos, mas mantém o que a proposta tem")
            linha_antiga = {c: None for c in bd.PROPOSTAS_COLUNAS_EDITAVEIS}
            linha_antiga.update({"CPF": fx.CPF_MARIA, "STATUS": "Garantia Assinada", "OBSERVAÇÕES": "", "ID_PROPOSTA": "", "ID_VENDA": "", "BANCO": "Banco Exemplo",
                                 "EQUIPAMENTO": "Equipamento Modelo X", "VALOR (R$)": 1000, "DATA": pd.Timestamp(2026, 3, 1)})
            formulario = FormularioProposta(fx.CPF_MARIA, "MARIA", proposta=linha_antiga, indice=0)
            itens = [formulario._status.itemText(i) for i in range(formulario._status.count())]
            assert itens == ["Garantia Assinada", *vendas_mod.STATUS_DA_PROPOSTA], itens
            assert formulario._status.currentText() == "Garantia Assinada", "nunca troca o status sem o usuário pedir"
            novo = FormularioProposta(fx.CPF_MARIA, "MARIA")
            assert [novo._status.itemText(i) for i in range(novo._status.count())] == vendas_mod.STATUS_DA_PROPOSTA
            formulario.deleteLater()
            novo.deleteLater()
            print("OK: a lista tem as 4 respostas do banco (e o status de agora, se for outro); a proposta nova só as 4.")
            linha("TUDO OK")
        finally:
            amb.encerrar()


if __name__ == "__main__":
    main()
