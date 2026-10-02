"""Testa o botão "Sincronizar agora" da aba "Sincronização e backup" da tela Administração
(desktop/screens/usuarios_screen.py): dispara as 4 abas, avisa quando a sincronização está
desativada, e não quebra se a rede (falsa) falhar. Rede sempre substituída - nenhum byte sai
da máquina. Planilha fictícia numa pasta temporária, nunca em data/.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_administracao_sincronizacao.py
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl
from PySide6.QtWidgets import QApplication, QMessageBox

import config
config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
import fixture_ficticia as fx
from core import data_store as bd
from core import sessao as sessao_mod
from core import sheets_sync
from desktop.screens.usuarios_screen import UsuariosScreen
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
    def __init__(self, envio):
        self._envio = envio
        self.log = ColetorDeLog()

    def __enter__(self):
        registrador = logging.getLogger(sheets_sync.__name__)
        registrador.addHandler(self.log)
        self._propagava = registrador.propagate
        registrador.propagate = False
        self._original = sheets_sync._sincronizar_agora
        self._cliente_original = sheets_sync._obter_cliente

        def _sem_rede(*_a, **_k):
            raise AssertionError("o teste tentou acessar o Google de verdade")

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


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    registro_antes = fx.instantaneo_do_registro()
    tmp = Path(tempfile.mkdtemp(prefix="_smoke_admin_sync_"))
    fx.isolar_preferencias(tmp)

    mensagens: list[str] = []

    def _stub(*args, **kwargs):
        mensagens.append(args[2] if len(args) > 2 else "")
        return QMessageBox.StandardButton.Ok

    QMessageBox.warning = staticmethod(_stub)
    QMessageBox.critical = staticmethod(_stub)
    QMessageBox.information = staticmethod(_stub)

    try:
        arquivo = tmp / "controle.xlsx"
        _criar_planilha_vazia(arquivo)
        fx.apontar_modulos_para(arquivo)
        sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))

        linha("1) Sincronização desativada: o botão avisa e não dispara nada")
        assert config.SINCRONIZACAO_GOOGLE_ATIVADA is False
        tela = UsuariosScreen()
        antes = len(mensagens)
        tela._sincronizar_agora()
        assert len(mensagens) == antes + 1
        assert "desativada" in mensagens[-1].lower()
        assert sheets_sync.estado_atual().em_andamento == 0
        print("OK: com a sincronização desligada, o botão avisa e não tenta nada.")

        chamadas = []

        def envio_ok(nome_aba, df):
            chamadas.append(nome_aba)

        linha("2) Sincronização ativada: dispara as 4 abas e avisa que iniciou")
        with _RedeFalsa(envio_ok):
            antes = len(mensagens)
            tela._sincronizar_agora()
            _esperar(lambda: sheets_sync.estado_atual().em_andamento == 0)
            assert len(mensagens) == antes + 1
            assert "enviadas para sincronizar" in mensagens[-1].lower()
            assert set(chamadas) == {bd.ABA_CLIENTES, bd.ABA_EQUIPAMENTOS, bd.ABA_PROPOSTAS, bd.ABA_VENDEDORES, bd.ABA_BANCOS}, chamadas
        print(f"OK: clicar em 'Sincronizar agora' disparou as 4 abas ({sorted(set(chamadas))}) e avisou.")

        linha("3) Uma falha (rede fora) não quebra o botão - a aba fica na fila de repetição")

        def envio_falha(nome_aba, df):
            raise RuntimeError("sem internet (falso)")

        with _RedeFalsa(envio_falha):
            antes = len(mensagens)
            tela._sincronizar_agora()  # nao pode levantar
            _esperar(lambda: sheets_sync.estado_atual().em_andamento == 0)
            assert len(mensagens) == antes + 1, "o botao ainda avisa que iniciou (a falha e so depois, em background)"
            assert sheets_sync.estado_atual().nivel == sheets_sync.NIVEL_FALHOU
            assert set(sheets_sync._pendentes) == {bd.ABA_CLIENTES, bd.ABA_EQUIPAMENTOS, bd.ABA_PROPOSTAS, bd.ABA_VENDEDORES, bd.ABA_BANCOS}
        print("OK: uma falha de rede não quebra o botão - as 4 abas ficam pendentes pra fila tentar de novo.")

        linha("TUDO OK")
    finally:
        fx.restaurar_modulos()
        sessao_mod.encerrar()
        shutil.rmtree(tmp, ignore_errors=True)
        assert fx.instantaneo_do_registro() == registro_antes, "não pode ter mexido no registro real"


if __name__ == "__main__":
    main()
