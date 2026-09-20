"""Testa a barra lateral da janela principal (desktop/main_window.py e os widgets dela) sem abrir
uma janela de verdade (QT_QPA_PLATFORM=offscreen), no estilo do Windows 11 e nos DOIS temas.

Nada aqui toca em dado real:
- a planilha e uma copia FICTICIA temporaria (scripts/fixture_ficticia.py), nunca data/;
- as preferencias (tema, ultima tela, geometria) vao pra um .ini temporario, e o registro do
  Windows e conferido antes e depois;
- o Google Sheets esta desligado e o acesso ao cliente dele derruba o teste se for tentado.

Cobre: identidade (nome/acesso), botao Sair (com e sem edicao nao salva, e o fluxo de trocar de
usuario), indicador de sincronizacao nos tres estados (+ vendedor), selo de propostas paradas,
ultima tela e geometria lembradas, menu (grupos, teclado, atalhos, icones), "+ Nova proposta",
recolher, e o fundo dos rotulos (regra global de QLabel) + tooltip.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_barra_lateral.py
"""

from __future__ import annotations

import os
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")  # sem tela o Qt nao acha fontes

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from PySide6.QtCore import QByteArray, QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QShortcut
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QToolTip, QVBoxLayout, QWidget

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
import fixture_ficticia as fx
from ambiente_de_teste import Ambiente, Mensagens
from core import data_store as bd
from core import data_store_sheets as leitura_sheets
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import sheets_sync
from desktop import main as main_mod
from desktop import settings as settings_mod
from desktop.main_window import (
    PAGINA_ADMINISTRACAO,
    PAGINA_DASHBOARD,
    PAGINA_FICHA,
    PAGINA_PROPOSTAS,
    MainWindow,
)
from desktop.theme import CORES_STATUS, PALETAS, TEMA_CLARO, TEMA_ESCURO
from desktop.widgets import icones_linha
from desktop.widgets.identidade_usuario import IdentidadeUsuario
from desktop.widgets.indicador_sincronizacao import descrever_leitura, descrever_sincronizacao
from desktop.widgets.menu_lateral import texto_do_selo

TEMAS = (TEMA_ESCURO, TEMA_CLARO)


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


# -- ambiente de teste ------------------------------------------------------------------------


def _contar_pixels(imagem: QImage, cor: QColor, area: QRect, tolerancia: int = 6) -> int:
    """Quantos pixels de `area` tem a cor `cor` (com a tolerancia do antialiasing)."""
    total = 0
    for y in range(max(area.top(), 0), min(area.bottom() + 1, imagem.height())):
        for x in range(max(area.left(), 0), min(area.right() + 1, imagem.width())):
            c = imagem.pixelColor(x, y)
            if (
                abs(c.red() - cor.red()) <= tolerancia
                and abs(c.green() - cor.green()) <= tolerancia
                and abs(c.blue() - cor.blue()) <= tolerancia
            ):
                total += 1
    return total


def _perto(a: QColor, b: QColor, tolerancia: int = 4) -> bool:
    return max(abs(a.red() - b.red()), abs(a.green() - b.green()), abs(a.blue() - b.blue())) <= tolerancia


def _centro_x_do_desenho(widget: QWidget) -> float:
    """O centro horizontal da CAIXA que envolve o que o widget desenhou (os pixels que diferem do fundo,
    o do canto). Amostrar um pixel so nao pega um icone deslocado 1-2 px; a media dos pixels erraria em
    icones assimetricos (lua, porta) - a caixa envolvente e o que "centralizado" quer dizer."""
    imagem = widget.grab().toImage()
    fundo = imagem.pixel(0, 0)
    xs = [x for y in range(imagem.height()) for x in range(imagem.width()) if imagem.pixel(x, y) != fundo]
    assert xs, "o widget nao desenhou nada"
    return (min(xs) + max(xs)) / 2


def _retangulo_do_item(janela: MainWindow, chave: str) -> QRect:
    """O retangulo do item de menu `chave`, em coordenadas da janela."""
    menu = janela._menu
    item = menu._itens_por_chave[chave]
    retangulo = menu.visualItemRect(item)
    return QRect(menu.viewport().mapTo(janela, retangulo.topLeft()), retangulo.size())


# -- testes ---------------------------------------------------------------------------------------


