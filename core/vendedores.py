"""Regras de negocio para o cadastro de VENDEDORES - inclui a senha de
acesso de cada um (login com dois niveis de acesso, Fase 2). A senha em
texto puro NUNCA e salva - so o hash+salt (core/auth.py).

Existe como cadastro proprio (nao so "nomes distintos usados em CLIENTES")
por tres motivos: 1) a lista precisa continuar existindo mesmo que nenhum
cliente esteja usando aquele nome no momento; 2) cadastrar por aqui evita
duplicar o mesmo vendedor com grafias diferentes (ex.: "Bruno" e "BRUNO"
virando duas pessoas por engano); 3) o VENDEDOR precisa logar de outro
computador, sem acesso ao .xlsx local do ADMIN - por isso este cadastro
sincroniza com o Google Sheets como qualquer outro (core/sheets_sync.py via
core/data_store.py), e o login de um vendedor e conferido de la
(core/data_store_sheets.py). Por decisao de produto, o vendedor nunca
escreve em nada - nem na propria senha - pra nao precisar dar a ele NENHUMA
permissao de escrita na planilha partilhada; pra trocar de senha, ele pede
pro ADMIN.
"""

from __future__ import annotations

import pandas as pd

from config import CAMINHO_XLSX
from core import auth
from core import data_store as bd
from core import sessao as sessao_mod


class ErroVendedor(Exception):
    """Erro de validacao de negocio (nao de leitura/escrita de arquivo)."""


def listar_vendedores() -> list[str]:
    df = bd.ler_vendedores(CAMINHO_XLSX)
    return sorted({nome for nome in df["NOME"].tolist() if nome}, key=str.upper)


def listar_vendedores_detalhado() -> pd.DataFrame:
    """Como listar_vendedores(), mas devolve o DataFrame completo (NOME +
    SENHA_HASH/SALT, sem a senha em texto puro - so pra saber se ja foi
    definida) - usado pela tela de gestão de usuários (ADMIN)."""
    return bd.ler_vendedores(CAMINHO_XLSX)


def adicionar_vendedor(nome: str) -> str:
    """Cadastra um vendedor novo e devolve o nome ja normalizado (sem espaco
    nas pontas). Se ja existir um vendedor com o mesmo nome (ignorando
    maiusculas/minusculas e espacos), nao duplica - so devolve o nome que ja
    estava cadastrado. Nao gera senha aqui - chame
    gerar_senhas_iniciais_pendentes() logo em seguida pra isso."""
    sessao_mod.exigir_admin()
    nome = (nome or "").strip()
    if not nome:
        raise ErroVendedor("Nome do vendedor é obrigatório.")

    df = bd.ler_vendedores(CAMINHO_XLSX)
    existentes = {n.upper(): n for n in df["NOME"] if n}
    if nome.upper() in existentes:
        return existentes[nome.upper()]

    nova_linha = {"NOME": nome, "SENHA_HASH": "", "SALT": ""}
    df = pd.concat([df, pd.DataFrame([nova_linha])], ignore_index=True)
    bd.escrever_vendedores(CAMINHO_XLSX, df)
    return nome


def gerar_senhas_iniciais_pendentes() -> dict[str, str]:
    """Gera e salva uma senha aleatoria pra cada vendedor que ainda nao tem
    senha (SENHA_HASH vazio) - tanto pro rollout inicial (vendedores
    cadastrados antes da Fase 2 existir) quanto pra vendedores novos
    cadastrados dali pra frente. Devolve {nome: senha em texto puro} SO
    desta chamada - a senha em texto nunca fica salva em lugar nenhum,
    entao precisa ser anotada/avisada agora (nao da pra recuperar depois,
    so redefinir uma nova com redefinir_senha())."""
    sessao_mod.exigir_admin()
    df = bd.ler_vendedores(CAMINHO_XLSX)
    geradas: dict[str, str] = {}
    for indice, linha in df.iterrows():
        if not linha["SENHA_HASH"]:
            senha = auth.gerar_senha_aleatoria()
            hash_hex, salt_hex = auth.hash_senha(senha)
            df.loc[indice, "SENHA_HASH"] = hash_hex
            df.loc[indice, "SALT"] = salt_hex
            geradas[linha["NOME"]] = senha
    if geradas:
        bd.escrever_vendedores(CAMINHO_XLSX, df)
    return geradas


def redefinir_senha(nome: str) -> str:
    """Gera uma senha nova pro vendedor `nome` (substitui qualquer senha
    anterior) e devolve em texto puro pra avisar a pessoa. So o ADMIN pode
    fazer isso - o vendedor nao troca a propria senha (decisao de produto)."""
    sessao_mod.exigir_admin()
    df = bd.ler_vendedores(CAMINHO_XLSX)
    alvo = df.index[df["NOME"].str.upper() == nome.strip().upper()]
    if len(alvo) == 0:
        raise ErroVendedor(f"Vendedor '{nome}' não encontrado.")

    senha = auth.gerar_senha_aleatoria()
    hash_hex, salt_hex = auth.hash_senha(senha)
    df.loc[alvo[0], "SENHA_HASH"] = hash_hex
    df.loc[alvo[0], "SALT"] = salt_hex
    bd.escrever_vendedores(CAMINHO_XLSX, df)
    return senha


def verificar_login(nome: str, senha: str) -> str | None:
    """Confere usuario+senha contra o cadastro de vendedores, lido do Google
    Sheets (nao do .xlsx local - o vendedor pode estar em outro computador).
    Devolve o nome com a grafia oficial cadastrada se a senha confere, ou
    None caso contrario (usuario inexistente ou senha errada - nao
    distinguimos os dois casos na mensagem, por seguranca)."""
    from core import data_store_sheets as bd_sheets

    df = bd_sheets.ler_vendedores()
    alvo = df[df["NOME"].str.upper() == nome.strip().upper()]
    if alvo.empty:
        return None
    linha = alvo.iloc[0]
    if auth.senha_confere(senha, linha.get("SENHA_HASH", ""), linha.get("SALT", "")):
        return linha["NOME"]
    return None
