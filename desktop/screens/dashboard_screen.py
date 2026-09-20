"""Tela Dashboard de Propostas.

Tudo calculado em tempo real a partir de CLIENTES e PROPOSTAS (a regra esta em core/dashboard.py) -
nada fica salvo, so exibido. A pagina rola; no topo ficam o titulo, o seletor de periodo (que vale pra
TODOS os blocos) e o botao "Atualizar", que rele os dados do zero (pro caso do arquivo ter sido editado
direto no Excel com o app aberto).

ADMIN ve: os numeros do topo, "Precisa de atencao", o funil por etapa, o desempenho por banco, os clientes
"Para reenviar", a qualidade dos dados, o resumo para copiar e o desempenho por vendedor.
VENDEDOR ve so o dele (as propostas ja vem filtradas): os numeros do topo, "minhas em analise", "minhas
aprovadas para efetivar", "meus clientes sem proposta", o funil, o desempenho por banco e o resumo -
nunca o nome de outro vendedor, nem os blocos de correcao de dados e de reenvio (que exigem escrever).

A tela nao navega sozinha: cada linha clicavel EMITE um sinal (`filtro_pedido`, `ficha_pedida`,
`duplicacao_pedida`) e a janela principal leva a pessoa pra Todas as Propostas ja filtrada ou pra Ficha.
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
from core.dashboard import FiltroDoDashboard
from core.formatting import formatar_reais, formatar_tempo
from desktop.widgets.botao_copiar import BotaoCopiar
from desktop.widgets.cartao_do_painel import CartaoDoPainel
from desktop.widgets.funil_de_etapas import FunilDeEtapas
from desktop.widgets.linha_clicavel import LinhaClicavel
from desktop.widgets.linha_de_qualidade import LinhaDeQualidade
from desktop.widgets.linha_para_reenviar import LinhaParaReenviar
from desktop.widgets.metric_card import MetricCard
from desktop.widgets.seletor_de_periodo import SeletorDePeriodo
from desktop.widgets.tabela_de_painel import COR_AVISO, COR_ERRO, Celula, TabelaDePainel

_MAXIMO_DE_LINHAS = 8  # nas listas curtas (para reenviar, "minhas...", clientes sem proposta); o resto vira "e mais N"
_ROTULOS_DE_PENDENTES = {
    dashboard_mod.ATENCAO_SEM_VALOR: "Sem valor preenchido",
    dashboard_mod.FILTRO_SEM_MESES: "Sem meses preenchido",
    dashboard_mod.FILTRO_SEM_BANCO: "Sem banco informado",
    dashboard_mod.FILTRO_SEM_STATUS: "Sem status",
}
_AVISO_CURTO_DE_BANCO = {
    dashboard_mod.AVISO_SEM_APROVACAO: "Sem aprovações",
    dashboard_mod.AVISO_NAO_E_BANCO: "Revisar",
    dashboard_mod.AVISO_SEM_BANCO: "Revisar",
}
_COLUNAS_DE_BANCO = ["Banco", "Enviadas", "Aprovadas", "Negadas", "Em análise", "Taxa", "Aviso"]
_COLUNAS_DE_VENDEDOR = ["Vendedor", "Total", "Em análise", "Aprovadas", "Negadas", "Taxa", "A efetivar", "Valor aprovado"]


def _percentual(valor: float) -> str:
    return f"{valor:.1f}".replace(".", ",") + "%"


def _diferenca(valor: float, unidade: str, referencia: str, casas: int = 0) -> str:
    """"▲ +3 vs. os 7 dias anteriores" / "▼ -2 ..." / "= sem mudança vs. ..." (o sinal e a seta dizem o sentido, sem julgar
    se e bom ou ruim: mais propostas em analise nao e nem uma coisa nem outra)."""
    if abs(valor) < 10 ** -casas / 2:
        return f"= sem mudança vs. {referencia}"
    seta = "▲" if valor > 0 else "▼"
    numero = f"{valor:+.{casas}f}".replace(".", ",")
    return f"{seta} {numero}{unidade} vs. {referencia}"


class DashboardScreen(QWidget):
    filtro_pedido = Signal(object)  # FiltroDoDashboard: abrir Todas as Propostas so com isso
    ficha_pedida = Signal(str)  # cpf: abrir a Ficha desse cliente
    duplicacao_pedida = Signal(str, int)  # cpf, posicao real da proposta: Ficha com "Nova proposta" a partir dela

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._vendedor = sessao_mod.eh_vendedor()
        self._periodo = dashboard_mod.PERIODO_PADRAO
        self._propostas = pd.DataFrame(columns=bd.PROPOSTAS_COLUNAS)
        self._clientes = pd.DataFrame(columns=bd.CLIENTES_COLUNAS)
        self._no_periodo = self._propostas
        self._intervalo = None
        self._texto_do_resumo = ""
        self._desatualizado = False

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
        corpo.addLayout(self._construir_topo())
        corpo.addLayout(self._construir_grade())
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
        self._seletor.periodo_alterado.connect(self._ao_mudar_periodo)
        cabecalho.addWidget(self._seletor)
        botao_atualizar = QPushButton("Atualizar")
        botao_atualizar.setProperty("role", "botao_primario")
        botao_atualizar.clicked.connect(self._carregar_dados)
        cabecalho.addWidget(botao_atualizar)
        return cabecalho

    def _construir_topo(self) -> QHBoxLayout:
        topo = QHBoxLayout()
        topo.setSpacing(16)
        self._card_em_analise = MetricCard("Em análise")
        self._card_a_efetivar = MetricCard("Aprovadas a efetivar")
        self._card_taxa = MetricCard("Taxa de aprovação")
        self._card_mediano = MetricCard("Valor mediano")
        self._card_a_efetivar.setToolTip("Propostas com status \"Aprovado\" que ainda não viraram \"Efetivado\" (a compra ainda não foi concluída).")
        self._card_taxa.setToolTip("Aprovadas ÷ (aprovadas + negadas). \"Aprovada\" conta todas as etapas positivas (aprovado, pré-aprovado, nota fiscal, garantia e efetivado). Propostas em análise ainda não entram na conta.")
        self._card_mediano.setToolTip("Metade das propostas com valor está acima dele e metade abaixo. Ao contrário da soma, um valor muito alto (ou de teste) não o distorce.")
        for card in (self._card_em_analise, self._card_a_efetivar, self._card_taxa, self._card_mediano):
            topo.addWidget(card, 1)
        return topo

    def _construir_grade(self) -> QGridLayout:
        grade = QGridLayout()
        grade.setHorizontalSpacing(16)
        grade.setVerticalSpacing(16)
        grade.setColumnStretch(0, 1)
        grade.setColumnStretch(1, 1)

        self._cartao_funil = CartaoDoPainel("Funil por etapa", "Clique numa etapa para ver as propostas dela")
        self._funil = FunilDeEtapas()
        self._funil.etapa_clicada.connect(self._pedir_filtro_de_etapa)
        self._cartao_funil.corpo.addWidget(self._funil)

        self._cartao_bancos = CartaoDoPainel(
            "Por banco",
            "Taxa = aprovadas ÷ (aprovadas + negadas). Clique no cabeçalho para ordenar e numa linha para ver as propostas do banco.",
        )
        self._tabela_bancos = TabelaDePainel(_COLUNAS_DE_BANCO, coluna_da_barra=5, colunas_a_direita=(1, 2, 3, 4, 5))
        self._tabela_bancos.linha_clicada.connect(self._pedir_filtro_de_banco)
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

        if self._vendedor:
            self._construir_blocos_do_vendedor(grade)
        else:
            self._construir_blocos_do_admin(grade)
        return grade

    def _construir_blocos_do_admin(self, grade: QGridLayout) -> None:
        self._cartao_atencao = CartaoDoPainel("Precisa de atenção", "Clique para ver as propostas")
        self._cartao_reenviar = CartaoDoPainel("Para reenviar", "Clientes cujas propostas foram todas negadas")
        self._cartao_qualidade = CartaoDoPainel("Qualidade dos dados", "Quanto das propostas tem cada campo preenchido")
        self._cartao_vendedores = CartaoDoPainel("Por vendedor", "Clique no cabeçalho para ordenar")
        self._tabela_vendedores = TabelaDePainel(_COLUNAS_DE_VENDEDOR, colunas_a_direita=(1, 2, 3, 4, 5, 6, 7))
        self._cartao_vendedores.corpo.addWidget(self._tabela_vendedores)

        direita = QVBoxLayout()
        direita.setSpacing(16)
        direita.addWidget(self._cartao_qualidade)
        direita.addWidget(self._cartao_resumo)
        direita.addStretch(1)  # a sobra de altura (o cartao da esquerda e mais alto) fica embaixo, nao dentro dos cartoes

        grade.addWidget(self._cartao_atencao, 0, 0)
        grade.addWidget(self._cartao_funil, 0, 1)
        grade.addWidget(self._cartao_bancos, 1, 0, 1, 2)
        grade.addWidget(self._cartao_reenviar, 2, 0)
        grade.addLayout(direita, 2, 1)
        grade.addWidget(self._cartao_vendedores, 3, 0, 1, 2)

    def _construir_blocos_do_vendedor(self, grade: QGridLayout) -> None:
        self._cartao_minhas_em_analise = CartaoDoPainel("Minhas em análise")
        self._cartao_minhas_a_efetivar = CartaoDoPainel("Minhas aprovadas para efetivar")
        self._cartao_meus_clientes = CartaoDoPainel("Meus clientes sem proposta", "De todos os períodos: clique para abrir a ficha")
        self._botao_ver_em_analise = self._criar_botao_de_ver_todas(propostas_mod.ETAPA_EM_ANALISE)
        self._botao_ver_a_efetivar = self._criar_botao_de_ver_todas(propostas_mod.ETAPA_APROVADO)
        self._cartao_minhas_em_analise.adicionar_acao(self._botao_ver_em_analise)
        self._cartao_minhas_a_efetivar.adicionar_acao(self._botao_ver_a_efetivar)

        grade.addWidget(self._cartao_minhas_em_analise, 0, 0)
        grade.addWidget(self._cartao_minhas_a_efetivar, 0, 1)
        grade.addWidget(self._cartao_meus_clientes, 1, 0)
        grade.addWidget(self._cartao_funil, 1, 1)
        grade.addWidget(self._cartao_bancos, 2, 0, 1, 2)
        grade.addWidget(self._cartao_resumo, 3, 0, 1, 2)

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
        if self._desatualizado:
            self._carregar_dados()

    def _carregar_dados(self, *_args) -> None:
        try:
            propostas = propostas_mod.listar_propostas()
            clientes = clientes_mod.listar_clientes() if self._vendedor else self._clientes
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
        self._desatualizado = False
        self._atualizar()

    def _ao_mudar_periodo(self, periodo: str) -> None:
        if periodo != self._periodo:
            self._periodo = periodo
            self._atualizar()

    def periodo(self) -> str:
        return self._periodo

    def definir_periodo(self, periodo: str) -> None:
        """Muda o periodo (como clicar no botao dele) e refaz todos os blocos."""
        self._seletor.definir_periodo(periodo)
        self._ao_mudar_periodo(periodo)

    def _atualizar(self) -> None:
        hoje = self._hoje()
        self._intervalo = dashboard_mod.intervalo_do_periodo(self._periodo, hoje)
        self._no_periodo = dashboard_mod.filtrar_por_periodo(self._propostas, self._intervalo)
        self._atualizar_topo(hoje)
        self._funil.definir_etapas(dashboard_mod.funil_por_etapa(self._no_periodo))
        self._atualizar_bancos()
        self._atualizar_resumo()
        if self._vendedor:
            self._atualizar_listas_do_vendedor()
        else:
            self._atualizar_atencao(hoje)
            self._atualizar_reenviar()
            self._atualizar_qualidade()
            self._atualizar_vendedores()

    # -- numeros do topo ----------------------------------------------------------------------

    def _atualizar_topo(self, hoje: date) -> None:
        topo = dashboard_mod.indicadores_do_topo(self._no_periodo)
        comparacao = None
        anterior = dashboard_mod.intervalo_anterior(self._periodo, hoje)
        if anterior is not None:
            comparacao = dashboard_mod.comparar_periodos(
                topo, dashboard_mod.indicadores_do_topo(dashboard_mod.filtrar_por_periodo(self._propostas, anterior))
            )
        referencia = dashboard_mod.descricao_do_periodo_anterior(self._periodo)

        em_analise = topo["em_analise"]
        self._card_em_analise.definir_valor(str(em_analise["quantidade"]))
        if not em_analise["quantidade"]:
            self._card_em_analise.definir_detalhe("Nenhuma proposta em análise")
        else:
            detalhe = formatar_reais(em_analise["valor"]) if em_analise["com_valor"] else "Nenhuma com valor"
            if 0 < em_analise["com_valor"] < em_analise["quantidade"]:
                detalhe += f" · só {em_analise['com_valor']} têm valor"
            self._card_em_analise.definir_detalhe(detalhe)

        a_efetivar = topo["a_efetivar"]
        self._card_a_efetivar.definir_valor(str(a_efetivar["quantidade"]))
        efetivadas = a_efetivar["efetivadas"]
        self._card_a_efetivar.definir_detalhe(
            f"{efetivadas} {'efetivada' if efetivadas == 1 else 'efetivadas'} até agora", aviso=efetivadas == 0
        )

        taxa = topo["taxa_aprovacao"]
        if taxa["percentual"] is None:
            self._card_taxa.definir_valor("—")
            self._card_taxa.definir_detalhe("Nenhuma proposta decidida")
        else:
            self._card_taxa.definir_valor(_percentual(taxa["percentual"]))
            self._card_taxa.definir_detalhe(f"{taxa['aprovadas']} de {taxa['decididas']} decididas")

        mediano = topo["valor_mediano"]
        self._card_mediano.definir_valor(formatar_reais(mediano["mediana"]) if mediano["mediana"] is not None else "—")
        self._card_mediano.definir_detalhe(f"{mediano['com_valor']} de {mediano['total']} com valor")

        for card, chave, unidade, casas in (
            (self._card_em_analise, "em_analise", "", 0),
            (self._card_a_efetivar, "a_efetivar", "", 0),
            (self._card_taxa, "taxa_aprovacao", " p.p.", 1),
            (self._card_mediano, "valor_mediano", "%", 0),
        ):
            diferenca = None if comparacao is None else comparacao[chave]
            card.definir_comparacao("" if diferenca is None else _diferenca(diferenca, unidade, referencia, casas))

    # -- precisa de atencao -------------------------------------------------------------------

    def _atualizar_atencao(self, hoje: date) -> None:
        self._cartao_atencao.limpar_corpo()
        itens = dashboard_mod.precisa_de_atencao(self._no_periodo, hoje=hoje)
        if not itens:
            quando = dashboard_mod.descricao_do_periodo(self._periodo)
            mensagem = QLabel(f"Tudo em dia: nenhuma proposta pedindo atenção{' ' + quando if quando else ''}.")
            mensagem.setProperty("role", "positivo")
            mensagem.setWordWrap(True)
            self._cartao_atencao.corpo.addWidget(mensagem)
            return
        for item in itens:
            linha = LinhaClicavel(item.texto, item.tom)
            linha.clicked.connect(lambda _=False, i=item: self._pedir_filtro_de_atencao(i))
            self._cartao_atencao.corpo.addWidget(linha)

    # -- por banco ------------------------------------------------------------------------------

    def _atualizar_bancos(self) -> None:
        bancos = dashboard_mod.por_banco(self._no_periodo)
        linhas = []
        for _, b in bancos.iterrows():
            aviso = b["Aviso"]
            taxa = b["Taxa (%)"]
            tem_taxa = not pd.isna(taxa)
            explicacao = dashboard_mod.TEXTO_DO_AVISO_DE_BANCO.get(aviso, "")
            celulas = [
                Celula(b["Banco"], tooltip=explicacao or b["Banco"], cor=(COR_ERRO if aviso in (dashboard_mod.AVISO_NAO_E_BANCO, dashboard_mod.AVISO_SEM_BANCO) else None)),
                Celula(str(b["Enviadas"]), float(b["Enviadas"]), a_direita=True),
                Celula(str(b["Aprovadas"]), float(b["Aprovadas"]), a_direita=True),
                Celula(str(b["Negadas"]), float(b["Negadas"]), a_direita=True),
                Celula(str(b["Em Análise"]), float(b["Em Análise"]), a_direita=True),
                Celula(
                    _percentual(taxa) if tem_taxa else "—",
                    float(taxa) if tem_taxa else -1.0,
                    tooltip="Aprovadas ÷ (aprovadas + negadas)" if tem_taxa else "Fora da taxa",
                    barra=taxa / 100 if tem_taxa else None,
                    a_direita=True,
                ),
                Celula(
                    _AVISO_CURTO_DE_BANCO.get(aviso, ""),
                    tooltip=explicacao,
                    cor=COR_AVISO if aviso == dashboard_mod.AVISO_SEM_APROVACAO else COR_ERRO if aviso else None,
                ),
            ]
            linhas.append(((dashboard_mod.chave_do_banco(b["Banco"]), b["Banco"]), celulas))
        self._tabela_bancos.definir_linhas(linhas, ordenar_por=1, decrescente=True)

    # -- resumo para copiar -----------------------------------------------------------------------

    def _atualizar_resumo(self) -> None:
        self._texto_do_resumo = dashboard_mod.resumo_para_copiar(self._no_periodo, self._periodo)
        self._rotulo_do_resumo.setText(self._texto_do_resumo)

    # -- para reenviar ------------------------------------------------------------------------------

    def _atualizar_reenviar(self) -> None:
        cartao = self._cartao_reenviar
        cartao.limpar_corpo()
        itens = dashboard_mod.para_reenviar(self._propostas, self._intervalo)
        quando = dashboard_mod.descricao_do_periodo(self._periodo)
        if not itens:
            cartao.definir_legenda("Clientes cujas propostas foram todas negadas")
            mensagem = QLabel(f"Nenhum cliente com todas as propostas negadas{' ' + quando if quando else ''}.")
            mensagem.setProperty("role", "secundario")
            mensagem.setWordWrap(True)
            cartao.corpo.addWidget(mensagem)
            return
        cartao.definir_legenda(f"{len(itens)} cliente{'s' if len(itens) > 1 else ''} com todas as propostas negadas · Duplicar abre a ficha com uma nova proposta")
        for item in itens[:_MAXIMO_DE_LINHAS]:
            linha = LinhaParaReenviar(item)
            linha.duplicar_pedido.connect(self.duplicacao_pedida)
            linha.ficha_pedida.connect(self.ficha_pedida)
            cartao.corpo.addWidget(linha)
        if len(itens) > _MAXIMO_DE_LINHAS:
            resto = QLabel(f"e mais {len(itens) - _MAXIMO_DE_LINHAS} — use o filtro de status \"Negado\" em Todas as Propostas")
            resto.setProperty("role", "secundario")
            resto.setWordWrap(True)
            cartao.corpo.addWidget(resto)

    # -- qualidade dos dados --------------------------------------------------------------------------

    def _atualizar_qualidade(self) -> None:
        self._cartao_qualidade.limpar_corpo()
        for campo in dashboard_mod.qualidade_dos_dados(self._no_periodo):
            linha = LinhaDeQualidade(campo)
            linha.pendentes_pedidas.connect(self._pedir_filtro_de_pendentes)
            self._cartao_qualidade.corpo.addWidget(linha)

    # -- por vendedor ------------------------------------------------------------------------------------

    def _atualizar_vendedores(self) -> None:
        vendedores = dashboard_mod.por_vendedor(self._no_periodo)
        linhas = []
        for _, v in vendedores.iterrows():
            decididas = v["Aprovadas"] + v["Negadas"]
            taxa = v["Taxa Aprovação (%)"]
            celulas = [
                Celula(str(v["Vendedor"]), tooltip=str(v["Vendedor"])),
                Celula(str(v["Total"]), float(v["Total"]), a_direita=True),
                Celula(str(v["Em Análise"]), float(v["Em Análise"]), a_direita=True),
                Celula(str(v["Aprovadas"]), float(v["Aprovadas"]), a_direita=True),
                Celula(str(v["Negadas"]), float(v["Negadas"]), a_direita=True),
                Celula(_percentual(taxa) if decididas else "—", float(taxa) if decididas else -1.0, a_direita=True, tooltip="Aprovadas ÷ (aprovadas + negadas)"),
                Celula(str(v["Não Efetivadas"]), float(v["Não Efetivadas"]), a_direita=True, tooltip="Propostas com status \"Aprovado\" que ainda não viraram \"Efetivado\""),
                Celula(formatar_reais(v["Valor Aprovado (R$)"]), float(v["Valor Aprovado (R$)"]), a_direita=True),
            ]
            linhas.append((None, celulas))
        self._tabela_vendedores.definir_linhas(linhas, ordenar_por=1, decrescente=True)

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

    def _pedir_filtro_de_atencao(self, item: dashboard_mod.ItemDeAtencao) -> None:
        dias = propostas_mod.DIAS_PROPOSTA_PARADA if item.chave == dashboard_mod.ATENCAO_PARADAS else None
        self.filtro_pedido.emit(self._filtro(item.chave, item.rotulo_do_filtro, dias=dias))

    def _pedir_filtro_de_etapa(self, etapa: str) -> None:
        self.filtro_pedido.emit(self._filtro(dashboard_mod.FILTRO_ETAPA, dashboard_mod.rotulo_do_filtro_de_etapa(etapa), parametro=etapa))

    def _pedir_filtro_de_banco(self, payload: tuple[str, str]) -> None:
        chave, nome = payload
        if chave == "":
            self.filtro_pedido.emit(self._filtro(dashboard_mod.FILTRO_SEM_BANCO, "Sem banco informado"))
        else:
            self.filtro_pedido.emit(self._filtro(dashboard_mod.FILTRO_BANCO, f"Banco: {nome}", parametro=chave))

    def _pedir_filtro_de_pendentes(self, chave: str) -> None:
        self.filtro_pedido.emit(self._filtro(chave, _ROTULOS_DE_PENDENTES[chave]))
