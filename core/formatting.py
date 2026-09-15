"""Formatacao de valores pra exibicao nas telas. Um valor ausente (None/NaN)
sempre vira "—" - nunca um numero quebrado tipo "R$ nan" ou uma celula em
branco sem explicacao (existia na planilha um caso assim: proposta antiga
sem VALOR/MESES preenchido, e a tela mostrava "R$ nan" literalmente).
"""

from __future__ import annotations

import pandas as pd

_AUSENTE = "—"


def formatar_reais(valor) -> str:
    if pd.isna(valor):
        return _AUSENTE
    texto = f"{valor:,.2f}"
    return "R$ " + texto.replace(",", "X").replace(".", ",").replace("X", ".")


def formatar_data(valor) -> str:
    if isinstance(valor, pd.Timestamp) and not pd.isna(valor):
        return valor.strftime("%d/%m/%Y")
    return _AUSENTE


def formatar_meses(valor) -> str:
    if pd.isna(valor):
        return _AUSENTE
    return str(int(valor))
