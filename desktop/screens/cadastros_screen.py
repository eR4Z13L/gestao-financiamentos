"""Tela Cadastros - as listas de apoio do app (Bancos, Vendedores; depois Equipamentos), em cards, uma secao embaixo
da outra numa pagina que rola, com uma busca unica no topo que filtra todas. So o ADMIN acessa (nem aparece no menu
pro VENDEDOR - ver desktop/main_window.py). Cada secao e a peca desktop/widgets/cadastro_em_cards.py.

Se um dia as secoes ficarem grandes demais pra uma pagina so, viram telas separadas - so se for necessario.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QVBoxLayout, QWidget

from desktop.vigia_do_arquivo import VigiaDoArquivo
from desktop.widgets.cadastro_bancos import CadastroBancos
from desktop.widgets.cadastro_vendedores import CadastroVendedores


class CadastrosScreen(QWidget):
    dados_atualizados = Signal()  # algo foi gravado (ex.: renomear um banco muda propostas): as outras telas releem

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._vigia = VigiaDoArquivo()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        topo = QHBoxLayout()
        titulo = QLabel("🗂️ Cadastros")
        titulo.setProperty("role", "titulo")
        topo.addWidget(titulo)
        topo.addStretch()
        self.busca = QLineEdit()
        self.busca.setPlaceholderText("Buscar em todos os cadastros")
        self.busca.setClearButtonEnabled(True)
        self.busca.setMinimumWidth(280)
        self.busca.textChanged.connect(self._filtrar)
        topo.addWidget(self.busca)
        layout.addLayout(topo)

        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QFrame.Shape.NoFrame)
        rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        conteudo = QWidget()
        conteudo.setProperty("role", "transparente")
        rolagem.setWidget(conteudo)
        layout.addWidget(rolagem, stretch=1)
        corpo = QVBoxLayout(conteudo)
        corpo.setContentsMargins(0, 0, 12, 0)  # a folga da direita e da barra de rolagem
        corpo.setSpacing(16)

        self.bancos = CadastroBancos(dentro_de_pagina=True)
        self.vendedores = CadastroVendedores(dentro_de_pagina=True)
        self.secoes = [self.bancos, self.vendedores]
        for secao in self.secoes:
            secao.alterado.connect(self._ao_alterar)
            corpo.addWidget(secao)
        corpo.addStretch()
        self._vigia.registrar_leitura()

    def _filtrar(self, texto: str) -> None:
        for secao in self.secoes:
            secao.busca.setText(texto)

    def _ao_alterar(self) -> None:
        self._vigia.registrar_leitura()  # a mudanca foi daqui: nao precisa reler tudo no proximo tique
        self.dados_atualizados.emit()

    def recarregar(self) -> None:
        self._vigia.registrar_leitura()
        for secao in self.secoes:
            secao.recarregar()  # cada secao preserva o que estiver sendo digitado

    def showEvent(self, evento) -> None:
        super().showEvent(evento)
        if self._vigia.mudou_desde_a_leitura():  # ex.: baixou da nuvem ou restaurou um backup
            self.recarregar()

    def recarregar_se_mudou(self) -> None:
        """Chamado a cada tique da janela com esta tela aberta: planilha mudou por fora -> rele as listas."""
        if self._vigia.mudou_desde_a_leitura():
            self.recarregar()
