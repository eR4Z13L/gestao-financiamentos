"""Titulo de secao que abre e fecha o conteudo logo abaixo (um "acordeao"): o
titulo + uma seta depois dele, tudo clicavel. Marcado (`isChecked()`) = aberto;
o sinal `toggled(bool)` avisa a mudanca, e quem usa mostra/esconde o conteudo.
Da pra usar so pelo teclado (Tab foca, Espaco alterna).

O titulo e um QLabel de verdade, com o papel (`role`) que se escolher: assim o
tema o estiliza como qualquer outro rotulo (ex.: "campo_rotulo" deixa o titulo
igual as legendas dos campos da ficha, "subtitulo" igual aos subtitulos). Ele
e transparente ao mouse: o clique cai no proprio cabecalho.

A seta e desenhada por codigo, como no BotaoCopiar: o QSS nao sabe colorir uma
seta, e assim ela usa as cores do tema ativo e se refaz sozinha quando o tema
muda com o app aberto. Fechado a seta aponta pra baixo ("abre pra baixo"),
aberto pra cima.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QLabel, QSizePolicy, QWidget

from desktop import settings as settings_mod
from desktop.theme import PALETAS, TEMA_ESCURO

_ESPACO_ANTES_DA_SETA = 4
_AREA_DA_SETA = 16  # largura reservada pra seta, depois do titulo


class CabecalhoRetratil(QAbstractButton):
    def __init__(
        self,
        titulo: str,
        dica_expandir: str = "Mostrar",
        dica_recolher: str = "Recolher",
        expandido: bool = False,
        papel_do_titulo: str = "subtitulo",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._dica_expandir = dica_expandir
        self._dica_recolher = dica_recolher
        self._resolver_paleta()

        self._rotulo = QLabel(titulo)
        self._rotulo.setProperty("role", papel_do_titulo)
        self._rotulo.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, _ESPACO_ANTES_DA_SETA + _AREA_DA_SETA, 0)
        layout.setSpacing(0)
        layout.addWidget(self._rotulo)

        self.setCheckable(True)
        self.setChecked(expandido)
        self.setAccessibleName(titulo)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # so o teclado (Tab) foca: um clique de mouse nao deixa um anel de foco "preso"
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.toggled.connect(self._atualizar_dica)
        self._atualizar_dica()

    def _atualizar_dica(self, *_args) -> None:
        self.setToolTip(self._dica_recolher if self.isChecked() else self._dica_expandir)

    # -- desenho -----------------------------------------------------------------

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

    def paintEvent(self, _evento) -> None:
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        # a seta tem a cor do titulo (secundaria, como as legendas); com o mouse em cima, a de destaque
        cor = QColor(self._paleta["destaque"] if self.underMouse() else self._paleta["texto_secundario"])

        meio_x = self._rotulo.geometry().right() + _ESPACO_ANTES_DA_SETA + _AREA_DA_SETA / 2
        meio_y = self.height() / 2
        if self.isChecked():  # aberto: aponta pra cima
            pontos = [QPointF(meio_x - 4, meio_y + 2.5), QPointF(meio_x, meio_y - 2.5), QPointF(meio_x + 4, meio_y + 2.5)]
        else:  # fechado: aponta pra baixo
            pontos = [QPointF(meio_x - 4, meio_y - 2.5), QPointF(meio_x, meio_y + 2.5), QPointF(meio_x + 4, meio_y - 2.5)]
        pintor.setBrush(Qt.BrushStyle.NoBrush)
        pintor.setPen(QPen(cor, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        pintor.drawPolyline(QPolygonF(pontos))

        if self.hasFocus():  # so por teclado (ver setFocusPolicy)
            pintor.setBrush(Qt.BrushStyle.NoBrush)
            pintor.setPen(QPen(QColor(self._paleta["destaque"]), 1))
            pintor.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 4, 4)
