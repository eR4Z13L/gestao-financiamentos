"""QComboBox que pode ficar "somente leitura": mostra o valor dentro da mesma
caixa de sempre (com o texto selecionavel/copiavel), mas o usuario nao consegue
trocar a opcao. O Qt nao tem isso pronto - QComboBox so tem "desabilitado",
que apaga a caixa e impede ate de selecionar o texto.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent, QWheelEvent
from PySide6.QtWidgets import QComboBox, QWidget

_TECLAS_QUE_TROCAM_OPCAO = (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown)


class ComboTravavel(QComboBox):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._travado = False
        self._era_editavel = False

    def travado(self) -> bool:
        return self._travado

    def definir_travado(self, travar: bool) -> None:
        if travar == self._travado:
            return
        self._travado = travar
        if travar:
            # so um combo editavel mostra o texto numa caixa de texto que da
            # pra selecionar - entao o nao-editavel vira editavel (com a caixa
            # de texto travada) enquanto estiver travado
            self._era_editavel = self.isEditable()
            if not self._era_editavel:
                self.setEditable(True)
            self.lineEdit().setReadOnly(True)
        else:
            self.lineEdit().setReadOnly(False)
            if not self._era_editavel:
                self.setEditable(False)
        # o QSS (desktop/theme.py) esconde a seta de abrir a lista nos travados
        self.setProperty("travado", travar)
        self.style().unpolish(self)
        self.style().polish(self)

    def showPopup(self) -> None:
        if not self._travado:
            super().showPopup()

    def wheelEvent(self, evento: QWheelEvent) -> None:
        if self._travado:
            evento.ignore()
            return
        super().wheelEvent(evento)

    def keyPressEvent(self, evento: QKeyEvent) -> None:
        if self._travado and evento.key() in _TECLAS_QUE_TROCAM_OPCAO:
            evento.ignore()
            return
        super().keyPressEvent(evento)
