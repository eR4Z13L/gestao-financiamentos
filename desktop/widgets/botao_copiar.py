"""Botao "copiar" discreto pra por ao lado de um campo somente-leitura: so um
icone pequeno (dois retangulos sobrepostos), sem borda nem preenchimento em
repouso - so ganha um fundo leve quando o mouse passa por cima. Ao clicar,
copia o texto do campo pra area de transferencia e o proprio icone vira um
"check" por um instante (com um tooltip "Copiado!"), sem abrir popup e sem
mudar o tamanho do botao - o layout em volta nao se mexe.

O icone e desenhado por codigo (nao e emoji nem imagem) porque o QSS nao sabe
colorir icone: ele usa as cores do tema ativo e se refaz sozinho quando o tema
muda (as telas vivem a sessao toda, e o tema pode ser trocado com o app aberto).
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QAbstractButton, QApplication, QToolTip, QWidget

from desktop import settings as settings_mod
from desktop.theme import PALETAS, TEMA_ESCURO

ESTADO_NORMAL = "normal"
ESTADO_COPIADO = "copiado"
ESTADO_VAZIO = "vazio"

DICA_PADRAO = "Copiar"
DICA_COPIADO = "Copiado!"
DICA_VAZIO = "Campo vazio, nada para copiar"
DURACAO_FEEDBACK_MS = 1200

_LADO = 24  # o botao e um quadrado de 24px; o desenho todo cabe nessa area
_ALPHA_REPOUSO = 140  # icone em repouso fica apagado (0-255) pra nao competir com o dado


class BotaoCopiar(QAbstractButton):
    def __init__(self, obter_texto: Callable[[], str], parent: QWidget | None = None):
        """`obter_texto` e chamado a cada clique (nao uma vez so, na criacao),
        pra copiar o valor atual do campo mesmo que ele tenha mudado."""
        super().__init__(parent)
        self._obter_texto = obter_texto
        self._resolver_paleta()
        self.estado = ESTADO_NORMAL

        self.setFixedSize(_LADO, _LADO)
        self.setToolTip(DICA_PADRAO)
        self.setAccessibleName(DICA_PADRAO)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # so o teclado (Tab) foca o botao - um clique de mouse nao deixa um
        # anel de foco "preso" nele
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        self._temporizador = QTimer(self)  # filho do botao: morre junto com ele
        self._temporizador.setSingleShot(True)
        self._temporizador.timeout.connect(self._restaurar)

        self.clicked.connect(self._copiar)

    # -- comportamento -----------------------------------------------------------

    def _copiar(self) -> None:
        texto = self._obter_texto()
        if not texto:
            # campo em branco: nao apaga o que o usuario tinha copiado antes
            self._mostrar_feedback(ESTADO_VAZIO, DICA_VAZIO)
            return
        QApplication.clipboard().setText(texto)
        self._mostrar_feedback(ESTADO_COPIADO, DICA_COPIADO)

    def _mostrar_feedback(self, estado: str, dica: str) -> None:
        self.estado = estado
        self.setToolTip(dica)
        self.update()
        # tooltip mostrado na hora (o padrao so aparece depois de uns instantes
        # parado em cima) e que some sozinho junto com o feedback do icone
        QToolTip.showText(self.mapToGlobal(QPoint(0, self.height())), dica, self, QRect(), DURACAO_FEEDBACK_MS)
        self._temporizador.start(DURACAO_FEEDBACK_MS)  # reinicia se clicar de novo antes de acabar

    def _restaurar(self) -> None:
        self.estado = ESTADO_NORMAL
        self.setToolTip(DICA_PADRAO)
        self.update()

    # -- desenho -----------------------------------------------------------------

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
        if self.estado == ESTADO_COPIADO:
            return QColor(self._paleta["sucesso"])
        if self.estado == ESTADO_VAZIO:
            return QColor(self._paleta["erro"])
        if self.underMouse() or self.isDown():
            return QColor(self._paleta["texto"])
        cor = QColor(self._paleta["texto_secundario"])
        cor.setAlpha(_ALPHA_REPOUSO)
        return cor

    def paintEvent(self, _evento) -> None:
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self.underMouse() or self.isDown():
            fundo = QColor(self._paleta["borda"])
            fundo.setAlpha(210 if self.isDown() else 140)
            pintor.setPen(Qt.PenStyle.NoPen)
            pintor.setBrush(fundo)
            pintor.drawRoundedRect(QRectF(self.rect()), 5, 5)

        cor = self._cor_do_icone()
        pintor.setBrush(Qt.BrushStyle.NoBrush)
        if self.estado == ESTADO_COPIADO:
            pintor.setPen(QPen(cor, 1.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            pintor.drawPolyline(QPolygonF([QPointF(7, 12.5), QPointF(10.5, 16), QPointF(17, 8.5)]))
        else:
            pintor.setPen(QPen(cor, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            # folha de tras: so as bordas que a folha da frente nao cobre
            pintor.drawPolyline(
                QPolygonF([QPointF(9.5, 15.5), QPointF(6.5, 15.5), QPointF(6.5, 6.5), QPointF(15.5, 6.5), QPointF(15.5, 9.5)])
            )
            pintor.drawRoundedRect(QRectF(9.5, 9.5, 8, 8), 1.5, 1.5)  # folha da frente

        if self.hasFocus():  # so por teclado (ver setFocusPolicy)
            pintor.setPen(QPen(QColor(self._paleta["destaque"]), 1))
            pintor.drawRoundedRect(QRectF(0.5, 0.5, _LADO - 1, _LADO - 1), 5, 5)
