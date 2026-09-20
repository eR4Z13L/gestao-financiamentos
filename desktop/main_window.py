"""Janela principal: barra lateral (retratil) + area de conteudo (QStackedWidget).

A barra lateral, de cima pra baixo: botao de recolher e nome do app; quem esta logado (avatar,
nome e nivel de acesso); "+ Nova proposta" (so ADMIN); o menu, em grupos, com um selo de
"propostas paradas" em Todas as Propostas; e o rodape (estado da sincronizacao, tema, Sair e
a versao).

Pra adicionar uma tela nova: cria a tela em _construir_paginas() e poe um ItemDoMenu no grupo
certo. Cada tela tem uma CHAVE (as constantes PAGINA_*): e por ela - nunca pela posicao - que
se navega (ir_para) e que se lembra a ultima tela aberta, ja que as telas mudam conforme o
papel de quem entrou (o VENDEDOR nao tem Administracao).
"""

from __future__ import annotations

import logging
from datetime import datetime
from functools import partial

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import config
from core import data_store_sheets as leitura_sheets
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import sheets_sync
from desktop import settings as settings_mod
from desktop.screens.dashboard_screen import DashboardScreen
from desktop.screens.ficha_cliente_screen import FichaClienteScreen
from desktop.screens.propostas_screen import PropostasScreen
from desktop.screens.usuarios_screen import UsuariosScreen
from desktop.theme import TEMA_CLARO, TEMA_ESCURO, build_stylesheet
from desktop.widgets.botao_lateral import BotaoLateral
from desktop.widgets.identidade_usuario import IdentidadeUsuario
from desktop.widgets.indicador_sincronizacao import (
    IndicadorSincronizacao,
    descrever_leitura,
    descrever_sincronizacao,
)
from desktop.widgets.menu_lateral import GrupoDoMenu, ItemDoMenu, MenuLateral

_logger = logging.getLogger(__name__)

PAGINA_DASHBOARD = "dashboard"
PAGINA_FICHA = "ficha"
PAGINA_PROPOSTAS = "propostas"
PAGINA_ADMINISTRACAO = "administracao"

_LARGURA_EXPANDIDA = 230
_LARGURA_RECOLHIDA = 60
_MARGEM_LATERAL = 14
_MARGEM_LATERAL_RECOLHIDA = 12  # (59 uteis - 34 do avatar) / 2: a barra tem 1 px de borda, e o avatar cabe inteiro
_TAMANHO_INICIAL = (1200, 800)
_INTERVALO_DO_INDICADOR_MS = 2000  # relê so a memoria (nunca a rede): barato


