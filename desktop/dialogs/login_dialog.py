"""Dialogo de login - primeira tela do app, antes da janela principal.

Dois casos:
- ADMIN ainda nao tem senha definida (primeira execucao nesta maquina) ->
  pede pra criar uma senha agora, em vez de mostrar o formulario de login.
- Caso normal -> usuario ("Administrador" ou o nome de um vendedor) + senha.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from core import auth
from core import sessao as sessao_mod
from core import vendedores as vendedores_mod

USUARIO_ADMIN = "Administrador"


class LoginDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Entrar — Gestão de Financiamentos")
        self.setMinimumWidth(360)
        self.sessao_criada: sessao_mod.Sessao | None = None

        # se o ADMIN nunca configurou uma senha nesta maquina, o "login" vira
        # um cadastro de senha - nao da pra pedir login de algo que nao existe
        self._primeiro_acesso = not auth.admin_configurado()

        layout = QVBoxLayout(self)

        if self._primeiro_acesso:
            aviso = QLabel(
                "Primeira execução — defina a senha do Administrador.\n"
                "Você pode trocá-la depois (fale com quem for dar suporte técnico)."
            )
            aviso.setWordWrap(True)
            layout.addWidget(aviso)

            form = QFormLayout()
            self._nova_senha = QLineEdit()
            self._nova_senha.setEchoMode(QLineEdit.EchoMode.Password)
            form.addRow("Nova senha do Administrador", self._nova_senha)
            self._confirmar_senha = QLineEdit()
            self._confirmar_senha.setEchoMode(QLineEdit.EchoMode.Password)
            form.addRow("Confirmar senha", self._confirmar_senha)
            layout.addLayout(form)
        else:
            form = QFormLayout()
            self._usuario = QLineEdit()
            self._usuario.setPlaceholderText("Administrador, ou o seu nome (vendedor)")
            form.addRow("Usuário", self._usuario)
            self._senha = QLineEdit()
            self._senha.setEchoMode(QLineEdit.EchoMode.Password)
            form.addRow("Senha", self._senha)
            layout.addLayout(form)

        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botoes.button(QDialogButtonBox.StandardButton.Ok).setText(
            "Definir senha" if self._primeiro_acesso else "Entrar"
        )
        botoes.accepted.connect(self._confirmar)
        botoes.rejected.connect(self.reject)
        layout.addWidget(botoes)

    def _confirmar(self) -> None:
        if self._primeiro_acesso:
            self._definir_senha_admin()
        else:
            self._fazer_login()

    def _definir_senha_admin(self) -> None:
        senha = self._nova_senha.text()
        confirmar = self._confirmar_senha.text()
        if len(senha) < 4:
            QMessageBox.warning(self, "Senha muito curta", "Use pelo menos 4 caracteres.")
            return
        if senha != confirmar:
            QMessageBox.warning(self, "Senhas diferentes", "As duas senhas digitadas não são iguais.")
            return

        auth.definir_senha_admin(senha)
        self.sessao_criada = sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario=USUARIO_ADMIN)
        self.accept()

    def _fazer_login(self) -> None:
        usuario = self._usuario.text().strip()
        senha = self._senha.text()
        if not usuario or not senha:
            QMessageBox.warning(self, "Campos obrigatórios", "Preencha usuário e senha.")
            return

        if usuario.upper() == USUARIO_ADMIN.upper():
            if auth.verificar_senha_admin(senha):
                self.sessao_criada = sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario=USUARIO_ADMIN)
                self.accept()
            else:
                QMessageBox.warning(self, "Não foi possível entrar", "Usuário ou senha incorretos.")
            return

        try:
            nome_oficial = vendedores_mod.verificar_login(usuario, senha)
        except Exception as exc:  # falha de rede/API ao consultar o Google Sheets
            QMessageBox.critical(
                self,
                "Erro ao conectar",
                "Não foi possível verificar o login agora - confira sua conexão com a internet "
                f"e tente de novo.\n\nDetalhe técnico: {exc}",
            )
            return

        if nome_oficial is None:
            QMessageBox.warning(self, "Não foi possível entrar", "Usuário ou senha incorretos.")
            return

        self.sessao_criada = sessao_mod.Sessao(papel=sessao_mod.PAPEL_VENDEDOR, nome_usuario=nome_oficial)
        self.accept()
