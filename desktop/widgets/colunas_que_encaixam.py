"""Cards em colunas que encaixam: a parte comum da lista de vendas e da lista de propostas.

As colunas dividem a largura visivel de quem rola (quantas couberem sem espremer o card; `uma_coluna` - a Ficha -, so
uma), cada uma empilhando os seus cards, sem buraco embaixo de um card curto: cada card novo vai para a coluna mais
curta e la fica - abrir, fechar ou gravar num card nao tira ninguem do lugar (so outra lista, ou outro numero de
colunas, redistribui). Os cards vem de TAMANHO_PAGINA em TAMANHO_PAGINA ("Carregar mais"), e refazer os cards (depois
de gravar) devolve a rolagem onde estava.

Quem herda diz como criar o card de cada item (`_criar_card`) e qual a chave dele (`_chave`). O formulario aberto num
card sobrevive a montagem (a busca ou um filtro mudou, a tela releu depois de gravar outro card): quem herda diz qual e
ele (`_formulario_aberto`) e, ao criar o card de novo, pega de volta o mesmo (`_formulario_guardado`) - o que foi
digitado nunca some sem perguntar.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

ESPACO = 8
TAMANHO_PAGINA = 30


class ListaEmColunas(QWidget):
    def __init__(self, rolagem: QScrollArea, parent: QWidget | None = None, *, largura_card: int,
                 uma_coluna: bool = False):
        """`rolagem`: quem rola a lista (a da tela) - a posicao e mantida ao refazer os cards. `largura_card`: o mais
        estreito que o card fica. `uma_coluna`: todo card na largura toda (a Ficha)."""
        super().__init__(parent)
        self.setProperty("role", "transparente")
        self._rolagem = rolagem
        self._largura_card = largura_card
        self._uma_coluna = uma_coluna
        self._coluna_do_item: dict[str, int] = {}
        self._distribuidas: list[str] = []
        self._itens: list = []
        self._chaves: list[str] = []  # a de cada card, na ordem dos cards
        self._limite = TAMANHO_PAGINA
        self._colunas = 1
        self._montagens = 0  # so a devolucao da rolagem da montagem mais recente vale (ver _devolver_rolagem)
        self.cards: list[QWidget] = []
        self._guardado: tuple[str, QWidget] | None = None  # (chave, formulario) aberto, entre uma montagem e outra

        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(0, 0, 0, 0)
        self._linha_das_colunas = QHBoxLayout()
        self._linha_das_colunas.setSpacing(ESPACO)
        coluna.addLayout(self._linha_das_colunas)
        self._pilhas: list[QVBoxLayout] = []  # uma por coluna
        rolagem.viewport().installEventFilter(self)  # quantas colunas cabem (ver _largura_disponivel)
        self.vazio = QLabel("", self)
        self.vazio.setProperty("role", "secundario")
        self.vazio.setWordWrap(True)
        coluna.addWidget(self.vazio)
        self.botao_mais = QPushButton("Carregar mais", self)
        self.botao_mais.clicked.connect(self._carregar_mais)
        coluna.addWidget(self.botao_mais, alignment=Qt.AlignmentFlag.AlignLeft)

    # -- o que quem herda diz -----------------------------------------------------------------------

    def _criar_card(self, item) -> QWidget:
        raise NotImplementedError

    def _chave(self, item) -> str:
        raise NotImplementedError

    def _formulario_aberto(self) -> tuple[str, QWidget] | None:
        """(chave, formulario) do formulario aberto num card, para guardar entre as montagens; None: nenhum. A chave
        diz a qual card ele volta (ver _formulario_guardado)."""
        return None

    def _formulario_guardado(self, chave: str) -> QWidget | None:
        """O formulario guardado da montagem anterior, se era desta `chave` (ele volta com o que ja foi digitado)."""
        if self._guardado is None or self._guardado[0] != chave:
            return None
        formulario, self._guardado = self._guardado[1], None
        return formulario

    def _posicao_que_precisa_aparecer(self) -> int | None:
        """A posicao (na lista de itens) de um card que tem que estar entre os carregados mesmo alem da pagina (o
        aberto, por exemplo). None: nenhum."""
        return None

    # -- itens --------------------------------------------------------------------------------------

    def _definir_itens(self, itens: list, texto_vazio: str, voltar_ao_inicio: bool) -> None:
        self._itens = list(itens)
        self.vazio.setText(texto_vazio)
        self._montar(voltar_ao_inicio)

    def total(self) -> int:
        return len(self._itens)

    def _montar(self, voltar_ao_inicio: bool = False) -> None:
        self._montagens += 1
        if voltar_ao_inicio:
            self._limite = TAMANHO_PAGINA
        posicao = self._posicao_que_precisa_aparecer()
        if posicao is not None:
            self._limite = max(self._limite, posicao + 1)
        conteudo = self._rolagem.widget()
        rolagem = self._rolagem.verticalScrollBar().value()
        # a lista nao "encolhe" enquanto os cards sao trocados: sem isso a rolagem caia pro topo a cada gravacao (o
        # card que a pessoa estava usando sumia de vista) - a altura so e solta depois de devolver a posicao
        conteudo.setMinimumHeight(0 if voltar_ao_inicio else conteudo.height())
        aberto = self._formulario_aberto()
        if aberto is not None:  # sai do card que vai ser apagado; escondido e com dono, nunca aparece como janela solta
            aberto[1].hide()
            aberto[1].setParent(self)
            self._guardado = aberto
        for card in self.cards:
            card.hide()  # some ja: o deleteLater so apaga no proximo ciclo
            card.deleteLater()
        self.cards, self._chaves = [], []
        for item in self._itens[: self._limite]:
            self.cards.append(self._criar_card(item))
            self._chaves.append(self._chave(item))
        if self._guardado is not None:  # o card dele nao voltou (fechou, ou a proposta saiu da lista)
            self._guardado[1].deleteLater()
            self._guardado = None
        self.vazio.setVisible(not self._itens and bool(self.vazio.text()))
        self.botao_mais.setVisible(len(self._itens) > self._limite)
        self._posicionar()
        if not voltar_ao_inicio:
            numero = self._montagens
            QTimer.singleShot(0, lambda: self._devolver_rolagem(rolagem, numero))

    def _devolver_rolagem(self, valor: int, numero: int) -> None:
        if numero != self._montagens:
            # outra montagem veio antes de chegar a vez desta (ex.: fechou o formulario e logo abriu outro cliente,
            # que comeca no topo): devolver a posicao velha empurraria a tela nova; quem cuida e a montagem nova
            return
        self._rolagem.verticalScrollBar().setValue(valor)
        self._rolagem.widget().setMinimumHeight(0)

    def _posicionar(self) -> None:
        """Cada card na sua coluna, empilhados na ordem da lista. Item que ainda nao tem coluna vai para a mais curta
        - pela altura dos cards como estao agora."""
        while len(self._pilhas) < self._colunas:
            pilha = QVBoxLayout()
            pilha.setSpacing(ESPACO)
            self._linha_das_colunas.addLayout(pilha, 1)
            self._pilhas.append(pilha)
        while len(self._pilhas) > self._colunas:
            pilha = self._pilhas.pop()
            while pilha.count():
                pilha.takeAt(0)
            self._linha_das_colunas.removeItem(pilha)
            pilha.deleteLater()
        chaves = list(self._chaves)
        if chaves[: len(self._distribuidas)] != self._distribuidas:  # outra lista, nao so mais uma pagina
            self._coluna_do_item, self._distribuidas = {}, []
        largura = max(self._largura_card, (self._largura_disponivel() - (self._colunas - 1) * ESPACO) // self._colunas)
        alturas = [0] * self._colunas
        for chave, card in zip(chaves, self.cards):
            coluna = self._coluna_do_item.get(chave)
            if coluna is None:
                coluna = alturas.index(min(alturas))
                self._coluna_do_item[chave] = coluna
            card.ensurePolished()
            altura = card.heightForWidth(largura)
            alturas[coluna] += (altura if altura > 0 else card.sizeHint().height()) + ESPACO
        self._distribuidas = chaves
        for pilha in self._pilhas:
            while pilha.count():
                pilha.takeAt(0)
        for chave, card in zip(chaves, self.cards):
            self._pilhas[self._coluna_do_item[chave]].addWidget(card)
        for pilha in self._pilhas:
            pilha.addStretch()  # o conteudo curto fica no topo da coluna

    def coluna_do_card(self, card: QWidget) -> int | None:
        """Em que coluna esta `card` (None: nao e desta lista)."""
        for numero, pilha in enumerate(self._pilhas):
            if pilha.indexOf(card) >= 0:
                return numero
        return None

    def _largura_disponivel(self) -> int:
        """A largura que a lista tem para os cards, pela area visivel de quem rola (e nao pela largura da propria
        lista: com colunas demais, os cards seguram a lista larga e ela nunca "veria" a janela encolher). A lista
        fica direto no layout do que rola - as margens dele saem da conta."""
        margens = self._rolagem.widget().layout().contentsMargins()
        barra = self._rolagem.verticalScrollBar()
        # sem a barra de rolagem a vista, conta com ela: aparecer ou sumir nao muda as colunas (nao fica pulando)
        sem_barra = 0 if barra.isVisible() else barra.sizeHint().width()
        return self._rolagem.viewport().width() - margens.left() - margens.right() - sem_barra

    def _ajustar_colunas(self) -> None:
        largura = self._largura_disponivel()
        colunas = 1 if self._uma_coluna else max(1, (largura + ESPACO) // (self._largura_card + ESPACO))
        if colunas != self._colunas:
            self._colunas = colunas
            self._coluna_do_item, self._distribuidas = {}, []
            self._posicionar()

    def eventFilter(self, objeto, evento) -> bool:
        if objeto is self._rolagem.viewport() and evento.type() == QEvent.Type.Resize:
            self._ajustar_colunas()
        return super().eventFilter(objeto, evento)

    def _carregar_mais(self) -> None:
        self._limite += TAMANHO_PAGINA
        self._montar()

    def rolar_ate(self, card: QWidget | None) -> None:
        if card is not None:  # depois de devolver a rolagem (o _montar agenda antes)
            QTimer.singleShot(0, lambda: self._rolagem.ensureWidgetVisible(card, 0, 40))
