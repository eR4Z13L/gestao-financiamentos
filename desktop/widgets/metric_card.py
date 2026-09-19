"""Cartao de metrica reaproveitavel (titulo pequeno + valor grande) - usado
no Dashboard e, provavelmente, em telas futuras que precisem do mesmo formato.
"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from desktop import settings as settings_mod
from desktop.widgets.shadow import aplicar_sombra_suave


class MetricCard(QFrame):
    def __init__(self, titulo: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("role", "card")
        aplicar_sombra_suave(self, settings_mod.obter_tema())

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

        # linha pequena opcional abaixo do valor (ex.: a porcentagem que
        # acompanha um numero absoluto) - so aparece se definir_detalhe() for chamado
        self._detalhe = QLabel("")
        self._detalhe.setProperty("role", "secundario")
        self._detalhe.setWordWrap(True)
        self._detalhe.setVisible(False)
        layout.addWidget(self._detalhe)

    def definir_valor(self, texto: str) -> None:
        self._valor.setText(texto)

    def definir_detalhe(self, texto: str) -> None:
        self._detalhe.setText(texto)
        self._detalhe.setVisible(bool(texto))
