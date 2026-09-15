"""Sombra suave pra dar sensacao de profundidade em cartoes/paineis - o Qt
Style Sheets nao tem equivalente a "box-shadow" do CSS, entao isso precisa
ser aplicado via QGraphicsDropShadowEffect (codigo), nao via QSS.

Mais forte no tema claro (onde o fundo e os cards sao proximos e precisam de
ajuda extra pra "flutuar") do que no escuro (que ja tem bastante contraste
so pela diferenca de cor entre fundo e card).
"""

from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

from desktop.theme import TEMA_CLARO


def aplicar_sombra_suave(widget: QWidget, tema: str = "") -> None:
    if tema == TEMA_CLARO:
        desfoque, deslocamento_y, alpha = 36, 10, 55
    else:
        desfoque, deslocamento_y, alpha = 24, 3, 45

    sombra = QGraphicsDropShadowEffect(widget)
    sombra.setBlurRadius(desfoque)
    sombra.setOffset(0, deslocamento_y)
    sombra.setColor(QColor(15, 23, 42, alpha))
    widget.setGraphicsEffect(sombra)
