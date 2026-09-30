"""Tela Administração (antes "Usuários") - só o ADMIN acessa (nem aparece no menu lateral
pra um VENDEDOR - ver desktop/main_window.py). Duas abas:
1. "Usuários": trocar a própria senha do Administrador (recolhido por padrão - usado
   raramente, não precisa competir por espaço com a lista de vendedores) e gerir
   vendedores - cadastrar, ver status/carteira/senha, redefinir senha, renomear,
   transferir carteira e desativar/reativar (o vendedor nunca troca a própria senha nem
   se autoadministra, só o ADMIN pode - ver core/vendedores.py).
2. "Sincronização e backup": "Sincronizar agora" (reenvia as 4 abas pro Google Sheets na
   hora - core/sincronizacao.py; cada escrita já sincroniza sozinha, e uma falha entra
   numa fila que tenta de novo sozinha - core/sheets_sync.reenviar_pendentes), backup
   automático (1x/dia, ao abrir o app - core/backup.py e desktop/main.py), manual
   ("Fazer backup agora") e "Restaurar", e "Mesclar grafias de banco" (reescreve o
   BANCO de propostas antigas - core.propostas.mesclar_bancos).

A aba de Cadastros do prompt original ainda não foi feita - ver
[[projeto-melhorias-em-etapas]] na memória do projeto.
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import config
from core import auth
from core import backup as backup_mod
from core import data_store as bd
from core import propostas as propostas_mod
from core import sincronizacao as sincronizacao_mod
from core import vendedores as vendedores_mod
from desktop import settings as settings_mod
from desktop.table_model import PandasTableModel
from desktop.widgets.cabecalho_retratil import CabecalhoRetratil
from desktop.widgets.shadow import aplicar_sombra_suave

_PAPEL_POR_FORCA = {"fraca": "aviso", "média": "secundario", "forte": "positivo"}
_ROTULO_POR_MOTIVO = {
    backup_mod.MOTIVO_AUTOMATICO: "Automático",
    backup_mod.MOTIVO_MANUAL: "Manual",
    backup_mod.MOTIVO_PRE_RESTAURACAO: "Pré-restauração",
    backup_mod.MOTIVO_PRE_MESCLAGEM: "Pré-mesclagem",
    backup_mod.MOTIVO_PRE_NUVEM: "Antes de baixar da nuvem",
    backup_mod.MOTIVO_COPIA_DA_NUVEM: "Cópia da nuvem (antes de sobrescrever)",
}


def _formatar_tamanho(tamanho_bytes: int) -> str:
    if tamanho_bytes < 1024:
        return f"{tamanho_bytes} B"
    if tamanho_bytes < 1024 * 1024:
        return f"{tamanho_bytes / 1024:.0f} KB"
    return f"{tamanho_bytes / (1024 * 1024):.1f} MB"


class UsuariosScreen(QWidget):
    # emitido depois de restaurar um backup: pode ter mudado TUDO (clientes, propostas,
    # vendedores) - quem escuta (MainWindow) reaproveita o mesmo sinal que Propostas/Ficha
    # usam pra avisar o selo da barra lateral e marcar o Dashboard como desatualizado.
    dados_atualizados = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        titulo = QLabel("⚙️ Administração")
        titulo.setProperty("role", "titulo")
        layout.addWidget(titulo)

        abas = QTabWidget()
        abas.addTab(self._construir_aba_usuarios(), "Usuários")
        abas.addTab(self._construir_aba_backup(), "Sincronização e backup")
        layout.addWidget(abas, stretch=1)

        self._carregar_vendedores()
        self._carregar_backups()
        self._carregar_bancos()

    def showEvent(self, evento) -> None:
        super().showEvent(evento)
        # o backup automatico diario roda na abertura do app, antes desta tela existir -
        # e um backup manual pode ter sido feito na sessao anterior. Sempre reler ao
        # reaparecer, do mesmo jeito que Propostas rele os vendedores (mostrar_screen).
        self._carregar_backups()
        self._carregar_bancos()

    # -- aba "Usuários" ----------------------------------------------------------------

    def _construir_aba_usuarios(self) -> QWidget:
        aba = QWidget()
        layout = QVBoxLayout(aba)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.setSpacing(16)
        layout.addWidget(self._construir_secao_minha_senha())
        layout.addWidget(self._construir_secao_vendedores(), stretch=1)
        return aba

    # -- minha senha (admin), recolhida por padrão -----------------------------

    def _construir_secao_minha_senha(self) -> QWidget:
        cartao = QFrame()
        cartao.setProperty("role", "card")
        aplicar_sombra_suave(cartao, settings_mod.obter_tema())
        layout_cartao = QVBoxLayout(cartao)
        layout_cartao.setContentsMargins(16, 16, 16, 16)
        layout_cartao.setSpacing(12)

        self._cabecalho_senha = CabecalhoRetratil(
            "Minha senha (Administrador)",
            dica_expandir="Mostrar os campos para trocar a senha",
            dica_recolher="Recolher",
            papel_do_titulo="subtitulo",
        )
        self._cabecalho_senha.toggled.connect(self._ao_alternar_minha_senha)
        layout_cartao.addWidget(self._cabecalho_senha)

        self._corpo_senha = QWidget()
        self._corpo_senha.setProperty("role", "transparente")
        self._corpo_senha.setVisible(False)
        corpo = QVBoxLayout(self._corpo_senha)
        corpo.setContentsMargins(0, 0, 0, 0)
        corpo.setSpacing(12)

        form = QFormLayout()
        self._senha_atual = QLineEdit()
        self._senha_atual.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Senha atual", self._senha_atual)
        self._senha_nova = QLineEdit()
        self._senha_nova.setEchoMode(QLineEdit.EchoMode.Password)
        self._senha_nova.textChanged.connect(self._atualizar_forca_da_senha)
        form.addRow("Nova senha", self._senha_nova)
        self._forca_senha = QLabel("")
        self._forca_senha.setProperty("role", "secundario")
        form.addRow("", self._forca_senha)
        self._senha_nova_confirmar = QLineEdit()
        self._senha_nova_confirmar.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Confirmar nova senha", self._senha_nova_confirmar)
        corpo.addLayout(form)

        botao_trocar = QPushButton("Trocar senha")
        botao_trocar.setProperty("role", "botao_primario")
        botao_trocar.clicked.connect(self._trocar_minha_senha)
        corpo.addWidget(botao_trocar)

        layout_cartao.addWidget(self._corpo_senha)
        return cartao

    def _ao_alternar_minha_senha(self, expandido: bool) -> None:
        self._corpo_senha.setVisible(expandido)

    def _atualizar_forca_da_senha(self, texto: str) -> None:
        if not texto:
            self._forca_senha.setText("")
            return
        forca = auth.forca_da_senha(texto)
        self._forca_senha.setProperty("role", _PAPEL_POR_FORCA[forca])
        self._forca_senha.setText(f"Força: {forca} (mínimo {auth.SENHA_MINIMA} caracteres)")
        self._forca_senha.style().unpolish(self._forca_senha)
        self._forca_senha.style().polish(self._forca_senha)

    def _trocar_minha_senha(self) -> None:
        atual = self._senha_atual.text()
        nova = self._senha_nova.text()
        confirmar = self._senha_nova_confirmar.text()

        if len(nova) < auth.SENHA_MINIMA:
            QMessageBox.warning(self, "Senha muito curta", f"Use pelo menos {auth.SENHA_MINIMA} caracteres.")
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
        self._forca_senha.setText("")
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

        linha_botoes = QHBoxLayout()
        self._botao_redefinir = self._botao_de_linha("Redefinir Senha", self._redefinir_senha_selecionado)
        self._botao_renomear = self._botao_de_linha("Renomear", self._renomear_selecionado)
        self._botao_transferir = self._botao_de_linha("Transferir Carteira", self._transferir_carteira_selecionado)
        self._botao_desativar = self._botao_de_linha("Desativar", self._alternar_ativo_selecionado)
        for botao in (self._botao_redefinir, self._botao_renomear, self._botao_transferir, self._botao_desativar):
            linha_botoes.addWidget(botao)
        layout_cartao.addLayout(linha_botoes)

        self._tabela_vendedores.selectionModel().selectionChanged.connect(self._atualizar_botoes_de_vendedor)

        return cartao

    @staticmethod
    def _botao_de_linha(texto: str, ao_clicar) -> QPushButton:
        botao = QPushButton(texto)
        botao.clicked.connect(ao_clicar)
        return botao

    # -- aba "Sincronização e backup" ---------------------------------------------------

    def _construir_aba_backup(self) -> QWidget:
        aba = QWidget()
        layout = QVBoxLayout(aba)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.setSpacing(16)
        layout.addWidget(self._construir_secao_sincronizacao())
        layout.addWidget(self._construir_secao_backup(), stretch=1)
        layout.addWidget(self._construir_secao_mesclar_bancos())
        return aba

    def _construir_secao_sincronizacao(self) -> QWidget:
        cartao = QFrame()
        cartao.setProperty("role", "card")
        aplicar_sombra_suave(cartao, settings_mod.obter_tema())
        layout_cartao = QVBoxLayout(cartao)
        layout_cartao.setContentsMargins(16, 16, 16, 16)
        layout_cartao.setSpacing(12)

        cabecalho = QHBoxLayout()
        subtitulo = QLabel("Sincronização com o Google Sheets")
        subtitulo.setProperty("role", "subtitulo")
        cabecalho.addWidget(subtitulo)
        cabecalho.addStretch()
        botao_sincronizar = QPushButton("Sincronizar agora")
        botao_sincronizar.setProperty("role", "botao_primario")
        botao_sincronizar.clicked.connect(self._sincronizar_agora)
        botao_baixar = QPushButton("Baixar da nuvem")
        botao_baixar.clicked.connect(self._baixar_da_nuvem_pelo_botao)
        cabecalho.addWidget(botao_baixar)
        cabecalho.addWidget(botao_sincronizar)
        layout_cartao.addLayout(cabecalho)

        explicacao = QLabel(
            "Cada alteração já é enviada automaticamente. Se uma sincronização falhar (sem "
            "internet, por exemplo), o aplicativo tenta de novo sozinho em instantes. "
            "\"Sincronizar agora\" força uma tentativa imediata das 4 abas (clientes, "
            "equipamentos, propostas e vendedores), mesmo sem nada ter mudado - útil depois "
            "de Restaurar um backup, que só mexe no arquivo local. "
            "\"Baixar da nuvem\" faz o contrário: troca os dados DESTE computador pelos da nuvem (útil ao "
            "voltar para um computador depois de trabalhar em outro) - um backup do arquivo atual é "
            "feito antes, e alterações daqui que ainda não foram enviadas são substituídas."
        )
        explicacao.setProperty("role", "secundario")
        explicacao.setWordWrap(True)
        layout_cartao.addWidget(explicacao)

        return cartao

    def _sincronizar_agora(self) -> None:
        if not config.SINCRONIZACAO_GOOGLE_ATIVADA:
            QMessageBox.information(
                self,
                "Sincronização desativada",
                "A sincronização com o Google Sheets está desativada neste aplicativo.",
            )
            return
        try:
            sincronizacao_mod.sincronizar_tudo_agora()
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro ao sincronizar", str(exc))
            return
        QMessageBox.information(
            self,
            "Sincronização iniciada",
            "As 4 abas (clientes, equipamentos, propostas e vendedores) foram enviadas para "
            "sincronizar. Acompanhe o indicador na barra lateral.",
        )

    def _baixar_da_nuvem_pelo_botao(self) -> None:
        if not config.SINCRONIZACAO_GOOGLE_ATIVADA:
            QMessageBox.information(
                self,
                "Sincronização desativada",
                "A sincronização com o Google Sheets está desativada neste aplicativo.",
            )
            return
        resposta = QMessageBox.question(
            self,
            "Baixar da nuvem",
            "Trocar os dados DESTE computador pelos que estão na nuvem?\n\n"
            "Um backup do arquivo atual é feito antes (aparece em Backups). Alterações feitas aqui que "
            "ainda não foram enviadas para a nuvem serão substituídas.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resposta == QMessageBox.StandardButton.Yes:
            self.executar_download_da_nuvem()

    def executar_download_da_nuvem(self) -> bool:
        """Baixa da nuvem SEM perguntar (quem chama ja perguntou) e mostra o resultado. True se deu certo."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            resultado = sincronizacao_mod.baixar_da_nuvem()
        except bd.ErroArquivoBloqueado as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Arquivo bloqueado", str(exc))
            return False
        except sincronizacao_mod.ErroNuvem as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Não foi possível baixar da nuvem", str(exc))
            return False
        except Exception as exc:  # nunca falhar em silencio
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(
                self,
                "Erro ao baixar da nuvem",
                f"{type(exc).__name__}: {exc}\n\nNada foi alterado neste computador. Tente de novo em instantes.",
            )
            return False
        QApplication.restoreOverrideCursor()
        self.recarregar_apos_mudar_os_dados()
        linhas = resultado.linhas
        QMessageBox.information(
            self,
            "Dados baixados",
            f"Os dados deste computador agora são os da nuvem: {linhas.get(bd.ABA_CLIENTES, 0)} cliente(s), "
            f"{linhas.get(bd.ABA_PROPOSTAS, 0)} proposta(s), {linhas.get(bd.ABA_EQUIPAMENTOS, 0)} equipamento(s) e "
            f"{linhas.get(bd.ABA_VENDEDORES, 0)} vendedor(es).\n\nO arquivo de antes foi guardado em:\n{resultado.backup}",
        )
        return True

    def executar_envio_substituindo_a_nuvem(self, *, copia_obrigatoria: bool) -> bool:
        """Manda os dados DESTE computador por cima da nuvem (quem chama ja perguntou). True se disparou."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            copia = sincronizacao_mod.enviar_para_a_nuvem_substituindo(copia_obrigatoria=copia_obrigatoria)
        except sincronizacao_mod.ErroNuvem as exc:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Não foi possível enviar para a nuvem", str(exc))
            return False
        except Exception as exc:  # nunca falhar em silencio
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, "Erro ao enviar para a nuvem", f"{type(exc).__name__}: {exc}")
            return False
        QApplication.restoreOverrideCursor()
        self._carregar_backups()
        onde = f"\n\nO que a nuvem tinha antes foi guardado em:\n{copia}" if copia is not None else ""
        QMessageBox.information(
            self,
            "Envio iniciado",
            "Os dados deste computador estão sendo enviados para a nuvem (as 4 abas). Acompanhe o indicador "
            f"na barra lateral.{onde}",
        )
        return True

    def recarregar_apos_mudar_os_dados(self) -> None:
        """Depois de trocar os dados por fora das telas (baixar da nuvem, restaurar): relê as listas daqui
        e avisa as outras telas."""
        self._carregar_backups()
        self._carregar_vendedores()
        self._carregar_bancos()
        self.dados_atualizados.emit()

    def _construir_secao_backup(self) -> QWidget:
        cartao = QFrame()
        cartao.setProperty("role", "card")
        aplicar_sombra_suave(cartao, settings_mod.obter_tema())
        layout_cartao = QVBoxLayout(cartao)
        layout_cartao.setContentsMargins(16, 16, 16, 16)
        layout_cartao.setSpacing(12)

        cabecalho = QHBoxLayout()
        subtitulo = QLabel("Backups")
        subtitulo.setProperty("role", "subtitulo")
        cabecalho.addWidget(subtitulo)
        cabecalho.addStretch()
        botao_agora = QPushButton("Fazer backup agora")
        botao_agora.setProperty("role", "botao_primario")
        botao_agora.clicked.connect(self._fazer_backup_agora)
        cabecalho.addWidget(botao_agora)
        layout_cartao.addLayout(cabecalho)

        explicacao = QLabel(
            "Um backup automático é feito ao abrir o aplicativo (no máximo 1 por dia), mantendo "
            f"sempre os {backup_mod.MAXIMO_BACKUPS_AUTOMATICOS} mais recentes. Backups manuais e o "
            "backup de pré-restauração (feito automaticamente antes de qualquer Restaurar) não são "
            "apagados sozinhos - só você, direto na pasta, se quiser."
        )
        explicacao.setProperty("role", "secundario")
        explicacao.setWordWrap(True)
        layout_cartao.addWidget(explicacao)

        self._modelo_backups = PandasTableModel()
        self._tabela_backups = QTableView()
        self._tabela_backups.setModel(self._modelo_backups)
        self._tabela_backups.setAlternatingRowColors(True)
        self._tabela_backups.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._tabela_backups.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._tabela_backups.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._tabela_backups.horizontalHeader().setStretchLastSection(True)
        self._tabela_backups.verticalHeader().setVisible(False)
        layout_cartao.addWidget(self._tabela_backups, stretch=1)

        linha_botoes = QHBoxLayout()
        self._botao_restaurar = self._botao_de_linha("Restaurar", self._restaurar_selecionado)
        linha_botoes.addWidget(self._botao_restaurar)
        linha_botoes.addStretch()
        layout_cartao.addLayout(linha_botoes)

        self._tabela_backups.selectionModel().selectionChanged.connect(self._atualizar_botao_restaurar)

        return cartao

    def _carregar_backups(self) -> None:
        try:
            backups = backup_mod.listar_backups()
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro ao carregar backups", str(exc))
            return

        # mesmo padrao do cache de _carregar_vendedores: a tabela exibida so tem colunas
        # formatadas pra leitura, o objeto Backup de verdade fica aqui, por caminho
        self._backups_por_caminho = {str(b.caminho): b for b in backups}

        exibicao = pd.DataFrame({
            "Quando": [b.quando.strftime("%d/%m/%Y %H:%M") for b in backups],
            "Tipo": [_ROTULO_POR_MOTIVO.get(b.motivo, b.motivo) for b in backups],
            "Tamanho": [_formatar_tamanho(b.tamanho_bytes) for b in backups],
        })
        exibicao.index = [str(b.caminho) for b in backups]

        self._modelo_backups.definir_dataframe(exibicao)
        self._tabela_backups.resizeColumnsToContents()
        self._atualizar_botao_restaurar()

    def _backup_selecionado(self) -> backup_mod.Backup | None:
        selecionadas = self._tabela_backups.selectionModel().selectedRows()
        if not selecionadas:
            return None
        caminho = self._modelo_backups.indice_real(selecionadas[0].row())
        return self._backups_por_caminho.get(caminho)

    def _atualizar_botao_restaurar(self, *_args) -> None:
        self._botao_restaurar.setEnabled(self._backup_selecionado() is not None)

    def _fazer_backup_agora(self) -> None:
        try:
            caminho = backup_mod.fazer_backup(backup_mod.MOTIVO_MANUAL)
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro ao fazer backup", str(exc))
            return
        self._carregar_backups()
        QMessageBox.information(self, "Backup feito", f"Backup salvo em:\n{caminho}")

    def _restaurar_selecionado(self) -> None:
        backup = self._backup_selecionado()
        if backup is None:
            QMessageBox.information(self, "Nenhum backup selecionado", "Selecione um backup na tabela.")
            return

        resposta = QMessageBox.question(
            self,
            "Restaurar backup",
            f"Restaurar o backup de {backup.quando.strftime('%d/%m/%Y %H:%M')} "
            f"({_ROTULO_POR_MOTIVO.get(backup.motivo, backup.motivo)})?\n\n"
            "Isso substitui TODOS os dados atuais (clientes, propostas, vendedores) pelos deste "
            "backup. O estado atual também é salvo automaticamente antes - então, se precisar, dá "
            "pra desfazer essa restauração também.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resposta != QMessageBox.StandardButton.Yes:
            return

        try:
            seguranca = backup_mod.restaurar_backup(backup.caminho)
        except bd.ErroArquivoBloqueado as exc:
            QMessageBox.critical(self, "Arquivo bloqueado", str(exc))
            return
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro inesperado ao restaurar", str(exc))
            return

        self._carregar_backups()
        self._carregar_vendedores()
        self._carregar_bancos()
        self.dados_atualizados.emit()
        QMessageBox.information(
            self,
            "Backup restaurado",
            f"Dados restaurados com sucesso.\n\nO estado anterior foi salvo em:\n{seguranca}",
        )

    # -- mesclar grafias de banco -------------------------------------------------------

    def _construir_secao_mesclar_bancos(self) -> QWidget:
        cartao = QFrame()
        cartao.setProperty("role", "card")
        aplicar_sombra_suave(cartao, settings_mod.obter_tema())
        layout_cartao = QVBoxLayout(cartao)
        layout_cartao.setContentsMargins(16, 16, 16, 16)
        layout_cartao.setSpacing(12)

        subtitulo = QLabel("Mesclar grafias de banco")
        subtitulo.setProperty("role", "subtitulo")
        layout_cartao.addWidget(subtitulo)

        explicacao = QLabel(
            "Escolha 2 ou mais grafias do mesmo banco (ex.: \"Hubcred BV\" e \"HUBCRED BV\") e o "
            "texto final - todas as propostas com as grafias marcadas passam a usar o texto "
            "final, incluindo propostas antigas. Um backup do estado atual é feito "
            "automaticamente antes."
        )
        explicacao.setProperty("role", "secundario")
        explicacao.setWordWrap(True)
        layout_cartao.addWidget(explicacao)

        self._lista_bancos = QListWidget()
        self._lista_bancos.itemChanged.connect(self._atualizar_botao_mesclar)
        layout_cartao.addWidget(self._lista_bancos)

        form = QFormLayout()
        self._grafia_final = QLineEdit()
        self._grafia_final.setPlaceholderText("Texto final (ex.: Hubcred BV)")
        self._grafia_final.textChanged.connect(self._atualizar_botao_mesclar)
        form.addRow("Grafia final", self._grafia_final)
        layout_cartao.addLayout(form)

        self._botao_mesclar = QPushButton("Mesclar")
        self._botao_mesclar.setProperty("role", "botao_primario")
        self._botao_mesclar.setEnabled(False)
        self._botao_mesclar.clicked.connect(self._mesclar_bancos_selecionados)
        layout_cartao.addWidget(self._botao_mesclar)

        return cartao

    def _carregar_bancos(self) -> None:
        try:
            bancos = propostas_mod.bancos_distintos()
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro ao carregar bancos", str(exc))
            return

        self._lista_bancos.blockSignals(True)
        try:
            self._lista_bancos.clear()
            for banco, quantidade in bancos:
                sufixo = "proposta" if quantidade == 1 else "propostas"
                item = QListWidgetItem(f"{banco}  ({quantidade} {sufixo})")
                item.setData(Qt.ItemDataRole.UserRole, banco)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                self._lista_bancos.addItem(item)
        finally:
            self._lista_bancos.blockSignals(False)
        self._atualizar_botao_mesclar()

    def _bancos_selecionados(self) -> list[str]:
        selecionados = []
        for i in range(self._lista_bancos.count()):
            item = self._lista_bancos.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selecionados.append(item.data(Qt.ItemDataRole.UserRole))
        return selecionados

    def _atualizar_botao_mesclar(self, *_args) -> None:
        self._botao_mesclar.setEnabled(
            len(self._bancos_selecionados()) >= 2 and bool(self._grafia_final.text().strip())
        )

    def _mesclar_bancos_selecionados(self) -> None:
        selecionados = self._bancos_selecionados()
        final = self._grafia_final.text().strip()
        if len(selecionados) < 2 or not final:
            return  # o botao ja fica desabilitado nesse caso - so uma garantia a mais

        resposta = QMessageBox.question(
            self,
            "Mesclar grafias de banco",
            "Isso reescreve TODAS as propostas com:\n"
            + "\n".join(f"- {banco}" for banco in selecionados)
            + f'\n\npara "{final}" - incluindo propostas antigas. Um backup do estado atual é '
            "feito antes. Continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resposta != QMessageBox.StandardButton.Yes:
            return

        try:
            quantidade = propostas_mod.mesclar_bancos(selecionados, final)
        except propostas_mod.ErroProposta as exc:
            QMessageBox.warning(self, "Não foi possível mesclar", str(exc))
            return
        except bd.ErroArquivoBloqueado as exc:
            QMessageBox.critical(self, "Arquivo bloqueado", str(exc))
            return
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro inesperado ao mesclar", str(exc))
            return

        self._grafia_final.clear()
        self._carregar_bancos()
        self._carregar_backups()
        self.dados_atualizados.emit()
        QMessageBox.information(
            self,
            "Grafias mescladas",
            f'{quantidade} proposta(s) atualizada(s) para "{final}".',
        )

    def _carregar_vendedores(self) -> None:
        try:
            df = vendedores_mod.listar_vendedores_detalhado()
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro ao carregar vendedores", str(exc))
            return

        # o NOME vira o indice da tabela exibida - permite recuperar qual vendedor foi
        # selecionado direto por indice_real(), sem precisar de uma coluna "escondida"
        # separada (mesmo padrao usado nas outras telas). O PandasTableModel so olha
        # pra .columns, nunca pro indice - por isso "Nome" tambem precisa existir como
        # coluna normal, pra aparecer.
        # cache separado (nome -> ativo?): a tabela so guarda o TEXTO formatado
        # ("Ativo"/"Inativo"), e o botao Desativar/Reativar precisa do booleano
        self._ativo_por_nome = {n: vendedores_mod.esta_ativo(a) for n, a in zip(df["NOME"], df["ATIVO"])}

        exibicao = pd.DataFrame({
            "Status": [("Ativo" if self._ativo_por_nome[n] else "Inativo") for n in df["NOME"]],
            "Carteira": [vendedores_mod.contar_carteira(n) for n in df["NOME"]],
            "Senha": df["SENHA_HASH"].map(lambda h: "Definida" if h else "Pendente"),
        })
        exibicao.index = df["NOME"]
        exibicao = exibicao.sort_index(key=lambda s: s.str.upper())
        exibicao.insert(0, "Nome", exibicao.index)

        self._modelo_vendedores.definir_dataframe(exibicao)
        self._tabela_vendedores.resizeColumnsToContents()
        self._atualizar_botoes_de_vendedor()

    def _nome_selecionado(self) -> str | None:
        selecionadas = self._tabela_vendedores.selectionModel().selectedRows()
        if not selecionadas:
            return None
        return self._modelo_vendedores.indice_real(selecionadas[0].row())

    def _vendedor_selecionado_esta_ativo(self) -> bool | None:
        """None se nao ha selecao; senao, o status ATUAL (do cache montado em
        _carregar_vendedores - evita reler o arquivo so pra saber o rotulo do botao
        Desativar/Reativar)."""
        nome = self._nome_selecionado()
        if nome is None:
            return None
        return self._ativo_por_nome.get(nome, True)

    def _atualizar_botoes_de_vendedor(self, *_args) -> None:
        ativo = self._vendedor_selecionado_esta_ativo()
        algum_selecionado = ativo is not None
        self._botao_redefinir.setEnabled(algum_selecionado)
        self._botao_renomear.setEnabled(algum_selecionado)
        self._botao_transferir.setEnabled(algum_selecionado)
        self._botao_desativar.setEnabled(algum_selecionado)
        self._botao_desativar.setText("Desativar" if ativo or ativo is None else "Reativar")

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

    def _renomear_selecionado(self) -> None:
        nome = self._nome_selecionado()
        if nome is None:
            QMessageBox.information(self, "Nenhum vendedor selecionado", "Selecione um vendedor na tabela.")
            return
        novo_nome, ok = QInputDialog.getText(self, "Renomear vendedor", "Novo nome:", text=nome)
        if not ok:
            return
        try:
            vendedores_mod.renomear_vendedor(nome, novo_nome)
        except vendedores_mod.ErroVendedor as exc:
            QMessageBox.warning(self, "Não foi possível renomear", str(exc))
            return
        except bd.ErroArquivoBloqueado as exc:
            QMessageBox.critical(self, "Arquivo bloqueado", str(exc))
            return
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro inesperado ao renomear", str(exc))
            return
        self._carregar_vendedores()
        QMessageBox.information(
            self, "Vendedor renomeado",
            f"'{nome}' agora é '{novo_nome}' (os clientes dele já estão com o nome novo).",
        )

    def _transferir_carteira_selecionado(self) -> None:
        nome = self._nome_selecionado()
        if nome is None:
            QMessageBox.information(self, "Nenhum vendedor selecionado", "Selecione um vendedor na tabela.")
            return
        candidatos = [n for n in vendedores_mod.listar_vendedores_ativos() if n.upper() != nome.upper()]
        if not candidatos:
            QMessageBox.information(
                self, "Sem destino disponível", "Não há outro vendedor ativo para receber a carteira."
            )
            return
        destino, ok = QInputDialog.getItem(
            self, "Transferir carteira", f"Passar os clientes de '{nome}' para:", candidatos, 0, False
        )
        if not ok:
            return
        try:
            quantidade = vendedores_mod.transferir_carteira(nome, destino)
        except vendedores_mod.ErroVendedor as exc:
            QMessageBox.warning(self, "Não foi possível transferir", str(exc))
            return
        except bd.ErroArquivoBloqueado as exc:
            QMessageBox.critical(self, "Arquivo bloqueado", str(exc))
            return
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro inesperado ao transferir carteira", str(exc))
            return
        self._carregar_vendedores()
        QMessageBox.information(
            self, "Carteira transferida",
            f"{quantidade} cliente(s) de '{nome}' agora estão com '{destino}'." if quantidade
            else f"'{nome}' já não tinha nenhum cliente - nada para transferir.",
        )

    def _alternar_ativo_selecionado(self) -> None:
        nome = self._nome_selecionado()
        if nome is None:
            QMessageBox.information(self, "Nenhum vendedor selecionado", "Selecione um vendedor na tabela.")
            return
        ativo = self._vendedor_selecionado_esta_ativo()

        if ativo:
            resposta = QMessageBox.question(
                self, "Desativar vendedor",
                f"Desativar '{nome}'? Ele(a) para de aparecer para escolher em cadastros novos e não "
                "consegue mais logar - o histórico dele(a) continua intacto.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
            )
            if resposta != QMessageBox.StandardButton.Yes:
                return
            try:
                vendedores_mod.desativar_vendedor(nome)
            except vendedores_mod.ErroVendedor as exc:
                QMessageBox.warning(self, "Não foi possível desativar", str(exc))
                return
            except bd.ErroArquivoBloqueado as exc:
                QMessageBox.critical(self, "Arquivo bloqueado", str(exc))
                return
            except Exception as exc:  # nunca falhar em silencio
                QMessageBox.critical(self, "Erro inesperado ao desativar", str(exc))
                return
        else:
            try:
                vendedores_mod.reativar_vendedor(nome)
            except vendedores_mod.ErroVendedor as exc:
                QMessageBox.warning(self, "Não foi possível reativar", str(exc))
                return
            except bd.ErroArquivoBloqueado as exc:
                QMessageBox.critical(self, "Arquivo bloqueado", str(exc))
                return
            except Exception as exc:  # nunca falhar em silencio
                QMessageBox.critical(self, "Erro inesperado ao reativar", str(exc))
                return

        self._carregar_vendedores()
