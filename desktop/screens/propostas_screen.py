"""Tela Todas as Propostas.

Lista as propostas de todos os clientes (nao so de um), com busca livre,
filtro por status e ordenacao por coluna (clicando no cabecalho, via
QSortFilterProxyModel). Cadastro/edicao/exclusao reaproveitam core/propostas.py
e o mesmo PropostaDialog usado na Ficha de Cliente.
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtCore import Qt, QSortFilterProxyModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from core import data_store as bd
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core.formatting import formatar_data, formatar_meses, formatar_reais
from core.validators import apenas_digitos
from desktop.dialogs.proposta_dialog import PropostaDialog
from desktop.table_model import PandasTableModel, limitar_largura_colunas

_COLUNAS_EXIBICAO = [
    "DATA", "VENDEDOR", "CLIENTE", "CPF", "EQUIPAMENTO", "BANCO",
    "VALOR (R$)", "MESES", "STATUS", "TEMPO", "OBSERVAÇÕES",
]
_FILTRO_TODOS = "Todos"


class PropostasScreen(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self._todas = pd.DataFrame(columns=_COLUNAS_EXIBICAO)  # dados crus; indice = posicao real no arquivo

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        cabecalho = QHBoxLayout()
        titulo = QLabel("📋 Todas as Propostas")
        titulo.setProperty("role", "titulo")
        cabecalho.addWidget(titulo)
        cabecalho.addStretch()
        botao_atualizar = QPushButton("Atualizar")
        botao_atualizar.setProperty("role", "botao_primario")
        botao_atualizar.clicked.connect(self._carregar_dados)
        cabecalho.addWidget(botao_atualizar)
        layout.addLayout(cabecalho)

        linha_filtros = QHBoxLayout()
        self._busca = QLineEdit()
        self._busca.setPlaceholderText("🔎 Buscar por cliente, CPF, banco ou equipamento")
        self._busca.textChanged.connect(self._aplicar_filtros)
        linha_filtros.addWidget(self._busca, 3)

        self._filtro_status = QComboBox()
        self._filtro_status.currentIndexChanged.connect(self._aplicar_filtros)
        linha_filtros.addWidget(self._filtro_status, 1)
        layout.addLayout(linha_filtros)

        self._contador = QLabel("")
        self._contador.setProperty("role", "secundario")
        layout.addWidget(self._contador)

        self._modelo = PandasTableModel()
        self._proxy = QSortFilterProxyModel()
        self._proxy.setSourceModel(self._modelo)
        self._tabela = QTableView()
        self._tabela.setModel(self._proxy)
        self._tabela.setSortingEnabled(True)
        self._tabela.setAlternatingRowColors(True)
        self._tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._tabela.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._tabela.horizontalHeader().setStretchLastSection(True)
        self._tabela.verticalHeader().setVisible(False)
        self._tabela.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._tabela.doubleClicked.connect(self._editar_selecionada)
        layout.addWidget(self._tabela, stretch=1)

        linha_botoes = QHBoxLayout()
        self._botao_editar = QPushButton("Editar")
        self._botao_editar.setProperty("role", "botao_primario")
        self._botao_editar.clicked.connect(self._editar_selecionada)
        linha_botoes.addWidget(self._botao_editar)
        self._botao_excluir = QPushButton("Excluir")
        self._botao_excluir.setProperty("role", "botao_perigo")
        self._botao_excluir.clicked.connect(self._excluir_selecionada)
        linha_botoes.addWidget(self._botao_excluir)
        self._botao_nova = QPushButton("+ Nova Proposta")
        self._botao_nova.setProperty("role", "botao_primario")
        self._botao_nova.clicked.connect(self._abrir_nova_proposta)
        linha_botoes.addWidget(self._botao_nova)
        layout.addLayout(linha_botoes)

        self._aplicar_restricoes_papel()
        self._carregar_dados()

    def _aplicar_restricoes_papel(self) -> None:
        """VENDEDOR e so-leitura - ver mesmo metodo em FichaClienteScreen."""
        if not sessao_mod.eh_vendedor():
            return
        self._botao_editar.setVisible(False)
        self._botao_excluir.setVisible(False)
        self._botao_nova.setVisible(False)
        self._tabela.doubleClicked.disconnect(self._editar_selecionada)

    # -- carregamento e filtro -----------------------------------------------

    def _carregar_dados(self) -> None:
        try:
            self._todas = propostas_mod.listar_propostas()
        except FileNotFoundError:
            QMessageBox.critical(
                self,
                "Arquivo não encontrado",
                "Não foi possível encontrar o arquivo de dados (.xlsx). Confira o caminho configurado em config.py.",
            )
            return
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro ao carregar propostas", str(exc))
            return

        status_antes = self._filtro_status.currentText() if self._filtro_status.count() else _FILTRO_TODOS
        opcoes_status = [_FILTRO_TODOS] + sorted({s for s in self._todas["STATUS"] if s})
        self._filtro_status.blockSignals(True)
        self._filtro_status.clear()
        self._filtro_status.addItems(opcoes_status)
        if status_antes in opcoes_status:
            self._filtro_status.setCurrentText(status_antes)
        self._filtro_status.blockSignals(False)

        self._aplicar_filtros()

    def _aplicar_filtros(self) -> None:
        df = self._todas

        termo = self._busca.text().strip()
        if termo:
            termo_upper = termo.upper()
            termo_digitos = apenas_digitos(termo)
            mascara = (
                df["CLIENTE"].str.upper().str.contains(termo_upper, na=False)
                | df["BANCO"].str.upper().str.contains(termo_upper, na=False)
                | df["EQUIPAMENTO"].str.upper().str.contains(termo_upper, na=False)
            )
            if termo_digitos:
                mascara = mascara | df["CPF"].map(apenas_digitos).str.contains(termo_digitos, na=False)
            df = df[mascara]

        status_selecionado = self._filtro_status.currentText()
        if status_selecionado and status_selecionado != _FILTRO_TODOS:
            df = df[df["STATUS"] == status_selecionado]

        self._contador.setText(f"{len(df)} proposta(s)")

        exibicao = df[_COLUNAS_EXIBICAO].copy()
        exibicao["DATA"] = exibicao["DATA"].map(formatar_data)
        exibicao["VALOR (R$)"] = exibicao["VALOR (R$)"].map(formatar_reais)
        exibicao["MESES"] = exibicao["MESES"].map(formatar_meses)
        self._modelo.definir_dataframe(exibicao)
        self._tabela.resizeColumnsToContents()
        limitar_largura_colunas(self._tabela)

    # -- selecao e acoes ------------------------------------------------------

    def _linha_selecionada(self) -> tuple[int | None, dict | None]:
        selecionadas = self._tabela.selectionModel().selectedRows()
        if not selecionadas:
            return None, None
        indice_fonte = self._proxy.mapToSource(selecionadas[0])
        indice_real = self._modelo.indice_real(indice_fonte.row())
        return indice_real, self._todas.loc[indice_real].to_dict()

    def _editar_selecionada(self, *_args) -> None:
        """*_args absorve o QModelIndex que o sinal doubleClicked manda."""
        indice_real, proposta = self._linha_selecionada()
        if indice_real is None:
            QMessageBox.information(
                self, "Nenhuma proposta selecionada", "Selecione uma proposta na tabela para editar."
            )
            return

        dialogo = PropostaDialog(proposta["CPF"], proposta["CLIENTE"], proposta=proposta, indice=indice_real, parent=self)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return
        self._carregar_dados()

    def _excluir_selecionada(self) -> None:
        indice_real, proposta = self._linha_selecionada()
        if indice_real is None:
            QMessageBox.information(
                self, "Nenhuma proposta selecionada", "Selecione uma proposta na tabela para excluir."
            )
            return

        valor_texto = formatar_reais(proposta["VALOR (R$)"])
        resposta = QMessageBox.question(
            self,
            "Excluir proposta",
            f"Tem certeza que deseja excluir a proposta de '{proposta['CLIENTE']}' "
            f"({proposta['BANCO'] or 'sem banco'}, {valor_texto})? Essa ação não pode ser desfeita.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resposta != QMessageBox.StandardButton.Yes:
            return

        try:
            propostas_mod.remover_proposta(indice_real)
        except propostas_mod.ErroProposta as exc:
            QMessageBox.warning(self, "Não foi possível excluir", str(exc))
            return
        except bd.ErroArquivoBloqueado as exc:
            QMessageBox.critical(self, "Arquivo bloqueado", str(exc))
            return
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro inesperado ao excluir", str(exc))
            return

        self._carregar_dados()

    def _abrir_nova_proposta(self) -> None:
        dialogo = PropostaDialog(cpf=None, parent=self)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return
        self._carregar_dados()
