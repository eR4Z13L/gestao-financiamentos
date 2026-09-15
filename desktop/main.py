"""Ponto de entrada do aplicativo desktop.

Rodar a partir da raiz do projeto com:
    venv\\Scripts\\python.exe -m desktop.main
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication

from desktop import settings as settings_mod
from desktop.main_window import MainWindow
from desktop.theme import build_stylesheet


def main() -> None:
    app = QApplication(sys.argv)
    # settings_mod ja garante organizationName/applicationName antes de ler
    app.setStyleSheet(build_stylesheet(settings_mod.obter_tema()))

    janela = MainWindow()
    janela.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
