"""Regras de negocio para EQUIPAMENTOS."""

from __future__ import annotations

import pandas as pd

from config import CAMINHO_XLSX
from core import data_store as bd


class ErroEquipamento(Exception):
    pass


def listar_equipamentos() -> pd.DataFrame:
    df = bd.ler_equipamentos(CAMINHO_XLSX)
    return df.sort_values(["FORNECEDOR", "EQUIPAMENTO"], key=lambda s: s.str.upper()).reset_index(drop=True)


def listar_fornecedores() -> list[str]:
    df = bd.ler_equipamentos(CAMINHO_XLSX)
    return sorted({v for v in df["FORNECEDOR"].dropna().tolist() if str(v).strip()})


def listar_nomes_equipamento() -> list[str]:
    """Nomes distintos ja usados (na aba EQUIPAMENTOS e nas PROPOSTAS ja
    lancadas) para preencher a lista de sugestoes no formulario de proposta."""
    equipamentos = bd.ler_equipamentos(CAMINHO_XLSX)["EQUIPAMENTO"].dropna().tolist()
    propostas = bd.ler_propostas(CAMINHO_XLSX)["EQUIPAMENTO"].dropna().tolist()
    nomes = {str(v).strip() for v in equipamentos + propostas if str(v).strip()}
    return sorted(nomes)


def adicionar_equipamento(campos: dict) -> None:
    campos = dict(campos)
    nome = (campos.get("EQUIPAMENTO") or "").strip()
    if not nome:
        raise ErroEquipamento("Nome do equipamento é obrigatório.")
    campos["EQUIPAMENTO"] = nome
    campos["FORNECEDOR"] = (campos.get("FORNECEDOR") or "").strip()

    df = bd.ler_equipamentos(CAMINHO_XLSX)
    nova_linha = {col: campos.get(col, "") for col in bd.EQUIPAMENTOS_COLUNAS}
    df = pd.concat([df, pd.DataFrame([nova_linha])], ignore_index=True)
    bd.escrever_equipamentos(CAMINHO_XLSX, df)


def atualizar_equipamento(indice: int, campos: dict) -> None:
    """`indice` e a posicao na tabela retornada por listar_equipamentos()/
    bd.ler_equipamentos() no momento em que a edicao foi aberta."""
    df = bd.ler_equipamentos(CAMINHO_XLSX)
    if indice not in df.index:
        raise ErroEquipamento("Equipamento não encontrado (a lista pode ter mudado).")
    for col, valor in campos.items():
        if col in bd.EQUIPAMENTOS_COLUNAS:
            df.loc[indice, col] = valor
    bd.escrever_equipamentos(CAMINHO_XLSX, df)
