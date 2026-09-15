"""Cartao de metrica reaproveitavel (titulo pequeno + valor grande) - usado
no Dashboard e, provavelmente, em telas futuras que precisem do mesmo formato.
"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


class MetricCard(QFrame):
    def __init__(self, titulo: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("role", "card")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        legenda = QLabel(titulo)
        legenda.setProperty("role", "secundario")
        legenda.setWordWrap(True)
        layout.addWidget(legenda)

        self._valor = QLabel("—")
        self._valor.setProperty("role", "valor_metrica")
        layout.addWidget(self._valor)

    def definir_valor(self, texto: str) -> None:
        self._valor.setText(texto)
