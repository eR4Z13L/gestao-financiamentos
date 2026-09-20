"""Testa, sem Qt e sem arquivo nenhum, as regras que a barra lateral usa: iniciais do avatar,
"ha X min" e a contagem de propostas paradas (selo de "Todas as Propostas").

Tudo com DataFrames e nomes inventados - nada da planilha real.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_barra_lateral_regras.py
"""

from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from core import propostas as propostas_mod
from core.formatting import iniciais_do_nome, tempo_decorrido_curto


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def testar_iniciais() -> None:
    linha("1) Iniciais do avatar")
    casos = {
        "Maria Exemplo da Silva": "MS",  # primeira e ultima palavra, sem o "da" do meio
        "Administrador": "A",  # uma palavra so: so a primeira letra
        "  joão   pedro ": "JP",  # espacos sobrando e minusculas
        "édson lima": "ÉL",  # a inicial mantem o acento (maiuscula de "é" e "É")
        "Ana": "A",
        "(teste) - x": "TX",  # pontuacao solta nao vira inicial
        "123 abc": "1A",
        "": "?",  # nunca um avatar vazio
        "   ": "?",
        "-- ..": "?",
        None: "?",
    }
    for nome, esperado in casos.items():
        obtido = iniciais_do_nome(nome)
        assert obtido == esperado, f"iniciais_do_nome({nome!r}) = {obtido!r}, esperado {esperado!r}"
    print(f"OK: {len(casos)} casos de iniciais.")


def testar_tempo_decorrido() -> None:
    linha("2) 'há X min' (tempo_decorrido_curto)")
    casos = [
        (timedelta(seconds=0), "agora"),
        (timedelta(seconds=59), "agora"),
        (timedelta(seconds=60), "há 1 min"),
        (timedelta(minutes=5, seconds=30), "há 5 min"),
        (timedelta(minutes=59, seconds=59), "há 59 min"),
        (timedelta(hours=1), "há 1 h"),
        (timedelta(hours=23, minutes=59), "há 23 h"),
        (timedelta(hours=24), "há 1 dia"),
        (timedelta(hours=49), "há 2 dias"),
        (timedelta(days=30), "há 30 dias"),
        (timedelta(seconds=-120), "agora"),  # relogio ajustado pra tras: nunca "há -2 min"
    ]
    for decorrido, esperado in casos:
        obtido = tempo_decorrido_curto(decorrido)
        assert obtido == esperado, f"tempo_decorrido_curto({decorrido}) = {obtido!r}, esperado {esperado!r}"
    print(f"OK: {len(casos)} casos de tempo decorrido.")


def _propostas(*linhas: tuple) -> pd.DataFrame:
    """(STATUS, TEMPO) -> DataFrame no formato de listar_propostas (so as colunas que a regra le)."""
    return pd.DataFrame(list(linhas), columns=["STATUS", "TEMPO"])


def testar_contar_paradas() -> None:
    linha("3) Contagem de propostas paradas (selo)")
    assert propostas_mod.DIAS_PROPOSTA_PARADA == 7, "o limite combinado e 7 dias"

    # sem nenhuma proposta (planilha vazia, ou vendedor sem propostas)
    assert propostas_mod.contar_paradas(_propostas()) == 0
    print("OK: sem propostas -> 0 (sem quebrar).")

    df = _propostas(
        ("Em Análise", "12 dias"),  # conta
        ("Em Análise", "7 dias"),  # exatamente no limite: "mais de 7" nao inclui
        ("Em Análise", "8 dias"),  # conta
        ("Aprovado", "20 dias"),  # aprovada e ainda nao efetivada segue em aberto: conta
        ("Pré-aprovado", "3 dias"),  # em aberto mas recente
        ("Efetivado", "Encerrado"),  # encerrada
        ("Negado", "Encerrado"),
        ("Negado", "40 dias"),  # negada nunca conta, mesmo que o TEMPO traga dias
        ("", "30 dias"),  # sem status: nao esta encerrada, conta
        ("Em Análise", "-3 dias"),  # data no futuro: nao conta
        ("Em Análise", ""),  # sem TEMPO: nunca se chuta
        ("Em Análise", None),
        ("Em Análise", "texto que nao conhecemos"),
        (None, "15 dias"),  # STATUS ausente (NaN/None): tratado como sem status
        ("Efetivado", "60 dias"),
    )
    assert propostas_mod.contar_paradas(df) == 5, propostas_mod.contar_paradas(df)
    print("OK: conta so as em aberto com mais de 7 dias (limite exato, negadas, efetivadas, futuras e sem TEMPO ficam de fora).")

    # o limite e um parametro: com 10 dias, so 12 (analise), 20 (aprovado), 30 (sem status) e 15 (status None)
    assert propostas_mod.contar_paradas(df, dias=10) == 4, propostas_mod.contar_paradas(df, dias=10)
    # e "mais de": a de exatamente 30 dias e as encerradas (Negado 40, Efetivado 60) nao contam
    assert propostas_mod.contar_paradas(df, dias=30) == 0, propostas_mod.contar_paradas(df, dias=30)
    print("OK: o limite e um parametro (10 dias -> 4; 30 dias -> 0, e as encerradas nunca entram).")

    # tudo sem dias calculaveis
    assert propostas_mod.contar_paradas(_propostas(("Em Análise", ""), ("Em Análise", "Encerrado"))) == 0
    print("OK: nenhuma proposta com dias calculaveis -> 0.")


def testar_dashboard_de_vendedor_sem_propostas() -> None:
    linha("4) Regressao: Dashboard de quem nao tem NENHUMA proposta (vendedor recem-cadastrado)")
    from core import dashboard as dashboard_mod
    from core import data_store as bd

    # como o app monta as propostas de um vendedor sem nenhuma: le a planilha (STATUS e texto) e
    # filtra por ele -> 0 linhas, mas a coluna continua com tipo de texto (era isso que quebrava)
    cheias = pd.DataFrame({"STATUS": ["Aprovado", "Em Análise"], "VALOR (R$)": [1000.0, 2000.0], "VENDEDOR": ["Outra Pessoa", "Outra Pessoa"]})
    vazias = cheias[cheias["VENDEDOR"] == "Fulano Sem Propostas"].reindex(columns=bd.PROPOSTAS_COLUNAS)
    assert len(vazias) == 0

    totais = dashboard_mod.totais_gerais(vazias)
    assert totais["total_propostas"] == 0 and totais["efetivadas"] == 0 and totais["aprovadas_nao_efetivadas"] == 0
    assert totais["taxa_aprovacao"] == 0.0 and totais["valor_aprovado"] == 0.0 and totais["pct_aprovadas_nao_efetivadas"] == 0.0
    assert dashboard_mod.detalhamento_por_status(vazias).empty and dashboard_mod.por_vendedor(vazias).empty
    print("OK: sem propostas, o dashboard calcula tudo zerado (antes: ValueError e a janela nao abria).")

    print("\nOK: regras da barra lateral conferidas.")


def main() -> None:
    testar_iniciais()
    testar_tempo_decorrido()
    testar_contar_paradas()
    testar_dashboard_de_vendedor_sem_propostas()
    linha("TUDO OK")


if __name__ == "__main__":
    main()
