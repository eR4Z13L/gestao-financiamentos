"""Botao de uma linha da barra lateral (icone de linha + rotulo), sem borda em repouso; ganha um
fundo leve com o mouse. Recolhido, so o icone. Todos os botoes do rodape (tema, sair) e o
indicador de sincronizacao sao desenhados por esta mesma classe, entao ficam alinhados
pixel a pixel e mudam juntos com o tema.

E desenhado por codigo (como o BotaoCopiar) porque o QSS nao sabe colorir icone.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QSizePolicy, QWidget

from desktop import settings as settings_mod
from desktop.theme import PALETAS, TEMA_ESCURO
from desktop.widgets.icones_linha import desenhar_icone

ALTURA = 38
_MARGEM_ESQUERDA = 12
_LADO_ICONE = 18
_ESPACO_ICONE_TEXTO = 10


class BotaoLateral(QAbstractButton):
    def __init__(self, texto: str, icone: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._icone = icone
        self._recolhido = False
        self._resolver_paleta()
        self.setText(texto)
        self.setAccessibleName(texto)
        self.setFixedHeight(ALTURA)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # so o teclado (Tab) foca: um clique de mouse nao deixa um anel de foco "preso" no botao
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    # -- estado -------------------------------------------------------------------

    def definir_icone(self, icone: str) -> None:
        self._icone = icone
        self.update()

    def icone(self) -> str:
        return self._icone

    def definir_rotulo(self, texto: str) -> None:
        self.setText(texto)
        self.setAccessibleName(texto)
        self.update()

    def esta_recolhido(self) -> bool:
        return self._recolhido

    def definir_recolhido(self, recolhido: bool) -> None:
        self._recolhido = recolhido
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(_MARGEM_ESQUERDA + _LADO_ICONE + _ESPACO_ICONE_TEXTO + self.fontMetrics().horizontalAdvance(self.text()) + 12, ALTURA)

    # -- desenho ------------------------------------------------------------------

    def _resolver_paleta(self) -> None:
        self._paleta = PALETAS.get(settings_mod.obter_tema(), PALETAS[TEMA_ESCURO])

    def changeEvent(self, evento: QEvent) -> None:
        # trocar o tema reaplica o stylesheet do app inteiro (StyleChange): e o sinal pra reler as cores
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

    def _cor_do_conteudo(self) -> QColor:
        ativo = self.underMouse() or self.isDown()
        return QColor(self._paleta["texto"] if ativo else self._paleta["texto_secundario"])

    def _pintar_marca(self, pintor: QPainter, area: QRectF, cor: QColor) -> None:
        """O que vai na coluna do icone (area de 18 x 18). Quem herda troca (ex.: uma bolinha)."""
        desenhar_icone(pintor, self._icone, area, cor)

    def paintEvent(self, _evento) -> None:
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect())

        if self.isDown() or self.underMouse():
            fundo = QColor(self._paleta["borda"] if self.isDown() else self._paleta["bg_card"])
            pintor.setPen(Qt.PenStyle.NoPen)
            pintor.setBrush(fundo)
            pintor.drawRoundedRect(area.adjusted(0, 1, 0, -1), 8, 8)

        cor = self._cor_do_conteudo()
        lado = float(_LADO_ICONE)
        x_icone = area.center().x() - lado / 2 if self._recolhido else area.left() + _MARGEM_ESQUERDA
        self._pintar_marca(pintor, QRectF(x_icone, area.center().y() - lado / 2, lado, lado), cor)

        if not self._recolhido:
            x_texto = area.left() + _MARGEM_ESQUERDA + lado + _ESPACO_ICONE_TEXTO
            largura = max(area.right() - 8 - x_texto, 0.0)
            texto = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, int(largura))
            pintor.setPen(cor)
            pintor.drawText(
                QRectF(x_texto, area.top(), largura, area.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                texto,
            )

        if self.hasFocus():  # so por teclado (ver setFocusPolicy)
            pintor.setBrush(Qt.BrushStyle.NoBrush)
            pintor.setPen(QPen(QColor(self._paleta["destaque"]), 1))
            pintor.drawRoundedRect(area.adjusted(0.5, 1.5, -0.5, -1.5), 8, 8)
