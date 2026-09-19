"""Leitura (SO leitura) dos dados direto do Google Sheets - usada quando
quem esta logado e um VENDEDOR (Fase 2), que pode estar em outro computador,
sem acesso ao .xlsx local do ADMIN. Devolve DataFrames no MESMO formato que
core/data_store.py (mesmas colunas e tipos), pra core/clientes.py e
core/propostas.py nao precisarem saber qual e a fonte ativa.

Aviso de seguranca: por enquanto usa a MESMA credencial do ADMIN (com
permissao de escrita) - suficiente pra testar a Fase 2 de ponta a ponta.
Antes de distribuir pra maquina de um vendedor de verdade, troque por uma
conta de servico com escopo SO DE LEITURA (veja o README) - assim, mesmo que
a credencial vaze, nao da pra escrever na planilha partilhada por fora do
app.
"""

from __future__ import annotations

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

import config
from core import data_store as bd

_ESCOPOS_LEITURA = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

_cliente = None


def _obter_cliente():
    global _cliente
    if _cliente is None:
        creds = Credentials.from_service_account_file(
            str(config.CAMINHO_CREDENCIAIS_GOOGLE), scopes=_ESCOPOS_LEITURA
        )
        _cliente = gspread.authorize(creds)
    return _cliente


def _ler_aba_bruta(nome_aba: str) -> pd.DataFrame:
    cliente = _obter_cliente()
    planilha = cliente.open_by_key(config.GOOGLE_SHEETS_ID)
    aba = planilha.worksheet(nome_aba)
    valores = aba.get_all_values()
    if len(valores) <= 1:
        return pd.DataFrame()
    cabecalho, *linhas = valores
    return pd.DataFrame(linhas, columns=cabecalho)


def _texto(serie: pd.Series) -> pd.Series:
    return serie.fillna("").astype(str).str.strip()


def _com_colunas_esperadas(df: pd.DataFrame, colunas: list[str]) -> pd.DataFrame:
    """Garante que todas as colunas esperadas existam (mesmo que a aba no
    Sheets tenha sido editada manualmente e perdido alguma), na ordem certa."""
    for col in colunas:
        if col not in df.columns:
            df[col] = ""
    return df[colunas]


def ler_clientes() -> pd.DataFrame:
    df = _ler_aba_bruta(bd.ABA_CLIENTES)
    if df.empty:
        return pd.DataFrame(columns=bd.CLIENTES_COLUNAS)
    df = _com_colunas_esperadas(df, bd.CLIENTES_COLUNAS)
    for col in bd.CLIENTES_COLUNAS:
        if col in ("DATA CADASTRO", "NASCIMENTO"):
            df[col] = pd.to_datetime(df[col], format="%d/%m/%Y", errors="coerce")
        else:
            df[col] = _texto(df[col])
    return df


def ler_equipamentos() -> pd.DataFrame:
    df = _ler_aba_bruta(bd.ABA_EQUIPAMENTOS)
    if df.empty:
        return pd.DataFrame(columns=bd.EQUIPAMENTOS_COLUNAS)
    df = _com_colunas_esperadas(df, bd.EQUIPAMENTOS_COLUNAS)
    colunas_numericas = {"PARCELAS", "VALOR PARCELA (R$)", "VALOR LÍQUIDO/REFERÊNCIA (R$)"}
    for col in bd.EQUIPAMENTOS_COLUNAS:
        if col in colunas_numericas:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = _texto(df[col])
    return df


def ler_vendedores() -> pd.DataFrame:
    df = _ler_aba_bruta(bd.ABA_VENDEDORES)
    if df.empty:
        return pd.DataFrame(columns=bd.VENDEDORES_COLUNAS)
    df = _com_colunas_esperadas(df, bd.VENDEDORES_COLUNAS)
    for col in bd.VENDEDORES_COLUNAS:
        df[col] = _texto(df[col])
    return df


def ler_propostas() -> pd.DataFrame:
    """A aba PROPOSTAS no Sheets ja chega com VENDEDOR/CLIENTE/TEMPO
    calculados (core/data_store.py sincroniza a visao completa, nunca
    formulas) - so precisa reconverter tipos, sem VLOOKUP nenhum aqui."""
    df = _ler_aba_bruta(bd.ABA_PROPOSTAS)
    if df.empty:
        return pd.DataFrame(columns=bd.PROPOSTAS_COLUNAS)
    df = _com_colunas_esperadas(df, bd.PROPOSTAS_COLUNAS)
    colunas_numericas = {"VALOR (R$)", "MESES"}
    for col in bd.PROPOSTAS_COLUNAS:
        if col == "DATA":
            df[col] = pd.to_datetime(df[col], format="%d/%m/%Y", errors="coerce")
        elif col in colunas_numericas:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = _texto(df[col])
    return df
