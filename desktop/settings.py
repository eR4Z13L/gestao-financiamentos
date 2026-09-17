"""Preferencias do usuario (tema, barra lateral recolhida) - persistidas via
QSettings (mecanismo padrao do Qt; no Windows fica no registro, dentro de
HKEY_CURRENT_USER\\Software, sob o usuario atual - nao mexe na planilha nem
em nenhum arquivo do projeto).
"""

from __future__ import annotations

from PySide6.QtCore import QSettings

from desktop.theme import TEMA_CLARO, TEMA_ESCURO

_ORGANIZACAO = "GestaoFinanciamentos"
_APLICACAO = "Desktop"


def _settings() -> QSettings:
    # passa organizacao/aplicativo direto pro construtor, em vez de depender
    # de QCoreApplication.setOrganizationName()/setApplicationName() - o Qt
    # preenche applicationName() sozinho com o nome do executavel (python,
    # pythonw, GestaoFinanciamentos.exe...) antes do nosso codigo rodar, o
    # que fragmentava as preferencias num local de registro diferente pra
    # cada jeito de abrir o app (python direto, .bat, ou o .exe empacotado)
    return QSettings(_ORGANIZACAO, _APLICACAO)


def obter_tema() -> str:
    valor = _settings().value("tema", TEMA_ESCURO)
    return valor if valor in (TEMA_ESCURO, TEMA_CLARO) else TEMA_ESCURO


def definir_tema(tema: str) -> None:
    _settings().setValue("tema", tema)


def obter_sidebar_recolhida() -> bool:
    valor = _settings().value("sidebar_recolhida", False)
    # QSettings as vezes devolve string "true"/"false" em vez de bool,
    # dependendo do backend de armazenamento usado
    if isinstance(valor, str):
        return valor.strip().lower() == "true"
    return bool(valor)


def definir_sidebar_recolhida(recolhida: bool) -> None:
    _settings().setValue("sidebar_recolhida", recolhida)
