"""Nova venda ou mais um banco numa venda: a janela dos dois botoes da tela Vendas.

- Nova venda (venda=None): o cliente, um ou mais equipamentos e o primeiro pedido (banco, valor, meses, data).
- Mandar a outro banco (venda=ResumoDaVenda): cliente e equipamentos ja sao os da venda; so o pedido novo. Com
  mais de um equipamento, o pedido cobre a venda toda (o padrao) ou so os marcados - pedidos separados na mesma
  venda (decidido com o usuario em 02/10/2026).

Quem grava e o core (core/vendas.py); a janela so junta os campos e mostra o motivo quando a regra recusa.
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core import bancos as bancos_mod
from core import clientes as clientes_mod
from core import data_store as bd
from core import equipamentos as equipamentos_mod
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import vendas as vendas_mod
from desktop.widgets.campo_data import CampoData

SEPARADOR_DE_EQUIPAMENTOS = " + "  # o mesmo de core/vendas.py (coluna EQUIPAMENTOS da venda)


class PedidoVendaDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, *, venda: vendas_mod.ResumoDaVenda | None = None):
        super().__init__(parent)
        self._venda = venda
        self.id_venda: str | None = None  # depois de gravar
        self.id_proposta: str | None = None
        self.setWindowTitle("Nova venda" if venda is None else "Mandar a outro banco")
        self.setMinimumWidth(520)
        raiz = QVBoxLayout(self)
        raiz.setSpacing(12)
        formulario = QFormLayout()
        formulario.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        raiz.addLayout(formulario)

        self._clientes_por_rotulo: dict[str, str] = {}
        self._cliente: QComboBox | None = None
        self._linhas_equipamento: list[QComboBox] = []
        self._cobre: list[QCheckBox] = []
        if venda is None:
            self._cliente = QComboBox()
            self._cliente.setEditable(True)
            for _, c in clientes_mod.listar_clientes().iterrows():
                self._clientes_por_rotulo[f"{c['CLIENTE']} — {c['CPF/CNPJ']}"] = c["CPF/CNPJ"]
            self._cliente.addItems(sorted(self._clientes_por_rotulo))
            self._cliente.setCurrentText("")
            completador = QCompleter(list(self._clientes_por_rotulo), self)
            completador.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completador.setFilterMode(Qt.MatchFlag.MatchContains)
            self._cliente.setCompleter(completador)
            self._cliente.lineEdit().setPlaceholderText("Digite o nome ou o CPF")
            formulario.addRow("Cliente *", self._cliente)

            self._caixa_equipamentos = QVBoxLayout()
            self._caixa_equipamentos.setSpacing(4)
            self._nomes_equipamento = equipamentos_mod.listar_nomes_equipamento()
            mais = QPushButton("+ Outro equipamento")
            mais.setProperty("role", "botao_link")
            mais.setCursor(Qt.CursorShape.PointingHandCursor)
            mais.clicked.connect(self._adicionar_equipamento)
            self._caixa_equipamentos.addWidget(mais)
            self._botao_mais_equipamento = mais
            formulario.addRow("Equipamento(s) *", self._caixa_equipamentos)
            self._adicionar_equipamento()
        else:
            cabecalho = QLabel(f"<b>{venda.cliente or venda.cpf}</b><br>{venda.equipamentos}")
            cabecalho.setWordWrap(True)
            formulario.addRow("Venda", cabecalho)
            equipamentos = [e for e in venda.equipamentos.split(SEPARADOR_DE_EQUIPAMENTOS) if e.strip()]
            if len(equipamentos) > 1:
                caixa = QVBoxLayout()
                caixa.setSpacing(2)
                for nome in equipamentos:
                    marcado = QCheckBox(nome)
                    marcado.setChecked(True)
                    caixa.addWidget(marcado)
                    self._cobre.append(marcado)
                dica = QLabel("Desmarque para mandar um pedido só de parte da venda.")
                dica.setProperty("role", "secundario")
                caixa.addWidget(dica)
                formulario.addRow("Este pedido cobre", caixa)

        self._banco = QComboBox()
        self._banco.addItems([*bancos_mod.nomes_ativos(), bancos_mod.BANCO_TODOS])
        self._banco.setCurrentIndex(-1)
        self._banco.setPlaceholderText("Escolha o banco")
        formulario.addRow("Banco/financeira *", self._banco)

        self._valor = QDoubleSpinBox()
        self._valor.setRange(0, 10_000_000)
        self._valor.setDecimals(2)
        self._valor.setPrefix("R$ ")
        self._valor.setGroupSeparatorShown(True)
        self._meses = QSpinBox()
        self._meses.setRange(0, 120)
        linha_valor = QHBoxLayout()
        linha_valor.addWidget(self._valor, stretch=2)
        rotulo_meses = QLabel("Meses")
        linha_valor.addWidget(rotulo_meses)
        linha_valor.addWidget(self._meses, stretch=1)
        formulario.addRow("Valor solicitado *", linha_valor)

        # as condicoes do banco (opcionais): em quantos dias vem a 1a parcela, e o valor dela
        self._carencia = QComboBox()
        self._carencia.setEditable(True)
        self._carencia.addItems([str(dias) for dias in propostas_mod.CARENCIAS_COMUNS])
        self._carencia.lineEdit().setValidator(QIntValidator(0, propostas_mod.CARENCIA_MAXIMA_DIAS, self))
        self._carencia.setCurrentText("")
        self._carencia.lineEdit().setPlaceholderText("dias")
        self._parcela = QDoubleSpinBox()
        self._parcela.setRange(0, 10_000_000)
        self._parcela.setDecimals(2)
        self._parcela.setPrefix("R$ ")
        self._parcela.setGroupSeparatorShown(True)
        linha_condicoes = QHBoxLayout()
        linha_condicoes.addWidget(self._carencia, stretch=1)
        linha_condicoes.addWidget(QLabel("Parcela"))
        linha_condicoes.addWidget(self._parcela, stretch=2)
        formulario.addRow("Carência (dias)", linha_condicoes)

        self._data = CampoData(permitir_futuro=True)
        self._data.definir_data(QDate.currentDate())
        formulario.addRow("Data do envio", self._data)

        self._observacoes = QPlainTextEdit()
        self._observacoes.setFixedHeight(60)
        formulario.addRow("Observações", self._observacoes)

        if venda is not None and venda.propostas:
            # o caso comum: o mesmo pedido a outro banco - valor e meses do ultimo, o banco e o que muda
            ultima = venda.propostas[-1]
            self._valor.setValue(float(ultima.valor or 0))
            self._meses.setValue(int(ultima.meses or 0))
            # a carencia costuma ser a mesma pedida a todos; a parcela, nao (cada banco calcula a sua)
            self._carencia.setCurrentText(str(ultima.carencia) if ultima.carencia is not None else "")

        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.botao_gravar = botoes.button(QDialogButtonBox.StandardButton.Ok)
        self.botao_gravar.setText("Criar venda" if venda is None else "Mandar ao banco")
        botoes.accepted.connect(self._gravar)
        botoes.rejected.connect(self.reject)
        raiz.addWidget(botoes)
        (self._cliente or self._banco).setFocus()

    # -- equipamentos (nova venda) ----------------------------------------------------------------

    def _adicionar_equipamento(self) -> None:
        linha = QHBoxLayout()
        combo = QComboBox()
        combo.setEditable(True)
        combo.addItems(self._nomes_equipamento)
        combo.setCurrentText("")
        combo.lineEdit().setPlaceholderText("Nome do equipamento")
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
        if len(self._linhas_equipamento) > 1:
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

    def _aviso(self, titulo: str, texto: str) -> None:
        QMessageBox.warning(self, titulo, texto)

    def _gravar(self) -> None:
        cpf = None
        if self._cliente is not None:
            cpf = self._clientes_por_rotulo.get(self._cliente.currentText().strip())
            if cpf is None:
                self._aviso("Cliente não encontrado", "Escolha um cliente da lista (comece a digitar o nome ou o CPF).")
                return
            if not self.equipamentos():
                self._aviso("Equipamento em branco", "Informe pelo menos um equipamento da venda.")
                return
        banco = self._banco.currentText().strip()
        if not banco:
            self._aviso("Banco em branco", "Escolha o banco/financeira para onde o pedido vai.")
            return
        data, erro = self._data.avaliar()
        if erro or data is None:
            self._aviso("Data inválida", erro or "Informe a data do envio (dd/mm/aaaa).")
            return
        cobre = ""
        if self._cobre:
            marcados = [c.text() for c in self._cobre if c.isChecked()]
            if not marcados:
                self._aviso("Nenhum equipamento marcado", "Marque pelo menos um equipamento que este pedido cobre.")
                return
            if len(marcados) < len(self._cobre):
                cobre = SEPARADOR_DE_EQUIPAMENTOS.join(marcados)
        proposta = {
            "DATA": pd.Timestamp(data.year(), data.month(), data.day()),
            "VALOR (R$)": self._valor.value() or "",
            "MESES": self._meses.value() or "",
            "CARÊNCIA (DIAS)": self._carencia.currentText().strip(),
            "PARCELA (R$)": self._parcela.value() or "",
            "BANCO": banco,
            "OBSERVAÇÕES": self._observacoes.toPlainText().strip(),
        }
        if cobre:
            proposta["EQUIPAMENTO"] = cobre
        try:
            if self._venda is None:
                self.id_venda, self.id_proposta = vendas_mod.criar_venda(cpf, self.equipamentos(), proposta)
            else:
                self.id_venda = self._venda.id
                self.id_proposta = vendas_mod.mandar_a_outro_banco(self._venda.id, proposta)
        except (vendas_mod.ErroVenda, propostas_mod.ErroProposta) as exc:
            self._aviso("Não foi possível gravar", str(exc))
            return
        except sessao_mod.PermissaoNegada as exc:
            self._aviso("Ação não permitida", str(exc))
            return
        except bd.ErroArquivoBloqueado as exc:
            QMessageBox.critical(self, "Arquivo bloqueado", str(exc))
            return
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro inesperado ao gravar", f"{type(exc).__name__}: {exc}")
            return
        self.accept()
