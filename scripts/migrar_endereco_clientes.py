"""Migra a aba CLIENTES do .xlsx pro formato atual (veja core/migracao_endereco.py):
- formato antigo (uma coluna "ENDEREÇO"): separa em CEP / LOGRADOURO / NÚMERO /
  COMPLEMENTO / BAIRRO / CIDADE / UF e acrescenta NOME DO PAI / NOME DA MÃE /
  PROFISSÃO;
- formato intermediário (sem COMPLEMENTO/UF): divide "Cidade/UF" em CIDADE e UF
  e tenta de novo os endereços que estavam em "ENDEREÇO (REVISAR)".

Por padrao SO SIMULA (mostra o que faria, sem gravar nada). Pra aplicar de
verdade, passe --aplicar - isso faz um backup do arquivo real antes.

    venv/Scripts/python.exe scripts/migrar_endereco_clientes.py            (simula)
    venv/Scripts/python.exe scripts/migrar_endereco_clientes.py --aplicar
    venv/Scripts/python.exe scripts/migrar_endereco_clientes.py --aplicar --sincronizar

--sincronizar tambem manda a aba CLIENTES nova pro Google Sheets (o app faria
isso sozinho na proxima gravacao; aqui so adianta, pra o modo vendedor ja
enxergar as colunas novas).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import CAMINHO_XLSX
from core import migracao_endereco as mig


def _imprimir_relatorio(relatorio: mig.Relatorio) -> None:
    print(f"\nFormato de origem: {relatorio.formato}")
    print(f"Clientes na aba: {relatorio.total_clientes}")
    print(f"  sem endereço:                          {relatorio.sem_endereco}")
    if relatorio.formato == mig.FORMATO_INTERMEDIARIO:
        print(f"  já com campos preenchidos (não tocados): {relatorio.ja_separados}")
        print(f"  Cidade/UF divididas em CIDADE + UF:      {relatorio.cidades_divididas}")
    print(f"  endereço separado com segurança agora: {len(relatorio.separados)}")
    print(f"  ENDEREÇO A REVISAR (não separado):     {len(relatorio.revisar)}")

    if relatorio.separados:
        print("\n--- Separados agora ---")
        for item in relatorio.separados:
            e = item.separado
            print(f"\nLinha {item.linha_planilha} - {item.cliente}")
            print(f"  original:    {item.original!r}")
            print(f"  CEP:         {e.cep!r}")
            print(f"  LOGRADOURO:  {e.logradouro!r}")
            print(f"  NÚMERO:      {e.numero!r}")
            print(f"  COMPLEMENTO: {e.complemento!r}")
            print(f"  BAIRRO:      {e.bairro!r}")
            print(f"  CIDADE:      {e.cidade!r}")
            print(f"  UF:          {e.uf!r}")

    if relatorio.cidades_sem_uf:
        print("\n--- Cidade preenchida sem '/UF' reconhecível (UF ficou em branco, cidade intacta) ---")
        for linha, cliente, cidade in relatorio.cidades_sem_uf:
            print(f"Linha {linha} - {cliente}: {cidade!r}")

    if relatorio.revisar:
        print("\n--- NÃO separados (revisar manualmente) ---")
        for item in relatorio.revisar:
            print(f"\nLinha {item.linha_planilha} - {item.cliente}")
            print(f"  original: {item.original!r}")
            print(f"  motivo:   {item.motivo}")


def main() -> int:
    analisador = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    analisador.add_argument("--aplicar", action="store_true", help="grava de verdade (faz backup antes)")
    analisador.add_argument("--sincronizar", action="store_true", help="depois de gravar, atualiza o Google Sheets")
    analisador.add_argument("--arquivo", type=Path, default=CAMINHO_XLSX, help="planilha a migrar (padrão: a do app)")
    args = analisador.parse_args()

    try:
        if not args.aplicar:
            _, relatorio = mig.planejar(args.arquivo)
            _imprimir_relatorio(relatorio)
            print("\nSIMULAÇÃO - nada foi gravado. Rode com --aplicar para migrar de verdade.")
            return 0

        relatorio = mig.migrar_planilha(args.arquivo, sincronizar=args.sincronizar)
    except (mig.ErroMigracao, mig.bd.ErroArquivoBloqueado) as exc:
        print(f"\nERRO: {exc}")
        return 1

    _imprimir_relatorio(relatorio)
    print(f"\nBackup do arquivo original: {relatorio.caminho_backup}")
    print("Migração concluída e conferida (todas as outras colunas e abas idênticas ao original).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
