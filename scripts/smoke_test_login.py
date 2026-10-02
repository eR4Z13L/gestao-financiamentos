"""Testa o login do Administrador (desktop/dialogs/login_dialog.py) e a regra da senha (core/auth.py):
o tamanho minimo e o MESMO no primeiro acesso e na troca de senha (antes o primeiro acesso aceitava 4
caracteres e a troca exigia 8), e a regra vale no core - nao so na tela. O arquivo de senha e redirecionado
para uma pasta temporaria; os arquivos de senha reais sao conferidos (hash) antes e depois.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_login.py
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QDialogButtonBox

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False
from ambiente_de_teste import Mensagens
from core import auth
from core import sessao as sessao_mod
from desktop.dialogs.login_dialog import LoginDialog

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVOS_DE_SENHA_REAIS = [RAIZ / "credentials" / "admin_senha.json", RAIZ / "credentials_teste" / "admin_senha_teste.json"]


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _hashes() -> dict:
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in ARQUIVOS_DE_SENHA_REAIS if p.exists()}


def _apertar_ok(dialogo: LoginDialog) -> None:
    dialogo.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    pasta = Path(tempfile.mkdtemp(prefix="_smoke_login_"))
    reais_antes = _hashes()
    caminho_original = auth.CAMINHO_CREDENCIAIS_ADMIN
    auth.CAMINHO_CREDENCIAIS_ADMIN = pasta / "credentials" / "admin_senha.json"
    arquivo = auth.CAMINHO_CREDENCIAIS_ADMIN
    try:
        linha("1) Regra no core: menos de SENHA_MINIMA caracteres e recusado (e nada e gravado)")
        assert auth.SENHA_MINIMA == 8
        try:
            auth.definir_senha_admin("1234567")
            raise AssertionError("deveria recusar 7 caracteres")
        except auth.ErroSenha as exc:
            assert "8" in str(exc)
        assert not arquivo.exists(), "senha recusada nao pode gravar nada"
        auth.definir_senha_admin("12345678")
        assert auth.verificar_senha_admin("12345678") and not auth.verificar_senha_admin("1234567")
        print("OK: 7 caracteres -> ErroSenha, nada gravado; 8 caracteres -> gravada e confere.")

        antes = arquivo.read_bytes()
        try:
            auth.alterar_senha_admin("12345678", "curta")
            raise AssertionError("a troca tambem deveria recusar")
        except auth.ErroSenha:
            pass
        assert arquivo.read_bytes() == antes and auth.verificar_senha_admin("12345678")
        print("OK: a troca de senha com senha nova curta tambem e recusada (a antiga continua valendo).")

        linha("2) Primeiro acesso na tela: o mesmo minimo da troca de senha")
        arquivo.unlink()
        with Mensagens() as msgs:
            dialogo = LoginDialog()
            assert dialogo._primeiro_acesso
            dialogo._nova_senha.setText("abc1234")
            dialogo._confirmar_senha.setText("abc1234")
            _apertar_ok(dialogo)
            assert msgs.ultima()[1] == "Senha muito curta" and "8 caracteres" in msgs.ultima()[2], msgs.registro
            assert dialogo.sessao_criada is None and not arquivo.exists()
            print("OK: 7 caracteres no primeiro acesso -> 'Use pelo menos 8 caracteres', nada gravado.")

            msgs.limpar()
            dialogo._nova_senha.setText("abcd1234")
            dialogo._confirmar_senha.setText("abcd9999")
            _apertar_ok(dialogo)
            assert msgs.ultima()[1] == "Senhas diferentes" and not arquivo.exists()
            print("OK: confirmacao diferente -> 'Senhas diferentes', nada gravado.")

            msgs.limpar()
            dialogo._confirmar_senha.setText("abcd1234")
            _apertar_ok(dialogo)
            assert not msgs.registro and arquivo.exists() and dialogo.sessao_criada is not None
            assert dialogo.sessao_criada.papel == sessao_mod.PAPEL_ADMIN and auth.verificar_senha_admin("abcd1234")
            print("OK: 8 caracteres iguais -> senha gravada e sessao de Administrador criada.")

            linha("3) Login normal: senha errada avisa, a certa entra")
            dialogo = LoginDialog()
            assert not dialogo._primeiro_acesso
            dialogo._senha.setText("errada123")
            _apertar_ok(dialogo)
            assert msgs.ultima()[1] == "Não foi possível entrar" and dialogo.sessao_criada is None
            dialogo._senha.setText("")
            _apertar_ok(dialogo)
            assert msgs.ultima()[1] == "Campo obrigatório"
            msgs.limpar()
            dialogo._senha.setText("abcd1234")
            _apertar_ok(dialogo)
            assert not msgs.registro and dialogo.sessao_criada is not None
            print("OK: senha errada -> aviso; vazia -> 'Campo obrigatorio'; certa -> entra.")

            linha("4) Erro ao gravar a senha aparece (nunca em silencio)")
            arquivo.unlink()
            dialogo = LoginDialog()
            original = auth.definir_senha_admin
            auth.definir_senha_admin = lambda _s: (_ for _ in ()).throw(PermissionError("sem permissao (falso)"))
            try:
                dialogo._nova_senha.setText("abcd1234")
                dialogo._confirmar_senha.setText("abcd1234")
                _apertar_ok(dialogo)
            finally:
                auth.definir_senha_admin = original
            assert msgs.ultima()[0] == "critical" and "sem permissao" in msgs.ultima()[2] and dialogo.sessao_criada is None
            print("OK: falha ao gravar -> mensagem de erro, sem entrar.")
        linha("TUDO OK")
    finally:
        auth.CAMINHO_CREDENCIAIS_ADMIN = caminho_original
        shutil.rmtree(pasta, ignore_errors=True)
        assert _hashes() == reais_antes, "o teste mexeu num arquivo de senha REAL"


if __name__ == "__main__":
    main()
