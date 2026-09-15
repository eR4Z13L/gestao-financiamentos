"""Validacao leve de CPF/CNPJ/e-mail - usada so pra pegar erro de digitacao
na hora de cadastrar/editar um cliente. Nao bloqueia nada que ja esta na
planilha.
"""

from __future__ import annotations

import re

_EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def apenas_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor or "")


def _digito_verificador_cpf(digitos: str) -> str:
    def calcular(numeros: list[int]) -> int:
        soma = sum(n * peso for n, peso in zip(numeros, range(len(numeros) + 1, 1, -1)))
        resto = (soma * 10) % 11
        return 0 if resto == 10 else resto

    d1 = calcular([int(c) for c in digitos[:9]])
    d2 = calcular([int(c) for c in digitos[:9]] + [d1])
    return f"{d1}{d2}"


def _digito_verificador_cnpj(digitos: str) -> str:
    def calcular(numeros: list[int], pesos: list[int]) -> int:
        soma = sum(n * p for n, p in zip(numeros, pesos))
        resto = soma % 11
        return 0 if resto < 2 else 11 - resto

    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    d1 = calcular([int(c) for c in digitos[:12]], pesos1)
    pesos2 = [6] + pesos1
    d2 = calcular([int(c) for c in digitos[:12]] + [d1], pesos2)
    return f"{d1}{d2}"


def cpf_valido(valor: str) -> bool:
    digitos = apenas_digitos(valor)
    if len(digitos) != 11 or digitos == digitos[0] * 11:
        return False
    return digitos[9:] == _digito_verificador_cpf(digitos)


def cnpj_valido(valor: str) -> bool:
    digitos = apenas_digitos(valor)
    if len(digitos) != 14 or digitos == digitos[0] * 14:
        return False
    return digitos[12:] == _digito_verificador_cnpj(digitos)


def cpf_cnpj_valido(valor: str) -> bool:
    digitos = apenas_digitos(valor)
    if len(digitos) == 11:
        return cpf_valido(valor)
    if len(digitos) == 14:
        return cnpj_valido(valor)
    return False


def formatar_cpf_cnpj(valor: str) -> str:
    digitos = apenas_digitos(valor)
    if len(digitos) == 11:
        return f"{digitos[0:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:11]}"
    if len(digitos) == 14:
        return f"{digitos[0:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:14]}"
    return valor


def email_valido(valor: str) -> bool:
    """Checagem simples de formato (algo@algo.algo) - nao verifica se o
    dominio existe de verdade, so pega erro de digitacao obvio."""
    return bool(_EMAIL_REGEX.match((valor or "").strip()))
