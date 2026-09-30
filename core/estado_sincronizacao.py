"""Estado LOCAL da sincronizacao com a nuvem: qual versao da nuvem este computador conhece e
quais abas tem alteracoes ainda nao enviadas. Fica num JSON ao lado do arquivo de dados
(estado_sincronizacao.json) e so o codigo de sincronizacao escreve nele - nunca o .dat, que
o app grava por outro caminho (dois escritores no mesmo arquivo perderiam gravacoes).

Os dois campos sao o que impede perda de dados com dois computadores:
- revisao_conhecida: a versao da nuvem (aba META) na ultima vez que este PC enviou ou baixou.
  Se a nuvem estiver em outra versao, outro PC gravou nesse meio-tempo.
- abas_pendentes: gravadas aqui e ainda nao confirmadas na nuvem. Sobrevive a fechar o app,
  ao contrario da fila em memoria de core.sheets_sync - sem isso, "baixar da nuvem" poderia
  jogar fora alteracoes feitas sem internet.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from config import CAMINHO_XLSX  # os testes redirecionam (fixture_ficticia.apontar_modulos_para)

_logger = logging.getLogger(__name__)

NOME_DO_ARQUIVO = "estado_sincronizacao.json"

# reentrante: as funcoes que gravam leem o estado de dentro do mesmo cadeado. A LEITURA tambem
# passa por ele - no Windows, substituir o arquivo enquanto outra thread o le da "acesso negado".
_lock = threading.RLock()


@dataclass(frozen=True)
class EstadoLocal:
    revisao_conhecida: int | None = None  # None: nunca sincronizou (ou o arquivo de estado se perdeu)
    abas_pendentes: tuple[str, ...] = ()


def _arquivo(caminho_xlsx: Path | None) -> Path:
    return (caminho_xlsx or CAMINHO_XLSX).parent / NOME_DO_ARQUIVO


def ler(caminho_xlsx: Path | None = None) -> EstadoLocal:
    arquivo = _arquivo(caminho_xlsx)
    try:
        with _lock:
            texto = arquivo.read_text(encoding="utf-8")
    except FileNotFoundError:
        return EstadoLocal()
    except OSError:
        _logger.warning("Nao foi possivel ler o estado da sincronizacao (%s).", arquivo, exc_info=True)
        return EstadoLocal()
    try:
        dados = json.loads(texto)
        revisao = dados.get("revisao_conhecida")
        return EstadoLocal(
            revisao_conhecida=None if revisao is None else int(revisao),
            abas_pendentes=tuple(str(aba) for aba in dados.get("abas_pendentes", [])),
        )
    except (ValueError, TypeError, AttributeError):
        _logger.warning("Estado da sincronizacao ilegivel (%s) - tratado como 'nunca sincronizou'.", arquivo)
        return EstadoLocal()


def _gravar(estado: EstadoLocal, caminho_xlsx: Path | None) -> None:
    arquivo = _arquivo(caminho_xlsx)
    conteudo = json.dumps(
        {"revisao_conhecida": estado.revisao_conhecida, "abas_pendentes": list(estado.abas_pendentes)},
        ensure_ascii=False,
    )
    # temporario na mesma pasta + os.replace: nunca deixa um JSON pela metade se o app fechar no meio
    tmp_fd, tmp_nome = tempfile.mkstemp(suffix=".tmp", dir=str(arquivo.parent))
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as tmp:
            tmp.write(conteudo)
        for tentativa in range(6):
            try:
                os.replace(tmp_nome, arquivo)
                break
            except PermissionError:  # antivirus/indexador segurando o arquivo por um instante
                if tentativa == 5:
                    raise
                time.sleep(0.02 * (tentativa + 1))
    except BaseException:
        Path(tmp_nome).unlink(missing_ok=True)
        raise


def marcar_pendente(aba: str, caminho_xlsx: Path | None = None) -> None:
    with _lock:
        atual = ler(caminho_xlsx)
        if aba not in atual.abas_pendentes:
            _gravar(EstadoLocal(atual.revisao_conhecida, atual.abas_pendentes + (aba,)), caminho_xlsx)


def marcar_todas_pendentes(abas: list[str], caminho_xlsx: Path | None = None) -> None:
    with _lock:
        atual = ler(caminho_xlsx)
        faltam = tuple(a for a in abas if a not in atual.abas_pendentes)
        if faltam:
            _gravar(EstadoLocal(atual.revisao_conhecida, atual.abas_pendentes + faltam), caminho_xlsx)


def limpar_pendente(aba: str, caminho_xlsx: Path | None = None) -> None:
    with _lock:
        atual = ler(caminho_xlsx)
        if aba in atual.abas_pendentes:
            restantes = tuple(a for a in atual.abas_pendentes if a != aba)
            _gravar(EstadoLocal(atual.revisao_conhecida, restantes), caminho_xlsx)


def definir_revisao(revisao: int, caminho_xlsx: Path | None = None) -> None:
    """Depois de um envio bem-sucedido, ou de adotar a versao atual da nuvem antes de um envio forcado."""
    with _lock:
        atual = ler(caminho_xlsx)
        _gravar(EstadoLocal(revisao, atual.abas_pendentes), caminho_xlsx)


def registrar_download(revisao: int, caminho_xlsx: Path | None = None) -> None:
    """Depois de baixar tudo da nuvem: este PC passa a ter exatamente aquela versao, sem nada pendente."""
    with _lock:
        _gravar(EstadoLocal(revisao, ()), caminho_xlsx)
