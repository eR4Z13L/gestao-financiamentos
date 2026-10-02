"""Cadastro de bancos/financeiras (aba BANCOS) - a lista fechada do campo "Banco" da proposta.

- Nome unico sem diferenciar maiusculas/espacos ("santander" e "Santander" sao o mesmo banco).
- Renomear corrige tambem o BANCO das propostas antigas (comparando sem diferenciar maiusculas).
- Desativar tira o banco da lista do formulario, mas as propostas antigas continuam com ele.
- Excluir so e possivel se nenhuma proposta usa o banco (senao, desative).
- "Todos" (a proposta foi para todos os bancos) e uma opcao fixa do formulario, nunca um cadastro.

So o ADMIN escreve (sessao.exigir_admin()), como nos outros cadastros.
"""

from __future__ import annotations

import pandas as pd

from config import CAMINHO_XLSX
from core import data_store as bd
from core import sessao as sessao_mod
from core.vendedores import esta_ativo

BANCO_TODOS = bd.BANCO_TODOS


class ErroBanco(Exception):
    """Erro de validacao de negocio (a mensagem diz o que fazer) - nada foi gravado."""


def _chave(nome) -> str:
    return str(nome or "").strip().upper()


def _uso_nas_propostas() -> dict[str, int]:
    """Quantas propostas usam cada banco (chave sem diferenciar maiusculas/espacos)."""
    bancos = bd.ler_propostas(CAMINHO_XLSX)["BANCO"].map(_chave)
    return bancos[bancos != ""].value_counts().to_dict()


def listar_bancos() -> pd.DataFrame:
    """O cadastro com NOME, ATIVO (True/False) e PROPOSTAS (quantas usam o banco), em ordem alfabetica."""
    df = bd.ler_bancos(CAMINHO_XLSX)
    uso = _uso_nas_propostas()
    df = df[df["NOME"] != ""].copy()
    df["ATIVO"] = df["ATIVO"].map(esta_ativo)
    df["PROPOSTAS"] = df["NOME"].map(lambda nome: uso.get(_chave(nome), 0)).astype(int)
    return df.sort_values("NOME", key=lambda s: s.str.upper()).reset_index(drop=True)


def nomes_ativos() -> list[str]:
    """Os bancos que aparecem na lista do formulario de proposta (sem "Todos")."""
    df = listar_bancos()
    return df.loc[df["ATIVO"], "NOME"].tolist()


def _validar_nome(nome: str) -> str:
    nome = " ".join(str(nome or "").split())
    if not nome:
        raise ErroBanco("Informe o nome do banco.")
    if _chave(nome) == _chave(BANCO_TODOS):
        raise ErroBanco(f'"{BANCO_TODOS}" já é uma opção fixa do formulário (enviada a todos os bancos).')
    return nome


def _linha_do_banco(df: pd.DataFrame, nome: str) -> int:
    alvo = df.index[df["NOME"].map(_chave) == _chave(nome)]
    if len(alvo) == 0:
        raise ErroBanco(f'O banco "{nome}" não está no cadastro.')
    return alvo[0]


def adicionar_banco(nome: str) -> str:
    """Cadastra um banco novo (ja ativo). Devolve o nome como foi gravado."""
    sessao_mod.exigir_admin()
    nome = _validar_nome(nome)
    df = bd.ler_bancos(CAMINHO_XLSX)
    if (df["NOME"].map(_chave) == _chave(nome)).any():
        raise ErroBanco(f'O banco "{nome}" já está no cadastro.')
    df = pd.concat([df, pd.DataFrame([{"NOME": nome, "ATIVO": "Sim"}])], ignore_index=True)
    bd.escrever_bancos(CAMINHO_XLSX, df)
    return nome


def renomear_banco(nome_atual: str, nome_novo: str) -> int:
    """Troca o nome no cadastro E nas propostas que usam o banco. Devolve quantas propostas mudaram.
    So mudar maiusculas ("smart" -> "Smart") tambem vale."""
    sessao_mod.exigir_admin()
    nome_novo = _validar_nome(nome_novo)
    df = bd.ler_bancos(CAMINHO_XLSX)
    linha = _linha_do_banco(df, nome_atual)
    outros = df.drop(index=linha)
    if (outros["NOME"].map(_chave) == _chave(nome_novo)).any():
        raise ErroBanco(f'Já existe outro banco chamado "{nome_novo}" no cadastro.')
    if df.at[linha, "NOME"] == nome_novo:
        return 0

    # propostas primeiro: se o cadastro falhar depois, o nome antigo continua nele e da pra repetir
    propostas = bd.ler_propostas(CAMINHO_XLSX)[bd.PROPOSTAS_COLUNAS_EDITAVEIS]
    afetadas = propostas["BANCO"].map(_chave) == _chave(df.at[linha, "NOME"])
    quantidade = int(afetadas.sum())
    if quantidade:
        propostas.loc[afetadas, "BANCO"] = nome_novo
        bd.escrever_propostas(CAMINHO_XLSX, propostas)
    df.at[linha, "NOME"] = nome_novo
    bd.escrever_bancos(CAMINHO_XLSX, df)
    return quantidade


def _definir_ativo(nome: str, ativo: bool) -> None:
    sessao_mod.exigir_admin()
    df = bd.ler_bancos(CAMINHO_XLSX)
    linha = _linha_do_banco(df, nome)
    df.at[linha, "ATIVO"] = "Sim" if ativo else "Não"
    bd.escrever_bancos(CAMINHO_XLSX, df)


def desativar_banco(nome: str) -> None:
    _definir_ativo(nome, False)


def reativar_banco(nome: str) -> None:
    _definir_ativo(nome, True)


def excluir_banco(nome: str) -> None:
    """Apaga do cadastro um banco que nenhuma proposta usa (se alguma usa, recusa: desative em vez disso)."""
    sessao_mod.exigir_admin()
    df = bd.ler_bancos(CAMINHO_XLSX)
    linha = _linha_do_banco(df, nome)
    usadas = _uso_nas_propostas().get(_chave(nome), 0)
    if usadas:
        raise ErroBanco(
            f'O banco "{df.at[linha, "NOME"]}" é usado em {usadas} proposta(s) e não pode ser excluído. '
            "Desative-o: ele sai da lista do formulário, e as propostas antigas continuam como estão."
        )
    bd.escrever_bancos(CAMINHO_XLSX, df.drop(index=linha).reset_index(drop=True))
