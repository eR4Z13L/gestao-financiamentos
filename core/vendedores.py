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

_PALAVRA_INATIVO = "NÃO"


def esta_ativo(valor_ativo: str) -> bool:
    """So "Não" (sem diferenciar maiusculas) desativa - vazio (planilha de antes desta
    coluna existir, ou vendedor nunca desativado) conta como ATIVO. Nunca desativa
    ninguem so por causa de um dado ausente."""
    return (valor_ativo or "").strip().upper() != _PALAVRA_INATIVO


class ErroVendedor(Exception):
    """Erro de validacao de negocio (nao de leitura/escrita de arquivo)."""


def listar_vendedores() -> list[str]:
    """TODOS os vendedores (ativos e inativos) - usado onde um nome precisa continuar
    "reconhecido" mesmo desativado (ex.: core.dashboard.por_vendedor, pra nao jogar o
    historico de quem foi desativado no balde "Não identificado"). Pra escolher um
    vendedor para trabalho NOVO (cadastro de cliente), use listar_vendedores_ativos()."""
    df = bd.ler_vendedores(CAMINHO_XLSX)
    return sorted({nome for nome in df["NOME"].tolist() if nome}, key=str.upper)


def listar_vendedores_ativos() -> list[str]:
    """Só os ATIVOS, em ordem alfabética - para pickers de trabalho novo (o combo de
    Vendedor no cadastro de cliente). Um vendedor desativado não pode receber cliente
    novo, mas o nome dele continua valendo nos filtros e no histórico (listar_vendedores)."""
    df = bd.ler_vendedores(CAMINHO_XLSX)
    return sorted({nome for nome, ativo in zip(df["NOME"], df["ATIVO"]) if nome and esta_ativo(ativo)}, key=str.upper)


def listar_vendedores_detalhado() -> pd.DataFrame:
    """Como listar_vendedores(), mas devolve o DataFrame completo (NOME, SENHA_HASH/SALT
    -sem a senha em texto puro, so pra saber se ja foi definida-, ATIVO) - usado pela
    tela de Administração (ADMIN)."""
    return bd.ler_vendedores(CAMINHO_XLSX)


def contar_carteira(nome: str) -> int:
    """Quantos clientes (CLIENTES.VENDEDOR) estao com `nome` hoje - sem diferenciar
    maiusculas/espacos. E a "carteira" que precisa estar vazia pra desativar."""
    df = bd.ler_clientes(CAMINHO_XLSX)
    alvo = nome.strip().upper()
    return int((df["VENDEDOR"].str.strip().str.upper() == alvo).sum())


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

    nova_linha = {"NOME": nome, "SENHA_HASH": "", "SALT": "", "ATIVO": "Sim"}
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


def desativar_vendedor(nome: str) -> None:
    """Desativa o vendedor: para de aparecer nos seletores de trabalho novo e não
    consegue mais logar (ver verificar_login), mas o nome continua valendo no histórico
    (propostas/clientes já lançados nunca mudam). Só funciona com a carteira VAZIA -
    transfira os clientes dele antes (ver transferir_carteira)."""
    sessao_mod.exigir_admin()
    df = bd.ler_vendedores(CAMINHO_XLSX)
    alvo = df.index[df["NOME"].str.upper() == nome.strip().upper()]
    if len(alvo) == 0:
        raise ErroVendedor(f"Vendedor '{nome}' não encontrado.")
    nome_oficial = df.loc[alvo[0], "NOME"]
    carteira = contar_carteira(nome_oficial)
    if carteira:
        raise ErroVendedor(
            f"'{nome_oficial}' ainda tem {carteira} cliente(s) na carteira. "
            "Transfira a carteira para outro vendedor antes de desativar."
        )
    df.loc[alvo[0], "ATIVO"] = "Não"
    bd.escrever_vendedores(CAMINHO_XLSX, df)


def reativar_vendedor(nome: str) -> None:
    """Reativa um vendedor desativado - volta a aparecer nos seletores e a poder logar."""
    sessao_mod.exigir_admin()
    df = bd.ler_vendedores(CAMINHO_XLSX)
    alvo = df.index[df["NOME"].str.upper() == nome.strip().upper()]
    if len(alvo) == 0:
        raise ErroVendedor(f"Vendedor '{nome}' não encontrado.")
    df.loc[alvo[0], "ATIVO"] = "Sim"
    bd.escrever_vendedores(CAMINHO_XLSX, df)


