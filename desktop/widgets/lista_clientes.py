"""Lista de "cards" de clientes (Ficha de Cliente): um card por cliente com o
nome em destaque, o Tipo (Cliente/Avalista) num badge colorido, o vendedor
responsavel e uma bolinha "Em aberto" pra quem tem alguma proposta ainda nao
encerrada. O CPF/CNPJ NAO aparece no card (segue valendo na busca).

Mesma ideia dos cards de proposta (lista_cartoes.py): QListView + delegate (o
card e DESENHADO, nao e um widget por cliente), cores do tema que se refazem
sozinhas quando ele muda, selecao por clique unico com destaque (fundo azulado e
borda mais grossa). Aqui e uma coluna so, que ocupa a largura da lista.
"""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QEvent, QModelIndex, QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QListView, QStyle, QStyledItemDelegate, QWidget

from core import clientes as clientes_mod
from core.validators import apenas_digitos
from desktop import settings as settings_mod
from desktop.theme import COR_EM_ABERTO, CORES_TIPO, PALETAS, TEMA_ESCURO
from desktop.widgets.lista_cartoes import _ALFA_SELECAO, _MARGEM, _RAIO, _alinhar, _fonte

PAPEL_CLIENTE = Qt.ItemDataRole.UserRole  # devolve o dict do card (ver ModeloClientes)

ALTURA_CARTAO_CLIENTE = 72
ESPACO_CLIENTE = 8  # entre um card e o proximo

_TEXTO_EM_ABERTO = "Em aberto"


def chave_cor_tipo(tipo: str) -> str:
    """Chave de CORES_TIPO (desktop/theme.py) do Tipo do cliente, sem diferenciar
    maiusculas ("Cliente" -> "cliente"); em branco ou desconhecido -> "neutro"."""
    texto = (tipo or "").strip().upper()
    for opcao in clientes_mod.TIPO_OPCOES:
        if texto == opcao.upper():
            return opcao.lower()
    return "neutro"


def rotulo_do_tipo(tipo: str) -> str:
    """O Tipo como o badge o mostra: "Cliente"/"Avalista" mesmo que a planilha
    tenha "CLIENTE" ou "avalista" (so a exibicao - o dado nao muda); qualquer
    outro texto aparece como esta."""
    texto = (tipo or "").strip()
    for opcao in clientes_mod.TIPO_OPCOES:
        if texto.upper() == opcao.upper():
            return opcao
    return texto


def textos_do_cliente(item: dict) -> dict:
    """Os textos que o card desenha: "nome", "tipo" (do badge), "vendedor" e
    "em_aberto" ("" quando nao ha). Nunca inclui o CPF/CNPJ."""
    vendedor = (item.get("vendedor") or "").strip()
    return {
        "nome": (item.get("cliente") or "").strip() or "(sem nome)",
        "tipo": rotulo_do_tipo(item.get("tipo")),
        "vendedor": f"Vendedor: {vendedor}" if vendedor else "Sem vendedor",
        "em_aberto": _TEXTO_EM_ABERTO if item.get("em_aberto") else "",
    }


