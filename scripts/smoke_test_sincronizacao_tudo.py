"""Testa core/sincronizacao.py (sincronizar_tudo_agora): relê as 4 abas do disco e
dispara a sincronização de cada uma, mesmo sem nada ter mudado. Rede sempre
substituída por uma falsa (nenhum byte sai da máquina) - mesmo padrão de
smoke_test_sincronizacao_estado.py. Planilha fictícia numa pasta temporária.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_sincronizacao_tudo.py
"""

from __future__ import annotations

import logging
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl

import config
config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
import fixture_ficticia as fx
from core import data_store as bd
from core import sessao as sessao_mod
from core import sheets_sync
from core import sincronizacao as sincronizacao_mod
from core import vendedores as vendedores_mod
from fixture_ficticia import ColetorDeLog


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _esperar(condicao, limite_s: float = 5.0) -> None:
    fim = time.monotonic() + limite_s
    while not condicao():
        assert time.monotonic() < fim, "tempo esgotado esperando a sincronizacao falsa terminar"
        time.sleep(0.01)


def _criar_planilha_vazia(caminho: Path) -> None:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for nome, colunas in (
        (bd.ABA_CLIENTES, bd.CLIENTES_COLUNAS),
        (bd.ABA_EQUIPAMENTOS, bd.EQUIPAMENTOS_COLUNAS),
        (bd.ABA_PROPOSTAS, bd.PROPOSTAS_COLUNAS),
        (bd.ABA_VENDEDORES, bd.VENDEDORES_COLUNAS),
    ):
        wb.create_sheet(nome).append(colunas)
    wb.save(caminho)


class _RedeFalsa:
    """Troca o envio real por um falso (so registra quem foi chamado) e liga a flag."""

    def __init__(self):
        self.chamadas: list[tuple[str, int]] = []  # (aba, numero de linhas do df)
        self.log = ColetorDeLog()

    def _envio(self, nome_aba, df):
        self.chamadas.append((nome_aba, len(df)))

    def __enter__(self):
        registrador = logging.getLogger(sheets_sync.__name__)
        registrador.addHandler(self.log)
        self._propagava = registrador.propagate
        registrador.propagate = False
        self._original = sheets_sync._sincronizar_agora

        def _sem_rede(*_a, **_k):
            raise AssertionError("o teste tentou acessar o Google de verdade")

        self._cliente_original = sheets_sync._obter_cliente
        sheets_sync._obter_cliente = _sem_rede
        sheets_sync._sincronizar_agora = self._envio
        sheets_sync._reiniciar_estado()
        config.SINCRONIZACAO_GOOGLE_ATIVADA = True
        return self

    def __exit__(self, *_exc):
        config.SINCRONIZACAO_GOOGLE_ATIVADA = False
        sheets_sync._sincronizar_agora = self._original
        sheets_sync._obter_cliente = self._cliente_original
        sheets_sync._reiniciar_estado()
        registrador = logging.getLogger(sheets_sync.__name__)
        registrador.removeHandler(self.log)
        registrador.propagate = self._propagava


def testar_sincronizar_tudo_agora(arquivo: Path) -> None:
    linha("1) sincronizar_tudo_agora() dispara as 4 abas, com o conteudo ATUAL do disco")
    vendedores_mod.adicionar_vendedor("Vendedora Da Fila")

    with _RedeFalsa() as rede:
        sincronizacao_mod.sincronizar_tudo_agora(arquivo)
        _esperar(lambda: sheets_sync.estado_atual().em_andamento == 0)
        abas_chamadas = {aba for aba, _n in rede.chamadas}
        assert abas_chamadas == {bd.ABA_CLIENTES, bd.ABA_EQUIPAMENTOS, bd.ABA_PROPOSTAS, bd.ABA_VENDEDORES, bd.ABA_BANCOS}, abas_chamadas
        assert sheets_sync.estado_atual().nivel == sheets_sync.NIVEL_OK
        _, linhas_vendedores = next(c for c in rede.chamadas if c[0] == bd.ABA_VENDEDORES)
        assert linhas_vendedores == len(vendedores_mod.listar_vendedores()), "leu o estado ATUAL, com o vendedor novo"
    print(f"OK: as 4 abas foram sincronizadas ({sorted(abas_chamadas)}), com os dados atuais do disco.")