def transferir_carteira(de: str, para: str) -> int:
    """Passa todos os clientes de `de` para `para` (CLIENTES.VENDEDOR) - usado antes de
    desativar `de`, ou só pra redistribuir carteira. `para` precisa ser um vendedor
    cadastrado e ATIVO. Devolve quantos clientes foram movidos (0 não é erro: a carteira
    já podia estar vazia)."""
    sessao_mod.exigir_admin()
    de = (de or "").strip()
    para = (para or "").strip()
    if not de or not para:
        raise ErroVendedor("Informe o vendedor de origem e o de destino.")
    if de.upper() == para.upper():
        raise ErroVendedor("Origem e destino não podem ser o mesmo vendedor.")

    vendedores_df = bd.ler_vendedores(CAMINHO_XLSX)
    alvo_destino = vendedores_df[vendedores_df["NOME"].str.upper() == para.upper()]
    if alvo_destino.empty:
        raise ErroVendedor(f"Vendedor de destino '{para}' não encontrado.")
    nome_destino = alvo_destino.iloc[0]["NOME"]
    if not esta_ativo(alvo_destino.iloc[0]["ATIVO"]):
        raise ErroVendedor(f"'{nome_destino}' está desativado - reative antes de transferir a carteira para ele(a).")

    df = bd.ler_clientes(CAMINHO_XLSX)
    mascara = df["VENDEDOR"].str.strip().str.upper() == de.upper()
    quantidade = int(mascara.sum())
    if quantidade:
        df.loc[mascara, "VENDEDOR"] = nome_destino
        bd.escrever_clientes(CAMINHO_XLSX, df)
    return quantidade


def renomear_vendedor(nome_atual: str, novo_nome: str) -> str:
    """Renomeia o vendedor no cadastro E em todos os clientes que estavam com ele -
    CLIENTES.VENDEDOR e texto solto (nao um id), entao sem essa cascata o nome antigo
    ficaria "orfao" nos clientes ja cadastrados. Devolve o nome novo, ja normalizado."""
    sessao_mod.exigir_admin()
    novo_nome = (novo_nome or "").strip()
    if not novo_nome:
        raise ErroVendedor("O novo nome não pode ficar em branco.")

    vendedores_df = bd.ler_vendedores(CAMINHO_XLSX)
    alvo = vendedores_df.index[vendedores_df["NOME"].str.upper() == nome_atual.strip().upper()]
    if len(alvo) == 0:
        raise ErroVendedor(f"Vendedor '{nome_atual}' não encontrado.")
    nome_oficial_atual = vendedores_df.loc[alvo[0], "NOME"]

    if novo_nome.upper() != nome_oficial_atual.upper():
        duplicado = vendedores_df[
            (vendedores_df["NOME"].str.upper() == novo_nome.upper()) & (vendedores_df.index != alvo[0])
        ]
        if not duplicado.empty:
            raise ErroVendedor(f"Já existe um vendedor chamado '{duplicado.iloc[0]['NOME']}'.")

    vendedores_df.loc[alvo[0], "NOME"] = novo_nome
    bd.escrever_vendedores(CAMINHO_XLSX, vendedores_df)

    clientes_df = bd.ler_clientes(CAMINHO_XLSX)
    mascara = clientes_df["VENDEDOR"].str.strip().str.upper() == nome_oficial_atual.upper()
    if mascara.any():
        clientes_df.loc[mascara, "VENDEDOR"] = novo_nome
        bd.escrever_clientes(CAMINHO_XLSX, clientes_df)
    return novo_nome


def verificar_login(nome: str, senha: str) -> str | None:
    """Confere usuario+senha contra o cadastro de vendedores, lido do Google
    Sheets (nao do .xlsx local - o vendedor pode estar em outro computador).
    Devolve o nome com a grafia oficial cadastrada se a senha confere, ou
    None caso contrario (usuario inexistente, senha errada ou vendedor
    DESATIVADO - nao distinguimos os casos na mensagem, por seguranca)."""
    from core import data_store_sheets as bd_sheets

    df = bd_sheets.ler_vendedores()
    alvo = df[df["NOME"].str.upper() == nome.strip().upper()]
    if alvo.empty:
        return None
    linha = alvo.iloc[0]
    if not esta_ativo(linha.get("ATIVO", "")):
        return None
    if auth.senha_confere(senha, linha.get("SENHA_HASH", ""), linha.get("SALT", "")):
        return linha["NOME"]
    return None
