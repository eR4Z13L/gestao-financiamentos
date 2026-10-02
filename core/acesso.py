"""Entrada no app: conta Google + PIN de 6 numeros, um PIN por computador (substitui a senha do Administrador).

- Primeira vez num computador: "Entrar com Google" (core/conta_google.py) e criar o PIN.
- Depois: so o PIN, sem internet. Ele vale enquanto a MESMA conta Google estiver conectada aqui;
  desconectar a conta (Administracao) apaga o PIN junto.
- TENTATIVAS_PERMITIDAS erros seguidos apagam o PIN: a proxima entrada exige "Entrar com Google" de novo.
- Transicao: onde ja havia a senha do Administrador (core/auth.py) e ainda nao ha PIN, entra-se com ela uma
  ultima vez; ao criar o PIN, o arquivo da senha e renomeado (.substituida) e ela deixa de valer.

O PIN fica so neste computador (credentials/acesso_pin.dat): hash PBKDF2 com salt, e o arquivo inteiro
criptografado pelo Windows (core/protecao_windows.py) - copiado para outro PC/usuario, nao abre.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import config
from core import auth, conta_google, protecao_windows

_logger = logging.getLogger(__name__)

TAMANHO_DO_PIN = 6
TENTATIVAS_PERMITIDAS = 5

ENTRADA_PIN = "pin"
ENTRADA_SENHA_ANTIGA = "senha_antiga"
ENTRADA_GOOGLE = "google"


class ErroPin(ValueError):
    """O PIN nao pode ser criado/trocado (a mensagem diz por que) - nada foi gravado."""


@dataclass(frozen=True)
class ResultadoDoPin:
    certo: bool
    tentativas_restantes: int  # 0 com certo=False: o PIN foi apagado (bloqueado)


def _caminho_pin() -> Path:
    return Path(config.CAMINHO_PIN_ACESSO)


def _ler_pin() -> dict | None:
    caminho = _caminho_pin()
    if not caminho.exists():
        return None
    try:
        return json.loads(protecao_windows.desproteger(caminho.read_bytes()).decode("utf-8"))
    except (protecao_windows.ErroProtecao, ValueError) as exc:
        _logger.warning("PIN deste computador ilegivel (%s) - ignorado; entre com Google e crie outro.", exc)
        return None


def _gravar_pin(dados: dict) -> None:
    caminho = _caminho_pin()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = caminho.with_suffix(caminho.suffix + ".tmp")
    temporario.write_bytes(protecao_windows.proteger(json.dumps(dados).encode("utf-8")))
    os.replace(temporario, caminho)


def _pin_valido() -> dict | None:
    """O PIN guardado, se ainda vale: criado para a conta Google que esta conectada agora."""
    dados = _ler_pin()
    conta = conta_google.conta_conectada()
    if not dados or conta is None or dados.get("email") != conta.email:
        return None
    return dados


def pin_configurado() -> bool:
    return _pin_valido() is not None


def modo_de_entrada() -> str:
    """Como entrar neste computador agora: ENTRADA_PIN, ENTRADA_SENHA_ANTIGA ou ENTRADA_GOOGLE."""
    if pin_configurado():
        return ENTRADA_PIN
    if auth.admin_configurado():
        return ENTRADA_SENHA_ANTIGA
    return ENTRADA_GOOGLE


def _conferir_formato(pin: str) -> None:
    if len(pin) != TAMANHO_DO_PIN or not pin.isdigit():
        raise ErroPin(f"O PIN tem que ter exatamente {TAMANHO_DO_PIN} números.")


def criar_pin(pin: str) -> None:
    """Grava o PIN deste computador para a conta Google conectada e aposenta a senha antiga do Administrador."""
    _conferir_formato(pin)
    conta = conta_google.conta_conectada()
    if conta is None:
        raise ErroPin("Entre com a conta Google antes de criar o PIN.")
    hash_hex, salt_hex = auth.hash_senha(pin)
    _gravar_pin({"pin_hash": hash_hex, "salt": salt_hex, "email": conta.email, "erros": 0})
    _aposentar_senha_antiga()


def _aposentar_senha_antiga() -> None:
    # renomeia em vez de apagar: se algo der errado com o PIN, da pra recuperar a senha antiga a mao
    antiga = Path(auth.CAMINHO_CREDENCIAIS_ADMIN)  # o mesmo caminho que auth confere
    if antiga.exists():
        os.replace(antiga, antiga.with_name(antiga.name + ".substituida"))


def conferir_pin(pin: str) -> ResultadoDoPin:
    """Confere o PIN e conta os erros seguidos; no ultimo erro permitido, apaga o PIN."""
    dados = _pin_valido()
    if dados is None:
        return ResultadoDoPin(certo=False, tentativas_restantes=0)
    if auth.senha_confere(pin, dados.get("pin_hash", ""), dados.get("salt", "")):
        if dados.get("erros"):
            _gravar_pin({**dados, "erros": 0})
        return ResultadoDoPin(certo=True, tentativas_restantes=TENTATIVAS_PERMITIDAS)
    erros = int(dados.get("erros", 0)) + 1
    if erros >= TENTATIVAS_PERMITIDAS:
        esquecer_pin()
        return ResultadoDoPin(certo=False, tentativas_restantes=0)
    _gravar_pin({**dados, "erros": erros})
    return ResultadoDoPin(certo=False, tentativas_restantes=TENTATIVAS_PERMITIDAS - erros)


def trocar_pin(pin_atual: str, pin_novo: str) -> bool:
    """Troca o PIN se o atual conferir (False: atual errado - conta como erro, igual a entrada)."""
    _conferir_formato(pin_novo)
    if not conferir_pin(pin_atual).certo:
        return False
    criar_pin(pin_novo)
    return True


def esquecer_pin() -> None:
    _caminho_pin().unlink(missing_ok=True)
