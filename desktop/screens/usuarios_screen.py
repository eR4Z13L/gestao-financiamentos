"""Tela Administração (antes "Usuários") - só o ADMIN acessa (nem aparece no menu lateral
pra um VENDEDOR - ver desktop/main_window.py). Dois blocos:
1. Trocar a própria senha do Administrador.
2. Cadastrar vendedores e redefinir a senha de um vendedor existente - por
   decisão de produto, o vendedor nunca troca a própria senha, só o ADMIN
   pode (ver core/vendedores.py).
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from core import auth
from core import data_store as bd
from core import vendedores as vendedores_mod
from desktop import settings as settings_mod
from desktop.table_model import PandasTableModel
from desktop.widgets.shadow import aplicar_sombra_suave


class UsuariosScreen(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        titulo = QLabel("⚙️ Administração")
        titulo.setProperty("role", "titulo")
        layout.addWidget(titulo)

        layout.addWidget(self._construir_secao_minha_senha())
        layout.addWidget(self._construir_secao_vendedores(), stretch=1)

        self._carregar_vendedores()

    # -- minha senha (admin) --------------------------------------------------

    def _construir_secao_minha_senha(self) -> QWidget:
        cartao = QFrame()
        cartao.setProperty("role", "card")
        aplicar_sombra_suave(cartao, settings_mod.obter_tema())
        layout_cartao = QVBoxLayout(cartao)
        layout_cartao.setContentsMargins(16, 16, 16, 16)
        layout_cartao.setSpacing(12)

        subtitulo = QLabel("Minha senha (Administrador)")
        subtitulo.setProperty("role", "subtitulo")
        layout_cartao.addWidget(subtitulo)

        form = QFormLayout()
        self._senha_atual = QLineEdit()
        self._senha_atual.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Senha atual", self._senha_atual)
        self._senha_nova = QLineEdit()
        self._senha_nova.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Nova senha", self._senha_nova)
        self._senha_nova_confirmar = QLineEdit()
        self._senha_nova_confirmar.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Confirmar nova senha", self._senha_nova_confirmar)
        layout_cartao.addLayout(form)

        botao_trocar = QPushButton("Trocar senha")
        botao_trocar.setProperty("role", "botao_primario")
        botao_trocar.clicked.connect(self._trocar_minha_senha)
        layout_cartao.addWidget(botao_trocar)

        return cartao

    def _trocar_minha_senha(self) -> None:
        atual = self._senha_atual.text()
        nova = self._senha_nova.text()
        confirmar = self._senha_nova_confirmar.text()

        if len(nova) < 4:
            QMessageBox.warning(self, "Senha muito curta", "Use pelo menos 4 caracteres.")
            return
        if nova != confirmar:
            QMessageBox.warning(self, "Senhas diferentes", "As duas senhas novas digitadas não são iguais.")
            return

        try:
            trocou = auth.alterar_senha_admin(atual, nova)
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro inesperado ao trocar senha", str(exc))
            return

        if not trocou:
            QMessageBox.warning(self, "Não foi possível trocar", "Senha atual incorreta.")
            return

        self._senha_atual.clear()
        self._senha_nova.clear()
        self._senha_nova_confirmar.clear()
        QMessageBox.information(self, "Senha alterada", "Sua senha de Administrador foi alterada.")

    # -- vendedores -------------------------------------------------------------

    def _construir_secao_vendedores(self) -> QWidget:
        cartao = QFrame()
        cartao.setProperty("role", "card")
        aplicar_sombra_suave(cartao, settings_mod.obter_tema())
        layout_cartao = QVBoxLayout(cartao)
        layout_cartao.setContentsMargins(16, 16, 16, 16)
        layout_cartao.setSpacing(12)

        cabecalho = QHBoxLayout()
        subtitulo = QLabel("Vendedores")
        subtitulo.setProperty("role", "subtitulo")
        cabecalho.addWidget(subtitulo)
        cabecalho.addStretch()
        botao_novo = QPushButton("+ Novo Vendedor")
        botao_novo.setProperty("role", "botao_primario")
        botao_novo.clicked.connect(self._cadastrar_vendedor)
        cabecalho.addWidget(botao_novo)
        layout_cartao.addLayout(cabecalho)

        self._modelo_vendedores = PandasTableModel()
        self._tabela_vendedores = QTableView()
        self._tabela_vendedores.setModel(self._modelo_vendedores)
        self._tabela_vendedores.setAlternatingRowColors(True)
        self._tabela_vendedores.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._tabela_vendedores.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._tabela_vendedores.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._tabela_vendedores.horizontalHeader().setStretchLastSection(True)
        self._tabela_vendedores.verticalHeader().setVisible(False)
        layout_cartao.addWidget(self._tabela_vendedores, stretch=1)

        botao_redefinir = QPushButton("Redefinir Senha do Selecionado")
        botao_redefinir.setProperty("role", "botao_primario")
        botao_redefinir.clicked.connect(self._redefinir_senha_selecionado)
        layout_cartao.addWidget(botao_redefinir)

        return cartao

    def _carregar_vendedores(self) -> None:
        try:
            df = vendedores_mod.listar_vendedores_detalhado()
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro ao carregar vendedores", str(exc))
            return

        # o NOME vira o indice da tabela exibida - permite recuperar qual
        # vendedor foi selecionado direto por indice_real(), sem precisar de
        # uma coluna "escondida" separada (mesmo padrao usado nas outras
        # telas pra identificar a linha real por trás da linha visual). O
        # PandasTableModel so olha pra .columns, nunca pro indice - por isso
        # "Nome" tambem precisa existir como coluna normal, pra aparecer.
        exibicao = pd.DataFrame(
            {"Senha definida": df["SENHA_HASH"].map(lambda h: "Sim" if h else "Não (usar 'Redefinir Senha')")}
        )
        exibicao.index = df["NOME"]
        exibicao = exibicao.sort_index(key=lambda s: s.str.upper())
        exibicao.insert(0, "Nome", exibicao.index)

        self._modelo_vendedores.definir_dataframe(exibicao)
        self._tabela_vendedores.resizeColumnsToContents()

    def _nome_selecionado(self) -> str | None:
        selecionadas = self._tabela_vendedores.selectionModel().selectedRows()
        if not selecionadas:
            return None
        return self._modelo_vendedores.indice_real(selecionadas[0].row())

    def _cadastrar_vendedor(self) -> None:
        nome, ok = QInputDialog.getText(self, "Novo vendedor", "Nome do vendedor:")
        if not ok:
            return
        try:
            nome_salvo = vendedores_mod.adicionar_vendedor(nome)
            senhas_geradas = vendedores_mod.gerar_senhas_iniciais_pendentes()
        except vendedores_mod.ErroVendedor as exc:
            QMessageBox.warning(self, "Não foi possível cadastrar", str(exc))
            return
        except bd.ErroArquivoBloqueado as exc:
            QMessageBox.critical(self, "Arquivo bloqueado", str(exc))
            return
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro inesperado ao cadastrar vendedor", str(exc))
            return

        self._carregar_vendedores()
        senha_do_novo = senhas_geradas.get(nome_salvo)
        if senha_do_novo:
            QMessageBox.information(
                self,
                "Senha inicial gerada",
                f"Senha inicial de acesso para '{nome_salvo}': {senha_do_novo}\n\n"
                "Anote/avise agora - essa senha não pode ser recuperada depois (só redefinida).",
            )

    def _redefinir_senha_selecionado(self) -> None:
        nome = self._nome_selecionado()
        if nome is None:
            QMessageBox.information(self, "Nenhum vendedor selecionado", "Selecione um vendedor na tabela.")
            return

        resposta = QMessageBox.question(
            self,
            "Redefinir senha",
            f"Gerar uma nova senha para '{nome}'? A senha atual dele(a) deixa de funcionar.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resposta != QMessageBox.StandardButton.Yes:
            return

        try:
            nova_senha = vendedores_mod.redefinir_senha(nome)
        except vendedores_mod.ErroVendedor as exc:
            QMessageBox.warning(self, "Não foi possível redefinir", str(exc))
            return
        except bd.ErroArquivoBloqueado as exc:
            QMessageBox.critical(self, "Arquivo bloqueado", str(exc))
            return
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro inesperado ao redefinir senha", str(exc))
            return

        self._carregar_vendedores()
        QMessageBox.information(
            self,
            "Senha redefinida",
            f"Nova senha para '{nome}': {nova_senha}\n\n"
            "Anote/avise agora - essa senha não pode ser recuperada depois (só redefinida de novo).",
        )
