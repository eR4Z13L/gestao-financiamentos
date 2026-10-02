"""Cartao "Bancos" da aba Cadastros (Administracao): a lista fechada do campo Banco das propostas.
As regras ficam em core/bancos.py; aqui so a tela (mesmo padrao do cartao de Vendedores)."""

from __future__ import annotations

import pandas as pd
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from core import bancos as bancos_mod
from core import data_store as bd
from desktop import settings as settings_mod
from desktop.table_model import PandasTableModel
from desktop.widgets.shadow import aplicar_sombra_suave


class CadastroBancos(QFrame):
    alterado = Signal()  # o cadastro (e talvez as propostas, ao renomear) mudou: as outras telas releem

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("role", "card")
        aplicar_sombra_suave(self, settings_mod.obter_tema())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        cabecalho = QHBoxLayout()
        subtitulo = QLabel("Bancos")
        subtitulo.setProperty("role", "subtitulo")
        cabecalho.addWidget(subtitulo)
        cabecalho.addStretch()
        self._botao_novo = QPushButton("+ Novo Banco")
        self._botao_novo.setProperty("role", "botao_primario")
        self._botao_novo.clicked.connect(self._cadastrar)
        cabecalho.addWidget(self._botao_novo)
        layout.addLayout(cabecalho)

        explicacao = QLabel(
            "A lista do campo Banco das propostas. Desativar tira o banco da lista, sem mexer nas propostas "
            f"antigas; renomear corrige também as propostas. \"{bancos_mod.BANCO_TODOS}\" (enviada a todos os "
            "bancos) é uma opção fixa do formulário."
        )
        explicacao.setProperty("role", "secundario")
        explicacao.setWordWrap(True)
        layout.addWidget(explicacao)

        self._modelo = PandasTableModel()
        self._tabela = QTableView()
        self._tabela.setModel(self._modelo)
        self._tabela.setAlternatingRowColors(True)
        self._tabela.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._tabela.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._tabela.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._tabela.horizontalHeader().setStretchLastSection(True)
        self._tabela.verticalHeader().setVisible(False)
        layout.addWidget(self._tabela, stretch=1)

        linha_botoes = QHBoxLayout()
        self._botao_renomear = QPushButton("Renomear")
        self._botao_renomear.clicked.connect(self._renomear)
        self._botao_ativo = QPushButton("Desativar")
        self._botao_ativo.clicked.connect(self._alternar_ativo)
        self._botao_excluir = QPushButton("Excluir")
        self._botao_excluir.clicked.connect(self._excluir)
        for botao in (self._botao_renomear, self._botao_ativo, self._botao_excluir):
            linha_botoes.addWidget(botao)
        layout.addLayout(linha_botoes)
        self._tabela.selectionModel().selectionChanged.connect(self._atualizar_botoes)

        self._por_nome: dict[str, tuple[bool, int]] = {}  # nome -> (ativo?, propostas)
        self.recarregar()

    def recarregar(self) -> None:
        try:
            df = bancos_mod.listar_bancos()
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro ao carregar bancos", str(exc))
            return
        self._por_nome = {n: (a, p) for n, a, p in zip(df["NOME"], df["ATIVO"], df["PROPOSTAS"])}
        # o NOME vira o indice (indice_real() devolve o banco selecionado) e tambem uma coluna, pra aparecer
        exibicao = pd.DataFrame({
            "Nome": df["NOME"].tolist(),
            "Situação": ["Ativo" if a else "Inativo" for a in df["ATIVO"]],
            "Propostas": df["PROPOSTAS"].tolist(),
        }, index=df["NOME"].tolist())
        self._modelo.definir_dataframe(exibicao)
        self._tabela.resizeColumnsToContents()
        self._atualizar_botoes()

    def _selecionado(self) -> str | None:
        linhas = self._tabela.selectionModel().selectedRows()
        return self._modelo.indice_real(linhas[0].row()) if linhas else None

    def _atualizar_botoes(self, *_args) -> None:
        nome = self._selecionado()
        ativo, propostas = self._por_nome.get(nome, (True, 0)) if nome else (True, 0)
        for botao in (self._botao_renomear, self._botao_ativo, self._botao_excluir):
            botao.setEnabled(nome is not None)
        self._botao_ativo.setText("Desativar" if ativo else "Reativar")
        self._botao_excluir.setToolTip(
            f"Usado em {propostas} proposta(s): não dá para excluir, só desativar." if propostas
            else "Apaga o banco do cadastro (nenhuma proposta usa)."
        )

    def _depois_de_mudar(self, titulo: str, texto: str) -> None:
        self.recarregar()
        self.alterado.emit()
        QMessageBox.information(self, titulo, texto)

    def _executar(self, titulo_erro: str, acao):
        """Roda `acao` mostrando o erro (nunca em silencio). Devolve (deu_certo, resultado)."""
        try:
            return True, acao()
        except bancos_mod.ErroBanco as exc:
            QMessageBox.warning(self, titulo_erro, str(exc))
        except bd.ErroArquivoBloqueado as exc:
            QMessageBox.critical(self, "Arquivo bloqueado", str(exc))
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, f"Erro inesperado: {titulo_erro.lower()}", f"{type(exc).__name__}: {exc}")
        return False, None

    def _cadastrar(self) -> None:
        nome, ok = QInputDialog.getText(self, "Novo banco", "Nome do banco/financeira:")
        if not ok:
            return
        deu_certo, salvo = self._executar("Não foi possível cadastrar", lambda: bancos_mod.adicionar_banco(nome))
        if deu_certo:
            self._depois_de_mudar("Banco cadastrado", f"'{salvo}' já aparece na lista do formulário de proposta.")

    def _renomear(self) -> None:
        nome = self._selecionado()
        if nome is None:
            return
        novo, ok = QInputDialog.getText(self, "Renomear banco", "Novo nome:", text=nome)
        if not ok:
            return
        deu_certo, quantidade = self._executar("Não foi possível renomear", lambda: bancos_mod.renomear_banco(nome, novo))
        if deu_certo:
            extra = f" {quantidade} proposta(s) também foram atualizadas." if quantidade else ""
            self._depois_de_mudar("Banco renomeado", f"'{nome}' agora é '{novo.strip()}'.{extra}")

    def _alternar_ativo(self) -> None:
        nome = self._selecionado()
        if nome is None:
            return
        ativo, _propostas = self._por_nome.get(nome, (True, 0))
        if ativo:
            resposta = QMessageBox.question(
                self, "Desativar banco",
                f"Desativar '{nome}'? Ele sai da lista do formulário de proposta; as propostas antigas "
                "continuam com ele.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
            )
            if resposta != QMessageBox.StandardButton.Yes:
                return
            deu_certo, _ = self._executar("Não foi possível desativar", lambda: bancos_mod.desativar_banco(nome))
            if deu_certo:
                self._depois_de_mudar("Banco desativado", f"'{nome}' não aparece mais na lista do formulário.")
            return
        deu_certo, _ = self._executar("Não foi possível reativar", lambda: bancos_mod.reativar_banco(nome))
        if deu_certo:
            self._depois_de_mudar("Banco reativado", f"'{nome}' voltou para a lista do formulário.")

    def _excluir(self) -> None:
        nome = self._selecionado()
        if nome is None:
            return
        resposta = QMessageBox.question(
            self, "Excluir banco", f"Excluir '{nome}' do cadastro? Essa ação não pode ser desfeita.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if resposta != QMessageBox.StandardButton.Yes:
            return
        deu_certo, _ = self._executar("Não foi possível excluir", lambda: bancos_mod.excluir_banco(nome))
        if deu_certo:
            self._depois_de_mudar("Banco excluído", f"'{nome}' foi apagado do cadastro.")
