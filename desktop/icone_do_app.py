"""Icone do app nas janelas (barra de titulo e barra de tarefas do Windows).

O mesmo desktop/assets/icone_app.ico do .exe e do instalador. Aplicado no QApplication, vale para
todas as janelas, inclusive o login, que abre antes da principal.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

_logger = logging.getLogger(__name__)

# Identifica o app no Windows. Rodando pelo Python, sem isso a barra de tarefas agrupa a janela
# como "python" e mostra o icone do Python no lugar do nosso.
ID_DO_APP_NO_WINDOWS = "GestaoFinanciamentos.App"


def caminho_do_icone() -> Path:
    # no .exe o arquivo vai junto (datas do .spec) e e extraido em sys._MEIPASS
    raiz = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return raiz / "desktop" / "assets" / "icone_app.ico"


def _identificar_app_no_windows() -> None:
    if sys.platform != "win32":
        return
    import ctypes

    try:
        resultado = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(ID_DO_APP_NO_WINDOWS)
    except Exception as exc:  # nunca falhar em silencio, mas um icone nao impede o app de abrir
        _logger.warning("Não foi possível identificar o app no Windows (barra de tarefas): %s", exc)
        return
    if resultado != 0:  # HRESULT diferente de S_OK
        _logger.warning("O Windows recusou a identificação do app (barra de tarefas): HRESULT %#x",
                        resultado & 0xFFFFFFFF)


def aplicar_icone_do_app(app: QApplication) -> bool:
    """Poe o icone em todas as janelas do app. Chamar logo depois de criar o QApplication e antes de
    abrir qualquer janela. False (e um aviso no log) se o icone nao pode ser carregado."""
    _identificar_app_no_windows()
    caminho = caminho_do_icone()
    icone = QIcon(str(caminho))
    if icone.isNull():
        _logger.warning("Ícone do app não encontrado ou ilegível: %s", caminho)
        return False
    app.setWindowIcon(icone)
    return True
