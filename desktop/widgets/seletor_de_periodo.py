"""Seletor de periodo do dashboard: uma fileira de botoes (Hoje, 7 dias, 30 dias, Mes, Tudo) onde so um
fica marcado. `periodo_alterado` traz a chave (core.dashboard.PERIODO_*).
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget

from core import dashboard as dashboard_mod


class SeletorDePeriodo(QWidget):
    periodo_alterado = Signal(str)

    def __init__(self, periodo: str = dashboard_mod.PERIODO_PADRAO, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("role", "transparente")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)  # colados, como um controle so

        self._grupo = QButtonGroup(self)
        self._grupo.setExclusive(True)
        self._botoes: dict[str, QPushButton] = {}
        ultimo = len(dashboard_mod.PERIODOS) - 1
        for i, (chave, rotulo) in enumerate(dashboard_mod.PERIODOS):
            botao = QPushButton(rotulo)
            botao.setCheckable(True)
            botao.setProperty("role", "segmento")
            botao.setProperty("posicao", "primeiro" if i == 0 else "ultimo" if i == ultimo else "meio")
            botao.setAutoDefault(False)
            self._grupo.addButton(botao)
            self._botoes[chave] = botao
            layout.addWidget(botao)
            botao.clicked.connect(lambda _marcado, c=chave: self.periodo_alterado.emit(c))
        self._botoes[periodo].setChecked(True)

    def periodo(self) -> str:
        return next(c for c, b in self._botoes.items() if b.isChecked())

    def definir_periodo(self, periodo: str) -> None:
        """Marca `periodo` sem avisar (quem chama ja sabe)."""
        self._botoes[periodo].setChecked(True)

    def botao(self, periodo: str) -> QPushButton:
        return self._botoes[periodo]
