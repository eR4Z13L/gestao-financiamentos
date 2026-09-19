"""Hashing de senha (PBKDF2-HMAC-SHA256 com salt) e persistencia da senha do
ADMIN - a UNICA credencial que precisa funcionar 100% offline (fica so no
disco local, nunca sincroniza pro Google Sheets). As senhas dos VENDEDORES
sao geridas por core/vendedores.py, junto do cadastro deles - precisam
sincronizar pra la, porque o login de um vendedor e conferido remotamente
(ver core/data_store_sheets.py).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets

from config import CAMINHO_CREDENCIAIS_ADMIN

_ITERACOES_PBKDF2 = 200_000
# sem 0/O/1/l/I - caracteres facilmente confundiveis ao digitar uma senha
# gerada automaticamente e passada por mensagem
_ALFABETO_SENHA = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"


def gerar_senha_aleatoria(tamanho: int = 8) -> str:
    return "".join(secrets.choice(_ALFABETO_SENHA) for _ in range(tamanho))


def hash_senha(senha: str, salt_hex: str | None = None) -> tuple[str, str]:
    """Devolve (hash_hex, salt_hex). Sem salt_hex, gera um salt novo (cadastro/
    redefinicao); com salt_hex, recalcula o hash com o MESMO salt (conferir
    login) - os dois hashes so vao bater se a senha for a mesma."""
    salt = bytes.fromhex(salt_hex) if salt_hex else os.urandom(16)
    hash_bytes = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), salt, _ITERACOES_PBKDF2)
    return hash_bytes.hex(), salt.hex()


def senha_confere(senha: str, hash_hex: str, salt_hex: str) -> bool:
    if not hash_hex or not salt_hex:
        return False
    calculado, _ = hash_senha(senha, salt_hex)
    # compare_digest evita vazar, pelo tempo de resposta, quantos caracteres
    # do hash bateram - nao importa muito aqui (app local), mas custa nada
    return secrets.compare_digest(calculado, hash_hex)


def admin_configurado() -> bool:
    return CAMINHO_CREDENCIAIS_ADMIN.exists()


def definir_senha_admin(senha: str) -> None:
    hash_hex, salt_hex = hash_senha(senha)
    CAMINHO_CREDENCIAIS_ADMIN.parent.mkdir(parents=True, exist_ok=True)
    CAMINHO_CREDENCIAIS_ADMIN.write_text(
        json.dumps({"senha_hash": hash_hex, "salt": salt_hex}), encoding="utf-8"
    )


def verificar_senha_admin(senha: str) -> bool:
    if not admin_configurado():
        return False
    dados = json.loads(CAMINHO_CREDENCIAIS_ADMIN.read_text(encoding="utf-8"))
    return senha_confere(senha, dados.get("senha_hash", ""), dados.get("salt", ""))


def alterar_senha_admin(senha_atual: str, senha_nova: str) -> bool:
    """Troca a senha do ADMIN, mas so se `senha_atual` conferir - evita que
    alguem que encontre o app aberto (sem ter que logar de novo) troque a
    senha sem saber a atual. Devolve False (sem trocar nada) se a senha
    atual estiver errada."""
    if not verificar_senha_admin(senha_atual):
        return False
    definir_senha_admin(senha_nova)
    return True
