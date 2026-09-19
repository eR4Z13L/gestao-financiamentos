"""Janela principal: barra lateral (menu de navegacao + botao de recolher no
topo + botao de tema embaixo) e area de conteudo (QStackedWidget), sem barra
superior separada.

Pra adicionar uma tela nova: acrescenta uma tupla (icone, rotulo, tela) em
_construir_itens() - a lista lateral e o stack ficam sincronizados
automaticamente pelo indice (mesma posicao nos dois).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core import sessao as sessao_mod
from desktop import settings as settings_mod
from desktop.screens.dashboard_screen import DashboardScreen
from desktop.screens.ficha_cliente_screen import FichaClienteScreen
from desktop.screens.propostas_screen import PropostasScreen
from desktop.screens.usuarios_screen import UsuariosScreen
from desktop.theme import TEMA_CLARO, TEMA_ESCURO, build_stylesheet

_LARGURA_EXPANDIDA = 230
_LARGURA_RECOLHIDA = 60


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gestão de Financiamentos")
        self.resize(1200, 800)

        self._itens = self._construir_itens()
        self._menu_recolhido = settings_mod.obter_sidebar_recolhida()
        self._tema_atual = settings_mod.obter_tema()

        self._paginas = QStackedWidget()
        for _icone, _rotulo, tela in self._itens:
            self._paginas.addWidget(tela)

        sidebar = self._construir_sidebar()
        self._menu.currentRowChanged.connect(self._paginas.setCurrentIndex)
        self._menu.setCurrentRow(0)

        corpo = QWidget()
        layout = QHBoxLayout(corpo)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(sidebar)
        layout.addWidget(self._paginas, stretch=1)
        self.setCentralWidget(corpo)

        self._aplicar_estado_sidebar()
        self._atualizar_botao_tema()

    @staticmethod
    def _construir_itens() -> list[tuple[str, str, QWidget]]:
        itens = [
            ("📊", "Dashboard de Propostas", DashboardScreen()),
            ("🗂️", "Ficha de Cliente", FichaClienteScreen()),
            ("📋", "Todas as Propostas", PropostasScreen()),
        ]
        # gestao de usuarios (trocar a propria senha, cadastrar vendedor,
        # redefinir senha de vendedor) e coisa de ADMIN - nem aparece no
        # menu pro VENDEDOR, que so tem acesso de leitura mesmo
        if sessao_mod.eh_admin():
            itens.append(("👤", "Usuários", UsuariosScreen()))
        return itens

    def _construir_sidebar(self) -> QWidget:
        sidebar = QFrame()
        self._sidebar = sidebar
        sidebar.setProperty("role", "sidebar")
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        cabecalho = QWidget()
        layout_cabecalho = QHBoxLayout(cabecalho)
        layout_cabecalho.setContentsMargins(14, 16, 14, 12)
        layout_cabecalho.setSpacing(10)

        self._botao_recolher = QPushButton("☰")
        self._botao_recolher.setProperty("role", "botao_icone")
        self._botao_recolher.setFixedSize(32, 32)
        self._botao_recolher.setToolTip("Recolher/expandir menu")
        self._botao_recolher.clicked.connect(self._alternar_sidebar)
        layout_cabecalho.addWidget(self._botao_recolher)

        self._titulo_app = QLabel("Financiamentos")
        self._titulo_app.setProperty("role", "titulo_app")
        layout_cabecalho.addWidget(self._titulo_app)
        layout_cabecalho.addStretch()
        layout.addWidget(cabecalho)

        # identifica quem esta logado e com que nivel de acesso - fica visivel
        # o tempo todo, pra nunca deixar duvida sobre estar em modo leitura
        sessao = sessao_mod.atual()
        if sessao is not None:
            papel_rotulo = "Administrador" if sessao.papel == sessao_mod.PAPEL_ADMIN else "Vendedor (somente leitura)"
            self._identidade = QLabel(f"👤 {sessao.nome_usuario}\n{papel_rotulo}")
        else:
            self._identidade = QLabel("")
        self._identidade.setProperty("role", "secundario")
        self._identidade.setWordWrap(True)
        self._identidade.setContentsMargins(14, 0, 14, 12)
        layout.addWidget(self._identidade)

        self._menu = QListWidget()
        self._menu.setFrameShape(QFrame.Shape.NoFrame)
        # so 3 itens fixos, nunca precisa rolar - e o menu ja e retratil, que
        # e a forma de "economizar espaco" aqui, entao a barra de rolagem so
        # atrapalha visualmente
        self._menu.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._menu.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for _icone, _rotulo, _tela in self._itens:
            QListWidgetItem(self._menu)
        layout.addWidget(self._menu, stretch=1)

        self._botao_tema = QPushButton()
        self._botao_tema.setProperty("role", "botao_tema")
        self._botao_tema.clicked.connect(self._alternar_tema)
        layout.addWidget(self._botao_tema)

        return sidebar

    # -- menu lateral retratil -----------------------------------------------

    def _alternar_sidebar(self) -> None:
        self._menu_recolhido = not self._menu_recolhido
        settings_mod.definir_sidebar_recolhida(self._menu_recolhido)
        self._aplicar_estado_sidebar()

    def _aplicar_estado_sidebar(self) -> None:
        self._sidebar.setFixedWidth(_LARGURA_RECOLHIDA if self._menu_recolhido else _LARGURA_EXPANDIDA)

        # padding dos itens e diferente recolhido x expandido (ver theme.py) -
        # precisa reaplicar o estilo pra QSS notar que a propriedade mudou
        self._menu.setProperty("recolhido", self._menu_recolhido)
        self._menu.style().unpolish(self._menu)
        self._menu.style().polish(self._menu)

        self._titulo_app.setVisible(not self._menu_recolhido)
        self._identidade.setVisible(not self._menu_recolhido)

        alinhamento = (
            Qt.AlignmentFlag.AlignCenter
            if self._menu_recolhido
            else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        for i, (icone, rotulo, _tela) in enumerate(self._itens):
            item = self._menu.item(i)
            item.setText(icone if self._menu_recolhido else f"{icone}   {rotulo}")
            item.setToolTip(rotulo if self._menu_recolhido else "")
            item.setTextAlignment(alinhamento)

        self._atualizar_botao_tema()

    # -- tema -----------------------------------------------------------------

    def _alternar_tema(self) -> None:
        self._tema_atual = TEMA_CLARO if self._tema_atual == TEMA_ESCURO else TEMA_ESCURO
        settings_mod.definir_tema(self._tema_atual)
        QApplication.instance().setStyleSheet(build_stylesheet(self._tema_atual))
        self._atualizar_botao_tema()

    def _atualizar_botao_tema(self) -> None:
        # o botao mostra a ACAO (pra que tema ele muda ao clicar), nao o tema atual
        if self._tema_atual == TEMA_ESCURO:
            icone, rotulo, dica = "☀️", "Modo Claro", "Mudar para o tema claro"
        else:
            icone, rotulo, dica = "🌙", "Modo Escuro", "Mudar para o tema escuro"
        self._botao_tema.setText(icone if self._menu_recolhido else f"{icone}   {rotulo}")
        self._botao_tema.setToolTip(dica)
