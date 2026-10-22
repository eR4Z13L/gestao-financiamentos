"""Calculos do dashboard - tudo em tempo real a partir de CLIENTES e PROPOSTAS,
nada fica salvo na planilha.

Duas camadas neste arquivo. A de cima (`totais_gerais`, `detalhamento_por_status`,
`por_vendedor`) e a original: nao aparecem mais no Dashboard do ADMIN e ficam para o modo vendedor e para os
testes de regra (a efetivar, taxa) que as usam. A de baixo ("Painel") e a do dashboard atual: periodo, os 4 numeros das
VENDAS (o momento de agora), por banco (com a demora para responder), resumo para copiar, os filtros que
Todas as Propostas aceita e a visao do vendedor. Todas as funcoes do painel recebem dados ja lidos (nunca
leem arquivo) e o dashboard so SINALIZA: nenhuma corrige dado.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Iterable

import pandas as pd

from core import vendas as vendas_mod
from core import vendedores as vendedores_mod
from core.formatting import dias_do_tempo, formatar_reais
from core import propostas as propostas_mod
from core.propostas import (
    ETAPA_APROVADO,
    ETAPA_DESCONHECIDA,
    ETAPA_EFETIVADO,
    ETAPA_EM_ANALISE,
    ETAPA_GARANTIA_ASSINADA,
    ETAPA_NAO_EFETIVADO,
    ETAPA_NEGADO,
    ETAPA_NF_ANEXADA,
    ETAPA_PRE_APROVADO,
    ETAPA_PROPOSTA_ENCERRADA,
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


def _nao_efetivadas(status: pd.Series, fora_do_fluxo: pd.Series | None = None) -> tuple[int, int, float]:
    """(efetivadas, aprovadas nao efetivadas, % nao efetivadas) de uma serie
    de STATUS. A porcentagem e sobre Aprovado + Efetivado - "de tudo que foi
    aprovado, quanto ainda nao virou venda"; 0.0 se nao ha nenhuma das duas.

    ATENCAO AO NOME: "aprovadas nao efetivadas" aqui e quem ainda esta com o
    status "Aprovado" (PENDENTE, ainda pode virar venda) - eh_aprovado_nao_efetivado().
    Isso e DIFERENTE do status "Não efetivado" (core.propostas.STATUS_NAO_EFETIVADO),
    que e um desfecho FINAL (o cliente ja desistiu). Os dois nomes parecidos existem
    porque esta metrica e mais antiga que aquele status - ver eh_nao_efetivado()."""
    # astype(bool): sem nenhuma proposta (ex.: vendedor recem-cadastrado) o map() devolve uma
    # serie vazia SEM tipo booleano - de texto, quando o STATUS e texto - e a soma dela e ""
    # em vez de 0 (o int("") derrubava o Dashboard, e com ele a janela inteira, pra esse vendedor)
    efetivadas = int(status.map(eh_efetivado).astype(bool).sum())
    pendentes = status.map(eh_aprovado_nao_efetivado).astype(bool)
    if fora_do_fluxo is not None:  # a proposta numa venda ja resolvida (Efetivada, Perdida...) nao esta "a efetivar"
        pendentes = pendentes & ~fora_do_fluxo
    nao_efetivadas = int(pendentes.sum())
    return efetivadas, nao_efetivadas, _percentual(nao_efetivadas, nao_efetivadas + efetivadas)


def totais_gerais(propostas: pd.DataFrame | None = None) -> dict:
    df = propostas if propostas is not None else listar_propostas()
    categoria = df["STATUS"].map(categoria_status)

    total = len(df)
    aprovadas = int((categoria == "Aprovado").sum())
    negadas = int((categoria == "Negado").sum())
    em_analise = int((categoria == "Em Análise").sum())
    # propostas que NAO entram em nenhum dos cards acima: status em branco
    # ("sem_status"), status preenchido mas desconhecido/mal digitado
    # ("nao_identificado") ou "Encerrada" (fechada por causa de outra proposta
    # da mesma venda, sem ter sido decidida por este banco) - separados pra
    # tela poder explicar a diferenca em vez de so deixar o total "nao bater"
    # com a soma dos cards.
    sem_status = int((categoria == "").sum())
    nao_identificado = int((categoria == "Não identificado").sum())
    encerradas = int((categoria == "Encerrada").sum())
    decididas = aprovadas + negadas
    # soma com skipna (padrao do pandas) ja ignora VALOR ausente em vez de
    # tratar como R$0 - mas isso e invisivel pra quem olha so o numero final,
    # entao contamos separado pra tela poder avisar que o "Valor total
    # aprovado" pode estar subestimado (nao esta errado, so incompleto).
    aprovadas_sem_valor = int(((categoria == "Aprovado") & df["VALOR (R$)"].isna()).sum())
    valor_aprovado = float(df.loc[categoria == "Aprovado", "VALOR (R$)"].sum())
    efetivadas, aprovadas_nao_efetivadas, pct_nao_efetivadas = _nao_efetivadas(df["STATUS"], propostas_mod.fora_do_fluxo(df))

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
        "encerradas": encerradas,
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
        _, nao_efetivadas, pct_nao_efetivadas = _nao_efetivadas(grupo["STATUS"], propostas_mod.fora_do_fluxo(grupo))
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


def descricao_do_periodo(periodo: str) -> str:
    """"hoje", "nos ultimos 7 dias"... ("" em Tudo): pra completar uma frase."""
    return _DESCRICAO_DO_PERIODO[periodo]


def filtrar_por_periodo(propostas: pd.DataFrame, intervalo: tuple[pd.Timestamp, pd.Timestamp] | None) -> pd.DataFrame:
    """As propostas cuja DATA cai no `intervalo` (pontas incluidas). Sem intervalo, todas; proposta sem
    data nunca entra num periodo (como no filtro de Todas as Propostas)."""
    if intervalo is None or propostas.empty:
        return propostas
    datas = pd.to_datetime(propostas["DATA"], errors="coerce").dt.normalize()
    return propostas[(datas >= intervalo[0]) & (datas <= intervalo[1])]


# -- utilitarios ----------------------------------------------------------------------------


def _valores(propostas: pd.DataFrame) -> pd.Series:
    return pd.to_numeric(propostas["VALOR (R$)"], errors="coerce")


def _texto_normalizado(serie: pd.Series) -> pd.Series:
    """Texto sem espacos nas pontas e em maiusculas ("Hubcred BV" e "HUBCRED BV" viram a mesma coisa)."""
    return serie.fillna("").astype(str).str.strip().str.upper()


# -- os filtros que o Dashboard abre em Todas as Propostas (e a regra de cada grupo) ---------

ATENCAO_PARADAS = "paradas"
ATENCAO_A_EFETIVAR = "a_efetivar"
ATENCAO_MESMA_VENDA = "mesma_venda"
ATENCAO_SEM_VALOR = "sem_valor"
ATENCAO_DUPLICADAS = "duplicadas"
ATENCAO_DATA_ESTRANHA = "data_estranha"
ATENCOES_EM_ORDEM = [
    ATENCAO_PARADAS,
    ATENCAO_A_EFETIVAR,
    ATENCAO_MESMA_VENDA,
    ATENCAO_SEM_VALOR,
    ATENCAO_DUPLICADAS,
    ATENCAO_DATA_ESTRANHA,
]

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
        # (a proposta numa venda ja resolvida nao entra: a venda diz o que falta - o mesmo do selo da barra lateral)
        em_aberto = propostas["STATUS"].map(esta_em_aberto).astype(bool) & ~propostas_mod.fora_do_fluxo(propostas)
        dias_parada = pd.to_numeric(propostas["TEMPO"].map(dias_do_tempo), errors="coerce")
        return _indices(propostas, em_aberto & (dias_parada > dias))
    if chave == ATENCAO_A_EFETIVAR:
        return _indices(propostas, (propostas["STATUS"].map(etapa_status) == ETAPA_APROVADO) & ~propostas_mod.fora_do_fluxo(propostas))
    if chave == ATENCAO_MESMA_VENDA:
        # propostas AINDA em aberto de um cliente+equipamento onde OUTRA proposta ja foi
        # efetivada (a mesma venda, fechada por outro banco) - candidatas a "Encerrada"
        # que ninguem encerrou ainda (a pergunta ao efetivar foi respondida "não", ou a
        # proposta nem existia naquele momento). Nunca mexe sozinho: so sinaliza. So vale para a proposta SEM venda: numa
        # venda, quem resolve isso e a propria venda (os bancos fechados dela).
        cpf = propostas["CPF"].map(apenas_digitos)
        equipamento = _texto_normalizado(propostas["EQUIPAMENTO"])
        em_aberto = propostas["STATUS"].map(esta_em_aberto).astype(bool) & ~propostas_mod.numa_venda(propostas)
        efetivada = propostas["STATUS"].map(eh_efetivado).astype(bool)
        valido = (cpf != "") & (equipamento != "")
        tem_efetivada_no_grupo = efetivada.groupby([cpf, equipamento]).transform("any")
        return _indices(propostas, em_aberto & valido & tem_efetivada_no_grupo)
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


def rotulo_do_filtro_de_etapa(etapa: str) -> str:
    return f"Etapa: {ROTULOS_DE_ETAPA[etapa]}"


def indices_do_filtro(propostas: pd.DataFrame, filtro: FiltroDoDashboard, hoje: date | None = None) -> set[int]:
    """As propostas (posicao real no arquivo) que o `filtro` do dashboard escolhe. NAO aplica o periodo:
    Todas as Propostas ja filtra por data nos proprios campos."""
    chave = filtro.chave
    if chave in ATENCOES_EM_ORDEM:
        return set(_indices_de_atencao(propostas, chave, filtro.dias or propostas_mod.DIAS_PROPOSTA_PARADA, hoje))
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


# -- rotulos das etapas (o chip "Etapa: ..." do filtro de etapa) -------------------------------

ROTULOS_DE_ETAPA = {
    ETAPA_EM_ANALISE: "Em análise",
    ETAPA_PRE_APROVADO: "Pré-aprovado",
    ETAPA_APROVADO: "Aprovado",
    ETAPA_NF_ANEXADA: "Nota fiscal",
    ETAPA_GARANTIA_ASSINADA: "Garantia",
    ETAPA_EFETIVADO: "Efetivado",
    ETAPA_NAO_EFETIVADO: "Não efetivado",
    ETAPA_PROPOSTA_ENCERRADA: "Encerrada",
    ETAPA_NEGADO: "Negado",
    ETAPA_SEM_STATUS: "Sem status",
    ETAPA_DESCONHECIDA: "Status não reconhecido",
}
# -- por banco ---------------------------------------------------------------------------------

COLUNAS_POR_BANCO = ["Banco", "Enviadas", "Aprovadas", "Negadas", "Em Análise", "Taxa (%)", "Demora (dias)", "Aviso"]
ROTULO_SEM_BANCO = "(sem banco)"
SUFIXO_BANCO_DIGITADO = " (banco digitado)"  # "Todos" digitado como banco: nao se confunde com a linha "Todos" do rodape
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


def demoras_de_resposta(propostas: pd.DataFrame, historico: pd.DataFrame | None) -> pd.Series:
    """Quantos dias cada proposta levou do envio (a DATA dela) ate a 1a mudanca de status no HISTORICO que tira
    ela de "Em Análise" (a resposta do banco), na mesma ordem de `propostas`. NaN quando nao da pra saber: sem
    HISTORICO, sem ID_PROPOSTA, sem nenhuma resposta ainda (a criacao - DE vazio - nao e resposta; nem uma proposta
    que ja nasceu Aprovada e so depois foi efetivada: aquela mudanca nao e do banco) ou com a mudanca ANTES da DATA
    (data digitada errada: nunca vira demora negativa)."""
    vazio = pd.Series(float("nan"), index=propostas.index, dtype="float64")
    if historico is None or historico.empty or propostas.empty or "ID_PROPOSTA" not in propostas.columns:
        return vazio
    saiu_de_em_analise = historico["DE"].map(etapa_status) == ETAPA_EM_ANALISE
    mudancas = historico[(historico["TIPO"] == vendas_mod.TIPO_PROPOSTA) & saiu_de_em_analise & historico["QUANDO"].notna()]
    if mudancas.empty:
        return vazio
    primeira = mudancas.groupby("ID")["QUANDO"].min().dt.normalize()
    resposta = pd.to_datetime(propostas["ID_PROPOSTA"].map(primeira), errors="coerce")
    envio = pd.to_datetime(propostas["DATA"], errors="coerce").dt.normalize()
    dias = (resposta - envio).dt.days.astype("float64")
    return dias.where(dias >= 0)


def mediana_da_demora(propostas: pd.DataFrame, historico: pd.DataFrame | None) -> float | None:
    """A mediana (metade responde em ate X dias) das demoras que se sabe; None se nenhuma proposta respondeu."""
    dias = demoras_de_resposta(propostas, historico).dropna()
    return float(dias.median()) if len(dias) else None


def texto_da_demora(dias: float | None) -> str:
    """"3 dias", "1 dia", "2,5 dias", "mesmo dia"; "—" sem resposta."""
    if dias is None or pd.isna(dias):
        return "—"
    if dias == 0:
        return "mesmo dia"
    numero = f"{int(dias)}" if float(dias).is_integer() else f"{dias:.1f}".replace(".", ",")
    return f"{numero} {'dia' if dias == 1 else 'dias'}"


def por_banco(propostas: pd.DataFrame, historico: pd.DataFrame | None = None) -> pd.DataFrame:
    """Uma linha por banco (grafias que so diferem em maiusculas/espacos viram UMA): quantas propostas
    foram enviadas, aprovadas (todas as etapas positivas), negadas, em analise, a taxa
    (aprovadas / (aprovadas + negadas)) e a demora para responder (mediana de dias, ver `demoras_de_resposta`;
    None sem HISTORICO ou sem resposta). Fica em `Aviso` o que pede atencao:
    banco com muitas propostas e nenhuma aprovada, "Todos" (nao e um banco) e proposta sem banco - estes
    dois ficam FORA da taxa (Taxa (%) vazia). Ordem: mais enviadas primeiro."""
    if propostas.empty:
        return pd.DataFrame(columns=COLUNAS_POR_BANCO)
    demoras = demoras_de_resposta(propostas, historico)

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
            nome, aviso = _grafia_mais_usada(propostas.loc[do_banco, "BANCO"]) + SUFIXO_BANCO_DIGITADO, AVISO_NAO_E_BANCO
        else:
            nome = _grafia_mais_usada(propostas.loc[do_banco, "BANCO"])
            if enviadas >= MINIMO_PARA_ALERTA_DE_BANCO and aprovadas == 0:
                aviso = AVISO_SEM_APROVACAO
        decididas = aprovadas + negadas
        taxa = None if aviso in (AVISO_SEM_BANCO, AVISO_NAO_E_BANCO) or not decididas else round(aprovadas / decididas * 100, 1)
        da_demora = demoras[do_banco].dropna()
        linhas.append(
            {
                "Banco": nome, "Enviadas": enviadas, "Aprovadas": aprovadas, "Negadas": negadas, "Em Análise": em_analise,
                "Taxa (%)": taxa, "Demora (dias)": float(da_demora.median()) if len(da_demora) else None, "Aviso": aviso,
            }
        )
    return pd.DataFrame(linhas, columns=COLUNAS_POR_BANCO).sort_values(["Enviadas", "Banco"], ascending=[False, True]).reset_index(drop=True)


def chave_do_banco(nome_exibido: str) -> str:
    """O `parametro` do FILTRO_BANCO de uma linha de `por_banco` ("" = proposta sem banco)."""
    if nome_exibido == ROTULO_SEM_BANCO:
        return ""
    return nome_exibido.removesuffix(SUFIXO_BANCO_DIGITADO).strip().upper()


def total_por_banco(propostas: pd.DataFrame, historico: pd.DataFrame | None = None) -> dict:
    """A linha "Todos" do rodape de Por banco: as MESMAS colunas somadas sobre todas as propostas do periodo
    (inclusive as sem banco e o "Todos" digitado - nenhuma proposta fica fora da conta). Taxa None sem decididas."""
    categoria = propostas["STATUS"].map(categoria_status)
    aprovadas = int((categoria == "Aprovado").sum())
    negadas = int((categoria == "Negado").sum())
    decididas = aprovadas + negadas
    return {
        "Enviadas": len(propostas),
        "Aprovadas": aprovadas,
        "Negadas": negadas,
        "Em Análise": int((categoria == "Em Análise").sum()),
        "Taxa (%)": round(aprovadas / decididas * 100, 1) if decididas else None,
        "Demora (dias)": mediana_da_demora(propostas, historico),
    }


# -- os numeros das vendas (o momento de agora) --------------------------------------------------


@dataclass(frozen=True)
class NumerosDasVendas:
    em_andamento: int  # vendas Aguardando bancos ou Em andamento (nem efetivadas nem desistidas)
    valor_em_andamento: float  # soma dos valores dos bancos FECHADOS delas
    fechadas_sem_valor: int  # bancos fechados dessas vendas sem valor (ficam fora da soma)
    paradas: int  # vendas paradas (a regra de ResumoDaVenda.parada: a mesma do filtro "Paradas" da tela Vendas)
    dias_de_parada: int
    efetivadas_no_mes: int
    valor_efetivadas_no_mes: float
    efetivadas_sem_valor: int
    efetivadas_sem_data: int  # Efetivada sem data de quando efetivou (nem historico nem criacao): fica fora do mes
    com_pendencias: int  # vendas (de qualquer status) com pendencia aberta: a mesma regra do filtro "Com pendências"
    com_pendencias_ilegiveis: int  # vendas com a celula de pendencias ilegivel (nao da pra contar as dela)


def _valor_dos_bancos_fechados(venda) -> tuple[float, int]:
    """(soma dos valores, quantos bancos fechados sem valor)."""
    valores = [p.valor for p in venda.bancos_fechados()]
    return float(sum(v for v in valores if v is not None)), sum(1 for v in valores if v is None)


def _datas_de_efetivacao(historico: pd.DataFrame | None) -> dict[str, pd.Timestamp]:
    """Para cada proposta, o dia da ULTIMA vez que ela virou Efetivado, das linhas de TIPO proposta do HISTORICO (a
    conversao dos dados antigos e as linhas de outros tipos nunca contam: nao dizem quando efetivou)."""
    if historico is None or historico.empty:
        return {}
    h = historico[(historico["TIPO"] == vendas_mod.TIPO_PROPOSTA) & (historico["PARA"] == vendas_mod.PROPOSTA_EFETIVADA)
                  & historico["QUANDO"].notna()]
    if h.empty:
        return {}
    return h.groupby("ID")["QUANDO"].max().dt.normalize().to_dict()


def numeros_das_vendas(vendas, hoje: date | None = None, historico: pd.DataFrame | None = None) -> NumerosDasVendas:
    """Os 4 numeros do topo do Dashboard sobre as vendas (`core.vendas.listar_vendas`), do momento de agora - nao
    seguem o seletor de periodo. "Efetivadas no mes" conta a venda Efetivada cuja data de efetivacao cai neste mes:
    a MAIOR data, entre os bancos fechados dela, da linha do `historico` que levou o banco a Efetivado. Sem essa
    linha (venda convertida dos dados antigos) nao ha como saber: fica fora da conta e vai em `efetivadas_sem_data`."""
    efetivacoes = _datas_de_efetivacao(historico)
    hoje_dia = _dia(hoje or date.today())
    em_andamento = [v for v in vendas if v.status in vendas_mod.VENDA_EM_ABERTO]
    soma_andamento = sem_valor_andamento = 0
    for venda in em_andamento:
        valor, sem_valor = _valor_dos_bancos_fechados(venda)
        soma_andamento += valor
        sem_valor_andamento += sem_valor
    paradas = [v for v in vendas if v.parada]

    efetivadas_no_mes = []
    sem_data = 0
    for venda in vendas:
        if venda.status != vendas_mod.VENDA_EFETIVADA:
            continue
        datas = [efetivacoes[i] for i in venda.fechadas if i in efetivacoes]
        if not datas:
            sem_data += 1
            continue
        dia = max(datas)
        if (dia.year, dia.month) == (hoje_dia.year, hoje_dia.month):
            efetivadas_no_mes.append(venda)
    soma_efetivadas = sem_valor_efetivadas = 0
    for venda in efetivadas_no_mes:
        valor, sem_valor = _valor_dos_bancos_fechados(venda)
        soma_efetivadas += valor
        sem_valor_efetivadas += sem_valor

    return NumerosDasVendas(
        em_andamento=len(em_andamento),
        valor_em_andamento=soma_andamento,
        fechadas_sem_valor=sem_valor_andamento,
        paradas=len(paradas),
        dias_de_parada=propostas_mod.DIAS_PROPOSTA_PARADA,
        efetivadas_no_mes=len(efetivadas_no_mes),
        valor_efetivadas_no_mes=soma_efetivadas,
        efetivadas_sem_valor=sem_valor_efetivadas,
        efetivadas_sem_data=sem_data,
        com_pendencias=sum(1 for v in vendas if v.pendencias_abertas > 0),
        com_pendencias_ilegiveis=sum(1 for v in vendas if v.erro_pendencias),
    )


_NOMES_DOS_MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro",
                    "novembro", "dezembro"]


def resumo_das_vendas_para_copiar(numeros: NumerosDasVendas, bancos: pd.DataFrame, total: dict | None, periodo: str = PERIODO_TUDO,
                                  hoje: date | None = None) -> str:
    """O texto pronto pra colar numa conversa: uma linha das vendas de agora e uma linha por banco do periodo (a
    tabela Por banco, ja com a linha "Todos"), sem nome de cliente. Ex.:
        Vendas (outubro de 2026): 9 em andamento, 2 paradas há 7+ dias, 5 efetivadas no mês (R$ 142.000,00), 1 com pendência.
        Bancos nos últimos 7 dias:
        - Banco Exemplo: 14 enviadas, 10 aprovadas, 3 negadas, 1 em análise, taxa 76,9%, responde em 2 dias."""
    dia = _dia(hoje or date.today())
    mes = f"{_NOMES_DOS_MESES[dia.month - 1]} de {dia.year}"
    paradas = f"{numeros.paradas} {'parada' if numeros.paradas == 1 else 'paradas'} há {numeros.dias_de_parada}+ dias"
    efetivadas = f"{numeros.efetivadas_no_mes} {'efetivada' if numeros.efetivadas_no_mes == 1 else 'efetivadas'} no mês"
    if numeros.efetivadas_no_mes:
        efetivadas += f" ({formatar_reais(numeros.valor_efetivadas_no_mes)})"
    pendencias = f"{numeros.com_pendencias} com {'pendência' if numeros.com_pendencias == 1 else 'pendências'}"
    linhas = [f"Vendas ({mes}): {numeros.em_andamento} em andamento, {paradas}, {efetivadas}, {pendencias}."]

    def _linha_do_banco(nome: str, dados) -> str:
        taxa = dados["Taxa (%)"]
        partes = [_plural(dados["Enviadas"], "enviada", "enviadas"), _plural(dados["Aprovadas"], "aprovada", "aprovadas"),
                  _plural(dados["Negadas"], "negada", "negadas"), f"{dados['Em Análise']} em análise"]
        if taxa is not None and not pd.isna(taxa):
            partes.append(f"taxa {taxa:.1f}%".replace(".", ","))
        demora = dados["Demora (dias)"]
        if demora is not None and not pd.isna(demora):
            partes.append(f"responde em {texto_da_demora(demora)}")
        return f"- {nome}: " + ", ".join(partes) + "."

    quando = descricao_do_periodo(periodo)
    if len(bancos):
        linhas.append(f"Bancos {quando or 'em todo o período'}:")
        linhas += [_linha_do_banco(b["Banco"], b) for _, b in bancos.iterrows()]
        linhas.append(_linha_do_banco("Todos", total))
    else:
        linhas.append(f"Nenhuma proposta enviada a bancos {quando or 'no período'}.")
    return "\n".join(linhas)


# -- resumo para copiar (propostas: a visao do vendedor) -------------------------------------------


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
