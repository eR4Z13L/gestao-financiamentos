"""Dialogo de cadastro/edicao de cliente.

O mesmo formulario serve pros dois casos: passe cliente=None pra cadastrar
um novo, ou um dict (do jeito que core.clientes.buscar_por_cpf devolve) pra
editar um existente.
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QWidget,
)

from core import clientes as clientes_mod
from core import data_store as bd
from core.validators import email_valido
from desktop.widgets.formatters import conectar_mascara, formatar_cpf_cnpj_parcial, formatar_telefone_parcial

_DATA_MINIMA = QDate(1900, 1, 1)


class ClienteDialog(QDialog):
    def __init__(self, cliente: dict | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self._cliente_original = cliente
        self.cpf_salvo: str | None = None

        self.setWindowTitle("Editar cliente" if cliente else "Cadastrar novo cliente")
        self.setMinimumWidth(420)

        layout = QFormLayout(self)

        self._cpf = QLineEdit(cliente.get("CPF/CNPJ", "") if cliente else "")
        self._cpf.setPlaceholderText("CPF ou CNPJ - só números")
        conectar_mascara(self._cpf, formatar_cpf_cnpj_parcial)
        layout.addRow("CPF/CNPJ *", self._cpf)

        self._nome = QLineEdit(cliente.get("CLIENTE", "") if cliente else "")
        layout.addRow("Nome completo *", self._nome)

        self._tipo = QComboBox()
        self._tipo.addItems(clientes_mod.TIPO_OPCOES)
        if cliente and cliente.get("TIPO") in clientes_mod.TIPO_OPCOES:
            self._tipo.setCurrentText(cliente["TIPO"])
        layout.addRow("Tipo *", self._tipo)

        self._vendedor = QComboBox()
        self._vendedor.setEditable(True)
        self._vendedor.addItems(clientes_mod.listar_vendedores())
        self._vendedor.setCurrentText(cliente.get("VENDEDOR", "") if cliente else "")
        layout.addRow("Vendedor responsável", self._vendedor)

        self._celular = QLineEdit(cliente.get("CELULAR", "") if cliente else "")
        self._celular.setPlaceholderText("(00) 00000-0000")
        conectar_mascara(self._celular, formatar_telefone_parcial)
        layout.addRow("Celular", self._celular)

        self._email = QLineEdit(cliente.get("EMAIL", "") if cliente else "")
        self._email.textChanged.connect(self._validar_email_ao_vivo)
        layout.addRow("E-mail", self._email)

        self._rede_social = QLineEdit(cliente.get("REDE SOCIAL", "") if cliente else "")
        layout.addRow("Rede social", self._rede_social)

        self._vinculado = QLineEdit(cliente.get("VINCULADO", "") if cliente else "")
        layout.addRow("Vinculado a (se for avalista)", self._vinculado)

        self._nascimento = QDateEdit()
        self._nascimento.setCalendarPopup(True)
        self._nascimento.setDisplayFormat("dd/MM/yyyy")
        self._nascimento.setMinimumDate(_DATA_MINIMA)
        self._nascimento.setMaximumDate(QDate.currentDate())
        # quando a data == a minima, tratamos como "nao informado" - evita
        # precisar de um segundo widget (checkbox) so pra permitir vazio
        self._nascimento.setSpecialValueText("Não informado")
        nascimento_atual = cliente.get("NASCIMENTO") if cliente else None
        if isinstance(nascimento_atual, pd.Timestamp) and not pd.isna(nascimento_atual):
            self._nascimento.setDate(QDate(nascimento_atual.year, nascimento_atual.month, nascimento_atual.day))
        else:
            self._nascimento.setDate(_DATA_MINIMA)
        layout.addRow("Nascimento", self._nascimento)

        self._endereco = QPlainTextEdit(cliente.get("ENDEREÇO", "") if cliente else "")
        self._endereco.setFixedHeight(70)
        layout.addRow("Endereço", self._endereco)

        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botoes.accepted.connect(self._salvar)
        botoes.rejected.connect(self.reject)
        layout.addRow(botoes)

    def _validar_email_ao_vivo(self, texto: str) -> None:
        """So um aviso visual (borda vermelha) enquanto digita - quem
        realmente impede salvar com e-mail invalido e core.clientes."""
        valido = not texto.strip() or email_valido(texto)
        self._email.setProperty("invalido", not valido)
        self._email.style().unpolish(self._email)
        self._email.style().polish(self._email)

    def _nascimento_valor(self):
        if self._nascimento.date() == _DATA_MINIMA:
            return ""
        qdate = self._nascimento.date()
        return pd.Timestamp(qdate.year(), qdate.month(), qdate.day())

    def _salvar(self) -> None:
        campos = {
            "CPF/CNPJ": self._cpf.text().strip(),
            "CLIENTE": self._nome.text().strip(),
            "TIPO": self._tipo.currentText(),
            "VENDEDOR": self._vendedor.currentText().strip(),
            "CELULAR": self._celular.text().strip(),
            "EMAIL": self._email.text().strip(),
            "REDE SOCIAL": self._rede_social.text().strip(),
            "VINCULADO": self._vinculado.text().strip(),
            "NASCIMENTO": self._nascimento_valor(),
            "ENDEREÇO": self._endereco.toPlainText().strip(),
        }
        try:
            if self._cliente_original is None:
                clientes_mod.adicionar_cliente(campos)
            else:
                clientes_mod.atualizar_cliente(self._cliente_original["CPF/CNPJ"], campos)
        except clientes_mod.ErroCliente as exc:
            QMessageBox.warning(self, "Não foi possível salvar", str(exc))
            return
        except bd.ErroArquivoBloqueado as exc:
            QMessageBox.critical(self, "Arquivo bloqueado", str(exc))
            return
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro inesperado ao salvar", str(exc))
            return

        self.cpf_salvo = campos["CPF/CNPJ"]
        self.accept()
