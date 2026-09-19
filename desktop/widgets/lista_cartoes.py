"""Lista de "cards" de propostas (tela Todas as Propostas): um card por
proposta, so com o essencial - nome do cliente, data e o status numa pilula
colorida, com uma faixa da mesma cor na lateral. Os detalhes (valor, meses,
equipamento, banco, observacoes) ficam na tela de leitura da proposta, que abre
ao clicar no card.

Feito com QListView + delegate (o card e DESENHADO, nao e um widget por
proposta): continua leve mesmo com milhares de propostas, e ganha de graca
selecao, rolagem e navegacao por teclado. As cores vem de desktop/theme.py e
se refazem sozinhas quando o tema muda com o app aberto.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QEvent, QModelIndex, QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QListView, QStyle, QStyledItemDelegate, QWidget

from core import propostas as propostas_mod
from desktop import settings as settings_mod
from desktop.theme import CORES_STATUS, PALETAS, TEMA_ESCURO

PAPEL_CARTAO = Qt.ItemDataRole.UserRole  # devolve o dict do card (ver ModeloCartoes)

ALTURA_CARTAO = 84
LARGURA_MINIMA_CARTAO = 300  # abaixo disso o card perde uma coluna em vez de encolher
ESPACO = 12  # entre cards (na horizontal e na vertical)
_RAIO = 10
_FAIXA = 6  # largura da faixa colorida lateral
_MARGEM = 14  # entre a faixa/borda e o texto

_COR_POR_ETAPA = {
    propostas_mod.ETAPA_APROVADO: "aprovado",
    propostas_mod.ETAPA_EFETIVADO: "efetivado",
    propostas_mod.ETAPA_NEGADO: "negado",
    propostas_mod.ETAPA_EM_ANALISE: "em_analise",
    propostas_mod.ETAPA_PRE_APROVADO: "pre_aprovado",
    propostas_mod.ETAPA_NF_ANEXADA: "nota_fiscal",
    propostas_mod.ETAPA_GARANTIA_ASSINADA: "garantia",
}


def chave_cor_status(status: str) -> str:
    """Chave de CORES_STATUS (desktop/theme.py) do status; sem status ou
    desconhecido -> "neutro" (cinza)."""
    return _COR_POR_ETAPA.get(propostas_mod.etapa_status(status), "neutro")


class ModeloCartoes(QAbstractListModel):
    """Uma linha por card. Cada item e um dict com: "indice" (posicao real da
    proposta no arquivo - a que editar/excluir precisam), "cliente", "status"
    e "data" (ja formatada)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._itens: list[dict] = []

    def definir_itens(self, itens: list[dict]) -> None:
        self.beginResetModel()
        self._itens = itens
        self.endResetModel()

    def indice_real(self, linha: int) -> int:
        return self._itens[linha]["indice"]

    def linha_do_indice_real(self, indice_real: int) -> int | None:
        return next((i for i, item in enumerate(self._itens) if item["indice"] == indice_real), None)

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._itens)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        item = self._itens[index.row()]
        if role == PAPEL_CARTAO:
            return item
        if role == Qt.ItemDataRole.DisplayRole:
            return item["cliente"]
        if role == Qt.ItemDataRole.ToolTipRole:
            # o nome no card pode aparecer cortado ("..."): o hover mostra inteiro
            return f"{item['cliente'] or '(cliente não encontrado)'}\n{item['status'] or 'Sem status'} · {item['data']}"
        return None


def _alinhar(*flags) -> int:
    """Combina flags de alinhamento (Qt.AlignmentFlag e Qt.TextFlag) no inteiro
    que QPainter.drawText espera - o PySide6 nao mistura os dois tipos com "|"."""
    resultado = 0
    for flag in flags:
        resultado |= flag.value
    return resultado


def _fonte(base: QFont, delta: float = 0, negrito: bool = False) -> QFont:
    fonte = QFont(base)
    if fonte.pixelSize() > 0:
        fonte.setPixelSize(max(9, round(fonte.pixelSize() + delta)))
    else:
        fonte.setPointSizeF(max(7.0, fonte.pointSizeF() + delta * 0.75))
    fonte.setBold(negrito)
    return fonte


