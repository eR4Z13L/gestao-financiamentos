"""Tela Todas as Propostas.

Lista as propostas de todos os clientes (nao so de um) em CARDS - um por
proposta, com so o essencial (cliente, status colorido e data); ao clicar num
card abre a tela de leitura da proposta (PropostaDialog, a mesma da Ficha de
Cliente) com todos os detalhes e os botoes de copiar. Busca livre e filtro por
status; cadastro/edicao/exclusao reaproveitam core/propostas.py e o mesmo
PropostaDialog.
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtCore import QModelIndex
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import data_store as bd
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core.formatting import formatar_data, formatar_reais
from core.validators import apenas_digitos
from desktop.dialogs.proposta_dialog import PropostaDialog
from desktop.widgets.lista_cartoes import ListaCartoes, ModeloCartoes

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

        self._modelo = ModeloCartoes(self)
        self._lista = ListaCartoes()
        self._lista.setModel(self._modelo)
        self._lista.definir_mensagem_vazia("Nenhuma proposta encontrada com esses filtros.")
        # um clique (ou Enter) no card abre a tela de leitura da proposta
        self._lista.acionado.connect(self._editar_selecionada)
        layout.addWidget(self._lista, stretch=1)

        # fixos embaixo: agem sobre o card selecionado (clicar num card ja o
        # deixa selecionado), e assim nao poluem cada card com botoes
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
        """VENDEDOR e so-leitura - ver mesmo metodo em FichaClienteScreen: nao
        ve os botoes de editar/excluir/criar, mas AINDA abre o card na tela de
        leitura (so leitura + copiar - o dialogo ja nao oferece "Habilitar
        edicao" pra quem nao e ADMIN). Sem isso, com os detalhes fora do card,
        o vendedor perderia acesso a valor/equipamento/banco/observacoes."""
        if not sessao_mod.eh_vendedor():
            return
        self._botao_editar.setVisible(False)
        self._botao_excluir.setVisible(False)
        self._botao_nova.setVisible(False)

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

        self._contador.setText(f"{len(df)} proposta(s) — clique em um card para ver os detalhes")

        # mantem selecionado o mesmo card (mesma proposta no arquivo) depois de
        # recarregar/filtrar - senao editar uma proposta "perde" o card
        selecionada = self._indice_real_selecionado()
        self._modelo.definir_itens(
            [
                {
                    "indice": indice,
                    # CPF sem cliente cadastrado: CLIENTE vem vazio - o card avisa em vez de ficar sem nome
                    "cliente": linha["CLIENTE"],
                    "status": linha["STATUS"],
                    "data": formatar_data(linha["DATA"]),
                }
                for indice, linha in df.iterrows()
            ]
        )
        if selecionada is not None:
            linha_nova = self._modelo.linha_do_indice_real(selecionada)
            if linha_nova is not None:
                self._lista.setCurrentIndex(self._modelo.index(linha_nova))

    # -- selecao e acoes ------------------------------------------------------

    def _indice_real_selecionado(self) -> int | None:
        linha = self._lista.linha_atual()
        return None if linha is None else self._modelo.indice_real(linha)

    def _linha_selecionada(self) -> tuple[int | None, dict | None]:
        indice_real = self._indice_real_selecionado()
        if indice_real is None:
            return None, None
        return indice_real, self._todas.loc[indice_real].to_dict()

    def _editar_selecionada(self, *_args) -> None:
        """Abre a tela de leitura da proposta selecionada (dela se chega a
        edicao, por "Habilitar edicao"). *_args absorve o numero da linha que
        o sinal `acionado` manda - so importa a selecao atual."""
        indice_real, proposta = self._linha_selecionada()
        if indice_real is None:
            QMessageBox.information(
                self, "Nenhuma proposta selecionada", "Clique em um card para selecionar a proposta."
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
                self, "Nenhuma proposta selecionada", "Clique em um card para selecionar a proposta a excluir."
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

        # o card excluido nao existe mais; os indices dos seguintes mudam - nao
        # da pra "manter a selecao" por indice real depois de uma exclusao
        self._lista.setCurrentIndex(QModelIndex())
        self._lista.clearSelection()
        self._carregar_dados()

    def _abrir_nova_proposta(self) -> None:
        dialogo = PropostaDialog(cpf=None, parent=self)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return
        self._carregar_dados()
