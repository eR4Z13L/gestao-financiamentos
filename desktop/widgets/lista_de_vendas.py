"""A lista de cards de venda, a mesma na tela Vendas e na Ficha de Cliente (e, depois, na visao por banco).

Cuida dos cards - em colunas que dividem a largura (quantas couberem sem espremer o card; na Ficha, uma so), cada
uma empilhando os seus, sem buraco embaixo de um card curto -, de qual esta ABERTO (um por vez: ele so cresce para
baixo, na propria coluna), do formulario da proposta dentro dele e de nunca descartar algo digitado sem perguntar. Quem mostra a lista decide QUAIS vendas
aparecem (busca, filtros, o cliente da ficha) e rele depois de gravar: a lista avisa pelo sinal `gravou`.
"""

from __future__ import annotations

from collections import Counter
from typing import Callable

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core import sessao as sessao_mod
from core import vendas as vendas_mod
from desktop.dialogs.venda_dialog import VendaDialog
from desktop.widgets.card_da_venda import LARGURA_CARD, NOVA, CardDaVenda, ControleDasVendas, proposta_por_id

ESPACO = 8
TAMANHO_PAGINA = 30
SEGUNDOS_DO_AVISO = 8

_FRASE_STATUS = {  # (singular, plural) nas contagens
    vendas_mod.VENDA_AGUARDANDO: ("aguardando bancos", "aguardando bancos"),
    vendas_mod.VENDA_EM_ANDAMENTO: ("em andamento", "em andamento"),
    vendas_mod.VENDA_EFETIVADA: ("efetivada", "efetivadas"),
    vendas_mod.VENDA_NAO_EFETIVADA: ("não efetivada", "não efetivadas"),
    vendas_mod.VENDA_PERDIDA: ("perdida", "perdidas"),
}


def resumo_por_status(vendas: list[vendas_mod.ResumoDaVenda]) -> str:
    contagem = Counter(v.status for v in vendas)
    partes = []
    for status in vendas_mod.STATUS_DA_VENDA:
        if contagem.get(status):
            singular, plural = _FRASE_STATUS[status]
            partes.append(f"{contagem[status]} {singular if contagem[status] == 1 else plural}")
    return " · ".join(partes)


