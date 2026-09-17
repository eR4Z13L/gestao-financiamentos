"""Regras de negocio para o cadastro de VENDEDORES.

Existe como cadastro proprio (nao so "nomes distintos usados em CLIENTES")
por dois motivos: 1) a lista precisa continuar existindo mesmo que nenhum
cliente esteja usando aquele nome no momento; 2) cadastrar por aqui evita
duplicar o mesmo vendedor com grafias diferentes (ex.: "Bruno" e "BRUNO"
virando duas pessoas por engano).
"""

from __future__ import annotations

import pandas as pd

from config import CAMINHO_XLSX
from core import data_store as bd


class ErroVendedor(Exception):
    """Erro de validacao de negocio (nao de leitura/escrita de arquivo)."""


def listar_vendedores() -> list[str]:
    df = bd.ler_vendedores(CAMINHO_XLSX)
    return sorted({nome for nome in df["NOME"].tolist() if nome}, key=str.upper)


def adicionar_vendedor(nome: str) -> str:
    """Cadastra um vendedor novo e devolve o nome ja normalizado (sem espaco
    nas pontas). Se ja existir um vendedor com o mesmo nome (ignorando
    maiusculas/minusculas e espacos), nao duplica - so devolve o nome que ja
    estava cadastrado."""
    nome = (nome or "").strip()
    if not nome:
        raise ErroVendedor("Nome do vendedor é obrigatório.")

    df = bd.ler_vendedores(CAMINHO_XLSX)
    existentes = {n.upper(): n for n in df["NOME"] if n}
    if nome.upper() in existentes:
        return existentes[nome.upper()]

    df = pd.concat([df, pd.DataFrame([{"NOME": nome}])], ignore_index=True)
    bd.escrever_vendedores(CAMINHO_XLSX, df)
    return nome
