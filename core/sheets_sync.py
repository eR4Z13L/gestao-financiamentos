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

DOIS COMPUTADORES (trava de versao): como cada envio sobrescreve a aba inteira, dois PCs
com arquivos diferentes se apagariam um ao outro. Por isso a nuvem tem uma aba META com um
numero de VERSAO, e cada PC guarda (core/estado_sincronizacao.py) a versao que conhece. Antes
de enviar, o app confere se a versao da nuvem e a que ele conhece; se outro PC gravou no meio,
o envio e RECUSADO (ConflitoDeSincronizacao) em vez de sobrescrever calado, e quem decide o que
fazer e a pessoa (core/sincronizacao.py). A META tambem guarda quem esta com o app aberto
(sinal de vida, so um AVISO: nao bloqueia nada).
"""

from __future__ import annotations

import logging
import socket
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

import config
from core import estado_sincronizacao as estado_mod

_logger = logging.getLogger(__name__)

_ESCOPOS = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

_cliente_lock = threading.Lock()
_cliente = None
_planilha_lock = threading.Lock()
_planilha_em_cache: tuple | None = None  # (cliente, id da planilha, planilha aberta)

# -- aba META (versao + sinal de "outro computador editando") ---------------------------
# Celulas fixas numa coluna de valores (B): cada escrita mexe SO nas celulas dela, nunca
# regrava a aba toda - assim o envio (B2:B4) e o sinal de vida (B5:B6) nao se atropelam.
ABA_META = "META"
_CABECALHO_META = [
    ["CHAVE", "VALOR"],
    ["revisao", 1],
    ["ultimo_escritor", ""],
    ["ultima_gravacao", ""],
    ["editando_por", ""],
    ["ultimo_sinal", ""],
]
_FAIXA_DE_LEITURA_META = "B2:B6"
_FAIXA_DO_ENVIO = "B2:B4"  # revisao, ultimo_escritor, ultima_gravacao
_FAIXA_DO_SINAL = "B5:B6"  # editando_por, ultimo_sinal
_FORMATO_DO_MOMENTO = "%Y-%m-%dT%H:%M:%SZ"  # sempre UTC: os dois PCs podem estar em fusos/relogios diferentes

# Sem sinal ha mais que isso = o outro computador nao esta mais com o app aberto (fechou sem
# limpar, travou, ficou sem internet). Cobre um relogio adiantado/atrasado de alguns minutos.
JANELA_DO_SINAL = timedelta(minutes=5)

TIPO_SEM_CONTROLE = "sem_controle"  # a nuvem ainda nao tem a aba META (nunca recebeu um envio controlado)
TIPO_DIVERGENTE = "divergente"  # a nuvem esta numa versao que este PC nao conhece: outro PC gravou

# -- estado da sincronizacao (pro indicador da barra lateral) ------------------------
# So bookkeeping em memoria: quem le (a interface) nunca dispara rede, e as threads de
# sincronizacao gravam aqui atras de um lock. O erro guardado e so um texto curto - o
# detalhe completo continua no log.

NIVEL_DESATIVADA = "desativada"
NIVEL_AGUARDANDO = "aguardando"  # ligada, mas nenhuma sincronizacao tentada ainda nesta execucao
NIVEL_SINCRONIZANDO = "sincronizando"
NIVEL_OK = "ok"
NIVEL_FALHOU = "falhou"
NIVEL_CONFLITO = "conflito"  # a nuvem mudou por outro PC: um envio foi recusado e espera decisao
NIVEL_ATENCAO = "atencao"  # aviso sem urgencia: outro computador ativo / nuvem com dados mais novos

_TAMANHO_MAXIMO_ERRO = 400

_estado_lock = threading.Lock()
_em_andamento = 0
_ultimo_sucesso: datetime | None = None
_ultima_falha: datetime | None = None
_ultimo_erro = ""
_conflito: ConflitoDeSincronizacao | None = None
_aviso: tuple[str, str] = ("", "")  # (frase curta, detalhe)

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
_geracao: dict[str, int] = {}  # quantas vezes cada aba foi disparada: so a ULTIMA tentativa limpa o "pendente" em disco

# uma tentativa de envio por vez neste processo (a versao lida, o envio e a versao nova formam um bloco so)
_envio_lock = threading.Lock()
_sinal_lock = threading.Lock()
_sinal_enviado = False  # este PC registrou sinal nesta execucao (entao limpa ao sair)

_NOME_DA_MAQUINA: str | None = None  # so os testes trocam (simular dois computadores)

# "Baixar da nuvem" troca os dados locais: qualquer envio que ja estava na fila/em andamento carrega
# dados VELHOS e, se seguisse, sobrescreveria a nuvem com eles. A epoca sobe a cada download e um
# envio de epoca anterior e descartado (EnvioDescartado) em vez de enviado.
_epoca = 0
_contexto = threading.local()  # a epoca em que cada thread de envio foi disparada


class EnvioDescartado(Exception):
    """O envio foi disparado antes de um "Baixar da nuvem": os dados dele ficaram velhos."""


class ConflitoDeSincronizacao(Exception):
    """Um envio foi RECUSADO porque a nuvem esta numa versao que este computador nao conhece (ou
    ainda nao tem controle de versao). Nada foi escrito na nuvem."""

    def __init__(self, tipo: str, meta: MetaNuvem, revisao_local: int | None, mensagem: str):
        super().__init__(mensagem)
        self.tipo = tipo
        self.meta = meta
        self.revisao_local = revisao_local


@dataclass(frozen=True)
class MetaNuvem:
    existe: bool = False
    revisao: int = 0
    ultimo_escritor: str = ""
    ultima_gravacao: datetime | None = None  # UTC, com fuso
    editando_por: str = ""
    ultimo_sinal: datetime | None = None  # UTC, com fuso

    @property
    def com_controle(self) -> bool:
        """A nuvem ja recebeu ao menos um envio controlado (a META existe e tem uma versao)."""
        return self.existe and self.revisao >= 1


@dataclass(frozen=True)
class EstadoSincronizacao:
    ativada: bool
    em_andamento: int  # sincronizacoes disparadas que ainda nao terminaram
    ultimo_sucesso: datetime | None
    ultima_falha: datetime | None
    ultimo_erro: str  # texto da ultima falha ("" se nunca falhou)
    conflito: str = ""  # TIPO_* do conflito esperando decisao ("" = nenhum)
    aviso: str = ""  # frase curta do aviso sem urgencia ("" = nenhum)
    aviso_detalhe: str = ""

    @property
    def nivel(self) -> str:
        """Em que pe esta: desativada / aguardando / sincronizando / conflito / falhou / atencao / ok.
        "Falhou" so vale enquanto a falha for mais recente que o ultimo sucesso - uma sincronizacao
        boa depois dela volta pra "ok". Conflito exige uma decisao, entao vem antes de tudo menos
        de "sincronizando"."""
        if not self.ativada:
            return NIVEL_DESATIVADA
        if self.em_andamento > 0:
            return NIVEL_SINCRONIZANDO
        if self.conflito:
            return NIVEL_CONFLITO
        if self.ultima_falha is not None and (self.ultimo_sucesso is None or self.ultima_falha >= self.ultimo_sucesso):
            return NIVEL_FALHOU
        if self.aviso:
            return NIVEL_ATENCAO
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
            conflito=_conflito.tipo if _conflito is not None else "",
            aviso=_aviso[0],
            aviso_detalhe=_aviso[1],
        )


def conflito_atual() -> ConflitoDeSincronizacao | None:
    with _estado_lock:
        return _conflito


def limpar_conflito() -> None:
    """A pessoa resolveu (baixou da nuvem, ou mandou o que tem aqui): os envios voltam ao normal."""
    global _conflito
    with _estado_lock:
        _conflito = None


def sinalizar_conflito(meta: MetaNuvem) -> None:
    """Deixa o indicador mostrando o conflito quando a pessoa adiou a decisao no aviso de abertura
    (sem isso ele so apareceria na proxima gravacao). Nao faz nada se nao ha conflito."""
    try:
        _conferir_versao(meta, estado_mod.ler())
    except ConflitoDeSincronizacao as exc:
        _registrar_conflito(exc)


def _registrar_conflito(exc: ConflitoDeSincronizacao) -> None:
    global _conflito
    with _estado_lock:
        _conflito = exc


def _registrar_inicio() -> None:
    global _em_andamento
    with _estado_lock:
        _em_andamento += 1


def _registrar_fim(erro: BaseException | None, *, sem_resultado: bool = False) -> None:
    global _em_andamento, _ultimo_sucesso, _ultima_falha, _ultimo_erro
    with _estado_lock:
        _em_andamento = max(_em_andamento - 1, 0)
        if sem_resultado:
            return  # nem sucesso nem falha de rede: recusado de proposito (conflito) ou descartado (dados velhos)
        if erro is None:
            _ultimo_sucesso = datetime.now()
        else:
            _ultima_falha = datetime.now()
            _ultimo_erro = f"{type(erro).__name__}: {erro}"[:_TAMANHO_MAXIMO_ERRO]


def _reiniciar_estado() -> None:
    """So pros testes: volta ao estado de "nada aconteceu ainda"."""
    global _em_andamento, _ultimo_sucesso, _ultima_falha, _ultimo_erro, _conflito, _aviso, _sinal_enviado, _epoca
    with _estado_lock:
        _em_andamento = 0
        _ultimo_sucesso = None
        _ultima_falha = None
        _ultimo_erro = ""
        _conflito = None
        _aviso = ("", "")
    _sinal_enviado = False
    _epoca = 0
    _esquecer_planilha_aberta()
    with _pendentes_lock:
        _pendentes.clear()
        _geracao.clear()


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


def _obter_planilha():
    """A planilha aberta, reaproveitada entre chamadas: abrir de novo custa uma leitura de metadados na
    API, e a cota do Google (60 leituras por minuto) e da conta de servico - dividida entre os dois PCs."""
    global _planilha_em_cache
    cliente = _obter_cliente()
    chave = config.GOOGLE_SHEETS_ID
    with _planilha_lock:
        if _planilha_em_cache and _planilha_em_cache[0] is cliente and _planilha_em_cache[1] == chave:
            return _planilha_em_cache[2]
        planilha = cliente.open_by_key(chave)
        _planilha_em_cache = (cliente, chave, planilha)
        return planilha


def _esquecer_planilha_aberta() -> None:
    global _planilha_em_cache
    with _planilha_lock:
        _planilha_em_cache = None


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


# -- META: leitura e escrita -----------------------------------------------------------

def nome_desta_maquina() -> str:
    return _NOME_DA_MAQUINA or socket.gethostname()


def _agora_utc() -> datetime:
    return datetime.now(timezone.utc)


def _texto_do_momento(momento: datetime) -> str:
    return momento.astimezone(timezone.utc).strftime(_FORMATO_DO_MOMENTO)


def _momento(texto) -> datetime | None:
    try:
        return datetime.strptime(str(texto).strip(), _FORMATO_DO_MOMENTO).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _inteiro(valor) -> int:
    try:
        return int(float(str(valor).strip()))
    except ValueError:
        return 0


def _ler_meta(planilha) -> MetaNuvem:
    return _ler_meta_com_aba(planilha)[0]


def _ler_meta_com_aba(planilha) -> tuple[MetaNuvem, object | None]:
    """A META e a propria aba (None se ela nao existe): quem for escrever nela reaproveita a aba, sem
    procurar de novo (cada procura e uma leitura da API)."""
    try:
        aba = planilha.worksheet(ABA_META)
    except gspread.WorksheetNotFound:
        return MetaNuvem(), None
    linhas = aba.get(_FAIXA_DE_LEITURA_META, value_render_option="UNFORMATTED_VALUE")
    # o Sheets omite as celulas vazias do fim: completa pra sempre ter as 5 posicoes
    valores = [(linha[0] if linha else "") for linha in linhas] + [""] * 5
    meta = MetaNuvem(
        existe=True,
        revisao=_inteiro(valores[0]),
        ultimo_escritor=str(valores[1]),
        ultima_gravacao=_momento(valores[2]),
        editando_por=str(valores[3]),
        ultimo_sinal=_momento(valores[4]),
    )
    return meta, aba


def _garantir_meta(planilha) -> None:
    """Cria a aba META (versao 1) se ainda nao existir. So o envio forcado chama isto: e o momento
    em que esta planilha passa a ter controle de versao."""
    try:
        planilha.worksheet(ABA_META)
    except gspread.WorksheetNotFound:
        aba = planilha.add_worksheet(title=ABA_META, rows=10, cols=3)
        aba.update(_CABECALHO_META, "A1", raw=True)


def _gravar_meta_pos_envio(aba_meta, nova_revisao: int) -> None:
    aba_meta.update(
        [[nova_revisao], [nome_desta_maquina()], [_texto_do_momento(_agora_utc())]],
        _FAIXA_DO_ENVIO,
        raw=True,
    )


def ler_meta_da_nuvem() -> MetaNuvem:
    """Le a META na nuvem agora (rede!). Levanta a excecao de rede/credencial - quem chama decide."""
    return _ler_meta(_obter_planilha())


def _conferir_versao(meta: MetaNuvem, local: estado_mod.EstadoLocal) -> None:
    if not meta.com_controle:
        raise ConflitoDeSincronizacao(
            TIPO_SEM_CONTROLE,
            meta,
            local.revisao_conhecida,
            "A planilha na nuvem ainda não tem controle de versão. Envie os dados deste computador "
            "de propósito (no computador que tiver os dados mais recentes) para ligar o controle.",
        )
    if local.revisao_conhecida != meta.revisao:
        raise ConflitoDeSincronizacao(
            TIPO_DIVERGENTE,
            meta,
            local.revisao_conhecida,
            f"A nuvem foi atualizada por outro computador ({meta.ultimo_escritor or 'desconhecido'}) "
            "depois da última vez que este atualizou.",
        )


def _escrever_aba(planilha, nome_aba: str, df: pd.DataFrame) -> None:
    try:
        aba = planilha.worksheet(nome_aba)
    except gspread.WorksheetNotFound:
        aba = planilha.add_worksheet(
            title=nome_aba, rows=max(len(df) + 10, 100), cols=max(len(df.columns) + 2, 10)
        )
    # sobrescreve a aba inteira com o estado atual - ver docstring do modulo sobre por que isso e
    # mais robusto que sincronizar so as mudancas. "raw": o texto vai EXATAMENTE como esta (o
    # modo "USER_ENTERED" tirava o zero da frente de CPF/CNPJ digitado so com numeros e
    # transformava um texto que comeca com "=" numa formula) - e o que permite BAIXAR de volta
    # sem perder nada.
    aba.clear()
    aba.update(_preparar_linhas(df), "A1", raw=True)


def _sincronizar_agora(nome_aba: str, df: pd.DataFrame) -> None:
    planilha = _obter_planilha()
    with _envio_lock:
        if getattr(_contexto, "epoca", _epoca) != _epoca:
            raise EnvioDescartado()
        meta, aba_meta = _ler_meta_com_aba(planilha)
        _conferir_versao(meta, estado_mod.ler())  # ConflitoDeSincronizacao: nada e escrito
        _escrever_aba(planilha, nome_aba, df)
        nova = meta.revisao + 1
        _gravar_meta_pos_envio(aba_meta, nova)
        estado_mod.definir_revisao(nova)


def sincronizar_em_background(nome_aba: str, df: pd.DataFrame) -> None:
    """Dispara a sincronizacao de `df` (o estado JA COMPUTADO/completo da
    aba, do jeito que core.data_store.ler_* devolve) numa thread separada.
    Nunca bloqueia quem chamou nem propaga erro - so registra no log.

    Enquanto essa tentativa nao confirmar sucesso, a aba fica em _pendentes - se essa
    tentativa falhar, reenviar_pendentes() (chamado periodicamente, ver
    desktop/main_window.py) tenta de novo sozinho, sem esperar a proxima escrita
    naquela aba. A aba tambem fica marcada como pendente EM DISCO (core.estado_sincronizacao),
    pra esse aviso sobreviver a fechar o app.

    Com um conflito esperando decisao, nada e enviado (a alteracao fica salva so aqui e
    marcada pendente): o envio so volta depois que a pessoa resolver."""
    if not config.SINCRONIZACAO_GOOGLE_ATIVADA:
        return

    try:
        estado_mod.marcar_pendente(nome_aba)
    except Exception:  # nunca atrapalha quem acabou de salvar - so perde a protecao extra
        _logger.warning("Nao foi possivel gravar o estado da sincronizacao (aba %s).", nome_aba, exc_info=True)

    if conflito_atual() is not None:
        _logger.info("Envio da aba %s adiado: ha um conflito com a nuvem esperando decisao.", nome_aba)
        return

    with _pendentes_lock:
        _pendentes[nome_aba] = df
        _geracao[nome_aba] = _geracao.get(nome_aba, 0) + 1
        minha_geracao = _geracao[nome_aba]
        minha_epoca = _epoca

    def _tarefa() -> None:
        erro: Exception | None = None
        sem_resultado = False
        _contexto.epoca = minha_epoca
        try:
            _sincronizar_agora(nome_aba, df)
            with _pendentes_lock:
                if _pendentes.get(nome_aba) is df:  # nao apaga um pendente mais novo (outra tentativa ja disparada)
                    del _pendentes[nome_aba]
                so_esta_tentativa_pendente = _geracao.get(nome_aba) == minha_geracao
            if so_esta_tentativa_pendente:  # uma tentativa mais nova ainda nao confirmou: a aba continua pendente
                try:
                    estado_mod.limpar_pendente(nome_aba)
                except Exception:
                    _logger.warning("Nao foi possivel gravar o estado da sincronizacao (aba %s).", nome_aba, exc_info=True)
            _logger.info("Sincronizado com o Google Sheets: aba %s (%d linha(s)).", nome_aba, len(df))
        except EnvioDescartado:
            sem_resultado = True
            _logger.info("Envio da aba %s descartado: os dados locais mudaram (baixou da nuvem) depois de ele ser disparado.", nome_aba)
        except ConflitoDeSincronizacao as exc:
            sem_resultado = True
            _registrar_conflito(exc)
            with _pendentes_lock:
                if _pendentes.get(nome_aba) is df:  # tentar de novo a cada minuto so repetiria a recusa
                    del _pendentes[nome_aba]
            _logger.warning("Envio da aba %s recusado: %s", nome_aba, exc)
        except Exception as exc:
            erro = exc
            _logger.warning(
                "Falha ao sincronizar a aba %s com o Google Sheets - fica na fila de repeticao.",
                nome_aba,
                exc_info=True,
            )
        finally:
            _registrar_fim(erro, sem_resultado=sem_resultado)

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


def bloqueio_de_envio():
    """Segura os envios deste processo enquanto um download da nuvem le e troca os dados locais
    (um envio no meio mandaria dados velhos por cima da nuvem)."""
    return _envio_lock


def descartar_envios_velhos() -> None:
    """Chamado DEPOIS de trocar os dados locais pelos da nuvem: o que estava na fila ou em andamento
    ficou velho e nao pode mais ser enviado."""
    global _epoca
    _epoca += 1
    with _pendentes_lock:
        _pendentes.clear()


def preparar_envio_forcado() -> MetaNuvem:
    """Passo antes de MANDAR O QUE ESTA AQUI por cima da nuvem, de propósito (a pessoa escolheu):
    garante a aba META e adota a versao que a nuvem tem agora como "a que este PC conhece" - assim
    os envios seguintes passam pela trava. Nao envia nada por si so. Rede!"""
    planilha = _obter_planilha()
    with _envio_lock:
        _garantir_meta(planilha)
        meta = _ler_meta(planilha)
        estado_mod.definir_revisao(meta.revisao)
    limpar_conflito()
    return meta


# -- sinal de vida: "outro computador esta editando" ---------------------------------------

def outro_computador_ativo(meta: MetaNuvem, agora: datetime | None = None) -> tuple[str, datetime] | None:
    """(nome, momento do ultimo sinal) se OUTRO computador deu sinal dentro da janela, senao None."""
    if not meta.existe or not meta.editando_por or meta.ultimo_sinal is None:
        return None
    if meta.editando_por == nome_desta_maquina():
        return None
    if (agora or _agora_utc()) - meta.ultimo_sinal > JANELA_DO_SINAL:
        return None
    return meta.editando_por, meta.ultimo_sinal


def _atualizar_aviso(meta: MetaNuvem) -> None:
    global _aviso
    aviso = ("", "")
    outro = outro_computador_ativo(meta)
    if outro is not None:
        nome, quando = outro
        hora = quando.astimezone().strftime("%H:%M")
        aviso = (
            "Outro computador ativo",
            f"O computador {nome} está com o aplicativo aberto como Administrador (último sinal às {hora}). "
            "Gravar nos dois ao mesmo tempo pode gerar conflito.",
        )
    else:
        local = estado_mod.ler()
        if meta.com_controle and local.revisao_conhecida != meta.revisao and not local.abas_pendentes:
            aviso = (
                "Nuvem com dados mais novos",
                "Outro computador enviou dados depois da última vez que este atualizou. Em Administração > "
                "Sincronização e backup, use \"Baixar da nuvem\" para trazer esses dados.",
            )
    with _estado_lock:
        _aviso = aviso


def registrar_sinal() -> MetaNuvem:
    """Le a META (pra avisar se OUTRO computador esta ativo) e registra este como ativo agora. So
    escreve se a nuvem ja tem controle de versao. Rede!"""
    global _sinal_enviado
    meta, aba_meta = _ler_meta_com_aba(_obter_planilha())
    if aba_meta is not None:
        aba_meta.update(
            [[nome_desta_maquina()], [_texto_do_momento(_agora_utc())]], _FAIXA_DO_SINAL, raw=True
        )
        _sinal_enviado = True
    _atualizar_aviso(meta)
    return meta


def limpar_sinal() -> None:
    """Tira o "estou editando" - so se o sinal que esta la e DESTE computador (nunca apaga o de outro). Rede!"""
    meta, aba_meta = _ler_meta_com_aba(_obter_planilha())
    if aba_meta is not None and meta.editando_por == nome_desta_maquina():
        aba_meta.update([[""], [""]], _FAIXA_DO_SINAL, raw=True)


def enviar_sinal_em_background() -> None:
    """Um batimento (a cada ~1 min, ver desktop/main_window.py): nunca bloqueia nem propaga erro.
    Se o batimento anterior ainda nao terminou, este e pulado."""
    if not config.SINCRONIZACAO_GOOGLE_ATIVADA:
        return

    def _tarefa() -> None:
        try:
            registrar_sinal()
        except Exception:
            _logger.warning("Falha ao registrar o sinal de atividade na nuvem.", exc_info=True)
        finally:
            _sinal_lock.release()

    if not _sinal_lock.acquire(blocking=False):
        return
    try:
        threading.Thread(target=_tarefa, daemon=True, name="sinal-sheets").start()
    except Exception:
        _sinal_lock.release()
        _logger.warning("Nao foi possivel iniciar o sinal de atividade.", exc_info=True)


def limpar_sinal_ao_sair(limite_s: float = 3.0) -> None:
    """Ao fechar o app / trocar de usuario: tira o sinal, esperando no maximo `limite_s` (nunca
    trava o fechamento por causa de rede lenta). Se nao der tempo, o sinal expira sozinho."""
    global _sinal_enviado
    if not config.SINCRONIZACAO_GOOGLE_ATIVADA or not _sinal_enviado:
        return
    _sinal_enviado = False

    def _tarefa() -> None:
        try:
            limpar_sinal()
        except Exception:
            _logger.warning("Nao foi possivel limpar o sinal de atividade ao sair.", exc_info=True)

    linha = threading.Thread(target=_tarefa, daemon=True, name="limpar-sinal-sheets")
    linha.start()
    linha.join(limite_s)
