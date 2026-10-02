"""Roda algo demorado (rede) fora da thread da tela, com uma janelinha "Aguarde" enquanto isso."""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtWidgets import QProgressDialog, QWidget


def rodar_esperando(parent: QWidget | None, texto: str, funcao, limite_s: float | None):
    """Roda `funcao` numa thread (rede nunca na thread da tela) mostrando uma janela de espera, e devolve o
    resultado - ou levanta a excecao que ela levantou. Com `limite_s`, desiste depois desse tempo
    (TimeoutError); sem limite, espera o fim (e o que um download usa: abandonar no meio deixaria outra
    thread gravando o arquivo)."""
    resultado: dict = {}

    def alvo() -> None:
        try:
            resultado["valor"] = funcao()
        except BaseException as exc:  # a thread nao pode engolir o erro: vai pra quem chamou
            resultado["erro"] = exc

    trabalho = threading.Thread(target=alvo, daemon=True, name="espera")
    trabalho.start()
    espera = QProgressDialog(texto, None, 0, 0, parent)  # sem botao Cancelar, barra "em andamento"
    espera.setWindowTitle("Aguarde")
    espera.setWindowModality(Qt.WindowModality.ApplicationModal)
    espera.setMinimumDuration(0)
    espera.show()
    laco = QEventLoop()
    fim = None if limite_s is None else time.monotonic() + limite_s
    relogio = QTimer()
    relogio.setInterval(50)
    relogio.timeout.connect(lambda: laco.quit() if (not trabalho.is_alive() or (fim and time.monotonic() > fim)) else None)
    relogio.start()
    if trabalho.is_alive():
        laco.exec()
    relogio.stop()
    espera.close()
    if trabalho.is_alive():
        raise TimeoutError(f"não houve resposta em {limite_s:.0f} segundos")
    if "erro" in resultado:
        raise resultado["erro"]
    return resultado["valor"]
