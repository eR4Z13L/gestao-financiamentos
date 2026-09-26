"""Marca um campo (QLineEdit, QComboBox...) como invalido - borda vermelha (QSS,
propriedade "invalido" em desktop/theme.py) + o motivo no tooltip. Reutilizavel em
qualquer formulario com validacao por campo (ex.: Ficha de Cliente editavel), com
o motivo tambem visivel (passar o mouse), nao so a borda.
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget


def marcar_invalido(campo: QWidget, mensagem: str) -> None:
    campo.setProperty("invalido", True)
    campo.setToolTip(mensagem)
    campo.style().unpolish(campo)
    campo.style().polish(campo)


def limpar_invalido(campo: QWidget) -> None:
    campo.setProperty("invalido", False)
    campo.setToolTip("")
    campo.style().unpolish(campo)
    campo.style().polish(campo)
