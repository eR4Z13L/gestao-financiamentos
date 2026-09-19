"""Atualiza a formula da coluna TEMPO da aba PROPOSTAS no .xlsx pra regra atual
de "Encerrado" (Efetivado, Negado, Reprovado, Cancelado - Aprovado NAO encerra).

O app so reescreve essas formulas quando alguem grava uma proposta; numa
planilha gravada com a regra antiga (Aprovado = Encerrado), aberta direto no
Excel, a coluna TEMPO ainda mostraria a regra velha ate la. Este script corrige
SO essa coluna - nenhuma outra celula e tocada.

Por padrao SO SIMULA (diz quantas formulas mudariam). Pra aplicar de verdade,
passe --aplicar - isso faz um backup do arquivo antes:

    venv/Scripts/python.exe scripts/atualizar_formulas_tempo.py
    venv/Scripts/python.exe scripts/atualizar_formulas_tempo.py --aplicar
    venv/Scripts/python.exe scripts/atualizar_formulas_tempo.py --aplicar --sincronizar

--sincronizar tambem atualiza a aba PROPOSTAS no Google Sheets (la o TEMPO ja
vem calculado pelo app, entao muda quando a regra muda).
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl

from config import CAMINHO_XLSX
from core import data_store as bd


def _valores_fora_do_tempo(caminho: Path) -> list[tuple]:
    """Todas as celulas da planilha, EXCETO a coluna TEMPO da aba PROPOSTAS -
    o que tem que ficar identico antes e depois."""
    wb = openpyxl.load_workbook(caminho, data_only=False)
    try:
        resultado = []
        for ws in wb.worksheets:
            for linha in ws.iter_rows():
                for celula in linha:
                    if ws.title == bd.ABA_PROPOSTAS and celula.column == 9 and celula.row > 1:
                        continue
                    resultado.append((ws.title, celula.coordinate, celula.value))
        return resultado
    finally:
        wb.close()


def main() -> int:
    analisador = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    analisador.add_argument("--aplicar", action="store_true", help="grava de verdade (faz backup antes)")
    analisador.add_argument("--sincronizar", action="store_true", help="depois de gravar, atualiza o Google Sheets")
    analisador.add_argument("--arquivo", type=Path, default=CAMINHO_XLSX, help="planilha (padrão: a do app)")
    args = analisador.parse_args()
    arquivo: Path = args.arquivo

    try:
        if bd.arquivo_esta_bloqueado(arquivo):
            print(f"ERRO: '{arquivo.name}' está aberto no Excel. Feche-o e rode de novo.")
            return 1

        a_mudar = bd.atualizar_formulas_tempo(arquivo, gravar=False)
        print(f"Fórmulas de TEMPO desatualizadas: {a_mudar}")
        if not args.aplicar:
            print("SIMULAÇÃO - nada foi gravado. Rode com --aplicar para atualizar.")
            return 0
        if not a_mudar:
            print("Nada a fazer: as fórmulas já estão na regra atual.")
            return 0

        antes = _valores_fora_do_tempo(arquivo)
        backup = arquivo.with_name(f"{arquivo.stem}.backup-pre-formulas-tempo-{datetime.now():%Y%m%d-%H%M%S}{arquivo.suffix}")
        shutil.copy2(arquivo, backup)
        if hashlib.sha256(backup.read_bytes()).hexdigest() != hashlib.sha256(arquivo.read_bytes()).hexdigest():
            backup.unlink(missing_ok=True)
            print("ERRO: o backup não ficou idêntico ao original - nada foi alterado.")
            return 1

        alteradas = bd.atualizar_formulas_tempo(arquivo)
        # conferencia: so a coluna TEMPO pode ter mudado, e nada mais a atualizar
        if _valores_fora_do_tempo(arquivo) != antes or bd.atualizar_formulas_tempo(arquivo, gravar=False) != 0:
            print(f"ERRO: a conferência falhou. Restaure o backup: {backup}")
            return 1
        bd.ler_propostas(arquivo)  # o app tem que continuar lendo normalmente
        print(f"{alteradas} fórmula(s) de TEMPO atualizada(s). Todas as outras células idênticas ao original.")
        print(f"Backup do arquivo original: {backup}")

        if args.sincronizar:
            from core import sheets_sync

            sheets_sync._sincronizar_agora(bd.ABA_PROPOSTAS, bd.ler_propostas(arquivo))
            print("Aba PROPOSTAS sincronizada com o Google Sheets.")
    except bd.ErroArquivoBloqueado as exc:
        print(f"ERRO: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
