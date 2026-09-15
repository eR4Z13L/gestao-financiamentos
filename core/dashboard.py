"""Calculos do dashboard - tudo em tempo real a partir de CLIENTES e PROPOSTAS,
nada fica salvo na planilha.
"""

from __future__ import annotations

import pandas as pd

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
    decididas = aprovadas + negadas
    valor_aprovado = float(df.loc[categoria == "Aprovado", "VALOR (R$)"].sum())

    return {
        "total_propostas": total,
        "aprovadas": aprovadas,
        "negadas": negadas,
        "em_analise": em_analise,
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
    ordem_categoria = {"Aprovado": 0, "Em Análise": 1, "Negado": 2, "Não contabilizado": 3}
    agrupado["_ordem"] = agrupado["Categoria"].map(ordem_categoria).fillna(3)
    agrupado = agrupado.sort_values(["_ordem", "Quantidade"], ascending=[True, False])
    return agrupado[["STATUS", "Categoria", "Quantidade", "Valor (R$)"]].reset_index(drop=True)


def por_vendedor(propostas: pd.DataFrame | None = None) -> pd.DataFrame:
    df = propostas if propostas is not None else listar_propostas()
    if df.empty:
        return pd.DataFrame(
            columns=["Vendedor", "Total", "Aprovadas", "Negadas", "Em Análise", "Taxa Aprovação (%)", "Valor Aprovado (R$)"]
        )

    df = df.assign(_categoria=df["STATUS"].map(categoria_status))
    linhas = []
    for vendedor, grupo in df.groupby("VENDEDOR"):
        aprovadas = int((grupo["_categoria"] == "Aprovado").sum())
        negadas = int((grupo["_categoria"] == "Negado").sum())
        em_analise = int((grupo["_categoria"] == "Em Análise").sum())
        decididas = aprovadas + negadas
        linhas.append(
            {
                "Vendedor": vendedor or "(sem vendedor)",
                "Total": len(grupo),
                "Aprovadas": aprovadas,
                "Negadas": negadas,
                "Em Análise": em_analise,
                "Taxa Aprovação (%)": round(_percentual(aprovadas, decididas), 1),
                "Valor Aprovado (R$)": float(grupo.loc[grupo["_categoria"] == "Aprovado", "VALOR (R$)"].sum()),
            }
        )
    return pd.DataFrame(linhas).sort_values("Total", ascending=False).reset_index(drop=True)
