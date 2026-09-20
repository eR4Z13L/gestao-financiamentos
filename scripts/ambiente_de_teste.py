"""Ambiente compartilhado pelos testes de tela (barra lateral, Dashboard...): caixas de mensagem falsas (as
reais sao modais e travariam o teste), uma planilha 100% FICTICIA em pasta temporaria, preferencias do app num
.ini temporario (o registro do Windows e conferido antes e depois), o Google Sheets desligado e o acesso ao
cliente dele derrubando o teste se for tentado. Nada aqui toca em dado real.

    with Mensagens() as msgs:
        amb = Ambiente(volumoso=True)
        janela = amb.nova_janela("admin", TEMA_ESCURO)
        ...
        amb.encerrar()
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QMessageBox

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
import fixture_ficticia as fx
from core import clientes as clientes_mod
from core import data_store as bd
from core import data_store_sheets as leitura_sheets
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import sheets_sync
from desktop import settings as settings_mod
from desktop.main_window import MainWindow
from desktop.theme import build_stylesheet


class Mensagens:
    """Troca as caixas de mensagem (modais: travariam o teste) por versoes que so anotam o que
    foi mostrado. `resposta_pergunta` diz o que "o usuario" clica nas perguntas."""

    def __init__(self):
        self.registro: list[tuple[str, str, str]] = []
        self.resposta_pergunta = QMessageBox.StandardButton.Yes
        self._originais = {}

    def __enter__(self):
        for nome in ("warning", "critical", "information", "question"):
            self._originais[nome] = getattr(QMessageBox, nome)
            setattr(QMessageBox, nome, staticmethod(self._fazer_stub(nome)))
        return self

    def __exit__(self, *_exc):
        for nome, original in self._originais.items():
            setattr(QMessageBox, nome, original)

    def _fazer_stub(self, tipo: str):
        def _stub(*args, **_kwargs):
            titulo = args[1] if len(args) > 1 else ""
            texto = args[2] if len(args) > 2 else ""
            self.registro.append((tipo, titulo, texto))
            return self.resposta_pergunta if tipo == "question" else QMessageBox.StandardButton.Ok

        return _stub

    def limpar(self) -> None:
        self.registro.clear()

    def exigir_sem_erros(self, contexto: str) -> None:
        erros = [m for m in self.registro if m[0] in ("warning", "critical")]
        assert not erros, f"{contexto}: apareceu um aviso/erro inesperado: {erros}"

    def exigir_vazio(self, contexto: str) -> None:
        assert not self.registro, f"{contexto}: nenhuma mensagem era esperada, mas apareceu {self.registro}"

    def ultima(self) -> tuple[str, str, str]:
        assert self.registro, "esperava uma mensagem, mas nenhuma apareceu"
        return self.registro[-1]


class Ambiente:
    """A planilha ficticia, as preferencias isoladas e a rede bloqueada; ver o topo do arquivo."""

    def __init__(self, volumoso: bool = False):
        """`volumoso`: a planilha fictícia maior (fixture_ficticia.criar_volumoso) em vez da pequena."""
        self.pasta = Path(tempfile.mkdtemp(prefix="teste_de_tela_"))
        self.registro_antes = fx.instantaneo_do_registro()
        fx.isolar_preferencias(self.pasta)
        self.caminho = fx.criar_volumoso(self.pasta) if volumoso else fx.criar(self.pasta)
        fx.apontar_modulos_para(self.caminho)
        self.janelas: list[MainWindow] = []
        self._tema_aplicado: str | None = None
        self._fontes = (clientes_mod._ler_da_fonte_ativa, propostas_mod._ler_da_fonte_ativa)
        self._clientes_sheets = leitura_sheets._obter_cliente
        self._envio_sheets = sheets_sync._obter_cliente

        # o VENDEDOR le do Google Sheets: aqui le da copia ficticia, filtrando como o app filtra
        def _clientes():
            return sessao_mod.filtrar_por_vendedor_logado(bd.ler_clientes(self.caminho))

        def _propostas():
            return sessao_mod.filtrar_por_vendedor_logado(bd.ler_propostas(self.caminho))

        clientes_mod._ler_da_fonte_ativa = _clientes
        propostas_mod._ler_da_fonte_ativa = _propostas

        def _sem_rede(*_a, **_k):
            raise AssertionError("o teste tentou acessar o Google de verdade")

        leitura_sheets._obter_cliente = _sem_rede
        sheets_sync._obter_cliente = _sem_rede

    def limpar_janelas(self) -> None:
        """Apaga de verdade as janelas criadas ate agora. Sem isso elas se acumulam (dezenas) e cada troca
        de tema repinta TODAS as que estao vivas: o teste ficava lento sem necessidade."""
        # antes de apagar: deixa disparar os QTimer.singleShot(0, ...) pendentes das telas (ex.: a rolagem da
        # Ficha ate um card recem-expandido) - depois de a tela morrer eles imprimiriam um Traceback
        QApplication.processEvents()
        for janela in self.janelas:
            try:
                janela.desligar()
                janela.hide()
                janela.deleteLater()
            except RuntimeError:
                pass  # o controlador do "Sair" ja mandou apagar esta janela: nada a desligar
        self.janelas.clear()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)  # sem event loop, deleteLater nao roda sozinho

    def encerrar(self) -> None:
        self.limpar_janelas()
        clientes_mod._ler_da_fonte_ativa, propostas_mod._ler_da_fonte_ativa = self._fontes
        leitura_sheets._obter_cliente = self._clientes_sheets
        sheets_sync._obter_cliente = self._envio_sheets
        fx.restaurar_modulos()
        sessao_mod.encerrar()
        assert fx.instantaneo_do_registro() == self.registro_antes, (
            "o teste mexeu nas preferencias REAIS do app (registro do Windows)"
        )

    def resetar_preferencias(self) -> None:
        configuracoes = settings_mod._settings()
        configuracoes.clear()
        configuracoes.sync()

    def entrar_como(self, papel: str, nome: str | None = None) -> None:
        """`nome`: com o papel "vendedor", qual vendedor entrou (padrao: "Vendedor Exemplo")."""
        if papel == "admin":
            sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
        else:
            sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_VENDEDOR, nome_usuario=nome or "Vendedor Exemplo"))

    def nova_janela(self, papel: str, tema: str, mostrar: bool = True, nome: str | None = None) -> MainWindow:
        self.entrar_como(papel, nome)
        settings_mod.definir_tema(tema)
        if tema != self._tema_aplicado:  # reaplicar o QSS repinta TODOS os widgets vivos: so quando muda
            QApplication.instance().setStyleSheet(build_stylesheet(tema))
            self._tema_aplicado = tema
        for antiga in self.janelas:
            antiga.hide()  # so a janela nova fica visivel: com varias, atalhos e teclas iriam pra janela errada
        janela = MainWindow()
        self.janelas.append(janela)
        if mostrar:
            janela.show()
            QApplication.processEvents()
        return janela
