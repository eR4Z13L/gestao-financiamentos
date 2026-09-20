"""Quem esta logado, na barra lateral: um avatar (circulo com as iniciais) e, ao lado, o nome e
o nivel de acesso. Recolhido, so o avatar (o nome e o acesso vao no tooltip).

O avatar e desenhado por codigo (como o BotaoCopiar) pra usar a cor de destaque do tema ativo
e se refazer sozinho quando o tema muda.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from core.formatting import iniciais_do_nome
from desktop import settings as settings_mod
from desktop.theme import PALETAS, TEMA_ESCURO

_LADO_AVATAR = 34


class _Avatar(QWidget):
    def __init__(self, iniciais: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._iniciais = iniciais
        self._resolver_paleta()
        self.setFixedSize(_LADO_AVATAR, _LADO_AVATAR)

    def definir_iniciais(self, iniciais: str) -> None:
        self._iniciais = iniciais
        self.update()

    def iniciais(self) -> str:
        return self._iniciais

    def _resolver_paleta(self) -> None:
        self._paleta = PALETAS.get(settings_mod.obter_tema(), PALETAS[TEMA_ESCURO])

    def changeEvent(self, evento: QEvent) -> None:
        if evento.type() == QEvent.Type.StyleChange:
            self._resolver_paleta()
            self.update()
        super().changeEvent(evento)

    def sizeHint(self) -> QSize:
        return QSize(_LADO_AVATAR, _LADO_AVATAR)

    def paintEvent(self, _evento) -> None:
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(QColor(self._paleta["destaque"]))
        pintor.drawEllipse(QRectF(self.rect()))
        fonte = QFont(self.font())
        fonte.setPixelSize(13)
        fonte.setWeight(QFont.Weight.Bold)
        pintor.setFont(fonte)
        pintor.setPen(QColor("white"))
        pintor.drawText(QRectF(self.rect()), Qt.AlignmentFlag.AlignCenter, self._iniciais)


class _RotuloElidido(QLabel):
    """Uma linha so; o que nao couber vira "…" (nome de vendedor comprido nao pode esticar a
    barra lateral). O tooltip traz o texto inteiro."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._completo = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def definir_texto(self, texto: str) -> None:
        self._completo = texto
        self.setToolTip(texto)
        self._reelidir()

    def texto_completo(self) -> str:
        return self._completo

    def resizeEvent(self, evento) -> None:
        super().resizeEvent(evento)
        self._reelidir()

    def _reelidir(self) -> None:
        self.setText(self.fontMetrics().elidedText(self._completo, Qt.TextElideMode.ElideRight, max(self.width(), 0)))


class IdentidadeUsuario(QWidget):
    def __init__(self, nome: str, acesso: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("role", "transparente")
        self._nome = nome
        self._acesso = acesso

        self._avatar = _Avatar(iniciais_do_nome(nome))
        self._rotulo_nome = _RotuloElidido()
        self._rotulo_nome.setProperty("role", "nome_do_usuario")
        self._rotulo_acesso = _RotuloElidido()
        self._rotulo_acesso.setProperty("role", "secundario")
        self._rotulo_nome.definir_texto(nome)
        self._rotulo_acesso.definir_texto(acesso)

        textos = QWidget()
        textos.setProperty("role", "transparente")
        layout_textos = QVBoxLayout(textos)
        layout_textos.setContentsMargins(0, 0, 0, 0)
        layout_textos.setSpacing(0)
        layout_textos.addWidget(self._rotulo_nome)
        layout_textos.addWidget(self._rotulo_acesso)
        self._textos = textos

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._avatar)
        layout.addWidget(textos, stretch=1)
        self.definir_recolhido(False)

    def nome(self) -> str:
        return self._nome

    def acesso(self) -> str:
        return self._acesso

    def iniciais(self) -> str:
        return self._avatar.iniciais()

    def textos_visiveis(self) -> bool:
        return not self._textos.isHidden()

    def definir_recolhido(self, recolhido: bool) -> None:
        self._textos.setVisible(not recolhido)
        self.setToolTip(f"{self._nome} — {self._acesso}" if recolhido else "")
        layout = self.layout()
        layout.setAlignment(self._avatar, Qt.AlignmentFlag.AlignHCenter if recolhido else Qt.AlignmentFlag.AlignLeft)