class FaixaDeAviso(QFrame):
    """"Santander: "Em Análise" → "Aprovado"." - o que acabou de mudar; some sozinha (desfazer = a setinha ↩)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("role", "chip_filtro")
        linha = QHBoxLayout(self)
        linha.setContentsMargins(12, 6, 8, 6)
        self.texto = QLabel("", self)
        self.texto.setWordWrap(True)
        linha.addWidget(self.texto, stretch=1)
        self.setVisible(False)
        self._relogio = QTimer(self)
        self._relogio.setSingleShot(True)
        self._relogio.timeout.connect(lambda: self.setVisible(False))

    def avisar(self, texto: str) -> None:
        if not texto:
            return
        self.texto.setText(texto)
        self.setVisible(True)
        self._relogio.start(SEGUNDOS_DO_AVISO * 1000)


class ListaDeVendas(QWidget):
    gravou = Signal(str)  # gravou algo (o aviso a mostrar, "" = nenhum): quem mostra a lista rele as vendas
    ficha_pedida = Signal(str)  # cpf

    def __init__(self, rolagem: QScrollArea, parent: QWidget | None = None, *, com_ficha: bool = True,
                 uma_coluna: bool = False):
        """`rolagem`: quem rola a lista (a da tela) - a posicao e mantida ao refazer os cards. `com_ficha`: o
        "Abrir a ficha" do card aberto (na propria ficha nao faz sentido). `uma_coluna`: todo card na largura toda
        (a Ficha)."""
        super().__init__(parent)
        self.setProperty("role", "transparente")
        self._rolagem = rolagem
        self._com_ficha = com_ficha
        self._uma_coluna = uma_coluna
        # em que coluna esta cada venda: so muda com outra lista (busca, filtro, venda nova) ou outro numero de
        # colunas - abrir, fechar ou gravar num card nao tira ninguem do lugar
        self._coluna_da_venda: dict[str, int] = {}
        self._distribuidas: list[str] = []
        self._vendas: list[vendas_mod.ResumoDaVenda] = []
        self._limite = TAMANHO_PAGINA
        self._colunas = 1
        self._montagens = 0  # so a devolucao da rolagem da montagem mais recente vale (ver _devolver_rolagem)
        self.cards: list[CardDaVenda] = []
        self.aberta: str | None = None  # o ID_VENDA do card aberto
        self.editando: str | None = None  # no card aberto: o ID_PROPOSTA no formulario, NOVA, ou None
        self.antes_de_editar: Callable[[], bool] | None = None  # False: nao abre o formulario (ver abrir_venda)
        self.controle = ControleDasVendas(self, self.gravou.emit)

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

    # -- vendas -------------------------------------------------------------------------------------

    def definir_vendas(self, vendas: list[vendas_mod.ResumoDaVenda], *, texto_vazio: str = "",
                       voltar_ao_inicio: bool = False) -> None:
        """As vendas a mostrar, na ordem. `voltar_ao_inicio`: outra lista (busca, filtro, outro cliente) - volta
        a primeira pagina e nao devolve a rolagem; senao (releu depois de gravar) tudo fica onde estava."""
        self._vendas = list(vendas)
        if self.aberta not in {v.id for v in self._vendas}:
            self.aberta, self.editando = None, None
        self.vazio.setText(texto_vazio)
        self._montar(voltar_ao_inicio)

    def total(self) -> int:
        return len(self._vendas)

    def _montar(self, voltar_ao_inicio: bool = False) -> None:
        self._montagens += 1
        if voltar_ao_inicio:
            self._limite = TAMANHO_PAGINA
        conteudo = self._rolagem.widget()
        rolagem = self._rolagem.verticalScrollBar().value()
        # a lista nao "encolhe" enquanto os cards sao trocados: sem isso a rolagem caia pro topo a cada gravacao (o
        # card que a pessoa estava usando sumia de vista) - a altura so e solta depois de devolver a posicao
        conteudo.setMinimumHeight(0 if voltar_ao_inicio else conteudo.height())
        for card in self.cards:
            card.hide()  # some ja: o deleteLater so apaga no proximo ciclo
            card.deleteLater()
        self.cards = []
        for venda in self._vendas[: self._limite]:
            card = CardDaVenda(venda, self, aberto=venda.id == self.aberta)
            self.controle.conectar(card)
            card.abrir_pedido.connect(self.abrir_venda)
            card.fechar_pedido.connect(lambda _v: self.fechar_venda())
            card.proposta_pedida.connect(self.editar_proposta)
            card.edicao_da_venda_pedida.connect(self.editar_venda)
            card.ficha_pedida.connect(self.ficha_pedida)
            if card.abrir_ficha is not None and not self._com_ficha:
                card.abrir_ficha.hide()
            if card.aberto and self.editando is not None:
                self._por_formulario(card)
            self.cards.append(card)
        self.vazio.setVisible(not self._vendas and bool(self.vazio.text()))
        self.botao_mais.setVisible(len(self._vendas) > self._limite)
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
        """Cada card na sua coluna, empilhados na ordem da lista. Venda que ainda nao tem coluna vai para a mais curta
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
        ids = [c.venda.id for c in self.cards]
        if ids[: len(self._distribuidas)] != self._distribuidas:  # outra lista, nao so mais uma pagina
            self._coluna_da_venda, self._distribuidas = {}, []
        largura = max(LARGURA_CARD, (self._largura_disponivel() - (self._colunas - 1) * ESPACO) // self._colunas)
        alturas = [0] * self._colunas
        for card in self.cards:
            coluna = self._coluna_da_venda.get(card.venda.id)
            if coluna is None:
                coluna = alturas.index(min(alturas))
                self._coluna_da_venda[card.venda.id] = coluna
            card.ensurePolished()
            altura = card.heightForWidth(largura)
            alturas[coluna] += (altura if altura > 0 else card.sizeHint().height()) + ESPACO
        self._distribuidas = ids
        for pilha in self._pilhas:
            while pilha.count():
                pilha.takeAt(0)
        for card in self.cards:
            self._pilhas[self._coluna_da_venda[card.venda.id]].addWidget(card)
        for pilha in self._pilhas:
            pilha.addStretch()  # o conteudo curto fica no topo da coluna

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
        colunas = 1 if self._uma_coluna else max(1, (largura + ESPACO) // (LARGURA_CARD + ESPACO))
        if colunas != self._colunas:
            self._colunas = colunas
            self._coluna_da_venda, self._distribuidas = {}, []
            self._posicionar()

    def eventFilter(self, objeto, evento) -> bool:
        if objeto is self._rolagem.viewport() and evento.type() == QEvent.Type.Resize:
            self._ajustar_colunas()
        return super().eventFilter(objeto, evento)

    def _carregar_mais(self) -> None:
        self._limite += TAMANHO_PAGINA
        self._montar()

    # -- card aberto e formulario -------------------------------------------------------------------

    def card_aberto(self) -> CardDaVenda | None:
        return next((c for c in self.cards if c.aberto), None)

    def tem_edicao_pendente(self) -> bool:
        card = self.card_aberto()
        return card is not None and card.tem_alteracoes()

    def pode_descartar(self) -> bool:
        """Ha algo digitado no formulario aberto? Pergunta antes de descartar."""
        if not self.tem_edicao_pendente():
            return True
        resposta = QMessageBox.question(
            self, "Alterações não salvas", "Há uma proposta com alterações que ainda não foram salvas. Descartar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        return resposta == QMessageBox.StandardButton.Yes

    def descartar(self) -> None:
        """Fecha o formulario sem perguntar (quem chama ja perguntou ou avisou)."""
        if self.editando is not None or self.tem_edicao_pendente():
            self.editando = None
            self._montar()

    def liberar(self) -> bool:
        """Fecha o formulario (o card continua aberto), perguntando antes de descartar o digitado. False = a pessoa
        preferiu continuar editando (quem chamou nao segue)."""
        if self.editando is None:
            return True
        if not self.pode_descartar():
            return False
        self.editando = None
        self._montar()
        return True

    def abrir_venda(self, venda: vendas_mod.ResumoDaVenda, editando: str | None = None) -> bool:
        if venda.id == self.aberta and editando == self.editando:
            return True
        if not self.pode_descartar():
            return False
        # na Ficha ha outro formulario (o das propostas de antes das vendas): um por vez na tela
        if editando is not None and self.antes_de_editar is not None and not self.antes_de_editar():
            return False
        self.aberta, self.editando = venda.id, editando
        self._montar()
        self.rolar_ate_o_aberto()
        return True

    def rolar_ate_o_aberto(self) -> None:
        card = self.card_aberto()
        if card is not None:  # depois de devolver a rolagem (o _montar agenda antes)
            QTimer.singleShot(0, lambda: self._rolagem.ensureWidgetVisible(card, 0, 40))

    def fechar_venda(self) -> bool:
        if not self.pode_descartar():
            return False
        self.aberta, self.editando = None, None
        self._montar()
        return True

    def editar_proposta(self, venda: vendas_mod.ResumoDaVenda, proposta: vendas_mod.PropostaNaVenda | None) -> bool:
        """O ✎ (ou dois cliques num banco, ou "+ Adicionar proposta"): abre o card, se preciso, com o formulario."""
        return self.abrir_venda(venda, NOVA if proposta is None else proposta.id)

    def _por_formulario(self, card: CardDaVenda) -> None:
        try:
            formulario = self.controle.criar_formulario(card.venda, self.editando)
        except Exception as exc:  # nunca falhar em silencio (ex.: a proposta sumiu entre a leitura e o clique)
            QMessageBox.warning(self, "Não foi possível abrir a proposta", f"{type(exc).__name__}: {exc}")
            self.editando = None
            return
        formulario.gravada.connect(self._ao_gravar_formulario)
        formulario.cancelada.connect(self._ao_cancelar_formulario)
        ao_excluir = None
        proposta = proposta_por_id(card.venda, self.editando)
        if proposta is not None:
            ao_excluir = lambda: self._excluir(card.venda, proposta)  # noqa: E731
        card.mostrar_formulario(self.editando, formulario, ao_excluir)
        QTimer.singleShot(0, formulario.dar_foco_inicial)

    def _ao_gravar_formulario(self) -> None:
        self.editando = None
        QTimer.singleShot(0, lambda: self.gravou.emit("Proposta gravada."))  # fora do sinal do formulario

    def _ao_cancelar_formulario(self) -> None:
        self.editando = None
        QTimer.singleShot(0, self._montar)

    def _excluir(self, venda: vendas_mod.ResumoDaVenda, proposta: vendas_mod.PropostaNaVenda) -> None:
        self.editando = None
        if not self.controle.excluir_proposta(venda, proposta):
            self.editando = proposta.id

    def editar_venda(self, venda: vendas_mod.ResumoDaVenda) -> bool:
        if not self.pode_descartar():
            return False
        dialogo = VendaDialog(self, venda=venda)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return False
        self.editando = None
        self.gravou.emit(f"{ControleDasVendas.nome(venda)}: venda alterada.")
        return True

    def nova_venda(self, cpf: str | None = None) -> bool:
        """Cria a venda (so cliente e equipamentos; `cpf` ja escolhe o cliente) e deixa o card dela aberto, pronto
        pro primeiro banco. Quem mostra a lista rele (o card novo so aparece ai)."""
        if not sessao_mod.eh_admin() or not self.pode_descartar():
            return False
        dialogo = VendaDialog(self, cpf=cpf)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return False
        self.aberta, self.editando = dialogo.id_venda, None
        return True
