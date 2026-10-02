"""Conexao com a CONTA GOOGLE de quem usa o app (OAuth, tipo "App para computador"): a pessoa entra pelo
navegador, autoriza, e o app passa a acessar a planilha em nome dela - sem precisar do arquivo de chave
da conta de servico (service_account_admin.json) em cada computador.

- O cliente OAuth (credentials/oauth_cliente_google.json) identifica o APP; nao e segredo de verdade
  (o Google trata o de "app para computador" como publico).
- A autorizacao DA PESSOA (o "refresh token") e o que da acesso: fica em credentials/conta_google.dat,
  criptografada pelo Windows (core/protecao_windows.py) - so abre neste usuario, neste computador.
- Quem pode usar: qualquer conta Google com acesso de editor a planilha (o proprio Google confere).

credenciais_para_planilha() decide a credencial do acesso a planilha: a conta Google conectada, se ha
uma; senao, a chave da conta de servico (como antes) - assim nada quebra onde ninguem conectou ainda.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import config
from core import protecao_windows

_logger = logging.getLogger(__name__)

ESCOPOS = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/spreadsheets",
]
LIMITE_DO_LOGIN_S = 300  # quanto o app espera a pessoa terminar o login no navegador

# o Google devolve os escopos em outra ordem/forma ("email" x ".../userinfo.email"): sem isto, a
# biblioteca oauthlib acusa "o escopo mudou" e recusa uma autorizacao valida
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")


class ErroContaGoogle(Exception):
    """Algo impediu conectar/usar a conta Google; a mensagem diz o que fazer."""


@dataclass(frozen=True)
class ContaConectada:
    email: str


def _caminho_cliente() -> Path:
    return Path(config.CAMINHO_CLIENTE_OAUTH_GOOGLE)


def _caminho_conexao() -> Path:
    return Path(config.CAMINHO_CONTA_GOOGLE)


def cliente_oauth_disponivel() -> bool:
    return _caminho_cliente().exists()


def _email_do_id_token(id_token: str | None) -> str:
    """O e-mail de quem entrou, lido do id_token que o proprio Google acabou de devolver (veio direto do
    servidor de token, por HTTPS - nao precisa conferir a assinatura aqui)."""
    if not id_token:
        return ""
    try:
        carga = id_token.split(".")[1]
        carga += "=" * (-len(carga) % 4)
        return str(json.loads(base64.urlsafe_b64decode(carga)).get("email", ""))
    except (IndexError, ValueError):
        return ""


def _gravar_conexao(info_credenciais: dict, email: str) -> None:
    dados = json.dumps({"credenciais": info_credenciais, "email": email}).encode("utf-8")
    caminho = _caminho_conexao()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(caminho.suffix + ".tmp")
    temporario.write_bytes(protecao_windows.proteger(dados))
    os.replace(temporario, caminho)


def _ler_conexao() -> dict | None:
    caminho = _caminho_conexao()
    if not caminho.exists():
        return None
    try:
        return json.loads(protecao_windows.desproteger(caminho.read_bytes()).decode("utf-8"))
    except (protecao_windows.ErroProtecao, ValueError) as exc:
        # gravada por outro usuario do Windows / outro PC, ou arquivo estragado: como se nao houvesse
        _logger.warning("Conexao com a conta Google ilegivel (%s) - ignorada; conecte de novo.", exc)
        return None


def conta_conectada() -> ContaConectada | None:
    """A conta Google conectada neste computador (None = nenhuma). Nao acessa a rede."""
    dados = _ler_conexao()
    if not dados or not dados.get("credenciais", {}).get("refresh_token"):
        return None
    return ContaConectada(email=dados.get("email") or "conta Google")


def conectar() -> ContaConectada:
    """Abre o navegador para a pessoa entrar na conta Google e autorizar o app; guarda a autorizacao.
    BLOQUEIA ate ela terminar (ou LIMITE_DO_LOGIN_S): chamar numa thread, nunca na da tela. Rede!"""
    if not cliente_oauth_disponivel():
        raise ErroContaGoogle(
            f"O arquivo de configuração do login Google não está neste computador ({_caminho_cliente().name}). "
            "Reinstale o aplicativo ou fale com quem dá suporte."
        )
    from google_auth_oauthlib.flow import InstalledAppFlow

    fluxo = InstalledAppFlow.from_client_secrets_file(str(_caminho_cliente()), scopes=ESCOPOS)
    try:
        credenciais = fluxo.run_local_server(
            host="localhost",
            port=0,
            open_browser=True,
            prompt="select_account consent",  # sempre escolher a conta; "consent" garante o refresh token
            authorization_prompt_message="",
            success_message="Pronto! Pode fechar esta aba e voltar ao Gestão de Financiamentos.",
            timeout_seconds=LIMITE_DO_LOGIN_S,
        )
    except AttributeError as exc:  # a biblioteca falha assim quando o tempo acaba sem resposta do navegador
        raise ErroContaGoogle("O login no navegador não foi concluído a tempo. Tente de novo.") from exc
    except Exception as exc:
        raise ErroContaGoogle(f"O login Google não foi concluído: {exc}") from exc
    if not credenciais.refresh_token:
        raise ErroContaGoogle("O Google não devolveu a autorização permanente. Tente conectar de novo.")
    email = _email_do_id_token(getattr(credenciais, "id_token", None))
    _gravar_conexao(json.loads(credenciais.to_json()), email)
    return ContaConectada(email=email or "conta Google")


def desconectar() -> None:
    """Apaga a autorizacao guardada neste computador e, se der, avisa o Google para revoga-la (sem rede, so
    apaga daqui; a pessoa pode revogar depois em myaccount.google.com/permissions)."""
    dados = _ler_conexao()
    _caminho_conexao().unlink(missing_ok=True)
    token = (dados or {}).get("credenciais", {}).get("refresh_token")
    if token:
        try:
            import requests

            requests.post("https://oauth2.googleapis.com/revoke", params={"token": token}, timeout=10)
        except Exception:
            _logger.info("Nao foi possivel revogar a autorizacao no Google agora (sem rede?) - apagada daqui.")


def credenciais_da_conta():
    """As credenciais da conta Google conectada (google.oauth2.credentials.Credentials) ou None."""
    dados = _ler_conexao()
    if not dados or not dados.get("credenciais", {}).get("refresh_token"):
        return None
    from google.oauth2.credentials import Credentials as CredenciaisDeUsuario

    return CredenciaisDeUsuario.from_authorized_user_info(dados["credenciais"], ESCOPOS)


def credenciais_para_planilha(escopos_conta_de_servico: list[str]):
    """O que usar para acessar a planilha: a conta Google conectada, se ha; senao a chave da conta de
    servico (config.CAMINHO_CREDENCIAIS_GOOGLE). Sem nenhuma das duas, levanta ErroContaGoogle."""
    credenciais = credenciais_da_conta()
    if credenciais is not None:
        return credenciais
    chave = Path(config.CAMINHO_CREDENCIAIS_GOOGLE)
    if not chave.exists():
        raise ErroContaGoogle("Nenhuma conta Google conectada e sem a chave do Google neste computador.")
    from google.oauth2.service_account import Credentials as CredenciaisDeServico

    return CredenciaisDeServico.from_service_account_file(str(chave), scopes=escopos_conta_de_servico)


def ha_acesso_a_nuvem() -> bool:
    """Ha COMO acessar a planilha neste computador (conta conectada ou chave)? Nao acessa a rede."""
    return conta_conectada() is not None or Path(config.CAMINHO_CREDENCIAIS_GOOGLE).exists()
