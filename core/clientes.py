"""Regras de negocio para CLIENTES: busca, cadastro, edicao e remocao.

Esta camada nao sabe nada sobre .xlsx - so conversa com core/data_store.py
usando DataFrames. As telas (desktop/screens/*.py) so conversam com esta
camada, nunca direto com data_store - assim, se o banco mudar no futuro, so
data_store.py precisa mudar.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from config import CAMINHO_XLSX
from core import data_store as bd
from core.validators import apenas_digitos, cpf_cnpj_valido, email_valido

TIPO_OPCOES = ["Cliente", "Avalista"]


class ErroCliente(Exception):
    """Erro de validacao de negocio (nao de leitura/escrita de arquivo)."""


def listar_clientes() -> pd.DataFrame:
    df = bd.ler_clientes(CAMINHO_XLSX)
    return df.sort_values("CLIENTE", key=lambda s: s.str.upper()).reset_index(drop=True)


def buscar_por_cpf(cpf: str) -> dict | None:
    df = bd.ler_clientes(CAMINHO_XLSX)
    alvo = apenas_digitos(cpf)
    encontrado = df[df["CPF/CNPJ"].map(apenas_digitos) == alvo]
    if encontrado.empty:
        return None
    return encontrado.iloc[0].to_dict()


def buscar(termo: str) -> pd.DataFrame:
    """Busca por nome (substring, sem diferenciar maiusculas) ou por CPF/CNPJ."""
    df = listar_clientes()
    termo = (termo or "").strip()
    if not termo:
        return df
    digitos = apenas_digitos(termo)
    por_cpf = (
        df["CPF/CNPJ"].map(apenas_digitos).str.contains(digitos, na=False)
        if digitos
        else pd.Series(False, index=df.index)
    )
    por_nome = df["CLIENTE"].str.upper().str.contains(termo.upper(), na=False)
    return df[por_nome | por_cpf]


def _validar_campos(campos: dict, cpf_original: str | None = None) -> None:
    cpf = (campos.get("CPF/CNPJ") or "").strip()
    nome = (campos.get("CLIENTE") or "").strip()
    tipo = (campos.get("TIPO") or "").strip()

    if not cpf:
        raise ErroCliente("CPF/CNPJ é obrigatório.")

    cpf_mudou = cpf_original is None or apenas_digitos(cpf) != apenas_digitos(cpf_original)
    # so revalida o digito verificador se o CPF de fato mudou - varios
    # clientes reais tem CPF invalido (dado legado, digitado errado antes de
    # existir validacao) e nao podem ficar impedidos de editar QUALQUER outro
    # campo (nome, telefone, etc.) so por causa de um CPF que ja estava assim.
    if cpf_mudou and not cpf_cnpj_valido(cpf):
        raise ErroCliente("CPF/CNPJ inválido - confira os números digitados.")

    if not nome:
        raise ErroCliente("Nome do cliente é obrigatório.")
    if tipo not in TIPO_OPCOES:
        raise ErroCliente(f"Tipo deve ser um de: {', '.join(TIPO_OPCOES)}.")

    email = (campos.get("EMAIL") or "").strip()
    if email and not email_valido(email):
        raise ErroCliente("E-mail inválido - confira o endereço digitado.")

    existente = buscar_por_cpf(cpf)
    if cpf_mudou and existente is not None:
        raise ErroCliente(f"Já existe um cliente cadastrado com o CPF/CNPJ {cpf}.")


def adicionar_cliente(campos: dict) -> None:
    """`campos` deve ter as chaves de data_store.CLIENTES_COLUNAS (DATA CADASTRO
    e preenchida automaticamente com hoje se nao vier)."""
    campos = dict(campos)
    campos.setdefault("DATA CADASTRO", pd.Timestamp(date.today()))
    campos["CPF/CNPJ"] = (campos.get("CPF/CNPJ") or "").strip()
    campos["CLIENTE"] = (campos.get("CLIENTE") or "").strip().upper()

    _validar_campos(campos)

    df = bd.ler_clientes(CAMINHO_XLSX)
    nova_linha = {col: campos.get(col, "") for col in bd.CLIENTES_COLUNAS}
    df = pd.concat([df, pd.DataFrame([nova_linha])], ignore_index=True)
    bd.escrever_clientes(CAMINHO_XLSX, df)


def atualizar_cliente(cpf_original: str, campos: dict) -> None:
    campos = dict(campos)
    campos["CPF/CNPJ"] = (campos.get("CPF/CNPJ") or "").strip()
    campos["CLIENTE"] = (campos.get("CLIENTE") or "").strip().upper()

    _validar_campos(campos, cpf_original=cpf_original)

    df = bd.ler_clientes(CAMINHO_XLSX)
    alvo = apenas_digitos(cpf_original)
    indices = df.index[df["CPF/CNPJ"].map(apenas_digitos) == alvo]
    if len(indices) == 0:
        raise ErroCliente("Cliente não encontrado (o CPF pode ter sido alterado por fora).")
    for col in bd.CLIENTES_COLUNAS:
        if col == "DATA CADASTRO":
            continue  # nunca muda a data de cadastro original
        if col in campos:
            df.loc[indices[0], col] = campos[col]
    bd.escrever_clientes(CAMINHO_XLSX, df)


def remover_cliente(cpf: str) -> None:
    """Remove um cliente cadastrado.

    Nao mexe nas propostas ja lancadas para esse CPF - se houver alguma, ela
    continua na planilha, mas VENDEDOR/CLIENTE aparecerao em branco dali pra
    frente (o calculo e sempre via busca pelo CPF, que deixa de bater com
    nenhum cliente cadastrado). Avisar o usuario sobre isso antes de excluir
    e responsabilidade da tela, nao desta funcao.
    """
    df = bd.ler_clientes(CAMINHO_XLSX)
    alvo = apenas_digitos(cpf)
    permanece = df["CPF/CNPJ"].map(apenas_digitos) != alvo
    if permanece.all():
        raise ErroCliente("Cliente não encontrado (pode já ter sido removido).")
    bd.escrever_clientes(CAMINHO_XLSX, df[permanece].reset_index(drop=True))
