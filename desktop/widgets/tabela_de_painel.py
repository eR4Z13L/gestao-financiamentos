"""Tabela pequena e ordenavel do dashboard (por banco, por vendedor): clicar no cabecalho ordena (numeros
pelo valor, nao pelo texto), uma celula pode ter cor de aviso e uma mini-barra embaixo (a taxa), e uma
linha pode ser clicavel (`linha_clicada` traz o que a tela guardou nela). Nao rola por dentro: a altura
acompanha as linhas e quem rola e a pagina.

    tabela = TabelaDePainel(["Banco", "Enviadas", "Taxa"], coluna_da_barra=2)
    tabela.definir_linhas([("SANTANDER", [Celula("Santander"), Celula("15", 15.0), Celula("38,5%", 38.5, barra=0.385)])])
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QEvent, QModelIndex, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPalette, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QSizePolicy, QStyledItemDelegate, QStyleOptionViewItem, QTableView, QWidget

from desktop import settings as settings_mod
from desktop.theme import CORES_STATUS, PALETAS, TEMA_ESCURO

_PAPEL_ORDEM = Qt.ItemDataRole.UserRole
_PAPEL_BARRA = Qt.ItemDataRole.UserRole + 1
_PAPEL_PAYLOAD = Qt.ItemDataRole.UserRole + 2
_PAPEL_COR = Qt.ItemDataRole.UserRole + 3

COR_AVISO = "aviso"  # ambar
COR_ERRO = "erro"
COR_SUCESSO = "sucesso"
COR_SECUNDARIA = "secundario"

_ALTURA_DA_LINHA = 36


@dataclass(frozen=True)
class Celula:
    texto: str
    ordem: float | str | None = None  # o que ordena (numero ou texto); None = o proprio texto
    tooltip: str = ""
    cor: str | None = None  # COR_*
    barra: float | None = None  # 0..1: mini-barra embaixo do texto (so na coluna_da_barra)
    a_direita: bool = False  # numeros ficam encostados na direita


class _Delegado(QStyledItemDelegate):
    def __init__(self, coluna_da_barra: int | None, parent: QWidget):
        super().__init__(parent)
        self._coluna_da_barra = coluna_da_barra
        self.atualizar_paleta()

    def atualizar_paleta(self) -> None:
        tema = settings_mod.obter_tema()
        self._paleta = PALETAS.get(tema, PALETAS[TEMA_ESCURO])
        self._status = CORES_STATUS.get(tema, CORES_STATUS[TEMA_ESCURO])

    def _cor(self, chave: str | None) -> QColor | None:
        if chave == COR_AVISO:
            return QColor(self._status["em_analise"]["faixa"])
        if chave == COR_ERRO:
            return QColor(self._paleta["erro"])
        if chave == COR_SUCESSO:
            return QColor(self._paleta["sucesso"])
        if chave == COR_SECUNDARIA:
            return QColor(self._paleta["texto_secundario"])
        return None

    def initStyleOption(self, opcao: QStyleOptionViewItem, indice: QModelIndex) -> None:
        super().initStyleOption(opcao, indice)
        cor = self._cor(indice.data(_PAPEL_COR))
        if cor is not None:
            opcao.palette.setColor(QPalette.ColorRole.Text, cor)
            opcao.palette.setColor(QPalette.ColorRole.HighlightedText, cor)

    def paint(self, pintor: QPainter, opcao: QStyleOptionViewItem, indice: QModelIndex) -> None:
        super().paint(pintor, opcao, indice)
        barra = indice.data(_PAPEL_BARRA)
        if barra is None or indice.column() != self._coluna_da_barra:
            return
        area = QRectF(opcao.rect)
        trilho = QRectF(area.left() + 8, area.bottom() - 9, area.width() - 16, 4)
        pintor.save()
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        pintor.setPen(Qt.PenStyle.NoPen)
        cor_do_trilho = QColor(self._paleta["borda"])
        cor_do_trilho.setAlpha(120)
        pintor.setBrush(cor_do_trilho)
        pintor.drawRoundedRect(trilho, 2, 2)
        if barra > 0:
            pintor.setBrush(QColor(self._status["aprovado"]["faixa"]))
            pintor.drawRoundedRect(QRectF(trilho.left(), trilho.top(), max(trilho.width() * min(barra, 1.0), 3.0), trilho.height()), 2, 2)
        pintor.restore()


class TabelaDePainel(QTableView):
    linha_clicada = Signal(object)  # o payload da linha (o que `definir_linhas` recebeu com ela)

    def __init__(
        self,
        colunas: list[str],
        coluna_da_barra: int | None = None,
        colunas_a_direita: tuple[int, ...] = (),
        parent: QWidget | None = None,
    ):
        """`colunas_a_direita`: as colunas de numero - o cabecalho delas fica encostado na direita, como as celulas."""
        super().__init__(parent)
        self._modelo = QStandardItemModel(0, len(colunas), self)
        self._modelo.setHorizontalHeaderLabels(colunas)
        for coluna in range(len(colunas)):
            alinhamento = Qt.AlignmentFlag.AlignRight if coluna in colunas_a_direita else Qt.AlignmentFlag.AlignLeft
            self._modelo.setHeaderData(coluna, Qt.Orientation.Horizontal, alinhamento | Qt.AlignmentFlag.AlignVCenter, Qt.ItemDataRole.TextAlignmentRole)
        self._modelo.setSortRole(_PAPEL_ORDEM)
        self.setModel(self._modelo)
        self._delegado = _Delegado(coluna_da_barra, self)
        self.setItemDelegate(self._delegado)

        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setWordWrap(False)  # um nome comprido fica numa linha so (elide), nunca em duas
        self.setSortingEnabled(True)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(_ALTURA_DA_LINHA)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        cabecalho = self.horizontalHeader()
        cabecalho.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        cabecalho.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        cabecalho.setStretchLastSection(False)
        cabecalho.setSortIndicatorShown(True)
        self.clicked.connect(self._ao_clicar)
        self._ajustar_altura()

    # -- dados ------------------------------------------------------------------------

    def definir_linhas(self, linhas: list[tuple[Any, list[Celula]]], ordenar_por: int | None = None, decrescente: bool = True) -> None:
        """Troca o conteudo. `linhas`: (payload, celulas) por linha. `ordenar_por`: a coluna que ordena
        agora (a ordem que o usuario tinha escolhido no cabecalho se mantem quando None)."""
        cabecalho = self.horizontalHeader()
        coluna = cabecalho.sortIndicatorSection() if ordenar_por is None else ordenar_por
        ordem = cabecalho.sortIndicatorOrder() if ordenar_por is None else (Qt.SortOrder.DescendingOrder if decrescente else Qt.SortOrder.AscendingOrder)

        self.setSortingEnabled(False)
        self._modelo.removeRows(0, self._modelo.rowCount())
        for payload, celulas in linhas:
            itens = []
            for celula in celulas:
                item = QStandardItem(celula.texto)
                item.setData(celula.texto.casefold() if celula.ordem is None else celula.ordem, _PAPEL_ORDEM)
                item.setData(celula.barra, _PAPEL_BARRA)
                item.setData(celula.cor, _PAPEL_COR)
                if celula.tooltip:
                    item.setToolTip(celula.tooltip)
                if celula.a_direita:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                else:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                itens.append(item)
            if itens:
                itens[0].setData(payload, _PAPEL_PAYLOAD)
            self._modelo.appendRow(itens)
        self.setSortingEnabled(True)
        self.sortByColumn(min(coluna, self._modelo.columnCount() - 1), ordem)
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if any(p is not None for p, _ in linhas) else Qt.CursorShape.ArrowCursor)
        self._ajustar_altura()

    def total_de_linhas(self) -> int:
        return self._modelo.rowCount()

    def texto_da_celula(self, linha: int, coluna: int) -> str:
        return self._modelo.item(linha, coluna).text()

    def textos_da_coluna(self, coluna: int) -> list[str]:
        return [self._modelo.item(l, coluna).text() for l in range(self._modelo.rowCount())]

    def payload_da_linha(self, linha: int) -> Any:
        return self._modelo.item(linha, 0).data(_PAPEL_PAYLOAD)

    def cor_da_celula(self, linha: int, coluna: int) -> str | None:
        return self._modelo.item(linha, coluna).data(_PAPEL_COR)

    def barra_da_celula(self, linha: int, coluna: int) -> float | None:
        return self._modelo.item(linha, coluna).data(_PAPEL_BARRA)

    def centro_da_linha(self, linha: int):
        """O ponto (no viewport) no meio da 1a celula da linha: onde um clique de teste cai."""
        return self.visualRect(self._modelo.index(linha, 0)).center()

    # -- interno ------------------------------------------------------------------------

    def _ajustar_altura(self) -> None:
        self.setFixedHeight(self.horizontalHeader().height() + self._modelo.rowCount() * _ALTURA_DA_LINHA + 2)

    def sizeHint(self) -> QSize:
        return QSize(400, self.horizontalHeader().height() + self._modelo.rowCount() * _ALTURA_DA_LINHA + 2)

    def _ao_clicar(self, indice: QModelIndex) -> None:
        payload = self._modelo.item(indice.row(), 0).data(_PAPEL_PAYLOAD)
        if payload is not None:
            self.linha_clicada.emit(payload)

    def changeEvent(self, evento) -> None:
        # trocar o tema (StyleChange) refaz as cores do delegado
        if evento.type() == QEvent.Type.StyleChange and hasattr(self, "_delegado"):
            self._delegado.atualizar_paleta()
            self.viewport().update()
        super().changeEvent(evento)
