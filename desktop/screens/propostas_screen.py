"""Tela Todas as Propostas: TODAS as propostas, um card por pedido a um banco (desenhado com o usuario em 04/10/2026).

Os cards sao os de desktop/widgets/lista_de_propostas.py (o mesmo da Ficha, nas propostas de antes das vendas), em
colunas que encaixam, como na tela Vendas: fechados, mostram o banco, o status com as mesmas acoes rapidas do card da
venda, o cliente, as condicoes e ha quanto tempo esperam a resposta; dois cliques abrem a propria proposta ali (o
formulario, "Ver na venda →" e "Abrir a ficha"). Excluir so de dentro do formulario, com confirmacao.

Os cards vem de 30 em 30 ("Carregar mais") e na ordenacao escolhida - ao abrir, as que esperam resposta ha mais
tempo primeiro. Busca livre, filtro de resposta (status), vendedor, banco, equipamento e periodo, todos combinados (a
regra esta em core/propostas.py), mais o filtro que vem do Dashboard. "+ Nova venda" cria a venda (a tela Vendas
mostra a criada).
"""

from __future__ import annotations

from collections import Counter
from typing import Mapping

import pandas as pd
from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core import dashboard as dashboard_mod
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import vendas as vendas_mod
from core import vendedores as vendedores_mod
from desktop.vigia_do_arquivo import VigiaDoArquivo
from desktop.widgets.botao_recarregar import criar_botao_recarregar
from desktop.widgets.campo_data import CampoData, ler_periodo
from desktop.widgets.lista_de_propostas import ListaDePropostas, chave_da_proposta
from desktop.widgets.lista_de_vendas import FaixaDeAviso

_COLUNAS_EXIBICAO = [
    "DATA", "VENDEDOR", "CLIENTE", "CPF", "EQUIPAMENTO", "BANCO",
    "VALOR (R$)", "MESES", "STATUS", "TEMPO", "OBSERVAÇÕES",
]
_FILTRO_TODOS = "Todos"
_MENSAGEM_VAZIA = "Nenhuma proposta encontrada com esses filtros."

# como cada etapa aparece na contagem do topo ("12 em análise · 5 aprovadas"):
# (singular, plural)
_FRASE_CONTAGEM = {
    propostas_mod.ETAPA_EM_ANALISE: ("em análise", "em análise"),
    propostas_mod.ETAPA_PRE_APROVADO: ("pré-aprovada", "pré-aprovadas"),
    propostas_mod.ETAPA_APROVADO: ("aprovada", "aprovadas"),
    propostas_mod.ETAPA_NF_ANEXADA: ("com nota fiscal anexada", "com nota fiscal anexada"),
    propostas_mod.ETAPA_GARANTIA_ASSINADA: ("com garantia assinada", "com garantia assinada"),
    propostas_mod.ETAPA_EFETIVADO: ("efetivada", "efetivadas"),
    propostas_mod.ETAPA_NAO_EFETIVADO: ("não efetivada", "não efetivadas"),
    propostas_mod.ETAPA_PROPOSTA_ENCERRADA: ("encerrada", "encerradas"),
    propostas_mod.ETAPA_NEGADO: ("negada", "negadas"),
    propostas_mod.ETAPA_DESCONHECIDA: ("com status não reconhecido", "com status não reconhecido"),
    propostas_mod.ETAPA_SEM_STATUS: ("sem status", "sem status"),
}


def resumo_por_etapa(contagem: Mapping[str, int]) -> str:
    """"12 em análise · 5 aprovadas · 1 negada": so as etapas que tem alguma
    proposta, na ordem do funil."""
    partes = []
    for etapa in propostas_mod.ETAPAS_EM_ORDEM:
        quantidade = contagem.get(etapa, 0)
        if quantidade:
            singular, plural = _FRASE_CONTAGEM[etapa]
            partes.append(f"{quantidade} {singular if quantidade == 1 else plural}")
    return " · ".join(partes)


class _ComboListaLarga(QComboBox):
    """Combo estreito (nomes de equipamento sao longos) cuja lista aberta mostra
    cada opcao inteira. No estilo do Windows a lista nasce com a largura do
    combo fechado e corta o nome. A largura e medida ao ABRIR a lista, com a
    fonte ja aplicada pelo tema - medir ao povoar o combo (antes de a tela
    aparecer) da uma fonte menor e uma lista curta demais."""

    def showPopup(self) -> None:
        medidor = self.fontMetrics()
        mais_larga = max((medidor.horizontalAdvance(self.itemText(i)) for i in range(self.count())), default=0)
        self.view().setMinimumWidth(mais_larga + 48)  # + margens do item e barra de rolagem
        super().showPopup()


