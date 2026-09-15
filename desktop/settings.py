"""Preferencias do usuario (tema, barra lateral recolhida) - persistidas via
QSettings (mecanismo padrao do Qt; no Windows fica no registro, dentro de
HKEY_CURRENT_USER\\Software, sob o usuario atual - nao mexe na planilha nem
em nenhum arquivo do projeto).
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QSettings

from desktop.theme import TEMA_CLARO, TEMA_ESCURO

_ORGANIZACAO = "GestaoFinanciamentos"
_APLICACAO = "Desktop"


def _settings() -> QSettings:
    # garante que organizationName/applicationName estao definidos mesmo se
    # settings.py for usado antes de desktop/main.py rodar (ex: em testes)
    if not QCoreApplication.organizationName():
        QCoreApplication.setOrganizationName(_ORGANIZACAO)
    if not QCoreApplication.applicationName():
        QCoreApplication.setApplicationName(_APLICACAO)
    return QSettings()


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
