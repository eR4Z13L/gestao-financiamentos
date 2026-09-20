"""Preferencias do usuario (tema, barra lateral recolhida, ultima tela aberta, tamanho e
posicao da janela) - persistidas via
QSettings (mecanismo padrao do Qt; no Windows fica no registro, dentro de
HKEY_CURRENT_USER\\Software, sob o usuario atual - nao mexe na planilha nem
em nenhum arquivo do projeto).
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSettings

from desktop.theme import TEMA_CLARO, TEMA_ESCURO

_ORGANIZACAO = "GestaoFinanciamentos"
_APLICACAO = "Desktop"


def _settings() -> QSettings:
    # passa organizacao/aplicativo direto pro construtor, em vez de depender
    # de QCoreApplication.setOrganizationName()/setApplicationName() - o Qt
    # preenche applicationName() sozinho com o nome do executavel (python,
    # pythonw, GestaoFinanciamentos.exe...) antes do nosso codigo rodar, o
    # que fragmentava as preferencias num local de registro diferente pra
    # cada jeito de abrir o app (python direto, .bat, ou o .exe empacotado).
    # O formato e o padrao do Qt (registro do Windows) - e explicito so pra os testes poderem
    # trocar por um .ini temporario (QSettings.setDefaultFormat): o construtor de dois
    # argumentos ignora essa troca e gravaria no registro de verdade.
    return QSettings(QSettings.defaultFormat(), QSettings.Scope.UserScope, _ORGANIZACAO, _APLICACAO)


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


def obter_ultima_tela() -> str | None:
    """A chave da ultima tela aberta (ex.: "propostas"), ou None se nunca gravou. Quem le
    confere se a tela ainda existe pra este usuario (o VENDEDOR nao tem Administracao)."""
    valor = _settings().value("ultima_tela")
    return valor if isinstance(valor, str) and valor else None


def definir_ultima_tela(chave: str) -> None:
    _settings().setValue("ultima_tela", chave)


def obter_geometria_janela() -> QByteArray | None:
    """Tamanho, posicao e estado (maximizada ou nao) da janela principal como o Qt os
    salvou (saveGeometry); None se nunca gravou ou se o valor guardado nao e utilizavel."""
    valor = _settings().value("geometria_janela")
    if isinstance(valor, (bytes, bytearray)):
        valor = QByteArray(bytes(valor))
    if isinstance(valor, QByteArray) and not valor.isEmpty():
        return valor
    return None


def definir_geometria_janela(geometria: QByteArray) -> None:
    _settings().setValue("geometria_janela", geometria)
