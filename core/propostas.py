"""Regras de negocio para PROPOSTAS: cadastro, atualizacao de status e
classificacao para o dashboard.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from config import CAMINHO_XLSX
from core import clientes as clientes_mod
from core import data_store as bd
from core.validators import apenas_digitos

STATUS_EM_ANALISE = "Em Análise"
STATUS_PRE_APROVADO = "Pré-aprovado"
STATUS_APROVADO = "Aprovado"
STATUS_NF_ANEXADA = "Nota Fiscal Anexada"
STATUS_GARANTIA_ASSINADA = "Garantia Assinada"
STATUS_NEGADO = "Negado"

# Ordem sugerida nos formularios/dropdowns (funil aproximado da proposta).
STATUS_OPCOES = [
    STATUS_EM_ANALISE,
    STATUS_PRE_APROVADO,
    STATUS_APROVADO,
    STATUS_NF_ANEXADA,
    STATUS_GARANTIA_ASSINADA,
    STATUS_NEGADO,
]

# Statuses que contam como "Negado" ou "Em Análise" no dashboard. Qualquer
# outro valor - inclusive um status novo que ainda nao existe hoje - conta
# como "Aprovado" nas taxas gerais, porque na pratica representa alguma etapa
# depois da aprovacao inicial (combinado com o usuario: o importante e ver, no
# detalhamento por status do dashboard, onde as aprovadas estao empacando).
_PALAVRAS_NEGADO = {"NEGADO", "NEGADA", "REPROVADO", "REPROVADA", "CANCELADO", "CANCELADA"}
_PALAVRAS_EM_ANALISE = {"EM ANÁLISE", "EM ANALISE", "ANÁLISE", "ANALISE", "PENDENTE"}


class ErroProposta(Exception):
    pass


def categoria_status(status: str) -> str:
    """Classifica um status (mesmo um customizado/novo) em 'Negado',
    'Em Análise' ou 'Aprovado' - as 3 categorias usadas nas taxas do dashboard.
    """
    s = (status or "").strip().upper()
    if not s:
        return ""
    if s in _PALAVRAS_NEGADO:
        return "Negado"
    if s in _PALAVRAS_EM_ANALISE:
        return "Em Análise"
    return "Aprovado"


def listar_propostas() -> pd.DataFrame:
    """O indice do DataFrame retornado corresponde a posicao real da proposta
    no arquivo (a mesma que atualizar_proposta espera) - por isso NAO e
    resetado depois do sort. Nao reordene esse DataFrame antes de usar o
    indice para editar uma linha.
    """
    df = bd.ler_propostas(CAMINHO_XLSX)
    return df.sort_values("DATA", ascending=False)


def historico_por_cpf(cpf: str) -> pd.DataFrame:
    """Mesma observacao de listar_propostas: o indice reflete a posicao real
    no arquivo, necessaria para atualizar_proposta().
    """
    df = bd.ler_propostas(CAMINHO_XLSX)
    alvo = apenas_digitos(cpf)
    filtrado = df[df["CPF"].map(apenas_digitos) == alvo]
    return filtrado.sort_values("DATA", ascending=False)


def _validar_campos(campos: dict) -> None:
    cpf = (campos.get("CPF") or "").strip()
    valor = campos.get("VALOR (R$)")
    equipamento = (campos.get("EQUIPAMENTO") or "").strip()
    banco = (campos.get("BANCO") or "").strip()

    if not cpf:
        raise ErroProposta("CPF do cliente é obrigatório.")
    if clientes_mod.buscar_por_cpf(cpf) is None:
        raise ErroProposta(f"Não existe cliente cadastrado com o CPF {cpf}. Cadastre o cliente primeiro.")
    # NaN e "truthy" e NaN <= 0 e sempre False, entao "not valor or valor<=0"
    # sozinho deixaria um valor invalido passar sem ser pego
    if not valor or pd.isna(valor) or float(valor) <= 0:
        raise ErroProposta("Valor solicitado deve ser maior que zero.")
    if not equipamento:
        raise ErroProposta("Equipamento é obrigatório.")
    if not banco:
        raise ErroProposta("Banco/financeira é obrigatório.")


def adicionar_proposta(campos: dict) -> None:
    """`campos` deve conter DATA, CPF, VALOR (R$), MESES, EQUIPAMENTO, BANCO,
    STATUS, OBSERVAÇÕES. DATA e STATUS tem valor padrao se nao informados."""
    campos = dict(campos)
    campos.setdefault("DATA", pd.Timestamp(date.today()))
    campos.setdefault("STATUS", STATUS_EM_ANALISE)
    campos["CPF"] = (campos.get("CPF") or "").strip()

    _validar_campos(campos)

    df = bd.ler_propostas(CAMINHO_XLSX)[bd.PROPOSTAS_COLUNAS_EDITAVEIS]
    nova_linha = {col: campos.get(col, "") for col in bd.PROPOSTAS_COLUNAS_EDITAVEIS}
    df = pd.concat([df, pd.DataFrame([nova_linha])], ignore_index=True)
    bd.escrever_propostas(CAMINHO_XLSX, df)


def atualizar_proposta(indice: int, campos: dict) -> None:
    """`indice` e a posicao (0-based) da proposta na tabela retornada por
    listar_propostas()/historico_por_cpf() no momento em que a edicao foi
    aberta. Como o app sempre reescreve a aba inteira na mesma ordem, essa
    posicao continua valida entre a leitura e a escrita, desde que nada mais
    tenha mexido no arquivo nesse meio-tempo (uso individual e local).
    """
    df = bd.ler_propostas(CAMINHO_XLSX)[bd.PROPOSTAS_COLUNAS_EDITAVEIS]
    if indice not in df.index:
        raise ErroProposta("Proposta não encontrada (a lista pode ter mudado). Recarregue e tente de novo.")

    # `campos` pode vir parcial (so os campos que mudaram) - valida sempre o
    # estado FINAL da linha (valores atuais + alteracoes), nunca so o que foi
    # passado, senao uma edicao parcial poderia escapar da validacao normal
    # (ex: zerar o valor por engano numa linha que ja tinha valor valido).
    estado_final = df.loc[indice].to_dict()
    estado_final.update(campos)
    _validar_campos(estado_final)

    for col, valor in campos.items():
        if col in bd.PROPOSTAS_COLUNAS_EDITAVEIS:
            # "" nao pode ser atribuido direto numa coluna ja tipada como
            # numerica (MESES/VALOR viram float64 na leitura) - o pandas
            # recusa ("Invalid value '' for dtype 'float64'"). None e aceito
            # em qualquer coluna (numerica vira NaN, texto vira None mesmo).
            df.loc[indice, col] = None if valor == "" else valor
    bd.escrever_propostas(CAMINHO_XLSX, df)


def remover_proposta(indice: int) -> None:
    """`indice` e a posicao real da proposta no arquivo (mesmo valor que
    atualizar_proposta espera - ver o aviso na docstring dela)."""
    df = bd.ler_propostas(CAMINHO_XLSX)[bd.PROPOSTAS_COLUNAS_EDITAVEIS]
    if indice not in df.index:
        raise ErroProposta("Proposta não encontrada (a lista pode ter mudado). Recarregue e tente de novo.")
    bd.escrever_propostas(CAMINHO_XLSX, df.drop(index=indice).reset_index(drop=True))
