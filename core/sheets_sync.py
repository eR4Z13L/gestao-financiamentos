"""Sincronizacao em background do .xlsx local (fonte de verdade, sempre
escrita primeiro) para uma planilha no Google Sheets na nuvem.

Existe pra permitir acesso remoto aos dados (ex: vendedores fora do
computador do ADMIN, na Fase 2) sem o app local depender de internet pra
funcionar: toda escrita local acontece normalmente mesmo sem rede; so DEPOIS
de salvar local com sucesso e que tentamos replicar na nuvem, em background,
sem bloquear quem chamou.

Se a sincronizacao falhar (sem internet, credencial ausente, API fora do
ar), o erro so vai pro log - nunca propaga pra quem fez a escrita local. Cada
sincronizacao manda o estado ATUAL COMPLETO da aba (sobrescrevendo, nao um
diff incremental), entao uma tentativa perdida nunca deixa a planilha "meio
atualizada": a proxima escrita local (e portanto a proxima sincronizacao) ja
manda tudo certo de novo.
"""

from __future__ import annotations

import logging
import threading

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

import config

_logger = logging.getLogger(__name__)

_ESCOPOS = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

_cliente_lock = threading.Lock()
_cliente = None


def _obter_cliente():
    """Autoriza (uma vez, com cache em memoria) o cliente gspread com a
    conta de servico do ADMIN. So e chamada dentro da thread de
    sincronizacao - se a credencial nao existir (ex: maquina de um
    VENDEDOR, que nunca deveria escrever), a excecao e tratada como
    qualquer outra falha de sincronizacao (log, tenta de novo depois)."""
    global _cliente
    with _cliente_lock:
        if _cliente is None:
            creds = Credentials.from_service_account_file(
                str(config.CAMINHO_CREDENCIAIS_GOOGLE), scopes=_ESCOPOS
            )
            _cliente = gspread.authorize(creds)
        return _cliente


def _valor_serializavel(valor):
    """None/NaN/NaT viram celula vazia (nunca o texto literal "nan"/"None"/
    "NaT"); datas viram texto dd/mm/aaaa - o Sheets (JSON) nao entende
    pd.Timestamp nem pd.NaT diretamente."""
    if valor is None:
        return ""
    if pd.isna(valor):  # cobre NaN, NaT e pd.NA - nao so float
        return ""
    if isinstance(valor, pd.Timestamp):
        return valor.strftime("%d/%m/%Y")
    return valor


def _preparar_linhas(df: pd.DataFrame) -> list[list]:
    cabecalho = list(df.columns)
    linhas = [cabecalho]
    for _, linha in df.iterrows():
        linhas.append([_valor_serializavel(v) for v in linha])
    return linhas


def _sincronizar_agora(nome_aba: str, df: pd.DataFrame) -> None:
    cliente = _obter_cliente()
    planilha = cliente.open_by_key(config.GOOGLE_SHEETS_ID)
    try:
        aba = planilha.worksheet(nome_aba)
    except gspread.WorksheetNotFound:
        aba = planilha.add_worksheet(
            title=nome_aba, rows=max(len(df) + 10, 100), cols=max(len(df.columns) + 2, 10)
        )

    # sobrescreve a aba inteira com o estado atual - ver docstring do modulo
    # sobre por que isso e mais robusto que sincronizar so as mudancas.
    aba.clear()
    linhas = _preparar_linhas(df)
    aba.update(linhas, "A1", value_input_option="USER_ENTERED")


def sincronizar_em_background(nome_aba: str, df: pd.DataFrame) -> None:
    """Dispara a sincronizacao de `df` (o estado JA COMPUTADO/completo da
    aba, do jeito que core.data_store.ler_* devolve) numa thread separada.
    Nunca bloqueia quem chamou nem propaga erro - so registra no log."""
    if not config.SINCRONIZACAO_GOOGLE_ATIVADA:
        return

    def _tarefa() -> None:
        try:
            _sincronizar_agora(nome_aba, df)
            _logger.info("Sincronizado com o Google Sheets: aba %s (%d linha(s)).", nome_aba, len(df))
        except Exception:
            _logger.warning(
                "Falha ao sincronizar a aba %s com o Google Sheets - "
                "a proxima escrita local tenta de novo.",
                nome_aba,
                exc_info=True,
            )

    threading.Thread(target=_tarefa, daemon=True, name=f"sync-sheets-{nome_aba}").start()
