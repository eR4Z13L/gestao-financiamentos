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
from core import sessao as sessao_mod
from core.formatting import formatar_data, formatar_meses, formatar_reais
from desktop import settings as settings_mod
from desktop.dialogs.cliente_dialog import ClienteDialog
from desktop.dialogs.proposta_dialog import PropostaDialog
from desktop.table_model import PandasTableModel, limitar_largura_colunas
from desktop.widgets.botao_copiar import BotaoCopiar
from desktop.widgets.quebra_texto import texto_quebravel
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

        self._botao_novo_cliente = QPushButton("+ Novo Cliente")
        self._botao_novo_cliente.setProperty("role", "botao_primario")
        self._botao_novo_cliente.clicked.connect(self._abrir_cadastro_cliente)
        coluna_lista.addWidget(self._botao_novo_cliente)

        corpo.addLayout(coluna_lista, 1)

        self._painel_stack = QStackedWidget()
        self._painel_stack.addWidget(self._construir_pagina_vazia())  # indice 0
        self._painel_stack.addWidget(self._construir_pagina_ficha())  # indice 1
        corpo.addWidget(self._painel_stack, 2)

        layout_principal.addLayout(corpo, stretch=1)

        self._aplicar_restricoes_papel()
        self._atualizar_lista()

    def _aplicar_restricoes_papel(self) -> None:
        """VENDEDOR e so-leitura: nenhum botao de criar/editar/excluir pode
        aparecer (a camada core/*.py ja bloqueia a acao de verdade via
        sessao.exigir_admin(), isso aqui e so pra nao mostrar um botao que
        sempre daria erro)."""
        if not sessao_mod.eh_vendedor():
            return
        self._botao_novo_cliente.setVisible(False)
        self._botao_editar_cliente.setVisible(False)
        self._botao_excluir_cliente.setVisible(False)
        self._botao_editar_proposta.setVisible(False)
        self._botao_nova_proposta.setVisible(False)
        self._tabela_historico.doubleClicked.disconnect(self._editar_proposta_selecionada)

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
        self._botao_editar_cliente = QPushButton("Editar")
        self._botao_editar_cliente.setProperty("role", "botao_primario")
        self._botao_editar_cliente.clicked.connect(self._abrir_edicao_cliente)
        cabecalho_ficha.addWidget(self._botao_editar_cliente)
        self._botao_excluir_cliente = QPushButton("Excluir")
        self._botao_excluir_cliente.setProperty("role", "botao_perigo")
        self._botao_excluir_cliente.clicked.connect(self._excluir_cliente)
        cabecalho_ficha.addWidget(self._botao_excluir_cliente)
        layout_cartao.addLayout(cabecalho_ficha)

        grade = self._nova_grade()
        # informacoes principais (as duas primeiras linhas), logo abaixo do
        # nome do cliente: quem e, quando nasceu, como falar com ele
        self._campo_cpf = self._criar_campo(grade, 0, 0, "CPF/CNPJ")
        self._campo_nascimento = self._criar_campo(grade, 0, 1, "Nascimento")
        self._campo_tipo = self._criar_campo(grade, 0, 2, "Tipo")
        self._campo_celular = self._criar_campo(grade, 1, 0, "Celular")
        self._campo_email = self._criar_campo(grade, 1, 1, "E-mail")
        self._campo_vendedor = self._criar_campo(grade, 1, 2, "Vendedor")
        # informacoes secundarias
        self._campo_rede_social = self._criar_campo(grade, 2, 0, "Rede social")
        self._campo_vinculado = self._criar_campo(grade, 2, 1, "Vinculado a")
        self._campo_cadastrado_em = self._criar_campo(grade, 2, 2, "Cadastrado em")
        self._campo_nome_pai = self._criar_campo(grade, 3, 0, "Nome do pai")
        self._campo_nome_mae = self._criar_campo(grade, 3, 1, "Nome da mãe")
        self._campo_profissao = self._criar_campo(grade, 3, 2, "Profissão")
        layout_cartao.addLayout(grade)

        subtitulo_endereco = QLabel("Endereço")
        subtitulo_endereco.setProperty("role", "subtitulo")
        layout_cartao.addWidget(subtitulo_endereco)

        # cada campo do endereco tem seu botao de copiar (a ideia e copiar
        # um de cada vez pra colar em outro sistema)
        grade_endereco = self._nova_grade()
        self._campo_cep = self._criar_campo_copiavel(grade_endereco, 0, 0, "CEP")
        self._campo_logradouro = self._criar_campo_copiavel(grade_endereco, 0, 1, "Logradouro")
        self._campo_numero = self._criar_campo_copiavel(grade_endereco, 0, 2, "Número")
        self._campo_complemento = self._criar_campo_copiavel(grade_endereco, 1, 0, "Complemento")
        self._campo_bairro = self._criar_campo_copiavel(grade_endereco, 1, 1, "Bairro")
        # Cidade e UF dividem a 3a coluna (a UF e curta) - assim a grade
        # continua com as mesmas 3 colunas da grade de dados, la em cima
        caixa_cidade, self._campo_cidade = self._caixa_copiavel("Cidade")
        caixa_uf, self._campo_uf = self._caixa_copiavel("UF")
        linha_cidade_uf = QHBoxLayout()
        linha_cidade_uf.setSpacing(12)
        linha_cidade_uf.addLayout(caixa_cidade, 3)
        linha_cidade_uf.addLayout(caixa_uf, 1)
        grade_endereco.addLayout(linha_cidade_uf, 1, 2)
        layout_cartao.addLayout(grade_endereco)

        # so aparece pra quem tem endereco antigo que a migracao nao separou
        self._aviso_endereco_revisar = QLabel("")
        self._aviso_endereco_revisar.setProperty("role", "secundario")
        self._aviso_endereco_revisar.setWordWrap(True)
        self._aviso_endereco_revisar.setVisible(False)
        layout_cartao.addWidget(self._aviso_endereco_revisar)

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
        self._tabela_historico.setTextElideMode(Qt.TextElideMode.ElideRight)
        self._tabela_historico.doubleClicked.connect(self._editar_proposta_selecionada)
        layout.addWidget(self._tabela_historico, stretch=1)

        linha_botoes_historico = QHBoxLayout()
        self._botao_editar_proposta = QPushButton("Editar Proposta Selecionada")
        self._botao_editar_proposta.setProperty("role", "botao_primario")
        self._botao_editar_proposta.clicked.connect(self._editar_proposta_selecionada)
        linha_botoes_historico.addWidget(self._botao_editar_proposta)
        self._botao_nova_proposta = QPushButton("+ Nova Proposta")
        self._botao_nova_proposta.setProperty("role", "botao_primario")
        self._botao_nova_proposta.clicked.connect(self._abrir_nova_proposta)
        linha_botoes_historico.addWidget(self._botao_nova_proposta)
        layout.addLayout(linha_botoes_historico)

        return pagina

    @staticmethod
    def _nova_grade() -> QGridLayout:
        grade = QGridLayout()
        grade.setHorizontalSpacing(24)
        grade.setVerticalSpacing(8)
        # tres colunas iguais - as duas grades do cartao (dados e endereco)
        # ficam alinhadas entre si
        for coluna in range(3):
            grade.setColumnStretch(coluna, 1)
        return grade

    @staticmethod
    def _criar_rotulo_valor() -> QLabel:
        valor = QLabel("—")
        valor.setProperty("role", "campo_valor")
        valor.setWordWrap(True)
        return valor

    @staticmethod
    def _criar_campo(grade: QGridLayout, row: int, col: int, titulo: str) -> QLabel:
        """Cria um par legenda/valor na grade e devolve o QLabel do valor (pra
        dar setText depois)."""
        caixa = QVBoxLayout()
        caixa.setSpacing(2)
        legenda = QLabel(titulo)
        legenda.setProperty("role", "campo_rotulo")
        valor = FichaClienteScreen._criar_rotulo_valor()
        caixa.addWidget(legenda)
        caixa.addWidget(valor)
        grade.addLayout(caixa, row, col)
        return valor

    @staticmethod
    def _caixa_copiavel(titulo: str) -> tuple[QVBoxLayout, QLabel]:
        """Legenda + valor + botao Copiar ao lado do valor. Devolve o layout
        (pra quem chamou encaixar onde quiser) e o QLabel do valor. O que o
        botao copia e o texto CRU guardado na propriedade "texto_cru" (ver
        _definir_valor_copiavel), nunca o que aparece no QLabel: la o texto
        tem "—" quando vazio e pontos de quebra invisiveis (texto_quebravel)."""
        caixa = QVBoxLayout()
        caixa.setSpacing(2)
        legenda = QLabel(titulo)
        legenda.setProperty("role", "campo_rotulo")
        caixa.addWidget(legenda)

        valor = FichaClienteScreen._criar_rotulo_valor()
        botao = BotaoCopiar(lambda: valor.property("texto_cru") or "")
        linha = QHBoxLayout()
        linha.setSpacing(4)
        linha.addWidget(valor, stretch=1)
        linha.addWidget(botao, alignment=Qt.AlignmentFlag.AlignTop)
        caixa.addLayout(linha)
        return caixa, valor

    @staticmethod
    def _criar_campo_copiavel(grade: QGridLayout, row: int, col: int, titulo: str) -> QLabel:
        """Como _criar_campo, mas com um botao Copiar ao lado do valor."""
        caixa, valor = FichaClienteScreen._caixa_copiavel(titulo)
        grade.addLayout(caixa, row, col)
        return valor

    @staticmethod
    def _definir_valor_copiavel(rotulo: QLabel, texto: str) -> None:
        rotulo.setProperty("texto_cru", texto)
        rotulo.setText(texto_quebravel(texto) or "—")

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

        self._nome_label.setText(texto_quebravel(cliente["CLIENTE"]))
        self._campo_cpf.setText(cliente["CPF/CNPJ"])
        self._campo_tipo.setText(cliente["TIPO"] or "—")
        self._campo_vendedor.setText(cliente["VENDEDOR"] or "—")
        self._campo_celular.setText(cliente["CELULAR"] or "—")
        self._campo_email.setText(texto_quebravel(cliente["EMAIL"]) or "—")
        self._campo_rede_social.setText(texto_quebravel(cliente["REDE SOCIAL"]) or "—")
        self._campo_nascimento.setText(formatar_data(cliente.get("NASCIMENTO")))
        self._campo_cadastrado_em.setText(formatar_data(cliente.get("DATA CADASTRO")))
        self._campo_vinculado.setText(texto_quebravel(cliente["VINCULADO"]) or "—")
        self._campo_nome_pai.setText(texto_quebravel(cliente["NOME DO PAI"]) or "—")
        self._campo_nome_mae.setText(texto_quebravel(cliente["NOME DA MÃE"]) or "—")
        self._campo_profissao.setText(texto_quebravel(cliente["PROFISSÃO"]) or "—")

        self._definir_valor_copiavel(self._campo_cep, cliente["CEP"])
        self._definir_valor_copiavel(self._campo_logradouro, cliente["LOGRADOURO"])
        self._definir_valor_copiavel(self._campo_numero, cliente["NÚMERO"])
        self._definir_valor_copiavel(self._campo_complemento, cliente["COMPLEMENTO"])
        self._definir_valor_copiavel(self._campo_bairro, cliente["BAIRRO"])
        self._definir_valor_copiavel(self._campo_cidade, cliente["CIDADE"])
        self._definir_valor_copiavel(self._campo_uf, cliente["UF"])

        texto_revisar = cliente["ENDEREÇO (REVISAR)"]
        self._aviso_endereco_revisar.setVisible(bool(texto_revisar))
        if texto_revisar:
            self._aviso_endereco_revisar.setText(
                f"⚠ Endereço a revisar (ainda não separado nos campos acima): {texto_quebravel(texto_revisar)}"
            )

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
        limitar_largura_colunas(self._tabela_historico)

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
            QMessageBox.warning(self, "Cliente não encontrado", "Este cliente pode ter sido removido.")
            self._cpf_selecionado = None
            self._painel_stack.setCurrentIndex(0)
            return
        dialogo = ClienteDialog(cliente=cliente, parent=self)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return
        self._busca.setText("")
        self._atualizar_lista()
        self._selecionar_por_cpf(dialogo.cpf_salvo)

    def _recarregar_ficha_atual(self) -> bool:
        """Recarrega cliente + historico do CPF selecionado, com a mesma
        protecao contra erro de leitura que o primeiro carregamento
        (_selecionar_cliente) ja tinha - antes disso, so o carregamento
        inicial estava protegido, e um erro de leitura aqui (ex: arquivo
        bloqueado no meio da releitura) derrubava a tela sem aviso nenhum.
        Devolve False se o cliente sumiu ou deu erro (a tela ja foi avisada
        e ajustada nesse caso).
        """
        try:
            cliente = clientes_mod.buscar_por_cpf(self._cpf_selecionado)
            historico = propostas_mod.historico_por_cpf(self._cpf_selecionado)
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro ao recarregar cliente", str(exc))
            return False
        if cliente is None:
            QMessageBox.warning(self, "Cliente não encontrado", "Este cliente pode ter sido removido.")
            self._cpf_selecionado = None
            self._painel_stack.setCurrentIndex(0)
            return False
        self._preencher_ficha(cliente, historico)
        return True

    def _abrir_nova_proposta(self) -> None:
        if not self._cpf_selecionado:
            return
        dialogo = PropostaDialog(self._cpf_selecionado, self._nome_label.text(), parent=self)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return
        # so precisa recarregar a ficha atual (historico) - a lista de
        # clientes nao muda ao lancar uma proposta
        self._recarregar_ficha_atual()

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

        self._recarregar_ficha_atual()

    def _excluir_cliente(self) -> None:
        if not self._cpf_selecionado:
            return

        nome = self._nome_label.text()
        try:
            historico = propostas_mod.historico_por_cpf(self._cpf_selecionado)
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro ao carregar histórico", str(exc))
            return

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
