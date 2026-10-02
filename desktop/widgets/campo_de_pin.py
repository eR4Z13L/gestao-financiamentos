"""Campo para digitar o PIN de entrada: so numeros, no maximo core.acesso.TAMANHO_DO_PIN, escondido."""

from __future__ import annotations

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import QLineEdit

from core import acesso


def campo_de_pin() -> QLineEdit:
    campo = QLineEdit()
    campo.setEchoMode(QLineEdit.EchoMode.Password)
    campo.setMaxLength(acesso.TAMANHO_DO_PIN)
    campo.setValidator(QRegularExpressionValidator(QRegularExpression(rf"\d{{0,{acesso.TAMANHO_DO_PIN}}}"), campo))
    campo.setPlaceholderText(f"{acesso.TAMANHO_DO_PIN} números")
    return campo
