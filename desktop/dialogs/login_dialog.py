"""Dialogo de login - primeira tela do app, antes da janela principal. As regras ficam em core/acesso.py.

Tres casos (acesso.modo_de_entrada()):
- PIN: o PIN deste computador (sem internet). "Esqueci o PIN" volta a entrar com Google.
- Google: primeira vez neste computador (ou PIN apagado) -> entrar com a conta Google e criar o PIN.
- Senha antiga: computador que ainda tem a senha do Administrador e nao tem PIN -> entra com ela uma ultima
  vez e ja passa para entrar com Google + criar o PIN (que aposenta a senha). Se isso nao der certo agora
  (sem internet, por exemplo), entra assim mesmo: ninguem fica trancado do lado de fora.

Por enquanto SO o Administrador entra no app - o modo vendedor (core.vendedores.verificar_login) fica
pausado ate a fase de rollout pros vendedores.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core import acesso, auth, conta_google
from core import sessao as sessao_mod
from desktop.entrar_com_google import conectar_e_conferir
from desktop.widgets.campo_de_pin import campo_de_pin

USUARIO_ADMIN = "Administrador"


class CriarPinDialog(QDialog):
    """Cria o PIN deste computador para a conta Google recem-conectada."""

    def __init__(self, email: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Criar PIN")
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        aviso = QLabel(
            f"Conectado como <b>{email}</b>.<br><br>"
            f"Crie um PIN de {acesso.TAMANHO_DO_PIN} números para entrar neste computador, mesmo sem internet. "
            "Ele vale só aqui: em outro computador, você cria o daquele."
        )
        aviso.setWordWrap(True)
        layout.addWidget(aviso)
        form = QFormLayout()
        self._pin = campo_de_pin()
        form.addRow("PIN", self._pin)
        self._confirmar = campo_de_pin()
        form.addRow("Confirmar PIN", self._confirmar)
        layout.addLayout(form)
        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botoes.button(QDialogButtonBox.StandardButton.Ok).setText("Criar PIN")
        botoes.accepted.connect(self._criar)
        botoes.rejected.connect(self.reject)
        layout.addWidget(botoes)

    def _criar(self) -> None:
        if self._pin.text() != self._confirmar.text():
            QMessageBox.warning(self, "PINs diferentes", "Os dois PINs digitados não são iguais.")
            return
        try:
            acesso.criar_pin(self._pin.text())
        except acesso.ErroPin as exc:
            QMessageBox.warning(self, "PIN inválido", str(exc))
            return
        except Exception as exc:  # nunca falhar em silencio (ex.: sem permissao pra gravar a pasta)
            QMessageBox.critical(self, "Não foi possível gravar o PIN", f"{type(exc).__name__}: {exc}")
            return
        self.accept()


class LoginDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Entrar — Gestão de Financiamentos")
        self.setMinimumWidth(380)
        self.sessao_criada: sessao_mod.Sessao | None = None
        self._layout = QVBoxLayout(self)
        self._conteudo: QWidget | None = None
        self._montar(acesso.modo_de_entrada())

    def _montar(self, modo: str) -> None:
        """(Re)monta o dialogo para o modo de entrada - muda no meio quando o PIN e apagado por erros."""
        self.modo = modo
        if self._conteudo is not None:
            self._conteudo.deleteLater()
        self._conteudo = QWidget()
        layout = QVBoxLayout(self._conteudo)
        layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(self._conteudo)

        if modo == acesso.ENTRADA_PIN:
            conta = conta_google.conta_conectada()
            rotulo = QLabel(f"Conta: <b>{conta.email if conta else ''}</b>")
            layout.addWidget(rotulo)
            form = QFormLayout()
            self._pin = campo_de_pin()
            form.addRow("PIN deste computador", self._pin)
            layout.addLayout(form)
            esqueci = QPushButton("Esqueci o PIN (entrar com Google)")
            esqueci.setFlat(True)
            esqueci.clicked.connect(self._entrar_com_google)
            layout.addWidget(esqueci)
            texto_ok = "Entrar"
        elif modo == acesso.ENTRADA_SENHA_ANTIGA:
            aviso = QLabel(
                "Entre com a senha do Administrador uma última vez. Em seguida, o aplicativo pede para entrar "
                "com sua conta Google e criar um PIN, que substitui a senha."
            )
            aviso.setWordWrap(True)
            layout.addWidget(aviso)
            form = QFormLayout()
            self._senha = QLineEdit()
            self._senha.setEchoMode(QLineEdit.EchoMode.Password)
            form.addRow("Senha do Administrador", self._senha)
            layout.addLayout(form)
            texto_ok = "Entrar"
        else:
            aviso = QLabel(
                "Entre com sua conta Google: o navegador abre para você escolher a conta e autorizar o "
                f"aplicativo. Depois, você cria um PIN de {acesso.TAMANHO_DO_PIN} números para as próximas "
                "vezes neste computador (funciona sem internet).<br><br>"
                "A conta precisa ter acesso de Editor à planilha da nuvem."
            )
            aviso.setWordWrap(True)
            layout.addWidget(aviso)
            texto_ok = "Entrar com Google"

        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botoes.button(QDialogButtonBox.StandardButton.Ok).setText(texto_ok)
        botoes.accepted.connect(self._confirmar)
        botoes.rejected.connect(self.reject)
        layout.addWidget(botoes)

    def _confirmar(self) -> None:
        if self.modo == acesso.ENTRADA_PIN:
            self._entrar_com_pin()
        elif self.modo == acesso.ENTRADA_SENHA_ANTIGA:
            self._entrar_com_senha_antiga()
        else:
            self._entrar_com_google()

    def _aceitar(self) -> None:
        self.sessao_criada = sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario=USUARIO_ADMIN)
        self.accept()

    def _entrar_com_pin(self) -> None:
        try:
            resultado = acesso.conferir_pin(self._pin.text())
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro ao conferir o PIN", f"{type(exc).__name__}: {exc}")
            return
        if resultado.certo:
            self._aceitar()
            return
        if resultado.tentativas_restantes > 0:
            self._pin.clear()
            QMessageBox.warning(
                self, "PIN incorreto",
                f"PIN incorreto. Restam {resultado.tentativas_restantes} tentativa(s); depois disso, será preciso "
                "entrar com Google de novo.",
            )
            return
        QMessageBox.warning(
            self, "PIN apagado",
            "PIN errado vezes demais: o PIN deste computador foi apagado. Entre com Google para criar outro.",
        )
        self._montar(acesso.modo_de_entrada())

    def _entrar_com_senha_antiga(self) -> None:
        if not auth.verificar_senha_admin(self._senha.text()):
            QMessageBox.warning(self, "Não foi possível entrar", "Senha incorreta.")
            return
        if self._conectar_e_criar_pin() is not True:
            QMessageBox.information(
                self, "Entrou com a senha",
                "Você entrou com a senha do Administrador. A conta Google e o PIN ficam para a próxima vez: "
                "até lá, a senha continua valendo.",
            )
        self._aceitar()

    def _entrar_com_google(self) -> None:
        criou_pin = self._conectar_e_criar_pin()
        if criou_pin is not None:
            # com ou sem PIN, o Google acabou de confirmar quem e: entra (sem PIN, na proxima e Google de novo)
            self._aceitar()
            return
        if acesso.modo_de_entrada() != self.modo:  # a tentativa desfez a conexao anterior (conta sem acesso)
            self._montar(acesso.modo_de_entrada())

    def _conectar_e_criar_pin(self) -> bool | None:
        """None: nao conectou (ja avisado). True/False: conectou e criou / nao criou o PIN."""
        conta = conectar_e_conferir(self)
        if conta is None:
            return None
        return CriarPinDialog(conta.email, self).exec() == QDialog.DialogCode.Accepted