def testar_menu_e_grupos(amb: Ambiente, msgs: Mensagens, tema: str) -> None:
    linha(f"1) Menu, grupos e nomes [{tema}]")
    amb.resetar_preferencias()
    janela = amb.nova_janela("admin", tema)
    menu = janela._menu

    linhas = [(menu.item(i).text(), menu.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(menu.count())]
    assert linhas == [
        ("Visão geral", None),
        ("Dashboard de Propostas", PAGINA_DASHBOARD),
        ("Ficha de Cliente", PAGINA_FICHA),
        ("Todas as Propostas", PAGINA_PROPOSTAS),
        ("Administração", None),
        ("Administração", PAGINA_ADMINISTRACAO),
    ], linhas
    assert all("Usuários" not in texto for texto, _ in linhas), "o item 'Usuários' virou 'Administração'"
    assert menu.item(0).flags() == Qt.ItemFlag.NoItemFlags and menu.item(4).flags() == Qt.ItemFlag.NoItemFlags
    assert "Administração" in janela._tela_administracao.findChildren(QLabel)[0].text(), "o titulo da tela acompanha o menu"
    print("OK: ADMIN ve 2 grupos (Visão geral / Administração), o item se chama 'Administração' e os titulos nao sao selecionaveis.")

    for chave, atalho in ((PAGINA_DASHBOARD, "Ctrl+1"), (PAGINA_FICHA, "Ctrl+2"), (PAGINA_PROPOSTAS, "Ctrl+3"), (PAGINA_ADMINISTRACAO, "Ctrl+4")):
        assert atalho in menu._itens_por_chave[chave].toolTip(), f"o tooltip de {chave} deveria citar {atalho}"
    print("OK: o tooltip de cada item cita o atalho (Ctrl+1..4).")

    vendedor = amb.nova_janela("vendedor", tema)
    linhas_v = [(vendedor._menu.item(i).text(), vendedor._menu.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(vendedor._menu.count())]
    assert linhas_v == [
        ("Dashboard de Propostas", PAGINA_DASHBOARD),
        ("Ficha de Cliente", PAGINA_FICHA),
        ("Todas as Propostas", PAGINA_PROPOSTAS),
    ], linhas_v
    assert PAGINA_ADMINISTRACAO not in vendedor._indice_por_chave and vendedor._botao_nova_proposta is None
    print("OK: VENDEDOR so ve um grupo (sem titulo), sem Administração e sem '+ Nova proposta'.")
    msgs.exigir_vazio("montar o menu")


def testar_navegacao_por_teclado_e_atalhos(amb: Ambiente, msgs: Mensagens, tema: str) -> None:
    linha(f"2) Teclado, clique em titulo e atalhos [{tema}]")
    amb.resetar_preferencias()
    janela = amb.nova_janela("admin", tema)
    menu = janela._menu
    assert janela.chave_atual() == PAGINA_DASHBOARD

    menu.setFocus()
    sequencia = []
    for _ in range(4):
        QTest.keyClick(menu, Qt.Key.Key_Down)
        sequencia.append(janela.chave_atual())
    assert sequencia == [PAGINA_FICHA, PAGINA_PROPOSTAS, PAGINA_ADMINISTRACAO, PAGINA_ADMINISTRACAO], sequencia
    QTest.keyClick(menu, Qt.Key.Key_Up)
    assert janela.chave_atual() == PAGINA_PROPOSTAS
    print("OK: as setas percorrem os itens pulando o titulo do grupo, e o QStackedWidget acompanha.")

    assert janela._paginas.currentWidget() is janela._tela_propostas
    cabecalho = menu.item(0)
    QTest.mouseClick(menu.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, menu.visualItemRect(cabecalho).center())
    assert janela.chave_atual() == PAGINA_PROPOSTAS, "clicar num titulo de grupo nao pode mudar a tela"
    print("OK: clicar no titulo do grupo nao faz nada.")

    janela.ir_para(PAGINA_DASHBOARD)
    for nome_da_tecla, tecla, esperado in (
        ("Ctrl+2", Qt.Key.Key_2, PAGINA_FICHA),
        ("Ctrl+3", Qt.Key.Key_3, PAGINA_PROPOSTAS),
        ("Ctrl+4", Qt.Key.Key_4, PAGINA_ADMINISTRACAO),
        ("Ctrl+1", Qt.Key.Key_1, PAGINA_DASHBOARD),
    ):
        QTest.keyClick(janela, tecla, Qt.KeyboardModifier.ControlModifier)
        assert janela.chave_atual() == esperado, f"{nome_da_tecla} deveria abrir {esperado}, abriu {janela.chave_atual()}"
    print("OK: Ctrl+1..4 abrem as telas na ordem do menu.")

    vendedor = amb.nova_janela("vendedor", tema)
    assert {s.key().toString() for s in vendedor.findChildren(QShortcut)} == {"Ctrl+1", "Ctrl+2", "Ctrl+3"}
    QTest.keyClick(vendedor, Qt.Key.Key_4, Qt.KeyboardModifier.ControlModifier)
    assert vendedor.chave_atual() == PAGINA_DASHBOARD, "VENDEDOR nao tem Ctrl+4 (nao existe Administração pra ele)"
    print("OK: o VENDEDOR so tem Ctrl+1..3.")
    msgs.exigir_vazio("navegar")


def testar_identidade(amb: Ambiente, msgs: Mensagens, tema: str) -> None:
    linha(f"3) Identidade: avatar, nome e acesso [{tema}]")
    janela = amb.nova_janela("admin", tema)
    identidade = janela._identidade
    assert (identidade.nome(), identidade.acesso(), identidade.iniciais()) == ("Administrador", "Acesso total", "A")
    assert identidade.nome() != identidade.acesso(), "nunca a mesma palavra duas vezes (o 'Administrador' repetido de antes)"
    print("OK: ADMIN = 'Administrador' / 'Acesso total', avatar 'A'.")

    # o avatar de fato desenha o circulo na cor de destaque do tema
    imagem = identidade._avatar.grab().toImage()
    esperado = QColor(PALETAS[tema]["destaque"])
    assert _contar_pixels(imagem, esperado, QRect(0, 0, imagem.width(), imagem.height()), 4) > 300, "o avatar deveria ser um circulo na cor de destaque"
    print("OK: o avatar e desenhado na cor de destaque do tema.")

    vendedor = amb.nova_janela("vendedor", tema)
    identidade_v = vendedor._identidade
    assert (identidade_v.nome(), identidade_v.acesso(), identidade_v.iniciais()) == ("Vendedor Exemplo", "Somente leitura", "VE")
    print("OK: VENDEDOR = nome dele / 'Somente leitura', avatar 'VE'.")

    # nome comprido nao estica a barra: elide e guarda o completo no tooltip
    nome_longo = "Fulana de Tal Com Um Sobrenome Absurdamente Comprido Da Silva Sauro"
    largura_util = 230 - 28  # a barra expandida menos as margens do bloco de identidade
    contentor = QWidget()
    contentor.setFixedWidth(largura_util)
    layout_contentor = QVBoxLayout(contentor)
    layout_contentor.setContentsMargins(0, 0, 0, 0)
    comprido = IdentidadeUsuario(nome_longo, "Somente leitura")
    layout_contentor.addWidget(comprido)
    contentor.show()
    QApplication.processEvents()
    rotulo = comprido._rotulo_nome
    assert rotulo.text().endswith("…") and rotulo.toolTip() == nome_longo and rotulo.texto_completo() == nome_longo
    assert rotulo.width() <= largura_util, "o nome nao pode passar da largura da barra"
    assert contentor.minimumSizeHint().width() < largura_util, "o nome comprido nao pode forcar a barra a crescer"
    contentor.hide()
    print("OK: nome comprido vira 'nome…' com o texto inteiro no tooltip, sem esticar a barra.")

    # recolhida: so o avatar, e o tooltip diz quem e
    janela._alternar_sidebar()
    assert janela._menu_recolhido and not identidade.textos_visiveis()
    assert "Administrador" in identidade.toolTip() and "Acesso total" in identidade.toolTip()
    janela._alternar_sidebar()
    assert identidade.textos_visiveis() and identidade.toolTip() == ""
    print("OK: recolhida, so o avatar (nome e acesso vao no tooltip); expandida volta ao normal.")
    amb.resetar_preferencias()
    msgs.exigir_vazio("identidade")


def testar_selo(amb: Ambiente, msgs: Mensagens, tema: str) -> None:
    linha(f"4) Selo de propostas paradas [{tema}]")
    amb.resetar_preferencias()
    janela = amb.nova_janela("admin", tema)
    menu = janela._menu
    assert texto_do_selo(150) == "99+" and texto_do_selo(99) == "99" and texto_do_selo(None) == "" and texto_do_selo(0) == ""
    assert texto_do_selo(5, "algum erro") == "!"

    # a fixture tem 2 propostas em aberto ha mais de 7 dias (12 dias em analise e 20 dias aprovada)
    assert menu.selo(PAGINA_PROPOSTAS) == 2 and menu.texto_do_selo(PAGINA_PROPOSTAS) == "2"
    assert "2 propostas em aberto há mais de 7 dias" in menu._itens_por_chave[PAGINA_PROPOSTAS].toolTip()
    assert menu.selo(PAGINA_DASHBOARD) is None and menu.selo(PAGINA_FICHA) is None, "so Todas as Propostas tem selo"
    print("OK: comeca com o selo '2' (2 propostas paradas na fixture), so no item Todas as Propostas.")

    # o selo e DESENHADO: ha pixels da cor do selo (pilula amber) no item; sem selo nao ha
    cores = CORES_STATUS[tema]["em_analise"]
    area = _retangulo_do_item(janela, PAGINA_PROPOSTAS)
    imagem = janela.grab().toImage()
    lado_direito = QRect(area.center().x(), area.top(), area.width() // 2, area.height())
    assert _contar_pixels(imagem, QColor(cores["fundo"]), lado_direito, 3) > 40, "a pilula do selo nao foi desenhada"
    print("OK: a pilula do selo aparece no lado direito do item.")

    # o limite vem da constante, lida na hora
    original = propostas_mod.DIAS_PROPOSTA_PARADA
    try:
        propostas_mod.DIAS_PROPOSTA_PARADA = 15
        janela._atualizar_selo_propostas()
        assert menu.selo(PAGINA_PROPOSTAS) == 1, "com 15 dias so a de 20 dias conta"
        assert "1 proposta em aberto há mais de 15 dias" in menu._itens_por_chave[PAGINA_PROPOSTAS].toolTip()
        propostas_mod.DIAS_PROPOSTA_PARADA = 30
        janela._atualizar_selo_propostas()
        assert menu.selo(PAGINA_PROPOSTAS) is None
    finally:
        propostas_mod.DIAS_PROPOSTA_PARADA = original
    janela._atualizar_selo_propostas()
    assert menu.selo(PAGINA_PROPOSTAS) == 2
    print("OK: o limite de dias e a constante DIAS_PROPOSTA_PARADA (15 -> 1, 30 -> sem selo, 7 -> 2).")

    # (a) DEPOIS DE GRAVAR em Todas as Propostas: a de 12 dias vira Negado -> sobra 1
    todas = propostas_mod.listar_propostas()
    p12 = int(todas[(todas["STATUS"] == "Em Análise") & (todas["TEMPO"] == "12 dias")].index[0])
    p20 = int(todas[(todas["STATUS"] == "Aprovado") & (todas["TEMPO"] == "20 dias")].index[0])
    janela.ir_para(PAGINA_PROPOSTAS)
    tela = janela._tela_propostas
    tela._expansor.alternar(tela._modelo.linha_do_indice_real(p12))
    formulario = tela._expansor.formulario()
    formulario._habilitar_edicao()
    formulario._status.setCurrentText(propostas_mod.STATUS_NEGADO)
    formulario._salvar()
    assert menu.selo(PAGINA_PROPOSTAS) == 1, "gravar em Todas as Propostas recalcula o selo"
    print("OK: gravar uma proposta em Todas as Propostas recalcula o selo (2 -> 1).")

    # (b) TROCAR DE TELA recalcula: muda o arquivo por fora da tela e o selo acompanha ao trocar
    propostas_mod.atualizar_proposta(p20, {"STATUS": propostas_mod.STATUS_EFETIVADO})
    assert menu.selo(PAGINA_PROPOSTAS) == 1, "nada avisou a janela ainda: continua 1 ate trocar de tela"
    janela.ir_para(PAGINA_FICHA)
    assert menu.selo(PAGINA_PROPOSTAS) is None, "trocar de tela recalcula o selo"
    print("OK: trocar de tela recalcula o selo (1 -> sem selo).")

    # (c) DEPOIS DE GRAVAR na Ficha de Cliente
    novo = propostas_mod.adicionar_proposta(
        {
            "CPF": fx.CPF_ANA,
            "DATA": pd.Timestamp(date.today() - timedelta(days=15)),
            "STATUS": propostas_mod.STATUS_EM_ANALISE,
            "BANCO": "Banco Exemplo",
            "EQUIPAMENTO": "Equipamento Modelo Y",
            "VALOR (R$)": 41000,
            "MESES": 24,
        }
    )
    assert menu.selo(PAGINA_PROPOSTAS) is None
    ficha = janela._tela_ficha
    ficha._selecionar_por_cpf(fx.CPF_ANA)
    ficha._expansor.alternar(ficha._modelo_historico.linha_do_indice_real(novo))
    formulario = ficha._expansor.formulario()
    formulario._habilitar_edicao()
    formulario._observacoes.setPlainText("editado no teste")
    formulario._salvar()
    assert menu.selo(PAGINA_PROPOSTAS) == 1, "gravar na Ficha de Cliente recalcula o selo"
    print("OK: gravar na Ficha de Cliente recalcula o selo (sem selo -> 1).")

    # excluir a proposta (mesma tela) tira o selo de novo
    ficha._expansor.liberar()
    ficha._lista_historico.setCurrentIndex(ficha._modelo_historico.index(ficha._modelo_historico.linha_do_indice_real(novo)))
    ficha._excluir_proposta_selecionada()
    assert menu.selo(PAGINA_PROPOSTAS) is None
    area = _retangulo_do_item(janela, PAGINA_PROPOSTAS)
    imagem = janela.grab().toImage()
    lado_direito = QRect(area.center().x(), area.top(), area.width() // 2, area.height())
    assert _contar_pixels(imagem, QColor(cores["fundo"]), lado_direito, 3) == 0, "sem selo nao pode sobrar a pilula"
    print("OK: excluir a proposta tira o selo e a pilula some do desenho.")

    # erro na contagem: "!" com o motivo, nunca sumir em silencio; e limpa quando volta a funcionar
    original_listar = propostas_mod.listar_propostas

    def _falha():
        raise RuntimeError("arquivo bloqueado (falso)")

    propostas_mod.listar_propostas = _falha
    try:
        with fx.capturar_log("desktop.main_window") as log:
            janela._atualizar_selo_propostas()
        assert "arquivo bloqueado (falso)" in menu.selo_erro(PAGINA_PROPOSTAS)
        assert menu.texto_do_selo(PAGINA_PROPOSTAS) == "!"
        assert "arquivo bloqueado (falso)" in menu._itens_por_chave[PAGINA_PROPOSTAS].toolTip()
        assert len(log.avisos_com_traceback()) == 1, "a falha da contagem tem que ir pro log"
    finally:
        propostas_mod.listar_propostas = original_listar
    janela._atualizar_selo_propostas()
    assert menu.selo_erro(PAGINA_PROPOSTAS) == "" and menu.texto_do_selo(PAGINA_PROPOSTAS) == ""
    print("OK: se a contagem falha o selo vira '!' com o motivo no tooltip (e no log); some quando volta a funcionar.")

    # recolhida: o selo vira uma bolinha no canto do icone
    propostas_mod.atualizar_proposta(p12, {"STATUS": propostas_mod.STATUS_EM_ANALISE})  # volta a 1 parada
    janela.ir_para(PAGINA_DASHBOARD)
    assert menu.selo(PAGINA_PROPOSTAS) == 1
    janela._alternar_sidebar()
    QApplication.processEvents()
    area = _retangulo_do_item(janela, PAGINA_PROPOSTAS)
    imagem = janela.grab().toImage()
    assert _contar_pixels(imagem, QColor(cores["faixa"]), area, 3) > 15, "recolhida, o selo vira uma bolinha ambar"
    janela._alternar_sidebar()
    amb.resetar_preferencias()
    print("OK: com o menu recolhido o selo vira uma bolinha no canto do icone.")

    # VENDEDOR: usa o que a tela de propostas ja leu (nunca relê a "rede" a cada troca de tela)
    vendedor = amb.nova_janela("vendedor", tema)
    assert vendedor._menu.selo(PAGINA_PROPOSTAS) == 1
    original_listar = propostas_mod.listar_propostas

    def _nao_deveria_reler():
        raise AssertionError("o VENDEDOR nao pode reler as propostas (ida ao Google Sheets) so pra atualizar o selo")

    propostas_mod.listar_propostas = _nao_deveria_reler
    try:
        vendedor._atualizar_selo_propostas()
        vendedor.ir_para(PAGINA_FICHA)
        vendedor.ir_para(PAGINA_DASHBOARD)
    finally:
        propostas_mod.listar_propostas = original_listar
    assert vendedor._menu.selo(PAGINA_PROPOSTAS) == 1 and vendedor._menu.selo_erro(PAGINA_PROPOSTAS) == ""
    print("OK: VENDEDOR: o selo vem do que a tela ja leu (nenhuma releitura ao trocar de tela).")
    # ... e o que a fixture tinha volta ao normal pros proximos testes (so o ADMIN escreve)
    amb.entrar_como("admin")
    propostas_mod.atualizar_proposta(p12, {"STATUS": propostas_mod.STATUS_EM_ANALISE})
    propostas_mod.atualizar_proposta(p20, {"STATUS": propostas_mod.STATUS_APROVADO})
    msgs.exigir_sem_erros("selo")


def testar_indicador_de_sincronizacao(amb: Ambiente, msgs: Mensagens, tema: str) -> None:
    linha(f"5) Indicador de sincronizacao [{tema}]")
    paleta = PALETAS[tema]
    agora = datetime(2026, 9, 20, 12, 0, 0)

    # -- as frases (funcoes puras) --
    def estado(**campos):
        base = dict(ativada=True, em_andamento=0, ultimo_sucesso=None, ultima_falha=None, ultimo_erro="")
        base.update(campos)
        return sheets_sync.EstadoSincronizacao(**base)

    assert descrever_sincronizacao(estado(ativada=False), agora).texto == "Sincronização desativada"
    assert descrever_sincronizacao(estado(), agora).texto == "Sem sincronização ainda"
    assert descrever_sincronizacao(estado(em_andamento=1), agora).texto == "Sincronizando…"
    assert descrever_sincronizacao(estado(em_andamento=3), agora).texto == "Sincronizando… (3)"
    assert descrever_sincronizacao(estado(ultimo_sucesso=agora - timedelta(seconds=10)), agora).texto == "Sincronizado agora"
    assert descrever_sincronizacao(estado(ultimo_sucesso=agora - timedelta(minutes=2)), agora).texto == "Sincronizado há 2 min"
    assert descrever_sincronizacao(estado(ultimo_sucesso=agora - timedelta(hours=3)), agora).texto == "Sincronizado há 3 h"
    falhou = descrever_sincronizacao(estado(ultima_falha=agora, ultimo_erro="RuntimeError: sem rede"), agora)
    assert falhou.texto == "Falhou — clique para ver" and "RuntimeError: sem rede" in falhou.detalhe and "20/09/2026 12:00" in falhou.detalhe
    assert descrever_leitura(None, agora).texto == "Sem leitura ainda"
    assert descrever_leitura(datetime(2026, 9, 20, 9, 5), agora).texto == "Dados de 09:05"
    assert descrever_leitura(datetime(2026, 9, 19, 9, 5), agora).texto == "Dados de 19/09 09:05"
    print("OK: as frases de cada estado (ADMIN: sincronizando / ok / falhou / ...; VENDEDOR: 'Dados de HH:MM').")

    # -- o widget na janela do ADMIN, nos tres estados --
    janela = amb.nova_janela("admin", tema)
    indicador = janela._indicador_sincronizacao
    assert janela._temporizador_do_indicador.isActive(), "o indicador se atualiza sozinho (poll da memoria)"

    def cor_desenhada() -> QColor:
        imagem = indicador.grab().toImage()
        return imagem.pixelColor(12 + 9, imagem.height() // 2)  # o centro da bolinha (coluna do icone)

    def conferir(nivel: str, texto: str, cor: QColor) -> None:
        janela._atualizar_indicador_de_sincronizacao()
        d = indicador.descricao()
        assert (d.nivel, d.texto) == (nivel, texto), (d.nivel, d.texto)
        assert indicador.text() == texto and texto in indicador.toolTip()
        desenhada = cor_desenhada()
        assert _perto(desenhada, cor), f"bolinha desenhada {desenhada.name()} != esperada {cor.name()}"

    sheets_sync._reiniciar_estado()
    config.SINCRONIZACAO_GOOGLE_ATIVADA = False
    try:
        janela._atualizar_indicador_de_sincronizacao()
        assert indicador.descricao().nivel == sheets_sync.NIVEL_DESATIVADA
        assert indicador.cor_da_bolinha().alpha() < 255, "desativada: bolinha neutra (cinza apagado), sem alarme"
        print("OK: desativada -> bolinha cinza.")

        config.SINCRONIZACAO_GOOGLE_ATIVADA = True
        janela._atualizar_indicador_de_sincronizacao()
        assert indicador.descricao().nivel == sheets_sync.NIVEL_AGUARDANDO

        sheets_sync._registrar_inicio()
        conferir(sheets_sync.NIVEL_SINCRONIZANDO, "Sincronizando…", QColor(CORES_STATUS[tema]["em_analise"]["faixa"]))
        print("OK: sincronizando -> bolinha ambar + 'Sincronizando…'.")

        sheets_sync._registrar_fim(None)
        conferir(sheets_sync.NIVEL_OK, "Sincronizado agora", QColor(paleta["sucesso"]))
        print("OK: sincronizado -> bolinha verde + 'Sincronizado agora'.")

        msgs.limpar()
        indicador.click()
        assert msgs.ultima()[0] == "information" and "Última sincronização" in msgs.ultima()[2]

        sheets_sync._registrar_inicio()
        sheets_sync._registrar_fim(RuntimeError("falha de teste"))
        conferir(sheets_sync.NIVEL_FALHOU, "Falhou — clique para ver", QColor(paleta["erro"]))
        print("OK: falhou -> bolinha vermelha + 'Falhou — clique para ver'.")

        msgs.limpar()
        indicador.click()
        tipo, titulo, texto = msgs.ultima()
        assert tipo == "warning" and "falha de teste" in texto and "Os dados continuam salvos" in texto, msgs.registro
        print("OK: clicar na falha abre o detalhe (com o erro e a tranquilizacao de que os dados estao salvos).")

        # recolhido: so a bolinha (centralizada), e o texto no tooltip
        janela._alternar_sidebar()
        assert indicador.esta_recolhido() and "Falhou" in indicador.toolTip()
        imagem = indicador.grab().toImage()
        assert _perto(imagem.pixelColor(imagem.width() // 2, imagem.height() // 2), QColor(paleta["erro"]))
        for botao in (indicador, janela._botao_tema, janela._botao_sair):
            desvio = abs(_centro_x_do_desenho(botao) - (botao.width() - 1) / 2)
            assert desvio <= 1.25, f"recolhido, o desenho de '{botao.text()}' esta {desvio:.1f} px fora do centro do botao"
        janela._alternar_sidebar()
        print("OK: recolhido, a bolinha fica centralizada e o texto vai no tooltip.")
    finally:
        config.SINCRONIZACAO_GOOGLE_ATIVADA = False
        sheets_sync._reiniciar_estado()
        amb.resetar_preferencias()

    # -- VENDEDOR: so le, mostra "Dados de HH:MM", nunca fala de sincronizacao --
    vendedor = amb.nova_janela("vendedor", tema)
    leitura_original = leitura_sheets._ultima_leitura
    try:
        leitura_sheets._ultima_leitura = None
        vendedor._atualizar_indicador_de_sincronizacao()
        assert vendedor._indicador_sincronizacao.descricao().texto == "Sem leitura ainda"
        leitura_sheets._ultima_leitura = datetime.now()
        vendedor._atualizar_indicador_de_sincronizacao()
        texto = vendedor._indicador_sincronizacao.descricao().texto
        assert texto == f"Dados de {datetime.now():%H:%M}" and "incroniz" not in texto, texto
        msgs.limpar()
        vendedor._indicador_sincronizacao.click()
        assert msgs.ultima()[0] == "information" and "Leitura mais recente" in msgs.ultima()[2]
    finally:
        leitura_sheets._ultima_leitura = leitura_original
    print("OK: VENDEDOR ve 'Dados de HH:MM' (a ultima leitura), nunca o estado de sincronizacao.")
    msgs.exigir_sem_erros("indicador")


def testar_sair(amb: Ambiente, msgs: Mensagens, tema: str) -> None:
    linha(f"6) Botao Sair [{tema}]")
    janela = amb.nova_janela("admin", tema)
    saidas: list[int] = []
    janela.sair_solicitado.connect(lambda: saidas.append(1))

    msgs.limpar()
    janela._botao_sair.click()
    assert saidas == [1] and not msgs.registro, "sem edicao pendente sai direto, sem perguntar"
    print("OK: sem edicao pendente, Sair emite o pedido na hora (sem perguntar nada).")

    # edicao nao salva em Todas as Propostas
    janela.ir_para(PAGINA_PROPOSTAS)
    janela._tela_propostas.abrir_nova_proposta()
    janela._tela_propostas._expansor.formulario()._observacoes.setPlainText("rascunho de teste")
    assert janela.tem_edicao_pendente()

    msgs.limpar()
    msgs.resposta_pergunta = QMessageBox.StandardButton.No
    janela._botao_sair.click()
    assert saidas == [1], "respondeu Não: continua na janela"
    tipo, titulo, texto = msgs.ultima()
    assert tipo == "question" and "não foram salvas" in texto and "Alterações não salvas" == titulo
    msgs.resposta_pergunta = QMessageBox.StandardButton.Yes
    janela._botao_sair.click()
    assert saidas == [1, 1], "respondeu Sim: sai"
    print("OK: com edicao nao salva em Todas as Propostas, pergunta antes (Não = fica, Sim = sai).")

    janela._tela_propostas._expansor.descartar()
    assert not janela.tem_edicao_pendente()

    # e o mesmo na Ficha de Cliente
    janela.ir_para(PAGINA_FICHA)
    janela._tela_ficha._selecionar_por_cpf(fx.CPF_MARIA)
    janela._tela_ficha._abrir_nova_proposta()
    janela._tela_ficha._expansor.formulario()._observacoes.setPlainText("outro rascunho")
    assert janela.tem_edicao_pendente()
    msgs.limpar()
    msgs.resposta_pergunta = QMessageBox.StandardButton.No
    janela._botao_sair.click()
    assert saidas == [1, 1] and msgs.ultima()[0] == "question"
    print("OK: o mesmo vale para edicao nao salva na Ficha de Cliente.")
    janela._tela_ficha._expansor.descartar()
    msgs.resposta_pergunta = QMessageBox.StandardButton.Yes

    # rascunho aberto mas SEM nada digitado nao conta como edicao pendente
    janela._tela_propostas.abrir_nova_proposta()
    assert janela._tela_propostas._expansor.eh_rascunho() and not janela.tem_edicao_pendente()
    janela._tela_propostas._expansor.descartar()
    print("OK: um card 'Nova proposta' em branco nao conta como edicao pendente.")

    # -- fluxo de trocar de usuario (desktop/main.py) --
    class _AppFalso:
        def __init__(self):
            self.saidas = 0

        def quit(self):
            self.saidas += 1

    entrar_original = main_mod.entrar
    try:
        # (1) outra pessoa entra: nova janela, montada pro papel dela
        app_falso = _AppFalso()
        controlador = main_mod.ControladorDaJanela(app_falso)
        amb.entrar_como("admin")
        controlador.abrir()
        anterior = controlador.janela
        amb.janelas.append(anterior)
        chamadas = []

        def _login_de_vendedor():
            chamadas.append(sessao_mod.atual())  # o que a sessao vale QUANDO o login aparece
            amb.entrar_como("vendedor")
            return True

        main_mod.entrar = _login_de_vendedor
        msgs.limpar()
        anterior._botao_sair.click()
        assert chamadas == [None], "a sessao tem que estar encerrada quando o login aparece"
        assert controlador.janela is not anterior and anterior.isHidden(), "janela nova; a antiga fica escondida"
        assert not anterior._temporizador_do_indicador.isActive(), "a janela antiga para de atualizar o indicador"
        nova = controlador.janela
        amb.janelas.append(nova)
        assert nova._identidade.nome() == "Vendedor Exemplo" and nova._botao_nova_proposta is None
        assert PAGINA_ADMINISTRACAO not in nova._indice_por_chave, "a janela nova e montada pro papel de quem entrou"
        assert app_falso.saidas == 0
        print("OK: Sair -> login -> outra pessoa entra: janela nova montada pro papel dela (VENDEDOR sem Administração).")

        # (2) o login e cancelado: o app fecha
        main_mod.entrar = lambda: chamadas.append(sessao_mod.atual()) or False
        atual = controlador.janela
        atual._botao_sair.click()
        assert chamadas[-1] is None and app_falso.saidas == 1 and sessao_mod.atual() is None
        assert atual.isHidden()
        print("OK: login cancelado depois do Sair -> a sessao fica encerrada e o app fecha (quit).")

        # (3) o login deu certo, mas a janela nova NAO abre: avisa e fecha o app (nunca some em silencio)
        app_falso = _AppFalso()
        controlador = main_mod.ControladorDaJanela(app_falso)
        amb.entrar_como("admin")
        assert controlador.abrir() is True
        anterior = controlador.janela
        amb.janelas.append(anterior)
        janela_original = main_mod.MainWindow

        class _JanelaQueNaoAbre:
            def __init__(self):
                raise RuntimeError("erro de teste ao montar a janela")

        main_mod.entrar = _login_de_vendedor
        main_mod.MainWindow = _JanelaQueNaoAbre
        try:
            msgs.limpar()
            anterior._botao_sair.click()
            tipo, titulo, texto = msgs.ultima()
            assert tipo == "critical" and "Não foi possível abrir" in titulo and "erro de teste ao montar a janela" in texto
            assert app_falso.saidas == 1 and sessao_mod.atual() is None, "sem janela nova o app fecha, sem sessao pendurada"
            print("OK: se a janela nova nao abre depois do login, avisa o motivo e fecha o app (nao some em silencio).")

            # e a abertura inicial do app (main) tambem avisa, em vez de so morrer
            msgs.limpar()
            assert main_mod.ControladorDaJanela(_AppFalso()).abrir() is False
            assert msgs.ultima()[0] == "critical"
            print("OK: a abertura inicial que falha tambem mostra o erro e devolve False (main sai com codigo 1).")
        finally:
            main_mod.MainWindow = janela_original
    finally:
        main_mod.entrar = entrar_original
    msgs.resposta_pergunta = QMessageBox.StandardButton.Yes


def testar_ultima_tela_e_geometria(amb: Ambiente, msgs: Mensagens, tema: str) -> None:
    linha(f"7) Ultima tela e geometria da janela lembradas [{tema}]")
    amb.resetar_preferencias()
    janela = amb.nova_janela("admin", tema)
    assert janela.chave_atual() == PAGINA_DASHBOARD, "sem nada salvo abre no Dashboard"
    assert settings_mod.obter_ultima_tela() == PAGINA_DASHBOARD

    janela.ir_para(PAGINA_PROPOSTAS)
    assert settings_mod.obter_ultima_tela() == PAGINA_PROPOSTAS
    reaberta = amb.nova_janela("admin", tema)
    assert reaberta.chave_atual() == PAGINA_PROPOSTAS and reaberta._paginas.currentWidget() is reaberta._tela_propostas
    print("OK: a ultima tela aberta e lembrada e a janela seguinte abre nela.")

    reaberta.ir_para(PAGINA_ADMINISTRACAO)
    vendedor = amb.nova_janela("vendedor", tema)
    assert vendedor.chave_atual() == PAGINA_DASHBOARD, "a tela lembrada nao existe pro VENDEDOR: cai no Dashboard"
    settings_mod.definir_ultima_tela("tela-que-nao-existe")
    assert amb.nova_janela("admin", tema).chave_atual() == PAGINA_DASHBOARD, "valor invalido salvo: cai no Dashboard"
    print("OK: tela lembrada que nao existe (VENDEDOR sem Administração, ou valor invalido) cai no Dashboard.")

    # geometria: tamanho salvo ao fechar e restaurado
    amb.resetar_preferencias()
    janela = amb.nova_janela("admin", tema, mostrar=False)
    assert janela.size() == QSize(1200, 800), "sem geometria salva usa o tamanho padrao"
    minimo = janela.minimumSizeHint()  # o layout tem um tamanho minimo: usa-se um tamanho acima dele
    alvo = QSize(minimo.width() + 40, minimo.height() + 60)
    assert alvo.height() != 800, "o tamanho de teste tem que se distinguir do padrao"
    janela.resize(alvo)
    janela.show()
    QApplication.processEvents()
    assert janela.size() == alvo
    janela.close()
    assert settings_mod.obter_geometria_janela() is not None
    outra = amb.nova_janela("admin", tema)
    # a altura e o que distingue "restaurou" de "usou o padrao" (800); a largura pode cair no minimo do layout
    assert outra.size().height() == alvo.height() and outra.size().width() >= minimo.width(), outra.size()
    print("OK: o tamanho da janela e salvo ao fechar e restaurado na proxima abertura.")

    # geometria invalida (lixo no registro/arquivo): usa o padrao, sem quebrar
    settings_mod.definir_geometria_janela(QByteArray(b"isto nao e uma geometria"))
    assert amb.nova_janela("admin", tema, mostrar=False).size() == QSize(1200, 800)
    print("OK: geometria salva invalida -> tamanho padrao, sem quebrar.")

    # o estado da barra recolhida tambem continua sendo lembrado
    amb.resetar_preferencias()
    janela = amb.nova_janela("admin", tema)
    janela._alternar_sidebar()
    assert amb.nova_janela("admin", tema)._menu_recolhido is True
    amb.resetar_preferencias()
    msgs.exigir_vazio("ultima tela")


def testar_nova_proposta(amb: Ambiente, msgs: Mensagens, tema: str) -> None:
    linha(f"8) Botao '+ Nova proposta' [{tema}]")
    amb.resetar_preferencias()
    janela = amb.nova_janela("admin", tema)
    janela.ir_para(PAGINA_DASHBOARD)
    assert not janela._tela_propostas._expansor.eh_rascunho()
    janela._botao_nova_proposta.click()
    assert janela.chave_atual() == PAGINA_PROPOSTAS, "leva a Todas as Propostas"
    assert janela._tela_propostas._expansor.eh_rascunho() and janela._tela_propostas._modelo.tem_rascunho()
    print("OK: '+ Nova proposta' abre Todas as Propostas com o card 'Nova proposta' em edicao.")

    janela._alternar_sidebar()
    assert janela._botao_nova_proposta.text() == "+" and janela._botao_nova_proposta.toolTip() == "Nova proposta"
    janela._alternar_sidebar()
    assert janela._botao_nova_proposta.text() == "+ Nova proposta"
    print("OK: recolhido, o botao vira '+' (com tooltip).")

    vendedor = amb.nova_janela("vendedor", tema)
    vendedor._tela_propostas.abrir_nova_proposta()  # a segunda trava: nem por codigo o VENDEDOR abre
    assert not vendedor._tela_propostas._expansor.eh_rascunho()
    print("OK: o VENDEDOR nao tem o botao, e abrir_nova_proposta() por codigo nao faz nada pra ele.")
    amb.resetar_preferencias()
    msgs.exigir_vazio("nova proposta")


def testar_recolher_e_tema(amb: Ambiente, msgs: Mensagens, tema: str) -> None:
    linha(f"9) Recolher a barra e trocar o tema [{tema}]")
    amb.resetar_preferencias()
    janela = amb.nova_janela("admin", tema)
    menu = janela._menu
    janela.ir_para(PAGINA_FICHA)

    altura_titulo_expandido = menu.visualItemRect(menu.item(0)).height()
    janela._alternar_sidebar()
    assert janela._sidebar.width() == 60 and menu.esta_recolhido()
    assert janela._rotulo_versao.isHidden() and not janela._titulo_app.isVisible()
    assert all(b.esta_recolhido() for b in (janela._indicador_sincronizacao, janela._botao_tema, janela._botao_sair))
    assert menu.visualItemRect(menu.item(0)).height() < altura_titulo_expandido, "recolhido, o titulo do grupo vira um filete"
    for chave, rotulo in (
        (PAGINA_DASHBOARD, "Dashboard de Propostas"),
        (PAGINA_FICHA, "Ficha de Cliente"),
        (PAGINA_PROPOSTAS, "Todas as Propostas"),
        (PAGINA_ADMINISTRACAO, "Administração"),
    ):
        assert rotulo in menu._itens_por_chave[chave].toolTip(), f"recolhido, o rotulo de {chave} vai no tooltip"
    assert settings_mod.obter_sidebar_recolhida() is True
    print("OK: recolhida: 60 px, so icones, titulos viram filete, rotulos no tooltip e o estado e salvo.")

    # o icone tem que continuar VISIVEL e centrado no item da barra estreita (ja houve um bug em que o
    # padding do item empurrava o icone pra fora da area de desenho e ele sumia)
    QApplication.processEvents()
    paleta_r = PALETAS[tema]
    imagem_r = janela.grab().toImage()
    for chave, cor_do_icone in ((PAGINA_FICHA, QColor("white")), (PAGINA_DASHBOARD, QColor(paleta_r["texto_secundario"])), (PAGINA_ADMINISTRACAO, QColor(paleta_r["texto_secundario"]))):
        area_r = _retangulo_do_item(janela, chave)
        assert area_r.height() >= 36, f"o item recolhido de {chave} ficou baixo demais ({area_r.height()} px)"
        assert area_r.width() >= 30, f"o item recolhido de {chave} ficou estreito demais ({area_r.width()} px)"
        area_do_icone = QRect(area_r.center().x() - 9, area_r.center().y() - 9, 18, 18)
        assert _contar_pixels(imagem_r, cor_do_icone, area_do_icone, 16) > 8, f"o icone de {chave} sumiu da barra recolhida"
    print("OK: recolhida, o icone de cada item continua desenhado e centrado (nao some, nao e espremido).")

    # a identidade e o "+ Nova proposta" cabem na barra estreita (o avatar ja saiu cortado: 34 px numa area de 32)
    avatar = janela._identidade._avatar
    assert avatar.geometry().right() <= janela._identidade.rect().right(), "o avatar esta cortado pela borda da barra recolhida"
    centro_do_avatar = avatar.mapTo(janela._sidebar, QPoint(avatar.width() // 2, 0)).x()
    assert abs(centro_do_avatar - janela._sidebar.width() // 2) <= 1, "o avatar deveria ficar centrado na barra recolhida"
    botao_nova = janela._botao_nova_proposta
    assert botao_nova.sizeHint().width() <= botao_nova.width(), (
        f"o '+' esta cortado: o botao pede {botao_nova.sizeHint().width()} px e tem {botao_nova.width()} px"
    )
    print("OK: recolhida, o avatar nao e cortado e fica centrado, e o '+' de Nova proposta cabe no botao.")
    janela._alternar_sidebar()
    assert janela._sidebar.width() == 230 and not janela._rotulo_versao.isHidden()
    assert janela._rotulo_versao.text() == f"v{config.VERSAO_APP}"
    print(f"OK: expandida: 230 px, versao 'v{config.VERSAO_APP}' no rodape (constante unica em config.py).")

    # item selecionado: fundo de destaque + icone branco; nao selecionado: icone na cor secundaria do tema
    QApplication.processEvents()
    paleta = PALETAS[tema]
    area = _retangulo_do_item(janela, PAGINA_FICHA)
    imagem = janela.grab().toImage()
    assert _contar_pixels(imagem, QColor(paleta["destaque"]), QRect(area.left() + 2, area.center().y() - 3, 8, 6), 2) > 30, "o item selecionado tem fundo de destaque"
    icone_selecionado = QRect(area.left() + 14, area.center().y() - 9, 18, 18)
    assert _contar_pixels(imagem, QColor("white"), icone_selecionado, 16) > 8, "icone do item selecionado e branco"
    area_dash = _retangulo_do_item(janela, PAGINA_DASHBOARD)
    icone_dash = QRect(area_dash.left() + 14, area_dash.center().y() - 9, 18, 18)
    assert _contar_pixels(imagem, QColor(paleta["texto_secundario"]), icone_dash, 14) > 8, "icone nao selecionado na cor secundaria do tema"
    print("OK: selecionado = fundo de destaque + icone branco; os outros = icone na cor secundaria do tema.")

    # trocar o tema refaz as cores de tudo (menu, botoes do rodape, avatar)
    inicial = janela._tema_atual
    janela._alternar_tema()
    novo = TEMA_CLARO if inicial == TEMA_ESCURO else TEMA_ESCURO
    assert janela._tema_atual == novo and settings_mod.obter_tema() == novo
    assert menu._delegado._paleta is PALETAS[novo]
    assert janela._botao_tema._paleta is PALETAS[novo] and janela._identidade._avatar._paleta is PALETAS[novo]
    assert janela._botao_tema.icone() == ("lua" if novo == TEMA_CLARO else "sol")
    assert ("Escuro" in janela._botao_tema.text()) == (novo == TEMA_CLARO)
    QApplication.processEvents()
    area = _retangulo_do_item(janela, PAGINA_FICHA)
    imagem = janela.grab().toImage()
    assert _contar_pixels(imagem, QColor(PALETAS[novo]["destaque"]), QRect(area.left() + 2, area.center().y() - 3, 8, 6), 2) > 30
    janela._alternar_tema()
    assert janela._tema_atual == inicial
    print("OK: trocar o tema refaz a paleta do menu, dos botoes e do avatar (e o botao mostra a ACAO: sol/lua).")
    amb.resetar_preferencias()
    msgs.exigir_vazio("recolher e tema")


def testar_icones() -> None:
    linha("10) Icones de linha")
    nomes = icones_linha.nomes_de_icones()
    assert {"dashboard", "ficha", "propostas", "administracao", "mais", "sair", "sol", "lua"} <= set(nomes), nomes
    cor = QColor("#3366cc")
    for nome in nomes:
        imagem = QImage(48, 48, QImage.Format.Format_ARGB32)
        imagem.fill(Qt.GlobalColor.transparent)
        pintor = QPainter(imagem)
        icones_linha.desenhar_icone(pintor, nome, QRectF(0, 0, 48, 48), cor)
        pintor.end()
        opacos = [imagem.pixelColor(x, y) for y in range(48) for x in range(48) if imagem.pixelColor(x, y).alpha() > 200]
        assert len(opacos) >= 30, f"o icone {nome!r} nao desenhou nada"
        assert all(max(abs(c.red() - cor.red()), abs(c.green() - cor.green()), abs(c.blue() - cor.blue())) <= 3 for c in opacos), (
            f"o icone {nome!r} nao usou a cor pedida"
        )
    print(f"OK: os {len(nomes)} icones desenham algo, na cor pedida.")

    imagem_vazia = QImage(8, 8, QImage.Format.Format_ARGB32)
    pintor = QPainter(imagem_vazia)
    try:
        icones_linha.desenhar_icone(pintor, "icone-que-nao-existe", QRectF(0, 0, 8, 8), cor)
    except KeyError as exc:
        assert "icone-que-nao-existe" in str(exc)
    else:
        raise AssertionError("um icone desconhecido tem que dar erro, nao passar em branco")
    finally:
        pintor.end()
    print("OK: icone desconhecido -> KeyError (nunca em branco).")

    icone = icones_linha.icone_de_linha("sair", cor, 18)
    assert not icone.pixmap(QSize(18, 18)).isNull()
    print("OK: icone_de_linha() devolve um QIcon utilizavel.")


def testar_fundo_dos_rotulos_e_tooltip(amb: Ambiente, msgs: Mensagens, tema: str) -> None:
    linha(f"11) Fundo dos rotulos (regra global de QLabel) e tooltip [{tema}]")
    amb.resetar_preferencias()
    janela = amb.nova_janela("admin", tema)
    paleta = PALETAS[tema]

    def fundo_proprio(rotulo: QLabel) -> QColor:
        """O fundo que o QSS deu ao PROPRIO rotulo: a cor que mais aparece na foto dele (as letras
        ocupam pouco; amostrar um pixel so cairia sobre uma letra em rotulos curtos, como "SP")."""
        imagem = rotulo.grab().toImage()
        assert imagem.width() > 4 and imagem.height() > 4, f"rotulo sem tamanho ({rotulo.text()!r}): a foto nao diz nada"
        cores = Counter(imagem.pixel(x, y) for y in range(imagem.height()) for x in range(imagem.width()))
        return QColor.fromRgba(cores.most_common(1)[0][0])

    def transparente(rotulo: QLabel) -> bool:
        return fundo_proprio(rotulo).alpha() == 0

    # Dashboard, Administração e a barra lateral: rotulos sem fundo (sem a faixa escura sobre o card)
    for nome, tela in (("Dashboard", janela._tela_dashboard), ("Administração", janela._tela_administracao), ("barra lateral", janela._sidebar)):
        rotulos = tela.findChildren(QLabel)
        assert len(rotulos) >= 3, nome
        com_fundo = [r.text() for r in rotulos if not transparente(r)]
        assert not com_fundo, f"{nome}: rotulos com fundo proprio (faixa atras do texto): {com_fundo}"
    for card in (janela._tela_dashboard._card_em_analise, janela._tela_dashboard._card_taxa):
        for rotulo in card.findChildren(QLabel):
            assert transparente(rotulo)
    print("OK: os rotulos do Dashboard (cards), da Administração e da barra lateral nao tem fundo proprio.")

    # ... e a foto do card confirma: onde nao ha letra, o fundo e o do CARD (nao o da janela)
    card = janela._tela_dashboard._card_em_analise
    imagem = card.grab().toImage()
    legenda = card._valor
    ponto = legenda.mapTo(card, QPoint(legenda.width() - 3, 3))
    assert imagem.pixelColor(ponto).name() == QColor(paleta["bg_card"]).name(), (imagem.pixelColor(ponto).name(), paleta["bg_card"])
    print("OK: no card, atras do texto aparece a cor do proprio card.")

    # Ficha de Cliente: os rotulos de CAMPO mantem o fundo de proposito (o visual de sempre)
    janela.ir_para(PAGINA_FICHA)
    ficha = janela._tela_ficha
    ficha._selecionar_por_cpf(fx.CPF_MARIA)
    QApplication.processEvents()
    de_campo = [r for r in ficha.findChildren(QLabel) if r.property("role") in ("campo_rotulo", "campo_valor")]
    assert len(de_campo) >= 20, f"a Ficha deveria ter dezenas de rotulos de campo, achei {len(de_campo)}"
    esperado = QColor(paleta["bg"])
    for rotulo in de_campo:
        fundo = fundo_proprio(rotulo)
        assert fundo.alpha() == 255 and fundo.name() == esperado.name(), (rotulo.text(), fundo.name(), esperado.name())
    print(f"OK: os {len(de_campo)} rotulos de campo da Ficha continuam com o fundo proprio (o visual dos campos).")

    # o tooltip e um QLabel por baixo dos panos: tem que continuar opaco (e legivel)
    QToolTip.showText(QPoint(300, 300), "texto de teste do tooltip", janela)
    QApplication.processEvents()
    dicas = [w for w in QApplication.allWidgets() if w.metaObject().className() == "QTipLabel" and w.isVisible()]
    assert dicas, "o tooltip nao apareceu"
    pixel = dicas[0].grab().toImage().pixelColor(2, 2)
    assert pixel.alpha() == 255 and pixel.name() == QColor(paleta["bg"]).name(), (pixel.name(), pixel.alpha())
    QToolTip.hideText()
    print("OK: o tooltip continua com fundo opaco (a regra de QLabel nao o deixou transparente).")
    amb.resetar_preferencias()
    msgs.exigir_vazio("fundo dos rotulos")


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    estilo_original = app.style().objectName()
    app.setStyle("windows11")  # o app real usa este estilo; o padrao sem tela (Fusion) esconderia diferencas
    amb = Ambiente()
    try:
        with Mensagens() as msgs:
            for tema in TEMAS:
                for teste in (
                    testar_menu_e_grupos,
                    testar_navegacao_por_teclado_e_atalhos,
                    testar_identidade,
                    testar_selo,
                    testar_indicador_de_sincronizacao,
                    testar_sair,
                    testar_ultima_tela_e_geometria,
                    testar_nova_proposta,
                    testar_recolher_e_tema,
                    testar_fundo_dos_rotulos_e_tooltip,
                ):
                    msgs.limpar()  # cada teste comeca sem mensagens do anterior (o do Sair provoca erros de proposito)
                    teste(amb, msgs, tema)
                    amb.limpar_janelas()
            testar_icones()
        linha("TUDO OK")
    finally:
        amb.encerrar()
        app.setStyle(estilo_original)
        app.setStyleSheet("")


if __name__ == "__main__":
    main()