class MainWindow(QMainWindow):
    sair_solicitado = Signal()  # o botao Sair (ja confirmado): quem abriu a janela cuida do login

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gestão de Financiamentos")
        self._restaurar_geometria()

        self._menu_recolhido = settings_mod.obter_sidebar_recolhida()
        self._tema_atual = settings_mod.obter_tema()

        self._paginas = QStackedWidget()
        self._indice_por_chave: dict[str, int] = {}
        grupos = self._construir_paginas()
        sidebar = self._construir_sidebar(grupos)

        corpo = QWidget()
        layout = QHBoxLayout(corpo)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(sidebar)
        layout.addWidget(self._paginas, stretch=1)
        self.setCentralWidget(corpo)

        self._aplicar_estado_sidebar()
        self._configurar_atalhos()

        self._tela_propostas.dados_atualizados.connect(self._atualizar_selo_propostas)
        self._tela_ficha.dados_atualizados.connect(self._atualizar_selo_propostas)
        # o Dashboard nao muda dado, mas mostra o que outras telas mudam: reler quando voltar a ele
        self._tela_propostas.dados_atualizados.connect(self._tela_dashboard.marcar_como_desatualizado)
        self._tela_ficha.dados_atualizados.connect(self._tela_dashboard.marcar_como_desatualizado)
        # e cada linha clicavel dele pede pra levar a pessoa a outra tela
        self._tela_dashboard.filtro_pedido.connect(self.abrir_propostas_filtradas)
        self._tela_dashboard.ficha_pedida.connect(self.abrir_ficha_do_cliente)
        self._tela_dashboard.duplicacao_pedida.connect(self.abrir_nova_proposta_duplicada)
        self._menu.pagina_escolhida.connect(self._ao_escolher_pagina)

        self._temporizador_do_indicador = QTimer(self)
        self._temporizador_do_indicador.timeout.connect(self._atualizar_indicador_de_sincronizacao)
        self._temporizador_do_indicador.start(_INTERVALO_DO_INDICADOR_MS)

        # abre na ultima tela usada (se ela existe pra este usuario); escolher() ja atualiza o selo
        # e o indicador, como qualquer troca de tela
        ultima = settings_mod.obter_ultima_tela()
        self._menu.escolher(ultima if ultima in self._indice_por_chave else next(iter(self._indice_por_chave)))

    # -- telas ----------------------------------------------------------------------

    def _construir_paginas(self) -> list[GrupoDoMenu]:
        """Cria as telas (na ordem do menu) e devolve os grupos do menu que as levam."""
        self._tela_dashboard = DashboardScreen()
        self._tela_ficha = FichaClienteScreen()
        self._tela_propostas = PropostasScreen()
        # (chave, rotulo, icone, tela) por grupo
        visao_geral = [
            (PAGINA_DASHBOARD, "Dashboard de Propostas", "dashboard", self._tela_dashboard),
            (PAGINA_FICHA, "Ficha de Cliente", "ficha", self._tela_ficha),
            (PAGINA_PROPOSTAS, "Todas as Propostas", "propostas", self._tela_propostas),
        ]
        grupos_e_telas = [("Visão geral", visao_geral)]
        # gestao de usuarios (trocar a propria senha, cadastrar vendedor, redefinir senha de
        # vendedor) e coisa de ADMIN - nem aparece no menu pro VENDEDOR, que so tem leitura
        if sessao_mod.eh_admin():
            self._tela_administracao = UsuariosScreen()
            grupos_e_telas.append(
                ("Administração", [(PAGINA_ADMINISTRACAO, "Administração", "administracao", self._tela_administracao)])
            )

        grupos = []
        numero = 0
        for titulo, itens in grupos_e_telas:
            itens_do_menu = []
            for chave, rotulo, icone, tela in itens:
                numero += 1
                self._indice_por_chave[chave] = self._paginas.addWidget(tela)
                itens_do_menu.append(ItemDoMenu(chave, rotulo, icone, atalho=f"Ctrl+{numero}"))
            grupos.append(GrupoDoMenu(titulo, itens_do_menu))
        return grupos

    def pagina(self, chave: str) -> QWidget:
        return self._paginas.widget(self._indice_por_chave[chave])

    def chave_atual(self) -> str | None:
        return self._menu.chave_atual()

    def ir_para(self, chave: str) -> None:
        """Abre a tela `chave` (uma das PAGINA_*) - o mesmo que clicar no item do menu."""
        self._menu.escolher(chave)

    def ir_para_indice(self, indice: int) -> None:
        chave = next(c for c, i in self._indice_por_chave.items() if i == indice)
        self.ir_para(chave)

    # -- navegacao pedida por outras telas (as linhas clicaveis do Dashboard) ------------------

    def abrir_propostas_filtradas(self, filtro) -> None:
        """Todas as Propostas ja filtrada pelo `filtro` (core.dashboard.FiltroDoDashboard)."""
        if not self._confirmar_descartar_edicoes():
            return
        self.ir_para(PAGINA_PROPOSTAS)
        self._tela_propostas.aplicar_filtro_do_dashboard(filtro)

    def abrir_ficha_do_cliente(self, cpf: str) -> None:
        if not self._confirmar_descartar_edicoes():
            return
        self.ir_para(PAGINA_FICHA)
        self._tela_ficha.abrir_ficha_do_cliente(cpf)

    def abrir_nova_proposta_duplicada(self, cpf: str, indice_da_proposta: int) -> None:
        """A Ficha do cliente com o card "Nova proposta" ja preenchido a partir da proposta `indice_da_proposta`."""
        if not sessao_mod.eh_admin():  # so o ADMIN cria proposta (a trava de verdade tambem esta no core)
            return
        if not self._confirmar_descartar_edicoes():
            return
        self.ir_para(PAGINA_FICHA)
        self._tela_ficha.abrir_nova_proposta_a_partir_de(cpf, indice_da_proposta)

    def _confirmar_descartar_edicoes(self, pergunta: str = "Descartar as alterações e continuar?") -> bool:
        """Se ha um card de proposta com edicao nao salva, pergunta antes de seguir; True = pode seguir."""
        if not self.tem_edicao_pendente():
            return True
        resposta = QMessageBox.question(
            self,
            "Alterações não salvas",
            f"Há uma proposta com alterações que ainda não foram salvas. {pergunta}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return resposta == QMessageBox.StandardButton.Yes

    def _ao_escolher_pagina(self, chave: str) -> None:
        self._paginas.setCurrentIndex(self._indice_por_chave[chave])
        settings_mod.definir_ultima_tela(chave)
        # voltar pra uma tela e um bom momento pra rever o que depende de dados que outra tela
        # pode ter mudado
        self._atualizar_selo_propostas()
        self._atualizar_indicador_de_sincronizacao()

    def _configurar_atalhos(self) -> None:
        """Ctrl+1, Ctrl+2... abrem as telas na ordem do menu (o tooltip de cada item diz qual)."""
        for chave in self._menu.chaves():
            atalho = QShortcut(QKeySequence(self._menu.atalho(chave)), self)
            atalho.activated.connect(partial(self.ir_para, chave))

    # -- barra lateral --------------------------------------------------------------

    def _construir_sidebar(self, grupos: list[GrupoDoMenu]) -> QWidget:
        sidebar = QFrame()
        self._sidebar = sidebar
        sidebar.setProperty("role", "sidebar")
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        cabecalho = QWidget()
        cabecalho.setProperty("role", "transparente")
        layout_cabecalho = QHBoxLayout(cabecalho)
        layout_cabecalho.setContentsMargins(14, 16, 14, 12)
        layout_cabecalho.setSpacing(10)

        self._botao_recolher = QPushButton("☰")
        self._botao_recolher.setProperty("role", "botao_icone")
        self._botao_recolher.setFixedSize(32, 32)
        self._botao_recolher.setToolTip("Recolher/expandir menu")
        self._botao_recolher.clicked.connect(self._alternar_sidebar)
        layout_cabecalho.addWidget(self._botao_recolher)

        self._titulo_app = QLabel("Financiamentos")
        self._titulo_app.setProperty("role", "titulo_app")
        layout_cabecalho.addWidget(self._titulo_app)
        layout_cabecalho.addStretch()
        layout.addWidget(cabecalho)

        # quem esta logado e com que nivel de acesso - fica visivel o tempo todo, pra nunca
        # deixar duvida sobre estar em modo leitura
        sessao = sessao_mod.atual()
        nome = sessao.nome_usuario if sessao is not None else ""
        acesso = "Acesso total" if sessao_mod.eh_admin() else "Somente leitura"
        self._identidade = IdentidadeUsuario(nome, acesso)
        self._contentor_identidade = QWidget()
        self._contentor_identidade.setProperty("role", "transparente")
        layout_identidade = QVBoxLayout(self._contentor_identidade)
        layout_identidade.setContentsMargins(_MARGEM_LATERAL, 0, _MARGEM_LATERAL, 12)
        layout_identidade.addWidget(self._identidade)
        layout.addWidget(self._contentor_identidade)

        # atalho de quem cria proposta o dia todo; o VENDEDOR so le, entao nem tem o botao
        self._botao_nova_proposta: QPushButton | None = None
        if sessao_mod.eh_admin():
            self._botao_nova_proposta = QPushButton("+ Nova proposta")
            self._botao_nova_proposta.setProperty("role", "botao_primario")
            self._botao_nova_proposta.setToolTip("Nova proposta")
            self._botao_nova_proposta.clicked.connect(self._ao_clicar_nova_proposta)
            contentor_nova = QWidget()
            contentor_nova.setProperty("role", "transparente")
            layout_nova = QVBoxLayout(contentor_nova)
            layout_nova.setContentsMargins(_MARGEM_LATERAL, 0, _MARGEM_LATERAL, 8)
            layout_nova.addWidget(self._botao_nova_proposta)
            layout.addWidget(contentor_nova)
            self._contentor_nova_proposta = contentor_nova

        self._menu = MenuLateral()
        self._menu.definir_itens(grupos)
        layout.addWidget(self._menu, stretch=1)

        layout.addWidget(self._construir_rodape())
        return sidebar

    def _construir_rodape(self) -> QWidget:
        rodape = QFrame()
        rodape.setProperty("role", "rodape_lateral")
        layout = QVBoxLayout(rodape)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        self._indicador_sincronizacao = IndicadorSincronizacao()
        self._indicador_sincronizacao.clicked.connect(self._mostrar_detalhe_da_sincronizacao)
        layout.addWidget(self._indicador_sincronizacao)

        self._botao_tema = BotaoLateral("", "sol")
        self._botao_tema.clicked.connect(self._alternar_tema)
        layout.addWidget(self._botao_tema)

        self._botao_sair = BotaoLateral("Sair", "sair")
        self._botao_sair.setToolTip("Sair e entrar com outro usuário")
        self._botao_sair.clicked.connect(self._ao_clicar_sair)
        layout.addWidget(self._botao_sair)

        self._rotulo_versao = QLabel(f"v{config.VERSAO_APP}")
        self._rotulo_versao.setProperty("role", "versao")
        self._rotulo_versao.setContentsMargins(12, 2, 0, 0)
        layout.addWidget(self._rotulo_versao)

        self._atualizar_botao_tema()
        return rodape

    # -- menu lateral retratil -----------------------------------------------------------

    def _alternar_sidebar(self) -> None:
        self._menu_recolhido = not self._menu_recolhido
        settings_mod.definir_sidebar_recolhida(self._menu_recolhido)
        self._aplicar_estado_sidebar()

    def _aplicar_estado_sidebar(self) -> None:
        recolhido = self._menu_recolhido
        self._sidebar.setFixedWidth(_LARGURA_RECOLHIDA if recolhido else _LARGURA_EXPANDIDA)

        self._titulo_app.setVisible(not recolhido)
        self._identidade.definir_recolhido(recolhido)
        margem = _MARGEM_LATERAL_RECOLHIDA if recolhido else _MARGEM_LATERAL
        self._contentor_identidade.layout().setContentsMargins(margem, 0, margem, 12)
        if self._botao_nova_proposta is not None:
            self._botao_nova_proposta.setText("+" if recolhido else "+ Nova proposta")
            self._contentor_nova_proposta.layout().setContentsMargins(margem, 0, margem, 8)
            # o "+" cabe na barra estreita so sem o padding de um botao normal (ver theme.py)
            self._botao_nova_proposta.setProperty("compacto", recolhido)
            self._botao_nova_proposta.style().unpolish(self._botao_nova_proposta)
            self._botao_nova_proposta.style().polish(self._botao_nova_proposta)
        self._menu.definir_recolhido(recolhido)
        for botao in (self._indicador_sincronizacao, self._botao_tema, self._botao_sair):
            botao.definir_recolhido(recolhido)
        self._rotulo_versao.setVisible(not recolhido)

    # -- nova proposta --------------------------------------------------------------------

    def _ao_clicar_nova_proposta(self) -> None:
        self.ir_para(PAGINA_PROPOSTAS)
        self._tela_propostas.abrir_nova_proposta()

    # -- selo de propostas paradas ---------------------------------------------------------

    def _atualizar_selo_propostas(self, *_args) -> None:
        """Conta as propostas em aberto ha mais de DIAS_PROPOSTA_PARADA dias e poe o numero no item
        Todas as Propostas. O ADMIN le do arquivo local (barato); o VENDEDOR usa o que a tela de
        propostas ja leu do Google Sheets - reler a cada troca de tela seria uma ida a rede."""
        try:
            if sessao_mod.eh_vendedor():
                propostas = self._tela_propostas.propostas_carregadas()
            else:
                propostas = propostas_mod.listar_propostas()
            quantidade = propostas_mod.contar_paradas(propostas)
        except Exception as exc:  # nunca falhar em silencio: o selo vira "!" com o motivo no tooltip
            _logger.warning("Nao foi possivel contar as propostas paradas.", exc_info=True)
            self._menu.definir_selo(PAGINA_PROPOSTAS, None, erro=f"Não foi possível contar as propostas paradas: {exc}")
            return

        dias = propostas_mod.DIAS_PROPOSTA_PARADA
        dica = ""
        if quantidade == 1:
            dica = f"1 proposta em aberto há mais de {dias} dias"
        elif quantidade > 1:
            dica = f"{quantidade} propostas em aberto há mais de {dias} dias"
        self._menu.definir_selo(PAGINA_PROPOSTAS, quantidade, dica)

    # -- sincronizacao ---------------------------------------------------------------------

    def _atualizar_indicador_de_sincronizacao(self) -> None:
        agora = datetime.now()
        if sessao_mod.eh_vendedor():
            descricao = descrever_leitura(leitura_sheets.ultima_leitura(), agora)
        else:
            descricao = descrever_sincronizacao(sheets_sync.estado_atual(), agora)
        if descricao != self._indicador_sincronizacao.descricao():
            self._indicador_sincronizacao.definir(descricao)

    def _mostrar_detalhe_da_sincronizacao(self) -> None:
        self._atualizar_indicador_de_sincronizacao()
        descricao = self._indicador_sincronizacao.descricao()
        if sessao_mod.eh_vendedor():
            QMessageBox.information(self, "Dados do Google Sheets", descricao.detalhe)
        elif descricao.nivel == sheets_sync.NIVEL_FALHOU:
            QMessageBox.warning(self, "Falha na sincronização", descricao.detalhe)
        else:
            QMessageBox.information(self, "Sincronização com o Google Sheets", descricao.detalhe)

    # -- sair --------------------------------------------------------------------------------

    def tem_edicao_pendente(self) -> bool:
        """Algum card de proposta (na Ficha ou em Todas as Propostas) com edicao nao salva."""
        return self._tela_ficha.tem_edicao_pendente() or self._tela_propostas.tem_edicao_pendente()

    def _ao_clicar_sair(self) -> None:
        if not self._confirmar_descartar_edicoes("Sair mesmo assim e descartar as alterações?"):
            return
        self.sair_solicitado.emit()

    def desligar(self) -> None:
        """Chamado por quem abriu a janela ao encerrar a sessao: guarda o estado da janela e
        para o temporizador (ela ainda existe, escondida, enquanto o login aparece)."""
        self._temporizador_do_indicador.stop()
        self._salvar_estado_da_janela()

    def closeEvent(self, evento) -> None:
        self._salvar_estado_da_janela()
        super().closeEvent(evento)

    # -- tamanho e posicao da janela ---------------------------------------------------------------

    def _restaurar_geometria(self) -> None:
        geometria = settings_mod.obter_geometria_janela()
        if geometria is None or not self.restoreGeometry(geometria):
            self.resize(*_TAMANHO_INICIAL)

    def _salvar_estado_da_janela(self) -> None:
        settings_mod.definir_geometria_janela(self.saveGeometry())

    # -- tema -----------------------------------------------------------------------------------------

    def _alternar_tema(self) -> None:
        self._tema_atual = TEMA_CLARO if self._tema_atual == TEMA_ESCURO else TEMA_ESCURO
        settings_mod.definir_tema(self._tema_atual)
        QApplication.instance().setStyleSheet(build_stylesheet(self._tema_atual))
        self._atualizar_botao_tema()

    def _atualizar_botao_tema(self) -> None:
        # o botao mostra a ACAO (pra que tema ele muda ao clicar), nao o tema atual
        if self._tema_atual == TEMA_ESCURO:
            self._botao_tema.definir_icone("sol")
            self._botao_tema.definir_rotulo("Modo Claro")
            self._botao_tema.setToolTip("Mudar para o tema claro")
        else:
            self._botao_tema.definir_icone("lua")
            self._botao_tema.definir_rotulo("Modo Escuro")
            self._botao_tema.setToolTip("Mudar para o tema escuro")
