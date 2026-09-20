"""Testa, sem Qt e sem arquivo nenhum, as regras novas de core/dashboard.py (o "painel"): periodo e
comparacao, numeros do topo, "Precisa de atencao", funil, por banco, para reenviar, qualidade dos
dados, resumo para copiar e a visao do vendedor. Inclui os casos de borda: sem propostas, tudo sem
valor, um so banco, "Todos", periodo sem dados.

Tudo com DataFrames e nomes inventados - nada da planilha real.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_dashboard_core.py
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from core import dashboard as dash
from core import propostas as propostas_mod
from fixture_ficticia import montar_propostas as montar
from fixture_ficticia import propostas_vazias as vazio

HOJE = date.today()


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _dias_atras(n: int) -> pd.Timestamp:
    return pd.Timestamp(HOJE - timedelta(days=n))


def testar_periodos() -> None:
    linha("1) Periodos e periodo anterior")
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

    assert dash.intervalo_anterior(dash.PERIODO_HOJE, h) == (ts(2026, 9, 19), ts(2026, 9, 19))
    assert dash.intervalo_anterior(dash.PERIODO_7_DIAS, h) == (ts(2026, 9, 7), ts(2026, 9, 13))
    assert dash.intervalo_anterior(dash.PERIODO_30_DIAS, h) == (ts(2026, 7, 23), ts(2026, 8, 21))
    assert dash.intervalo_anterior(dash.PERIODO_MES, h) == (ts(2026, 8, 1), ts(2026, 8, 20)), "mes: ate o mesmo dia do mes anterior"
    assert dash.intervalo_anterior(dash.PERIODO_MES, date(2026, 3, 31)) == (ts(2026, 2, 1), ts(2026, 2, 28)), "fevereiro curto: nao passa do ultimo dia"
    assert dash.intervalo_anterior(dash.PERIODO_MES, date(2026, 3, 1)) == (ts(2026, 2, 1), ts(2026, 2, 1))
    assert dash.intervalo_anterior(dash.PERIODO_TUDO, h) is None
    print("OK: o periodo anterior tem o mesmo tamanho (mes: ate o mesmo dia); Tudo nao tem anterior.")

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


def testar_indicadores() -> None:
    linha("2) Numeros do topo")
    df = montar(
        dict(STATUS="Em Análise", **{"VALOR (R$)": 100.0}),
        dict(STATUS="Em Análise", **{"VALOR (R$)": 200.0}),
        dict(STATUS="Em Análise", **{"VALOR (R$)": float("nan")}),
        dict(STATUS="Aprovado", **{"VALOR (R$)": 300.0}),
        dict(STATUS="Aprovado", **{"VALOR (R$)": 500.0}),
        dict(STATUS="Pré-aprovado"),
        dict(STATUS="Nota Fiscal Anexada"),
        dict(STATUS="Efetivado"),
        dict(STATUS="Negado"), dict(STATUS="Negado"), dict(STATUS="Negado"), dict(STATUS="Negado"),
        dict(STATUS=""),
    )
    i = dash.indicadores_do_topo(df)
    assert i["total"] == 13
    assert i["em_analise"] == {"quantidade": 3, "valor": 300.0, "com_valor": 2}, i["em_analise"]
    assert i["a_efetivar"] == {"quantidade": 2, "efetivadas": 1}, "so o status 'Aprovado' esta a efetivar; 1 ja foi efetivada"
    assert i["taxa_aprovacao"]["aprovadas"] == 5, "aprovadas = todas as etapas positivas (2 + pre + NF + efetivado)"
    assert i["taxa_aprovacao"]["decididas"] == 9 and abs(i["taxa_aprovacao"]["percentual"] - 5 / 9 * 100) < 1e-9
    assert i["valor_mediano"]["com_valor"] == 12 and i["valor_mediano"]["total"] == 13, "so 1 das 13 esta sem valor"
    assert i["valor_mediano"]["mediana"] == 1000.0
    print("OK: em analise (quantidade, valor, so N tem valor), a efetivar x efetivadas, taxa sobre as decididas.")

    # nenhuma decidida: taxa None (nunca divide por zero); tudo sem valor: mediana None
    sem_valor = montar(dict(STATUS="Em Análise", **{"VALOR (R$)": float("nan")}), dict(STATUS="Em Análise", **{"VALOR (R$)": float("nan")}))
    i = dash.indicadores_do_topo(sem_valor)
    assert i["taxa_aprovacao"] == {"aprovadas": 0, "decididas": 0, "percentual": None}
    assert i["valor_mediano"] == {"mediana": None, "com_valor": 0, "total": 2}
    assert i["em_analise"] == {"quantidade": 2, "valor": 0.0, "com_valor": 0}
    print("OK: tudo sem valor -> mediana None e soma 0; sem decididas -> taxa None.")

    v = dash.indicadores_do_topo(vazio())
    assert v["total"] == 0 and v["em_analise"]["quantidade"] == 0 and v["valor_mediano"]["mediana"] is None
    assert v["taxa_aprovacao"]["percentual"] is None and v["a_efetivar"] == {"quantidade": 0, "efetivadas": 0}
    print("OK: sem nenhuma proposta, tudo zerado (e sem quebrar).")

    mediana = dash.indicadores_do_topo(montar(*[dict(**{"VALOR (R$)": x}) for x in (10.0, 20.0, 1_000_000.0)]))["valor_mediano"]["mediana"]
    assert mediana == 20.0, "a mediana nao se deixa levar por um valor absurdo (a soma se deixaria)"
    print("OK: a mediana ignora o valor atipico.")


def testar_comparacao() -> None:
    linha("3) Comparacao com o periodo anterior")
    atual = dash.indicadores_do_topo(montar(dict(STATUS="Em Análise"), dict(STATUS="Em Análise"), dict(STATUS="Aprovado"), dict(STATUS="Negado"), dict(**{"VALOR (R$)": 200.0})))
    anterior = dash.indicadores_do_topo(montar(dict(STATUS="Em Análise"), dict(STATUS="Negado"), dict(STATUS="Negado"), dict(**{"VALOR (R$)": 100.0})))
    c = dash.comparar_periodos(atual, anterior)
    assert c["em_analise"] == 1, "3 em analise agora contra 2 antes"
    assert c["a_efetivar"] == 1, "1 a efetivar agora contra nenhuma"
    assert c["taxa_aprovacao"] == 50.0, "50% (1 de 2) contra 0% (0 de 2): subiu 50 pontos"
    assert c["valor_mediano"] == 0.0, "as duas medianas sao 1000: variacao 0%"
    print("OK: as diferencas de cada numero (positivo = subiu).")

    assert dash.comparar_periodos(atual, dash.indicadores_do_topo(vazio())) is None
    assert dash.comparar_periodos(dash.indicadores_do_topo(vazio()), anterior) is None
    print("OK: se um dos periodos nao tem nenhuma proposta, nao ha comparacao (None).")

    so_analise = dash.indicadores_do_topo(montar(dict(STATUS="Em Análise")))
    c = dash.comparar_periodos(so_analise, anterior)
    assert c["taxa_aprovacao"] is None, "sem propostas decididas de um lado, a taxa nao e comparavel"
    sem_valor = dash.indicadores_do_topo(montar(dict(**{"VALOR (R$)": float("nan")})))
    assert dash.comparar_periodos(sem_valor, anterior)["valor_mediano"] is None, "sem mediana de um lado, nao compara a mediana"
    print("OK: a taxa e a mediana so comparam quando existem dos dois lados.")


def testar_atencao() -> None:
    linha("4) Precisa de atencao")
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
    )
    itens = {i.chave: i for i in dash.precisa_de_atencao(df)}
    assert set(itens) == {dash.ATENCAO_PARADAS, dash.ATENCAO_A_EFETIVAR, dash.ATENCAO_SEM_VALOR, dash.ATENCAO_DUPLICADAS, dash.ATENCAO_DATA_ESTRANHA}
    assert itens[dash.ATENCAO_PARADAS].indices == (0, 2), "paradas: em aberto ha MAIS de 7 dias (7 exatos nao conta; encerrada nunca)"
    assert itens[dash.ATENCAO_A_EFETIVAR].indices == (2,)
    assert itens[dash.ATENCAO_SEM_VALOR].indices == (4,)
    assert itens[dash.ATENCAO_DUPLICADAS].indices == (5, 6), "mesmo cliente + equipamento + banco + dia (ignorando caixa/espacos)"
    assert itens[dash.ATENCAO_DATA_ESTRANHA].indices == (10, 13), "antes de 2020 ou alem de 1 ano no futuro"
    assert itens[dash.ATENCAO_PARADAS].tom == dash.TOM_PROCESSO and itens[dash.ATENCAO_SEM_VALOR].tom == dash.TOM_DADOS
    assert [i.chave for i in dash.precisa_de_atencao(df)] == ["paradas", "a_efetivar", "sem_valor", "duplicadas", "data_estranha"], "ordem fixa: o que esta parado no processo antes dos problemas de cadastro"
    print("OK: cada grupo com as propostas certas (limites exatos: 7 dias, 2020-01-01, +365 dias).")

    assert itens[dash.ATENCAO_PARADAS].texto == "2 propostas em aberto há mais de 7 dias"
    assert itens[dash.ATENCAO_A_EFETIVAR].texto == "1 proposta aprovada ainda sem efetivar", itens[dash.ATENCAO_A_EFETIVAR].texto
    assert itens[dash.ATENCAO_SEM_VALOR].texto == "1 proposta sem valor"
    assert itens[dash.ATENCAO_DUPLICADAS].texto == "2 propostas que parecem duplicadas"
    assert itens[dash.ATENCAO_PARADAS].rotulo_do_filtro == "Em aberto há mais de 7 dias"
    print("OK: os textos (singular/plural) e o rotulo do filtro.")

    so_20 = {i.chave: i for i in dash.precisa_de_atencao(df, dias=15)}
    assert so_20[dash.ATENCAO_PARADAS].indices == (2,) and "15 dias" in so_20[dash.ATENCAO_PARADAS].texto
    print("OK: o limite de dias e configuravel.")

    em_dia = montar(dict(DATA=_dias_atras(1), STATUS="Em Análise"), dict(DATA=_dias_atras(400), STATUS="Negado"))
    assert dash.precisa_de_atencao(em_dia) == [], "nada pedindo atencao -> lista vazia (a tela mostra a mensagem positiva)"
    assert dash.precisa_de_atencao(vazio()) == []
    print("OK: sem nada a sinalizar (ou sem propostas) -> lista vazia.")

    # os filtros que os itens abrem em Todas as Propostas dao EXATAMENTE as mesmas propostas
    for chave in dash.ATENCOES_EM_ORDEM:
        filtro = dash.FiltroDoDashboard(chave, "x")
        assert dash.indices_do_filtro(df, filtro) == set(itens[chave].indices), chave
    assert dash.indices_do_filtro(df, dash.FiltroDoDashboard(dash.ATENCAO_PARADAS, "x", dias=15)) == {2}
    assert dash.indices_do_filtro(df, dash.FiltroDoDashboard(dash.FILTRO_ETAPA, "x", parametro=propostas_mod.ETAPA_NEGADO)) == {3, 10, 11, 12, 13}
    assert dash.indices_do_filtro(df, dash.FiltroDoDashboard(dash.FILTRO_BANCO, "x", parametro="portobank")) == {5, 6, 7}, "banco sem diferenciar caixa"
    print("OK: indices_do_filtro devolve as mesmas propostas do item (e por etapa e por banco).")

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


def testar_funil() -> None:
    linha("5) Funil por etapa")
    df = montar(
        dict(STATUS="Em Análise", **{"VALOR (R$)": 100.0}), dict(STATUS="Em Análise", **{"VALOR (R$)": float("nan")}),
        dict(STATUS="Pré-aprovado"), dict(STATUS="Aprovado", **{"VALOR (R$)": 50.0}),
        dict(STATUS="Efetivado"), dict(STATUS="Negado"), dict(STATUS="Negado"), dict(STATUS="Negado"),
    )
    f = dash.funil_por_etapa(df)
    assert [(e.etapa, e.quantidade) for e in f] == [
        (propostas_mod.ETAPA_EM_ANALISE, 2), (propostas_mod.ETAPA_PRE_APROVADO, 1), (propostas_mod.ETAPA_APROVADO, 1),
        (propostas_mod.ETAPA_NF_ANEXADA, 0), (propostas_mod.ETAPA_GARANTIA_ASSINADA, 0), (propostas_mod.ETAPA_EFETIVADO, 1),
        (propostas_mod.ETAPA_NEGADO, 3),
    ], [(e.etapa, e.quantidade) for e in f]
    assert f[0].valor == 100.0 and f[0].com_valor == 1 and f[-1].rotulo == "Negado" and f[3].rotulo == "Nota fiscal"
    print("OK: as 6 etapas do funil em ordem e 'Negado' por ultimo (separado), com valor e quantas tem valor.")

    com_estranhas = montar(dict(STATUS=""), dict(STATUS="coisa esquisita"), dict(STATUS="Em Análise"))
    extras = [e for e in dash.funil_por_etapa(com_estranhas) if e.etapa in (propostas_mod.ETAPA_SEM_STATUS, propostas_mod.ETAPA_DESCONHECIDA)]
    assert [(e.rotulo, e.quantidade) for e in extras] == [("Sem status", 1), ("Status não reconhecido", 1)]
    assert len(dash.funil_por_etapa(df)) == 7 and len(dash.funil_por_etapa(vazio())) == 7
    assert all(e.quantidade == 0 for e in dash.funil_por_etapa(vazio()))
    print("OK: 'sem status' e 'nao reconhecido' so aparecem se houver (nada some da conta); vazio = tudo 0.")


def testar_por_banco() -> None:
    linha("6) Por banco")
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

    todos = por_nome["Todos"]
    assert todos["Aviso"] == dash.AVISO_NAO_E_BANCO and pd.isna(todos["Taxa (%)"]) and todos["Enviadas"] == 3
    sem = por_nome[dash.ROTULO_SEM_BANCO]
    assert sem["Aviso"] == dash.AVISO_SEM_BANCO and pd.isna(sem["Taxa (%)"]) and sem["Enviadas"] == 1
    assert dash.TEXTO_DO_AVISO_DE_BANCO[dash.AVISO_NAO_E_BANCO].startswith("Revisar")
    print("OK: 'Todos' e 'sem banco' viram 'revisar' e ficam FORA da taxa.")

    assert list(b["Enviadas"]) == sorted(b["Enviadas"], reverse=True), "mais enviadas primeiro"
    assert dash.chave_do_banco("Portobank") == "PORTOBANK" and dash.chave_do_banco(dash.ROTULO_SEM_BANCO) == ""
    print("OK: ordenado por enviadas; chave do banco pro filtro.")

    um = dash.por_banco(montar(dict(BANCO="Santander"), dict(BANCO="Santander", STATUS="Aprovado")))
    assert len(um) == 1 and um.iloc[0]["Enviadas"] == 2 and um.iloc[0]["Taxa (%)"] == 100.0
    assert dash.por_banco(vazio()).empty and list(dash.por_banco(vazio()).columns) == dash.COLUNAS_POR_BANCO
    print("OK: um so banco; sem propostas -> tabela vazia com as colunas.")


def testar_para_reenviar() -> None:
    linha("7) Para reenviar")
    df = montar(
        # A: todas negadas em Santander e Portobank
        dict(CPF="10000000001", CLIENTE="CLIENTE A", BANCO="Santander", STATUS="Negado", DATA=_dias_atras(5)),
        dict(CPF="10000000001", CLIENTE="CLIENTE A", BANCO="portobank", STATUS="Negado", DATA=_dias_atras(2)),
        # B: uma negada e uma aprovada -> nao entra
        dict(CPF="10000000002", CLIENTE="CLIENTE B", BANCO="Santander", STATUS="Negado"),
        dict(CPF="10000000002", CLIENTE="CLIENTE B", BANCO="Medicalsan", STATUS="Aprovado"),
        # C: so em analise -> nao entra
        dict(CPF="10000000003", CLIENTE="CLIENTE C", BANCO="Santander", STATUS="Em Análise"),
        # D: negada so em "Todos" (nao e banco)
        dict(CPF="10000000004", CLIENTE="CLIENTE D", BANCO="Todos", STATUS="Negado", DATA=_dias_atras(20)),
        # E: sem cliente cadastrado
        dict(CPF="10000000005", CLIENTE="", BANCO="Smart", STATUS="Negado", DATA=_dias_atras(40)),
        # F: mesmo dia: a que esta mais abaixo no arquivo e a mais recente
        dict(CPF="10000000006", CLIENTE="CLIENTE F", BANCO="Smart", STATUS="Negado", DATA=_dias_atras(3), EQUIPAMENTO="PRIMEIRA"),
        dict(CPF="10000000006", CLIENTE="CLIENTE F", BANCO="Mova HTM", STATUS="Negado", DATA=_dias_atras(3), EQUIPAMENTO="SEGUNDA"),
        # G: sem CPF: ignorado
        dict(CPF="", CLIENTE="SEM CPF", BANCO="Santander", STATUS="Negado"),
    )
    r = {c.cliente or c.cpf: c for c in dash.para_reenviar(df, bancos_conhecidos=["Santander", "Portobank", "Medicalsan", "Smart", "Mova HTM", "Todos", "Gloriabank"])}
    assert set(r) == {"CLIENTE A", "CLIENTE D", "10000000005", "CLIENTE F"}, sorted(r)
    a = r["CLIENTE A"]
    assert a.propostas == 2 and a.indice_da_proposta == 1, "duplicar parte da proposta mais recente (2 dias atras)"
    assert set(a.bancos_tentados) == {"Portobank", "Santander"}, "a grafia da lista de config.py vale sobre a digitada ('portobank')"
    assert set(a.bancos_nao_tentados) == {"Medicalsan", "Smart", "Mova HTM", "Gloriabank"}, "conhecidos + usados, menos os tentados; 'Todos' nunca"
    assert "Todos" not in a.bancos_nao_tentados and "TODOS" not in a.bancos_nao_tentados
    print("OK: quem tem TODAS as propostas negadas entra, com bancos tentados e os que faltam.")

    assert r["CLIENTE D"].bancos_tentados == () and "Todos" not in r["CLIENTE D"].bancos_nao_tentados
    assert r["10000000005"].cadastrado is False and r["CLIENTE A"].cadastrado is True
    f = r["CLIENTE F"]
    assert f.indice_da_proposta == 8, "no mesmo dia, a proposta que esta mais abaixo no arquivo e a mais recente"
    print("OK: 'Todos' nao conta como banco; cliente sem cadastro fica marcado; desempate pela linha do arquivo.")

    ordem = [c.cliente or c.cpf for c in dash.para_reenviar(df, bancos_conhecidos=[])]
    assert ordem == ["CLIENTE A", "CLIENTE F", "CLIENTE D", "10000000005"], ordem  # mais recente primeiro (2, 3, 20, 40 dias)
    print("OK: os mais recentes primeiro.")

    intervalo = (pd.Timestamp(_dias_atras(4)), pd.Timestamp(_dias_atras(0)))
    no_periodo = [c.cliente for c in dash.para_reenviar(df, intervalo, bancos_conhecidos=[])]
    assert no_periodo == ["CLIENTE A", "CLIENTE F"], "com periodo: so quem teve a ULTIMA proposta nele"
    assert dash.para_reenviar(df, (pd.Timestamp(_dias_atras(400)), pd.Timestamp(_dias_atras(300)))) == []
    assert dash.para_reenviar(vazio()) == []
    print("OK: o periodo olha a ultima proposta do cliente; periodo sem ninguem e sem propostas -> lista vazia.")

    padrao = dash.para_reenviar(df)
    sugeridos = {b for c in padrao for b in c.bancos_nao_tentados}
    assert "Todos" not in sugeridos and "Hubcred BV" in sugeridos, "sem a lista explicita, usa os bancos de config.py (menos 'Todos')"
    print("OK: por padrao usa a lista de bancos conhecidos de config.py.")


def testar_qualidade() -> None:
    linha("8) Qualidade dos dados")
    df = montar(
        dict(), dict(**{"VALOR (R$)": float("nan")}), dict(**{"VALOR (R$)": float("nan")}), dict(MESES=float("nan")), dict(BANCO=""), dict(STATUS=""),
    )
    q = {c.chave: c for c in dash.qualidade_dos_dados(df)}
    assert [c.rotulo for c in dash.qualidade_dos_dados(df)] == ["Valor", "Meses", "Banco", "Status"]
    assert (q[dash.ATENCAO_SEM_VALOR].preenchidos, q[dash.ATENCAO_SEM_VALOR].total) == (4, 6)
    assert abs(q[dash.ATENCAO_SEM_VALOR].percentual - 4 / 6 * 100) < 1e-9
    assert q[dash.ATENCAO_SEM_VALOR].indices_pendentes == (1, 2)
    assert q[dash.FILTRO_SEM_MESES].indices_pendentes == (3,) and q[dash.FILTRO_SEM_BANCO].indices_pendentes == (4,) and q[dash.FILTRO_SEM_STATUS].indices_pendentes == (5,)
    for chave, campo in q.items():
        assert dash.indices_do_filtro(df, dash.FiltroDoDashboard(chave, "x")) == set(campo.indices_pendentes), chave
    print("OK: % preenchido, quantas e quais estao pendentes (e o filtro abre exatamente essas).")

    completo = dash.qualidade_dos_dados(montar(dict(), dict()))
    assert all(c.percentual == 100.0 and c.indices_pendentes == () for c in completo)
    zero = dash.qualidade_dos_dados(vazio())
    assert all(c.total == 0 and c.percentual is None and c.indices_pendentes == () for c in zero)
    print("OK: tudo preenchido = 100%; sem propostas = sem percentual (nunca divisao por zero).")


def testar_resumo() -> None:
    linha("9) Resumo para copiar")
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
    linha("10) Visao do vendedor (minhas em analise / a efetivar / clientes sem proposta)")
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
    linha("11) Bordas gerais: nenhum quebra com propostas vazias")
    v = vazio()
    dash.indicadores_do_topo(v)
    assert dash.funil_por_etapa(v) and dash.por_banco(v).empty and dash.para_reenviar(v) == [] and dash.precisa_de_atencao(v) == []
    assert all(c.total == 0 for c in dash.qualidade_dos_dados(v))
    # o mesmo, como o app monta o de um vendedor SEM nenhuma proposta: le a planilha (colunas de texto) e filtra -> 0 linhas
    cheias = montar(dict(VENDEDOR="OUTRA PESSOA"), dict(VENDEDOR="OUTRA PESSOA"))
    filtradas = cheias[cheias["VENDEDOR"] == "FULANO SEM PROPOSTAS"]
    assert len(filtradas) == 0
    dash.indicadores_do_topo(filtradas)
    dash.funil_por_etapa(filtradas)
    dash.por_banco(filtradas)
    dash.precisa_de_atencao(filtradas)
    dash.qualidade_dos_dados(filtradas)
    dash.para_reenviar(filtradas)
    assert dash.resumo_para_copiar(filtradas) == "Nenhuma proposta."
    print("OK: sem propostas (vazias ou filtradas ate zero) nenhuma funcao do painel quebra.")

    # periodo sem dados: filtra ate ficar vazio e o painel todo responde vazio
    velhas = montar(dict(DATA=_dias_atras(400)), dict(DATA=_dias_atras(500)))
    do_periodo = dash.filtrar_por_periodo(velhas, dash.intervalo_do_periodo(dash.PERIODO_7_DIAS))
    assert do_periodo.empty and dash.indicadores_do_topo(do_periodo)["total"] == 0
    assert dash.comparar_periodos(dash.indicadores_do_topo(do_periodo), dash.indicadores_do_topo(velhas)) is None
    print("OK: periodo sem dados -> painel vazio e sem comparacao.")


def main() -> None:
    testar_periodos()
    testar_indicadores()
    testar_comparacao()
    testar_atencao()
    testar_funil()
    testar_por_banco()
    testar_para_reenviar()
    testar_qualidade()
    testar_resumo()
    testar_visao_do_vendedor()
    testar_casos_de_borda_gerais()
    linha("TUDO OK")


if __name__ == "__main__":
    main()
