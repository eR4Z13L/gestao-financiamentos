"""Tela Dashboard de Propostas.

Tudo calculado em tempo real a partir da planilha (a regra esta em core/dashboard.py) - nada fica salvo, so
exibido. No topo ficam o titulo, o seletor de periodo e o botao "Recarregar", que rele os dados do zero (pro caso
do arquivo ter sido editado direto no Excel com o app aberto).

ADMIN ve, sem abas e cabendo numa janela de 1366x768: os 4 numeros das VENDAS do momento de agora (em andamento,
paradas, efetivadas no mes e com pendencias - NAO seguem o seletor de periodo; "Paradas" e "Com pendencias" levam
a tela Vendas ja filtrada), "Por banco" (segue o periodo: enviadas, aprovadas, negadas, em analise, taxa e a
demora para responder, mais a linha "Todos") e o resumo para copiar.
VENDEDOR ve so o dele (as propostas ja vem filtradas e a leitura dele nao tem as vendas): "minhas em analise",
"minhas aprovadas para efetivar", "meus clientes sem proposta", por banco (sem a demora: nao tem o historico) e o
resumo das propostas - nunca o nome de outro vendedor, nem os blocos que exigem escrever.

A tela nao navega sozinha: cada linha clicavel EMITE um sinal (`filtro_pedido`, `ficha_pedida`, `vendas_pedidas`) e a
janela principal leva a pessoa pra Todas as Propostas ja filtrada, pra Ficha ou pra Vendas.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core import clientes as clientes_mod
from core import dashboard as dashboard_mod
from core import data_store as bd
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import vendas as vendas_mod
from core.dashboard import FiltroDoDashboard
from core.formatting import formatar_reais, formatar_tempo
from desktop.screens.vendas_screen import FILTRO_COM_PENDENCIAS, FILTRO_PARADAS
from desktop.vigia_do_arquivo import VigiaDoArquivo
from desktop.widgets.botao_copiar import BotaoCopiar
from desktop.widgets.botao_recarregar import criar_botao_recarregar
from desktop.widgets.cartao_do_painel import CartaoDoPainel
from desktop.widgets.linha_clicavel import LinhaClicavel
from desktop.widgets.metric_card import MetricCard
from desktop.widgets.seletor_de_periodo import SeletorDePeriodo
from desktop.widgets.tabela_de_painel import COR_ERRO, Celula, TabelaDePainel

_MAXIMO_DE_LINHAS = 8  # nas listas curtas ("minhas...", clientes sem proposta); o resto vira "e mais N"
_COLUNAS_DE_BANCO = ["Banco", "Enviadas", "Aprovadas", "Negadas", "Em análise", "Taxa", "Demora para responder"]
_COLUNA_DA_DEMORA = 6
_ACAO_DOS_CARTOES = "Ver na tela Vendas →"
_LEGENDA_DA_DEMORA = "Mediana de dias entre o envio e a primeira resposta do banco registrada no histórico"


def _percentual(valor: float) -> str:
    return f"{valor:.1f}".replace(".", ",") + "%"


class DashboardScreen(QWidget):
    filtro_pedido = Signal(object)  # FiltroDoDashboard: abrir Todas as Propostas so com isso
    ficha_pedida = Signal(str)  # cpf: abrir a Ficha desse cliente
    vendas_pedidas = Signal(str)  # o nome do filtro da tela Vendas (vendas_screen.FILTRO_*): abrir Vendas so com isso

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._vendedor = sessao_mod.eh_vendedor()
        self._periodo = dashboard_mod.PERIODO_PADRAO
        self._propostas = pd.DataFrame(columns=bd.PROPOSTAS_COLUNAS)
        self._clientes = pd.DataFrame(columns=bd.CLIENTES_COLUNAS)
        self._vendas: list[vendas_mod.ResumoDaVenda] = []
        self._historico: pd.DataFrame | None = None
        self._no_periodo = self._propostas
        self._intervalo = None
        self._numeros: dashboard_mod.NumerosDasVendas | None = None
        self._texto_do_resumo = ""
        self._desatualizado = False
        self._vigia = VigiaDoArquivo()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        layout.addLayout(self._construir_cabecalho())

        self._rolagem = QScrollArea()
        self._rolagem.setWidgetResizable(True)
        self._rolagem.setFrameShape(QFrame.Shape.NoFrame)
        self._rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        conteudo = QWidget()
        conteudo.setProperty("role", "transparente")
        self._rolagem.setWidget(conteudo)
        layout.addWidget(self._rolagem, stretch=1)

        corpo = QVBoxLayout(conteudo)
        corpo.setContentsMargins(0, 0, 12, 0)  # a folga da direita e da barra de rolagem
        corpo.setSpacing(16)
        self._construir_blocos()
        if self._vendedor:
            corpo.addLayout(self._construir_blocos_do_vendedor())
        else:
            corpo.addLayout(self._construir_topo())
        corpo.addWidget(self._cartao_bancos)
        corpo.addWidget(self._cartao_resumo)
        corpo.addStretch(1)

        self._carregar_dados()

    # -- construcao ---------------------------------------------------------------------

    def _construir_cabecalho(self) -> QHBoxLayout:
        cabecalho = QHBoxLayout()
        cabecalho.setSpacing(12)
        titulo = QLabel("📊 Dashboard de Propostas")
        titulo.setProperty("role", "titulo")
        cabecalho.addWidget(titulo)
        cabecalho.addStretch()
        self._seletor = SeletorDePeriodo(self._periodo)
        self._seletor.setToolTip("O período vale para \"Por banco\" e para o resumo. Os números das vendas são sempre os de agora.")
        self._seletor.periodo_alterado.connect(self._ao_mudar_periodo)
        cabecalho.addWidget(self._seletor)
        cabecalho.addWidget(criar_botao_recarregar(self._carregar_dados))
        return cabecalho

    def _construir_topo(self) -> QHBoxLayout:
        """Os 4 numeros das vendas (ADMIN): o momento de agora, sem seguir o periodo."""
        dias = propostas_mod.DIAS_PROPOSTA_PARADA
        topo = QHBoxLayout()
        topo.setSpacing(16)
        self._card_andamento = MetricCard("Vendas em andamento")
        self._card_paradas = MetricCard(f"Paradas há {dias}+ dias")
        self._card_efetivadas = MetricCard("Efetivadas no mês")
        self._card_pendencias = MetricCard("Com pendências")
        self._card_andamento.setToolTip("Vendas que aguardam resposta dos bancos ou já têm banco fechado e ainda não efetivaram. O valor é a soma das propostas dos bancos fechados.")
        self._card_paradas.setToolTip(f"Vendas aguardando bancos, ou com banco fechado parado na mesma etapa, há {dias} dias ou mais (a mesma regra da tela Vendas).")
        self._card_efetivadas.setToolTip("Vendas que viraram Efetivadas neste mês (a contar da última mudança de status da venda).")
        self._card_pendencias.setToolTip("Vendas, de qualquer status, com alguma pendência aberta (ex.: equipamento ainda não entregue).")
        self._card_paradas.tornar_clicavel(_ACAO_DOS_CARTOES)
        self._card_pendencias.tornar_clicavel(_ACAO_DOS_CARTOES)
        self._card_paradas.clicado.connect(lambda: self.vendas_pedidas.emit(FILTRO_PARADAS))
        self._card_pendencias.clicado.connect(lambda: self.vendas_pedidas.emit(FILTRO_COM_PENDENCIAS))
        for card in (self._card_andamento, self._card_paradas, self._card_efetivadas, self._card_pendencias):
            topo.addWidget(card, 1)
        return topo

    def _construir_blocos(self) -> None:
        """Por banco e Resumo: os dois papeis tem."""
        self._cartao_bancos = CartaoDoPainel(
            "Por banco",
            "Segue o período escolhido. Taxa = aprovadas ÷ (aprovadas + negadas). "
            + ("" if self._vendedor else "Demora = mediana de dias até o banco responder. ")
            + "Clique numa linha para ver as propostas do banco.",
        )
        self._tabela_bancos = TabelaDePainel(_COLUNAS_DE_BANCO, coluna_da_barra=5, colunas_a_direita=(1, 2, 3, 4, 5, 6))
        self._tabela_bancos.linha_clicada.connect(self._pedir_filtro_de_banco)
        self._tabela_bancos.setColumnHidden(_COLUNA_DA_DEMORA, self._vendedor)  # a leitura do vendedor nao tem o historico
        self._cartao_bancos.corpo.addWidget(self._tabela_bancos)

        self._cartao_resumo = CartaoDoPainel("Resumo para copiar")
        linha_do_resumo = QHBoxLayout()
        linha_do_resumo.setSpacing(8)
        self._rotulo_do_resumo = QLabel("")
        self._rotulo_do_resumo.setWordWrap(True)
        self._rotulo_do_resumo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        linha_do_resumo.addWidget(self._rotulo_do_resumo, stretch=1)
        self._botao_copiar_resumo = BotaoCopiar(lambda: self._texto_do_resumo)
        linha_do_resumo.addWidget(self._botao_copiar_resumo, alignment=Qt.AlignmentFlag.AlignTop)
        self._cartao_resumo.corpo.addLayout(linha_do_resumo)

    def _construir_blocos_do_vendedor(self) -> QGridLayout:
        self._cartao_minhas_em_analise = CartaoDoPainel("Minhas em análise")
        self._cartao_minhas_a_efetivar = CartaoDoPainel("Minhas aprovadas para efetivar")
        self._cartao_meus_clientes = CartaoDoPainel("Meus clientes sem proposta", "De todos os períodos: clique para abrir a ficha")
        self._botao_ver_em_analise = self._criar_botao_de_ver_todas(propostas_mod.ETAPA_EM_ANALISE)
        self._botao_ver_a_efetivar = self._criar_botao_de_ver_todas(propostas_mod.ETAPA_APROVADO)
        self._cartao_minhas_em_analise.adicionar_acao(self._botao_ver_em_analise)
        self._cartao_minhas_a_efetivar.adicionar_acao(self._botao_ver_a_efetivar)

        grade = QGridLayout()
        grade.setHorizontalSpacing(16)
        grade.setVerticalSpacing(16)
        grade.setColumnStretch(0, 1)
        grade.setColumnStretch(1, 1)
        grade.addWidget(self._cartao_minhas_em_analise, 0, 0)
        grade.addWidget(self._cartao_minhas_a_efetivar, 0, 1)
        grade.addWidget(self._cartao_meus_clientes, 1, 0, 1, 2)
        return grade

    def _criar_botao_de_ver_todas(self, etapa: str) -> QPushButton:
        botao = QPushButton("Ver todas")
        botao.setProperty("role", "botao_link")
        botao.setCursor(Qt.CursorShape.PointingHandCursor)
        botao.clicked.connect(lambda _=False: self._pedir_filtro_de_etapa(etapa))
        return botao

    # -- carregamento -----------------------------------------------------------------------

    def _hoje(self) -> date:
        return date.today()

    def marcar_como_desatualizado(self) -> None:
        """Alguma proposta mudou em outra tela: na proxima vez que o Dashboard aparecer, le tudo de novo."""
        self._desatualizado = True

    def showEvent(self, evento) -> None:
        super().showEvent(evento)
        if self._desatualizado or self._vigia.mudou_desde_a_leitura():
            self._carregar_dados()

    def recarregar_se_mudou(self) -> None:
        """Chamado a cada tique da janela com esta tela aberta: planilha mudou por fora -> rele."""
        if self._vigia.mudou_desde_a_leitura():
            self._carregar_dados()

    def _carregar_dados(self, *_args) -> None:
        self._vigia.registrar_leitura()
        try:
            propostas = propostas_mod.listar_propostas()
            clientes = clientes_mod.listar_clientes() if self._vendedor else self._clientes
            # o VENDEDOR le da nuvem, sem as vendas nem o historico
            vendas = [] if self._vendedor else vendas_mod.listar_vendas(self._hoje())
            historico = None if self._vendedor else bd.ler_historico(propostas_mod.CAMINHO_XLSX)
        except FileNotFoundError:
            QMessageBox.critical(
                self,
                "Arquivo não encontrado",
                "Não foi possível encontrar o arquivo de dados (.xlsx). Confira o caminho configurado em config.py.",
            )
            return
        except Exception as exc:  # arquivo corrompido, formato inesperado, etc. - nunca falhar em silencio
            QMessageBox.critical(self, "Erro ao carregar dados", str(exc))
            return
        self._propostas = propostas
        self._clientes = clientes
        self._vendas = vendas
        self._historico = historico
        self._desatualizado = False
        self._atualizar()

    def _ao_mudar_periodo(self, periodo: str) -> None:
        if periodo != self._periodo:
            self._periodo = periodo
            self._atualizar()

    def periodo(self) -> str:
        return self._periodo

    def definir_periodo(self, periodo: str) -> None:
        """Muda o periodo (como clicar no botao dele) e refaz os blocos que o seguem."""
        self._seletor.definir_periodo(periodo)
        self._ao_mudar_periodo(periodo)

    def _atualizar(self) -> None:
        hoje = self._hoje()
        self._intervalo = dashboard_mod.intervalo_do_periodo(self._periodo, hoje)
        self._no_periodo = dashboard_mod.filtrar_por_periodo(self._propostas, self._intervalo)
        bancos, total = self._atualizar_bancos()
        if self._vendedor:
            self._texto_do_resumo = dashboard_mod.resumo_para_copiar(self._no_periodo, self._periodo)
            self._atualizar_listas_do_vendedor()
        else:
            self._numeros = dashboard_mod.numeros_das_vendas(self._vendas, hoje, self._historico)
            self._atualizar_topo(self._numeros)
            self._texto_do_resumo = dashboard_mod.resumo_das_vendas_para_copiar(self._numeros, bancos, total, self._periodo, hoje)
        self._rotulo_do_resumo.setText(self._texto_do_resumo)

    # -- os 4 numeros das vendas ---------------------------------------------------------------

    def _atualizar_topo(self, n: dashboard_mod.NumerosDasVendas) -> None:
        self._card_andamento.definir_valor(str(n.em_andamento))
        if not n.em_andamento:
            self._card_andamento.definir_detalhe("Nenhuma venda em andamento")
        else:
            detalhe = f"{formatar_reais(n.valor_em_andamento)} em propostas fechadas"
            if n.fechadas_sem_valor:
                detalhe += f" · {n.fechadas_sem_valor} sem valor"
            self._card_andamento.definir_detalhe(detalhe, aviso=bool(n.fechadas_sem_valor))

        self._card_paradas.definir_valor(str(n.paradas))
        self._card_paradas.definir_valor_em_aviso(n.paradas > 0)
        self._card_paradas.definir_detalhe("Precisam de atenção" if n.paradas else "Nenhuma venda parada", aviso=n.paradas > 0)

        self._card_efetivadas.definir_valor(str(n.efetivadas_no_mes))
        if not n.efetivadas_no_mes:
            detalhe, aviso = "Nenhuma venda efetivada neste mês", False
        else:
            detalhe, aviso = formatar_reais(n.valor_efetivadas_no_mes), bool(n.efetivadas_sem_valor)
            if n.efetivadas_sem_valor:
                detalhe += f" · {n.efetivadas_sem_valor} sem valor"
        if n.efetivadas_sem_data:
            detalhe += f" · {n.efetivadas_sem_data} sem data de efetivação (fora da conta)"
            aviso = True
        self._card_efetivadas.definir_detalhe(detalhe, aviso=aviso)

        self._card_pendencias.definir_valor(str(n.com_pendencias))
        if n.com_pendencias_ilegiveis:
            self._card_pendencias.definir_detalhe(f"{n.com_pendencias_ilegiveis} venda(s) com a pendência ilegível (fora da conta)", aviso=True)
        else:
            self._card_pendencias.definir_detalhe("" if n.com_pendencias else "Nenhuma pendência aberta")

    # -- por banco ------------------------------------------------------------------------------

    def _atualizar_bancos(self) -> tuple[pd.DataFrame, dict]:
        bancos = dashboard_mod.por_banco(self._no_periodo, self._historico)
        total = dashboard_mod.total_por_banco(self._no_periodo, self._historico)
        linhas = []
        for _, b in bancos.iterrows():
            aviso = b["Aviso"]
            explicacao = dashboard_mod.TEXTO_DO_AVISO_DE_BANCO.get(aviso, "")
            celulas = [
                Celula(b["Banco"], tooltip=explicacao or b["Banco"], cor=(COR_ERRO if aviso in (dashboard_mod.AVISO_NAO_E_BANCO, dashboard_mod.AVISO_SEM_BANCO) else None)),
                *self._celulas_dos_numeros(b),
            ]
            linhas.append(((dashboard_mod.chave_do_banco(b["Banco"]), b["Banco"]), celulas))
        rodape = [Celula("Todos", tooltip="Todas as propostas do período, com ou sem banco informado"), *self._celulas_dos_numeros(total)]
        self._tabela_bancos.definir_linhas(linhas, ordenar_por=1, decrescente=True, rodape=rodape)
        return bancos, total

    @staticmethod
    def _celulas_dos_numeros(dados) -> list[Celula]:
        """Enviadas, Aprovadas, Negadas, Em analise, Taxa e Demora de uma linha de por_banco (ou do total)."""
        taxa = dados["Taxa (%)"]
        tem_taxa = taxa is not None and not pd.isna(taxa)
        demora = dados["Demora (dias)"]
        tem_demora = demora is not None and not pd.isna(demora)
        return [
            Celula(str(dados["Enviadas"]), float(dados["Enviadas"]), a_direita=True),
            Celula(str(dados["Aprovadas"]), float(dados["Aprovadas"]), a_direita=True),
            Celula(str(dados["Negadas"]), float(dados["Negadas"]), a_direita=True),
            Celula(str(dados["Em Análise"]), float(dados["Em Análise"]), a_direita=True),
            Celula(
                _percentual(taxa) if tem_taxa else "—",
                float(taxa) if tem_taxa else -1.0,
                tooltip="Aprovadas ÷ (aprovadas + negadas)" if tem_taxa else "Fora da taxa",
                barra=taxa / 100 if tem_taxa else None,
                a_direita=True,
            ),
            Celula(
                dashboard_mod.texto_da_demora(demora if tem_demora else None),
                float(demora) if tem_demora else -1.0,
                tooltip=_LEGENDA_DA_DEMORA if tem_demora else "Nenhuma resposta registrada no histórico",
                a_direita=True,
            ),
        ]

    # -- visao do vendedor -----------------------------------------------------------------------------------

    def _atualizar_listas_do_vendedor(self) -> None:
        for cartao, botao, etapa, vazio in (
            (self._cartao_minhas_em_analise, self._botao_ver_em_analise, propostas_mod.ETAPA_EM_ANALISE, "Nenhuma proposta em análise"),
            (self._cartao_minhas_a_efetivar, self._botao_ver_a_efetivar, propostas_mod.ETAPA_APROVADO, "Nenhuma proposta aprovada aguardando efetivação"),
        ):
            itens = dashboard_mod.propostas_da_etapa(self._no_periodo, etapa)
            botao.setText(f"Ver todas ({len(itens)})")
            botao.setVisible(bool(itens))
            cartao.limpar_corpo()
            if not itens:
                cartao.corpo.addWidget(self._mensagem_secundaria(vazio))
                continue
            for p in itens[:_MAXIMO_DE_LINHAS]:
                valor = formatar_reais(p.valor) if p.valor is not None else ""
                # a linha mostra o que cabe (cliente, valor, ha quanto tempo); o equipamento e o banco vao no tooltip
                curto = [p.cliente or "(sem cadastro)", valor, formatar_tempo(p.tempo)]
                completo = [p.cliente or "(sem cadastro)", p.equipamento, valor, p.banco, formatar_tempo(p.tempo)]
                linha = LinhaClicavel(" · ".join(x for x in curto if x), dashboard_mod.TOM_PROCESSO)
                linha.setToolTip(" · ".join(x for x in completo if x))
                linha.clicked.connect(lambda _=False, cpf=p.cpf: self.ficha_pedida.emit(cpf))
                cartao.corpo.addWidget(linha)
            if len(itens) > _MAXIMO_DE_LINHAS:
                cartao.corpo.addWidget(self._mensagem_secundaria(f"e mais {len(itens) - _MAXIMO_DE_LINHAS} — clique em \"Ver todas\""))

        self._cartao_meus_clientes.limpar_corpo()
        sem_proposta = dashboard_mod.clientes_sem_proposta(self._clientes, self._propostas)
        if not sem_proposta:
            self._cartao_meus_clientes.corpo.addWidget(self._mensagem_secundaria("Todos os seus clientes têm proposta"))
            return
        for cpf, nome in sem_proposta[:_MAXIMO_DE_LINHAS]:
            linha = LinhaClicavel(nome)
            linha.clicked.connect(lambda _=False, c=cpf: self.ficha_pedida.emit(c))
            self._cartao_meus_clientes.corpo.addWidget(linha)
        if len(sem_proposta) > _MAXIMO_DE_LINHAS:
            self._cartao_meus_clientes.corpo.addWidget(self._mensagem_secundaria(f"e mais {len(sem_proposta) - _MAXIMO_DE_LINHAS} — veja todos na Ficha de Cliente"))

    @staticmethod
    def _mensagem_secundaria(texto: str) -> QLabel:
        rotulo = QLabel(texto)
        rotulo.setProperty("role", "secundario")
        rotulo.setWordWrap(True)
        return rotulo

    # -- pedidos de navegacao -------------------------------------------------------------------------------

    def _filtro(self, chave: str, rotulo: str, parametro: str = "", dias: int | None = None) -> FiltroDoDashboard:
        de, ate = (None, None) if self._intervalo is None else self._intervalo
        return FiltroDoDashboard(chave, rotulo, parametro, dias, de, ate)

    def _pedir_filtro_de_etapa(self, etapa: str) -> None:
        self.filtro_pedido.emit(self._filtro(dashboard_mod.FILTRO_ETAPA, dashboard_mod.rotulo_do_filtro_de_etapa(etapa), parametro=etapa))

    def _pedir_filtro_de_banco(self, payload: tuple[str, str]) -> None:
        chave, nome = payload
        if chave == "":
            self.filtro_pedido.emit(self._filtro(dashboard_mod.FILTRO_SEM_BANCO, "Sem banco informado"))
        else:
            self.filtro_pedido.emit(self._filtro(dashboard_mod.FILTRO_BANCO, f"Banco: {nome}", parametro=chave))
