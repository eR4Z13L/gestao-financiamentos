"""Sincronizar TUDO com o Google Sheets sob pedido (botão "Sincronizar agora", em
Administração > Sincronização e backup) - fora do fluxo normal, onde cada escrita já
sincroniza sozinha a PRÓPRIA aba (core/data_store.py). Fica num módulo separado só
para não criar um import circular: core.data_store já importa core.sheets_sync, e
este módulo precisa dos dois (reler tudo do disco E mandar pra nuvem).
"""

from __future__ import annotations

from pathlib import Path

from config import CAMINHO_XLSX
from core import data_store as bd
from core import sheets_sync


def sincronizar_tudo_agora(caminho_xlsx: Path | None = None) -> None:
    """Relê as 4 abas do disco agora mesmo e reenvia pro Google Sheets, mesmo que nada
    tenha mudado desde a última sincronização - útil depois de restaurar um backup
    (core/backup.py: Restaurar só mexe no arquivo local) ou pra forçar uma tentativa
    sem esperar a fila de repetição (core.sheets_sync.reenviar_pendentes)."""
    caminho_xlsx = caminho_xlsx or CAMINHO_XLSX
    sheets_sync.sincronizar_em_background(bd.ABA_CLIENTES, bd.ler_clientes(caminho_xlsx))
    sheets_sync.sincronizar_em_background(bd.ABA_EQUIPAMENTOS, bd.ler_equipamentos(caminho_xlsx))
    sheets_sync.sincronizar_em_background(bd.ABA_PROPOSTAS, bd.ler_propostas(caminho_xlsx))
    sheets_sync.sincronizar_em_background(bd.ABA_VENDEDORES, bd.ler_vendedores(caminho_xlsx))
