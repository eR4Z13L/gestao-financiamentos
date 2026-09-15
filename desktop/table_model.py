"""Model generico do Qt pra exibir qualquer DataFrame do pandas numa QTableView.

Toda tela que precisa mostrar uma tabela so cria um PandasTableModel(df) e um
QTableView - evita reescrever a logica de popular celulas em cada tela.
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


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
        if role == Qt.ItemDataRole.DisplayRole:
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
