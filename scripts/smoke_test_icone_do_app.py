"""Testa o icone do app nas janelas (desktop/icone_do_app.py), sem abrir janela de verdade
(QT_QPA_PLATFORM=offscreen).

Nada aqui toca em dado real: nenhuma planilha e lida, as preferencias vao pra um .ini temporario
(isolar_preferencias) e o login e trocado por um falso que so observa a janela.

Cobre: o arquivo do icone existe e carrega; aplicado no QApplication, vale pra qualquer janela
nova; o main() aplica o icone ANTES do login aparecer; no .exe o caminho sai de sys._MEIPASS e o
.spec leva o arquivo junto; icone ausente nao derruba o app e fica registrado no log (nunca em
silencio).

Rodar com: venv/Scripts/python.exe scripts/smoke_test_icone_do_app.py
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")  # sem tela o Qt nao acha fontes

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from PySide6.QtWidgets import QApplication, QWidget

import fixture_ficticia as fx
from desktop import icone_do_app
from desktop import main as main_mod


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def main() -> None:
    pasta = Path(tempfile.mkdtemp(prefix="_smoke_icone_"))
    try:
        fx.isolar_preferencias(pasta)
        app = QApplication.instance() or QApplication(sys.argv)

        linha("1) O arquivo do icone existe e o Qt consegue ler")
        caminho = icone_do_app.caminho_do_icone()
        assert caminho == RAIZ / "desktop" / "assets" / "icone_app.ico", caminho
        assert caminho.is_file(), caminho
        print(f"OK: {caminho.relative_to(RAIZ)} encontrado.")

        linha("2) O main() aplica o icone antes do login aparecer, e ele vale pras janelas novas")
        visto_no_login: dict[str, object] = {}

        def login_falso() -> bool:
            janela = QWidget()  # qualquer janela nova, como o LoginDialog
            visto_no_login["app"] = not QApplication.instance().windowIcon().isNull()
            visto_no_login["janela"] = not janela.windowIcon().isNull()
            visto_no_login["tamanhos"] = QApplication.instance().windowIcon().availableSizes()
            return False  # "cancelou o login": o main() sai sem abrir a janela principal

        main_original = (main_mod.QApplication, main_mod.entrar)
        main_mod.QApplication = lambda _argv: app
        main_mod.entrar = login_falso
        try:
            main_mod.main()
            raise AssertionError("main() deveria sair com sys.exit(0) quando o login e cancelado")
        except SystemExit as saida:
            assert saida.code == 0, saida.code
        finally:
            main_mod.QApplication, main_mod.entrar = main_original
        assert visto_no_login.get("app") is True, visto_no_login
        assert visto_no_login.get("janela") is True, visto_no_login
        assert visto_no_login["tamanhos"], "o icone carregou sem nenhum tamanho"
        print(f"OK: o login ja nasce com o icone (tamanhos no .ico: "
              f"{sorted({t.width() for t in visto_no_login['tamanhos']})}).")

        linha("3) No .exe empacotado o icone sai de sys._MEIPASS, e o .spec leva o arquivo junto")
        sys._MEIPASS = str(pasta / "extraido")
        try:
            assert icone_do_app.caminho_do_icone() == pasta / "extraido" / "desktop" / "assets" / "icone_app.ico"
        finally:
            del sys._MEIPASS
        spec = (RAIZ / "GestaoFinanciamentos.spec").read_text(encoding="utf-8")
        assert "datas=[('desktop/assets/icone_app.ico', 'desktop/assets')]" in spec, \
            "o .spec nao leva o icone junto: no .exe a janela ficaria sem icone"
        print("OK: o caminho no .exe bate com o destino que o .spec usa.")

        linha("4) Icone ausente: o app segue, mas fica registrado no log (nunca em silencio)")
        caminho_original = icone_do_app.caminho_do_icone
        icone_do_app.caminho_do_icone = lambda: pasta / "nao_existe.ico"
        try:
            with fx.capturar_log(icone_do_app.__name__) as log:
                assert icone_do_app.aplicar_icone_do_app(app) is False
        finally:
            icone_do_app.caminho_do_icone = caminho_original
        avisos = [r.getMessage() for r in log.registros if r.levelno >= logging.WARNING]
        assert any("nao_existe.ico" in aviso for aviso in avisos), avisos
        print("OK: sem o arquivo, aplicar_icone_do_app devolve False e avisa no log com o caminho.")

        linha("TUDO OK")
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


if __name__ == "__main__":
    main()
