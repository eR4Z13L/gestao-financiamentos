"""Testa o ESTADO da sincronizacao com o Google Sheets (core/sheets_sync.py) que o indicador da
barra lateral le: sincronizando / ok / falhou, seguro entre threads e sem rede.

A funcao que de fato fala com o Google (_sincronizar_agora) e SUBSTITUIDA por uma falsa em todo
teste, e o acesso ao cliente do Google (_obter_cliente) por uma que derruba o teste se for
chamada - nenhum byte sai da maquina. A flag da sincronizacao so e ligada com a falsa no lugar
e sempre desligada no fim.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_sincronizacao_estado.py
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
from core import sheets_sync
from core.sheets_sync import EstadoSincronizacao
from fixture_ficticia import ColetorDeLog  # o coletor de log compartilhado dos testes

DF = pd.DataFrame({"A": [1, 2]})  # so um dado qualquer pra "sincronizar"


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _esperar(condicao, limite_s: float = 5.0) -> None:
    fim = time.monotonic() + limite_s
    while not condicao():
        assert time.monotonic() < fim, "tempo esgotado esperando a sincronizacao falsa terminar"
        time.sleep(0.01)


class _Ambiente:
    """Troca o envio real por um falso e liga a flag; desfaz tudo ao sair."""

    def __init__(self, envio_falso):
        self._envio_falso = envio_falso
        self.log = ColetorDeLog()

    def __enter__(self):
        registrador = logging.getLogger(sheets_sync.__name__)
        registrador.addHandler(self.log)
        self._propagava = registrador.propagate
        registrador.propagate = False
        self._envio_original = sheets_sync._sincronizar_agora
        self._cliente_original = sheets_sync._obter_cliente

        def _sem_rede(*_a, **_k):
            raise AssertionError("o teste tentou acessar o Google de verdade")

        sheets_sync._obter_cliente = _sem_rede
        sheets_sync._sincronizar_agora = self._envio_falso  # ANTES de ligar a flag
        sheets_sync._reiniciar_estado()
        config.SINCRONIZACAO_GOOGLE_ATIVADA = True
        return self

    def __exit__(self, *_exc):
        config.SINCRONIZACAO_GOOGLE_ATIVADA = False
        sheets_sync._sincronizar_agora = self._envio_original
        sheets_sync._obter_cliente = self._cliente_original
        sheets_sync._reiniciar_estado()
        registrador = logging.getLogger(sheets_sync.__name__)
        registrador.removeHandler(self.log)
        registrador.propagate = self._propagava


def testar_desativada() -> None:
    linha("1) Sincronizacao desativada: nada acontece")
    sheets_sync._reiniciar_estado()
    chamadas = []
    original = sheets_sync._sincronizar_agora
    sheets_sync._sincronizar_agora = lambda *a: chamadas.append(a)
    try:
        sheets_sync.sincronizar_em_background("ABA", DF)
    finally:
        sheets_sync._sincronizar_agora = original
    estado = sheets_sync.estado_atual()
    assert estado.ativada is False and estado.nivel == sheets_sync.NIVEL_DESATIVADA
    assert estado.em_andamento == 0 and estado.ultimo_sucesso is None and not chamadas
    print("OK: com a flag desligada nada e disparado e o nivel e 'desativada'.")


def testar_sincronizando_e_ok() -> None:
    linha("2) Sincronizando -> ok")
    liberar = threading.Event()
    iniciou = threading.Event()

    def envio_lento(aba, df):
        iniciou.set()
        assert liberar.wait(5), "o teste nao liberou o envio"

    with _Ambiente(envio_lento):
        assert sheets_sync.estado_atual().nivel == sheets_sync.NIVEL_AGUARDANDO  # ligada, mas nada tentado
        sheets_sync.sincronizar_em_background("ABA", DF)
        assert iniciou.wait(5)
        estado = sheets_sync.estado_atual()
        assert estado.em_andamento == 1 and estado.nivel == sheets_sync.NIVEL_SINCRONIZANDO
        print("OK: enquanto o envio nao termina, 1 em andamento e nivel 'sincronizando'.")

        liberar.set()
        _esperar(lambda: sheets_sync.estado_atual().em_andamento == 0)
        estado = sheets_sync.estado_atual()
        assert estado.nivel == sheets_sync.NIVEL_OK
        assert estado.ultimo_sucesso is not None and abs(datetime.now() - estado.ultimo_sucesso) < timedelta(seconds=5)
        assert estado.ultima_falha is None and estado.ultimo_erro == ""
        print("OK: terminou -> nivel 'ok' com a hora do sucesso.")


def testar_falha_e_recuperacao() -> None:
    linha("3) Falhou -> ok de novo; nunca propaga o erro")
    resultados = ["falha", "ok"]

    def envio(aba, df):
        if resultados.pop(0) == "falha":
            raise RuntimeError("sem internet (falso)")

    with _Ambiente(envio) as ambiente:
        sheets_sync.sincronizar_em_background("ABA", DF)  # nao pode levantar
        _esperar(lambda: sheets_sync.estado_atual().em_andamento == 0)
        estado = sheets_sync.estado_atual()
        assert estado.nivel == sheets_sync.NIVEL_FALHOU, estado
        assert len(ambiente.log.avisos_com_traceback()) == 1, "a falha tem que ir pro log, com o traceback"
        assert "RuntimeError" in estado.ultimo_erro and "sem internet (falso)" in estado.ultimo_erro
        assert estado.ultima_falha is not None and estado.ultimo_sucesso is None
        print(f"OK: falha vira nivel 'falhou' com o erro guardado ({estado.ultimo_erro!r}).")

        sheets_sync.sincronizar_em_background("ABA", DF)
        _esperar(lambda: sheets_sync.estado_atual().em_andamento == 0)
        estado = sheets_sync.estado_atual()
        assert estado.nivel == sheets_sync.NIVEL_OK, "uma sincronizacao boa depois da falha volta pra 'ok'"
        print("OK: a proxima sincronizacao boa volta o nivel pra 'ok' (a falha antiga fica so no historico).")


def testar_varias_ao_mesmo_tempo() -> None:
    linha("4) Varias em andamento ao mesmo tempo")
    liberar = threading.Event()
    chegaram = threading.Semaphore(0)

    def envio(aba, df):
        chegaram.release()
        assert liberar.wait(5)

    with _Ambiente(envio):
        for aba in ("A", "B", "C"):
            sheets_sync.sincronizar_em_background(aba, DF)
        for _ in range(3):
            assert chegaram.acquire(timeout=5)
        assert sheets_sync.estado_atual().em_andamento == 3
        liberar.set()
        _esperar(lambda: sheets_sync.estado_atual().em_andamento == 0)
        assert sheets_sync.estado_atual().nivel == sheets_sync.NIVEL_OK
        print("OK: 3 envios seguidos contam 3 em andamento e voltam a 0 (nunca negativo, nunca preso).")


def testar_thread_que_nao_inicia() -> None:
    linha("5) Thread que nao consegue iniciar conta como falha (sem contador preso)")

    def envio(aba, df):
        raise AssertionError("nao deveria chegar a rodar")

    with _Ambiente(envio) as ambiente:
        original = threading.Thread

        class _ThreadQueFalha:
            def __init__(self, *a, **k):
                pass

            def start(self):
                raise RuntimeError("nao ha threads disponiveis (falso)")

        threading.Thread = _ThreadQueFalha
        try:
            sheets_sync.sincronizar_em_background("ABA", DF)  # nao pode levantar
        finally:
            threading.Thread = original
        estado = sheets_sync.estado_atual()
        assert estado.em_andamento == 0, "o contador nao pode ficar preso em 1"
        assert estado.nivel == sheets_sync.NIVEL_FALHOU and "nao ha threads" in estado.ultimo_erro
        assert len(ambiente.log.avisos_com_traceback()) == 1, "e a falha ao iniciar tambem vai pro log"
        print("OK: falha ao iniciar a thread vira 'falhou' e o contador volta a 0.")


def testar_erro_comprido_e_nivel() -> None:
    linha("6) Erro comprido e a tabela de niveis")

    def envio(aba, df):
        raise RuntimeError("x" * 5000)

    with _Ambiente(envio):
        sheets_sync.sincronizar_em_background("ABA", DF)
        _esperar(lambda: sheets_sync.estado_atual().em_andamento == 0)
        assert len(sheets_sync.estado_atual().ultimo_erro) <= 400
        print("OK: o erro guardado e cortado em 400 caracteres (o detalhe completo fica no log).")

    agora = datetime(2026, 9, 20, 12, 0)
    antes = agora - timedelta(minutes=5)
    tabela = [
        (EstadoSincronizacao(False, 0, agora, None, ""), sheets_sync.NIVEL_DESATIVADA),
        (EstadoSincronizacao(False, 2, None, agora, "x"), sheets_sync.NIVEL_DESATIVADA),  # desativada vence tudo
        (EstadoSincronizacao(True, 0, None, None, ""), sheets_sync.NIVEL_AGUARDANDO),
        (EstadoSincronizacao(True, 1, agora, None, ""), sheets_sync.NIVEL_SINCRONIZANDO),
        (EstadoSincronizacao(True, 1, None, agora, "x"), sheets_sync.NIVEL_SINCRONIZANDO),  # em andamento vence a falha
        (EstadoSincronizacao(True, 0, agora, None, ""), sheets_sync.NIVEL_OK),
        (EstadoSincronizacao(True, 0, antes, agora, "x"), sheets_sync.NIVEL_FALHOU),  # falha mais recente que o sucesso
        (EstadoSincronizacao(True, 0, agora, antes, "x"), sheets_sync.NIVEL_OK),  # sucesso mais recente que a falha
        (EstadoSincronizacao(True, 0, agora, agora, "x"), sheets_sync.NIVEL_FALHOU),  # empate: assume o pior
        (EstadoSincronizacao(True, 0, None, agora, "x"), sheets_sync.NIVEL_FALHOU),
    ]
    for estado, esperado in tabela:
        assert estado.nivel == esperado, f"{estado} -> {estado.nivel}, esperado {esperado}"
    print(f"OK: {len(tabela)} combinacoes de estado -> nivel.")


def main() -> None:
    testar_desativada()
    testar_sincronizando_e_ok()
    testar_falha_e_recuperacao()
    testar_varias_ao_mesmo_tempo()
    testar_thread_que_nao_inicia()
    testar_erro_comprido_e_nivel()
    assert config.SINCRONIZACAO_GOOGLE_ATIVADA is False
    linha("TUDO OK")


if __name__ == "__main__":
    main()
