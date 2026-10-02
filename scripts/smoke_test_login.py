"""Testa a entrada no app: conta Google + PIN de 6 numeros por computador (core/acesso.py) e o dialogo de login
(desktop/dialogs/login_dialog.py), inclusive a transicao de quem ainda tem a senha do Administrador.

O login Google de verdade abre o navegador: aqui ele e SUBSTITUIDO por um falso, e a conferencia de acesso a
planilha tambem (nenhum byte sai da maquina). Senha, conexao, PIN, cliente OAuth e chave sao redirecionados para
uma pasta temporaria; os arquivos reais de credentials/ e credentials_teste/ sao conferidos (hash) antes e depois.

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

from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False
from ambiente_de_teste import CredenciaisFalsas, GoogleFalso, Mensagens
from core import acesso, auth, conta_google, sheets_sync
from core import sessao as sessao_mod
from desktop.dialogs import login_dialog
from desktop.dialogs.login_dialog import LoginDialog

RAIZ = Path(__file__).resolve().parent.parent
REAIS = [p for pasta in ("credentials", "credentials_teste") for p in (RAIZ / pasta).glob("*") if p.is_file()]
EMAIL = "pessoa.teste@gmail.com"


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _hashes() -> dict:
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in REAIS if p.exists()}


def _apertar_ok(dialogo: QDialog) -> None:
    dialogo.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()


class _CriarPinFalso:
    """O dialogo "Criar PIN" e modal (travaria o teste): `pins` diz o que "a pessoa" digita (None = cancela)."""

    def __init__(self):
        self.pins: list[str | None] = []
        self.chamadas = 0
        self._original = login_dialog.CriarPinDialog.exec

    def __enter__(self):
        falso = self

        def _exec(dialogo):
            falso.chamadas += 1
            pin = falso.pins.pop(0) if falso.pins else None
            if pin is None:
                return QDialog.DialogCode.Rejected
            dialogo._pin.setText(pin)
            dialogo._confirmar.setText(pin)
            dialogo._criar()
            return dialogo.result()

        login_dialog.CriarPinDialog.exec = _exec
        return self

    def __exit__(self, *_):
        login_dialog.CriarPinDialog.exec = self._original


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    pasta = Path(tempfile.mkdtemp(prefix="_smoke_login_"))
    reais_antes = _hashes()
    originais = (config.CAMINHO_CONTA_GOOGLE, config.CAMINHO_CLIENTE_OAUTH_GOOGLE, config.CAMINHO_CREDENCIAIS_GOOGLE,
                 config.CAMINHO_PIN_ACESSO, auth.CAMINHO_CREDENCIAIS_ADMIN)
    config.CAMINHO_CONTA_GOOGLE = pasta / "conta_google.dat"
    config.CAMINHO_CLIENTE_OAUTH_GOOGLE = pasta / "oauth_cliente_google.json"
    config.CAMINHO_CLIENTE_OAUTH_GOOGLE.write_text('{"installed": {}}', encoding="utf-8")
    config.CAMINHO_CREDENCIAIS_GOOGLE = pasta / "service_account_admin.json"
    config.CAMINHO_PIN_ACESSO = pasta / "acesso_pin.dat"
    auth.CAMINHO_CREDENCIAIS_ADMIN = pasta / "admin_senha.json"
    senha = auth.CAMINHO_CREDENCIAIS_ADMIN
    import requests

    post_original = requests.post
    requests.post = lambda *a, **kw: None  # a revogacao ao desconectar nao sai da maquina
    ler_meta_original = sheets_sync.ler_meta_da_nuvem
    acesso_a_planilha = {"ok": True}

    def _ler_meta_falso():
        if not acesso_a_planilha["ok"]:
            raise PermissionError("sem permissao (falso)")
        return sheets_sync.MetaNuvem()

    sheets_sync.ler_meta_da_nuvem = _ler_meta_falso
    try:
        linha("1) Regras do PIN no core")
        assert acesso.modo_de_entrada() == acesso.ENTRADA_GOOGLE, "nada configurado: entra com Google"
        try:
            acesso.criar_pin("123456")
            raise AssertionError("sem conta Google conectada nao cria PIN")
        except acesso.ErroPin:
            pass
        with GoogleFalso():
            conta_google.conectar()
        for ruim in ("12345", "1234567", "12a456", ""):
            try:
                acesso.criar_pin(ruim)
                raise AssertionError(f"PIN {ruim!r} deveria ser recusado")
            except acesso.ErroPin as exc:
                assert "6 números" in str(exc)
        assert not config.CAMINHO_PIN_ACESSO.exists(), "PIN recusado nao grava nada"
        acesso.criar_pin("123456")
        bruto = config.CAMINHO_PIN_ACESSO.read_bytes()
        assert b"pin_hash" not in bruto and EMAIL.encode() not in bruto, "arquivo do PIN criptografado"
        assert acesso.modo_de_entrada() == acesso.ENTRADA_PIN
        print("OK: sem conta nao cria; so 6 numeros; arquivo criptografado; depois disso a entrada e pelo PIN.")

        assert not acesso.conferir_pin("000000").certo
        assert acesso.conferir_pin("000000").tentativas_restantes == acesso.TENTATIVAS_PERMITIDAS - 2
        assert acesso.conferir_pin("123456").certo
        assert acesso.conferir_pin("000000").tentativas_restantes == acesso.TENTATIVAS_PERMITIDAS - 1, "acertar zera os erros"
        for _ in range(acesso.TENTATIVAS_PERMITIDAS - 1):
            resultado = acesso.conferir_pin("000000")
        assert resultado.tentativas_restantes == 0 and not config.CAMINHO_PIN_ACESSO.exists()
        assert not acesso.conferir_pin("123456").certo and acesso.modo_de_entrada() == acesso.ENTRADA_GOOGLE
        print(f"OK: erros contam, acertar zera; {acesso.TENTATIVAS_PERMITIDAS} erros seguidos apagam o PIN (volta a pedir Google).")

        acesso.criar_pin("123456")
        with GoogleFalso() as google:
            google.resposta = CredenciaisFalsas(email="outra.pessoa@gmail.com")
            conta_google.conectar()
        assert not acesso.pin_configurado() and not acesso.conferir_pin("123456").certo, "PIN de outra conta nao vale"
        conta_google.desconectar()
        assert acesso.modo_de_entrada() == acesso.ENTRADA_GOOGLE
        print("OK: o PIN so vale para a conta Google com que foi criado; sem conta conectada, nao vale.")

        linha("2) Transicao: quem tem a senha antiga e nao tem PIN entra com ela; criar o PIN aposenta a senha")
        auth.definir_senha_admin("senhaAntiga1")
        assert acesso.modo_de_entrada() == acesso.ENTRADA_SENHA_ANTIGA
        with GoogleFalso():
            conta_google.conectar()
        acesso.criar_pin("654321")
        assert not senha.exists() and senha.with_name(senha.name + ".substituida").exists()
        assert not auth.verificar_senha_admin("senhaAntiga1") and acesso.modo_de_entrada() == acesso.ENTRADA_PIN
        print("OK: modo 'senha antiga'; ao criar o PIN a senha e renomeada (.substituida) e deixa de valer.")

        assert acesso.trocar_pin("111111", "222222") is False and acesso.conferir_pin("654321").certo
        try:
            acesso.trocar_pin("654321", "12")
            raise AssertionError("PIN novo curto deveria ser recusado")
        except acesso.ErroPin:
            pass
        assert acesso.trocar_pin("654321", "222222") and acesso.conferir_pin("222222").certo
        print("OK: trocar o PIN exige o atual certo e um novo de 6 numeros.")

        with Mensagens() as msgs, _CriarPinFalso() as criar_pin:
            linha("3) Tela - PIN: errado avisa quantas tentativas restam; certo entra")
            dialogo = LoginDialog()
            assert dialogo.modo == acesso.ENTRADA_PIN and EMAIL in dialogo.findChild(login_dialog.QLabel).text()
            dialogo._pin.setText("999999")
            _apertar_ok(dialogo)
            assert msgs.ultima()[1] == "PIN incorreto" and f"Restam {acesso.TENTATIVAS_PERMITIDAS - 1}" in msgs.ultima()[2]
            assert dialogo.sessao_criada is None and dialogo._pin.text() == ""
            dialogo._pin.setText("222222")
            _apertar_ok(dialogo)
            assert dialogo.sessao_criada is not None and dialogo.sessao_criada.papel == sessao_mod.PAPEL_ADMIN
            print("OK: PIN errado -> 'Restam 4'; certo -> sessao de Administrador.")

            linha("4) Tela - PIN errado vezes demais: apaga e passa para 'Entrar com Google'")
            dialogo = LoginDialog()
            for _ in range(acesso.TENTATIVAS_PERMITIDAS):
                dialogo._pin.setText("999999")
                _apertar_ok(dialogo)
            assert msgs.ultima()[1] == "PIN apagado" and dialogo.modo == acesso.ENTRADA_GOOGLE and dialogo.sessao_criada is None
            texto_ok = dialogo.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).text()
            # o conteudo antigo so sai no proximo ciclo de eventos: conferir o botao do conteudo novo
            assert any(b.text() == "Entrar com Google" for b in dialogo._conteudo.findChildren(login_dialog.QPushButton)), texto_ok
            print("OK: 5 erros -> 'PIN apagado' e o dialogo vira 'Entrar com Google'.")

            linha("5) Tela - Entrar com Google: conta sem acesso a planilha nao entra; com acesso cria o PIN e entra")
            acesso_a_planilha["ok"] = False
            msgs.limpar()
            with GoogleFalso():
                dialogo._entrar_com_google()
            assert msgs.ultima()[1] == "Conta sem acesso à planilha" and dialogo.sessao_criada is None
            assert conta_google.conta_conectada() is None and criar_pin.chamadas == 0, "sem acesso: desfaz e nem pede PIN"
            acesso_a_planilha["ok"] = True
            criar_pin.pins = ["135790"]
            with GoogleFalso():
                dialogo._entrar_com_google()
            assert dialogo.sessao_criada is not None and acesso.conferir_pin("135790").certo
            print("OK: sem acesso -> explica e nao entra; com acesso -> cria o PIN e entra.")

            linha("6) Tela - Google sem criar o PIN: entra desta vez, e da proxima pede Google de novo")
            acesso.esquecer_pin()
            dialogo = LoginDialog()
            assert dialogo.modo == acesso.ENTRADA_GOOGLE
            criar_pin.pins = [None]
            with GoogleFalso():
                _apertar_ok(dialogo)
            assert dialogo.sessao_criada is not None and acesso.modo_de_entrada() == acesso.ENTRADA_GOOGLE
            print("OK: cancelar o PIN entra assim mesmo (o Google ja confirmou quem e); sem PIN, proxima vez e Google.")

            linha("7) Tela - Esqueci o PIN: conectar falhou nao deixa entrar pela conexao antiga")
            acesso.criar_pin("246802")
            dialogo = LoginDialog()
            msgs.limpar()
            with GoogleFalso() as google:
                google.resposta = RuntimeError("acesso negado")
                dialogo._entrar_com_google()
            assert dialogo.sessao_criada is None and msgs.ultima()[1] == "Não foi possível conectar"
            criar_pin.pins = ["975310"]
            with GoogleFalso():
                dialogo._entrar_com_google()
            assert dialogo.sessao_criada is not None and acesso.conferir_pin("975310").certo
            print("OK: login Google que falha nao entra; que da certo troca o PIN e entra.")

            linha("8) Tela - senha antiga: errada avisa; certa entra e ja pede Google + PIN")
            conta_google.desconectar()
            acesso.esquecer_pin()
            auth.definir_senha_admin("senhaAntiga1")
            dialogo = LoginDialog()
            assert dialogo.modo == acesso.ENTRADA_SENHA_ANTIGA
            dialogo._senha.setText("errada123")
            _apertar_ok(dialogo)
            assert msgs.ultima()[1] == "Não foi possível entrar" and dialogo.sessao_criada is None

            # sem internet (o Google falha): entra com a senha e ela continua valendo
            msgs.limpar()
            dialogo._senha.setText("senhaAntiga1")
            with GoogleFalso() as google:
                google.resposta = RuntimeError("sem internet")
                _apertar_ok(dialogo)
            assert dialogo.sessao_criada is not None and msgs.ultima()[1] == "Entrou com a senha"
            assert auth.verificar_senha_admin("senhaAntiga1") and acesso.modo_de_entrada() == acesso.ENTRADA_SENHA_ANTIGA
            print("OK: senha errada nao entra; certa sem internet entra e a senha continua valendo.")

            dialogo = LoginDialog()
            dialogo._senha.setText("senhaAntiga1")
            criar_pin.pins = ["112233"]
            msgs.limpar()
            with GoogleFalso():
                _apertar_ok(dialogo)
            assert dialogo.sessao_criada is not None and not any(m[1] == "Entrou com a senha" for m in msgs.registro)
            assert acesso.modo_de_entrada() == acesso.ENTRADA_PIN and not auth.verificar_senha_admin("senhaAntiga1")
            print("OK: senha certa + Google + PIN -> entra, e da proxima vez e so o PIN (senha aposentada).")

            linha("9) Tela - Criar PIN: confirmacao diferente e erro ao gravar aparecem (nunca em silencio)")
            dialogo = login_dialog.CriarPinDialog(EMAIL)
            dialogo._pin.setText("123456")
            dialogo._confirmar.setText("654321")
            dialogo._criar()
            assert msgs.ultima()[1] == "PINs diferentes" and dialogo.result() != QDialog.DialogCode.Accepted
            original = acesso.criar_pin
            acesso.criar_pin = lambda _p: (_ for _ in ()).throw(PermissionError("sem permissao (falso)"))
            try:
                dialogo._confirmar.setText("123456")
                dialogo._criar()
            finally:
                acesso.criar_pin = original
            assert msgs.ultima()[0] == "critical" and "sem permissao" in msgs.ultima()[2]
            assert dialogo.result() != QDialog.DialogCode.Accepted
            print("OK: PINs diferentes -> aviso; falha ao gravar -> erro, sem fechar.")
        linha("TUDO OK")
    finally:
        requests.post = post_original
        sheets_sync.ler_meta_da_nuvem = ler_meta_original
        (config.CAMINHO_CONTA_GOOGLE, config.CAMINHO_CLIENTE_OAUTH_GOOGLE, config.CAMINHO_CREDENCIAIS_GOOGLE,
         config.CAMINHO_PIN_ACESSO, auth.CAMINHO_CREDENCIAIS_ADMIN) = originais
        shutil.rmtree(pasta, ignore_errors=True)
        assert _hashes() == reais_antes, "o teste mexeu num arquivo REAL de credentials/"


if __name__ == "__main__":
    main()
