"""Rotulo que ocupa so a largura do proprio texto, numa linha - e so QUEBRA em
mais linhas quando nao cabe (ex.: um endereco muito longo numa janela estreita).

Um QLabel comum com quebra de linha pede uma largura "de compromisso" (varias
linhas) e, num layout, ou fica assim ou estica pela largura toda. Aqui o
tamanho pedido e o de UMA linha, entao, ao lado de um botao (ex.: copiar) e de
um espacador, o rotulo fica do tamanho do texto e o botao logo depois dele.
"""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QLabel, QWidget

_ESPACO_LARGURA_ZERO = "​"  # ponto de quebra invisivel (ver quebra_texto.py): nao ocupa largura
_FOLGA = 4  # px a mais que o texto: sem folga, um arredondamento da fonte quebra a linha por 1 px


class RotuloUmaLinha(QLabel):
    def __init__(self, texto: str = "", parent: QWidget | None = None):
        super().__init__(texto, parent)
        self.setWordWrap(True)  # so pra poder quebrar quando nao couber (o tamanho ideal e o de uma linha)

    def sizeHint(self) -> QSize:
        self.ensurePolished()  # a fonte do tema (QSS) so vale depois de aplicada
        texto = self.text().replace(_ESPACO_LARGURA_ZERO, "")
        largura = self.fontMetrics().horizontalAdvance(texto) + 2 * (self.margin() + self.frameWidth()) + _FOLGA
        return QSize(largura, self.heightForWidth(largura))