class DelegateCartao(QStyledItemDelegate):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._largura = LARGURA_MINIMA_CARTAO
        self.atualizar_tema()

    def atualizar_tema(self) -> None:
        tema = settings_mod.obter_tema()
        self._tema = tema if tema in PALETAS else TEMA_ESCURO

    def paleta(self) -> dict:
        return PALETAS[self._tema]

    def definir_largura(self, largura: int) -> None:
        self._largura = largura

    def retangulo_do_cartao(self, retangulo_da_celula: QRect) -> QRect:
        """O card ocupa so o canto da celula - o resto e o espaco entre cards."""
        return QRect(retangulo_da_celula.left(), retangulo_da_celula.top(), self._largura, ALTURA_CARTAO)

    def sizeHint(self, option, index) -> QSize:
        return QSize(self._largura + ESPACO, ALTURA_CARTAO + ESPACO)

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        item = index.data(PAPEL_CARTAO)
        if not item:
            return
        paleta = self.paleta()
        cor = CORES_STATUS[self._tema][chave_cor_status(item["status"])]
        selecionado = bool(option.state & QStyle.StateFlag.State_Selected)
        sobre = bool(option.state & QStyle.StateFlag.State_MouseOver)

        cartao = QRectF(self.retangulo_do_cartao(option.rect)).adjusted(0.5, 0.5, -0.5, -0.5)
        contorno = QPainterPath()
        contorno.addRoundedRect(cartao, _RAIO, _RAIO)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        painter.fillPath(contorno, QColor(paleta["bg_card"]))
        # faixa colorida: pintada recortada pelo contorno arredondado do card
        painter.save()
        painter.setClipPath(contorno)
        painter.fillRect(QRectF(cartao.left(), cartao.top(), _FAIXA, cartao.height()), QColor(cor["faixa"]))
        painter.restore()

        if selecionado:
            caneta = QPen(QColor(paleta["destaque"]), 2)
        elif sobre:
            caneta = QPen(QColor(paleta["destaque"]), 1)
        else:
            caneta = QPen(QColor(paleta["borda"]), 1)
        painter.setPen(caneta)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(contorno)

        esquerda = cartao.left() + _FAIXA + _MARGEM
        direita = cartao.right() - _MARGEM
        largura_texto = int(direita - esquerda)

        # -- nome do cliente (linha de cima) ---------------------------------
        fonte_nome = _fonte(option.font, delta=1, negrito=True)
        painter.setFont(fonte_nome)
        cliente = item["cliente"]
        if cliente:
            painter.setPen(QColor(paleta["texto"]))
            texto_nome = cliente
        else:
            painter.setPen(QColor(paleta["texto_secundario"]))
            texto_nome = "(cliente não encontrado)"
        texto_nome = QFontMetrics(fonte_nome).elidedText(texto_nome, Qt.TextElideMode.ElideRight, largura_texto)
        painter.drawText(
            QRectF(esquerda, cartao.top() + 12, largura_texto, 22),
            _alinhar(Qt.AlignmentFlag.AlignLeft, Qt.AlignmentFlag.AlignVCenter),
            texto_nome,
        )

        # -- linha de baixo: data (esquerda) e pilula do status (direita) ----
        faixa_de_baixo = QRectF(esquerda, cartao.top() + 44, largura_texto, 26)

        fonte_pilula = _fonte(option.font, delta=-2, negrito=True)
        metricas = QFontMetrics(fonte_pilula)
        texto_status = item["status"] or "Sem status"
        largura_pilula = min(metricas.horizontalAdvance(texto_status) + 20, int(largura_texto * 0.62))
        pilula = QRectF(direita - largura_pilula, faixa_de_baixo.center().y() - 11, largura_pilula, 22)
        painter.setPen(QPen(QColor(cor["faixa"]), 1))
        painter.setBrush(QColor(cor["fundo"]))
        painter.drawRoundedRect(pilula, 11, 11)
        painter.setFont(fonte_pilula)
        painter.setPen(QColor(cor["texto"]))
        painter.drawText(
            pilula.adjusted(8, 0, -8, 0),
            _alinhar(Qt.AlignmentFlag.AlignCenter),
            metricas.elidedText(texto_status, Qt.TextElideMode.ElideRight, int(pilula.width() - 16)),
        )

        painter.setFont(_fonte(option.font, delta=-1))
        painter.setPen(QColor(paleta["texto_secundario"]))
        painter.drawText(
            QRectF(esquerda, faixa_de_baixo.top(), max(0.0, largura_texto - largura_pilula - 8), faixa_de_baixo.height()),
            _alinhar(Qt.AlignmentFlag.AlignLeft, Qt.AlignmentFlag.AlignVCenter),
            item["data"],
        )
        painter.restore()


