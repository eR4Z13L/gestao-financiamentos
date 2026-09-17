"""Dialogo de lancamento/edicao de proposta.

Mesmo formulario serve pra tres casos:
- cpf fixo + proposta=None -> nova proposta pra um cliente ja conhecido
  (aberto a partir da Ficha de Cliente)
- cpf fixo + proposta+indice -> editar uma proposta existente
- cpf=None -> nova proposta "avulsa" (aberto a partir da tela Todas as
  Propostas, que nao tem um cliente pre-selecionado): mostra um campo de
  cliente pesquisavel em vez do titulo com o nome fixo.
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QMessageBox,
    QPlainTextEdit,
    QSpinBox,
    QWidget,
)

from config import BANCOS_CONHECIDOS
from core import clientes as clientes_mod
from core import data_store as bd
from core import equipamentos as equipamentos_mod
from core import propostas as propostas_mod


class PropostaDialog(QDialog):
    def __init__(
        self,
        cpf: str | None,
        nome_cliente: str | None = None,
        proposta: dict | None = None,
        indice: int | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._cpf = cpf
        self._indice = indice
        self._clientes_por_rotulo: dict[str, str] = {}

        self.setWindowTitle(f"{'Editar' if proposta else 'Nova'} proposta" + (f" — {nome_cliente}" if cpf else ""))
        self.setMinimumWidth(420)

        layout = QFormLayout(self)

        if cpf is None:
            self._cliente_combo = QComboBox()
            self._cliente_combo.setEditable(True)
            for _, c in clientes_mod.listar_clientes().iterrows():
                rotulo = f"{c['CLIENTE']} — {c['CPF/CNPJ']}"
                self._clientes_por_rotulo[rotulo] = c["CPF/CNPJ"]
            self._cliente_combo.addItems(sorted(self._clientes_por_rotulo.keys()))
            self._cliente_combo.setCurrentText("")
            completador = QCompleter(list(self._clientes_por_rotulo.keys()), self)
            completador.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            completador.setFilterMode(Qt.MatchFlag.MatchContains)
            self._cliente_combo.setCompleter(completador)
            layout.addRow("Cliente *", self._cliente_combo)
        else:
            self._cliente_combo = None

        self._data = QDateEdit()
        self._data.setCalendarPopup(True)
        self._data.setDisplayFormat("dd/MM/yyyy")
        data_atual = proposta.get("DATA") if proposta else None
        if isinstance(data_atual, pd.Timestamp) and not pd.isna(data_atual):
            self._data.setDate(QDate(data_atual.year, data_atual.month, data_atual.day))
        else:
            self._data.setDate(QDate.currentDate())
        layout.addRow("Data", self._data)

        self._valor = QDoubleSpinBox()
        self._valor.setRange(0, 10_000_000)
        self._valor.setDecimals(2)
        self._valor.setPrefix("R$ ")
        self._valor.setGroupSeparatorShown(True)
        if proposta and not pd.isna(proposta.get("VALOR (R$)")):
            self._valor.setValue(float(proposta["VALOR (R$)"]))
        layout.addRow("Valor solicitado *", self._valor)

        self._meses = QSpinBox()
        self._meses.setRange(0, 120)
        if proposta and not pd.isna(proposta.get("MESES")):
            self._meses.setValue(int(proposta["MESES"]))
        layout.addRow("Meses", self._meses)

        self._equipamento = QComboBox()
        self._equipamento.setEditable(True)
        self._equipamento.addItems(equipamentos_mod.listar_nomes_equipamento())
        self._equipamento.setCurrentText(proposta.get("EQUIPAMENTO", "") if proposta else "")
        layout.addRow("Equipamento *", self._equipamento)

        self._banco = QComboBox()
        self._banco.setEditable(True)
        self._banco.addItems(BANCOS_CONHECIDOS)
        self._banco.setCurrentText(proposta.get("BANCO", "") if proposta else "")
        layout.addRow("Banco/financeira *", self._banco)

        self._status = QComboBox()
        opcoes_status = list(propostas_mod.STATUS_OPCOES)
        status_atual = (proposta.get("STATUS") if proposta else "") or ""
        if status_atual and status_atual not in opcoes_status:
            # dados antigos tem status em CAIXA ALTA ("APROVADO", "NEGADO")
            # que nao batem com a lista oficial ("Aprovado", "Negado") - sem
            # isso, editar uma proposta assim mudaria o status dela pra "Em
            # Análise" (o primeiro item) sem o usuario perceber.
            opcoes_status.insert(0, status_atual)
        self._status.addItems(opcoes_status)
        if status_atual:
            self._status.setCurrentText(status_atual)
        layout.addRow("Status", self._status)

        self._observacoes = QPlainTextEdit(proposta.get("OBSERVAÇÕES", "") if proposta else "")
        self._observacoes.setFixedHeight(70)
        layout.addRow("Observações", self._observacoes)

        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botoes.accepted.connect(self._salvar)
        botoes.rejected.connect(self.reject)
        layout.addRow(botoes)

    def _resolver_cpf(self) -> str | None:
        if self._cpf is not None:
            return self._cpf
        rotulo = self._cliente_combo.currentText().strip()
        cpf = self._clientes_por_rotulo.get(rotulo)
        if cpf is None:
            QMessageBox.warning(
                self, "Cliente não encontrado", "Selecione um cliente da lista (comece a digitar o nome ou CPF)."
            )
        return cpf

    def _confirmar(self, titulo: str, mensagem: str) -> bool:
        resposta = QMessageBox.question(
            self,
            titulo,
            mensagem,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return resposta == QMessageBox.StandardButton.Yes

    def _duplicata_provavel(self, cpf: str, data: pd.Timestamp, valor) -> bool:
        """Mesmo cliente + mesma data + mesmo valor de outra proposta ja
        lancada (ignorando a que esta sendo editada agora) - um sinal comum
        de duplicidade por engano (ex: clique duplo em "Salvar")."""
        try:
            historico = propostas_mod.historico_por_cpf(cpf)
        except Exception:
            return False  # checagem extra nao pode impedir o salvamento normal
        if self._indice is not None:
            historico = historico[historico.index != self._indice]
        if historico.empty or valor in (None, ""):
            return False
        mesma_data = historico["DATA"] == data
        mesmo_valor = (historico["VALOR (R$)"] - float(valor)).abs() < 0.01
        return bool((mesma_data & mesmo_valor).any())

    def _salvar(self) -> None:
        cpf = self._resolver_cpf()
        if cpf is None:
            return

        banco = self._banco.currentText().strip()
        status = self._status.currentText().strip()
        faltando = [rotulo for rotulo, valor in (("Banco/financeira", banco), ("Status", status)) if not valor]
        if faltando:
            plural = len(faltando) > 1
            if not self._confirmar(
                "Campo recomendado em branco",
                f"{' e '.join(faltando)} não {'foram preenchidos' if plural else 'foi preenchido'}. "
                "Deseja salvar assim mesmo?",
            ):
                return

        qdate = self._data.date()
        data_proposta = pd.Timestamp(qdate.year(), qdate.month(), qdate.day())
        valor_informado = self._valor.value() or ""  # 0 = campo nao preenchido (mesma convencao de MESES)

        if self._duplicata_provavel(cpf, data_proposta, valor_informado):
            if not self._confirmar(
                "Possível duplicata",
                "Já existe uma proposta deste cliente com a mesma data e o mesmo valor. "
                "Deseja salvar mesmo assim?",
            ):
                return

        campos = {
            "DATA": data_proposta,
            "CPF": cpf,
            "VALOR (R$)": valor_informado,
            "MESES": self._meses.value() or "",
            "EQUIPAMENTO": self._equipamento.currentText().strip(),
            "BANCO": banco,
            "STATUS": status,
            "OBSERVAÇÕES": self._observacoes.toPlainText().strip(),
        }
        try:
            if self._indice is None:
                propostas_mod.adicionar_proposta(campos)
            else:
                propostas_mod.atualizar_proposta(self._indice, campos)
        except propostas_mod.ErroProposta as exc:
            QMessageBox.warning(self, "Não foi possível salvar", str(exc))
            return
        except bd.ErroArquivoBloqueado as exc:
            QMessageBox.critical(self, "Arquivo bloqueado", str(exc))
            return
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro inesperado ao salvar", str(exc))
            return

        self.accept()
