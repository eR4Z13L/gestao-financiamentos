"""Cartao de um bloco do dashboard: titulo, uma legenda opcional embaixo dele, uma acao opcional na
ponta direita do cabecalho (ex.: "Ver todas") e o corpo, um layout vertical que a tela enche e
esvazia a cada atualizacao dos dados.
"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from desktop import settings as settings_mod
from desktop.widgets.shadow import aplicar_sombra_suave


class CartaoDoPainel(QFrame):
    def __init__(self, titulo: str, legenda: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("role", "card")
        aplicar_sombra_suave(self, settings_mod.obter_tema())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        cabecalho = QHBoxLayout()
        cabecalho.setSpacing(8)
        self._titulo = QLabel(titulo)
        self._titulo.setProperty("role", "subtitulo")
        cabecalho.addWidget(self._titulo)
        cabecalho.addStretch()
        self._cabecalho = cabecalho
        layout.addLayout(cabecalho)

        self._legenda = QLabel("")
        self._legenda.setProperty("role", "secundario")
        self._legenda.setWordWrap(True)
        self._legenda.setVisible(False)
        layout.addWidget(self._legenda)
        self.definir_legenda(legenda)

        self.corpo = QVBoxLayout()
        self.corpo.setSpacing(4)
        layout.addLayout(self.corpo)
        layout.addStretch(1)  # dois cartoes lado a lado tem a mesma altura: a sobra fica no fim, nao entre as linhas

    def titulo(self) -> str:
        return self._titulo.text()

    def definir_titulo(self, texto: str) -> None:
        self._titulo.setText(texto)

    def legenda(self) -> str:
        return self._legenda.text()

    def definir_legenda(self, texto: str) -> None:
        self._legenda.setText(texto)
        self._legenda.setVisible(bool(texto))

    def adicionar_acao(self, widget: QWidget) -> None:
        """Poe `widget` na ponta direita do cabecalho."""
        self._cabecalho.addWidget(widget)

    def limpar_corpo(self) -> None:
        """Tira tudo do corpo (esconde antes de apagar: um widget so agendado pra apagar continuaria
        desenhado como um "fantasma" ate o proximo ciclo de eventos)."""
        while self.corpo.count():
            item = self.corpo.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
