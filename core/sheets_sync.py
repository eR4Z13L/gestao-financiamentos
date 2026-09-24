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
from dataclasses import dataclass
from datetime import datetime

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

# -- estado da sincronizacao (pro indicador da barra lateral) ------------------------
# So bookkeeping em memoria: quem le (a interface) nunca dispara rede, e as threads de
# sincronizacao gravam aqui atras de um lock. O erro guardado e so um texto curto - o
# detalhe completo continua no log.

NIVEL_DESATIVADA = "desativada"
NIVEL_AGUARDANDO = "aguardando"  # ligada, mas nenhuma sincronizacao tentada ainda nesta execucao
NIVEL_SINCRONIZANDO = "sincronizando"
NIVEL_OK = "ok"
NIVEL_FALHOU = "falhou"

_TAMANHO_MAXIMO_ERRO = 400

_estado_lock = threading.Lock()
_em_andamento = 0
_ultimo_sucesso: datetime | None = None
_ultima_falha: datetime | None = None
_ultimo_erro = ""

# -- fila de repeticao (E9) ---------------------------------------------------------
# Toda vez que uma sincronizacao e disparada, a aba entra aqui (o ultimo df que se
# tentou mandar) e so sai quando ESSA tentativa especifica confirma sucesso. Assim,
# se a rede cair, a aba fica "pendente" ate uma proxima tentativa dar certo - seja a
# proxima ESCRITA de verdade naquela aba (fluxo de sempre), o botao "Sincronizar
# agora" (core.sincronizacao), ou o timer periodico que chama reenviar_pendentes()
# (desktop/main_window.py). Guardar o df (nao so o nome da aba) evita reler o disco
# aqui - quem quiser reler antes de tentar de novo (como "Sincronizar agora") so
# chama sincronizar_em_background() com um df fresco, que substitui o pendente.
_pendentes_lock = threading.Lock()
_pendentes: dict[str, pd.DataFrame] = {}


@dataclass(frozen=True)
class EstadoSincronizacao:
    ativada: bool
    em_andamento: int  # sincronizacoes disparadas que ainda nao terminaram
    ultimo_sucesso: datetime | None
    ultima_falha: datetime | None
    ultimo_erro: str  # texto da ultima falha ("" se nunca falhou)

    @property
    def nivel(self) -> str:
        """Em que pe esta: desativada / aguardando / sincronizando / ok / falhou. "Falhou" so
        vale enquanto a falha for mais recente que o ultimo sucesso - uma sincronizacao
        boa depois dela volta pra "ok"."""
        if not self.ativada:
            return NIVEL_DESATIVADA
        if self.em_andamento > 0:
            return NIVEL_SINCRONIZANDO
        if self.ultima_falha is not None and (self.ultimo_sucesso is None or self.ultima_falha >= self.ultimo_sucesso):
            return NIVEL_FALHOU
        if self.ultimo_sucesso is not None:
            return NIVEL_OK
        return NIVEL_AGUARDANDO


def estado_atual() -> EstadoSincronizacao:
    """Copia do estado de agora (seguro de chamar de qualquer thread, nao acessa a rede)."""
    with _estado_lock:
        return EstadoSincronizacao(
            ativada=config.SINCRONIZACAO_GOOGLE_ATIVADA,
            em_andamento=_em_andamento,
            ultimo_sucesso=_ultimo_sucesso,
            ultima_falha=_ultima_falha,
            ultimo_erro=_ultimo_erro,
        )


def _registrar_inicio() -> None:
    global _em_andamento
    with _estado_lock:
        _em_andamento += 1


def _registrar_fim(erro: BaseException | None) -> None:
    global _em_andamento, _ultimo_sucesso, _ultima_falha, _ultimo_erro
    with _estado_lock:
        _em_andamento = max(_em_andamento - 1, 0)
        if erro is None:
            _ultimo_sucesso = datetime.now()
        else:
            _ultima_falha = datetime.now()
            _ultimo_erro = f"{type(erro).__name__}: {erro}"[:_TAMANHO_MAXIMO_ERRO]


def _reiniciar_estado() -> None:
    """So pros testes: volta ao estado de "nada aconteceu ainda"."""
    global _em_andamento, _ultimo_sucesso, _ultima_falha, _ultimo_erro
    with _estado_lock:
        _em_andamento = 0
        _ultimo_sucesso = None
        _ultima_falha = None
        _ultimo_erro = ""
    with _pendentes_lock:
        _pendentes.clear()


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
    Nunca bloqueia quem chamou nem propaga erro - so registra no log.

    Enquanto essa tentativa nao confirmar sucesso, a aba fica em _pendentes - se essa
    tentativa falhar, reenviar_pendentes() (chamado periodicamente, ver
    desktop/main_window.py) tenta de novo sozinho, sem esperar a proxima escrita
    naquela aba."""
    if not config.SINCRONIZACAO_GOOGLE_ATIVADA:
        return

    with _pendentes_lock:
        _pendentes[nome_aba] = df

    def _tarefa() -> None:
        erro: Exception | None = None
        try:
            _sincronizar_agora(nome_aba, df)
            with _pendentes_lock:
                if _pendentes.get(nome_aba) is df:  # nao apaga um pendente mais novo (outra tentativa ja disparada)
                    del _pendentes[nome_aba]
            _logger.info("Sincronizado com o Google Sheets: aba %s (%d linha(s)).", nome_aba, len(df))
        except Exception as exc:
            erro = exc
            _logger.warning(
                "Falha ao sincronizar a aba %s com o Google Sheets - fica na fila de repeticao.",
                nome_aba,
                exc_info=True,
            )
        finally:
            _registrar_fim(erro)

    # registra ANTES de iniciar a thread: assim o indicador ja mostra "sincronizando" e
    # nunca ha uma janela em que a sincronizacao existe mas o estado diz que nao
    _registrar_inicio()
    try:
        threading.Thread(target=_tarefa, daemon=True, name=f"sync-sheets-{nome_aba}").start()
    except Exception as exc:  # sem thread nao ha sincronizacao: conta como falha, nunca em silencio
        _registrar_fim(exc)
        _logger.warning("Nao foi possivel iniciar a sincronizacao da aba %s.", nome_aba, exc_info=True)


def reenviar_pendentes() -> None:
    """Tenta de novo cada aba que ainda esta pendente (a ultima tentativa falhou, ou
    nunca terminou). Chamada periodicamente (desktop/main_window.py) - assim uma queda
    de rede passageira se resolve sozinha, sem esperar a proxima edicao naquela aba
    nem precisar clicar em "Sincronizar agora"."""
    with _pendentes_lock:
        pendentes = dict(_pendentes)
    for nome_aba, df in pendentes.items():
        sincronizar_em_background(nome_aba, df)
