"""Testa a janela em tela pequena (plano 1.6, "caber na tela"): tamanho inicial de 90% da area util da tela e a barra
lateral que recolhe sozinha abaixo de 1200 px (desktop/main_window.py), com as telas de 1366x768, 1092x614 (125% do
Windows) e 910x512 (150%) simuladas. Offscreen, planilha FICTICIA, preferencias num .ini temporario, Google bloqueado.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_tela_1366.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixture_ficticia as fx
from ambiente_de_teste import Ambiente, Mensagens
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

from desktop import settings as settings_mod
from desktop.main_window import PAGINA_PROPOSTAS, tamanho_inicial_da_janela
from desktop.theme import TEMA_CLARO

TELAS = ((1366, 768), (1092, 614), (910, 512))
LARGURA_RECOLHIDA, LARGURA_EXPANDIDA = 60, 230


def _assentar() -> None:
    """O piso novo da janela (depois de a barra recolher/expandir) so vale depois de o layout rodar de novo,
    o que leva mais de uma volta do loop de eventos."""
    for _ in range(4):
        QApplication.processEvents()


def linha(texto: str) -> None:
    print(texto)


def testar_tamanho_inicial() -> None:
    esperado = {
        (1920, 1080): QSize(1200, 800),  # tela grande: o tamanho padrao
        (1366, 768): QSize(1200, 691),
        (1092, 614): QSize(982, 552),
        (910, 512): QSize(819, 460),
    }
    for (largura, altura), tamanho in esperado.items():
        obtido = tamanho_inicial_da_janela(QSize(largura, altura))
        assert obtido == tamanho, f"tela {largura}x{altura}: esperava {tamanho}, veio {obtido}"
        assert obtido.width() <= largura and obtido.height() <= altura, "a janela nunca pode ser maior que a tela"
    linha("OK: o tamanho inicial e 90% da area util, no maximo 1200x800, e nunca maior que a tela.")


def testar_janela_em_cada_tela(amb: Ambiente) -> None:
    for largura, altura in TELAS:
        amb.resetar_preferencias()
        fx.simular_tela(largura, altura)
        janela = amb.nova_janela("admin", TEMA_CLARO)
        esperado = tamanho_inicial_da_janela(QSize(largura, altura))
        # o piso do layout pode subir a janela (so em tela muito pequena: ver o aviso abaixo)
        assert esperado.height() <= janela.height() <= altura, (largura, altura, janela.size())
        if largura >= 1200 / 0.9:
            assert not janela._janela_estreita and janela._sidebar.width() == LARGURA_EXPANDIDA
            assert janela.width() == esperado.width() and janela.width() <= largura
        else:
            assert janela._janela_estreita and janela._menu_recolhido and janela._sidebar.width() == LARGURA_RECOLHIDA, (
                f"tela {largura}: a barra tinha que abrir recolhida")
            assert janela._menu.esta_recolhido()
        assert settings_mod.obter_sidebar_recolhida() is False, "recolher sozinha nao pode gravar a escolha da pessoa"

        janela.ir_para(PAGINA_PROPOSTAS)
        QApplication.processEvents()
        piso = janela.minimumSizeHint().width()
        if largura >= 1000:
            if janela._janela_estreita:  # barra recolhida: 60 + 923; com a barra expandida o piso e 1153 e cabe em 1366
                assert piso < 1000, f"tela {largura}: o piso da janela e {piso} px (tem que ficar abaixo de 1000)"
            assert piso <= largura, f"tela {largura}: o piso da janela ({piso} px) e maior que a tela"
            assert janela.width() <= largura, f"tela {largura}: a janela abriu com {janela.width()} px, maior que a tela"
            linha(f"OK: tela {largura}x{altura}: janela {janela.width()}x{janela.height()}, barra "
                  f"{janela._sidebar.width()} px, piso {piso} px (cabe).")
        else:
            # Propostas pede 923 px (filtros numa linha so) + 60 da barra recolhida: em 150% ainda passa da tela.
            # Isso espera o item 3 do plano (filtros que quebram linha); aqui so se confirma a causa.
            assert piso == LARGURA_RECOLHIDA + janela._tela_propostas.minimumSizeHint().width(), piso
            linha(f"AVISO: tela {largura}x{altura}: o piso da janela e {piso} px, maior que a tela: depende do item 3 "
                  "(filtros da pagina Propostas quebrando linha).")


def testar_recolhe_ao_cruzar_1200(amb: Ambiente) -> None:
    amb.resetar_preferencias()
    fx.simular_tela(1920, 1080)
    janela = amb.nova_janela("admin", TEMA_CLARO)
    assert janela.width() == 1200 and janela._sidebar.width() == LARGURA_EXPANDIDA

    janela.resize(1199, 800)
    _assentar()
    assert janela._menu_recolhido and janela._sidebar.width() == LARGURA_RECOLHIDA, "com 1199 px a barra tem que recolher"
    assert settings_mod.obter_sidebar_recolhida() is False

    janela.resize(1000, 700)
    _assentar()
    assert janela.width() < 1100 and janela._sidebar.width() == LARGURA_RECOLHIDA, (janela.size(), janela.minimumSizeHint(), "recolhida, a janela passa de 1153 para baixo")

    janela.resize(1200, 800)
    _assentar()
    assert not janela._menu_recolhido and janela._sidebar.width() == LARGURA_EXPANDIDA, "com 1200 px a barra volta"
    linha("OK: abaixo de 1200 px a barra recolhe sozinha (sem gravar a preferencia) e volta em 1200 px ou mais.")

    # a escolha da pessoa vale ate o proximo cruzamento do limite
    janela.resize(1150, 800)
    _assentar()
    assert janela._menu_recolhido
    janela._alternar_sidebar()  # a pessoa expande a mao
    _assentar()
    assert not janela._menu_recolhido and janela._sidebar.width() == LARGURA_EXPANDIDA
    janela.resize(janela.width() + 20, janela.height())
    _assentar()
    assert not janela._menu_recolhido, "mexer no tamanho sem cruzar o limite nao desfaz a escolha da pessoa"
    janela.resize(1300, 800)
    janela.resize(1100, 800)
    _assentar()
    assert janela._menu_recolhido, "cruzar o limite de novo recolhe outra vez"
    linha("OK: expandir a barra a mao numa janela estreita vale ate a janela cruzar o limite de 1200 px de novo.")

    # a preferencia "recolhida" continua mandando numa janela larga, e uma janela larga nao a muda
    amb.resetar_preferencias()
    settings_mod.definir_sidebar_recolhida(True)
    janela = amb.nova_janela("admin", TEMA_CLARO)
    assert janela._menu_recolhido and janela._sidebar.width() == LARGURA_RECOLHIDA
    janela.resize(1000, 700)
    _assentar()
    janela.resize(1300, 800)
    _assentar()
    assert janela._menu_recolhido, "ao crescer, volta ao que a pessoa tinha escolhido (recolhida)"
    linha("OK: a escolha 'recolhida' da pessoa e respeitada tambem depois de a janela estreitar e crescer.")


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    amb = Ambiente()
    try:
        with Mensagens() as msgs:
            testar_tamanho_inicial()
            testar_janela_em_cada_tela(amb)
            amb.limpar_janelas()
            testar_recolhe_ao_cruzar_1200(amb)
            msgs.exigir_vazio("tela 1366")
        linha("TUDO OK")
    finally:
        amb.encerrar()
        app.setStyleSheet("")


if __name__ == "__main__":
    main()
