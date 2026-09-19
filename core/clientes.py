"""Regras de negocio para CLIENTES: busca, cadastro, edicao e remocao.

Esta camada nao sabe nada sobre .xlsx - so conversa com core/data_store.py
usando DataFrames. As telas (desktop/screens/*.py) so conversam com esta
camada, nunca direto com data_store - assim, se o banco mudar no futuro, so
data_store.py precisa mudar.
"""

from __future__ import annotations

import unicodedata
from datetime import date

import pandas as pd

from config import CAMINHO_XLSX
from core import data_store as bd
from core import sessao as sessao_mod
from core.endereco import UFS_VALIDAS
from core.validators import apenas_digitos, cpf_cnpj_valido, email_valido

TIPO_OPCOES = ["Cliente", "Avalista"]


class ErroCliente(Exception):
    """Erro de validacao de negocio (nao de leitura/escrita de arquivo)."""


def _ler_da_fonte_ativa() -> pd.DataFrame:
    """ADMIN sempre le do .xlsx local (funciona offline); VENDEDOR le do
    Google Sheets (pode estar em outro computador, sem acesso ao arquivo
    local do ADMIN) - ver core/data_store_sheets.py."""
    if sessao_mod.eh_vendedor():
        from core import data_store_sheets as bd_sheets

        return bd_sheets.ler_clientes()
    return bd.ler_clientes(CAMINHO_XLSX)


ORDENACAO_NOME_AZ = "nome_az"
ORDENACAO_NOME_ZA = "nome_za"
ORDENACAO_CADASTRO_RECENTE = "cadastro_recente"
ORDENACAO_CADASTRO_ANTIGO = "cadastro_antigo"
# (chave, rotulo) na ordem em que a tela deve listar
ORDENACAO_OPCOES = [
    (ORDENACAO_NOME_AZ, "Nome (A-Z)"),
    (ORDENACAO_NOME_ZA, "Nome (Z-A)"),
    (ORDENACAO_CADASTRO_RECENTE, "Data de cadastro (mais recente primeiro)"),
    (ORDENACAO_CADASTRO_ANTIGO, "Data de cadastro (mais antigo primeiro)"),
]


def _chave_nome(nome: str) -> str:
    """Maiusculas e SEM acento, pra ordenar como um dicionario: por padrao o
    Python poe "JÉSSICA" depois de "JULIANA" (o "É" vale mais que qualquer
    letra sem acento), o que na lista parece um erro de ordem alfabetica."""
    sem_acento = "".join(c for c in unicodedata.normalize("NFD", nome) if unicodedata.category(c) != "Mn")
    return sem_acento.upper()


def _ordenar(df: pd.DataFrame, ordenacao: str) -> pd.DataFrame:
    if ordenacao not in {chave for chave, _ in ORDENACAO_OPCOES}:
        raise ValueError(f"Ordenação desconhecida: {ordenacao!r}")

    auxiliar = df.assign(
        _NOME=df["CLIENTE"].map(_chave_nome),
        _CADASTRO=pd.to_datetime(df["DATA CADASTRO"], errors="coerce"),
    )
    if ordenacao in (ORDENACAO_NOME_AZ, ORDENACAO_NOME_ZA):
        colunas, crescente = ["_NOME", "CPF/CNPJ"], [ordenacao == ORDENACAO_NOME_AZ, True]
    else:
        # empate de data (muito comum: varios cadastrados no mesmo dia) desempata
        # por nome, e quem nao tem data de cadastro vai sempre pro fim
        colunas, crescente = ["_CADASTRO", "_NOME"], [ordenacao == ORDENACAO_CADASTRO_ANTIGO, True]
    auxiliar = auxiliar.sort_values(colunas, ascending=crescente, na_position="last")
    return auxiliar.drop(columns=["_NOME", "_CADASTRO"]).reset_index(drop=True)


def listar_clientes(ordenacao: str = ORDENACAO_NOME_AZ) -> pd.DataFrame:
    df = sessao_mod.filtrar_por_vendedor_logado(_ler_da_fonte_ativa())
    return _ordenar(df, ordenacao)


def buscar_por_cpf(cpf: str) -> dict | None:
    df = sessao_mod.filtrar_por_vendedor_logado(_ler_da_fonte_ativa())
    alvo = apenas_digitos(cpf)
    encontrado = df[df["CPF/CNPJ"].map(apenas_digitos) == alvo]
    if encontrado.empty:
        return None
    return encontrado.iloc[0].to_dict()


def _mesmo_texto(serie: pd.Series, valor: str) -> pd.Series:
    """Igualdade sem diferenciar maiusculas nem espacos nas pontas (dado
    legado tem "AVALISTA"/"Avalista" e nomes de vendedor com grafias mistas)."""
    return serie.str.strip().str.upper() == valor.strip().upper()


