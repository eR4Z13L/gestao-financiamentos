"""Uma linha clicavel de lista do dashboard: um marcador colorido, o texto (elidido se nao couber, com o
inteiro no tooltip) e uma seta na ponta. Sem borda em repouso; ganha um fundo leve com o mouse e
um anel de foco pelo teclado (Tab, Enter/Espaco). E desenhada por codigo (o QSS nao sabe
colorir o marcador nem a seta) e usa as cores do tema ativo.

O marcador diz o TIPO do que a linha aponta: "processo" (algo parado no fluxo, ambar) ou "dados"
(algo errado ou faltando no cadastro, cor de destaque); "neutro" e cinza.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

from core import dashboard as dashboard_mod
from desktop.widgets.paleta_do_tema import UsaPaletaDoTema

_ALTURA = 34
_MARGEM = 10


class LinhaClicavel(UsaPaletaDoTema, QAbstractButton):
    def __init__(self, texto: str, tom: str = "neutro", parent: QWidget | None = None):
        super().__init__(parent)
        self._tom = tom
        self._resolver_paleta()
        self.setText(texto)
        self.setToolTip(texto)
        self.setAccessibleName(texto)
        self.setFixedHeight(_ALTURA)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)  # o texto elide: nunca estica o cartao
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def tom(self) -> str:
        return self._tom

    def cor_do_marcador(self) -> QColor:
        if self._tom == dashboard_mod.TOM_PROCESSO:
            return QColor(self._cores_de_status["em_analise"]["faixa"])
        if self._tom == dashboard_mod.TOM_DADOS:
            return QColor(self._paleta["destaque"])
        return QColor(self._cores_de_status["neutro"]["faixa"])

    def sizeHint(self) -> QSize:
        return QSize(200, _ALTURA)

    def enterEvent(self, evento) -> None:
        self.update()
        super().enterEvent(evento)

    def leaveEvent(self, evento) -> None:
        self.update()
        super().leaveEvent(evento)

    def paintEvent(self, _evento) -> None:
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect())

        if self.underMouse() or self.isDown():
            fundo = QColor(self._paleta["borda"])
            fundo.setAlpha(150 if self.isDown() else 90)
            pintor.setPen(Qt.PenStyle.NoPen)
            pintor.setBrush(fundo)
            pintor.drawRoundedRect(area, 6, 6)

        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(self.cor_do_marcador())
        pintor.drawEllipse(QPointF(area.left() + _MARGEM + 4, area.center().y()), 4.5, 4.5)

        x_texto = area.left() + _MARGEM + 4 + 4.5 + 10
        largura = max(area.right() - _MARGEM - 14 - x_texto, 0.0)
        pintor.setPen(QColor(self._paleta["texto"]))
        pintor.drawText(
            QRectF(x_texto, area.top(), largura, area.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, int(largura)),
        )

        # a seta (">") na ponta: diz que a linha leva pra algum lugar
        cor_seta = QColor(self._paleta["texto_secundario"])
        pintor.setPen(QPen(cor_seta, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        pintor.setBrush(Qt.BrushStyle.NoBrush)
        x = area.right() - _MARGEM - 4
        pintor.drawPolyline(QPolygonF([QPointF(x - 3, area.center().y() - 4.5), QPointF(x + 2, area.center().y()), QPointF(x - 3, area.center().y() + 4.5)]))

        if self.hasFocus():  # so pelo teclado (ver setFocusPolicy)
            pintor.setPen(QPen(QColor(self._paleta["destaque"]), 1))
            pintor.drawRoundedRect(area.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
