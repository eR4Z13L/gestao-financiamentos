"""Tela Ficha de Cliente.

Busca por nome/CPF + lista de clientes + a ficha do cliente selecionado
(dados + historico de propostas), com cadastro/edicao de cliente e
lancamento de propostas via dialogo.
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from core import clientes as clientes_mod
from core import data_store as bd
from core import propostas as propostas_mod
from core.formatting import formatar_data, formatar_meses, formatar_reais
from desktop import settings as settings_mod
from desktop.dialogs.cliente_dialog import ClienteDialog
from desktop.dialogs.proposta_dialog import PropostaDialog
from desktop.table_model import PandasTableModel
from desktop.widgets.shadow import aplicar_sombra_suave

_TEXTO_PADRAO_PAINEL = "Selecione um cliente na lista ao lado, ou cadastre um novo."

_COLUNAS_HISTORICO = ["DATA", "BANCO", "EQUIPAMENTO", "VALOR (R$)", "MESES", "STATUS", "TEMPO", "OBSERVAÇÕES"]


class FichaClienteScreen(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self._cpf_selecionado: str | None = None
        self._historico_atual: pd.DataFrame = pd.DataFrame(columns=_COLUNAS_HISTORICO)

        layout_principal = QVBoxLayout(self)
        layout_principal.setContentsMargins(24, 24, 24, 24)
        layout_principal.setSpacing(16)

        titulo = QLabel("🗂️ Ficha de Cliente")
        titulo.setProperty("role", "titulo")
        layout_principal.addWidget(titulo)

        self._busca = QLineEdit()
        self._busca.setPlaceholderText("🔎 Buscar cliente por nome ou CPF/CNPJ")
        self._busca.textChanged.connect(self._atualizar_lista)
        layout_principal.addWidget(self._busca)

        corpo = QHBoxLayout()
        corpo.setSpacing(16)

        coluna_lista = QVBoxLayout()
        self._contador = QLabel("")
        self._contador.setProperty("role", "secundario")
        coluna_lista.addWidget(self._contador)

        self._lista = QListWidget()
        self._lista.currentItemChanged.connect(self._selecionar_cliente)
        coluna_lista.addWidget(self._lista)

        botao_novo_cliente = QPushButton("+ Novo Cliente")
        botao_novo_cliente.setProperty("role", "botao_primario")
        botao_novo_cliente.clicked.connect(self._abrir_cadastro_cliente)
        coluna_lista.addWidget(botao_novo_cliente)

        corpo.addLayout(coluna_lista, 1)

        self._painel_stack = QStackedWidget()
        self._painel_stack.addWidget(self._construir_pagina_vazia())  # indice 0
        self._painel_stack.addWidget(self._construir_pagina_ficha())  # indice 1
        corpo.addWidget(self._painel_stack, 2)

        layout_principal.addLayout(corpo, stretch=1)

        self._atualizar_lista()

    # -- construcao dos widgets --------------------------------------------

    @staticmethod
    def _construir_pagina_vazia() -> QWidget:
        pagina = QWidget()
        layout = QVBoxLayout(pagina)
        texto = QLabel(_TEXTO_PADRAO_PAINEL)
        texto.setProperty("role", "secundario")
        texto.setWordWrap(True)
        texto.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(texto)
        layout.addStretch()
        return pagina

    def _construir_pagina_ficha(self) -> QWidget:
        pagina = QWidget()
        layout = QVBoxLayout(pagina)
        layout.setSpacing(16)

        cartao = QFrame()
        cartao.setProperty("role", "card")
        aplicar_sombra_suave(cartao, settings_mod.obter_tema())
        layout_cartao = QVBoxLayout(cartao)
        layout_cartao.setContentsMargins(16, 16, 16, 16)
        layout_cartao.setSpacing(12)

        cabecalho_ficha = QHBoxLayout()
        self._nome_label = QLabel("")
        self._nome_label.setProperty("role", "subtitulo")
        cabecalho_ficha.addWidget(self._nome_label)
        cabecalho_ficha.addStretch()
        botao_editar = QPushButton("Editar")
        botao_editar.setProperty("role", "botao_primario")
        botao_editar.clicked.connect(self._abrir_edicao_cliente)
        cabecalho_ficha.addWidget(botao_editar)
        botao_excluir = QPushButton("Excluir")
        botao_excluir.setProperty("role", "botao_perigo")
        botao_excluir.clicked.connect(self._excluir_cliente)
        cabecalho_ficha.addWidget(botao_excluir)
        layout_cartao.addLayout(cabecalho_ficha)

        grade = QGridLayout()
        grade.setHorizontalSpacing(24)
        grade.setVerticalSpacing(8)
        self._campo_cpf = self._criar_campo(grade, 0, 0, "CPF/CNPJ")
        self._campo_tipo = self._criar_campo(grade, 1, 0, "Tipo")
        self._campo_vendedor = self._criar_campo(grade, 2, 0, "Vendedor")
        self._campo_celular = self._criar_campo(grade, 0, 1, "Celular")
        self._campo_email = self._criar_campo(grade, 1, 1, "E-mail")
        self._campo_rede_social = self._criar_campo(grade, 2, 1, "Rede social")
        self._campo_nascimento = self._criar_campo(grade, 0, 2, "Nascimento")
        self._campo_cadastrado_em = self._criar_campo(grade, 1, 2, "Cadastrado em")
        self._campo_vinculado = self._criar_campo(grade, 2, 2, "Vinculado a")
        layout_cartao.addLayout(grade)

        self._campo_endereco = self._criar_campo(layout_cartao, None, None, "Endereço", em_grid=False)

        layout.addWidget(cartao)

        subtitulo_historico = QLabel("Histórico de propostas")
        subtitulo_historico.setProperty("role", "subtitulo")
        layout.addWidget(subtitulo_historico)

        self._historico_vazio = QLabel("Nenhuma proposta registrada para este cliente ainda.")
        self._historico_vazio.setProperty("role", "secundario")
        layout.addWidget(self._historico_vazio)

        self._modelo_historico = PandasTableModel()
        self._tabela_historico = QTableView()
        self._tabela_historico.setModel(self._modelo_historico)
        self._tabela_historico.setAlternatingRowColors(True)
        self._tabela_historico.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._tabela_historico.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._tabela_historico.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._tabela_historico.horizontalHeader().setStretchLastSection(True)
        self._tabela_historico.verticalHeader().setVisible(False)
        self._tabela_historico.doubleClicked.connect(self._editar_proposta_selecionada)
        layout.addWidget(self._tabela_historico, stretch=1)

        linha_botoes_historico = QHBoxLayout()
        botao_editar_proposta = QPushButton("Editar Proposta Selecionada")
        botao_editar_proposta.setProperty("role", "botao_primario")
        botao_editar_proposta.clicked.connect(self._editar_proposta_selecionada)
        linha_botoes_historico.addWidget(botao_editar_proposta)
        botao_nova_proposta = QPushButton("+ Nova Proposta")
        botao_nova_proposta.setProperty("role", "botao_primario")
        botao_nova_proposta.clicked.connect(self._abrir_nova_proposta)
        linha_botoes_historico.addWidget(botao_nova_proposta)
        layout.addLayout(linha_botoes_historico)

        return pagina

    @staticmethod
    def _criar_campo(container, row, col, titulo: str, em_grid: bool = True) -> QLabel:
        """Cria um par legenda/valor e devolve o QLabel do valor (pra dar
        setText depois). `container` e um QGridLayout (em_grid=True, usa
        row/col) ou um QBoxLayout comum (em_grid=False, so adiciona no fim).
        """
        caixa = QVBoxLayout()
        caixa.setSpacing(2)
        legenda = QLabel(titulo)
        legenda.setProperty("role", "campo_rotulo")
        valor = QLabel("—")
        valor.setProperty("role", "campo_valor")
        valor.setWordWrap(True)
        caixa.addWidget(legenda)
        caixa.addWidget(valor)

        if em_grid:
            container.addLayout(caixa, row, col)
        else:
            container.addLayout(caixa)
        return valor

    # -- carregamento de dados ----------------------------------------------

    def _atualizar_lista(self) -> None:
        termo = self._busca.text().strip()
        try:
            resultados = clientes_mod.buscar(termo) if termo else clientes_mod.listar_clientes()
        except FileNotFoundError:
            QMessageBox.critical(
                self,
                "Arquivo não encontrado",
                "Não foi possível encontrar o arquivo de dados (.xlsx). Confira o caminho configurado em config.py.",
            )
            return
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro ao buscar clientes", str(exc))
            return

        self._contador.setText(f"{len(resultados)} cliente(s)")

        # bloqueia sinais pra repovoar a lista sem disparar _selecionar_cliente
        # a cada item removido/inserido
        self._lista.blockSignals(True)
        self._lista.clear()
        for _, linha in resultados.iterrows():
            item = QListWidgetItem(f"{linha['CLIENTE']} — {linha['CPF/CNPJ']}")
            item.setData(Qt.ItemDataRole.UserRole, linha["CPF/CNPJ"])
            self._lista.addItem(item)
        self._lista.blockSignals(False)

        self._cpf_selecionado = None
        self._painel_stack.setCurrentIndex(0)

    def _selecionar_por_cpf(self, cpf: str) -> None:
        """Procura `cpf` na lista atual e seleciona (dispara _selecionar_cliente).
        Usado depois de cadastrar/editar um cliente, pra reabrir a ficha dele.
        """
        for i in range(self._lista.count()):
            item = self._lista.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == cpf:
                self._lista.setCurrentItem(item)
                return

    def _selecionar_cliente(self, atual: QListWidgetItem | None, _anterior: QListWidgetItem | None = None) -> None:
        if atual is None:
            self._cpf_selecionado = None
            self._painel_stack.setCurrentIndex(0)
            return

        cpf = atual.data(Qt.ItemDataRole.UserRole)
        try:
            cliente = clientes_mod.buscar_por_cpf(cpf)
            historico = propostas_mod.historico_por_cpf(cpf)
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro ao carregar cliente", str(exc))
            return

        if cliente is None:
            QMessageBox.warning(self, "Cliente não encontrado", "Este cliente pode ter sido removido.")
            self._cpf_selecionado = None
            self._painel_stack.setCurrentIndex(0)
            return

        self._cpf_selecionado = cpf
        self._preencher_ficha(cliente, historico)
        self._painel_stack.setCurrentIndex(1)

    def _preencher_ficha(self, cliente: dict, historico: pd.DataFrame) -> None:
        # guarda os valores "crus" (Timestamp/float, indice = posicao real no
        # arquivo) - a tabela exibida logo abaixo mostra uma versao formatada
        # pra leitura, mas editar uma proposta precisa dos valores originais
        self._historico_atual = historico

        self._nome_label.setText(cliente["CLIENTE"])
        self._campo_cpf.setText(cliente["CPF/CNPJ"])
        self._campo_tipo.setText(cliente["TIPO"] or "—")
        self._campo_vendedor.setText(cliente["VENDEDOR"] or "—")
        self._campo_celular.setText(cliente["CELULAR"] or "—")
        self._campo_email.setText(cliente["EMAIL"] or "—")
        self._campo_rede_social.setText(cliente["REDE SOCIAL"] or "—")
        self._campo_nascimento.setText(formatar_data(cliente.get("NASCIMENTO")))
        self._campo_cadastrado_em.setText(formatar_data(cliente.get("DATA CADASTRO")))
        self._campo_vinculado.setText(cliente["VINCULADO"] or "—")
        self._campo_endereco.setText(cliente["ENDEREÇO"] or "—")

        if historico.empty:
            self._historico_vazio.setVisible(True)
            self._tabela_historico.setVisible(False)
            self._modelo_historico.definir_dataframe(pd.DataFrame(columns=_COLUNAS_HISTORICO))
            return

        self._historico_vazio.setVisible(False)
        self._tabela_historico.setVisible(True)

        exibicao = historico[_COLUNAS_HISTORICO].copy()
        exibicao["DATA"] = exibicao["DATA"].map(formatar_data)
        exibicao["VALOR (R$)"] = exibicao["VALOR (R$)"].map(formatar_reais)
        exibicao["MESES"] = exibicao["MESES"].map(formatar_meses)
        self._modelo_historico.definir_dataframe(exibicao)
        self._tabela_historico.resizeColumnsToContents()

    # -- dialogos: cadastro/edicao de cliente e nova proposta ---------------

    def _abrir_cadastro_cliente(self) -> None:
        dialogo = ClienteDialog(cliente=None, parent=self)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return
        # limpa a busca pra garantir que o cliente novo apareca na lista,
        # mesmo que o texto buscado antes nao bata com o nome/CPF dele
        self._busca.setText("")
        self._atualizar_lista()
        self._selecionar_por_cpf(dialogo.cpf_salvo)

    def _abrir_edicao_cliente(self) -> None:
        if not self._cpf_selecionado:
            return
        cliente = clientes_mod.buscar_por_cpf(self._cpf_selecionado)
        if cliente is None:
            return
        dialogo = ClienteDialog(cliente=cliente, parent=self)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return
        self._busca.setText("")
        self._atualizar_lista()
        self._selecionar_por_cpf(dialogo.cpf_salvo)

    def _abrir_nova_proposta(self) -> None:
        if not self._cpf_selecionado:
            return
        dialogo = PropostaDialog(self._cpf_selecionado, self._nome_label.text(), parent=self)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return
        # so precisa recarregar a ficha atual (historico) - a lista de
        # clientes nao muda ao lancar uma proposta
        cliente = clientes_mod.buscar_por_cpf(self._cpf_selecionado)
        historico = propostas_mod.historico_por_cpf(self._cpf_selecionado)
        self._preencher_ficha(cliente, historico)

    def _editar_proposta_selecionada(self, *_args) -> None:
        """*_args absorve o QModelIndex que o sinal doubleClicked manda -
        tanto faz qual celula foi clicada, so importa a linha selecionada."""
        if not self._cpf_selecionado:
            return

        linhas_selecionadas = self._tabela_historico.selectionModel().selectedRows()
        if not linhas_selecionadas:
            QMessageBox.information(
                self, "Nenhuma proposta selecionada", "Selecione uma proposta na tabela para editar."
            )
            return

        indice_real = self._modelo_historico.indice_real(linhas_selecionadas[0].row())
        proposta = self._historico_atual.loc[indice_real].to_dict()

        dialogo = PropostaDialog(
            self._cpf_selecionado, self._nome_label.text(), proposta=proposta, indice=indice_real, parent=self
        )
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return

        cliente = clientes_mod.buscar_por_cpf(self._cpf_selecionado)
        historico = propostas_mod.historico_por_cpf(self._cpf_selecionado)
        self._preencher_ficha(cliente, historico)

    def _excluir_cliente(self) -> None:
        if not self._cpf_selecionado:
            return

        nome = self._nome_label.text()
        historico = propostas_mod.historico_por_cpf(self._cpf_selecionado)

        mensagem = f"Tem certeza que deseja excluir '{nome}'? Essa ação não pode ser desfeita."
        if not historico.empty:
            mensagem += (
                f"\n\nAtenção: existem {len(historico)} proposta(s) lançada(s) para este cliente. "
                "Elas NÃO serão apagadas, mas deixarão de mostrar o nome e o vendedor "
                "corretos dali pra frente (o vínculo é feito pelo CPF)."
            )

        resposta = QMessageBox.question(
            self,
            "Excluir cliente",
            mensagem,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resposta != QMessageBox.StandardButton.Yes:
            return

        try:
            clientes_mod.remover_cliente(self._cpf_selecionado)
        except clientes_mod.ErroCliente as exc:
            QMessageBox.warning(self, "Não foi possível excluir", str(exc))
            return
        except bd.ErroArquivoBloqueado as exc:
            QMessageBox.critical(self, "Arquivo bloqueado", str(exc))
            return
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro inesperado ao excluir", str(exc))
            return

        self._busca.setText("")
        self._atualizar_lista()