def buscar(
    termo: str = "",
    *,
    vendedor: str | None = None,
    tipo: str | None = None,
    cadastro_de: date | pd.Timestamp | None = None,
    cadastro_ate: date | pd.Timestamp | None = None,
    ordenacao: str = ORDENACAO_NOME_AZ,
) -> pd.DataFrame:
    """Busca por nome (substring, sem diferenciar maiusculas) ou por CPF/CNPJ,
    combinada (E) com os filtros que vierem preenchidos:
    - vendedor / tipo: igualdade exata, sem diferenciar maiusculas;
    - cadastro_de / cadastro_ate: periodo da DATA CADASTRO, com as duas pontas
      INCLUIDAS; quem nao tem data de cadastro nunca entra num periodo.
    Filtro None (ou "") = sem filtro. O resultado sai na `ordenacao` pedida."""
    df = listar_clientes(ordenacao)
    mascara = pd.Series(True, index=df.index)

    termo = (termo or "").strip()
    if termo:
        digitos = apenas_digitos(termo)
        por_cpf = (
            df["CPF/CNPJ"].map(apenas_digitos).str.contains(digitos, na=False)
            if digitos
            else pd.Series(False, index=df.index)
        )
        por_nome = df["CLIENTE"].str.upper().str.contains(termo.upper(), na=False)
        mascara &= por_nome | por_cpf

    if vendedor:
        mascara &= _mesmo_texto(df["VENDEDOR"], vendedor)
    if tipo:
        mascara &= _mesmo_texto(df["TIPO"], tipo)

    if cadastro_de is not None or cadastro_ate is not None:
        cadastro = pd.to_datetime(df["DATA CADASTRO"], errors="coerce")
        if cadastro_de is not None:
            mascara &= cadastro >= pd.Timestamp(cadastro_de).normalize()
        if cadastro_ate is not None:
            mascara &= cadastro <= pd.Timestamp(cadastro_ate).normalize()

    return df[mascara]


def _normalizar_cep(campos: dict) -> None:
    """CEP em branco fica em branco; preenchido, tem que ter 8 numeros e e
    gravado sempre como 00000-000 (com o zero da frente preservado - por isso
    a coluna e texto, nunca numero)."""
    cep = (campos.get("CEP") or "").strip()
    if not cep:
        campos["CEP"] = ""
        return
    digitos = apenas_digitos(cep)
    if len(digitos) != 8:
        raise ErroCliente("CEP inválido - o CEP tem 8 números (ex.: 60165-120).")
    campos["CEP"] = f"{digitos[:5]}-{digitos[5:]}"


def _normalizar_uf(campos: dict) -> None:
    """UF em branco fica em branco; preenchida, e sempre a sigla de um estado
    valido em maiusculas (ex.: "ce" vira "CE"; "Ceara" e recusado)."""
    uf = (campos.get("UF") or "").strip().upper()
    if uf and uf not in UFS_VALIDAS:
        raise ErroCliente("UF inválida - use a sigla do estado com 2 letras (ex.: CE).")
    campos["UF"] = uf


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
    sessao_mod.exigir_admin()
    campos = dict(campos)
    campos.setdefault("DATA CADASTRO", pd.Timestamp(date.today()))
    campos["CPF/CNPJ"] = (campos.get("CPF/CNPJ") or "").strip()
    campos["CLIENTE"] = (campos.get("CLIENTE") or "").strip().upper()

    _validar_campos(campos)
    _normalizar_cep(campos)
    _normalizar_uf(campos)

    df = bd.ler_clientes(CAMINHO_XLSX)
    nova_linha = {col: campos.get(col, "") for col in bd.CLIENTES_COLUNAS}
    df = pd.concat([df, pd.DataFrame([nova_linha])], ignore_index=True)
    bd.escrever_clientes(CAMINHO_XLSX, df)


def atualizar_cliente(cpf_original: str, campos: dict) -> None:
    sessao_mod.exigir_admin()
    campos = dict(campos)
    campos["CPF/CNPJ"] = (campos.get("CPF/CNPJ") or "").strip()
    campos["CLIENTE"] = (campos.get("CLIENTE") or "").strip().upper()

    _validar_campos(campos, cpf_original=cpf_original)
    # atualizacao parcial (so alguns campos) nao mexe no que nao veio
    if "CEP" in campos:
        _normalizar_cep(campos)
    if "UF" in campos:
        _normalizar_uf(campos)

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
    sessao_mod.exigir_admin()
    df = bd.ler_clientes(CAMINHO_XLSX)
    alvo = apenas_digitos(cpf)
    permanece = df["CPF/CNPJ"].map(apenas_digitos) != alvo
    if permanece.all():
        raise ErroCliente("Cliente não encontrado (pode já ter sido removido).")
    bd.escrever_clientes(CAMINHO_XLSX, df[permanece].reset_index(drop=True))
