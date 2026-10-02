"""Criptografia "presa ao usuario do Windows" (DPAPI): o que e protegido aqui so pode ser aberto por
este mesmo usuario, neste mesmo computador. Copiar o arquivo pra outro PC (ou outro usuario do
Windows) nao adianta. E o que guarda a autorizacao da conta Google (core/conta_google.py).

Sem dependencia nova: chama a API do Windows (crypt32.dll) direto, via ctypes.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


class ErroProtecao(Exception):
    """O Windows recusou proteger/abrir os dados (a mensagem diz o motivo)."""


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _para_blob(dados: bytes) -> tuple[_Blob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(dados, len(dados))
    return _Blob(len(dados), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _de_blob(blob: _Blob) -> bytes:
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob.pbData)


def _exigir_windows() -> None:
    if sys.platform != "win32":
        raise ErroProtecao("A proteção de dados do Windows só existe no Windows.")


def proteger(dados: bytes) -> bytes:
    _exigir_windows()
    entrada, _buffer = _para_blob(dados)
    saida = _Blob()
    if not ctypes.windll.crypt32.CryptProtectData(ctypes.byref(entrada), None, None, None, None, 0, ctypes.byref(saida)):
        raise ErroProtecao(f"O Windows não conseguiu proteger os dados (erro {ctypes.GetLastError()}).")
    return _de_blob(saida)


def desproteger(dados: bytes) -> bytes:
    _exigir_windows()
    entrada, _buffer = _para_blob(dados)
    saida = _Blob()
    if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(entrada), None, None, None, None, 0, ctypes.byref(saida)):
        raise ErroProtecao(
            "Não foi possível abrir os dados protegidos: eles foram gravados por outro usuário do Windows "
            f"ou em outro computador (erro {ctypes.GetLastError()})."
        )
    return _de_blob(saida)