class PropostasScreen(QWidget):
    # a tela leu (ou releu) as propostas: quem mostra algo derivado delas (o selo da barra
    # lateral) pode se atualizar. Sai depois de todo carregamento que deu certo.
    dados_atualizados = Signal()
    ficha_pedida = Signal(str)  # cpf ("Abrir a ficha" de um card aberto)
    venda_pedida = Signal(str, str)  # (ID_VENDA, ID_PROPOSTA) ("Ver na venda →")
    nova_venda_pedida = Signal()  # "+ Nova venda": a janela cria e mostra a venda na tela Vendas

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self._todas = pd.DataFrame(columns=_COLUNAS_EXIBICAO)  # dados crus; indice = posicao real no arquivo
        self._itens: dict[int, vendas_mod.PropostaNaLista] = {}  # o card de cada proposta, pelo indice
        self._vigia = VigiaDoArquivo()
        self._estado_periodo: tuple = (None, None, ())  # ultimo periodo aplicado (ver _ao_mudar_periodo)
        # o filtro que o Dashboard pediu (ex.: "em aberto ha mais de 7 dias"); vale junto com os demais
        self._filtro_dashboard: dashboard_mod.FiltroDoDashboard | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        cabecalho = QHBoxLayout()
        titulo = QLabel("📋 Todas as Propostas")
        titulo.setProperty("role", "titulo")
        cabecalho.addWidget(titulo)
        cabecalho.addStretch()
        cabecalho.addWidget(criar_botao_recarregar(self._ao_recarregar))
        self._botao_nova = QPushButton("+ Nova venda")
        self._botao_nova.setProperty("role", "botao_primario")
        self._botao_nova.setToolTip("Nova venda (cliente e equipamentos); os bancos entram depois, no card da venda")
        self._botao_nova.clicked.connect(self.nova_venda_pedida)
        cabecalho.addWidget(self._botao_nova)
        layout.addLayout(cabecalho)

        layout.addLayout(self._construir_linha_busca_e_ordenacao())
        layout.addLayout(self._construir_linha_filtros())
        self._chip_do_filtro = self._construir_chip_do_filtro()
        layout.addWidget(self._chip_do_filtro)

        # contagem ("59 proposta(s) · 21 em análise · ...")
        self._contador = QLabel("")
        self._contador.setProperty("role", "secundario")
        self._contador.setWordWrap(True)
        layout.addWidget(self._contador)

        conteudo = QWidget()
        conteudo.setProperty("role", "transparente")
        coluna = QVBoxLayout(conteudo)
        coluna.setContentsMargins(0, 0, 4, 0)
        self.rolagem = QScrollArea()
        self.rolagem.setWidgetResizable(True)
        self.rolagem.setFrameShape(QFrame.Shape.NoFrame)
        self.rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rolagem.setWidget(conteudo)
        self.lista = ListaDePropostas(self.rolagem, self._linha_da_proposta, conteudo)
        self.lista.gravou.connect(self._depois_de_gravar)
        self.lista.ficha_pedida.connect(self.ficha_pedida)
        self.lista.venda_pedida.connect(self.venda_pedida)
        coluna.addWidget(self.lista)
        coluna.addStretch()
        layout.addWidget(self.rolagem, stretch=1)

        self.faixa_aviso = FaixaDeAviso()
        layout.addWidget(self.faixa_aviso)

        self._aplicar_restricoes_papel()
        self._carregar_dados()

    def _construir_linha_busca_e_ordenacao(self) -> QHBoxLayout:
        linha = QHBoxLayout()
        linha.setSpacing(12)

        self._busca = QLineEdit()
        self._busca.setPlaceholderText("🔎 Buscar por cliente, CPF, banco ou equipamento")
        self._busca.textChanged.connect(self._aplicar_filtros)
        linha.addWidget(self._busca, stretch=1)

        rotulo_resposta = QLabel("Resposta")
        rotulo_resposta.setProperty("role", "secundario")
        linha.addWidget(rotulo_resposta)
        self._filtro_status = QComboBox()
        self._filtro_status.setMinimumWidth(150)
        self._filtro_status.setToolTip("O status da proposta (a resposta do banco)")
        self._filtro_status.currentIndexChanged.connect(self._aplicar_filtros)
        linha.addWidget(self._filtro_status)

        rotulo = QLabel("Ordenar por")
        rotulo.setProperty("role", "secundario")
        linha.addWidget(rotulo)
        self._ordenacao = _ComboListaLarga()
        for chave, texto in propostas_mod.ORDENACAO_OPCOES:
            self._ordenacao.addItem(texto, chave)
        # so depois de povoar: addItem() ja dispararia o sinal, com a tela ainda pela metade
        self._ordenacao.currentIndexChanged.connect(self._aplicar_filtros)
        linha.addWidget(self._ordenacao)
        return linha

    @staticmethod
    def _bloco_com_rotulo(texto: str, controle: QWidget) -> QWidget:
        """Rotulo pequeno em cima + o controle embaixo, num widget so (pra
        poder esconder o conjunto todo, ex.: o filtro de vendedor)."""
        bloco = QWidget()
        camada = QVBoxLayout(bloco)
        camada.setContentsMargins(0, 0, 0, 0)
        camada.setSpacing(2)
        legenda = QLabel(texto)
        legenda.setProperty("role", "campo_rotulo")
        camada.addWidget(legenda)
        camada.addWidget(controle)
        return bloco

    def _criar_combo_filtro(self) -> QComboBox:
        combo = _ComboListaLarga()
        # sem isso o combo ficaria tao largo quanto a maior opcao ("VELARYAN E ULTRAMED HIFU")
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(10)
        combo.currentIndexChanged.connect(self._aplicar_filtros)  # vazio ate o primeiro carregamento: sem disparo
        return combo

    def _construir_linha_filtros(self) -> QHBoxLayout:
        linha = QHBoxLayout()
        linha.setSpacing(12)

        self._filtro_vendedor = self._criar_combo_filtro()
        self._bloco_filtro_vendedor = self._bloco_com_rotulo("Vendedor", self._filtro_vendedor)
        linha.addWidget(self._bloco_filtro_vendedor, stretch=2)

        self._filtro_banco = self._criar_combo_filtro()
        linha.addWidget(self._bloco_com_rotulo("Banco", self._filtro_banco), stretch=2)

        self._filtro_equipamento = self._criar_combo_filtro()
        linha.addWidget(self._bloco_com_rotulo("Equipamento", self._filtro_equipamento), stretch=3)

        # o "ate" aceita data futura; as duas so filtram quando a data esta
        # completa e valida (ver campo_data.ler_periodo)
        self._filtro_de = CampoData(permitir_futuro=True)
        self._filtro_de.setFixedWidth(150)
        self._filtro_de.alterado.connect(self._ao_mudar_periodo)
        linha.addWidget(self._bloco_com_rotulo("Período de", self._filtro_de))

        self._filtro_ate = CampoData(permitir_futuro=True)
        self._filtro_ate.setFixedWidth(150)
        self._filtro_ate.alterado.connect(self._ao_mudar_periodo)
        linha.addWidget(self._bloco_com_rotulo("até", self._filtro_ate))

        self._botao_limpar_filtros = QPushButton("Limpar filtros")
        self._botao_limpar_filtros.setToolTip(
            "Volta Status, Vendedor, Banco, Equipamento e o período para \"Todos\" / em branco "
            "(a busca e a ordenação continuam)"
        )
        self._botao_limpar_filtros.clicked.connect(self._limpar_filtros)
        linha.addWidget(self._botao_limpar_filtros, alignment=Qt.AlignmentFlag.AlignBottom)
        return linha

    def _construir_chip_do_filtro(self) -> QFrame:
        """A faixa "Filtro do dashboard: ..." com o botao pra tirar so esse filtro (fica escondida enquanto
        nao ha filtro do dashboard)."""
        chip = QFrame()
        chip.setProperty("role", "chip_filtro")
        linha = QHBoxLayout(chip)
        linha.setContentsMargins(12, 6, 8, 6)
        linha.setSpacing(10)
        self._rotulo_do_chip = QLabel("")
        linha.addWidget(self._rotulo_do_chip)
        linha.addStretch()
        self._botao_remover_chip = QPushButton("✕ Remover filtro")
        self._botao_remover_chip.setProperty("role", "botao_link")
        self._botao_remover_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self._botao_remover_chip.clicked.connect(self._remover_filtro_do_dashboard)
        linha.addWidget(self._botao_remover_chip)
        chip.setVisible(False)
        return chip

    def _aplicar_restricoes_papel(self) -> None:
        """VENDEDOR e so-leitura: nao cria venda, e os cards dele nao tem acoes (sem a venda); ainda abre a proposta,
        com o formulario travado (valor, equipamento, banco, observacoes, copiar)."""
        if not sessao_mod.eh_vendedor():
            return
        self._bloco_filtro_vendedor.setVisible(False)  # so enxerga as proprias propostas: filtrar por vendedor nao faz sentido
        self._botao_nova.setVisible(False)

    # -- carregamento e filtro -----------------------------------------------

    def _ao_recarregar(self, *_args) -> None:
        """Botao Recarregar: le tudo de novo. Se ha um card com edicao nao salva, pergunta antes."""
        if self.lista.pode_descartar():
            self.lista.descartar()
            self._carregar_dados()

    def _depois_de_gravar(self, aviso: str = "") -> None:
        self._carregar_dados()
        self.faixa_aviso.avisar(aviso)

    def avisar(self, texto: str) -> None:
        self.faixa_aviso.avisar(texto)

    def _carregar_dados(self, *_args) -> None:
        self._vigia.registrar_leitura()
        try:
            self._todas = propostas_mod.listar_propostas()
            self._itens = self._montar_itens(self._todas)
        except FileNotFoundError:
            QMessageBox.critical(
                self,
                "Arquivo não encontrado",
                "Não foi possível encontrar o arquivo de dados (.xlsx). Confira o caminho configurado em config.py.",
            )
            return
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro ao carregar propostas", str(exc))
            return

        status_antes = self._filtro_status.currentText() if self._filtro_status.count() else _FILTRO_TODOS
        opcoes_status = [_FILTRO_TODOS] + sorted({s for s in self._todas["STATUS"] if s})
        self._filtro_status.blockSignals(True)
        self._filtro_status.clear()
        self._filtro_status.addItems(opcoes_status)
        if status_antes in opcoes_status:
            self._filtro_status.setCurrentText(status_antes)
        self._filtro_status.blockSignals(False)

        # banco e equipamento: so os que ja aparecem em alguma proposta; se o
        # escolhido deixou de existir (ex.: editou a unica proposta dele) o
        # combo volta pra "Todos", que e o que a tela mostra
        self._repovoar_filtro(self._filtro_banco, propostas_mod.valores_distintos(self._todas, "BANCO"))
        self._repovoar_filtro(self._filtro_equipamento, propostas_mod.valores_distintos(self._todas, "EQUIPAMENTO"))
        self._recarregar_vendedores_filtro()

        # recarregar (botao Recarregar, ou depois de gravar) NAO volta pra primeira
        # pagina: quem ja tinha carregado mais cards continua vendo, no mesmo lugar
        self._aplicar_filtros(manter_pagina=True)
        self.dados_atualizados.emit()

    @staticmethod
    def _montar_itens(todas: pd.DataFrame) -> dict[int, vendas_mod.PropostaNaLista]:
        """O card de cada proposta. O ADMIN tem as vendas e o HISTÓRICO (acoes, dias esperando desde a ultima troca);
        o VENDEDOR le do Google Sheets, sem eles: os dias contam da DATA e os cards nao tem acoes."""
        if sessao_mod.eh_vendedor():
            return vendas_mod.propostas_na_lista(todas)
        return vendas_mod.propostas_na_lista_do_arquivo(todas)

    def _linha_da_proposta(self, indice: int) -> dict | None:
        """A proposta como esta leitura a trouxe (o formulario do card aberto abre com ela)."""
        return self._todas.loc[indice].to_dict() if indice in self._todas.index else None

    def propostas_carregadas(self) -> pd.DataFrame:
        """As propostas como a ultima leitura desta tela as trouxe (sem ler de novo: pro
        VENDEDOR uma leitura e uma ida ao Google Sheets)."""
        return self._todas

    def tem_edicao_pendente(self) -> bool:
        return self.lista.tem_edicao_pendente()

    @staticmethod
    def _repovoar_filtro(combo: QComboBox, opcoes: list[str]) -> bool:
        """"Todos" + `opcoes`, mantendo a escolha atual se ela ainda existe (sem
        diferenciar maiusculas: a grafia mais usada de um banco pode mudar entre
        duas leituras). Devolve True se a escolha sumiu e o combo voltou pra
        "Todos" - quem chamou precisa reaplicar os filtros."""
        escolhido = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(_FILTRO_TODOS, None)
        for opcao in opcoes:
            combo.addItem(opcao, opcao)
        indice = 0
        if escolhido:
            indice = next(
                (i for i in range(1, combo.count()) if combo.itemData(i).strip().upper() == escolhido.strip().upper()), -1
            )
        combo.setCurrentIndex(max(indice, 0))
        combo.blockSignals(False)
        return bool(escolhido) and indice < 0

    def _recarregar_vendedores_filtro(self) -> bool:
        """Repovoa o filtro de Vendedor com quem esta no cadastro AGORA (a
        lista muda quando alguem cadastra um vendedor novo, em qualquer tela).
        Devolve True se o vendedor que estava escolhido nao existe mais e o
        filtro voltou pra "Todos" - quem chamou precisa reaplicar os filtros."""
        if sessao_mod.eh_vendedor():
            return False  # vendedor so enxerga as proprias propostas; o filtro nem aparece
        try:
            nomes = vendedores_mod.listar_vendedores()
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.warning(self, "Erro ao carregar vendedores", str(exc))
            return False
        return self._repovoar_filtro(self._filtro_vendedor, nomes)

    def showEvent(self, evento) -> None:
        super().showEvent(evento)
        # alguem pode ter cadastrado um vendedor em outra tela (Usuarios) desde a
        # ultima vez que esta tela apareceu
        if not self.recarregar_se_mudou() and self._recarregar_vendedores_filtro():
            self._aplicar_filtros(manter_pagina=True)

    def recarregar_se_mudou(self) -> bool:
        """Ao aparecer e a cada tique da janela com esta tela aberta: se a planilha mudou desde a ultima
        leitura (outra tela gravou, baixou da nuvem, restaurou backup), rele tudo - menos com um card em
        edicao nao salva, que nunca e descartado sem perguntar (o botao Recarregar pergunta). True se releu."""
        if self._vigia.mudou_desde_a_leitura() and not self.tem_edicao_pendente():
            self._carregar_dados()
            return True
        return False

    def _ao_mudar_periodo(self) -> None:
        """A data e digitada tecla a tecla: "1", "15/", "15/0"... nao filtram
        nada - so refaz a lista quando o periodo (ou os avisos) de fato mudou."""
        inicio, fim, avisos = ler_periodo(self._filtro_de, self._filtro_ate)
        if (inicio, fim, tuple(avisos)) == self._estado_periodo:
            return
        self._aplicar_filtros()

    def _limpar_filtros(self, *_args) -> None:
        """Status, Vendedor, Banco e Equipamento voltam pra "Todos", o periodo
        fica em branco e o filtro do dashboard (se ha) sai (a busca e a ordenacao
        NAO sao filtros - continuam como estao). Refaz a lista uma vez so, no fim."""
        self._definir_filtro_do_dashboard(None)
        for combo in (self._filtro_status, self._filtro_vendedor, self._filtro_banco, self._filtro_equipamento):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        for campo in (self._filtro_de, self._filtro_ate):
            campo.blockSignals(True)  # so o sinal "alterado" do conjunto; o campo interno ainda repinta a borda
            campo.limpar()
            campo.blockSignals(False)
        self._aplicar_filtros()

    def _aplicar_filtros(self, *_args, manter_pagina: bool = False) -> None:
        """Reaplica busca + filtros + ordenacao (todos combinados). Mudar
        qualquer um deles (sinais dos controles) volta pra primeira pagina;
        `manter_pagina=True` (recarregar) preserva quantos cards ja tinham sido
        carregados e a rolagem. O card aberto continua aberto se a proposta continua na lista."""
        inicio, fim, avisos = ler_periodo(self._filtro_de, self._filtro_ate)
        status_escolhido = self._filtro_status.currentText()
        try:
            df = propostas_mod.filtrar_propostas(
                self._todas,
                self._busca.text(),
                status=None if status_escolhido == _FILTRO_TODOS else status_escolhido,
                vendedor=self._filtro_vendedor.currentData(),
                banco=self._filtro_banco.currentData(),
                equipamento=self._filtro_equipamento.currentData(),
                data_de=inicio,
                data_ate=fim,
                ordenacao=self._ordenacao.currentData(),
                dias_esperando={i: item.proposta.dias_esperando for i, item in self._itens.items()},
            )
            if self._filtro_dashboard is not None:
                # recalculado a cada vez, sobre as propostas de agora: o filtro continua certo depois de uma edicao
                escolhidas = dashboard_mod.indices_do_filtro(self._todas, self._filtro_dashboard)
                df = df[df.index.isin(escolhidas)]
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro ao filtrar propostas", str(exc))
            return

        self._estado_periodo = (inicio, fim, tuple(avisos))
        self._botao_limpar_filtros.setEnabled(
            bool(
                (status_escolhido and status_escolhido != _FILTRO_TODOS)
                or self._filtro_vendedor.currentData()
                or self._filtro_banco.currentData()
                or self._filtro_equipamento.currentData()
                or self._filtro_de.texto()
                or self._filtro_ate.texto()
                or self._filtro_dashboard is not None
            )
        )

        itens = [self._itens[indice] for indice in df.index if indice in self._itens]
        # a contagem e o resumo por status sao SO do resultado filtrado
        resumo = resumo_por_etapa(Counter(propostas_mod.etapa_status(i.proposta.status) for i in itens))
        contador = f"{len(itens)} proposta(s)" + (f" · {resumo}" if resumo else "")
        if avisos:
            contador += " — " + "; ".join(avisos)
        self._contador.setText(contador)
        # a proposta aberta continua na lista mesmo que a busca ou um filtro a tirem (como na tela Vendas): o que foi
        # digitado nela nunca some sem perguntar
        aberta = next((i for i in self._itens.values() if chave_da_proposta(i) == self.lista.aberta), None)
        if aberta is not None and self.lista.aberta not in {chave_da_proposta(i) for i in itens}:
            itens.insert(0, aberta)
        self.lista.definir_propostas(itens, texto_vazio=_MENSAGEM_VAZIA, voltar_ao_inicio=not manter_pagina)

    def propostas_visiveis(self) -> list[vendas_mod.PropostaNaLista]:
        """As propostas que a lista mostra agora, na ordem (os cards vem de 30 em 30)."""
        return self.lista.propostas()

    # -- filtro vindo do Dashboard ---------------------------------------------------

    def filtro_do_dashboard(self) -> dashboard_mod.FiltroDoDashboard | None:
        return self._filtro_dashboard

    def chip_do_filtro_visivel(self) -> bool:
        return not self._chip_do_filtro.isHidden()

    def _definir_filtro_do_dashboard(self, filtro: dashboard_mod.FiltroDoDashboard | None) -> None:
        self._filtro_dashboard = filtro
        self._rotulo_do_chip.setText("" if filtro is None else f"Filtro do dashboard: {filtro.rotulo}")
        self._chip_do_filtro.setVisible(filtro is not None)

    def _remover_filtro_do_dashboard(self, *_args) -> None:
        self._definir_filtro_do_dashboard(None)
        self._aplicar_filtros()

    def aplicar_filtro_do_dashboard(self, filtro: dashboard_mod.FiltroDoDashboard) -> bool:
        """Mostra so as propostas que o `filtro` do Dashboard escolhe, com o periodo que ele estava usando. Zera
        os demais filtros e a busca (senao a lista podia vir vazia sem a pessoa saber por que). Com edicao
        nao salva em algum card, pergunta antes; False se a pessoa preferiu continuar editando."""
        if not self.lista.liberar():
            return False
        self._busca.blockSignals(True)
        self._busca.clear()
        self._busca.blockSignals(False)
        for combo in (self._filtro_status, self._filtro_vendedor, self._filtro_banco, self._filtro_equipamento):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        for campo, data in ((self._filtro_de, filtro.periodo_de), (self._filtro_ate, filtro.periodo_ate)):
            campo.blockSignals(True)  # so o sinal "alterado" do conjunto; o campo interno ainda repinta a borda
            campo.limpar()
            if data is not None:
                campo.definir_data(QDate(data.year, data.month, data.day))
            campo.blockSignals(False)
        self._definir_filtro_do_dashboard(filtro)
        if not sessao_mod.eh_vendedor():
            self._carregar_dados()  # arquivo local: releitura barata, e garante os dados de agora
        self._aplicar_filtros()  # e volta pra primeira pagina
        return True
