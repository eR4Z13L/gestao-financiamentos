"""Sincronizar com a nuvem alem do envio automatico de cada gravacao (core/data_store.py):

- sincronizar_tudo_agora: reenvia todas as abas sob pedido (botao "Sincronizar agora");
- verificar_ao_abrir: ao abrir o app como Administrador, compara este computador com a nuvem
  (versao, o que ficou pendente, quem mais esta com o app aberto) e diz o que fazer;
- baixar_da_nuvem: troca os dados LOCAIS pelos da nuvem (backup antes, tudo-ou-nada);
- enviar_para_a_nuvem_substituindo: manda o que esta aqui POR CIMA da nuvem, de proposito (guarda
  antes uma copia do que a nuvem tinha).

Fica num modulo separado so para nao criar um import circular: core.data_store ja importa
core.sheets_sync, e aqui precisamos dos dois (reler do disco E falar com a nuvem).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import gspread
import pandas as pd

import config
from config import CAMINHO_XLSX
from core import backup as backup_mod
from core import conta_google
from core import data_store as bd
from core import data_store_sheets as nuvem
from core import estado_sincronizacao as estado_mod
from core import sheets_sync

_logger = logging.getLogger(__name__)

SITUACAO_DESATIVADA = "desativada"
SITUACAO_SEM_REDE = "sem_rede"  # nao deu pra falar com a nuvem agora: o app abre normal, offline
SITUACAO_SEM_CONTROLE = "sem_controle"  # a nuvem ainda nao tem controle de versao (aba META)
SITUACAO_EM_DIA = "em_dia"
SITUACAO_LOCAL_PENDENTE = "local_pendente"  # a nuvem e a que conheco, mas tenho abas nao enviadas
SITUACAO_NUVEM_MAIS_NOVA = "nuvem_mais_nova"  # outro PC enviou e eu nao tenho nada pendente: da pra baixar
SITUACAO_CONFLITO = "conflito"  # outro PC enviou E eu tenho abas nao enviadas: alguem tem que decidir

_LEITORES_LOCAIS = {
    bd.ABA_CLIENTES: bd.ler_clientes,
    bd.ABA_EQUIPAMENTOS: bd.ler_equipamentos,
    bd.ABA_PROPOSTAS: bd.ler_propostas,
    bd.ABA_VENDEDORES: bd.ler_vendedores,
    bd.ABA_BANCOS: bd.ler_bancos,
    bd.ABA_VENDAS: bd.ler_vendas,
    bd.ABA_HISTORICO: bd.ler_historico,
}
# abas que uma nuvem de antes delas existirem nao tem: a falta delas nao e erro, e a aba daqui fica como esta.
# Pelo NOME da funcao (lida na hora): guardar a funcao em si congelaria a de agora.
_ABAS_OPCIONAIS_NA_NUVEM = {bd.ABA_BANCOS: "ler_bancos", bd.ABA_VENDAS: "ler_vendas", bd.ABA_HISTORICO: "ler_historico"}


class ErroNuvem(Exception):
    """Algo impediu a operacao com a nuvem; a mensagem diz o que e que nada foi alterado."""


@dataclass(frozen=True)
class SituacaoAoAbrir:
    tipo: str
    meta: sheets_sync.MetaNuvem | None = None
    detalhe: str = ""
    outro_computador: str = ""  # nome do outro PC ativo agora ("" = nenhum)
    outro_desde: datetime | None = None  # o ultimo sinal dele, em horario local


@dataclass(frozen=True)
class ResultadoDoDownload:
    backup: Path | None  # None: nao havia arquivo local para guardar (primeira abertura)
    meta: sheets_sync.MetaNuvem
    linhas: dict[str, int]  # aba -> quantas linhas vieram da nuvem
    ligou_controle: bool = False  # a nuvem nao tinha controle de versao e passou a ter agora


NUVEM_DESATIVADA = "desativada"
NUVEM_SEM_CHAVE = "sem_chave"  # falta o arquivo da chave do Google neste computador
NUVEM_SEM_REDE = "sem_rede"
NUVEM_VAZIA = "vazia"  # a nuvem responde, mas nao tem dado nenhum
NUVEM_COM_DADOS = "com_dados"


@dataclass(frozen=True)
class NuvemParaPrimeiraAbertura:
    tipo: str
    linhas: dict[str, int] | None = None  # aba -> linhas na nuvem (so quando a nuvem respondeu)
    detalhe: str = ""


def sincronizar_tudo_agora(caminho_xlsx: Path | None = None) -> None:
    """Relê as abas do disco agora mesmo e reenvia pro Google Sheets, mesmo que nada
    tenha mudado desde a última sincronização - útil depois de restaurar um backup
    (core/backup.py: Restaurar só mexe no arquivo local) ou pra forçar uma tentativa
    sem esperar a fila de repetição (core.sheets_sync.reenviar_pendentes)."""
    caminho_xlsx = caminho_xlsx or CAMINHO_XLSX
    sheets_sync.sincronizar_em_background(bd.ABA_CLIENTES, bd.ler_clientes(caminho_xlsx))
    sheets_sync.sincronizar_em_background(bd.ABA_EQUIPAMENTOS, bd.ler_equipamentos(caminho_xlsx))
    sheets_sync.sincronizar_em_background(bd.ABA_PROPOSTAS, bd.ler_propostas(caminho_xlsx))
    sheets_sync.sincronizar_em_background(bd.ABA_VENDEDORES, bd.ler_vendedores(caminho_xlsx))
    sheets_sync.sincronizar_em_background(bd.ABA_BANCOS, bd.ler_bancos(caminho_xlsx))
    sheets_sync.sincronizar_em_background(bd.ABA_VENDAS, bd.ler_vendas(caminho_xlsx))
    sheets_sync.sincronizar_em_background(bd.ABA_HISTORICO, bd.ler_historico(caminho_xlsx))


def enviar_pendentes_do_estado(caminho_xlsx: Path | None = None) -> list[str]:
    """Reenvia so as abas que o estado em disco marca como nao enviadas (sobrevive a fechar o app,
    ao contrario da fila em memoria). Devolve os nomes das abas disparadas."""
    caminho_xlsx = caminho_xlsx or CAMINHO_XLSX
    disparadas = []
    for aba in estado_mod.ler(caminho_xlsx).abas_pendentes:
        leitor = _LEITORES_LOCAIS.get(aba)
        if leitor is not None:
            sheets_sync.sincronizar_em_background(aba, leitor(caminho_xlsx))
            disparadas.append(aba)
    return disparadas


def verificar_ao_abrir(caminho_xlsx: Path | None = None) -> SituacaoAoAbrir:
    """Compara este computador com a nuvem (UMA leitura da aba META - rede!): chamar numa thread,
    nunca na da tela. Nunca levanta: sem rede, o app abre normal e devolve SEM_REDE."""
    if not config.SINCRONIZACAO_GOOGLE_ATIVADA:
        return SituacaoAoAbrir(SITUACAO_DESATIVADA)
    try:
        meta = sheets_sync.ler_meta_da_nuvem()
    except Exception as exc:
        _logger.warning("Nao foi possivel consultar a nuvem ao abrir.", exc_info=True)
        return SituacaoAoAbrir(SITUACAO_SEM_REDE, detalhe=f"{type(exc).__name__}: {exc}"[:300])

    local = estado_mod.ler(caminho_xlsx)
    outro = sheets_sync.outro_computador_ativo(meta)
    nome_outro = outro[0] if outro else ""
    desde_outro = outro[1].astimezone().replace(tzinfo=None) if outro else None

    if not meta.com_controle:
        tipo = SITUACAO_SEM_CONTROLE
    elif local.revisao_conhecida == meta.revisao:
        tipo = SITUACAO_LOCAL_PENDENTE if local.abas_pendentes else SITUACAO_EM_DIA
    else:
        tipo = SITUACAO_CONFLITO if local.abas_pendentes else SITUACAO_NUVEM_MAIS_NOVA
    return SituacaoAoAbrir(tipo, meta, outro_computador=nome_outro, outro_desde=desde_outro)


def _ler_dados_da_nuvem() -> dict[str, pd.DataFrame]:
    """As abas da nuvem, ja com os tipos do app. Tudo ou nada: se uma aba falhar, levanta. BANCOS e a
    excecao: uma nuvem de antes do cadastro de bancos nao tem essa aba, e ela so fica de fora."""
    try:
        dados = {
            bd.ABA_CLIENTES: nuvem.ler_clientes(),
            bd.ABA_EQUIPAMENTOS: nuvem.ler_equipamentos(),
            bd.ABA_VENDEDORES: nuvem.ler_vendedores(),
            bd.ABA_PROPOSTAS: nuvem.ler_propostas(),
        }
    except gspread.WorksheetNotFound as exc:
        raise ErroNuvem(f"A nuvem não tem a aba {exc}. Nada foi alterado.") from exc
    for aba, nome_do_leitor in _ABAS_OPCIONAIS_NA_NUVEM.items():
        try:
            dados[aba] = getattr(nuvem, nome_do_leitor)()
        except gspread.WorksheetNotFound:
            pass
    return dados


def _gravar_dados_no_arquivo(caminho: Path, dados: dict[str, pd.DataFrame]) -> None:
    bd.escrever_tudo(
        caminho,
        dados[bd.ABA_CLIENTES],
        dados[bd.ABA_EQUIPAMENTOS],
        dados[bd.ABA_VENDEDORES],
        dados[bd.ABA_PROPOSTAS],
        dados.get(bd.ABA_BANCOS),
        dados.get(bd.ABA_VENDAS),
        dados.get(bd.ABA_HISTORICO),
    )


def _recusar_se_a_nuvem_parece_vazia_por_engano(dados: dict[str, pd.DataFrame], caminho: Path) -> None:
    """Um envio que caiu no meio pode deixar uma aba da nuvem VAZIA (ela e apagada e reescrita).
    Baixar isso apagaria os dados daqui, entao uma aba vazia na nuvem com linhas aqui e recusada."""
    for aba, leitor in _LEITORES_LOCAIS.items():
        if aba not in dados:  # aba opcional que a nuvem ainda nao tem: a daqui fica como esta
            continue
        aqui = len(leitor(caminho))
        if len(dados[aba]) == 0 and aqui > 0:
            raise ErroNuvem(
                f"A aba {aba} está vazia na nuvem, mas aqui tem {aqui} linha(s). Isso parece um envio "
                "interrompido - por segurança não vou apagar os dados deste computador. Nada foi alterado. "
                "Use \"Sincronizar agora\" no computador que tem os dados certos."
            )


def baixar_da_nuvem(caminho_xlsx: Path | None = None, *, ligar_controle: bool = False) -> ResultadoDoDownload:
    """Troca os dados LOCAIS pelos da nuvem. Faz backup do arquivo atual antes; e tudo-ou-nada (as 4
    abas numa unica gravacao) e nao manda nada de volta pra nuvem. Alteracoes daqui que ainda nao
    tinham sido enviadas sao substituidas (por isso o backup). Sem arquivo local (primeira abertura),
    cria o arquivo com o que veio da nuvem - nao ha o que guardar em backup. Rede!

    Uma nuvem SEM controle de versao (ninguem com esta versao do app enviou ainda) so e aceita com
    `ligar_controle=True`: depois de baixar, cria a aba META (sem reenviar dados) e este PC passa a
    conhecer essa versao - os envios seguintes ja passam pela trava.

    Levanta ErroNuvem (nada foi alterado) se a nuvem nao tem controle e `ligar_controle` e False, se
    ela mudou durante o download ou parece incompleta, e ErroArquivoBloqueado se o Excel esta com o
    arquivo aberto."""
    caminho = caminho_xlsx or CAMINHO_XLSX
    if not config.SINCRONIZACAO_GOOGLE_ATIVADA:
        raise ErroNuvem("A sincronização com o Google Sheets está desativada neste aplicativo.")
    existia = caminho.exists()
    if existia and bd.arquivo_esta_bloqueado(caminho):
        raise bd.ErroArquivoBloqueado(
            f"O arquivo '{caminho.name}' está aberto no Excel. Feche-o e baixe da nuvem de novo."
        )

    with sheets_sync.bloqueio_de_envio():  # nenhum envio deste PC no meio da troca
        meta_antes = sheets_sync.ler_meta_da_nuvem()
        if not meta_antes.com_controle and not ligar_controle:
            raise ErroNuvem(
                "A nuvem ainda não recebeu dados com controle de versão (nenhum computador enviou). "
                "Envie primeiro, no computador que tem os dados certos. Nada foi alterado."
            )
        dados = _ler_dados_da_nuvem()
        meta_depois = sheets_sync.ler_meta_da_nuvem()
        # sem controle a revisao e 0; se outro PC ligar o controle no meio, ela vira 1 e cai aqui tambem
        if meta_depois.revisao != meta_antes.revisao:
            raise ErroNuvem("A nuvem foi atualizada enquanto baixava. Nada foi alterado - tente de novo.")

        seguranca: Path | None = None
        if existia:
            _recusar_se_a_nuvem_parece_vazia_por_engano(dados, caminho)
            seguranca = backup_mod.fazer_backup(backup_mod.MOTIVO_PRE_NUVEM, caminho)
        else:
            bd.criar_planilha_vazia(caminho)
        try:
            _gravar_dados_no_arquivo(caminho, dados)
        except Exception:
            if not existia:  # nao deixa uma planilha vazia "de verdade" no lugar da que nao chegou
                caminho.unlink(missing_ok=True)
            raise
        sheets_sync.descartar_envios_velhos()

        meta_final = meta_antes
        if not meta_antes.com_controle:
            try:
                meta_final = sheets_sync.ligar_controle_de_versao()
            except Exception as exc:
                onde = f" O arquivo de antes está em:\n{seguranca}" if seguranca else ""
                raise ErroNuvem(
                    "Os dados da nuvem foram baixados para este computador, mas não consegui ligar o controle "
                    f"de versão na nuvem ({type(exc).__name__}: {exc}). Abra o aplicativo de novo para tentar "
                    f"outra vez.{onde}"
                ) from exc
        estado_mod.registrar_download(meta_final.revisao, caminho)
    sheets_sync.limpar_conflito()
    return ResultadoDoDownload(
        seguranca, meta_final, {aba: len(df) for aba, df in dados.items()}, ligou_controle=not meta_antes.com_controle
    )


def consultar_nuvem_para_primeira_abertura() -> NuvemParaPrimeiraAbertura:
    """Sem planilha neste computador: a nuvem tem dados para baixar? Le as 4 abas (rede! chamar numa
    thread). Nunca levanta: qualquer falha vira NUVEM_SEM_REDE com o motivo em `detalhe`."""
    if not config.SINCRONIZACAO_GOOGLE_ATIVADA:
        return NuvemParaPrimeiraAbertura(NUVEM_DESATIVADA)
    if not conta_google.ha_acesso_a_nuvem():  # nem conta Google conectada, nem a chave
        return NuvemParaPrimeiraAbertura(NUVEM_SEM_CHAVE)
    leitores = {
        bd.ABA_CLIENTES: nuvem.ler_clientes,
        bd.ABA_EQUIPAMENTOS: nuvem.ler_equipamentos,
        bd.ABA_VENDEDORES: nuvem.ler_vendedores,
        bd.ABA_PROPOSTAS: nuvem.ler_propostas,
    }
    linhas: dict[str, int] = {}
    try:
        for aba, leitor in leitores.items():
            try:
                linhas[aba] = len(leitor())
            except gspread.WorksheetNotFound:
                linhas[aba] = 0
    except Exception as exc:
        _logger.warning("Nao foi possivel consultar a nuvem na primeira abertura.", exc_info=True)
        return NuvemParaPrimeiraAbertura(NUVEM_SEM_REDE, detalhe=f"{type(exc).__name__}: {exc}"[:300])
    tipo = NUVEM_COM_DADOS if any(linhas.values()) else NUVEM_VAZIA
    return NuvemParaPrimeiraAbertura(tipo, linhas)


def salvar_copia_da_nuvem(caminho_xlsx: Path | None = None) -> Path:
    """Guarda em backups/ um arquivo com o que a nuvem tem AGORA (o arquivo local, com as abas
    trocadas pelas da nuvem). Serve pra nao perder o que a nuvem tinha quando o envio a sobrescreve.
    Nao mexe no arquivo de dados nem na nuvem. Rede!"""
    caminho = caminho_xlsx or CAMINHO_XLSX
    dados = _ler_dados_da_nuvem()
    copia = backup_mod.fazer_backup(backup_mod.MOTIVO_COPIA_DA_NUVEM, caminho)
    _gravar_dados_no_arquivo(copia, dados)
    return copia


def enviar_para_a_nuvem_substituindo(caminho_xlsx: Path | None = None, *, copia_obrigatoria: bool = True) -> Path | None:
    """Manda os dados DESTE computador por cima da nuvem, de proposito: primeiro guarda uma copia do
    que a nuvem tem (se `copia_obrigatoria` e a copia falhar, aborta sem enviar nada), depois adota a
    versao atual da nuvem (preparar_envio_forcado) e dispara o envio de todas as abas. Devolve o caminho da
    copia (None se nao houve). Rede!"""
    caminho = caminho_xlsx or CAMINHO_XLSX
    if not config.SINCRONIZACAO_GOOGLE_ATIVADA:
        raise ErroNuvem("A sincronização com o Google Sheets está desativada neste aplicativo.")
    copia: Path | None = None
    try:
        copia = salvar_copia_da_nuvem(caminho)
    except Exception as exc:
        if copia_obrigatoria:
            raise ErroNuvem(
                "Não consegui guardar uma cópia do que está na nuvem antes de sobrescrevê-la "
                f"({exc}). Nada foi enviado."
            ) from exc
        _logger.info("Sem copia da nuvem antes do envio (a nuvem pode estar vazia): %s", exc)
    sheets_sync.preparar_envio_forcado()
    sincronizar_tudo_agora(caminho)
    return copia
