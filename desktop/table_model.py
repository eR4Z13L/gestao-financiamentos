"""Model generico do Qt pra exibir qualquer DataFrame do pandas numa QTableView.

Toda tela que precisa mostrar uma tabela so cria um PandasTableModel(df) e um
QTableView - evita reescrever a logica de popular celulas em cada tela.
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import QTableView

_LARGURA_MAXIMA_COLUNA = 280


class PandasTableModel(QAbstractTableModel):
    def __init__(self, df: pd.DataFrame | None = None, parent=None):
        super().__init__(parent)
        self._df = df if df is not None else pd.DataFrame()

    def definir_dataframe(self, df: pd.DataFrame) -> None:
        self.beginResetModel()
        self._df = df
        self.endResetModel()

    def indice_real(self, linha_posicional: int):
        """O rotulo (index) do DataFrame na posicao visual `linha_posicional`.

        Usado pra identificar a linha de verdade no arquivo quando a tabela
        esta mostrando uma versao so com colunas formatadas pra exibicao (ex:
        "R$ 50.000,00" em vez do float) - o DataFrame exibido ainda carrega o
        indice original (a posicao real na planilha), so os valores mudam.
        """
        return self._df.index[linha_posicional]

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._df)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._df.columns)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        # ToolTipRole repete o mesmo texto do DisplayRole: como as colunas
        # tem largura maxima (ver limitar_largura_colunas), um valor longo
        # aparece truncado com "..." na celula, mas o hover mostra ele
        # inteiro - sem isso, um campo como OBSERVACOES longo ficaria
        # ilegivel sem nunca esticar a coluna alem do espaco disponivel.
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            valor = self._df.iat[index.row(), index.column()]
            if pd.isna(valor):
                return ""
            return str(valor)
        return None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return str(self._df.columns[section])
        return str(section + 1)


def limitar_largura_colunas(tabela: QTableView, largura_maxima: int = _LARGURA_MAXIMA_COLUNA) -> None:
    """Chamar depois de resizeColumnsToContents(): sem isso, uma unica celula
    com um texto longo sem espaco (ex.: uma URL colada em Observacoes) faz a
    coluna - e a tabela inteira - esticar bem alem do espaco disponivel na
    tela. O texto que nao couber mais aparece truncado com "..." (Qt ja faz
    isso sozinho quando a coluna fica mais estreita que o conteudo); o texto
    completo continua disponivel no tooltip ao passar o mouse."""
    modelo = tabela.model()
    if modelo is None:
        return
    for coluna in range(modelo.columnCount()):
        if tabela.columnWidth(coluna) > largura_maxima:
            tabela.setColumnWidth(coluna, largura_maxima)
