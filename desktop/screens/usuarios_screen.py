"""Tela Administração (antes "Usuários") - só o ADMIN acessa (nem aparece no menu lateral
pra um VENDEDOR - ver desktop/main_window.py). Duas abas:
1. "Meu acesso": trocar o PIN de entrada deste computador (recolhido por padrão - usado raramente).
   Vendedores e Bancos ficam na tela Cadastros (desktop/screens/cadastros_screen.py).
2. "Sincronização e backup": "Sincronizar agora" (reenvia as abas pro Google Sheets na
   hora - core/sincronizacao.py; cada escrita já sincroniza sozinha, e uma falha entra
   numa fila que tenta de novo sozinha - core/sheets_sync.reenviar_pendentes), backup
   automático (1x/dia, ao abrir o app - core/backup.py e desktop/main.py), manual
   ("Fazer backup agora") e "Restaurar".
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
    QLabel,
    QMessageBox,
    QPushButton,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import config
from core import acesso
from core import backup as backup_mod
from core import conta_google
from core import data_store as bd
from core import sincronizacao as sincronizacao_mod
from desktop import settings as settings_mod
from desktop.entrar_com_google import conectar_e_conferir, esquecer_conexoes
from desktop.espera import rodar_esperando
from desktop.table_model import PandasTableModel
from desktop.vigia_do_arquivo import VigiaDoArquivo
from desktop.widgets.cabecalho_retratil import CabecalhoRetratil
from desktop.widgets.campo_de_pin import campo_de_pin
from desktop.widgets.shadow import aplicar_sombra_suave

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


def texto_do_download(resultado: sincronizacao_mod.ResultadoDoDownload) -> str:
    """A mensagem de "dados baixados" (usada aqui e na primeira abertura, sem planilha)."""
    linhas = resultado.linhas
    texto = (
        f"Os dados deste computador agora são os da nuvem: {linhas.get(bd.ABA_CLIENTES, 0)} cliente(s), "
        f"{linhas.get(bd.ABA_PROPOSTAS, 0)} proposta(s), {linhas.get(bd.ABA_EQUIPAMENTOS, 0)} equipamento(s) e "
        f"{linhas.get(bd.ABA_VENDEDORES, 0)} vendedor(es)."
    )
    if resultado.backup is not None:
        texto += f"\n\nO arquivo de antes foi guardado em:\n{resultado.backup}"
    if resultado.ligou_controle:
        texto += (
            "\n\nO controle de versão da nuvem foi ligado agora: a partir daqui, este computador só envia "
            "para a nuvem se ninguém tiver gravado lá no meio-tempo."
        )
    return texto


class UsuariosScreen(QWidget):
    # emitido depois de restaurar um backup: pode ter mudado TUDO (clientes, propostas,
    # vendedores) - quem escuta (MainWindow) reaproveita o mesmo sinal que Propostas/Ficha
    # usam pra avisar o selo da barra lateral e marcar o Dashboard como desatualizado.
    dados_atualizados = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._vigia = VigiaDoArquivo()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        titulo = QLabel("⚙️ Administração")
        titulo.setProperty("role", "titulo")
        layout.addWidget(titulo)

        abas = QTabWidget()
        abas.addTab(self._construir_aba_meu_acesso(), "Meu acesso")
        abas.addTab(self._construir_aba_backup(), "Sincronização e backup")
        layout.addWidget(abas, stretch=1)

        self._carregar_backups()

    def showEvent(self, evento) -> None:
        super().showEvent(evento)
        # o backup automatico diario roda na abertura do app, antes desta tela existir -
        # e um backup manual pode ter sido feito na sessao anterior. Sempre reler ao
        # reaparecer, do mesmo jeito que Propostas rele os vendedores (mostrar_screen).
        self._carregar_backups()

    def recarregar_se_mudou(self) -> None:
        """Chamado a cada tique da janela com esta tela aberta: planilha mudou por fora -> rele a lista de backups
        (os campos digitados ficam como estao)."""
        if self._vigia.mudou_desde_a_leitura():
            self._vigia.registrar_leitura()
            self._carregar_backups()

    # -- aba "Meu acesso" ---------------------------------------------------------------

    def _construir_aba_meu_acesso(self) -> QWidget:
        aba = QWidget()
        layout = QVBoxLayout(aba)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.setSpacing(16)
        layout.addWidget(self._construir_secao_meu_pin())
        layout.addStretch()
        return aba

    # -- meu PIN (entrada neste computador), recolhido por padrão ---------------

    def _construir_secao_meu_pin(self) -> QWidget:
        cartao = QFrame()
        cartao.setProperty("role", "card")
        aplicar_sombra_suave(cartao, settings_mod.obter_tema())
        layout_cartao = QVBoxLayout(cartao)
        layout_cartao.setContentsMargins(16, 16, 16, 16)
        layout_cartao.setSpacing(12)

        self._cabecalho_pin = CabecalhoRetratil(
            "Meu PIN (este computador)",
            dica_expandir="Mostrar os campos para trocar o PIN",
            dica_recolher="Recolher",
            papel_do_titulo="subtitulo",
        )
        self._cabecalho_pin.toggled.connect(self._ao_alternar_meu_pin)
        layout_cartao.addWidget(self._cabecalho_pin)

        self._corpo_pin = QWidget()
        self._corpo_pin.setProperty("role", "transparente")
        self._corpo_pin.setVisible(False)
        corpo = QVBoxLayout(self._corpo_pin)
        corpo.setContentsMargins(0, 0, 0, 0)
        corpo.setSpacing(12)

        self._sem_pin = QLabel(
            "Este computador ainda não tem PIN. Na próxima entrada, o aplicativo pede para entrar com "
            "Google e criar um."
        )
        self._sem_pin.setWordWrap(True)
        self._sem_pin.setProperty("role", "secundario")
        corpo.addWidget(self._sem_pin)

        self._campos_pin = QWidget()
        self._campos_pin.setProperty("role", "transparente")
        campos = QVBoxLayout(self._campos_pin)
        campos.setContentsMargins(0, 0, 0, 0)
        campos.setSpacing(12)
        form = QFormLayout()
        self._pin_atual = campo_de_pin()
        form.addRow("PIN atual", self._pin_atual)
        self._pin_novo = campo_de_pin()
        form.addRow("Novo PIN", self._pin_novo)
        self._pin_novo_confirmar = campo_de_pin()
        form.addRow("Confirmar novo PIN", self._pin_novo_confirmar)
        campos.addLayout(form)
        botao_trocar = QPushButton("Trocar PIN")
        botao_trocar.setProperty("role", "botao_primario")
        botao_trocar.clicked.connect(self._trocar_meu_pin)
        campos.addWidget(botao_trocar)
        corpo.addWidget(self._campos_pin)

        layout_cartao.addWidget(self._corpo_pin)
        self._atualizar_meu_pin()
        return cartao

    def _ao_alternar_meu_pin(self, expandido: bool) -> None:
        self._corpo_pin.setVisible(expandido)

    def _atualizar_meu_pin(self) -> None:
        tem_pin = acesso.pin_configurado()
        self._campos_pin.setVisible(tem_pin)
        self._sem_pin.setVisible(not tem_pin)

    def _trocar_meu_pin(self) -> None:
        atual = self._pin_atual.text()
        novo = self._pin_novo.text()
        if novo != self._pin_novo_confirmar.text():
            QMessageBox.warning(self, "PINs diferentes", "Os dois PINs novos digitados não são iguais.")
            return
        try:
            trocou = acesso.trocar_pin(atual, novo)
        except acesso.ErroPin as exc:
            QMessageBox.warning(self, "PIN inválido", str(exc))
            return
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro inesperado ao trocar o PIN", f"{type(exc).__name__}: {exc}")
            return
        if not trocou:
            self._atualizar_meu_pin()  # errar demais apaga o PIN
            if acesso.pin_configurado():
                QMessageBox.warning(self, "Não foi possível trocar", "PIN atual incorreto.")
            else:
                QMessageBox.warning(
                    self, "PIN apagado",
                    "PIN atual errado vezes demais: o PIN deste computador foi apagado. Na próxima entrada, "
                    "entre com Google e crie outro.",
                )
            return
        for campo in (self._pin_atual, self._pin_novo, self._pin_novo_confirmar):
            campo.clear()
        QMessageBox.information(self, "PIN alterado", "O PIN de entrada deste computador foi alterado.")

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

        linha_conta = QHBoxLayout()
        self._rotulo_conta_google = QLabel("")
        self._rotulo_conta_google.setWordWrap(True)
        linha_conta.addWidget(self._rotulo_conta_google, stretch=1)
        self._botao_conta_google = QPushButton("")
        self._botao_conta_google.clicked.connect(self._ao_clicar_conta_google)
        linha_conta.addWidget(self._botao_conta_google)
        layout_cartao.addLayout(linha_conta)
        self._atualizar_conta_google()

        explicacao = QLabel(
            "Cada alteração já é enviada automaticamente. Se uma sincronização falhar (sem "
            "internet, por exemplo), o aplicativo tenta de novo sozinho em instantes. "
            "\"Sincronizar agora\" força uma tentativa imediata de todas as abas (clientes, "
            "equipamentos, propostas, vendedores e bancos), mesmo sem nada ter mudado - útil depois "
            "de Restaurar um backup, que só mexe no arquivo local. "
            "\"Baixar da nuvem\" faz o contrário: troca os dados DESTE computador pelos da nuvem (útil ao "
            "voltar para um computador depois de trabalhar em outro) - um backup do arquivo atual é "
            "feito antes, e alterações daqui que ainda não foram enviadas são substituídas."
        )
        explicacao.setProperty("role", "secundario")
        explicacao.setWordWrap(True)
        layout_cartao.addWidget(explicacao)

        return cartao

    # -- conta Google ------------------------------------------------------------------

    def _atualizar_conta_google(self) -> None:
        conta = conta_google.conta_conectada()
        if conta is not None:
            self._rotulo_conta_google.setText(f"Conta Google conectada: <b>{conta.email}</b> (a sincronização usa esta conta)")
            self._botao_conta_google.setText("Desconectar")
            self._botao_conta_google.setEnabled(True)
            self._botao_conta_google.setToolTip("Apaga a autorização guardada neste computador.")
            return
        if conta_google.ha_acesso_a_nuvem():
            situacao = "a sincronização usa a chave do Google instalada neste computador"
        else:
            situacao = "sem conta nem chave, este computador não sincroniza"
        self._rotulo_conta_google.setText(f"Nenhuma conta Google conectada ({situacao}).")
        self._botao_conta_google.setText("Conectar com Google")
        disponivel = conta_google.cliente_oauth_disponivel()
        self._botao_conta_google.setEnabled(disponivel)
        self._botao_conta_google.setToolTip(
            "Abre o navegador para entrar na sua conta Google e autorizar o aplicativo." if disponivel
            else "O arquivo de configuração do login Google não está neste computador."
        )

    def _ao_clicar_conta_google(self) -> None:
        if conta_google.conta_conectada() is not None:
            self._desconectar_conta_google()
        else:
            self._conectar_conta_google()

    def _conectar_conta_google(self) -> None:
        conta = conectar_e_conferir(self)
        self._atualizar_conta_google()
        self._atualizar_meu_pin()
        if conta is not None:
            QMessageBox.information(
                self, "Conta Google conectada",
                f"Conectado como {conta.email}. A partir de agora, a sincronização com a nuvem usa esta conta.",
            )

    def _desconectar_conta_google(self) -> None:
        resposta = QMessageBox.question(
            self,
            "Desconectar a conta Google",
            "Apagar a autorização da conta Google guardada neste computador? O PIN de entrada deste computador "
            "também é apagado: na próxima vez, o aplicativo pede para entrar com Google e criar outro.\n\n"
            "A sincronização volta a usar a chave do Google instalada aqui (se houver); sem ela, este computador "
            "para de sincronizar até conectar de novo.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resposta != QMessageBox.StandardButton.Yes:
            return
        try:
            acesso.esquecer_pin()
            rodar_esperando(self, "Desconectando…", conta_google.desconectar, limite_s=20)
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro ao desconectar", f"{type(exc).__name__}: {exc}")
        esquecer_conexoes()
        self._atualizar_conta_google()
        self._atualizar_meu_pin()

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
            "Todas as abas (clientes, equipamentos, propostas, vendedores e bancos) foram enviadas para "
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

    def executar_download_da_nuvem(self, *, ligar_controle: bool = False) -> bool:
        """Baixa da nuvem SEM perguntar (quem chama ja perguntou) e mostra o resultado. True se deu certo.
        `ligar_controle`: aceita uma nuvem ainda sem controle de versao e liga o controle depois de baixar."""
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            resultado = sincronizacao_mod.baixar_da_nuvem(ligar_controle=ligar_controle)
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
        QMessageBox.information(self, "Dados baixados", texto_do_download(resultado))
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

        # a tabela exibida so tem colunas
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
        self.dados_atualizados.emit()
        QMessageBox.information(
            self,
            "Backup restaurado",
            f"Dados restaurados com sucesso.\n\nO estado anterior foi salvo em:\n{seguranca}",
        )
