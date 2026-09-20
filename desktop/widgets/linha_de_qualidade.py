"""Uma linha da "Qualidade dos dados": em cima o nome do campo, "63% · 37 de 59" e, se falta alguma, o link
"Ver 22" que abre a lista das pendentes; embaixo uma barra do quanto esta preenchido (desenhada por codigo,
na cor do tema). A cor da barra diz a gravidade: verde (tudo preenchido), cor de destaque (a maior parte) ou
ambar (menos da metade).
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from core.dashboard import CampoDeQualidade
from desktop.widgets.paleta_do_tema import UsaPaletaDoTema

_LIMITE_AMBAR = 50.0


class _Trilho(UsaPaletaDoTema, QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._resolver_paleta()
        self._percentual: float | None = None
        self.setFixedHeight(10)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def definir_percentual(self, percentual: float | None) -> None:
        self._percentual = percentual
        self.update()

    def percentual(self) -> float | None:
        return self._percentual

    def cor_do_preenchimento(self) -> QColor:
        if self._percentual is not None and self._percentual >= 100.0:
            return QColor(self._paleta["sucesso"])
        if self._percentual is not None and self._percentual < _LIMITE_AMBAR:
            return QColor(self._cores_de_status["em_analise"]["faixa"])
        return QColor(self._paleta["destaque"])

    def sizeHint(self) -> QSize:
        return QSize(120, 10)

    def paintEvent(self, _evento) -> None:
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = QRectF(self.rect())
        trilho = QColor(self._paleta["borda"])
        trilho.setAlpha(110)
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(trilho)
        pintor.drawRoundedRect(area, 5, 5)
        if self._percentual:
            pintor.setBrush(self.cor_do_preenchimento())
            pintor.drawRoundedRect(QRectF(area.left(), area.top(), max(area.width() * self._percentual / 100, 10.0), area.height()), 5, 5)


class LinhaDeQualidade(QWidget):
    pendentes_pedidas = Signal(str)  # a chave do campo (CampoDeQualidade.chave)

    def __init__(self, campo: CampoDeQualidade, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("role", "transparente")
        self._chave = campo.chave

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 4)
        layout.setSpacing(4)

        # em cima: o campo, "63% · 37 de 59" e o link; embaixo, a barra na largura toda
        cima = QHBoxLayout()
        cima.setSpacing(10)
        self._rotulo = QLabel(campo.rotulo)
        cima.addWidget(self._rotulo, stretch=1)

        texto = "—" if campo.percentual is None else f"{campo.percentual:.0f}% · {campo.preenchidos} de {campo.total}"
        self._valor = QLabel(texto)
        self._valor.setProperty("role", "secundario")
        cima.addWidget(self._valor)

        pendentes = len(campo.indices_pendentes)
        self._botao = QPushButton(f"Ver {pendentes}")
        self._botao.setProperty("role", "botao_link")
        self._botao.setCursor(Qt.CursorShape.PointingHandCursor)
        self._botao.setToolTip(f"Abre a lista das {pendentes} proposta(s) com {campo.rotulo.lower()} em branco")
        self._botao.setFixedWidth(52)
        self._botao.clicked.connect(lambda: self.pendentes_pedidas.emit(self._chave))
        self._botao.setVisible(pendentes > 0)
        cima.addWidget(self._botao)
        if pendentes == 0:
            # sem pendentes o botao some, mas o lugar dele fica: os textos de todas as linhas terminam alinhados
            espaco = QWidget()
            espaco.setProperty("role", "transparente")
            espaco.setFixedWidth(52)
            cima.addWidget(espaco)
        layout.addLayout(cima)

        self.trilho = _Trilho()
        self.trilho.definir_percentual(campo.percentual)
        layout.addWidget(self.trilho)

    def chave(self) -> str:
        return self._chave

    def texto_do_valor(self) -> str:
        return self._valor.text()

    def botao_de_pendentes(self) -> QPushButton:
        return self._botao
