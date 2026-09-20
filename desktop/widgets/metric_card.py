"""Cartao de metrica reaproveitavel (titulo pequeno + valor grande) - usado
no Dashboard e, provavelmente, em telas futuras que precisem do mesmo formato.

Abaixo do valor ha duas linhas opcionais: o detalhe ("R$ 927.000,00 · so 10 tem valor"), que pode ir
em destaque de aviso (ambar) quando o numero merece atencao, e a comparacao com o periodo anterior.
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
        self._legenda = legenda

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

        # a diferenca contra o periodo anterior ("▲ +3 vs. os 7 dias anteriores"): so quando da pra comparar
        self._comparacao = QLabel("")
        self._comparacao.setProperty("role", "secundario")
        self._comparacao.setWordWrap(True)
        self._comparacao.setVisible(False)
        layout.addWidget(self._comparacao)

    def titulo(self) -> str:
        return self._legenda.text()

    def valor(self) -> str:
        return self._valor.text()

    def detalhe(self) -> str:
        return self._detalhe.text()

    def comparacao(self) -> str:
        return self._comparacao.text()

    def detalhe_em_aviso(self) -> bool:
        return self._detalhe.property("role") == "aviso"

    def definir_valor(self, texto: str) -> None:
        self._valor.setText(texto)

    def definir_detalhe(self, texto: str, aviso: bool = False) -> None:
        """`aviso`: o detalhe aparece em destaque (ambar, negrito) - pro que o numero sozinho esconde."""
        self._detalhe.setText(texto)
        self._detalhe.setVisible(bool(texto))
        papel = "aviso" if aviso else "secundario"
        if self._detalhe.property("role") != papel:
            self._detalhe.setProperty("role", papel)
            self._detalhe.style().unpolish(self._detalhe)  # o QSS so reavalia a propriedade depois disto
            self._detalhe.style().polish(self._detalhe)

    def definir_comparacao(self, texto: str) -> None:
        self._comparacao.setText(texto)
        self._comparacao.setVisible(bool(texto))
