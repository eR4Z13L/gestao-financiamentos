"""Testa a tela do resumo para o WhatsApp (plano 1.5-B): o botao "Resumo por vendedor" da tela Vendas, o dialogo
(vendedor, sugestoes de periodo que preenchem as datas de/ate, datas livres, caixinhas dos blocos, previa e Copiar) e o
link "Copiar resumo da venda" do card aberto. O texto em si e de core/resumo_vendas.py (smoke_test_resumo_vendas.py).

Planilha 100% ficticia em pasta temporaria, preferencias isoladas e o Google desligado. Nada e gravado.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_resumo_tela.py
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False
import fixture_ficticia as fx
from ambiente_de_teste import Mensagens
from core import bancos as bancos_mod
from core import clientes as clientes_mod
from core import vendedores as vendedores_mod
from core import data_store_sheets as nuvem
from core import propostas as propostas_mod
from core import resumo_vendas as resumo_mod
from core import sessao as sessao_mod
from core import sheets_sync
from core import vendas as v
from desktop.dialogs.resumo_vendedor_dialog import PERSONALIZADO, TODOS, ResumoPorVendedorDialog
from desktop.screens import vendas_screen as tela_mod
from desktop.theme import TEMA_ESCURO, build_stylesheet

ADMIN = sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador")
APROVADO = propostas_mod.STATUS_APROVADO


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _processar() -> None:
    for _ in range(4):
        QApplication.processEvents()


def main() -> None:
    def _sem_rede(*_a, **_k):
        raise AssertionError("o teste tentou acessar o Google de verdade")

    rede_original = (nuvem._obter_cliente, sheets_sync._obter_cliente)
    nuvem._obter_cliente = sheets_sync._obter_cliente = _sem_rede
    pasta = Path(tempfile.mkdtemp(prefix="_smoke_resumo_tela_"))
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
            id_a, p_a = v.criar_venda(fx.CPF_MARIA, ["Cadeira Exemplo"],
                                      {"BANCO": b1, "VALOR (R$)": 30000, "MESES": 36, "EQUIPAMENTO": "Cadeira Exemplo"})
            v.mudar_status_proposta(p_a, APROVADO)
            v.fechar_proposta(p_a)
            v.adicionar_pendencia(id_a, "Equipamento ainda não chegou")
            v.editar_venda(id_a, ["Cadeira Exemplo"], "observação que não vai para o resumo")
            id_b, _ = v.criar_venda(fx.CPF_JOAO, ["Laser Exemplo"],
                                    {"BANCO": b2, "VALOR (R$)": 52000, "MESES": 48, "EQUIPAMENTO": "Laser Exemplo"})
            # uma venda de um cliente de OUTRO vendedor (uma so) e um vendedor sem nenhuma venda
            vendedores_mod.adicionar_vendedor("Vendedor Sem Vendas")
            cpf_c = fx.cpf_ficticio(700_000_001)
            clientes_mod.adicionar_cliente({"CPF/CNPJ": cpf_c, "CLIENTE": "CLIENTE UNICO", "TIPO": "Cliente",
                                            "VENDEDOR": "Vendedora Teste Dois"})
            id_c, _ = v.criar_venda(cpf_c, ["Mesa Exemplo"], {"BANCO": b1, "VALOR (R$)": 9000, "MESES": 24, "EQUIPAMENTO": "Mesa Exemplo"})
            hash_antes = hashlib.sha256(caminho.read_bytes()).hexdigest()
            hoje = date.today()
            segunda = hoje - timedelta(days=hoje.weekday())

            linha("1) O botao na tela Vendas abre o dialogo: Todos, Esta semana, datas preenchidas, todos os blocos")
            tela = tela_mod.VendasScreen()
            tela.resize(1100, 760)
            tela.show()
            _processar()
            assert tela.botao_resumo.text() == "Resumo por vendedor" and tela.botao_nova.text() == "+ Nova venda"
            assert tela.botao_resumo.isVisible() and tela.botao_resumo.isEnabled()
            mostrados = []
            tela._mostrar_dialogo = mostrados.append  # (o exec() bloquearia o teste)
            tela.botao_resumo.click()
            assert len(mostrados) == 1 and mostrados[0] is tela.dialogo_resumo
            d = mostrados[0]
            assert d.vendedor.currentText() == TODOS and d.vendedor.currentData() is None
            assert {d.vendedor.itemText(i) for i in range(d.vendedor.count())} >= {TODOS, "Vendedora Teste Dois"}
            assert d.sugestao.currentText() == "Esta semana"
            assert [d.sugestao.itemText(i) for i in range(d.sugestao.count())] == [
                "Esta semana", "Semana passada", "Esta quinzena", "Quinzena passada", "Este mês", "Mês passado", PERSONALIZADO]
            assert (d.de.date().toPython(), d.ate.date().toPython()) == (segunda, segunda + timedelta(days=6))
            assert d.de.displayFormat() == "dd/MM/yyyy" and d.de.calendarPopup() and d.ate.calendarPopup()
            assert list(d.caixas) == list(resumo_mod.BLOCOS) and all(c.isChecked() for c in d.caixas.values())
            assert [c.text() for c in d.caixas.values()] == ["Efetivadas", "Aprovadas", "Em análise", "Negadas",
                                                             "Não efetivadas", "Pendências"]
            texto = d.previa.toPlainText()
            assert texto.splitlines()[0] == "*Resumo da semana — Todos os vendedores*", texto
            assert texto.splitlines()[1].endswith("· 3 vendas") and "Pendências em aberto:" in texto
            assert "observação que não vai" not in texto, "observações não entram"
            assert d.previa.isReadOnly() and d.botao_copiar.isEnabled() and d.botao_copiar.text() == "Copiar resumo"
            print("OK: botão ao lado de + Nova venda; dialogo com Todos, Esta semana, datas e blocos marcados; prévia na hora.")

            linha("2) Copiar: o texto da prévia vai para a area de transferencia, com o aviso 'Resumo copiado (N vendas)'")
            QApplication.clipboard().setText("antes")
            assert d.copiar() is True
            assert QApplication.clipboard().text() == texto
            assert d.aviso.text() == "Resumo copiado (3 vendas)."
            print("OK: copiado, com o aviso.")

            linha("3) As sugestoes preenchem as datas; editar uma data vira 'Personalizado'; de depois de ate avisa")
            mes_passado = resumo_mod.periodo(resumo_mod.MES, resumo_mod.ANTERIOR, hoje)
            d.sugestao.setCurrentText("Mês passado")
            assert (d.de.date().toPython(), d.ate.date().toPython()) == (mes_passado.inicio, mes_passado.fim)
            assert d.previa.toPlainText() == "Nenhuma venda no mês passado" and not d.botao_copiar.isEnabled()
            QApplication.clipboard().setText("intacto")
            assert d.copiar() is False and QApplication.clipboard().text() == "intacto", "sem vendas, nada copia"
            d.sugestao.setCurrentText("Esta quinzena")
            quinzena = resumo_mod.periodo(resumo_mod.QUINZENA, resumo_mod.ATUAL, hoje)
            assert (d.de.date().toPython(), d.ate.date().toPython()) == (quinzena.inicio, quinzena.fim)
            assert d.sugestao.currentText() == "Esta quinzena", "preencher as datas nao muda a sugestao escolhida"
            assert d.previa.toPlainText().splitlines()[0] == "*Resumo da quinzena — Todos os vendedores*"
            d.de.setDate(QDate(hoje.year, hoje.month, hoje.day))  # so uma das datas muda: personalizado
            d.ate.setDate(QDate(hoje.year, hoje.month, hoje.day))
            assert d.sugestao.currentText() == PERSONALIZADO
            assert d.previa.toPlainText().splitlines()[:2] == [
                "*Resumo do período — Todos os vendedores*", f"{hoje:%d/%m} a {hoje:%d/%m/%Y} · 3 vendas"], d.previa.toPlainText()
            d.ate.setDate(QDate(hoje.year, hoje.month, hoje.day).addDays(-3))  # ate antes de de
            assert d.previa.toPlainText() == "O período começa depois de terminar." and not d.botao_copiar.isEnabled()
            d.ate.setDate(QDate(hoje.year, hoje.month, hoje.day))
            d.sugestao.setCurrentText("Esta semana")  # as sugestoes refazem as datas
            assert (d.de.date().toPython(), d.ate.date().toPython()) == (segunda, segunda + timedelta(days=6))
            # escolher "Personalizado" a mao nao mexe nas datas
            d.sugestao.setCurrentText(PERSONALIZADO)
            assert (d.de.date().toPython(), d.ate.date().toPython()) == (segunda, segunda + timedelta(days=6))
            d.sugestao.setCurrentText("Esta semana")
            print("OK: sugestões preenchem de/até; editar vira Personalizado; de depois de até avisa e desliga o Copiar.")

            linha("4) As caixinhas dos blocos: so os marcados entram; nenhum marcado desliga o Copiar")
            d.caixas[resumo_mod.PENDENCIAS].setChecked(False)
            assert "Pendências" not in d.previa.toPlainText() and d.botao_copiar.isEnabled()
            d.caixas[resumo_mod.APROVADAS].setChecked(False)
            sem_aprovadas = d.previa.toPlainText()
            assert "*Aprovadas" not in sem_aprovadas and "*Em análise (2)*" in sem_aprovadas
            for bloco, caixa in d.caixas.items():
                caixa.setChecked(False)
            assert d.previa.toPlainText() == "Marque pelo menos um bloco para o resumo." and not d.botao_copiar.isEnabled()
            assert d.blocos_marcados() == []
            d.caixas[resumo_mod.NEGADAS].setChecked(True)
            assert d.previa.toPlainText().endswith("Nada nos blocos escolhidos neste período.")
            for caixa in d.caixas.values():
                caixa.setChecked(True)
            assert d.blocos_marcados() == list(resumo_mod.BLOCOS) and "Pendências" in d.previa.toPlainText()
            print("OK: só os blocos marcados entram na prévia; nenhum marcado avisa e desliga o Copiar.")

            linha("5) O vendedor: so as vendas dele")
            dona = "Vendedora Teste Dois"
            d.vendedor.setCurrentText(dona)
            assert d.previa.toPlainText().splitlines()[0] == f"*Resumo da semana — {dona}*" and d.botao_copiar.isEnabled()
            assert d.copiar(), d.previa.toPlainText()
            assert d.aviso.text() == "Resumo copiado (1 venda).", d.aviso.text()
            outro = "Vendedor Sem Vendas"
            d.vendedor.setCurrentText(outro)
            assert d.previa.toPlainText() == f"Nenhuma venda de {outro} nesta semana" and not d.botao_copiar.isEnabled()
            d.vendedor.setCurrentText(TODOS)
            assert d.previa.toPlainText().splitlines()[0] == "*Resumo da semana — Todos os vendedores*"
            print("OK: o vendedor muda a prévia.")

            linha("6) 'Copiar resumo da venda' no card aberto (so no aberto)")
            tela.filtro.setCurrentText(tela_mod.FILTRO_TODAS)
            tela.carregar()
            _processar()
            fechado = next(c for c in tela.lista.cards if c.venda.id == id_a)
            assert fechado.copiar_resumo is None, "o link fica no rodapé do card aberto"
            tela.lista.abrir_venda(fechado.venda)
            _processar()
            card = next(c for c in tela.lista.cards if c.venda.id == id_a)
            assert card.aberto and card.copiar_resumo is not None and card.copiar_resumo.text() == "Copiar resumo da venda"
            rodape = [b.text() for b in (card.adicionar, card.editar_venda, card.nova_pendencia, card.copiar_resumo, card.abrir_ficha)]
            assert rodape == ["+ Adicionar proposta", "Editar a venda", "+ Pendência", "Copiar resumo da venda", "Abrir a ficha"]
            QApplication.clipboard().setText("antes")
            card.copiar_resumo.click()
            _processar()
            esperado = resumo_mod.texto_da_venda(id_a)
            assert QApplication.clipboard().text() == esperado
            assert esperado.splitlines()[0].startswith("*Venda de ") and "Pendências em aberto:" in esperado
            assert "• Equipamento ainda não chegou" in esperado and "observação" not in esperado and "Obs" not in esperado
            assert "resumo copiado" in tela.texto_aviso.text() and not tela.faixa_aviso.isHidden()
            msgs.exigir_sem_erros("copiar o resumo da venda")
            # a venda sumiu entre a leitura e o clique: mensagem, nada copiado
            QApplication.clipboard().setText("intacto")
            card.venda = card.venda.__class__(**{**card.venda.__dict__, "id": "V-nao-existe"})
            tela.lista.controle.copiar_resumo_da_venda(card.venda)
            assert "Venda não encontrada" in msgs.ultima()[2] and QApplication.clipboard().text() == "intacto"
            print("OK: o link só existe no card aberto; copia o resumo da venda (sem observação) e avisa; venda que sumiu: mensagem.")

            linha("7) Nada foi gravado")
            assert hashlib.sha256(caminho.read_bytes()).hexdigest() == hash_antes, "o resumo mexeu na planilha"
            assert id_b
            print("OK")
            linha("TUDO OK")
    finally:
        nuvem._obter_cliente, sheets_sync._obter_cliente = rede_original
        fx.restaurar_modulos()
        sessao_mod.encerrar()
        assert fx.instantaneo_do_registro() == registro_antes, "o teste mexeu nas preferencias REAIS do app"


if __name__ == "__main__":
    main()
