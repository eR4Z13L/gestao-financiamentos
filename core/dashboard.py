"""Calculos do dashboard - tudo em tempo real a partir de CLIENTES e PROPOSTAS,
nada fica salvo na planilha.
"""

from __future__ import annotations

import pandas as pd

from core import vendedores as vendedores_mod
from core.propostas import categoria_status, listar_propostas


def _percentual(numerador: float, denominador: float) -> float:
    return (numerador / denominador * 100) if denominador else 0.0


def totais_gerais(propostas: pd.DataFrame | None = None) -> dict:
    df = propostas if propostas is not None else listar_propostas()
    categoria = df["STATUS"].map(categoria_status)

    total = len(df)
    aprovadas = int((categoria == "Aprovado").sum())
    negadas = int((categoria == "Negado").sum())
    em_analise = int((categoria == "Em Análise").sum())
    # propostas que NAO entram em nenhum dos 3 cards acima: status em branco
    # ("sem_status") ou status preenchido mas desconhecido/mal digitado
    # ("nao_identificado") - separados pra tela poder explicar a diferenca
    # em vez de so deixar o total "nao bater" com a soma dos cards.
    sem_status = int((categoria == "").sum())
    nao_identificado = int((categoria == "Não identificado").sum())
    decididas = aprovadas + negadas
    # soma com skipna (padrao do pandas) ja ignora VALOR ausente em vez de
    # tratar como R$0 - mas isso e invisivel pra quem olha so o numero final,
    # entao contamos separado pra tela poder avisar que o "Valor total
    # aprovado" pode estar subestimado (nao esta errado, so incompleto).
    aprovadas_sem_valor = int(((categoria == "Aprovado") & df["VALOR (R$)"].isna()).sum())
    valor_aprovado = float(df.loc[categoria == "Aprovado", "VALOR (R$)"].sum())

    return {
        "total_propostas": total,
        "aprovadas": aprovadas,
        "negadas": negadas,
        "em_analise": em_analise,
        "sem_status": sem_status,
        "nao_identificado": nao_identificado,
        "aprovadas_sem_valor": aprovadas_sem_valor,
        "taxa_aprovacao": _percentual(aprovadas, decididas),
        "taxa_reprovacao": _percentual(negadas, decididas),
        "valor_aprovado": valor_aprovado,
    }


def detalhamento_por_status(propostas: pd.DataFrame | None = None) -> pd.DataFrame:
    """Contagem e valor por status EXATO (nao so pela categoria geral), pra
    entender onde as propostas aprovadas estao empacando - ex: aprovada mas
    nunca virou Nota Fiscal Anexada / Garantia Assinada.
    """
    df = propostas if propostas is not None else listar_propostas()
    if df.empty:
        return pd.DataFrame(columns=["STATUS", "Categoria", "Quantidade", "Valor (R$)"])

    # a categoria (usada nas taxas) e calculada a partir do status ORIGINAL,
    # antes de trocar "" por um rotulo de exibicao - senao uma proposta sem
    # status cai (por engano) no balde "Aprovado" so por nao ser nem negado
    # nem em analise.
    categoria = df["STATUS"].map(categoria_status).replace("", "Não contabilizado")
    status_exibicao = df["STATUS"].replace("", "(sem status)")

    tmp = pd.DataFrame({"STATUS": status_exibicao, "Categoria": categoria, "_valor": df["VALOR (R$)"]})
    agrupado = (
        tmp.groupby(["STATUS", "Categoria"], as_index=False)
        .agg(Quantidade=("STATUS", "size"), **{"Valor (R$)": ("_valor", "sum")})
    )
    ordem_categoria = {"Aprovado": 0, "Em Análise": 1, "Negado": 2, "Não identificado": 3, "Não contabilizado": 4}
    agrupado["_ordem"] = agrupado["Categoria"].map(ordem_categoria).fillna(3)
    agrupado = agrupado.sort_values(["_ordem", "Quantidade"], ascending=[True, False])
    return agrupado[["STATUS", "Categoria", "Quantidade", "Valor (R$)"]].reset_index(drop=True)


_COLUNAS_POR_VENDEDOR = [
    "Vendedor", "Total", "Aprovadas", "Negadas", "Em Análise", "Não Contabilizado",
    "Taxa Aprovação (%)", "Valor Aprovado (R$)",
]

_VENDEDOR_NAO_IDENTIFICADO = "Não identificado"


def por_vendedor(propostas: pd.DataFrame | None = None) -> pd.DataFrame:
    df = propostas if propostas is not None else listar_propostas()
    if df.empty:
        return pd.DataFrame(columns=_COLUNAS_POR_VENDEDOR)

    # vendedor em branco OU que nao esta (mais) no cadastro oficial (ex: nome
    # digitado direto na planilha, com erro de grafia) cai numa unica
    # categoria "Não identificado", em vez de virar uma linha solta por
    # variante de nome.
    oficiais = {nome.upper() for nome in vendedores_mod.listar_vendedores()}

    def _rotulo_vendedor(nome: str) -> str:
        nome = (nome or "").strip()
        return nome if nome and nome.upper() in oficiais else _VENDEDOR_NAO_IDENTIFICADO

    df = df.assign(
        _categoria=df["STATUS"].map(categoria_status),
        _vendedor_rotulo=df["VENDEDOR"].map(_rotulo_vendedor),
    )
    linhas = []
    for vendedor, grupo in df.groupby("_vendedor_rotulo"):
        aprovadas = int((grupo["_categoria"] == "Aprovado").sum())
        negadas = int((grupo["_categoria"] == "Negado").sum())
        em_analise = int((grupo["_categoria"] == "Em Análise").sum())
        nao_contabilizado = len(grupo) - aprovadas - negadas - em_analise
        decididas = aprovadas + negadas
        linhas.append(
            {
                "Vendedor": vendedor,
                "Total": len(grupo),
                "Aprovadas": aprovadas,
                "Negadas": negadas,
                "Em Análise": em_analise,
                "Não Contabilizado": nao_contabilizado,
                "Taxa Aprovação (%)": round(_percentual(aprovadas, decididas), 1),
                "Valor Aprovado (R$)": float(grupo.loc[grupo["_categoria"] == "Aprovado", "VALOR (R$)"].sum()),
            }
        )
    return pd.DataFrame(linhas).sort_values("Total", ascending=False).reset_index(drop=True)
