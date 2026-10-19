"""Converte os dados antigos para o jeito novo (veja core/migracao_legado.py): junta as propostas sem venda em
vendas e troca os status antigos pelos novos. Roda SO sobre uma COPIA dos dados, passada de forma explicita: sem o
caminho do arquivo o script nao roda, e ele recusa o arquivo do app e QUALQUER lugar dentro da pasta do projeto (o
arquivo e a pasta --saida: o repositorio e publico, os relatorios tem nomes de clientes). Nao acessa o Google.

    venv/Scripts/python.exe scripts/converter_legado.py <arquivo.dat> [--decisoes decisoes.json] [--saida pasta] [--aplicar]

Sem --aplicar so SIMULA: escreve relatorio_conversao.md (contagens antes e depois) e duvidas_conversao.json (o que
precisa de resposta) em --saida (padrao: a pasta do arquivo) e nao mexe no arquivo. Com --aplicar recusa se faltar
decisao para alguma duvida, faz backup, grava numa gravacao so e confere o resultado (se nao bater, restaura o backup).
decisoes.json: {"D1": "juntar", "S3": "Aprovado", ...} - a chave e a de duvidas_conversao.json.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # antes de qualquer outra coisa: o conversor nunca fala com o Google

from core import data_store as bd
from core import migracao_legado as legado


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    analisador.add_argument("arquivo", type=Path, help="a COPIA do arquivo de dados (.dat) a converter (obrigatorio)")
    analisador.add_argument("--decisoes", type=Path, help="JSON com a resposta de cada duvida")
    analisador.add_argument("--saida", type=Path, help="pasta dos relatorios (padrao: a pasta do arquivo)")
    analisador.add_argument("--aplicar", action="store_true", help="converte de verdade (backup antes; padrao: so simula)")
    args = analisador.parse_args(argv)

    try:
        if args.saida:
            legado.exigir_saida_permitida(args.saida)  # antes de ler qualquer coisa
        decisoes = legado.carregar_decisoes(args.decisoes) if args.decisoes else {}
        plano = legado.planejar(args.arquivo)
        pasta = args.saida or plano.caminho.parent
        depois = legado.simular(plano, decisoes)
        relatorio, duvidas = legado.escrever_relatorios(plano, pasta, depois)
        print(f"Arquivo: {plano.caminho}")
        print(f"Propostas: {plano.antes['propostas']} | vendas: {plano.antes['vendas']} -> {depois['vendas']} | "
              f"propostas que mudam de status: {plano.conversoes} | dúvidas: {len(plano.duvidas)} | problemas: {len(plano.problemas)}")
        print(f"Relatório: {relatorio}\nDúvidas:   {duvidas}")
        if not args.aplicar:
            print("\nSIMULAÇÃO - nada foi gravado. Rode com --aplicar (e --decisoes, se houver dúvidas) para converter.")
            return 0
        resumo = legado.aplicar(plano, decisoes)
        legado.escrever_relatorios(plano, pasta, resumo["depois"], resumo)
    except (legado.ErroConversao, bd.ErroArquivoBloqueado) as exc:
        print(f"\nERRO: {exc}", file=sys.stderr)
        return 1

    print(f"\nConvertido e conferido. Backup: {resumo['backup']}")
    print(f"{resumo['conversoes']} proposta(s) com status trocado, {resumo['vendas_novas']} venda(s) nova(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
