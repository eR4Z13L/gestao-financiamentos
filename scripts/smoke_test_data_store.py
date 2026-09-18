"""Valida a camada core/data_store.py:
1. Le as 3 abas do arquivo real (so leitura, nao mexe em nada).
2. Faz um teste de escrita/round-trip numa COPIA temporaria (nunca no arquivo real).
3. Simula o arquivo aberto no Excel (cria o lock file ~$...) e confere que a
   escrita falha do jeito certo (ErroArquivoBloqueado), sem travar nem corromper nada.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_data_store.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import CAMINHO_XLSX

import config
config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
from core import data_store as bd


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def testar_leitura_real() -> None:
    linha("1) LEITURA DO ARQUIVO REAL (data/controle_financiamentos.xlsx)")

    clientes = bd.ler_clientes(CAMINHO_XLSX)
    equipamentos = bd.ler_equipamentos(CAMINHO_XLSX)
    propostas = bd.ler_propostas(CAMINHO_XLSX, df_clientes=clientes)

    print(f"CLIENTES: {len(clientes)} linhas")
    print(f"EQUIPAMENTOS: {len(equipamentos)} linhas")
    print(f"PROPOSTAS: {len(propostas)} linhas")

    assert len(clientes) > 0, "esperava encontrar clientes"
    assert len(equipamentos) > 0, "esperava encontrar equipamentos"
    assert len(propostas) > 0, "esperava encontrar propostas"

    print("\nExemplo de proposta com VENDEDOR/CLIENTE/TEMPO recalculados:")
    exemplo = propostas.iloc[0]
    print(exemplo[["DATA", "CPF", "VENDEDOR", "CLIENTE", "STATUS", "TEMPO"]].to_dict())

    abertas = propostas[~propostas["STATUS"].str.upper().isin(bd.STATUS_ENCERRADO)]
    encerradas = propostas[propostas["STATUS"].str.upper().isin(bd.STATUS_ENCERRADO)]
    if len(abertas):
        assert abertas.iloc[0]["TEMPO"].endswith("dias"), "TEMPO de proposta aberta deveria ser 'N dias'"
    if len(encerradas):
        assert encerradas.iloc[0]["TEMPO"] == "Encerrado"

    assert (propostas["VENDEDOR"] != "").any(), "VLOOKUP por CPF nao encontrou nenhum vendedor"

    print("\nOK: leitura das 3 abas e calculo de VENDEDOR/CLIENTE/TEMPO batem com o esperado.")


def testar_escrita_em_copia() -> Path:
    linha("2) ESCRITA (round-trip) EM UMA COPIA TEMPORARIA")

    tmp_path = CAMINHO_XLSX.parent / "_smoke_test_copy.xlsx"
    shutil.copy(CAMINHO_XLSX, tmp_path)

    clientes_antes = bd.ler_clientes(tmp_path)
    propostas_antes = bd.ler_propostas(tmp_path, df_clientes=clientes_antes)
    n_antes = len(propostas_antes)

    novo_cpf = clientes_antes.iloc[0]["CPF/CNPJ"]
    nova_linha = {
        "DATA": propostas_antes.iloc[0]["DATA"],
        "CPF": novo_cpf,
        "VALOR (R$)": 12345.67,
        "MESES": 24,
        "EQUIPAMENTO": "TESTE SMOKE",
        "BANCO": "TESTE",
        "STATUS": "Em Análise",
        "OBSERVAÇÕES": "linha criada pelo smoke test",
    }
    editaveis = propostas_antes[bd.PROPOSTAS_COLUNAS_EDITAVEIS].to_dict("records")
    editaveis.append(nova_linha)
    bd.escrever_propostas(tmp_path, __import__("pandas").DataFrame(editaveis))

    propostas_depois = bd.ler_propostas(tmp_path, df_clientes=clientes_antes)
    print(f"PROPOSTAS antes: {n_antes} | depois de adicionar 1 linha: {len(propostas_depois)}")
    assert len(propostas_depois) == n_antes + 1

    linha_nova = propostas_depois.iloc[-1]
    print("Linha nova (recalculada apos escrita):")
    print(linha_nova[["CPF", "VENDEDOR", "CLIENTE", "STATUS", "TEMPO"]].to_dict())
    assert linha_nova["VENDEDOR"] == clientes_antes.iloc[0]["VENDEDOR"], "VENDEDOR deveria vir do CPF"
    assert linha_nova["TEMPO"].endswith("dias")

    print("\nOK: escrita + releitura batem (fórmulas de VENDEDOR/CLIENTE/TEMPO regravadas corretamente).")
    return tmp_path


def testar_deteccao_de_bloqueio(tmp_path: Path) -> None:
    linha("3) DETECCAO DE ARQUIVO ABERTO NO EXCEL (lock file)")

    caminho_bloqueio = tmp_path.with_name(f"~${tmp_path.name}")
    caminho_bloqueio.write_text("simulando o Excel com o arquivo aberto")
    try:
        assert bd.arquivo_esta_bloqueado(tmp_path) is True
        df = bd.ler_propostas(tmp_path)[bd.PROPOSTAS_COLUNAS_EDITAVEIS]
        try:
            bd.escrever_propostas(tmp_path, df)
        except bd.ErroArquivoBloqueado as exc:
            print(f"OK: escrita bloqueada como esperado -> {exc}")
        else:
            raise AssertionError("deveria ter levantado ErroArquivoBloqueado com o lock file presente")
    finally:
        caminho_bloqueio.unlink(missing_ok=True)


def main() -> None:
    testar_leitura_real()
    tmp_path = testar_escrita_em_copia()
    try:
        testar_deteccao_de_bloqueio(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)
    linha("TUDO OK")


if __name__ == "__main__":
    main()
