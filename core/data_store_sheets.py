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

import threading
from datetime import datetime

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

import config
from core import data_store as bd

_ESCOPOS_LEITURA = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

_cliente = None
_planilha_em_cache: tuple | None = None  # (cliente, id da planilha, planilha aberta)
_planilha_lock = threading.Lock()
_ultima_leitura: datetime | None = None


def ultima_leitura() -> datetime | None:
    """Quando foi a ultima leitura bem-sucedida de uma aba do Sheets (None se nenhuma ainda):
    o "dados de HH:MM" que o VENDEDOR ve na barra lateral. So consulta a memoria - nao
    acessa a rede."""
    return _ultima_leitura


def _obter_cliente():
    global _cliente
    if _cliente is None:
        creds = Credentials.from_service_account_file(
            str(config.CAMINHO_CREDENCIAIS_GOOGLE), scopes=_ESCOPOS_LEITURA
        )
        _cliente = gspread.authorize(creds)
    return _cliente


def _obter_planilha():
    """A planilha aberta, reaproveitada: abrir de novo custa uma leitura na API (cota de 60 por minuto)."""
    global _planilha_em_cache
    cliente = _obter_cliente()
    chave = config.GOOGLE_SHEETS_ID
    with _planilha_lock:
        if _planilha_em_cache and _planilha_em_cache[0] is cliente and _planilha_em_cache[1] == chave:
            return _planilha_em_cache[2]
        planilha = cliente.open_by_key(chave)
        _planilha_em_cache = (cliente, chave, planilha)
        return planilha


def _ler_aba_bruta(nome_aba: str) -> pd.DataFrame:
    global _ultima_leitura
    aba = _obter_planilha().worksheet(nome_aba)
    # sem formatacao: o valor exatamente como foi gravado (texto continua texto, numero continua
    # numero). O texto "formatado" segue a configuracao regional da planilha (virgula decimal,
    # separador de milhar) e nao da pra ler de volta como numero.
    valores = aba.get_all_values(value_render_option="UNFORMATTED_VALUE")
    _ultima_leitura = datetime.now()
    if len(valores) <= 1:
        return pd.DataFrame()
    cabecalho, *linhas = valores
    return pd.DataFrame(linhas, columns=cabecalho)


def _texto_da_celula(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float):
        if valor != valor:  # NaN
            return ""
        # um numero inteiro que veio como float (85999998888.0) e o mesmo numero, sem o ".0"
        return str(int(valor)) if valor.is_integer() else str(valor)
    return str(valor).strip()


def _texto(serie: pd.Series) -> pd.Series:
    return serie.map(_texto_da_celula)


def _para_data(serie: pd.Series) -> pd.Series:
    """dd/mm/aaaa em texto (como o app envia) OU numero serial de data (planilha enviada por uma
    versao antiga do app, quando o Sheets convertia o texto em data de verdade)."""
    numeros = pd.to_numeric(serie, errors="coerce")
    em_texto = pd.to_datetime(serie.where(numeros.isna()), format="%d/%m/%Y", errors="coerce")
    seriais = pd.to_datetime(numeros, unit="D", origin="1899-12-30", errors="coerce")
    return em_texto.fillna(seriais)


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
            df[col] = _para_data(df[col])
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
            df[col] = _para_data(df[col])
        elif col in colunas_numericas:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        else:
            df[col] = _texto(df[col])
    return df
