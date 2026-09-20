"""Calculos do dashboard - tudo em tempo real a partir de CLIENTES e PROPOSTAS,
nada fica salvo na planilha.

Duas camadas neste arquivo. A de cima (`totais_gerais`, `detalhamento_por_status`,
`por_vendedor`) e a original. A de baixo ("Painel") e a do dashboard atual: periodo, numeros do
topo, "Precisa de atencao", funil, por banco, para reenviar, qualidade dos dados, resumo para
copiar e a visao do vendedor. Todas as funcoes do painel recebem DataFrames ja lidos (nunca leem
arquivo) e o dashboard so SINALIZA: nenhuma corrige dado.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Iterable

import pandas as pd

import config
from core import vendedores as vendedores_mod
from core.formatting import dias_do_tempo
from core.propostas import (
    DIAS_PROPOSTA_PARADA,
    ETAPA_APROVADO,
    ETAPA_DESCONHECIDA,
    ETAPA_EFETIVADO,
    ETAPA_EM_ANALISE,
    ETAPA_GARANTIA_ASSINADA,
    ETAPA_NEGADO,
    ETAPA_NF_ANEXADA,
    ETAPA_PRE_APROVADO,
    ETAPA_SEM_STATUS,
    categoria_status,
    eh_aprovado_nao_efetivado,
    eh_efetivado,
    esta_em_aberto,
    etapa_status,
    listar_propostas,
)
from core.validators import apenas_digitos


def _percentual(numerador: float, denominador: float) -> float:
    return (numerador / denominador * 100) if denominador else 0.0


def _nao_efetivadas(status: pd.Series) -> tuple[int, int, float]:
    """(efetivadas, aprovadas nao efetivadas, % nao efetivadas) de uma serie
    de STATUS. A porcentagem e sobre Aprovado + Efetivado - "de tudo que foi
    aprovado, quanto ainda nao virou venda"; 0.0 se nao ha nenhuma das duas."""
    # astype(bool): sem nenhuma proposta (ex.: vendedor recem-cadastrado) o map() devolve uma
    # serie vazia SEM tipo booleano - de texto, quando o STATUS e texto - e a soma dela e ""
    # em vez de 0 (o int("") derrubava o Dashboard, e com ele a janela inteira, pra esse vendedor)
    efetivadas = int(status.map(eh_efetivado).astype(bool).sum())
    nao_efetivadas = int(status.map(eh_aprovado_nao_efetivado).astype(bool).sum())
    return efetivadas, nao_efetivadas, _percentual(nao_efetivadas, nao_efetivadas + efetivadas)


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
    efetivadas, aprovadas_nao_efetivadas, pct_nao_efetivadas = _nao_efetivadas(df["STATUS"])

    return {
        "total_propostas": total,
        # "aprovadas" e a CATEGORIA (Aprovado, Pre-aprovado, Nota Fiscal Anexada,
        # Garantia Assinada e Efetivado) - Efetivado continua dentro dela, entao
        # separar essa etapa nao muda a taxa de aprovacao
        "aprovadas": aprovadas,
        "negadas": negadas,
        "em_analise": em_analise,
        "sem_status": sem_status,
        "nao_identificado": nao_identificado,
        "aprovadas_sem_valor": aprovadas_sem_valor,
        "taxa_aprovacao": _percentual(aprovadas, decididas),
        "taxa_reprovacao": _percentual(negadas, decididas),
        "valor_aprovado": valor_aprovado,
        "efetivadas": efetivadas,
        # status exatamente "Aprovado" (ainda nao virou "Efetivado") e a
        # porcentagem dele sobre Aprovado + Efetivado
        "aprovadas_nao_efetivadas": aprovadas_nao_efetivadas,
        "pct_aprovadas_nao_efetivadas": pct_nao_efetivadas,
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
    "Taxa Aprovação (%)", "Não Efetivadas", "Não Efetivadas (%)", "Valor Aprovado (R$)",
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
        _, nao_efetivadas, pct_nao_efetivadas = _nao_efetivadas(grupo["STATUS"])
        linhas.append(
            {
                "Vendedor": vendedor,
                "Total": len(grupo),
                "Aprovadas": aprovadas,
                "Negadas": negadas,
                "Em Análise": em_analise,
                "Não Contabilizado": nao_contabilizado,
                "Taxa Aprovação (%)": round(_percentual(aprovadas, decididas), 1),
                "Não Efetivadas": nao_efetivadas,
                "Não Efetivadas (%)": round(pct_nao_efetivadas, 1),
                "Valor Aprovado (R$)": float(grupo.loc[grupo["_categoria"] == "Aprovado", "VALOR (R$)"].sum()),
            }
        )
    return pd.DataFrame(linhas).sort_values("Total", ascending=False).reset_index(drop=True)


# =============================================================================================
# Painel (Etapa 2)
# =============================================================================================

# -- periodo ---------------------------------------------------------------------------------

PERIODO_HOJE = "hoje"
PERIODO_7_DIAS = "7d"
PERIODO_30_DIAS = "30d"
PERIODO_MES = "mes"
PERIODO_TUDO = "tudo"
# (chave, rotulo) na ordem em que a tela mostra
PERIODOS = [
    (PERIODO_HOJE, "Hoje"),
    (PERIODO_7_DIAS, "7 dias"),
    (PERIODO_30_DIAS, "30 dias"),
    (PERIODO_MES, "Mês"),
    (PERIODO_TUDO, "Tudo"),
]
PERIODO_PADRAO = PERIODO_TUDO

_DESCRICAO_DO_PERIODO = {
    PERIODO_HOJE: "hoje",
    PERIODO_7_DIAS: "nos últimos 7 dias",
    PERIODO_30_DIAS: "nos últimos 30 dias",
    PERIODO_MES: "neste mês",
    PERIODO_TUDO: "",
}
_DESCRICAO_DO_ANTERIOR = {
    PERIODO_HOJE: "ontem",
    PERIODO_7_DIAS: "os 7 dias anteriores",
    PERIODO_30_DIAS: "os 30 dias anteriores",
    PERIODO_MES: "o mês anterior",
}


def _dia(data) -> pd.Timestamp:
    return pd.Timestamp(data).normalize()


def intervalo_do_periodo(periodo: str, hoje: date | None = None) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """(inicio, fim) do periodo, com as duas pontas INCLUIDAS ("7 dias" = hoje e os 6 anteriores);
    None em "Tudo" (sem filtro)."""
    dia = _dia(hoje or date.today())
    if periodo == PERIODO_TUDO:
        return None
    if periodo == PERIODO_HOJE:
        return dia, dia
    if periodo == PERIODO_7_DIAS:
        return dia - pd.Timedelta(days=6), dia
    if periodo == PERIODO_30_DIAS:
        return dia - pd.Timedelta(days=29), dia
    if periodo == PERIODO_MES:
        return dia.replace(day=1), dia
    raise ValueError(f"Período desconhecido: {periodo!r}")


def intervalo_anterior(periodo: str, hoje: date | None = None) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """O periodo de mesmo tamanho logo antes do atual (Hoje -> ontem; 7 dias -> os 7 anteriores). "Mes"
    compara com o mes anterior ATE O MESMO DIA (10 dias de um mes contra 10 do outro, nunca contra o
    mes inteiro). None em "Tudo": nao ha o que comparar."""
    atual = intervalo_do_periodo(periodo, hoje)
    if atual is None:
        return None
    inicio, fim = atual
    if periodo == PERIODO_MES:
        fim_do_mes_anterior = inicio - pd.Timedelta(days=1)
        inicio_anterior = fim_do_mes_anterior.replace(day=1)
        return inicio_anterior, inicio_anterior.replace(day=min(fim.day, fim_do_mes_anterior.day))
    dias = (fim - inicio).days + 1
    return inicio - pd.Timedelta(days=dias), inicio - pd.Timedelta(days=1)


def descricao_do_periodo(periodo: str) -> str:
    """"hoje", "nos ultimos 7 dias"... ("" em Tudo): pra completar uma frase."""
    return _DESCRICAO_DO_PERIODO[periodo]


def descricao_do_periodo_anterior(periodo: str) -> str:
    return _DESCRICAO_DO_ANTERIOR.get(periodo, "")


def filtrar_por_periodo(propostas: pd.DataFrame, intervalo: tuple[pd.Timestamp, pd.Timestamp] | None) -> pd.DataFrame:
    """As propostas cuja DATA cai no `intervalo` (pontas incluidas). Sem intervalo, todas; proposta sem
    data nunca entra num periodo (como no filtro de Todas as Propostas)."""
    if intervalo is None or propostas.empty:
        return propostas
    datas = pd.to_datetime(propostas["DATA"], errors="coerce").dt.normalize()
    return propostas[(datas >= intervalo[0]) & (datas <= intervalo[1])]


# -- numeros do topo ------------------------------------------------------------------------


def _valores(propostas: pd.DataFrame) -> pd.Series:
    return pd.to_numeric(propostas["VALOR (R$)"], errors="coerce")


def _texto_normalizado(serie: pd.Series) -> pd.Series:
    """Texto sem espacos nas pontas e em maiusculas ("Hubcred BV" e "HUBCRED BV" viram a mesma coisa)."""
    return serie.fillna("").astype(str).str.strip().str.upper()


def indicadores_do_topo(propostas: pd.DataFrame) -> dict:
    """Os quatro numeros do topo do dashboard:
    - em_analise: quantas, a soma dos valores e quantas TEM valor (o resto nao entra na soma);
    - a_efetivar: as de status exatamente "Aprovado" (aprovadas que ainda nao viraram compra) e
      quantas ja foram efetivadas - o que mostra se o processo termina;
    - taxa_aprovacao: aprovadas (todas as etapas positivas) sobre as DECIDIDAS (aprovadas + negadas);
    - valor_mediano: a mediana dos valores preenchidos (a soma engana quando ha valores de teste ou
      atipicos) e quantas propostas tem valor."""
    etapas = propostas["STATUS"].map(etapa_status)
    categoria = propostas["STATUS"].map(categoria_status)
    valores = _valores(propostas)

    em_analise = etapas == ETAPA_EM_ANALISE
    aprovadas = int((categoria == "Aprovado").sum())
    negadas = int((categoria == "Negado").sum())
    decididas = aprovadas + negadas
    com_valor = valores.dropna()
    return {
        "total": len(propostas),
        "em_analise": {
            "quantidade": int(em_analise.sum()),
            "valor": float(valores[em_analise].sum()),
            "com_valor": int(valores[em_analise].notna().sum()),
        },
        "a_efetivar": {
            "quantidade": int((etapas == ETAPA_APROVADO).sum()),
            "efetivadas": int((etapas == ETAPA_EFETIVADO).sum()),
        },
        "taxa_aprovacao": {
            "aprovadas": aprovadas,
            "decididas": decididas,
            "percentual": (aprovadas / decididas * 100) if decididas else None,
        },
        "valor_mediano": {
            "mediana": float(com_valor.median()) if len(com_valor) else None,
            "com_valor": len(com_valor),
            "total": len(propostas),
        },
    }


def comparar_periodos(atual: dict, anterior: dict) -> dict | None:
    """A diferenca de cada numero do topo contra o periodo anterior, ou None se nao da pra comparar
    (um dos dois periodos sem nenhuma proposta). Cada item e None quando ele especifico nao
    e comparavel (ex.: taxa sem nenhuma proposta decidida num dos lados). Positivo = subiu."""
    if not atual["total"] or not anterior["total"]:
        return None

    def _diferenca(a, b):
        return None if a is None or b is None else a - b

    mediana_atual, mediana_anterior = atual["valor_mediano"]["mediana"], anterior["valor_mediano"]["mediana"]
    variacao_da_mediana = None
    if mediana_atual is not None and mediana_anterior:
        variacao_da_mediana = (mediana_atual - mediana_anterior) / mediana_anterior * 100
    return {
        "em_analise": atual["em_analise"]["quantidade"] - anterior["em_analise"]["quantidade"],
        "a_efetivar": atual["a_efetivar"]["quantidade"] - anterior["a_efetivar"]["quantidade"],
        "taxa_aprovacao": _diferenca(atual["taxa_aprovacao"]["percentual"], anterior["taxa_aprovacao"]["percentual"]),
        "valor_mediano": variacao_da_mediana,
    }


# -- precisa de atencao (e os filtros que os itens abrem em Todas as Propostas) ---------------

ATENCAO_PARADAS = "paradas"
ATENCAO_A_EFETIVAR = "a_efetivar"
ATENCAO_SEM_VALOR = "sem_valor"
ATENCAO_DUPLICADAS = "duplicadas"
ATENCAO_DATA_ESTRANHA = "data_estranha"
ATENCOES_EM_ORDEM = [ATENCAO_PARADAS, ATENCAO_A_EFETIVAR, ATENCAO_SEM_VALOR, ATENCAO_DUPLICADAS, ATENCAO_DATA_ESTRANHA]

TOM_PROCESSO = "processo"  # o que esta parado no fluxo (amber)
TOM_DADOS = "dados"  # o que esta errado ou faltando no cadastro

FILTRO_ETAPA = "etapa"
FILTRO_BANCO = "banco"
FILTRO_SEM_MESES = "sem_meses"
FILTRO_SEM_BANCO = "sem_banco"
FILTRO_SEM_STATUS = "sem_status"

DATA_MINIMA_PLAUSIVEL = pd.Timestamp(2020, 1, 1)  # antes disso, quase certamente erro de digitacao
MAXIMO_DE_DIAS_NO_FUTURO = 365


@dataclass(frozen=True)
class FiltroDoDashboard:
    """O pedido "abra Todas as Propostas so com isto": qual grupo (`chave`, uma das ATENCAO_*,
    FILTRO_* ou "etapa"/"banco" com o `parametro`), como se chama o filtro na tela (`rotulo`) e o periodo
    escolhido no dashboard (que a tela aplica nos campos de data dela). Quem calcula QUAIS
    propostas sao e `indices_do_filtro` - sempre a partir das propostas de agora, entao o filtro
    continua certo depois de uma edicao."""

    chave: str
    rotulo: str
    parametro: str = ""
    dias: int | None = None
    periodo_de: pd.Timestamp | None = None
    periodo_ate: pd.Timestamp | None = None


@dataclass(frozen=True)
class ItemDeAtencao:
    chave: str
    tom: str
    quantidade: int
    texto: str  # "31 propostas em aberto há mais de 7 dias"
    rotulo_do_filtro: str  # "Em aberto há mais de 7 dias"
    indices: tuple[int, ...]


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _datas(propostas: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(propostas["DATA"], errors="coerce").dt.normalize()


def _indices(propostas: pd.DataFrame, mascara: pd.Series) -> list[int]:
    return [int(i) for i in propostas.index[mascara.astype(bool).to_numpy()]]


def _indices_de_atencao(propostas: pd.DataFrame, chave: str, dias: int, hoje: date | None) -> list[int]:
    """As propostas (posicao real no arquivo) de cada grupo de "Precisa de atencao"."""
    if propostas.empty:
        return []
    if chave == ATENCAO_PARADAS:
        em_aberto = propostas["STATUS"].map(esta_em_aberto).astype(bool)
        dias_parada = pd.to_numeric(propostas["TEMPO"].map(dias_do_tempo), errors="coerce")
        return _indices(propostas, em_aberto & (dias_parada > dias))
    if chave == ATENCAO_A_EFETIVAR:
        return _indices(propostas, propostas["STATUS"].map(etapa_status) == ETAPA_APROVADO)
    if chave == ATENCAO_SEM_VALOR:
        return _indices(propostas, _valores(propostas).isna())
    if chave == ATENCAO_DUPLICADAS:
        datas = _datas(propostas)
        cpf = propostas["CPF"].map(apenas_digitos)
        chaves = pd.DataFrame(
            {"cpf": cpf, "equipamento": _texto_normalizado(propostas["EQUIPAMENTO"]), "banco": _texto_normalizado(propostas["BANCO"]), "dia": datas}
        )
        # sem data ou sem CPF nao da pra dizer que e "o mesmo dia"/"o mesmo cliente": nunca acusa
        return _indices(propostas, chaves.duplicated(keep=False) & datas.notna() & (cpf != ""))
    if chave == ATENCAO_DATA_ESTRANHA:
        datas = _datas(propostas)
        limite = _dia(hoje or date.today()) + pd.Timedelta(days=MAXIMO_DE_DIAS_NO_FUTURO)
        return _indices(propostas, datas.notna() & ((datas < DATA_MINIMA_PLAUSIVEL) | (datas > limite)))
    raise ValueError(f"Grupo de atenção desconhecido: {chave!r}")


def precisa_de_atencao(propostas: pd.DataFrame, dias: int | None = None, hoje: date | None = None) -> list[ItemDeAtencao]:
    """Os grupos de propostas que pedem uma olhada, so os que tem alguma (lista vazia = tudo em dia). `dias`:
    ha quantos dias em aberto conta como "parada" (padrao: propostas.DIAS_PROPOSTA_PARADA, o mesmo
    do selo da barra lateral)."""
    if dias is None:
        dias = DIAS_PROPOSTA_PARADA
    definicoes = {
        ATENCAO_PARADAS: (TOM_PROCESSO, lambda n: _plural(n, "proposta", "propostas") + f" em aberto há mais de {dias} dias", f"Em aberto há mais de {dias} dias"),
        ATENCAO_A_EFETIVAR: (TOM_PROCESSO, lambda n: _plural(n, "proposta aprovada", "propostas aprovadas") + " ainda sem efetivar", "Aprovadas ainda sem efetivar"),
        ATENCAO_SEM_VALOR: (TOM_DADOS, lambda n: _plural(n, "proposta", "propostas") + " sem valor", "Sem valor preenchido"),
        ATENCAO_DUPLICADAS: (TOM_DADOS, lambda n: _plural(n, "proposta", "propostas") + " que parecem duplicadas", "Parecem duplicadas"),
        ATENCAO_DATA_ESTRANHA: (TOM_DADOS, lambda n: _plural(n, "proposta", "propostas") + " com data fora do padrão", "Data fora do padrão"),
    }
    itens = []
    for chave in ATENCOES_EM_ORDEM:
        indices = _indices_de_atencao(propostas, chave, dias, hoje)
        if indices:
            tom, texto, rotulo = definicoes[chave]
            itens.append(ItemDeAtencao(chave, tom, len(indices), texto(len(indices)), rotulo, tuple(indices)))
    return itens


def rotulo_do_filtro_de_etapa(etapa: str) -> str:
    return f"Etapa: {ROTULOS_DE_ETAPA[etapa]}"


def indices_do_filtro(propostas: pd.DataFrame, filtro: FiltroDoDashboard, hoje: date | None = None) -> set[int]:
    """As propostas (posicao real no arquivo) que o `filtro` do dashboard escolhe. NAO aplica o periodo:
    Todas as Propostas ja filtra por data nos proprios campos."""
    chave = filtro.chave
    if chave in ATENCOES_EM_ORDEM:
        return set(_indices_de_atencao(propostas, chave, filtro.dias or DIAS_PROPOSTA_PARADA, hoje))
    if propostas.empty:
        if chave in (FILTRO_ETAPA, FILTRO_BANCO, FILTRO_SEM_MESES, FILTRO_SEM_BANCO, FILTRO_SEM_STATUS):
            return set()
        raise ValueError(f"Filtro do dashboard desconhecido: {chave!r}")
    if chave == FILTRO_ETAPA:
        return set(_indices(propostas, propostas["STATUS"].map(etapa_status) == filtro.parametro))
    if chave == FILTRO_BANCO:
        return set(_indices(propostas, _texto_normalizado(propostas["BANCO"]) == filtro.parametro.strip().upper()))
    if chave == FILTRO_SEM_MESES:
        return set(_indices(propostas, pd.to_numeric(propostas["MESES"], errors="coerce").isna()))
    if chave == FILTRO_SEM_BANCO:
        return set(_indices(propostas, _texto_normalizado(propostas["BANCO"]) == ""))
    if chave == FILTRO_SEM_STATUS:
        return set(_indices(propostas, _texto_normalizado(propostas["STATUS"]) == ""))
    raise ValueError(f"Filtro do dashboard desconhecido: {chave!r}")


# -- funil por etapa ---------------------------------------------------------------------------

ROTULOS_DE_ETAPA = {
    ETAPA_EM_ANALISE: "Em análise",
    ETAPA_PRE_APROVADO: "Pré-aprovado",
    ETAPA_APROVADO: "Aprovado",
    ETAPA_NF_ANEXADA: "Nota fiscal",
    ETAPA_GARANTIA_ASSINADA: "Garantia",
    ETAPA_EFETIVADO: "Efetivado",
    ETAPA_NEGADO: "Negado",
    ETAPA_SEM_STATUS: "Sem status",
    ETAPA_DESCONHECIDA: "Status não reconhecido",
}
ETAPAS_DO_FUNIL = [
    ETAPA_EM_ANALISE,
    ETAPA_PRE_APROVADO,
    ETAPA_APROVADO,
    ETAPA_NF_ANEXADA,
    ETAPA_GARANTIA_ASSINADA,
    ETAPA_EFETIVADO,
]


@dataclass(frozen=True)
class EtapaDoFunil:
    etapa: str
    rotulo: str
    quantidade: int
    valor: float  # soma dos valores PREENCHIDOS
    com_valor: int


def funil_por_etapa(propostas: pd.DataFrame) -> list[EtapaDoFunil]:
    """Uma linha por etapa do funil (em ordem), depois "Negado" (que fica separado: sair do funil nao e
    uma etapa dele). "Sem status" e "Status nao reconhecido" so aparecem se houver alguma - uma proposta
    que nao se encaixa nao pode sumir da conta."""
    etapas = propostas["STATUS"].map(etapa_status)
    valores = _valores(propostas)

    def _linha(etapa: str) -> EtapaDoFunil:
        da_etapa = etapas == etapa
        return EtapaDoFunil(
            etapa, ROTULOS_DE_ETAPA[etapa], int(da_etapa.sum()), float(valores[da_etapa].sum()), int(valores[da_etapa].notna().sum())
        )

    linhas = [_linha(e) for e in ETAPAS_DO_FUNIL + [ETAPA_NEGADO]]
    linhas += [l for l in (_linha(ETAPA_SEM_STATUS), _linha(ETAPA_DESCONHECIDA)) if l.quantidade]
    return linhas


# -- por banco ---------------------------------------------------------------------------------

COLUNAS_POR_BANCO = ["Banco", "Enviadas", "Aprovadas", "Negadas", "Em Análise", "Taxa (%)", "Aviso"]
ROTULO_SEM_BANCO = "(sem banco)"
AVISO_SEM_APROVACAO = "sem_aprovacao"
AVISO_NAO_E_BANCO = "nao_e_banco"
AVISO_SEM_BANCO = "sem_banco"
# o que cada aviso quer dizer, pra tela mostrar (mesmo texto no tooltip)
TEXTO_DO_AVISO_DE_BANCO = {
    AVISO_SEM_APROVACAO: "Muitas propostas e nenhuma aprovada",
    AVISO_NAO_E_BANCO: "Revisar: \"Todos\" não é um banco (fica fora da taxa)",
    AVISO_SEM_BANCO: "Revisar: proposta sem banco informado (fica fora da taxa)",
}
# "Todos" ja foi digitado como se fosse um banco (uma proposta pra varios): nao e, e nao entra em taxa nenhuma
NAO_SAO_BANCO = {"TODOS"}
MINIMO_PARA_ALERTA_DE_BANCO = 5  # a partir de quantas propostas sem nenhuma aprovada o banco e sinalizado


def _grafia_mais_usada(textos: Iterable[str]) -> str:
    """A grafia mais usada entre as que so diferem em maiusculas/espacos; no empate, a primeira em
    ordem alfabetica (costuma ser a em maiusculas) - a mesma regra do filtro de bancos."""
    contagem = Counter(t.strip() for t in textos if isinstance(t, str) and t.strip())
    return min(contagem, key=lambda t: (-contagem[t], t))


def por_banco(propostas: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por banco (grafias que so diferem em maiusculas/espacos viram UMA): quantas propostas
    foram enviadas, aprovadas (todas as etapas positivas), negadas, em analise e a taxa
    (aprovadas / (aprovadas + negadas)). Fica em `Aviso` o que pede atencao:
    banco com muitas propostas e nenhuma aprovada, "Todos" (nao e um banco) e proposta sem banco - estes
    dois ficam FORA da taxa (Taxa (%) vazia). Ordem: mais enviadas primeiro."""
    if propostas.empty:
        return pd.DataFrame(columns=COLUNAS_POR_BANCO)

    chaves = _texto_normalizado(propostas["BANCO"])
    categoria = propostas["STATUS"].map(categoria_status)
    linhas = []
    for chave in sorted(set(chaves)):
        do_banco = chaves == chave
        aprovadas = int(((categoria == "Aprovado") & do_banco).sum())
        negadas = int(((categoria == "Negado") & do_banco).sum())
        em_analise = int(((categoria == "Em Análise") & do_banco).sum())
        enviadas = int(do_banco.sum())
        aviso = ""
        if chave == "":
            nome, aviso = ROTULO_SEM_BANCO, AVISO_SEM_BANCO
        elif chave in NAO_SAO_BANCO:
            nome, aviso = _grafia_mais_usada(propostas.loc[do_banco, "BANCO"]), AVISO_NAO_E_BANCO
        else:
            nome = _grafia_mais_usada(propostas.loc[do_banco, "BANCO"])
            if enviadas >= MINIMO_PARA_ALERTA_DE_BANCO and aprovadas == 0:
                aviso = AVISO_SEM_APROVACAO
        decididas = aprovadas + negadas
        taxa = None if aviso in (AVISO_SEM_BANCO, AVISO_NAO_E_BANCO) or not decididas else round(aprovadas / decididas * 100, 1)
        linhas.append(
            {"Banco": nome, "Enviadas": enviadas, "Aprovadas": aprovadas, "Negadas": negadas, "Em Análise": em_analise, "Taxa (%)": taxa, "Aviso": aviso}
        )
    return pd.DataFrame(linhas, columns=COLUNAS_POR_BANCO).sort_values(["Enviadas", "Banco"], ascending=[False, True]).reset_index(drop=True)


def chave_do_banco(nome_exibido: str) -> str:
    """O `parametro` do FILTRO_BANCO de uma linha de `por_banco` ("" = proposta sem banco)."""
    return "" if nome_exibido == ROTULO_SEM_BANCO else nome_exibido.strip().upper()


# -- para reenviar -------------------------------------------------------------------------------


@dataclass(frozen=True)
class ClienteParaReenviar:
    cpf: str
    cliente: str
    cadastrado: bool  # False: ha propostas com este CPF mas nao ha cliente cadastrado (nao da pra abrir a ficha)
    indice_da_proposta: int  # a mais recente: e dela que "Duplicar" parte
    propostas: int
    bancos_tentados: tuple[str, ...]
    bancos_nao_tentados: tuple[str, ...]
    ultima_data: pd.Timestamp | None


def para_reenviar(
    propostas: pd.DataFrame,
    intervalo: tuple[pd.Timestamp, pd.Timestamp] | None = None,
    bancos_conhecidos: Iterable[str] | None = None,
) -> list[ClienteParaReenviar]:
    """Clientes cujas propostas foram TODAS negadas (olhando o historico inteiro de `propostas`), com os
    bancos ja tentados e os que ainda nao (os conhecidos + os ja usados em qualquer proposta). Com
    `intervalo`, so quem teve a ultima proposta nele. "Todos" nao e banco: nunca entra em nenhuma das duas listas.
    Mais recentes primeiro."""
    if propostas.empty:
        return []
    conhecidos = config.BANCOS_CONHECIDOS if bancos_conhecidos is None else bancos_conhecidos

    chaves = _texto_normalizado(propostas["BANCO"])
    grafias: dict[str, str] = {}
    for chave in set(chaves) - {""} - NAO_SAO_BANCO:
        grafias[chave] = _grafia_mais_usada(propostas.loc[chaves == chave, "BANCO"])
    uso = Counter(c for c in chaves if c and c not in NAO_SAO_BANCO)
    for nome in conhecidos:  # a grafia da lista de config.py e a "oficial": vale sobre a digitada nas propostas
        chave = nome.strip().upper()
        if chave and chave not in NAO_SAO_BANCO:
            grafias[chave] = nome.strip()

    cpfs = propostas["CPF"].map(apenas_digitos)
    etapas = propostas["STATUS"].map(etapa_status)
    datas = pd.to_datetime(propostas["DATA"], errors="coerce")
    resultado = []
    for cpf in sorted(set(cpfs) - {""}):
        do_cliente = cpfs == cpf
        if not (etapas[do_cliente] == ETAPA_NEGADO).all():
            continue
        # a mais recente por DATA; no empate (mesmo dia) a que esta mais abaixo no arquivo (lancada depois)
        ordem = (
            propostas[do_cliente]
            .assign(_data=datas[do_cliente])
            .sort_index(ascending=False)
            .sort_values("_data", ascending=False, na_position="last", kind="stable")
        )
        mais_recente = ordem.iloc[0]
        ultima_data = mais_recente["_data"] if pd.notna(mais_recente["_data"]) else None
        if intervalo is not None and (ultima_data is None or not (intervalo[0] <= _dia(ultima_data) <= intervalo[1])):
            continue
        nome = next((n for n in propostas.loc[do_cliente, "CLIENTE"] if isinstance(n, str) and n.strip()), "")
        tentados = sorted({c for c in chaves[do_cliente] if c and c not in NAO_SAO_BANCO})
        nao_tentados = sorted((c for c in grafias if c not in tentados), key=lambda c: (-uso[c], grafias[c]))
        resultado.append(
            ClienteParaReenviar(
                cpf=cpf,
                cliente=nome.strip(),
                cadastrado=bool(nome.strip()),
                indice_da_proposta=int(ordem.index[0]),
                propostas=int(do_cliente.sum()),
                bancos_tentados=tuple(grafias[c] for c in tentados),
                bancos_nao_tentados=tuple(grafias[c] for c in nao_tentados),
                ultima_data=ultima_data,
            )
        )
    return sorted(resultado, key=lambda r: (r.ultima_data is None, -(r.ultima_data.value if r.ultima_data is not None else 0), r.cliente))


# -- qualidade dos dados ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CampoDeQualidade:
    chave: str  # o FILTRO_*/ATENCAO_* que lista as pendentes
    rotulo: str
    preenchidos: int
    total: int
    percentual: float | None  # None: nao ha propostas
    indices_pendentes: tuple[int, ...]


def qualidade_dos_dados(propostas: pd.DataFrame) -> list[CampoDeQualidade]:
    """Quantas propostas tem valor, meses, banco e status preenchidos (e quais nao tem)."""
    total = len(propostas)
    if total:
        faltando = {
            ATENCAO_SEM_VALOR: _valores(propostas).isna(),
            FILTRO_SEM_MESES: pd.to_numeric(propostas["MESES"], errors="coerce").isna(),
            FILTRO_SEM_BANCO: _texto_normalizado(propostas["BANCO"]) == "",
            FILTRO_SEM_STATUS: _texto_normalizado(propostas["STATUS"]) == "",
        }
    campos = []
    for chave, rotulo in ((ATENCAO_SEM_VALOR, "Valor"), (FILTRO_SEM_MESES, "Meses"), (FILTRO_SEM_BANCO, "Banco"), (FILTRO_SEM_STATUS, "Status")):
        pendentes = _indices(propostas, faltando[chave]) if total else []
        campos.append(
            CampoDeQualidade(
                chave, rotulo, total - len(pendentes), total, ((total - len(pendentes)) / total * 100) if total else None, tuple(pendentes)
            )
        )
    return campos


# -- resumo para copiar --------------------------------------------------------------------------


def resumo_para_copiar(propostas: pd.DataFrame, periodo: str = PERIODO_TUDO) -> str:
    """Uma frase pronta pra colar numa conversa: "59 propostas: 21 em análise, 11 aprovadas (0 efetivadas),
    26 negadas e 1 sem status." Com periodo: "12 propostas nos últimos 7 dias: ..."."""
    quando = descricao_do_periodo(periodo)
    if propostas.empty:
        return f"Nenhuma proposta {quando}.".replace(" .", ".")

    etapas = propostas["STATUS"].map(etapa_status)
    categoria = propostas["STATUS"].map(categoria_status)
    em_analise = int((categoria == "Em Análise").sum())
    aprovadas = int((categoria == "Aprovado").sum())
    efetivadas = int((etapas == ETAPA_EFETIVADO).sum())
    negadas = int((categoria == "Negado").sum())
    sem_status = int((etapas == ETAPA_SEM_STATUS).sum())
    desconhecidas = int((etapas == ETAPA_DESCONHECIDA).sum())

    partes = []
    if em_analise:
        partes.append(f"{em_analise} em análise")
    if aprovadas:
        partes.append(f"{aprovadas} {'aprovada' if aprovadas == 1 else 'aprovadas'} ({_plural(efetivadas, 'efetivada', 'efetivadas')})")
    if negadas:
        partes.append(f"{negadas} {'negada' if negadas == 1 else 'negadas'}")
    if sem_status:
        partes.append(f"{sem_status} sem status")
    if desconhecidas:
        partes.append(f"{desconhecidas} com status não reconhecido")
    lista = partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " e " + partes[-1]
    return f"{_plural(len(propostas), 'proposta', 'propostas')}{' ' + quando if quando else ''}: {lista}."


# -- visao do vendedor ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PropostaResumida:
    indice: int
    cpf: str
    cliente: str
    equipamento: str
    banco: str
    valor: float | None
    tempo: str  # a coluna TEMPO como esta ("12 dias")
    dias: int | None


def propostas_da_etapa(propostas: pd.DataFrame, etapa: str) -> list[PropostaResumida]:
    """As propostas da `etapa`, as mais paradas primeiro (as sem dias calculaveis por ultimo)."""
    if propostas.empty:
        return []
    da_etapa = propostas[propostas["STATUS"].map(etapa_status) == etapa]
    itens = []
    for indice, p in da_etapa.iterrows():
        valor = pd.to_numeric(p["VALOR (R$)"], errors="coerce")
        tempo = p["TEMPO"] if isinstance(p["TEMPO"], str) else ""
        itens.append(
            PropostaResumida(
                indice=int(indice),
                cpf=p["CPF"] if isinstance(p["CPF"], str) else "",
                cliente=p["CLIENTE"] if isinstance(p["CLIENTE"], str) else "",
                equipamento=p["EQUIPAMENTO"] if isinstance(p["EQUIPAMENTO"], str) else "",
                banco=p["BANCO"] if isinstance(p["BANCO"], str) else "",
                valor=None if pd.isna(valor) else float(valor),
                tempo=tempo,
                dias=dias_do_tempo(tempo),
            )
        )
    return sorted(itens, key=lambda i: (i.dias is None, -(i.dias or 0), i.cliente))


def clientes_sem_proposta(clientes: pd.DataFrame, propostas: pd.DataFrame) -> list[tuple[str, str]]:
    """(cpf, nome) dos clientes que nao tem nenhuma proposta em `propostas`, em ordem alfabetica."""
    if clientes.empty:
        return []
    com_proposta = set(propostas["CPF"].map(apenas_digitos)) if not propostas.empty else set()
    sem = [
        (cpf, nome)
        for cpf, nome in zip(clientes["CPF/CNPJ"], clientes["CLIENTE"])
        if apenas_digitos(cpf) not in com_proposta
    ]
    return sorted(sem, key=lambda par: par[1].upper())
