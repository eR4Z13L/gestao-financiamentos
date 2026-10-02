"""Testa a conexao com a conta Google (core/conta_google.py + core/protecao_windows.py) e o cartao "Conta Google"
da Administracao. O login de verdade abre o navegador e precisa de alguem clicando: aqui o fluxo do Google e
SUBSTITUIDO por um falso (nenhum byte sai da maquina). Os caminhos da conexao, do cliente OAuth e da chave sao
redirecionados para uma pasta temporaria; os arquivos reais de credentials/ sao conferidos (hash) antes e depois.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_conta_google.py
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QMessageBox

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False
from ambiente_de_teste import Ambiente, Mensagens
from core import conta_google, protecao_windows, sheets_sync
from desktop.theme import TEMA_ESCURO

RAIZ = Path(__file__).resolve().parent.parent
REAIS = [p for pasta in ("credentials", "credentials_teste") for p in (RAIZ / pasta).glob("*") if p.is_file()]


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _hashes() -> dict:
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in REAIS if p.exists()}


def _id_token(email: str) -> str:
    carga = base64.urlsafe_b64encode(json.dumps({"email": email}).encode()).decode().rstrip("=")
    return f"cabecalho.{carga}.assinatura"


class _CredenciaisFalsas:
    def __init__(self, refresh_token="refresh-falso-123", email="pessoa.teste@gmail.com"):
        self.refresh_token = refresh_token
        self.id_token = _id_token(email)

    def to_json(self):
        return json.dumps({"refresh_token": self.refresh_token, "client_id": "cliente-falso.apps.googleusercontent.com",
                           "client_secret": "segredo-falso", "token_uri": "https://oauth2.googleapis.com/token",
                           "token": "acesso-falso"})


class _GoogleFalso:
    """Substitui InstalledAppFlow: `resposta` e o que o "navegador" devolve (credenciais ou uma excecao)."""

    def __init__(self):
        self.resposta = _CredenciaisFalsas()
        self.chamadas = []
        from google_auth_oauthlib import flow

        self._flow = flow
        self._original = flow.InstalledAppFlow.from_client_secrets_file

    def __enter__(self):
        falso = self

        class _Fluxo:
            def run_local_server(self, **kw):
                falso.chamadas.append(kw)
                if isinstance(falso.resposta, BaseException):
                    raise falso.resposta
                return falso.resposta

        self._flow.InstalledAppFlow.from_client_secrets_file = classmethod(lambda cls, caminho, scopes: _Fluxo())
        return self

    def __exit__(self, *_):
        self._flow.InstalledAppFlow.from_client_secrets_file = self._original


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    pasta = Path(tempfile.mkdtemp(prefix="_smoke_conta_google_"))
    reais_antes = _hashes()
    originais = (config.CAMINHO_CONTA_GOOGLE, config.CAMINHO_CLIENTE_OAUTH_GOOGLE, config.CAMINHO_CREDENCIAIS_GOOGLE)
    config.CAMINHO_CONTA_GOOGLE = pasta / "conta_google.dat"
    config.CAMINHO_CLIENTE_OAUTH_GOOGLE = pasta / "oauth_cliente_google.json"
    config.CAMINHO_CREDENCIAIS_GOOGLE = pasta / "service_account_admin.json"
    import requests

    post_original = requests.post
    revogacoes = []
    requests.post = lambda url, params=None, timeout=None: revogacoes.append((url, params))
    try:
        linha("1) Protecao do Windows: ida e volta, e recusa dado adulterado")
        protegido = protecao_windows.proteger(b"segredo")
        assert protegido != b"segredo" and protecao_windows.desproteger(protegido) == b"segredo"
        try:
            protecao_windows.desproteger(protegido[:-4] + b"xxxx")
            raise AssertionError("deveria recusar")
        except protecao_windows.ErroProtecao:
            pass
        print("OK: protege, abre de volta, e um arquivo adulterado e recusado.")

        linha("2) Sem nada: sem conta, sem acesso; conectar sem o arquivo do cliente OAuth explica")
        assert conta_google.conta_conectada() is None and not conta_google.ha_acesso_a_nuvem()
        try:
            conta_google.credenciais_para_planilha(["x"])
            raise AssertionError("sem conta e sem chave deveria recusar")
        except conta_google.ErroContaGoogle:
            pass
        try:
            conta_google.conectar()
            raise AssertionError("sem o cliente OAuth deveria recusar")
        except conta_google.ErroContaGoogle as exc:
            assert "oauth_cliente_google.json" in str(exc)
        print("OK: nada conectado; sem o arquivo do cliente OAuth, conectar explica o que falta.")

        linha("3) Conectar: guarda a autorizacao PROTEGIDA e sabe o e-mail")
        config.CAMINHO_CLIENTE_OAUTH_GOOGLE.write_text('{"installed": {}}', encoding="utf-8")
        with _GoogleFalso() as google:
            conta = conta_google.conectar()
            assert conta.email == "pessoa.teste@gmail.com"
            kw = google.chamadas[0]
            assert kw["port"] == 0 and kw["open_browser"] and "select_account" in kw["prompt"] and kw["timeout_seconds"] == conta_google.LIMITE_DO_LOGIN_S
        bruto = config.CAMINHO_CONTA_GOOGLE.read_bytes()
        assert b"refresh-falso-123" not in bruto and b"pessoa.teste" not in bruto, "nada legivel no arquivo"
        assert conta_google.conta_conectada().email == "pessoa.teste@gmail.com" and conta_google.ha_acesso_a_nuvem()
        cred = conta_google.credenciais_para_planilha(["x"])
        from google.oauth2.credentials import Credentials as CredenciaisDeUsuario

        assert isinstance(cred, CredenciaisDeUsuario) and cred.refresh_token == "refresh-falso-123"
        print("OK: e-mail lido do Google, autorizacao gravada criptografada (nada legivel no arquivo) e usada para a planilha.")

        linha("4) Conectar que falha: tempo esgotado, sem autorizacao permanente, erro do Google")
        for resposta, trecho in ((AttributeError("x"), "a tempo"), (_CredenciaisFalsas(refresh_token=None), "permanente"),
                                 (RuntimeError("acesso negado"), "acesso negado")):
            config.CAMINHO_CONTA_GOOGLE.unlink(missing_ok=True)
            with _GoogleFalso() as google:
                google.resposta = resposta
                try:
                    conta_google.conectar()
                    raise AssertionError("deveria falhar")
                except conta_google.ErroContaGoogle as exc:
                    assert trecho in str(exc), str(exc)
            assert not config.CAMINHO_CONTA_GOOGLE.exists(), "falhou: nada gravado"
        print("OK: cada falha vira uma mensagem clara e nada e gravado.")

        linha("5) Arquivo da conexao ilegivel (outro usuario/PC): como se nao houvesse")
        config.CAMINHO_CONTA_GOOGLE.write_bytes(b"nao e dpapi")
        assert conta_google.conta_conectada() is None
        print("OK: conexao ilegivel e ignorada (pede para conectar de novo).")

        linha("6) Sem conta, com a chave: usa a chave (como antes); desconectar apaga e tenta revogar")
        config.CAMINHO_CREDENCIAIS_GOOGLE.write_text("{}", encoding="utf-8")
        from google.oauth2 import service_account

        original_sa = service_account.Credentials.from_service_account_file
        service_account.Credentials.from_service_account_file = classmethod(lambda cls, caminho, scopes: ("CHAVE", caminho, tuple(scopes)))
        try:
            config.CAMINHO_CONTA_GOOGLE.unlink(missing_ok=True)
            assert conta_google.credenciais_para_planilha(["escopo-a"]) == ("CHAVE", str(config.CAMINHO_CREDENCIAIS_GOOGLE), ("escopo-a",))
            with _GoogleFalso():
                conta_google.conectar()
            assert conta_google.credenciais_para_planilha(["escopo-a"]) != ("CHAVE", str(config.CAMINHO_CREDENCIAIS_GOOGLE), ("escopo-a",)), \
                "com a conta conectada, ela tem preferencia sobre a chave"
        finally:
            service_account.Credentials.from_service_account_file = original_sa
        conta_google.desconectar()
        assert not config.CAMINHO_CONTA_GOOGLE.exists() and revogacoes and revogacoes[-1][1] == {"token": "refresh-falso-123"}
        assert conta_google.ha_acesso_a_nuvem(), "sem conta, a chave ainda da acesso"
        print("OK: sem conta usa a chave; com conta, a conta tem preferencia; desconectar apaga e pede a revogacao.")

        linha("7) Administracao: o cartao mostra a conta e conecta/desconecta")
        amb = Ambiente()
        try:
            with Mensagens() as msgs:
                janela = amb.nova_janela("admin", TEMA_ESCURO)
                adm = janela._tela_administracao
                assert "Nenhuma conta Google conectada" in adm._rotulo_conta_google.text() and "chave" in adm._rotulo_conta_google.text()
                assert adm._botao_conta_google.text() == "Conectar com Google" and adm._botao_conta_google.isEnabled()

                ler_meta = sheets_sync.ler_meta_da_nuvem
                esquecidas = []
                original_esquecer = sheets_sync.esquecer_conexao
                sheets_sync.esquecer_conexao = lambda: esquecidas.append(1)
                try:
                    # a conta entra mas NAO abre a planilha: desfaz e explica
                    sheets_sync.ler_meta_da_nuvem = lambda: (_ for _ in ()).throw(PermissionError("sem permissao (falso)"))
                    with _GoogleFalso():
                        adm._botao_conta_google.click()
                    assert conta_google.conta_conectada() is None, "sem acesso a planilha, a conexao e desfeita"
                    assert msgs.ultima()[1] == "Conta sem acesso à planilha" and "Editor" in msgs.ultima()[2]
                    print("OK: conta sem acesso a planilha -> conexao desfeita e explicacao (compartilhar como Editor).")

                    sheets_sync.ler_meta_da_nuvem = lambda: sheets_sync.MetaNuvem()
                    msgs.limpar()
                    with _GoogleFalso():
                        adm._botao_conta_google.click()
                    assert conta_google.conta_conectada() is not None and esquecidas
                    assert "pessoa.teste@gmail.com" in adm._rotulo_conta_google.text() and adm._botao_conta_google.text() == "Desconectar"
                    assert msgs.ultima()[1] == "Conta Google conectada"
                    print("OK: conectar mostra o e-mail, troca o botao para Desconectar e reinicia a conexao da sincronizacao.")

                    msgs.limpar(); msgs.resposta_pergunta = QMessageBox.StandardButton.No
                    adm._botao_conta_google.click()
                    assert conta_google.conta_conectada() is not None, "respondendo Nao, continua conectada"
                    msgs.resposta_pergunta = QMessageBox.StandardButton.Yes
                    adm._botao_conta_google.click()
                    assert conta_google.conta_conectada() is None and adm._botao_conta_google.text() == "Conectar com Google"
                    print("OK: desconectar pergunta antes; 'Sim' apaga e o cartao volta ao estado inicial.")
                finally:
                    sheets_sync.ler_meta_da_nuvem = ler_meta
                    sheets_sync.esquecer_conexao = original_esquecer

                config.CAMINHO_CLIENTE_OAUTH_GOOGLE.unlink()
                adm._atualizar_conta_google()
                assert not adm._botao_conta_google.isEnabled() and "não está neste computador" in adm._botao_conta_google.toolTip()
                print("OK: sem o arquivo do cliente OAuth, o botao fica desativado e a dica explica.")
        finally:
            amb.encerrar()
        linha("TUDO OK")
    finally:
        requests.post = post_original
        config.CAMINHO_CONTA_GOOGLE, config.CAMINHO_CLIENTE_OAUTH_GOOGLE, config.CAMINHO_CREDENCIAIS_GOOGLE = originais
        shutil.rmtree(pasta, ignore_errors=True)
        assert _hashes() == reais_antes, "o teste mexeu num arquivo REAL de credentials/"


if __name__ == "__main__":
    main()
