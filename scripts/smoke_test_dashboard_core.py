"""Testa, sem Qt e sem arquivo nenhum, as regras de core/dashboard.py (o "painel", etapa 2.2): periodo, os 4
numeros das VENDAS do momento de agora, os filtros que Todas as Propostas aceita, por banco (com a demora para
responder e a linha "Todos"), o resumo para copiar (das vendas e o das propostas do vendedor) e a visao do
vendedor. Inclui os casos de borda: sem propostas, um so banco, "Todos", periodo sem dados, mes corrente.

Tudo com DataFrames e nomes inventados - nada da planilha real.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_dashboard_core.py
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from core import dashboard as dash
from core import data_store as bd
from core import propostas as propostas_mod
from core import vendas as v
from fixture_ficticia import montar_propostas as montar
from fixture_ficticia import propostas_vazias as vazio

HOJE = date.today()


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _dias_atras(n: int) -> pd.Timestamp:
    return pd.Timestamp(HOJE - timedelta(days=n))


def testar_periodos() -> None:
    linha("1) Periodos")
    h = date(2026, 9, 20)
    ts = pd.Timestamp
    assert dash.intervalo_do_periodo(dash.PERIODO_HOJE, h) == (ts(2026, 9, 20), ts(2026, 9, 20))
    assert dash.intervalo_do_periodo(dash.PERIODO_7_DIAS, h) == (ts(2026, 9, 14), ts(2026, 9, 20)), "7 dias = hoje e os 6 anteriores"
    assert dash.intervalo_do_periodo(dash.PERIODO_30_DIAS, h) == (ts(2026, 8, 22), ts(2026, 9, 20))
    assert dash.intervalo_do_periodo(dash.PERIODO_MES, h) == (ts(2026, 9, 1), ts(2026, 9, 20))
    assert dash.intervalo_do_periodo(dash.PERIODO_TUDO, h) is None
    try:
        dash.intervalo_do_periodo("semana", h)
    except ValueError as exc:
        assert "semana" in str(exc)
    else:
        raise AssertionError("periodo desconhecido tem que dar erro")
    print("OK: hoje / 7 dias / 30 dias / mes / tudo (e periodo desconhecido -> erro).")

    df = montar(
        dict(DATA=ts(2026, 9, 13)), dict(DATA=ts(2026, 9, 14)), dict(DATA=ts(2026, 9, 20)), dict(DATA=ts(2026, 9, 21)), dict(DATA=pd.NaT)
    )
    no_periodo = dash.filtrar_por_periodo(df, dash.intervalo_do_periodo(dash.PERIODO_7_DIAS, h))
    assert list(no_periodo.index) == [1, 2], "pontas incluidas; sem data e fora do periodo nao entram"
    assert dash.filtrar_por_periodo(df, None) is df, "Tudo nao filtra (inclusive quem nao tem data)"
    assert dash.filtrar_por_periodo(vazio(), (ts(2026, 9, 1), ts(2026, 9, 2))).empty
    assert dash.filtrar_por_periodo(df, dash.intervalo_do_periodo(dash.PERIODO_HOJE, date(2000, 1, 1))).empty
    assert dash.descricao_do_periodo(dash.PERIODO_7_DIAS) == "nos últimos 7 dias" and dash.descricao_do_periodo(dash.PERIODO_TUDO) == ""
    print("OK: filtrar_por_periodo inclui as pontas, deixa de fora quem nao tem data e devolve vazio sem quebrar.")


def testar_atencao() -> None:
    linha("2) Os filtros que Todas as Propostas aceita (as regras de parada, a efetivar, dados estranhos)")
    assert propostas_mod.DIAS_PROPOSTA_PARADA == 7
    df = montar(
        dict(DATA=_dias_atras(8), STATUS="Em Análise"),  # 0: parada (8 dias)
        dict(DATA=_dias_atras(7), STATUS="Em Análise"),  # 1: 7 dias exatos: nao
        dict(DATA=_dias_atras(20), STATUS="Aprovado"),  # 2: parada E a efetivar
        dict(DATA=_dias_atras(30), STATUS="Negado"),  # 3: encerrada: nunca parada
        dict(DATA=_dias_atras(2), STATUS="Em Análise", **{"VALOR (R$)": float("nan")}),  # 4: sem valor
        dict(DATA=_dias_atras(2), STATUS="Efetivado", CPF="22222222222", EQUIPAMENTO="EQ Y", BANCO="Portobank"),  # 5: duplicada com 6
        dict(DATA=_dias_atras(2), STATUS="Efetivado", CPF="22222222222", EQUIPAMENTO=" eq y ", BANCO="PORTOBANK"),  # 6: (caixa e espacos nao importam)
        dict(DATA=_dias_atras(3), STATUS="Efetivado", CPF="22222222222", EQUIPAMENTO="EQ Y", BANCO="Portobank"),  # 7: outro dia: nao e duplicada
        dict(DATA=pd.NaT, STATUS="Efetivado", CPF="33333333333"),  # 8: sem data: nunca duplicada
        dict(DATA=pd.NaT, STATUS="Efetivado", CPF="33333333333"),  # 9
        dict(DATA=pd.Timestamp(2019, 12, 31), STATUS="Negado"),  # 10: data estranha (antes de 2020)
        dict(DATA=pd.Timestamp(2020, 1, 1), STATUS="Negado"),  # 11: limite: ok
        dict(DATA=_dias_atras(-365), STATUS="Negado"),  # 12: daqui a 1 ano: ok
        dict(DATA=_dias_atras(-366), STATUS="Negado"),  # 13: alem de 1 ano no futuro
        # mesma venda (mesmo cliente+equipamento) em 2 bancos: um ja efetivou, o outro
        # ainda esta em aberto - so o 15 e sinalizado (o 14, efetivado, nao esta "em aberto")
        dict(DATA=_dias_atras(1), STATUS="Efetivado", CPF="44444444444", EQUIPAMENTO="EQ MESMA VENDA", BANCO="Banco X"),  # 14
        dict(DATA=_dias_atras(1), STATUS="Em Análise", CPF="44444444444", EQUIPAMENTO="EQ MESMA VENDA", BANCO="Banco Y"),  # 15
    )
    itens = {chave: tuple(sorted(dash.indices_do_filtro(df, dash.FiltroDoDashboard(chave, "x"), HOJE))) for chave in dash.ATENCOES_EM_ORDEM}
    assert itens[dash.ATENCAO_PARADAS] == (0, 2), "paradas: em aberto ha MAIS de 7 dias (7 exatos nao conta; encerrada nunca)"
    assert itens[dash.ATENCAO_A_EFETIVAR] == (2,)
    assert itens[dash.ATENCAO_MESMA_VENDA] == (15,), "so a que AINDA esta em aberto; a efetivada (14) nao entra"
    assert itens[dash.ATENCAO_SEM_VALOR] == (4,)
    assert itens[dash.ATENCAO_DUPLICADAS] == (5, 6), "mesmo cliente + equipamento + banco + dia (ignorando caixa/espacos)"
    assert itens[dash.ATENCAO_DATA_ESTRANHA] == (10, 13), "antes de 2020 ou alem de 1 ano no futuro"
    print("OK: cada grupo com as propostas certas (limites exatos: 7 dias, 2020-01-01, +365 dias; mesma venda em 2 bancos).")

    # os filtros que os itens abrem em Todas as Propostas dao EXATAMENTE as mesmas propostas
    assert dash.indices_do_filtro(df, dash.FiltroDoDashboard(dash.ATENCAO_PARADAS, "x", dias=15)) == {2}
    assert dash.indices_do_filtro(df, dash.FiltroDoDashboard(dash.FILTRO_ETAPA, "x", parametro=propostas_mod.ETAPA_NEGADO)) == {3, 10, 11, 12, 13}
    assert dash.indices_do_filtro(df, dash.FiltroDoDashboard(dash.FILTRO_BANCO, "x", parametro="portobank")) == {5, 6, 7}, "banco sem diferenciar caixa"
    print("OK: o limite de dias e configuravel; filtro por etapa e por banco (sem diferenciar caixa).")

    for chave in ("nada", ""):
        try:
            dash.indices_do_filtro(df, dash.FiltroDoDashboard(chave, "x"))
        except ValueError as exc:
            assert "desconhecido" in str(exc)
        else:
            raise AssertionError(f"filtro {chave!r} desconhecido tem que dar erro")
    assert dash.indices_do_filtro(vazio(), dash.FiltroDoDashboard(dash.FILTRO_ETAPA, "x", parametro="negado")) == set()
    assert dash.indices_do_filtro(vazio(), dash.FiltroDoDashboard(dash.ATENCAO_SEM_VALOR, "x")) == set()
    print("OK: filtro desconhecido e erro (nunca uma lista vazia calada); sem propostas, conjunto vazio.")


def testar_por_banco() -> None:
    linha("3) Por banco (grafias, taxa, avisos)")
    df = montar(
        *[dict(BANCO="Hubcred BV", STATUS="Aprovado") for _ in range(2)],
        dict(BANCO="HUBCRED BV", STATUS="Negado"),
        dict(BANCO=" hubcred bv ", STATUS="Em Análise"),
        *[dict(BANCO="Portobank", STATUS="Negado") for _ in range(5)],  # 5 enviadas, 0 aprovadas: sinaliza
        *[dict(BANCO="Gloriabank", STATUS="Negado") for _ in range(4)],  # 4: ainda nao sinaliza
        *[dict(BANCO="Mova HTM", STATUS=s) for s in ("Aprovado", "Negado", "Negado", "Negado", "Negado")],  # aprova 1 de 5: nao sinaliza
        *[dict(BANCO="Todos", STATUS=s) for s in ("Aprovado", "Em Análise", "Negado")],
        dict(BANCO="", STATUS="Aprovado"),
    )
    b = dash.por_banco(df)
    assert list(b.columns) == dash.COLUNAS_POR_BANCO
    por_nome = {r["Banco"]: r for _, r in b.iterrows()}
    hub = por_nome["Hubcred BV"]  # a grafia mais usada (2 contra 1 e 1)
    assert hub["Enviadas"] == 4 and hub["Aprovadas"] == 2 and hub["Negadas"] == 1 and hub["Em Análise"] == 1
    assert abs(hub["Taxa (%)"] - 66.7) < 0.05, "taxa = aprovadas / (aprovadas + negadas)"
    assert sum(1 for n in por_nome if n.strip().upper() == "HUBCRED BV") == 1, "as 3 grafias viram UM banco"
    assert por_nome["Portobank"]["Aviso"] == dash.AVISO_SEM_APROVACAO and por_nome["Portobank"]["Taxa (%)"] == 0.0
    assert por_nome["Gloriabank"]["Aviso"] == "", "4 enviadas sem aprovar ainda nao e alerta (o minimo e 5)"
    assert por_nome["Mova HTM"]["Aviso"] == "" and abs(por_nome["Mova HTM"]["Taxa (%)"] - 20.0) < 0.05
    assert dash.MINIMO_PARA_ALERTA_DE_BANCO == 5
    print("OK: grafias agrupadas, taxa certa, alerta so com 5+ enviadas e nenhuma aprovada.")

    todos = por_nome["Todos (banco digitado)"]
    assert "Todos" not in por_nome, "o 'Todos' digitado nao se confunde com a linha 'Todos' do rodape"
    assert dash.chave_do_banco("Todos (banco digitado)") == "TODOS", "o filtro de banco usa o nome digitado, sem o sufixo"
    assert todos["Aviso"] == dash.AVISO_NAO_E_BANCO and pd.isna(todos["Taxa (%)"]) and todos["Enviadas"] == 3
    sem = por_nome[dash.ROTULO_SEM_BANCO]
    assert sem["Aviso"] == dash.AVISO_SEM_BANCO and pd.isna(sem["Taxa (%)"]) and sem["Enviadas"] == 1
    assert dash.TEXTO_DO_AVISO_DE_BANCO[dash.AVISO_NAO_E_BANCO].startswith("Revisar")
    print("OK: 'Todos' e 'sem banco' viram 'revisar' e ficam FORA da taxa.")

    assert b["Demora (dias)"].isna().all(), "sem historico: nenhuma demora (nunca um numero chutado)"
    assert list(b["Enviadas"]) == sorted(b["Enviadas"], reverse=True), "mais enviadas primeiro"
    assert dash.chave_do_banco("Portobank") == "PORTOBANK" and dash.chave_do_banco(dash.ROTULO_SEM_BANCO) == ""
    print("OK: ordenado por enviadas; chave do banco pro filtro.")

    um = dash.por_banco(montar(dict(BANCO="Santander"), dict(BANCO="Santander", STATUS="Aprovado")))
    assert len(um) == 1 and um.iloc[0]["Enviadas"] == 2 and um.iloc[0]["Taxa (%)"] == 100.0
    assert dash.por_banco(vazio()).empty and list(dash.por_banco(vazio()).columns) == dash.COLUNAS_POR_BANCO
    print("OK: um so banco; sem propostas -> tabela vazia com as colunas.")


# -- as vendas (os 4 numeros) e a demora ------------------------------------------------------------------

_EM_ANALISE, _APROVADO, _EFETIVADO = propostas_mod.STATUS_EM_ANALISE, propostas_mod.STATUS_APROVADO, propostas_mod.STATUS_EFETIVADO


def _proposta_da_venda(banco: str, status: str, valor, fechada: bool, dias_na_etapa: int | None = None, id_: str | None = None) -> v.PropostaNaVenda:
    return v.PropostaNaVenda(id_ or f"P-{banco}", 0, banco, status, valor, 12, None, "EQ", fechada, None, dias_na_etapa=dias_na_etapa)


def _venda(id_: str, status: str, propostas=(), dias_na_etapa: int | None = 1, pendencias=(), erro: str = "") -> v.ResumoDaVenda:
    fechadas = tuple(p.id for p in propostas if p.fechada)
    return v.ResumoDaVenda(id_, "", "CLIENTE", "VENDEDOR", "EQ", status, "", fechadas, None, dias_na_etapa, "", tuple(propostas),
                           None, tuple(pendencias), erro)


def _pendencia(aberta: bool) -> v.Pendencia:
    momento = datetime(2026, 10, 1, 9, 0, 0)
    return v.Pendencia("PD-1", "Aguardando equipamento", momento, None if aberta else momento)


def testar_numeros_das_vendas() -> None:
    linha("4) Os 4 numeros das vendas (o momento de agora)")
    hoje = date(2026, 10, 21)
    vendas = [
        _venda("V1", v.VENDA_AGUARDANDO, dias_na_etapa=2),  # aguardando ha 2 dias: em andamento, nao parada
        _venda("V2", v.VENDA_AGUARDANDO, dias_na_etapa=7),  # 7 dias exatos: parada
        _venda("V3", v.VENDA_EM_ANDAMENTO, [_proposta_da_venda("A", _APROVADO, 1000.0, True, 3), _proposta_da_venda("B", _APROVADO, 9999.0, False, 40)]),
        _venda("V4", v.VENDA_EM_ANDAMENTO, [_proposta_da_venda("A", _APROVADO, 2000.0, True, 6), _proposta_da_venda("B", _APROVADO, None, True, 8)]),  # 8 dias: parada
        _venda("V5", v.VENDA_EFETIVADA, [_proposta_da_venda("A", _EFETIVADO, 5000.0, True, id_="P5")]),  # 1o de outubro: dentro
        _venda("V6", v.VENDA_EFETIVADA, [_proposta_da_venda("A", _EFETIVADO, 8888.0, True, id_="P6")]),  # 30 de setembro: fora
        _venda("V7", v.VENDA_EFETIVADA, [_proposta_da_venda("A", _EFETIVADO, 700.0, True, id_="P7")]),  # hoje: dentro
        _venda("V8", v.VENDA_EFETIVADA, [_proposta_da_venda("A", _EFETIVADO, 111.0, True, id_="P8")]),  # convertida: sem linha de efetivacao
        _venda("V9", v.VENDA_PERDIDA, [_proposta_da_venda("A", _APROVADO, 300.0, True, 30, id_="P9")], pendencias=[_pendencia(True)]),  # perdida: nunca parada
        _venda("V10", v.VENDA_EFETIVADA, [_proposta_da_venda("A", _EFETIVADO, 50.0, True, id_="P10")], pendencias=[_pendencia(True), _pendencia(True)]),  # setembro
        _venda("V11", v.VENDA_EM_ANDAMENTO, [_proposta_da_venda("A", _APROVADO, 100.0, True, 1)], pendencias=[_pendencia(False)]),  # so resolvida: nao conta
        _venda("V12", v.VENDA_AGUARDANDO, dias_na_etapa=1, erro="celula ilegivel"),
        # dois bancos: um efetivou em setembro e o outro em outubro: vale o MAIS RECENTE (outubro)
        _venda("V13", v.VENDA_EFETIVADA, [_proposta_da_venda("A", _EFETIVADO, 300.0, True, id_="P13a"), _proposta_da_venda("B", _EFETIVADO, 200.0, True, id_="P13b")]),
        # efetivou, voltou e efetivou de novo: vale a ULTIMA vez (outubro)
        _venda("V14", v.VENDA_EFETIVADA, [_proposta_da_venda("A", _EFETIVADO, 40.0, True, id_="P14")]),
        # a unica linha de efetivacao de verdade e de setembro; as de outro tipo, em outubro, nao contam
        _venda("V15", v.VENDA_EFETIVADA, [_proposta_da_venda("A", _EFETIVADO, 60.0, True, id_="P15")]),
    ]
    h = _historico(
        ("P5", "Aprovado", "Efetivado", "2026-10-01 00:00"),
        ("P6", "Aprovado", "Efetivado", "2026-09-30 23:59"),
        ("P7", "Aprovado", "Efetivado", "2026-10-21 18:00"),
        ("P8", "Aprovado", "Efetivado", "2026-10-15 10:00", v.TIPO_CONVERSAO),  # a conversao nao diz quando efetivou
        ("P10", "Aprovado", "Efetivado", "2026-09-02 10:00"),
        ("P13a", "Aprovado", "Efetivado", "2026-09-20 10:00"),
        ("P13b", "Aprovado", "Efetivado", "2026-10-05 10:00"),
        ("P14", "Aprovado", "Efetivado", "2026-08-01 10:00"),
        ("P14", "Efetivado", "Aprovado", "2026-08-02 10:00"),
        ("P14", "Aprovado", "Efetivado", "2026-10-02 10:00"),
        ("P15", "Aprovado", "Efetivado", "2026-09-10 10:00"),
        ("P15", "Efetivado", "Assinado", "2026-10-12 10:00"),  # mudou de etapa em outubro, mas nao e a efetivacao
        ("P15", "Aprovado", "Efetivado", "2026-10-10 10:00", v.TIPO_FECHAMENTO),
        ("P15", "Aprovado", "Efetivado", "2026-10-11 10:00", v.TIPO_VENDA),
        ("V6", "Aprovado", "Efetivado", "2026-10-12 10:00", v.TIPO_VENDA),  # o ID da VENDA nao e o de um banco
    )
    n = dash.numeros_das_vendas(vendas, hoje, h)
    assert n.em_andamento == 6, "V1, V2, V3, V4, V11 e V12 (efetivadas e perdida ficam de fora)"
    assert n.valor_em_andamento == 1000.0 + 2000.0 + 100.0, "so o valor dos bancos FECHADOS (o 9999 do banco nao fechado fica de fora)"
    assert n.fechadas_sem_valor == 1, "o banco fechado de V4 sem valor"
    assert n.paradas == 2 and n.dias_de_parada == 7, "V2 (aguardando ha 7 dias) e V4 (banco fechado ha 8); a perdida nunca"
    assert n.efetivadas_no_mes == 4 and n.valor_efetivadas_no_mes == 5000.0 + 700.0 + 500.0 + 40.0, "V5 (1o de outubro), V7 (hoje), V13 (o banco mais recente) e V14 (a ultima vez)"
    assert n.efetivadas_sem_valor == 0 and n.efetivadas_sem_data == 1, "V8 (convertida, so a linha de conversao) nao tem como saber quando: fica fora e avisada"
    assert n.com_pendencias == 2, "V9 (perdida) e V10 (efetivada em setembro): pendencia aberta em qualquer status; V11 so tem resolvida"
    assert n.com_pendencias_ilegiveis == 1
    sem_historico = dash.numeros_das_vendas(vendas, hoje)
    assert sem_historico.efetivadas_no_mes == 0 and sem_historico.efetivadas_sem_data == 8, "sem historico nenhuma efetivada tem data: todas avisadas"
    print("OK: em andamento, paradas, efetivadas no mes (data = a mais recente entre os bancos; conversao e outros tipos nao contam), com pendencias.")

    # a regra do mes: o dia 1 entra, o ultimo dia do mes anterior nao, e janeiro de um ano nao conta como o deste
    def efetivada_em(quando: str, hoje_: date) -> int:
        venda = _venda("A", v.VENDA_EFETIVADA, [_proposta_da_venda("A", _EFETIVADO, 10.0, True, id_="PA")])
        return dash.numeros_das_vendas([venda], hoje_, _historico(("PA", "Aprovado", "Efetivado", quando))).efetivadas_no_mes

    assert efetivada_em("2026-10-01 00:00", date(2026, 10, 1)) == 1
    assert efetivada_em("2026-09-30 23:59", date(2026, 10, 1)) == 0, "ontem = 30/09"
    assert efetivada_em("2026-01-01 08:00", date(2027, 1, 5)) == 0, "janeiro de outro ano nao e este mes"
    assert efetivada_em("2027-01-01 08:00", date(2027, 1, 5)) == 1, "1o de janeiro de 2027: dentro"
    print("OK: limites do mes (dia 1 entra, 30/09 nao, janeiro do ano anterior nao).")

    vazio_ = dash.numeros_das_vendas([], hoje)
    assert (vazio_.em_andamento, vazio_.paradas, vazio_.efetivadas_no_mes, vazio_.com_pendencias) == (0, 0, 0, 0)
    assert vazio_.valor_em_andamento == 0.0 and vazio_.valor_efetivadas_no_mes == 0.0
    sem_valor = dash.numeros_das_vendas([_venda("A", v.VENDA_EFETIVADA, [_proposta_da_venda("A", _EFETIVADO, None, True, id_="PA")])], hoje,
                                        _historico(("PA", "Aprovado", "Efetivado", "2026-10-02 10:00")))
    assert sem_valor.efetivadas_no_mes == 1 and sem_valor.valor_efetivadas_no_mes == 0.0 and sem_valor.efetivadas_sem_valor == 1
    print("OK: sem vendas tudo zero; efetivada sem valor conta a venda e avisa que falta o valor.")


def _historico(*linhas) -> pd.DataFrame:
    """(ID, DE, PARA, QUANDO[, TIPO]) -> a aba HISTORICO."""
    registros = [
        {"QUANDO": pd.Timestamp(q), "TIPO": (resto[0] if resto else v.TIPO_PROPOSTA), "ID": i, "DE": de, "PARA": para, "MOTIVO": "", "COMPUTADOR": ""}
        for i, de, para, q, *resto in linhas
    ]
    return pd.DataFrame(registros, columns=bd.HISTORICO_COLUNAS)


def testar_demora_e_por_banco() -> None:
    linha("5) Por banco: a demora para responder (mediana de dias) e a linha Todos")
    d = pd.Timestamp
    df = montar(
        dict(ID_PROPOSTA="P1", BANCO="Banco Alfa", STATUS="Aprovado", DATA=d(2026, 10, 1)),
        dict(ID_PROPOSTA="P2", BANCO="BANCO ALFA", STATUS="Aprovado", DATA=d(2026, 10, 1)),
        dict(ID_PROPOSTA="P3", BANCO="Banco Alfa", STATUS="Em Análise", DATA=d(2026, 10, 1)),  # so a criacao: sem resposta
        dict(ID_PROPOSTA="P4", BANCO="Banco Beta", STATUS="Aprovado", DATA=d(2026, 10, 10)),  # respondeu no mesmo dia
        dict(ID_PROPOSTA="P5", BANCO="Banco Beta", STATUS="Negado", DATA=d(2026, 10, 10)),  # 1 dia
        dict(ID_PROPOSTA="P6", BANCO="Banco Gama", STATUS="Em Análise", DATA=d(2026, 10, 3)),  # sem nenhum historico
        dict(BANCO="Banco Gama", STATUS="Em Análise", DATA=d(2026, 10, 3)),  # sem ID_PROPOSTA (de antes das vendas)
        dict(ID_PROPOSTA="P8", BANCO="Banco Delta", STATUS="Aprovado", DATA=d(2026, 10, 5)),  # a mudanca no historico e ANTES da DATA
        dict(ID_PROPOSTA="P9", BANCO="Banco Eps", STATUS="Aprovado", DATA=d(2026, 10, 5)),  # so uma linha de OUTRO tipo
        dict(ID_PROPOSTA="P10", BANCO="Banco Zeta", STATUS="Efetivado", DATA=d(2026, 10, 1)),  # ja nasceu Aprovada: a efetivacao nao e resposta
        *[dict(ID_PROPOSTA=f"PM{i}", BANCO="Banco Mediana", STATUS="Aprovado", DATA=d(2026, 10, 1)) for i in range(3)],
    )
    h = _historico(
        *[(f"P{i}", "", "Em Análise", "2026-10-01 09:00") for i in (1, 2, 3)],
        ("P2", "Em Análise", "Aprovado", "2026-10-06 18:30"),  # 5 dias
        ("P2", "Aprovado", "Assinado", "2026-10-02 08:00"),  # nao sai de Em Analise: nao e resposta do banco
        ("P10", "Aprovado", "Efetivado", "2026-10-09 08:00"),
        ("P1", "Em Análise", "Aprovado", "2026-10-04 12:00"),  # 3 dias
        ("P4", "Em Análise", "Aprovado", "2026-10-10 15:00"),  # 0 dia
        ("P4", "Aprovado", "Assinado", "2026-10-20 15:00"),  # a segunda mudanca nao conta
        ("P5", "Em Análise", "Negado", "2026-10-11 10:00"),  # 1 dia
        ("P8", "Em Análise", "Aprovado", "2026-10-01 10:00"),
        ("P9", "Em Análise", "Aprovado", "2026-10-09 10:00", v.TIPO_CONVERSAO),
        ("PM0", "Em Análise", "Aprovado", "2026-10-02 10:00"),  # 1
        ("PM0", "Em Análise", "Negado", "2026-10-15 10:00"),  # voltou a Em Analise e respondeu de novo: vale a PRIMEIRA resposta
        ("PM1", "Em Análise", "Aprovado", "2026-10-03 10:00"),  # 2
        ("PM2", "Em Análise", "Aprovado", "2026-10-11 10:00"),  # 10: a media seria 4,33, a mediana e 2
    )
    demoras = dash.demoras_de_resposta(df, h)
    assert list(demoras.index) == list(df.index)
    # P1 3 ; P2 5 ; P3 NaN ; P4 0 ; P5 1 ; P6 NaN ; sem ID NaN ; P8 NaN (negativa) ; P9 NaN ; P10 NaN ; 1, 2, 10
    esperadas = [3, 5, None, 0, 1, None, None, None, None, None, 1, 2, 10]
    assert [None if pd.isna(x) else int(x) for x in demoras] == esperadas, list(demoras)
    print("OK: dias do envio ate a 1a mudanca de status (a criacao, outro tipo de linha, sem ID, sem historico e mudanca antes da data ficam de fora).")

    b = {r["Banco"]: r for _, r in dash.por_banco(df, h).iterrows()}
    assert b["Banco Alfa"]["Demora (dias)"] == 4.0, "mediana de [3, 5] = 4"
    assert b["Banco Alfa"]["Enviadas"] == 3, "BANCO ALFA e Banco Alfa sao o mesmo banco"
    assert b["Banco Beta"]["Demora (dias)"] == 0.5 and b["Banco Mediana"]["Demora (dias)"] == 2.0, "a mediana, nao a media"
    assert all(pd.isna(b[nome]["Demora (dias)"]) for nome in ("Banco Gama", "Banco Delta", "Banco Eps", "Banco Zeta"))
    sem_historico = {r["Banco"]: r for _, r in dash.por_banco(df).iterrows()}
    assert all(pd.isna(r["Demora (dias)"]) for r in sem_historico.values()), "sem historico: '—' em todos"
    assert all(pd.isna(r["Demora (dias)"]) for _, r in dash.por_banco(df, bd_vazio()).iterrows())
    print("OK: demora por banco = mediana das demoras; banco sem resposta (ou sem historico) fica sem numero.")

    total = dash.total_por_banco(df, h)
    assert total["Enviadas"] == 13 and total["Aprovadas"] == 9 and total["Negadas"] == 1 and total["Em Análise"] == 3
    assert total["Taxa (%)"] == 90.0 and total["Demora (dias)"] == 2.0, "mediana de [3,5,0,1,1,2,10] = 2"
    assert dash.total_por_banco(montar(dict(STATUS="Em Análise")))["Taxa (%)"] is None, "sem decididas: sem taxa"
    com_todos = montar(dict(BANCO="Todos", STATUS="Aprovado"), dict(BANCO="", STATUS="Negado"), dict(BANCO="Santander", STATUS="Aprovado"))
    assert dash.total_por_banco(com_todos)["Enviadas"] == 3, "a linha Todos soma tambem o 'Todos' digitado e as sem banco"
    print("OK: linha 'Todos' = as mesmas colunas sobre todas as propostas do periodo.")

    assert dash.texto_da_demora(None) == "—" and dash.texto_da_demora(float("nan")) == "—"
    assert dash.texto_da_demora(0) == "mesmo dia" and dash.texto_da_demora(1.0) == "1 dia" and dash.texto_da_demora(3.0) == "3 dias"
    assert dash.texto_da_demora(2.5) == "2,5 dias"
    print("OK: texto da demora (— / mesmo dia / 1 dia / 3 dias / 2,5 dias).")


def bd_vazio() -> pd.DataFrame:
    return pd.DataFrame(columns=bd.HISTORICO_COLUNAS)


def testar_resumo_das_vendas() -> None:
    linha("5b) Resumo para copiar das vendas (sem nome de cliente)")
    hoje = date(2026, 10, 21)
    d = pd.Timestamp
    df = montar(
        dict(ID_PROPOSTA="P1", BANCO="Banco Alfa", STATUS="Aprovado", DATA=d(2026, 10, 1)),
        dict(ID_PROPOSTA="P2", BANCO="Banco Alfa", STATUS="Aprovado", DATA=d(2026, 10, 1)),
        dict(ID_PROPOSTA="P3", BANCO="Banco Alfa", STATUS="Negado", DATA=d(2026, 10, 1)),
        dict(ID_PROPOSTA="P4", BANCO="Banco Alfa", STATUS="Em Análise", DATA=d(2026, 10, 1)),
        dict(ID_PROPOSTA="P5", BANCO="Banco Beta", STATUS="Negado", DATA=d(2026, 10, 1)),
    )
    h = _historico(("P1", "Em Análise", "Aprovado", "2026-10-03 10:00"), ("P2", "Em Análise", "Aprovado", "2026-10-05 10:00"))
    numeros = dash.numeros_das_vendas(
        [_venda("V1", v.VENDA_AGUARDANDO, dias_na_etapa=9), _venda("V2", v.VENDA_EM_ANDAMENTO, [_proposta_da_venda("A", _APROVADO, 100.0, True, 1)]),
         _venda("V3", v.VENDA_EFETIVADA, [_proposta_da_venda("A", _EFETIVADO, 142000.0, True, id_="P3")]),
         _venda("V4", v.VENDA_PERDIDA, pendencias=[_pendencia(True)])], hoje, _historico(("P3", "Aprovado", "Efetivado", "2026-10-19 10:00")))
    bancos, total = dash.por_banco(df, h), dash.total_por_banco(df, h)
    texto = dash.resumo_das_vendas_para_copiar(numeros, bancos, total, dash.PERIODO_7_DIAS, hoje)
    assert texto == "\n".join([
        "Vendas (outubro de 2026): 2 em andamento, 1 parada há 7+ dias, 1 efetivada no mês (R$ 142.000,00), 1 com pendência.",
        "Bancos nos últimos 7 dias:",
        "- Banco Alfa: 4 enviadas, 2 aprovadas, 1 negada, 1 em análise, taxa 66,7%, responde em 3 dias.",
        "- Banco Beta: 1 enviada, 0 aprovadas, 1 negada, 0 em análise, taxa 0,0%.",
        "- Todos: 5 enviadas, 2 aprovadas, 2 negadas, 1 em análise, taxa 50,0%, responde em 3 dias.",
    ]), texto
    for nome_proibido in ("CLIENTE", "VENDEDOR"):
        assert nome_proibido not in texto
    print("OK: o texto das vendas + uma linha por banco + Todos (singular/plural, mes e periodo, sem cliente).")

    # o "Todos" digitado como banco aparece como linha de banco, diferente da linha "Todos" do rodape
    digitado = montar(dict(BANCO="Todos", STATUS="Aprovado"), dict(BANCO="Santander", STATUS="Negado"))
    texto_digitado = dash.resumo_das_vendas_para_copiar(dash.numeros_das_vendas([], hoje), dash.por_banco(digitado), dash.total_por_banco(digitado),
                                                         dash.PERIODO_TUDO, hoje).splitlines()
    assert "- Todos (banco digitado): 1 enviada, 1 aprovada, 0 negadas, 0 em análise." in texto_digitado, texto_digitado
    assert texto_digitado[-1].startswith("- Todos: 2 enviadas, 1 aprovada, 1 negada")
    assert not [l for l in texto_digitado if l.startswith("- Todos:") and l != texto_digitado[-1]], "so uma linha 'Todos:' (a do rodape)"

    vendas_zero = dash.numeros_das_vendas([], hoje)
    zerado = dash.resumo_das_vendas_para_copiar(vendas_zero, dash.por_banco(vazio()), dash.total_por_banco(vazio()), dash.PERIODO_TUDO, hoje)
    assert zerado == "\n".join([
        "Vendas (outubro de 2026): 0 em andamento, 0 paradas há 7+ dias, 0 efetivadas no mês, 0 com pendências.",
        "Nenhuma proposta enviada a bancos no período.",
    ]), zerado
    assert dash.resumo_das_vendas_para_copiar(vendas_zero, bancos, total, dash.PERIODO_TUDO, date(2026, 3, 5)).startswith("Vendas (março de 2026)")
    assert "Bancos em todo o período:" in dash.resumo_das_vendas_para_copiar(vendas_zero, bancos, total, dash.PERIODO_TUDO, hoje)
    print("OK: sem vendas e sem propostas o texto continua inteiro (zeros e 'Nenhuma proposta...').")


def testar_resumo() -> None:
    linha("6) Resumo para copiar (o das propostas, da visao do vendedor)")
    df = montar(*[dict(STATUS="Em Análise") for _ in range(21)], *[dict(STATUS="Aprovado") for _ in range(10)], dict(STATUS="Pré-aprovado"), *[dict(STATUS="Negado") for _ in range(26)], dict(STATUS=""))
    assert dash.resumo_para_copiar(df) == "59 propostas: 21 em análise, 11 aprovadas (0 efetivadas), 26 negadas e 1 sem status."
    print("OK: 'Tudo' -> o texto do exemplo (com as 11 aprovadas e 0 efetivadas).")

    um = montar(dict(STATUS="Efetivado"))
    assert dash.resumo_para_copiar(um) == "1 proposta: 1 aprovada (1 efetivada)."
    assert dash.resumo_para_copiar(montar(dict(STATUS="Negado"), dict(STATUS="Negado")), dash.PERIODO_7_DIAS) == "2 propostas nos últimos 7 dias: 2 negadas."
    assert dash.resumo_para_copiar(montar(dict(STATUS="coisa")), dash.PERIODO_MES) == "1 proposta neste mês: 1 com status não reconhecido."
    assert dash.resumo_para_copiar(vazio()) == "Nenhuma proposta."
    assert dash.resumo_para_copiar(vazio(), dash.PERIODO_HOJE) == "Nenhuma proposta hoje."
    print("OK: singular/plural, com periodo, status estranho e sem propostas.")


def testar_visao_do_vendedor() -> None:
    linha("7) Visao do vendedor (minhas em analise / a efetivar / clientes sem proposta)")
    df = montar(
        dict(STATUS="Em Análise", DATA=_dias_atras(2), CLIENTE="ANA", CPF="10000000001"),
        dict(STATUS="Em Análise", DATA=_dias_atras(9), CLIENTE="ZE", CPF="10000000002", **{"VALOR (R$)": float("nan")}),
        dict(STATUS="Aprovado", DATA=_dias_atras(4), CLIENTE="ZE", CPF="10000000001"),
        dict(STATUS="Negado"),
    )
    em_analise = dash.propostas_da_etapa(df, propostas_mod.ETAPA_EM_ANALISE)
    assert [p.cliente for p in em_analise] == ["ZE", "ANA"], "as mais paradas primeiro (e NAO em ordem alfabetica: ZE tem 9 dias e ANA 2)"
    assert em_analise[0].dias == 9 and em_analise[0].valor is None and em_analise[1].valor == 1000.0 and em_analise[0].indice == 1
    assert [p.indice for p in dash.propostas_da_etapa(df, propostas_mod.ETAPA_APROVADO)] == [2]
    assert dash.propostas_da_etapa(vazio(), propostas_mod.ETAPA_APROVADO) == []
    print("OK: as propostas da etapa, as mais paradas primeiro, com valor (ou None) e dias.")

    clientes = pd.DataFrame({"CPF/CNPJ": ["100.000.000-01", "100.000.000-09", "100.000.000-07"], "CLIENTE": ["ZE", "MARIA", "BIA"]})
    assert dash.clientes_sem_proposta(clientes, df) == [("100.000.000-07", "BIA"), ("100.000.000-09", "MARIA")], "compara so os digitos; ordem alfabetica"
    assert dash.clientes_sem_proposta(clientes, vazio()) == [("100.000.000-07", "BIA"), ("100.000.000-09", "MARIA"), ("100.000.000-01", "ZE")], "sem propostas, todos"
    assert dash.clientes_sem_proposta(clientes.iloc[0:0], df) == []
    print("OK: clientes sem proposta (comparando so os digitos do CPF), em ordem alfabetica.")


def testar_casos_de_borda_gerais() -> None:
    linha("8) Bordas gerais: nenhum quebra com propostas vazias")
    v = vazio()
    assert dash.por_banco(v).empty and dash.por_banco(v, bd_vazio()).empty
    total = dash.total_por_banco(v)
    assert total == {"Enviadas": 0, "Aprovadas": 0, "Negadas": 0, "Em Análise": 0, "Taxa (%)": None, "Demora (dias)": None}, total
    # o mesmo, como o app monta o de um vendedor SEM nenhuma proposta: le a planilha (colunas de texto) e filtra -> 0 linhas
    cheias = montar(dict(VENDEDOR="OUTRA PESSOA"), dict(VENDEDOR="OUTRA PESSOA"))
    filtradas = cheias[cheias["VENDEDOR"] == "FULANO SEM PROPOSTAS"]
    assert len(filtradas) == 0
    dash.por_banco(filtradas)
    dash.total_por_banco(filtradas)
    assert dash.resumo_para_copiar(filtradas) == "Nenhuma proposta."
    print("OK: sem propostas (vazias ou filtradas ate zero) nenhuma funcao do painel quebra.")

    # periodo sem dados: filtra ate ficar vazio e o painel todo responde vazio
    velhas = montar(dict(DATA=_dias_atras(400)), dict(DATA=_dias_atras(500)))
    do_periodo = dash.filtrar_por_periodo(velhas, dash.intervalo_do_periodo(dash.PERIODO_7_DIAS))
    assert do_periodo.empty and dash.total_por_banco(do_periodo)["Enviadas"] == 0
    print("OK: periodo sem dados -> painel vazio.")


def main() -> None:
    testar_periodos()
    testar_atencao()
    testar_por_banco()
    testar_numeros_das_vendas()
    testar_demora_e_por_banco()
    testar_resumo_das_vendas()
    testar_resumo()
    testar_visao_do_vendedor()
    testar_casos_de_borda_gerais()
    linha("TUDO OK")


if __name__ == "__main__":
    main()