class ListaCartoes(QListView):
    """Grade de cards que se ajusta a largura da janela: quantas colunas
    couberem (cada card com pelo menos LARGURA_MINIMA_CARTAO), esticando os
    cards pra preencher a linha. Um clique (ou Enter) num card emite `acionado`
    com o numero da linha."""

    acionado = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._delegate = DelegateCartao(self)
        self.setItemDelegate(self._delegate)
        self._mensagem_vazia = ""
        self._largura_atual = 0

        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setWrapping(True)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setUniformItemSizes(True)
        self.setSpacing(0)
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)

        self.clicked.connect(self._ao_clicar)
        self._ajustar_colunas()

    def definir_mensagem_vazia(self, texto: str) -> None:
        self._mensagem_vazia = texto
        self.viewport().update()

    def linha_atual(self) -> int | None:
        indice = self.currentIndex()
        return indice.row() if indice.isValid() else None

    # -- layout responsivo ---------------------------------------------------

    def _largura_util(self) -> int:
        """Largura disponivel pros cards, contando SEMPRE com o espaco da barra
        de rolagem (aparecendo ou nao): assim o numero de colunas nao depende
        de a barra estar visivel - senao ela aparecendo/sumindo mudaria a
        largura, e com ela as colunas, e o layout oscilaria. A folga de 2px e
        porque a grade do Qt quebra a linha se a soma das celulas for igual a
        largura do viewport."""
        return self.width() - 2 * self.frameWidth() - self.verticalScrollBar().sizeHint().width() - 2

    def _ajustar_colunas(self) -> None:
        util = self._largura_util()
        if util <= 0:
            return
        # a grade do Qt precisa que as CELULAS (card + espaco) caibam inteiras na
        # largura - inclusive a da ultima coluna, cujo espaco fica sobrando no canto
        colunas = max(1, util // (LARGURA_MINIMA_CARTAO + ESPACO))
        celula = util // colunas
        largura = max(120, celula - ESPACO)
        if largura == self._largura_atual:
            return
        self._largura_atual = largura
        self._delegate.definir_largura(largura)
        self.setGridSize(QSize(largura + ESPACO, ALTURA_CARTAO + ESPACO))
        self.scheduleDelayedItemsLayout()

    def resizeEvent(self, evento) -> None:
        super().resizeEvent(evento)
        self._ajustar_colunas()

    def colunas(self) -> int:
        return max(1, self._largura_util() // (LARGURA_MINIMA_CARTAO + ESPACO))

    # -- interacao ---------------------------------------------------------------

    def indexAt(self, ponto: QPoint) -> QModelIndex:
        """So conta como "dentro do card" o desenho do card - o espaco entre
        cards (que faz parte da celula) nao seleciona nem aciona nada."""
        indice = super().indexAt(ponto)
        if indice.isValid() and not self._delegate.retangulo_do_cartao(self.visualRect(indice)).contains(ponto):
            return QModelIndex()
        return indice

    def _ao_clicar(self, indice: QModelIndex) -> None:
        self.acionado.emit(indice.row())

    def keyPressEvent(self, evento) -> None:
        if evento.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.currentIndex().isValid():
            self.acionado.emit(self.currentIndex().row())
            return
        super().keyPressEvent(evento)

    def mouseMoveEvent(self, evento) -> None:
        sobre_card = self.indexAt(evento.position().toPoint()).isValid()
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if sobre_card else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(evento)

    # -- desenho / tema ---------------------------------------------------------

    def changeEvent(self, evento) -> None:
        # trocar o tema reaplica o stylesheet do app inteiro (StyleChange)
        if evento.type() == QEvent.Type.StyleChange:
            self._delegate.atualizar_tema()
            self.viewport().update()
        super().changeEvent(evento)

    def paintEvent(self, evento) -> None:
        super().paintEvent(evento)
        modelo = self.model()
        if self._mensagem_vazia and modelo is not None and modelo.rowCount() == 0:
            pintor = QPainter(self.viewport())
            pintor.setPen(QColor(self._delegate.paleta()["texto_secundario"]))
            pintor.drawText(
                self.viewport().rect().adjusted(16, 24, -16, 0),
                _alinhar(Qt.AlignmentFlag.AlignHCenter, Qt.AlignmentFlag.AlignTop, Qt.TextFlag.TextWordWrap),
                self._mensagem_vazia,
            )
