"""Backup automático e manual do arquivo .xlsx que funciona como banco de dados.

Cada backup é uma CÓPIA do arquivo real, salva em data/backups/ com o nome
"controle_financiamentos.<motivo>-<AAAAMMDD-HHMMSS>.xlsx" - o motivo distingue
backups automáticos (rotina diária, ao abrir o app, limitados às
MAXIMO_BACKUPS_AUTOMATICOS cópias mais recentes) de manuais e de
pré-restauração (esses dois NUNCA são apagados sozinhos, só a própria pessoa,
direto na pasta). Ficam numa pasta PRÓPRIA (nunca direto em data/, junto dos
backups de migração antigos) para a limpeza automática nunca correr o risco
de apagar algo que não foi ela mesma quem criou.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from config import CAMINHO_XLSX
from core.data_store import ErroArquivoBloqueado, arquivo_esta_bloqueado

_logger = logging.getLogger(__name__)

MAXIMO_BACKUPS_AUTOMATICOS = 7

MOTIVO_AUTOMATICO = "auto"
MOTIVO_MANUAL = "manual"
MOTIVO_PRE_RESTAURACAO = "pre-restauracao"
MOTIVO_PRE_MESCLAGEM = "pre-mesclagem"  # antes de core.propostas.mesclar_bancos reescrever o historico

_FORMATO_TIMESTAMP = "%Y%m%d-%H%M%S"
# só reconhece arquivos que ESTE módulo gerou (motivo + timestamp no formato exato, com um
# "-N" opcional no final) - qualquer outro arquivo na pasta (colocado à mão, por exemplo) é
# ignorado pela listagem e nunca é candidato a apagar na limpeza automática. O sufixo "-N"
# existe pra desempatar dois backups feitos dentro do mesmo segundo (ver _destino_disponivel) -
# sem ele, o segundo simplesmente sobrescreveria o arquivo do primeiro, calado.
_PADRAO_NOME = re.compile(
    r"^.+\.(?P<motivo>auto|manual|pre-restauracao|pre-mesclagem)-(?P<quando>\d{8}-\d{6})(?:-\d+)?\.xlsx$"
)


@dataclass(frozen=True)
class Backup:
    caminho: Path
    motivo: str
    quando: datetime
    tamanho_bytes: int

    @property
    def eh_automatico(self) -> bool:
        return self.motivo == MOTIVO_AUTOMATICO


def _analisar_nome(nome_arquivo: str) -> tuple[str, datetime] | None:
    m = _PADRAO_NOME.match(nome_arquivo)
    if not m:
        return None
    try:
        quando = datetime.strptime(m.group("quando"), _FORMATO_TIMESTAMP)
    except ValueError:
        return None
    return m.group("motivo"), quando


def _pasta_backups(caminho_xlsx: Path) -> Path:
    # deriva da pasta do PROPRIO caminho_xlsx recebido (nunca de config.DIRETORIO_DADOS
    # fixo) - assim, quando um teste redireciona CAMINHO_XLSX pra uma pasta temporaria
    # (o mesmo padrao de scripts/fixture_ficticia.apontar_modulos_para), os backups
    # tambem vao pra dentro dela, nunca perto do arquivo real.
    return caminho_xlsx.parent / "backups"


def listar_backups(caminho_xlsx: Path | None = None) -> list[Backup]:
    """Todos os backups reconhecidos na pasta de backups de `caminho_xlsx`, do mais
    recente para o mais antigo."""
    caminho_xlsx = caminho_xlsx or CAMINHO_XLSX
    pasta = _pasta_backups(caminho_xlsx)
    if not pasta.exists():
        return []
    encontrados = []
    for arquivo in pasta.glob(f"{caminho_xlsx.stem}.*.xlsx"):
        analisado = _analisar_nome(arquivo.name)
        if analisado is None:
            continue
        motivo, quando = analisado
        encontrados.append(Backup(arquivo, motivo, quando, arquivo.stat().st_size))
    encontrados.sort(key=lambda b: b.quando, reverse=True)
    return encontrados


def _destino_disponivel(pasta: Path, base: str, motivo: str, quando: str) -> Path:
    """O nome "<base>.<motivo>-<quando>.xlsx" - ou, se dois backups caíram no mesmo segundo
    (dois cliques rápidos em "Fazer backup agora", ou o backup de segurança logo antes de uma
    restauração), "<base>.<motivo>-<quando>-2.xlsx", "-3"... nunca sobrescreve um backup que
    já existe."""
    candidato = pasta / f"{base}.{motivo}-{quando}.xlsx"
    contador = 2
    while candidato.exists():
        candidato = pasta / f"{base}.{motivo}-{quando}-{contador}.xlsx"
        contador += 1
    return candidato


def fazer_backup(motivo: str = MOTIVO_MANUAL, caminho_xlsx: Path | None = None) -> Path:
    """Copia o .xlsx real para a pasta de backups com o timestamp de agora. Não verifica
    se o arquivo está aberto no Excel - um backup é só uma FOTO do que está no disco
    agora, não precisa do mesmo cuidado (bloqueio/gravação atômica) de uma escrita."""
    caminho_xlsx = caminho_xlsx or CAMINHO_XLSX
    if not caminho_xlsx.exists():
        raise FileNotFoundError(f"Arquivo '{caminho_xlsx}' não existe - nada para fazer backup.")

    pasta = _pasta_backups(caminho_xlsx)
    pasta.mkdir(parents=True, exist_ok=True)
    quando = datetime.now().strftime(_FORMATO_TIMESTAMP)
    destino = _destino_disponivel(pasta, caminho_xlsx.stem, motivo, quando)
    shutil.copy2(caminho_xlsx, destino)
    return destino


def limpar_backups_automaticos(caminho_xlsx: Path | None = None) -> int:
    """Apaga os backups automáticos mais antigos, mantendo só os MAXIMO_BACKUPS_AUTOMATICOS
    mais recentes. NUNCA mexe em backups manuais ou de pré-restauração - esses só a
    própria pessoa apaga, direto na pasta. Devolve quantos arquivos foram apagados."""
    automaticos = [b for b in listar_backups(caminho_xlsx) if b.eh_automatico]
    excedentes = automaticos[MAXIMO_BACKUPS_AUTOMATICOS:]
    for backup in excedentes:
        backup.caminho.unlink(missing_ok=True)
    return len(excedentes)


def backup_diario_se_necessario(caminho_xlsx: Path | None = None) -> Path | None:
    """Faz o backup automático do dia SE ainda não tiver um de hoje - chamado 1x por
    execução, na abertura do app. Devolve o caminho do backup novo, ou None se já
    tinha um de hoje (não faz nada nesse caso)."""
    caminho_xlsx = caminho_xlsx or CAMINHO_XLSX
    hoje = datetime.now().date()
    ja_tem_hoje = any(b.eh_automatico and b.quando.date() == hoje for b in listar_backups(caminho_xlsx))
    if ja_tem_hoje:
        return None
    novo = fazer_backup(MOTIVO_AUTOMATICO, caminho_xlsx)
    limpar_backups_automaticos(caminho_xlsx)
    return novo


def restaurar_backup(backup: Path, caminho_xlsx: Path | None = None) -> Path:
    """Restaura `backup` por cima do .xlsx real - mas ANTES disso, sempre faz um
    backup do estado atual (motivo pré-restauração), para a restauração também poder
    ser desfeita. Recusa se o arquivo real estiver aberto no Excel (mesma regra de
    qualquer escrita - core.data_store.ErroArquivoBloqueado). Devolve o caminho do
    backup de segurança criado."""
    caminho_xlsx = caminho_xlsx or CAMINHO_XLSX
    if not backup.exists():
        raise FileNotFoundError(f"Backup '{backup}' não existe mais.")
    if arquivo_esta_bloqueado(caminho_xlsx):
        raise ErroArquivoBloqueado(
            f"O arquivo '{caminho_xlsx.name}' está aberto no Excel. Feche-o e tente restaurar novamente."
        )

    seguranca = fazer_backup(MOTIVO_PRE_RESTAURACAO, caminho_xlsx)

    tmp_fd, tmp_nome = tempfile.mkstemp(suffix=".xlsx", dir=str(caminho_xlsx.parent))
    os.close(tmp_fd)
    caminho_temporario = Path(tmp_nome)
    try:
        shutil.copy2(backup, caminho_temporario)
        os.replace(caminho_temporario, caminho_xlsx)
    except PermissionError as exc:
        caminho_temporario.unlink(missing_ok=True)
        raise ErroArquivoBloqueado(
            f"Não foi possível restaurar '{caminho_xlsx.name}'. "
            "Verifique se ele não está aberto no Excel e tente novamente."
        ) from exc
    return seguranca
