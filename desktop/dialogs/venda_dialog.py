"""A venda em si: cliente, equipamentos e observacoes - "+ Nova venda" (venda=None) e "Editar a venda" (do card aberto).
Os equipamentos sao escolhidos da lista do cadastro (Cadastros > Equipamentos), um por linha - nunca digitados.

A venda nasce sem proposta (decidido com o usuario em 02/10/2026): os pedidos aos bancos entram depois, um a um,
pelo "+ Adicionar proposta" do card. Quem grava e o core (core/vendas.py); a janela so junta os campos e mostra o
motivo quando a regra recusa.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import clientes as clientes_mod
from core import data_store as bd
from core import equipamentos as equipamentos_mod
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import vendas as vendas_mod

SEPARADOR_DE_EQUIPAMENTOS = " + "  # o mesmo de core/vendas.py (coluna EQUIPAMENTOS da venda)


class VendaDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, *, venda: vendas_mod.ResumoDaVenda | None = None,
                 cpf: str | None = None):
        """`cpf`: nova venda ja com o cliente escolhido (a Ficha do cliente)."""
        super().__init__(parent)
        self._venda = venda
        self.id_venda: str | None = None  # depois de gravar
        self.setWindowTitle("Nova venda" if venda is None else "Editar a venda")
        self.setMinimumWidth(480)
        raiz = QVBoxLayout(self)
        raiz.setSpacing(12)
        formulario = QFormLayout()
        formulario.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        raiz.addLayout(formulario)

        self._clientes_por_rotulo: dict[str, str] = {}
        self._cliente: QComboBox | None = None
        if venda is not None:
            formulario.addRow("Cliente", QLabel(f"<b>{venda.cliente or venda.cpf}</b>"))
        else:
            self._cliente = QComboBox()
            self._cliente.setEditable(True)
            for _, c in clientes_mod.listar_clientes().iterrows():
                self._clientes_por_rotulo[f"{c['CLIENTE']} — {c['CPF/CNPJ']}"] = c["CPF/CNPJ"]
            self._cliente.addItems(sorted(self._clientes_por_rotulo))
            self._cliente.setCurrentText(next((r for r, c in self._clientes_por_rotulo.items() if c == cpf), ""))
            completador = QCompleter(list(self._clientes_por_rotulo), self)
            completador.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completador.setFilterMode(Qt.MatchFlag.MatchContains)
            self._cliente.setCompleter(completador)
            self._cliente.lineEdit().setPlaceholderText("Digite o nome ou o CPF")
            formulario.addRow("Cliente *", self._cliente)

        self._linhas_equipamento: list[QComboBox] = []
        self._caixa_equipamentos = QVBoxLayout()
        self._caixa_equipamentos.setSpacing(4)
        self._nomes_equipamento = equipamentos_mod.nomes_ativos()  # a lista fechada: equipamento novo so pelo Cadastros
        mais = QPushButton("+ Outro equipamento")
        mais.setProperty("role", "botao_link")
        mais.setCursor(Qt.CursorShape.PointingHandCursor)
        mais.clicked.connect(lambda: self._adicionar_equipamento(""))
        self._caixa_equipamentos.addWidget(mais)
        formulario.addRow("Equipamento(s) *", self._caixa_equipamentos)
        if not self._nomes_equipamento:
            vazio = QLabel("Nenhum equipamento cadastrado: cadastre em Cadastros > Equipamentos.")
            vazio.setProperty("role", "aviso")
            vazio.setWordWrap(True)
            formulario.addRow("", vazio)
        atuais = [e for e in (venda.equipamentos if venda else "").split(SEPARADOR_DE_EQUIPAMENTOS) if e.strip()]
        for nome in atuais or [""]:
            self._adicionar_equipamento(nome)

        self._observacoes = QPlainTextEdit()
        self._observacoes.setFixedHeight(70)
        self._observacoes.setPlainText(venda.observacoes if venda else "")
        formulario.addRow("Observações", self._observacoes)

        if venda is None:
            dica = QLabel("Os bancos entram depois, no card da venda (\"+ Adicionar proposta\").")
            dica.setProperty("role", "secundario")
            dica.setWordWrap(True)
            raiz.addWidget(dica)

        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.botao_gravar = botoes.button(QDialogButtonBox.StandardButton.Ok)
        self.botao_gravar.setText("Criar venda" if venda is None else "Salvar")
        botoes.accepted.connect(self._gravar)
        botoes.rejected.connect(self.reject)
        raiz.addWidget(botoes)
        (self._cliente or self._linhas_equipamento[0]).setFocus()

    # -- equipamentos -----------------------------------------------------------------------------

    def _adicionar_equipamento(self, nome: str) -> None:
        linha = QHBoxLayout()
        combo = QComboBox()
        combo.addItems(self._nomes_equipamento)
        combo.setPlaceholderText("Escolha o equipamento")
        indice = combo.findText(nome, Qt.MatchFlag.MatchFixedString | Qt.MatchFlag.MatchCaseSensitive) if nome else -1
        if nome and indice < 0:  # um nome de antes do cadastro (ou desativado) fica, so nesta venda
            combo.insertItem(0, nome)
            indice = 0
        combo.setCurrentIndex(indice)
        linha.addWidget(combo, stretch=1)
        if self._linhas_equipamento:  # o primeiro nunca sai: a venda tem pelo menos um equipamento
            tirar = QPushButton("✕")
            tirar.setProperty("role", "botao_icone")
            tirar.setToolTip("Tirar este equipamento")
            tirar.setFixedSize(28, 28)
            tirar.clicked.connect(lambda: self._tirar_equipamento(linha, combo))
            linha.addWidget(tirar)
        # antes do "+ Outro equipamento", que fica sempre por ultimo
        self._caixa_equipamentos.insertLayout(self._caixa_equipamentos.count() - 1, linha)
        self._linhas_equipamento.append(combo)
        if len(self._linhas_equipamento) > 1 and not nome:
            combo.setFocus()

    def _tirar_equipamento(self, linha: QHBoxLayout, combo: QComboBox) -> None:
        self._linhas_equipamento.remove(combo)
        while linha.count():
            widget = linha.takeAt(0).widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self._caixa_equipamentos.removeItem(linha)
        linha.deleteLater()

    def equipamentos(self) -> list[str]:
        return [c.currentText().strip() for c in self._linhas_equipamento if c.currentText().strip()]

    # -- gravar -----------------------------------------------------------------------------------

    def _gravar(self) -> None:
        cpf = None
        if self._cliente is not None:
            cpf = self._clientes_por_rotulo.get(self._cliente.currentText().strip())
            if cpf is None:
                QMessageBox.warning(self, "Cliente não encontrado",
                                    "Escolha um cliente da lista (comece a digitar o nome ou o CPF).")
                return
        if not self.equipamentos():
            QMessageBox.warning(self, "Equipamento em branco", "Informe pelo menos um equipamento da venda.")
            return
        observacoes = self._observacoes.toPlainText().strip()
        try:
            if self._venda is None:
                self.id_venda, _ = vendas_mod.criar_venda(cpf, self.equipamentos(), observacoes=observacoes)
            else:
                vendas_mod.editar_venda(self._venda.id, self.equipamentos(), observacoes)
                self.id_venda = self._venda.id
        except (vendas_mod.ErroVenda, propostas_mod.ErroProposta) as exc:
            QMessageBox.warning(self, "Não foi possível gravar", str(exc))
            return
        except sessao_mod.PermissaoNegada as exc:
            QMessageBox.warning(self, "Ação não permitida", str(exc))
            return
        except bd.ErroArquivoBloqueado as exc:
            QMessageBox.critical(self, "Arquivo bloqueado", str(exc))
            return
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro inesperado ao gravar", f"{type(exc).__name__}: {exc}")
            return
        self.accept()
