"""Dialogo de login - primeira tela do app, antes da janela principal.

Dois casos:
- ADMIN ainda nao tem senha definida (primeira execucao nesta maquina) ->
  pede pra criar uma senha agora, em vez de mostrar o formulario de login.
- Caso normal -> senha do Administrador.

Por enquanto SO o Administrador loga por aqui - o modo vendedor (usuario +
senha, conferidos no Google Sheets - core.vendedores.verificar_login) fica
pausado ate a fase de rollout pros vendedores. O CADASTRO de vendedores
(Administracao > Usuarios) continua funcionando normalmente - so o login
deles que esta desligado nesta tela.
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
            self._senha = QLineEdit()
            self._senha.setEchoMode(QLineEdit.EchoMode.Password)
            form.addRow("Senha do Administrador", self._senha)
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
        if senha != confirmar:
            QMessageBox.warning(self, "Senhas diferentes", "As duas senhas digitadas não são iguais.")
            return

        try:
            auth.definir_senha_admin(senha)  # confere o tamanho minimo (o mesmo da troca de senha)
        except auth.ErroSenha as exc:
            QMessageBox.warning(self, "Senha muito curta", str(exc))
            return
        except Exception as exc:  # nunca falhar em silencio (ex.: sem permissao pra gravar a pasta)
            QMessageBox.critical(self, "Não foi possível gravar a senha", f"{type(exc).__name__}: {exc}")
            return
        self.sessao_criada = sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario=USUARIO_ADMIN)
        self.accept()

    def _fazer_login(self) -> None:
        senha = self._senha.text()
        if not senha:
            QMessageBox.warning(self, "Campo obrigatório", "Preencha a senha.")
            return

        if auth.verificar_senha_admin(senha):
            self.sessao_criada = sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario=USUARIO_ADMIN)
            self.accept()
        else:
            QMessageBox.warning(self, "Não foi possível entrar", "Senha incorreta.")
