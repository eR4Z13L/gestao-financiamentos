"""Ponto de entrada do aplicativo desktop.

Rodar a partir da raiz do projeto com:
    venv\\Scripts\\python.exe -m desktop.main
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from core import sessao as sessao_mod
from desktop import settings as settings_mod
from desktop.dialogs.login_dialog import LoginDialog
from desktop.main_window import MainWindow
from desktop.theme import build_stylesheet


def entrar() -> bool:
    """Mostra o login e, se a pessoa entrar, inicia a sessao. False: cancelou."""
    login = LoginDialog()
    if login.exec() != QDialog.DialogCode.Accepted or login.sessao_criada is None:
        return False
    sessao_mod.iniciar(login.sessao_criada)
    return True


class ControladorDaJanela:
    """Abre a janela principal e cuida do "Sair": encerra a sessao, mostra o login de novo e, se a
    pessoa entrar, abre uma janela nova (montada pro papel dela: o VENDEDOR nao tem Administracao);
    se cancelar o login, fecha o app. Guarda a janela atual (sem uma referencia o Python a apagaria)."""

    def __init__(self, app: QApplication):
        self._app = app
        self.janela: MainWindow | None = None

    def abrir(self) -> bool:
        """Monta e mostra a janela principal. Se ela nao abrir (erro ao ler os dados, por exemplo), avisa
        a pessoa e devolve False: uma excecao solta aqui so iria pro stderr, e sem console (pythonw, .exe)
        o aplicativo simplesmente sumiria, sem explicacao."""
        try:
            janela = MainWindow()
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(
                None,
                "Não foi possível abrir o aplicativo",
                f"Ocorreu um erro ao montar a janela principal:\n\n{type(exc).__name__}: {exc}",
            )
            return False
        self.janela = janela
        janela.sair_solicitado.connect(self.trocar_de_usuario)
        janela.show()
        return True

    def trocar_de_usuario(self) -> None:
        anterior = self.janela
        # SO esconde (nao fecha): fechar a ultima janela faria o Qt encerrar o app antes do login aparecer
        anterior.desligar()
        anterior.hide()
        sessao_mod.encerrar()
        if not entrar() or not self.abrir():
            sessao_mod.encerrar()  # login cancelado, ou a janela nova nao abriu (ja avisado): fecha o app
            anterior.deleteLater()
            self._app.quit()
            return
        anterior.deleteLater()


def main() -> None:
    app = QApplication(sys.argv)
    # settings_mod ja garante organizationName/applicationName antes de ler
    app.setStyleSheet(build_stylesheet(settings_mod.obter_tema()))

    if not entrar():
        sys.exit(0)

    controlador = ControladorDaJanela(app)
    if not controlador.abrir():
        sys.exit(1)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
