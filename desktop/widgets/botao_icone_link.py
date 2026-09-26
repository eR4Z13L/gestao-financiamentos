"""Botao "abrir link" discreto pra por ao lado de um campo (WhatsApp do celular, link
da rede social detectada): so um icone pequeno, sem borda nem preenchimento em repouso -
so ganha um fundo leve quando o mouse passa por cima, e escurece/apaga quando
desabilitado. Mesmo padrao visual do BotaoCopiar (desktop/widgets/botao_copiar.py); o
desenho do icone em si vem do registro compartilhado em icones_linha.py.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QWidget

from desktop import settings as settings_mod
from desktop.theme import PALETAS, TEMA_ESCURO
from desktop.widgets.icones_linha import desenhar_icone

_LADO = 24  # o botao e um quadrado de 24px, igual ao BotaoCopiar
_AREA_ICONE = QRectF(4, 4, 16, 16)  # o desenho fica centralizado dentro do quadrado
_ALPHA_REPOUSO = 140  # icone em repouso fica apagado (0-255) pra nao competir com o dado
_ALPHA_DESABILITADO = 70


class BotaoIconeLink(QAbstractButton):
    def __init__(self, nome_icone: str, ao_clicar: Callable[[], None], parent: QWidget | None = None):
        super().__init__(parent)
        self._nome_icone = nome_icone
        self._resolver_paleta()

        self.setFixedSize(_LADO, _LADO)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        self.clicked.connect(ao_clicar)

    def _resolver_paleta(self) -> None:
        self._paleta = PALETAS.get(settings_mod.obter_tema(), PALETAS[TEMA_ESCURO])

    def changeEvent(self, evento: QEvent) -> None:
        # trocar o tema reaplica o stylesheet do app inteiro, o que manda
        # StyleChange pra todo widget - aqui e o sinal pra reler as cores
        if evento.type() == QEvent.Type.StyleChange:
            self._resolver_paleta()
            self.update()
        super().changeEvent(evento)

    def enterEvent(self, evento) -> None:
        self.update()
        super().enterEvent(evento)

    def leaveEvent(self, evento) -> None:
        self.update()
        super().leaveEvent(evento)

    def _cor_do_icone(self) -> QColor:
        if not self.isEnabled():
            cor = QColor(self._paleta["texto_secundario"])
            cor.setAlpha(_ALPHA_DESABILITADO)
            return cor
        if self.underMouse() or self.isDown():
            return QColor(self._paleta["texto"])
        cor = QColor(self._paleta["texto_secundario"])
        cor.setAlpha(_ALPHA_REPOUSO)
        return cor

    def paintEvent(self, _evento) -> None:
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self.isEnabled() and (self.underMouse() or self.isDown()):
            fundo = QColor(self._paleta["borda"])
            fundo.setAlpha(210 if self.isDown() else 140)
            pintor.setPen(Qt.PenStyle.NoPen)
            pintor.setBrush(fundo)
            pintor.drawRoundedRect(QRectF(self.rect()), 5, 5)

        desenhar_icone(pintor, self._nome_icone, _AREA_ICONE, self._cor_do_icone())

        if self.hasFocus():  # so por teclado (ver setFocusPolicy)
            pintor.setPen(QPen(QColor(self._paleta["destaque"]), 1))
            pintor.setBrush(Qt.BrushStyle.NoBrush)
            pintor.drawRoundedRect(QRectF(0.5, 0.5, _LADO - 1, _LADO - 1), 5, 5)