def testar_sincronizar_tudo_agora_reflete_edicao_local(arquivo: Path) -> None:
    linha("2) sincronizar_tudo_agora() sempre relê do disco (nao um snapshot antigo)")
    with _RedeFalsa() as rede:
        vendedores_mod.adicionar_vendedor("Vendedora Antes")
        sincronizacao_mod.sincronizar_tudo_agora(arquivo)
        _esperar(lambda: sheets_sync.estado_atual().em_andamento == 0)
        _, antes = next(c for c in rede.chamadas if c[0] == bd.ABA_VENDEDORES)

        vendedores_mod.adicionar_vendedor("Vendedora Depois")
        rede.chamadas.clear()
        sincronizacao_mod.sincronizar_tudo_agora(arquivo)
        _esperar(lambda: sheets_sync.estado_atual().em_andamento == 0)
        _, depois = next(c for c in rede.chamadas if c[0] == bd.ABA_VENDEDORES)

        assert depois == antes + 1, "a segunda chamada leu o vendedor cadastrado depois da primeira"
    print("OK: cada chamada relê o arquivo na hora - reflete uma edição feita entre uma chamada e outra.")


def testar_sincronizar_tudo_agora_entra_na_fila_se_falhar(arquivo: Path) -> None:
    linha("3) uma falha em sincronizar_tudo_agora() entra na fila de repeticao, do jeito normal")

    def sempre_falha(nome_aba, df):
        raise RuntimeError(f"sem internet ao sincronizar {nome_aba} (falso)")

    logging.getLogger(sheets_sync.__name__).addHandler(logging.NullHandler())
    original = sheets_sync._sincronizar_agora
    cliente_original = sheets_sync._obter_cliente
    sheets_sync._obter_cliente = lambda: (_ for _ in ()).throw(AssertionError("sem rede de verdade"))
    sheets_sync._sincronizar_agora = sempre_falha
    sheets_sync._reiniciar_estado()
    config.SINCRONIZACAO_GOOGLE_ATIVADA = True
    try:
        sincronizacao_mod.sincronizar_tudo_agora(arquivo)
        _esperar(lambda: sheets_sync.estado_atual().em_andamento == 0)
        assert set(sheets_sync._pendentes) == {bd.ABA_CLIENTES, bd.ABA_EQUIPAMENTOS, bd.ABA_PROPOSTAS, bd.ABA_VENDEDORES, bd.ABA_BANCOS}
        assert sheets_sync.estado_atual().nivel == sheets_sync.NIVEL_FALHOU
    finally:
        config.SINCRONIZACAO_GOOGLE_ATIVADA = False
        sheets_sync._sincronizar_agora = original
        sheets_sync._obter_cliente = cliente_original
        sheets_sync._reiniciar_estado()
    print("OK: se 'Sincronizar agora' falhar, as 4 abas ficam na fila de repetição normal (E9).")


def main() -> None:
    registro_antes = fx.instantaneo_do_registro()
    tmp = Path(tempfile.mkdtemp(prefix="_smoke_sync_tudo_"))
    try:
        arquivo = tmp / "controle.xlsx"
        _criar_planilha_vazia(arquivo)
        fx.apontar_modulos_para(arquivo)
        sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))

        testar_sincronizar_tudo_agora(arquivo)
        testar_sincronizar_tudo_agora_reflete_edicao_local(arquivo)
        testar_sincronizar_tudo_agora_entra_na_fila_se_falhar(arquivo)

        linha("TUDO OK")
    finally:
        fx.restaurar_modulos()
        sessao_mod.encerrar()
        shutil.rmtree(tmp, ignore_errors=True)
        assert fx.instantaneo_do_registro() == registro_antes, "não pode ter mexido no registro real"


if __name__ == "__main__":
    main()
