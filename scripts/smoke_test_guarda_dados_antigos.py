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
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
config.CONFIG_LOCAL_ATIVA = False  # os trechos 1 a 8 valem para a planilha real (sem caixinha); o 4b liga o modo de teste
import fixture_ficticia as fx
from ambiente_de_teste import Ambiente, Mensagens
from core import data_store as bd
from core import migracao_legado as leg
from core import propostas as propostas_mod
from core import vendas as vendas_mod
from desktop import main as main_mod
from desktop import settings as settings_mod
from desktop.main_window import PAGINA_PROPOSTAS, PASTAS_COM_DADOS_REAIS
from desktop.theme import TEMA_ESCURO
from desktop.widgets.card_da_proposta import CardDaProposta
from desktop.widgets.formulario_proposta import FormularioProposta

STATUS_ANTIGOS = ["Garantia Assinada", "Encerrada", "Nota Fiscal Anexada"]


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


class _AppFalso:
    def quit(self) -> None:
        pass


def _exec_proibido(self) -> int:
    # QMessageBox.exec bloqueia o teste para sempre: so a caixa da 4b (trocada ali) pode abrir; qualquer outra e erro
    raise AssertionError(f"abriu uma caixa bloqueante no teste: {self.windowTitle()!r}")


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    exec_de_verdade = QMessageBox.exec
    QMessageBox.exec = _exec_proibido
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

            linha("4b) Planilha de teste (config local): caixinha 'Não avisar de novo', por caminho da planilha")
            exec_original = QMessageBox.exec
            exibidos: list[tuple[str, str, bool]] = []  # (titulo, texto, tinha_caixinha)
            marcar = [False]

            def _exec_falso(self) -> int:
                caixinha = self.checkBox()
                exibidos.append((self.windowTitle(), self.text(), caixinha is not None))
                if caixinha is not None and marcar[0]:
                    caixinha.setChecked(True)
                return int(QMessageBox.StandardButton.Ok)

            QMessageBox.exec = _exec_falso
            try:
                # modo real: sem caixinha, avisa sempre (e nunca grava a preferencia)
                config.CONFIG_LOCAL_ATIVA = False
                marcar[0] = True
                msgs.limpar()
                for _ in range(2):
                    assert janela.avisar_dados_antigos() is True
                assert [m[1] for m in msgs.registro] == ["Dados de uma versão antiga"] * 2 and not exibidos
                assert not settings_mod.obter_sem_aviso_dados_antigos(caminho), "o modo real nunca silencia"
                # modo de teste, sem marcar: avisa de novo
                config.CONFIG_LOCAL_ATIVA = True
                marcar[0] = False
                msgs.limpar()
                for _ in range(2):
                    assert janela.avisar_dados_antigos() is True
                assert len(exibidos) == 2 and all(e[2] and "versão antiga" in e[0] for e in exibidos), exibidos
                assert not msgs.registro and not settings_mod.obter_sem_aviso_dados_antigos(caminho)
                # modo de teste, marcando: avisa essa vez e nunca mais naquele caminho
                exibidos.clear()
                marcar[0] = True
                assert janela.avisar_dados_antigos() is True and len(exibidos) == 1
                assert exibidos[0][2] and str(total + 3) in exibidos[0][1]
                assert settings_mod.obter_sem_aviso_dados_antigos(caminho)
                assert janela.avisar_dados_antigos() is False and len(exibidos) == 1, "marcou: não avisa mais"
                assert amb.nova_janela("admin", TEMA_ESCURO).avisar_dados_antigos() is False, "vale para a janela seguinte"
                # a escolha é por caminho: outra planilha continua avisando
                outro = caminho.with_name("outra_planilha.dat")
                assert not settings_mod.obter_sem_aviso_dados_antigos(outro)
                original_caminho = propostas_mod.CAMINHO_XLSX
                propostas_mod.CAMINHO_XLSX = outro
                try:
                    leg_original = leg.contar_dados_antigos
                    leg.contar_dados_antigos = lambda _c: leg.DadosAntigos(2, 0)
                    try:
                        marcar[0] = False
                        assert janela.avisar_dados_antigos() is True and len(exibidos) == 2
                    finally:
                        leg.contar_dados_antigos = leg_original
                finally:
                    propostas_mod.CAMINHO_XLSX = original_caminho
                # config local carregado, mas a planilha e a REAL (data/) ou a do dev com Sheets oficial (data_dev_oficial/):
                # dados reais, entao sem caixinha (e nada se grava); outra pasta (data_teste/) continua com a caixinha
                config.CONFIG_LOCAL_ATIVA = True
                raiz = Path(config.__file__).resolve().parent
                original_caminho = propostas_mod.CAMINHO_XLSX
                leg_original = leg.contar_dados_antigos
                leg.contar_dados_antigos = lambda _c: leg.DadosAntigos(2, 0)
                try:
                    assert len(PASTAS_COM_DADOS_REAIS) == 2 and "data" in PASTAS_COM_DADOS_REAIS
                    for pasta in PASTAS_COM_DADOS_REAIS:
                        propostas_mod.CAMINHO_XLSX = raiz / pasta / "controle_financiamentos.dat"
                        exibidos.clear()
                        msgs.limpar()
                        marcar[0] = True
                        assert janela.avisar_dados_antigos() is True, pasta
                        assert not exibidos and len(msgs.registro) == 1 and msgs.registro[0][1] == "Dados de uma versão antiga", pasta
                        assert not settings_mod.obter_sem_aviso_dados_antigos(propostas_mod.CAMINHO_XLSX), pasta
                    propostas_mod.CAMINHO_XLSX = raiz / "data_teste" / "controle_financiamentos_teste.dat"
                    exibidos.clear()
                    marcar[0] = False
                    assert janela.avisar_dados_antigos() is True and len(exibidos) == 1 and exibidos[0][2], "data_teste: caixinha"
                finally:
                    propostas_mod.CAMINHO_XLSX = original_caminho
                    leg.contar_dados_antigos = leg_original
                # em modo real, mesmo com o caminho marcado, o aviso aparece
                config.CONFIG_LOCAL_ATIVA = False
                msgs.limpar()
                assert janela.avisar_dados_antigos() is True and len(msgs.registro) == 1
            finally:
                QMessageBox.exec = exec_original
                config.CONFIG_LOCAL_ATIVA = False
            print("OK: modo de teste -> caixinha; marcada, não avisa mais naquele caminho; sem marcar avisa de novo; "
                  "outro caminho avisa; planilha real sem caixinha e sempre avisando.")

            linha("4c) O flag do config local (config.CONFIG_LOCAL_ATIVA)")
            import shutil
            import subprocess
            import tempfile
            # o config.py numa pasta so dele: sem config_local.py o flag e False; com um config_local.py vazio, True
            with tempfile.TemporaryDirectory() as pasta_flag:
                shutil.copy(Path(config.__file__), pasta_flag)
                for fake, esperado in ((False, "False"), (True, "True")):
                    destino = Path(pasta_flag) / "config_local.py"
                    if fake:
                        destino.write_text("# config local de teste, sem nada dentro\n", encoding="utf-8")
                    saida = subprocess.run([sys.executable, "-c", "import config; print(config.CONFIG_LOCAL_ATIVA)"],
                                           cwd=pasta_flag, capture_output=True, text=True)
                    assert saida.returncode == 0, saida.stderr
                    assert saida.stdout.strip() == esperado, (fake, saida.stdout)
            print("OK: sem config local o flag é False; com o config_local.py carregado é True.")

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
            QMessageBox.exec = exec_de_verdade
            amb.encerrar()


if __name__ == "__main__":
    main()