class ModeloClientes(QAbstractListModel):
    """Uma linha por cliente. Cada item e um dict com "cpf" (o CPF/CNPJ como esta
    na planilha - e o que identifica o cliente), "cliente" (nome), "tipo" e
    "vendedor". Quem tem proposta em aberto vem de fora (definir_em_aberto), como
    o conjunto de CPFs so com digitos."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._itens: list[dict] = []
        self._chaves: list[str] = []  # CPF so com digitos, na mesma ordem dos itens
        self._em_aberto: set[str] = set()

    def definir_itens(self, itens: list[dict]) -> None:
        self.beginResetModel()
        self._itens = itens
        self._chaves = [apenas_digitos(item["cpf"]) for item in itens]
        self.endResetModel()

    def definir_em_aberto(self, cpfs: set[str]) -> None:
        """Repinta so o que mudou: os cards continuam onde estao (e a selecao e a
        rolagem tambem)."""
        if cpfs == self._em_aberto:
            return
        self._em_aberto = set(cpfs)
        if self._itens:
            self.dataChanged.emit(self.index(0), self.index(len(self._itens) - 1))

    # -- acesso -------------------------------------------------------------------

    def total(self) -> int:
        return len(self._itens)

    def cpf(self, linha: int) -> str | None:
        return self._itens[linha]["cpf"] if 0 <= linha < len(self._itens) else None

    def nome(self, linha: int) -> str | None:
        return self._itens[linha]["cliente"] if 0 <= linha < len(self._itens) else None

    def esta_em_aberto(self, linha: int) -> bool:
        return 0 <= linha < len(self._itens) and self._chaves[linha] in self._em_aberto

    def linha_do_cpf(self, cpf: str | None) -> int | None:
        return next((i for i, item in enumerate(self._itens) if item["cpf"] == cpf), None)

    # -- QAbstractListModel -------------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._itens)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._itens):
            return None
        item = {**self._itens[index.row()], "em_aberto": self.esta_em_aberto(index.row())}
        if role == PAPEL_CLIENTE:
            return item
        textos = textos_do_cliente(item)
        if role == Qt.ItemDataRole.DisplayRole:
            return textos["nome"]
        if role == Qt.ItemDataRole.ToolTipRole:
            # o nome no card pode aparecer cortado ("..."): o hover mostra inteiro
            linhas = [textos["nome"]]
            if textos["tipo"]:
                linhas.append(f"Tipo: {textos['tipo']}")
            linhas.append(textos["vendedor"])
            if textos["em_aberto"]:
                linhas.append("Tem proposta em aberto")
            return "\n".join(linhas)
        return None


class DelegateCliente(QStyledItemDelegate):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._largura = 240
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
        return QRect(retangulo_da_celula.left(), retangulo_da_celula.top(), self._largura, ALTURA_CARTAO_CLIENTE)

    def sizeHint(self, option, index) -> QSize:
        return QSize(self._largura, ALTURA_CARTAO_CLIENTE + ESPACO_CLIENTE)

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        item = index.data(PAPEL_CLIENTE)
        if not item:
            return
        selecionado = bool(option.state & QStyle.StateFlag.State_Selected)
        sobre = bool(option.state & QStyle.StateFlag.State_MouseOver)
        paleta = self.paleta()
        textos = textos_do_cliente(item)
        cartao = QRectF(self.retangulo_do_cartao(option.rect)).adjusted(0.5, 0.5, -0.5, -0.5)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        contorno = QPainterPath()
        contorno.addRoundedRect(cartao, _RAIO, _RAIO)
        painter.fillPath(contorno, QColor(paleta["bg_card"]))
        if selecionado:
            realce = QColor(paleta["destaque"])
            realce.setAlpha(_ALFA_SELECAO)
            painter.fillPath(contorno, realce)
        if selecionado:
            caneta = QPen(QColor(paleta["destaque"]), 2)
        elif sobre:
            caneta = QPen(QColor(paleta["destaque"]), 1)
        else:
            caneta = QPen(QColor(paleta["borda"]), 1)
        painter.setPen(caneta)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(contorno)

        esquerda = cartao.left() + _MARGEM
        direita = cartao.right() - _MARGEM
        largura_texto = direita - esquerda
        alinhamento_esquerda = _alinhar(Qt.AlignmentFlag.AlignLeft, Qt.AlignmentFlag.AlignVCenter)

        # -- 1a linha: nome (destaque) e, na ponta, o badge do Tipo ------------
        topo_linha1 = cartao.top() + 12
        largura_badge = 0.0
        if textos["tipo"]:
            cores_tipo = CORES_TIPO[self._tema]
            cor = cores_tipo.get(chave_cor_tipo(textos["tipo"]), cores_tipo["neutro"])
            fonte_badge = _fonte(option.font, delta=-2, negrito=True)
            medidor_badge = QFontMetrics(fonte_badge)
            largura_badge = min(medidor_badge.horizontalAdvance(textos["tipo"]) + 18, largura_texto * 0.45)
            badge = QRectF(direita - largura_badge, topo_linha1 + 1, largura_badge, 20)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(cor["fundo"]))
            painter.drawRoundedRect(badge, 5, 5)  # quase retangulo: a pilula do status e toda arredondada
            painter.setFont(fonte_badge)
            painter.setPen(QColor(cor["texto"]))
            painter.drawText(
                badge.adjusted(6, 0, -6, 0),
                _alinhar(Qt.AlignmentFlag.AlignCenter),
                medidor_badge.elidedText(textos["tipo"], Qt.TextElideMode.ElideRight, int(badge.width() - 12)),
            )

        fonte_nome = _fonte(option.font, delta=1, negrito=True)
        painter.setFont(fonte_nome)
        painter.setPen(QColor(paleta["texto"]))
        largura_nome = max(0, int(largura_texto - largura_badge - (10 if largura_badge else 0)))
        nome = QFontMetrics(fonte_nome).elidedText(textos["nome"], Qt.TextElideMode.ElideRight, largura_nome)
        painter.drawText(QRectF(esquerda, topo_linha1, largura_nome, 22), alinhamento_esquerda, nome)

        # -- 2a linha: vendedor (discreto) e, na ponta, a bolinha "Em aberto" --------
        fonte_secundaria = _fonte(option.font, delta=-1)
        medidor = QFontMetrics(fonte_secundaria)
        topo_linha2 = cartao.top() + 40
        largura_indicador = 0.0
        if textos["em_aberto"]:
            largura_rotulo = medidor.horizontalAdvance(textos["em_aberto"])
            largura_indicador = 14 + largura_rotulo  # bolinha (8) + espaco (6) + texto
            x_indicador = direita - largura_indicador
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(COR_EM_ABERTO[self._tema]))
            painter.drawEllipse(QPointF(x_indicador + 4, topo_linha2 + 10), 4, 4)
            painter.setFont(fonte_secundaria)
            painter.setPen(QColor(paleta["texto_secundario"]))
            painter.drawText(
                QRectF(x_indicador + 14, topo_linha2, largura_rotulo + 2, 20), alinhamento_esquerda, textos["em_aberto"]
            )

        painter.setFont(fonte_secundaria)
        painter.setPen(QColor(paleta["texto_secundario"]))
        largura_vendedor = max(0, int(largura_texto - largura_indicador - (10 if largura_indicador else 0)))
        vendedor = medidor.elidedText(textos["vendedor"], Qt.TextElideMode.ElideRight, largura_vendedor)
        painter.drawText(QRectF(esquerda, topo_linha2, largura_vendedor, 20), alinhamento_esquerda, vendedor)

        painter.restore()


class ListaClientes(QListView):
    """Cards de clientes numa coluna so, com a largura da lista. Um clique num
    card o seleciona e emite `cliente_mudou` com o CPF/CNPJ dele (tambem ao
    navegar pelo teclado); "" quando nenhum fica selecionado."""

    cliente_mudou = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._modelo = ModeloClientes(self)
        self.setModel(self._modelo)
        self._delegate = DelegateCliente(self)
        self.setItemDelegate(self._delegate)
        self._mensagem_vazia = ""
        self._largura_atual = 0

        self.setViewMode(QListView.ViewMode.ListMode)
        self.setFlow(QListView.Flow.TopToBottom)
        self.setWrapping(False)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setSpacing(0)
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self._ajustar_largura()

    # -- dados ----------------------------------------------------------------------

    def definir_itens(self, itens: list[dict], cpf_atual: str | None = None) -> bool:
        """Troca os cards. Se `cpf_atual` continua na lista ele fica selecionado
        (e visivel) SEM emitir `cliente_mudou` - mudar filtro/ordenacao nao pode
        reabrir a ficha - e devolve True; senao nao fica ninguem selecionado."""
        self.blockSignals(True)
        try:
            self._modelo.definir_itens(itens)
            linha = self._modelo.linha_do_cpf(cpf_atual) if cpf_atual else None
            if linha is None:
                self.setCurrentIndex(QModelIndex())
                self.clearSelection()
            else:
                self.setCurrentIndex(self._modelo.index(linha))
        finally:
            self.blockSignals(False)
        self.viewport().update()
        return linha is not None

    def definir_em_aberto(self, cpfs: set[str]) -> None:
        self._modelo.definir_em_aberto(cpfs)

    def definir_mensagem_vazia(self, texto: str) -> None:
        self._mensagem_vazia = texto
        self.viewport().update()

    def count(self) -> int:
        return self._modelo.total()

    def cpf_da_linha(self, linha: int) -> str | None:
        return self._modelo.cpf(linha)

    def nome_da_linha(self, linha: int) -> str | None:
        return self._modelo.nome(linha)

    def esta_em_aberto(self, linha: int) -> bool:
        return self._modelo.esta_em_aberto(linha)

    def linha_do_cpf(self, cpf: str | None) -> int | None:
        return self._modelo.linha_do_cpf(cpf)

    def linha_atual(self) -> int | None:
        indice = self.currentIndex()
        return indice.row() if indice.isValid() else None

    def definir_linha_atual(self, linha: int) -> None:
        self.setCurrentIndex(self._modelo.index(linha))

    # -- layout --------------------------------------------------------------------

    def _ajustar_largura(self) -> None:
        """O card ocupa a largura da lista descontando SEMPRE o espaco da barra
        de rolagem (aparecendo ou nao) - senao ela aparecendo/sumindo mudaria a
        largura dos cards e o desenho oscilaria (a mesma regra dos cards de proposta)."""
        largura = self.width() - 2 * self.frameWidth() - self.verticalScrollBar().sizeHint().width() - 2
        if largura <= 0 or largura == self._largura_atual:
            return
        self._largura_atual = largura
        self._delegate.definir_largura(largura)
        self.setGridSize(QSize(largura, ALTURA_CARTAO_CLIENTE + ESPACO_CLIENTE))
        self.scheduleDelayedItemsLayout()

    def resizeEvent(self, evento) -> None:
        super().resizeEvent(evento)
        self._ajustar_largura()

    # -- interacao -----------------------------------------------------------------

    def indexAt(self, ponto: QPoint) -> QModelIndex:
        """So conta como "dentro do card" o desenho do card - o espaco entre
        cards (que faz parte da celula) nao seleciona nada."""
        indice = super().indexAt(ponto)
        if indice.isValid() and not self._delegate.retangulo_do_cartao(self.visualRect(indice)).contains(ponto):
            return QModelIndex()
        return indice

    def currentChanged(self, atual: QModelIndex, anterior: QModelIndex) -> None:
        super().currentChanged(atual, anterior)
        cpf = self._modelo.cpf(atual.row()) if atual.isValid() else None
        self.cliente_mudou.emit(cpf or "")

    def mouseMoveEvent(self, evento) -> None:
        sobre_card = self.indexAt(evento.position().toPoint()).isValid()
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if sobre_card else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(evento)

    # -- desenho / tema ---------------------------------------------------------------

    def changeEvent(self, evento) -> None:
        # trocar o tema reaplica o stylesheet do app inteiro (StyleChange)
        if evento.type() == QEvent.Type.StyleChange:
            self._delegate.atualizar_tema()
            self.viewport().update()
        super().changeEvent(evento)

    def paintEvent(self, evento) -> None:
        super().paintEvent(evento)
        if self._mensagem_vazia and self._modelo.total() == 0:
            pintor = QPainter(self.viewport())
            pintor.setPen(QColor(self._delegate.paleta()["texto_secundario"]))
            pintor.drawText(
                self.viewport().rect().adjusted(16, 24, -16, 0),
                _alinhar(Qt.AlignmentFlag.AlignHCenter, Qt.AlignmentFlag.AlignTop, Qt.TextFlag.TextWordWrap),
                self._mensagem_vazia,
            )
