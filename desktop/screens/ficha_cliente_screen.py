"""Tela Ficha de Cliente.

Busca por nome/CPF + lista de clientes + a ficha do cliente selecionado
(dados + historico de propostas), com cadastro/edicao de cliente e
lancamento de propostas (dialogo de cliente e card expansivel de proposta). A
lista de clientes e o historico de propostas sao CARDS: um clique so seleciona
(o duplo clique, no historico, EXPANDE o proprio card com os detalhes e a edicao, o
mesmo de "Todas as Propostas"). O painel da ficha rola na vertical, e o endereco aparece retraido
(uma linha por extenso) com a opcao de expandir nos campos individuais.
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtCore import QModelIndex, QRect, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core import clientes as clientes_mod
from core import data_store as bd
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import vendedores as vendedores_mod
from core.formatting import formatar_data, formatar_endereco, formatar_equipamento_e_valor, formatar_tempo
from desktop import settings as settings_mod
from desktop.dialogs.cliente_dialog import ClienteDialog
from desktop.widgets.botao_copiar import BotaoCopiar
from desktop.widgets.cabecalho_retratil import CabecalhoRetratil
from desktop.widgets.campo_data import CampoData, ler_periodo
from desktop.widgets.exclusao_proposta import excluir_proposta_com_confirmacao
from desktop.widgets.expansor_proposta import ExpansorDeProposta
from desktop.widgets.lista_cartoes import ContentorDeListaAutomatica, ListaCartoes, ModeloCartoes, chave_cor_etapa
from desktop.widgets.lista_clientes import ListaClientes
from desktop.widgets.quebra_texto import texto_quebravel
from desktop.widgets.rotulo_uma_linha import RotuloUmaLinha
from desktop.widgets.shadow import aplicar_sombra_suave

_TEXTO_PADRAO_PAINEL = "Selecione um cliente na lista ao lado, ou cadastre um novo."

_MARGEM_PAINEL = 10  # em volta do conteudo do painel do cliente: da espaco pra sombra do cartao


def _montar_item_historico(indice: int, banco: str, equipamento: str, valor, status: str, data, tempo: str) -> dict:
    """Um card do historico do cliente: o BANCO em destaque (o cliente ja esta
    implicito na ficha), "Equipamento . Valor" na segunda linha, e a data, o
    tempo e o status (com a mesma cor de "Todas as Propostas") como la."""
    etapa = propostas_mod.etapa_status(status)
    return {
        "indice": indice,  # posicao real da proposta no arquivo
        "titulo": banco,
        "titulo_vazio": "(sem banco)",
        "linha2": formatar_equipamento_e_valor(equipamento, valor),
        "status": status,
        "data": formatar_data(data),
        "tempo": formatar_tempo(tempo),
        "etapa": etapa,
        "cor": chave_cor_etapa(etapa),
    }


class FichaClienteScreen(QWidget):
    # lancou, editou, duplicou ou excluiu uma proposta aqui: quem mostra algo derivado das
    # propostas (o selo da barra lateral) pode se atualizar
    dados_atualizados = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self._cpf_selecionado: str | None = None
        self._historico_atual: pd.DataFrame = pd.DataFrame()  # valores "crus" (indice = posicao real no arquivo)
        # CPFs (so digitos) de quem tem proposta em aberto - pinta a bolinha nos cards de cliente.
        # Fica em cache: a lista e refeita a cada tecla da busca, e reler as propostas a cada
        # vez seria lento; so se relê quando algo pode ter mudado (ver _invalidar_em_aberto)
        self._cpfs_em_aberto: set[str] = set()
        self._em_aberto_desatualizado = True
        self._area_a_mostrar: QRect | None = None  # o que _rolar_ate pediu (ver _executar_rolagem)
        # ultimo periodo (de, ate, avisos) aplicado na lista - digitar uma data
        # dispara um evento por tecla, e so vale reler a lista quando o que
        # valeria mudou de fato (ex.: "15/0" -> "15/03/" nao muda nada)
        self._estado_periodo: tuple = (None, None, ())

        layout_principal = QVBoxLayout(self)
        layout_principal.setContentsMargins(24, 24, 24, 24)
        layout_principal.setSpacing(16)

        titulo = QLabel("🗂️ Ficha de Cliente")
        titulo.setProperty("role", "titulo")
        layout_principal.addWidget(titulo)

        layout_principal.addLayout(self._construir_linha_busca_e_ordenacao())
        layout_principal.addLayout(self._construir_linha_filtros())

        corpo = QHBoxLayout()
        corpo.setSpacing(16)

        coluna_lista = QVBoxLayout()
        self._contador = QLabel("")
        self._contador.setProperty("role", "secundario")
        coluna_lista.addWidget(self._contador)

        self._lista = ListaClientes()
        self._lista.definir_mensagem_vazia("Nenhum cliente encontrado com esses filtros.")
        self._lista.cliente_mudou.connect(self._selecionar_cliente)
        coluna_lista.addWidget(self._lista)

        self._botao_novo_cliente = QPushButton("+ Novo Cliente")
        self._botao_novo_cliente.setProperty("role", "botao_primario")
        self._botao_novo_cliente.clicked.connect(self._abrir_cadastro_cliente)
        coluna_lista.addWidget(self._botao_novo_cliente)

        corpo.addLayout(coluna_lista, 1)

        self._painel_stack = QStackedWidget()
        self._painel_stack.addWidget(self._construir_pagina_vazia())  # indice 0
        self._painel_stack.addWidget(self._construir_pagina_ficha())  # indice 1
        corpo.addWidget(self._painel_stack, 2)

        layout_principal.addLayout(corpo, stretch=1)

        # card expansivel (o mesmo de "Todas as Propostas"): ler, editar, lancar e duplicar proposta,
        # ali mesmo no historico. Gravar recarrega a ficha e deixa selecionada a proposta gravada
        self._expansor = ExpansorDeProposta(
            self._lista_historico, self._modelo_historico, self._dados_da_proposta, self._recarregar_e_selecionar, self
        )
        self._lista_historico.acionado.connect(self._expansor.alternar)

        self._aplicar_restricoes_papel()
        self._recarregar_vendedores_filtro()
        self._atualizar_lista()

    # -- busca, ordenacao e filtros da lista --------------------------------

    def _construir_linha_busca_e_ordenacao(self) -> QHBoxLayout:
        linha = QHBoxLayout()
        linha.setSpacing(12)

        self._busca = QLineEdit()
        self._busca.setPlaceholderText("🔎 Buscar cliente por nome ou CPF/CNPJ")
        self._busca.textChanged.connect(self._atualizar_lista)
        linha.addWidget(self._busca, stretch=1)

        rotulo = QLabel("Ordenar por")
        rotulo.setProperty("role", "secundario")
        linha.addWidget(rotulo)
        self._ordenacao = QComboBox()
        for chave, texto in clientes_mod.ORDENACAO_OPCOES:
            self._ordenacao.addItem(texto, chave)
        self._ordenacao.currentIndexChanged.connect(self._atualizar_lista)
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

    def _construir_linha_filtros(self) -> QHBoxLayout:
        linha = QHBoxLayout()
        linha.setSpacing(12)

        self._filtro_vendedor = QComboBox()
        self._filtro_vendedor.setMinimumWidth(150)
        self._filtro_vendedor.currentIndexChanged.connect(self._atualizar_lista)
        self._bloco_filtro_vendedor = self._bloco_com_rotulo("Vendedor", self._filtro_vendedor)
        linha.addWidget(self._bloco_filtro_vendedor)

        self._filtro_tipo = QComboBox()
        self._filtro_tipo.addItem("Todos", None)
        for tipo in clientes_mod.TIPO_OPCOES:
            self._filtro_tipo.addItem(tipo, tipo)
        self._filtro_tipo.currentIndexChanged.connect(self._atualizar_lista)
        linha.addWidget(self._bloco_com_rotulo("Tipo", self._filtro_tipo))

        # o "ate" aceita data futura (ex.: "ate 31/12"); as duas so filtram
        # quando a data esta completa e valida
        self._filtro_cadastro_de = CampoData(permitir_futuro=True)
        self._filtro_cadastro_de.setFixedWidth(150)
        self._filtro_cadastro_de.alterado.connect(self._ao_mudar_periodo)
        linha.addWidget(self._bloco_com_rotulo("Cadastrado de", self._filtro_cadastro_de))

        self._filtro_cadastro_ate = CampoData(permitir_futuro=True)
        self._filtro_cadastro_ate.setFixedWidth(150)
        self._filtro_cadastro_ate.alterado.connect(self._ao_mudar_periodo)
        linha.addWidget(self._bloco_com_rotulo("até", self._filtro_cadastro_ate))

        linha.addStretch(1)  # peso 1: so o espacador estica; sem isso o espaco extra se reparte entre os campos
        self._botao_limpar_filtros = QPushButton("Limpar filtros")
        self._botao_limpar_filtros.setToolTip("Volta Vendedor, Tipo e período para \"Todos\" / em branco (a busca e a ordenação continuam)")
        self._botao_limpar_filtros.clicked.connect(self._limpar_filtros)
        linha.addWidget(self._botao_limpar_filtros, alignment=Qt.AlignmentFlag.AlignBottom)
        return linha

    def _recarregar_vendedores_filtro(self) -> bool:
        """Repovoa o filtro de Vendedor com quem esta no cadastro AGORA (a
        lista muda quando alguem cadastra um vendedor novo, em qualquer tela).
        Devolve True se o vendedor que estava escolhido nao existe mais e o
        filtro voltou pra "Todos" - quem chamou precisa reler a lista."""
        if sessao_mod.eh_vendedor():
            return False  # vendedor so enxerga os proprios clientes; o filtro nem aparece
        try:
            nomes = vendedores_mod.listar_vendedores()
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.warning(self, "Erro ao carregar vendedores", str(exc))
            return False

        escolhido = self._filtro_vendedor.currentData()
        self._filtro_vendedor.blockSignals(True)
        self._filtro_vendedor.clear()
        self._filtro_vendedor.addItem("Todos", None)
        for nome in nomes:
            self._filtro_vendedor.addItem(nome, nome)
        indice = self._filtro_vendedor.findData(escolhido) if escolhido else 0
        self._filtro_vendedor.setCurrentIndex(max(indice, 0))
        self._filtro_vendedor.blockSignals(False)
        return bool(escolhido) and indice < 0

    def _ler_periodo(self) -> tuple[pd.Timestamp | None, pd.Timestamp | None, list[str]]:
        """(inicio, fim, avisos) do periodo digitado - ver campo_data.ler_periodo."""
        return ler_periodo(self._filtro_cadastro_de, self._filtro_cadastro_ate)

    def _ao_mudar_periodo(self) -> None:
        inicio, fim, avisos = self._ler_periodo()
        if (inicio, fim, tuple(avisos)) == self._estado_periodo:
            return
        self._atualizar_lista()

    def _limpar_filtros(self, *_args) -> None:
        """Vendedor e Tipo voltam pra "Todos" e o periodo fica em branco (a
        busca e a ordenacao NAO sao filtros - continuam como estao). Le a
        lista uma vez so, no fim."""
        for combo in (self._filtro_vendedor, self._filtro_tipo):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        for campo in (self._filtro_cadastro_de, self._filtro_cadastro_ate):
            campo.blockSignals(True)  # so o sinal "alterado" do conjunto; o campo interno ainda repinta a borda
            campo.limpar()
            campo.blockSignals(False)
        self._atualizar_lista()

    def _aplicar_restricoes_papel(self) -> None:
        """VENDEDOR e so-leitura: nenhum botao de criar/editar/excluir pode
        aparecer (a camada core/*.py ja bloqueia a acao de verdade via
        sessao.exigir_admin(), isso aqui e so pra nao mostrar um botao que
        sempre daria erro)."""
        if not sessao_mod.eh_vendedor():
            return
        self._bloco_filtro_vendedor.setVisible(False)  # so enxerga os proprios clientes: filtrar por vendedor nao faz sentido
        self._botao_novo_cliente.setVisible(False)
        self._botao_editar_cliente.setVisible(False)
        self._botao_excluir_cliente.setVisible(False)
        self._botao_excluir_proposta.setVisible(False)
        self._botao_nova_proposta.setVisible(False)
        # o duplo clique num card do historico segue expandindo a proposta: pro VENDEDOR e a
        # LEITURA (sem "Editar" nem "Duplicar"), e e por ela que ele ve meses/observacoes

    # -- construcao dos widgets --------------------------------------------

    @staticmethod
    def _construir_pagina_vazia() -> QWidget:
        pagina = QWidget()
        layout = QVBoxLayout(pagina)
        texto = QLabel(_TEXTO_PADRAO_PAINEL)
        texto.setProperty("role", "secundario")
        texto.setWordWrap(True)
        texto.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(texto)
        layout.addStretch()
        return pagina

    def _construir_pagina_ficha(self) -> QWidget:
        """Painel do cliente. O conteudo (cartao de dados + historico) ROLA na
        vertical: os campos sempre tem o espaco normal, em vez de o Qt espremer
        tudo pra caber quando a janela e baixa. Os botoes de proposta ficam
        fixos embaixo, fora da rolagem."""
        pagina = QWidget()
        layout_pagina = QVBoxLayout(pagina)
        layout_pagina.setContentsMargins(0, 0, 0, 0)
        layout_pagina.setSpacing(8)

        self._rolagem_ficha = QScrollArea()
        self._rolagem_ficha.setWidgetResizable(True)
        self._rolagem_ficha.setFrameShape(QFrame.Shape.NoFrame)
        self._rolagem_ficha.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        conteudo = QWidget()
        layout = QVBoxLayout(conteudo)
        layout.setContentsMargins(_MARGEM_PAINEL, _MARGEM_PAINEL, _MARGEM_PAINEL, _MARGEM_PAINEL)
        layout.setSpacing(16)
        self._rolagem_ficha.setWidget(conteudo)
        layout_pagina.addWidget(self._rolagem_ficha, stretch=1)

        cartao = QFrame()
        cartao.setProperty("role", "card")
        aplicar_sombra_suave(cartao, settings_mod.obter_tema())
        layout_cartao = QVBoxLayout(cartao)
        layout_cartao.setContentsMargins(16, 16, 16, 16)
        layout_cartao.setSpacing(12)

        cabecalho_ficha = QHBoxLayout()
        self._nome_label = QLabel("")
        self._nome_label.setProperty("role", "subtitulo")
        cabecalho_ficha.addWidget(self._nome_label)
        cabecalho_ficha.addStretch()
        self._botao_editar_cliente = QPushButton("Editar")
        self._botao_editar_cliente.setProperty("role", "botao_primario")
        self._botao_editar_cliente.clicked.connect(self._abrir_edicao_cliente)
        cabecalho_ficha.addWidget(self._botao_editar_cliente)
        self._botao_excluir_cliente = QPushButton("Excluir")
        self._botao_excluir_cliente.setProperty("role", "botao_perigo")
        self._botao_excluir_cliente.clicked.connect(self._excluir_cliente)
        cabecalho_ficha.addWidget(self._botao_excluir_cliente)
        layout_cartao.addLayout(cabecalho_ficha)

        grade = self._nova_grade()
        # informacoes principais (as duas primeiras linhas), logo abaixo do
        # nome do cliente: quem e, quando nasceu, como falar com ele
        self._campo_cpf = self._criar_campo(grade, 0, 0, "CPF/CNPJ")
        self._campo_nascimento = self._criar_campo(grade, 0, 1, "Nascimento")
        self._campo_tipo = self._criar_campo(grade, 0, 2, "Tipo")
        self._campo_celular = self._criar_campo(grade, 1, 0, "Celular")
        self._campo_email = self._criar_campo(grade, 1, 1, "E-mail")
        self._campo_vendedor = self._criar_campo(grade, 1, 2, "Vendedor")
        # informacoes secundarias
        self._campo_rede_social = self._criar_campo(grade, 2, 0, "Rede social")
        self._campo_vinculado = self._criar_campo(grade, 2, 1, "Vinculado a")
        self._campo_cadastrado_em = self._criar_campo(grade, 2, 2, "Cadastrado em")
        self._campo_nome_pai = self._criar_campo(grade, 3, 0, "Nome do pai")
        self._campo_nome_mae = self._criar_campo(grade, 3, 1, "Nome da mãe")
        self._campo_profissao = self._criar_campo(grade, 3, 2, "Profissão")
        layout_cartao.addLayout(grade)

        # endereco: um campo como os outros (legenda pequena + valor, na mesma
        # grade), RETRAIDO por padrao - uma linha por extenso com o botao que
        # copia o endereco inteiro; a seta ao lado da legenda expande nos 7 campos
        self._cabecalho_endereco = CabecalhoRetratil(
            "Endereço",
            dica_expandir="Mostrar os campos do endereço (CEP, logradouro, número...)",
            dica_recolher="Voltar ao endereço em uma linha",
            papel_do_titulo="campo_rotulo",  # a mesma legenda dos outros campos
        )
        self._cabecalho_endereco.toggled.connect(self._ao_alternar_endereco)
        linha_legenda_endereco = QHBoxLayout()
        linha_legenda_endereco.addWidget(self._cabecalho_endereco)
        linha_legenda_endereco.addStretch()

        self._endereco_resumo = QWidget()
        self._endereco_resumo.setProperty("role", "transparente")  # sem fundo proprio: nada de faixa atras do campo
        linha_resumo, self._campo_endereco_completo = self._linha_copiavel_compacta()
        linha_resumo.setContentsMargins(0, 0, 0, 0)
        self._endereco_resumo.setLayout(linha_resumo)

        caixa_endereco = QVBoxLayout()
        caixa_endereco.setSpacing(2)  # o mesmo espaco entre legenda e valor dos outros campos
        caixa_endereco.addLayout(linha_legenda_endereco)
        caixa_endereco.addWidget(self._endereco_resumo)
        grade.addLayout(caixa_endereco, 4, 0, 1, 3)  # ultima linha da grade de dados, por toda a largura

        # expandido: cada campo do endereco tem seu botao de copiar (a ideia e
        # copiar um de cada vez pra colar em outro sistema)
        self._endereco_campos = QWidget()
        self._endereco_campos.setProperty("role", "transparente")
        grade_endereco = self._nova_grade()
        grade_endereco.setContentsMargins(0, 0, 0, 0)
        self._endereco_campos.setLayout(grade_endereco)
        self._endereco_campos.setVisible(False)
        grade.addWidget(self._endereco_campos, 5, 0, 1, 3)
        self._campo_cep = self._criar_campo_copiavel(grade_endereco, 0, 0, "CEP")
        self._campo_logradouro = self._criar_campo_copiavel(grade_endereco, 0, 1, "Logradouro")
        self._campo_numero = self._criar_campo_copiavel(grade_endereco, 0, 2, "Número")
        self._campo_complemento = self._criar_campo_copiavel(grade_endereco, 1, 0, "Complemento")
        self._campo_bairro = self._criar_campo_copiavel(grade_endereco, 1, 1, "Bairro")
        # Cidade e UF dividem a 3a coluna (a UF e curta) - assim a grade
        # continua com as mesmas 3 colunas da grade de dados, la em cima
        caixa_cidade, self._campo_cidade = self._caixa_copiavel("Cidade")
        caixa_uf, self._campo_uf = self._caixa_copiavel("UF")
        linha_cidade_uf = QHBoxLayout()
        linha_cidade_uf.setSpacing(12)
        linha_cidade_uf.addLayout(caixa_cidade, 3)
        linha_cidade_uf.addLayout(caixa_uf, 1)
        grade_endereco.addLayout(linha_cidade_uf, 1, 2)

        # so aparece pra quem tem endereco antigo que a migracao nao separou
        self._aviso_endereco_revisar = QLabel("")
        self._aviso_endereco_revisar.setProperty("role", "secundario")
        self._aviso_endereco_revisar.setWordWrap(True)
        self._aviso_endereco_revisar.setVisible(False)
        layout_cartao.addWidget(self._aviso_endereco_revisar)

        layout.addWidget(cartao)

        subtitulo_historico = QLabel("Histórico de propostas")
        subtitulo_historico.setProperty("role", "subtitulo")
        layout.addWidget(subtitulo_historico)

        self._historico_vazio = QLabel("Nenhuma proposta registrada para este cliente ainda.")
        self._historico_vazio.setProperty("role", "secundario")
        layout.addWidget(self._historico_vazio)

        # cards, no mesmo estilo de "Todas as Propostas" (banco em destaque). Sem barra de rolagem
        # propria: quem rola e o painel. Um clique so seleciona; o duplo clique (ou Enter) EXPANDE o
        # card (ver _expansor), e o botao "Excluir Proposta Selecionada" age no card selecionado
        self._modelo_historico = ModeloCartoes(self)
        self._lista_historico = ListaCartoes(altura_automatica=True)
        self._lista_historico.setModel(self._modelo_historico)
        self._lista_historico.rolar_pedido.connect(self._rolar_ate)
        # o historico aparece quando ha propostas OU o card "Nova proposta" (um cliente sem nenhuma
        # ainda tambem precisa ver o card pra lancar a primeira)
        for sinal in (self._modelo_historico.modelReset, self._modelo_historico.rowsInserted, self._modelo_historico.rowsRemoved):
            sinal.connect(self._atualizar_visibilidade_do_historico)
        # o contentor alinha o ultimo card com a borda do cartao de dados, la em cima
        self._contentor_historico = ContentorDeListaAutomatica(self._lista_historico)
        self._contentor_historico.setProperty("role", "transparente")
        layout.addWidget(self._contentor_historico)
        layout.addStretch(1)  # conteudo curto fica no topo, sem esticar o cartao

        # fixos embaixo (fora da rolagem), alinhados com o cartao
        self._linha_botoes_ficha = QHBoxLayout()
        self._linha_botoes_ficha.setContentsMargins(_MARGEM_PAINEL, 0, _MARGEM_PAINEL, _MARGEM_PAINEL)
        self._botao_excluir_proposta = QPushButton("Excluir Proposta Selecionada")
        self._botao_excluir_proposta.setProperty("role", "botao_perigo")
        self._botao_excluir_proposta.clicked.connect(self._excluir_proposta_selecionada)
        self._linha_botoes_ficha.addWidget(self._botao_excluir_proposta)
        self._botao_nova_proposta = QPushButton("+ Nova Proposta")
        self._botao_nova_proposta.setProperty("role", "botao_primario")
        self._botao_nova_proposta.clicked.connect(self._abrir_nova_proposta)
        self._linha_botoes_ficha.addWidget(self._botao_nova_proposta)
        layout_pagina.addLayout(self._linha_botoes_ficha)
        self._rolagem_ficha.verticalScrollBar().rangeChanged.connect(self._ajustar_margem_dos_botoes)
        self._rolagem_ficha.verticalScrollBar().rangeChanged.connect(self._tentar_rolar)

        return pagina

    @staticmethod
    def _nova_grade() -> QGridLayout:
        grade = QGridLayout()
        grade.setHorizontalSpacing(24)
        grade.setVerticalSpacing(8)
        # tres colunas iguais - as duas grades do cartao (dados e endereco)
        # ficam alinhadas entre si
        for coluna in range(3):
            grade.setColumnStretch(coluna, 1)
        return grade

    @staticmethod
    def _criar_rotulo_valor() -> QLabel:
        valor = QLabel("—")
        valor.setProperty("role", "campo_valor")
        valor.setWordWrap(True)
        return valor

    @staticmethod
    def _criar_campo(grade: QGridLayout, row: int, col: int, titulo: str) -> QLabel:
        """Cria um par legenda/valor na grade e devolve o QLabel do valor (pra
        dar setText depois)."""
        caixa = QVBoxLayout()
        caixa.setSpacing(2)
        legenda = QLabel(titulo)
        legenda.setProperty("role", "campo_rotulo")
        valor = FichaClienteScreen._criar_rotulo_valor()
        caixa.addWidget(legenda)
        caixa.addWidget(valor)
        grade.addLayout(caixa, row, col)
        return valor

    @staticmethod
    def _linha_copiavel() -> tuple[QHBoxLayout, QLabel]:
        """Valor + botao Copiar ao lado, numa linha. Devolve o layout (pra
        quem chamou encaixar onde quiser) e o QLabel do valor. O que o botao
        copia e o texto CRU guardado na propriedade "texto_cru" (ver
        _definir_valor_copiavel), nunca o que aparece no QLabel: la o texto
        tem "—" quando vazio e pontos de quebra invisiveis (texto_quebravel)."""
        valor = FichaClienteScreen._criar_rotulo_valor()
        botao = BotaoCopiar(lambda: valor.property("texto_cru") or "")
        linha = QHBoxLayout()
        linha.setSpacing(4)
        linha.addWidget(valor, stretch=1)
        linha.addWidget(botao, alignment=Qt.AlignmentFlag.AlignTop)
        return linha, valor

    @staticmethod
    def _linha_copiavel_compacta() -> tuple[QHBoxLayout, RotuloUmaLinha]:
        """Como _linha_copiavel, mas pro endereco por extenso: o valor tem o
        MESMO estilo e altura dos outros campos (nao a altura do botao) e ocupa
        so a largura do proprio texto, com o botao de copiar logo ao lado - em
        vez de uma barra pela largura toda. So quebra em mais linhas se nao couber."""
        valor = RotuloUmaLinha("—")
        valor.setProperty("role", "campo_valor")
        botao = BotaoCopiar(lambda: valor.property("texto_cru") or "")
        linha = QHBoxLayout()
        linha.setSpacing(4)
        linha.addWidget(valor, alignment=Qt.AlignmentFlag.AlignVCenter)
        linha.addWidget(botao, alignment=Qt.AlignmentFlag.AlignVCenter)
        linha.addStretch(1)
        return linha, valor

    @staticmethod
    def _caixa_copiavel(titulo: str) -> tuple[QVBoxLayout, QLabel]:
        """Legenda + valor + botao Copiar ao lado do valor (ver _linha_copiavel).
        Devolve o layout e o QLabel do valor."""
        caixa = QVBoxLayout()
        caixa.setSpacing(2)
        legenda = QLabel(titulo)
        legenda.setProperty("role", "campo_rotulo")
        caixa.addWidget(legenda)

        linha, valor = FichaClienteScreen._linha_copiavel()
        caixa.addLayout(linha)
        return caixa, valor

    @staticmethod
    def _criar_campo_copiavel(grade: QGridLayout, row: int, col: int, titulo: str) -> QLabel:
        """Como _criar_campo, mas com um botao Copiar ao lado do valor."""
        caixa, valor = FichaClienteScreen._caixa_copiavel(titulo)
        grade.addLayout(caixa, row, col)
        return valor

    @staticmethod
    def _definir_valor_copiavel(rotulo: QLabel, texto: str) -> None:
        rotulo.setProperty("texto_cru", texto)
        rotulo.setText(texto_quebravel(texto) or "—")

    # -- endereco retratil, rolagem do painel --------------------------------

    def _ao_alternar_endereco(self, expandido: bool) -> None:
        """Retraido: o endereco numa linha (com copiar). Expandido: os 7 campos,
        cada um com o seu copiar. A escolha vale pra qualquer cliente que se abra
        depois (e uma preferencia de visualizacao, nao um dado do cliente)."""
        self._endereco_resumo.setVisible(not expandido)
        self._endereco_campos.setVisible(expandido)
        if expandido:
            # o layout so se refaz no proximo ciclo de eventos: so entao da pra rolar ate os campos
            QTimer.singleShot(0, self._mostrar_campos_do_endereco)

    def _mostrar_campos_do_endereco(self) -> None:
        self._rolagem_ficha.ensureWidgetVisible(self._endereco_campos, 0, 16)

    def _ajustar_margem_dos_botoes(self, _minimo: int, maximo: int) -> None:
        """Quando a barra de rolagem aparece ela ocupa o lado do painel e o
        cartao fica mais estreito: os botoes fixos de baixo (fora da rolagem)
        acompanham, pra continuarem alinhados com o cartao."""
        largura_barra = self._rolagem_ficha.verticalScrollBar().sizeHint().width() if maximo > 0 else 0
        self._linha_botoes_ficha.setContentsMargins(_MARGEM_PAINEL, 0, _MARGEM_PAINEL + largura_barra, _MARGEM_PAINEL)

    # -- carregamento de dados ----------------------------------------------

    def showEvent(self, evento) -> None:
        super().showEvent(evento)
        # alguem pode ter cadastrado um vendedor em outra tela (Usuarios) desde a
        # ultima vez que esta tela apareceu - e uma proposta pode ter mudado de
        # status em "Todas as Propostas": a bolinha "Em aberto" precisa refletir isso
        self._invalidar_em_aberto()
        if self._recarregar_vendedores_filtro():
            self._atualizar_lista()
        else:
            self._atualizar_indicadores_em_aberto()

    def _invalidar_em_aberto(self) -> None:
        """Algo pode ter mudado (cliente ou proposta): na proxima vez, relê quem tem proposta em aberto."""
        self._em_aberto_desatualizado = True

    def _atualizar_indicadores_em_aberto(self) -> None:
        """Relê quem tem proposta em aberto (so se algo pode ter mudado) e repinta
        a bolinha dos cards - a lista em si nao muda."""
        if self._em_aberto_desatualizado:
            try:
                self._cpfs_em_aberto = propostas_mod.cpfs_com_proposta_em_aberto()
            except Exception as exc:  # nunca falhar em silencio
                QMessageBox.warning(
                    self,
                    "Erro ao carregar as propostas em aberto",
                    f"A lista de clientes segue funcionando, mas sem a marca de quem tem proposta em aberto.\n\n{exc}",
                )
                self._cpfs_em_aberto = set()
            self._em_aberto_desatualizado = False
        self._lista.definir_em_aberto(self._cpfs_em_aberto)

    def _atualizar_lista(self, *_args) -> None:
        """Le a lista de novo com a busca + filtros + ordenacao atuais (todos
        combinados) e atualiza o contador. *_args absorve o valor que os
        sinais dos controles mandam."""
        termo = self._busca.text().strip()
        inicio, fim, avisos = self._ler_periodo()
        try:
            resultados = clientes_mod.buscar(
                termo,
                vendedor=self._filtro_vendedor.currentData(),
                tipo=self._filtro_tipo.currentData(),
                cadastro_de=inicio,
                cadastro_ate=fim,
                ordenacao=self._ordenacao.currentData(),
            )
        except FileNotFoundError:
            QMessageBox.critical(
                self,
                "Arquivo não encontrado",
                "Não foi possível encontrar o arquivo de dados (.xlsx). Confira o caminho configurado em config.py.",
            )
            return
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro ao buscar clientes", str(exc))
            return

        self._estado_periodo = (inicio, fim, tuple(avisos))
        contador = f"{len(resultados)} cliente(s)"
        if avisos:
            contador += " — " + "; ".join(avisos)
        self._contador.setText(contador)
        self._botao_limpar_filtros.setEnabled(
            bool(
                self._filtro_vendedor.currentData()
                or self._filtro_tipo.currentData()
                or self._filtro_cadastro_de.texto()
                or self._filtro_cadastro_ate.texto()
            )
        )

        itens = [
            {"cpf": cpf, "cliente": nome, "tipo": tipo, "vendedor": vendedor}
            for cpf, nome, tipo, vendedor in zip(
                resultados["CPF/CNPJ"], resultados["CLIENTE"], resultados["TIPO"], resultados["VENDEDOR"]
            )
        ]
        self._atualizar_indicadores_em_aberto()
        # mudar ordenacao/filtro nao pode fechar a ficha aberta se o cliente continua
        # na lista (a lista mantem o card selecionado sem emitir sinal: nada de reler a ficha)
        if not self._lista.definir_itens(itens, self._cpf_selecionado):
            self._cpf_selecionado = None
            self._painel_stack.setCurrentIndex(0)

    def _selecionar_por_cpf(self, cpf: str) -> bool:
        """Procura `cpf` na lista atual e seleciona (dispara _selecionar_cliente).
        Usado depois de cadastrar/editar um cliente, pra reabrir a ficha dele.
        Devolve False se ele nao esta na lista (ex.: escondido pelos filtros).
        """
        linha = self._lista.linha_do_cpf(cpf)
        if linha is None:
            return False
        ja_selecionado = self._cpf_selecionado == cpf and self._lista.linha_atual() == linha
        self._lista.definir_linha_atual(linha)
        if ja_selecionado:
            # ja era o atual: nao dispara nada, e a ficha aberta ainda mostra os
            # dados de ANTES da edicao
            self._recarregar_ficha_atual()
        return True

    def _mostrar_cliente(self, cpf: str) -> None:
        """Abre a ficha de `cpf`. Se os filtros o escondem (ex.: acabou de
        cadastrar alguem de outro vendedor, ou trocou o vendedor de quem estava
        aberto), limpa os filtros - senao a pessoa salvou e o cliente "sumiu"."""
        if not self._selecionar_por_cpf(cpf):
            self._limpar_filtros()
            self._selecionar_por_cpf(cpf)

    def _selecionar_cliente(self, cpf: str) -> None:
        """`cpf`: o do card que passou a ser o atual; "" = nenhum."""
        self._descartar_expansao()  # o card expandido (ou o "Nova proposta") era do cliente anterior
        if not cpf:
            self._cpf_selecionado = None
            self._painel_stack.setCurrentIndex(0)
            return

        try:
            cliente = clientes_mod.buscar_por_cpf(cpf)
            historico = propostas_mod.historico_por_cpf(cpf)
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro ao carregar cliente", str(exc))
            return

        if cliente is None:
            QMessageBox.warning(self, "Cliente não encontrado", "Este cliente pode ter sido removido.")
            self._cpf_selecionado = None
            self._painel_stack.setCurrentIndex(0)
            return

        self._cpf_selecionado = cpf
        self._preencher_ficha(cliente, historico)
        self._rolagem_ficha.verticalScrollBar().setValue(0)  # outro cliente: o painel volta pro topo
        self._painel_stack.setCurrentIndex(1)

    def _preencher_ficha(
        self, cliente: dict, historico: pd.DataFrame, mesmo_cliente: bool = False, selecionar: int | None = None
    ) -> None:
        """`mesmo_cliente`: recarregando a ficha JA aberta (depois de editar ou
        lancar uma proposta) - o card de proposta selecionado e a pagina carregada
        do historico se mantem; abrindo outro cliente, o historico comeca limpo.
        `selecionar`: a proposta (indice real) que fica selecionada e visivel (padrao: a que ja estava)."""
        # guarda os valores "crus" (Timestamp/float, indice = posicao real no
        # arquivo) - os cards mostram uma versao formatada pra leitura, mas
        # editar uma proposta precisa dos valores originais
        self._historico_atual = historico

        self._nome_label.setText(texto_quebravel(cliente["CLIENTE"]))
        self._campo_cpf.setText(cliente["CPF/CNPJ"])
        self._campo_tipo.setText(cliente["TIPO"] or "—")
        self._campo_vendedor.setText(cliente["VENDEDOR"] or "—")
        self._campo_celular.setText(cliente["CELULAR"] or "—")
        self._campo_email.setText(texto_quebravel(cliente["EMAIL"]) or "—")
        self._campo_rede_social.setText(texto_quebravel(cliente["REDE SOCIAL"]) or "—")
        self._campo_nascimento.setText(formatar_data(cliente.get("NASCIMENTO")))
        self._campo_cadastrado_em.setText(formatar_data(cliente.get("DATA CADASTRO")))
        self._campo_vinculado.setText(texto_quebravel(cliente["VINCULADO"]) or "—")
        self._campo_nome_pai.setText(texto_quebravel(cliente["NOME DO PAI"]) or "—")
        self._campo_nome_mae.setText(texto_quebravel(cliente["NOME DA MÃE"]) or "—")
        self._campo_profissao.setText(texto_quebravel(cliente["PROFISSÃO"]) or "—")

        self._definir_valor_copiavel(self._campo_cep, cliente["CEP"])
        self._definir_valor_copiavel(self._campo_logradouro, cliente["LOGRADOURO"])
        self._definir_valor_copiavel(self._campo_numero, cliente["NÚMERO"])
        self._definir_valor_copiavel(self._campo_complemento, cliente["COMPLEMENTO"])
        self._definir_valor_copiavel(self._campo_bairro, cliente["BAIRRO"])
        self._definir_valor_copiavel(self._campo_cidade, cliente["CIDADE"])
        self._definir_valor_copiavel(self._campo_uf, cliente["UF"])
        # o mesmo endereco por extenso, pro estado retraido (o campo vazio simplesmente fica de fora)
        self._definir_valor_copiavel(
            self._campo_endereco_completo,
            formatar_endereco(
                logradouro=cliente["LOGRADOURO"],
                numero=cliente["NÚMERO"],
                complemento=cliente["COMPLEMENTO"],
                bairro=cliente["BAIRRO"],
                cidade=cliente["CIDADE"],
                uf=cliente["UF"],
                cep=cliente["CEP"],
            ),
        )

        texto_revisar = cliente["ENDEREÇO (REVISAR)"]
        self._aviso_endereco_revisar.setVisible(bool(texto_revisar))
        if texto_revisar:
            self._aviso_endereco_revisar.setText(
                f"⚠ Endereço a revisar (ainda não separado nos campos acima): {texto_quebravel(texto_revisar)}"
            )

        if historico.empty:
            self._modelo_historico.definir_itens([])  # (a visibilidade do historico segue o modelo)
            return

        # a mesma ordem de "Todas as Propostas": a mais recente primeiro (na mesma data, a cadastrada por ultimo)
        ordenado = propostas_mod.ordenar(historico)
        itens = [
            _montar_item_historico(indice, banco, equipamento, valor, status, data, tempo)
            for indice, banco, equipamento, valor, status, data, tempo in zip(
                ordenado.index, ordenado["BANCO"], ordenado["EQUIPAMENTO"], ordenado["VALOR (R$)"],
                ordenado["STATUS"], ordenado["DATA"], ordenado["TEMPO"],
            )
        ]
        if selecionar is not None:
            selecionada = selecionar
        else:
            selecionada = self._indice_real_proposta_selecionada() if mesmo_cliente else None
        self._modelo_historico.definir_itens(itens, manter_limite=mesmo_cliente, garantir_visivel=selecionada)
        if selecionada is not None:
            linha = self._modelo_historico.linha_do_indice_real(selecionada)
            if linha is not None:
                self._lista_historico.setCurrentIndex(self._modelo_historico.index(linha))

    def _indice_real_proposta_selecionada(self) -> int | None:
        """Posicao real (no arquivo) da proposta do card selecionado no historico."""
        linha = self._lista_historico.linha_atual()
        return None if linha is None else self._modelo_historico.indice_real(linha)

    def _atualizar_visibilidade_do_historico(self, *_args) -> None:
        """O historico (os cards) aparece se ha propostas ou o card "Nova proposta"; senao, o aviso."""
        ha_cards = self._modelo_historico.total() > 0 or self._modelo_historico.tem_rascunho()
        self._historico_vazio.setVisible(not ha_cards)
        self._contentor_historico.setVisible(ha_cards)

    def _descartar_expansao(self) -> None:
        """Recolhe o card expandido (a ficha mudou de assunto); avisa se havia edicao nao salva."""
        if self._expansor.descartar():
            QMessageBox.information(
                self,
                "Alterações descartadas",
                "A proposta que estava sendo editada foi fechada e as alterações que não tinham sido salvas foram descartadas.",
            )

    def _dados_da_proposta(self, indice_real: int):
        """O que o card expandido precisa da proposta na posicao `indice_real`: (cpf, cliente, dict)."""
        if not self._cpf_selecionado or indice_real not in self._historico_atual.index:
            return None
        return self._cpf_selecionado, self._nome_label.text(), self._historico_atual.loc[indice_real].to_dict()

    def _recarregar_e_selecionar(self, indice: int | None) -> None:
        """Depois de gravar uma proposta: le a ficha de novo e deixa selecionado o card dela."""
        self._depois_de_mudar_propostas(selecionar=indice)

    def _rolar_ate(self, area: QRect) -> None:
        """O historico nao rola sozinho (quem rola e o painel da ficha): mostra `area` (do card
        expandido ou novo, em coordenadas da lista). Adiado um instante: a altura do painel so e
        atualizada quando o Qt refaz o layout."""
        self._area_a_mostrar = area
        QTimer.singleShot(0, self._tentar_rolar)

    def _tentar_rolar(self, *_args) -> None:
        """Rola o painel ate mostrar `_area_a_mostrar`. Se o painel ainda nao cresceu o bastante (o
        card acabou de expandir), fica pendente e tenta de novo quando a faixa de rolagem mudar."""
        area = self._area_a_mostrar
        if area is None or not self._lista_historico.isVisible():
            return
        barra = self._rolagem_ficha.verticalScrollBar()
        topo = self._lista_historico.viewport().mapTo(self._rolagem_ficha.widget(), area.topLeft()).y()
        altura_visivel = self._rolagem_ficha.viewport().height()
        if area.height() + 24 > altura_visivel:
            alvo = topo - 12  # nao cabe: o topo do card
        elif topo - 12 < barra.value():
            alvo = topo - 12
        elif topo + area.height() + 12 > barra.value() + altura_visivel:
            alvo = topo + area.height() + 12 - altura_visivel
        else:
            self._area_a_mostrar = None  # ja esta a vista
            return
        alvo = max(0, alvo)
        if alvo > barra.maximum():
            return  # o painel ainda nao cresceu: a mudanca da faixa de rolagem chama de novo
        barra.setValue(alvo)
        self._area_a_mostrar = None

    # -- dialogos: cadastro/edicao de cliente e nova proposta ---------------

    def _abrir_cadastro_cliente(self) -> None:
        dialogo = ClienteDialog(cliente=None, parent=self)
        aceito = dialogo.exec() == QDialog.DialogCode.Accepted
        # o dialogo tem "+ Novo Vendedor": o filtro precisa enxergar quem foi
        # cadastrado, mesmo que o cliente nao tenha sido salvo
        vendedor_escolhido_sumiu = self._recarregar_vendedores_filtro()
        if not aceito:
            if vendedor_escolhido_sumiu:
                self._atualizar_lista()
            return
        # limpa a busca pra garantir que o cliente novo apareca na lista,
        # mesmo que o texto buscado antes nao bata com o nome/CPF dele
        self._invalidar_em_aberto()
        self._busca.setText("")
        self._atualizar_lista()
        self._mostrar_cliente(dialogo.cpf_salvo)

    def _abrir_edicao_cliente(self) -> None:
        if not self._cpf_selecionado:
            return
        cliente = clientes_mod.buscar_por_cpf(self._cpf_selecionado)
        if cliente is None:
            QMessageBox.warning(self, "Cliente não encontrado", "Este cliente pode ter sido removido.")
            self._cpf_selecionado = None
            self._painel_stack.setCurrentIndex(0)
            return
        dialogo = ClienteDialog(cliente=cliente, parent=self)
        aceito = dialogo.exec() == QDialog.DialogCode.Accepted
        vendedor_escolhido_sumiu = self._recarregar_vendedores_filtro()
        if not aceito:
            if vendedor_escolhido_sumiu:
                self._atualizar_lista()
            return
        self._invalidar_em_aberto()  # o CPF pode ter mudado: as propostas em aberto sao ligadas a ele
        self._busca.setText("")
        self._atualizar_lista()
        self._mostrar_cliente(dialogo.cpf_salvo)

    def _recarregar_ficha_atual(self, selecionar: int | None = None) -> bool:
        """Recarrega cliente + historico do CPF selecionado, com a mesma
        protecao contra erro de leitura que o primeiro carregamento
        (_selecionar_cliente) ja tinha - antes disso, so o carregamento
        inicial estava protegido, e um erro de leitura aqui (ex: arquivo
        bloqueado no meio da releitura) derrubava a tela sem aviso nenhum.
        Devolve False se o cliente sumiu ou deu erro (a tela ja foi avisada
        e ajustada nesse caso).
        """
        try:
            cliente = clientes_mod.buscar_por_cpf(self._cpf_selecionado)
            historico = propostas_mod.historico_por_cpf(self._cpf_selecionado)
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro ao recarregar cliente", str(exc))
            return False
        if cliente is None:
            QMessageBox.warning(self, "Cliente não encontrado", "Este cliente pode ter sido removido.")
            self._cpf_selecionado = None
            self._painel_stack.setCurrentIndex(0)
            return False
        self._preencher_ficha(cliente, historico, mesmo_cliente=True, selecionar=selecionar)
        return True

    def _abrir_nova_proposta(self) -> None:
        if not self._cpf_selecionado:
            return
        self._expansor.nova(self._cpf_selecionado, self._nome_label.text())

    def abrir_ficha_do_cliente(self, cpf: str) -> bool:
        """Abre a ficha de `cpf` (em qualquer formato); se os filtros da lista escondem o cliente, limpa-os.
        False (depois de avisar) se nao ha cliente com esse CPF."""
        try:
            cliente = clientes_mod.buscar_por_cpf(cpf)
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro ao carregar cliente", str(exc))
            return False
        if cliente is None:
            QMessageBox.warning(self, "Cliente não encontrado", "Não há cliente cadastrado com este CPF/CNPJ.")
            return False
        self._mostrar_cliente(cliente["CPF/CNPJ"])
        return self._cpf_selecionado == cliente["CPF/CNPJ"]

    def abrir_nova_proposta_a_partir_de(self, cpf: str, indice_da_proposta: int) -> bool:
        """Abre a ficha de `cpf` com o card "Nova proposta" ja preenchido a partir da proposta na posicao
        `indice_da_proposta` do arquivo (o "Duplicar" do dashboard). Nao grava nada."""
        if not self.abrir_ficha_do_cliente(cpf):
            return False
        if indice_da_proposta not in self._historico_atual.index:
            QMessageBox.warning(
                self, "Proposta não encontrada", "A proposta de onde duplicar não foi encontrada (a lista pode ter mudado). Atualize o Dashboard."
            )
            return False
        proposta = self._historico_atual.loc[indice_da_proposta].to_dict()
        self._expansor.nova_a_partir_de(self._cpf_selecionado, self._nome_label.text(), proposta)
        return True

    def _depois_de_mudar_propostas(self, selecionar: int | None = None) -> None:
        """Lancou, editou, duplicou ou excluiu uma proposta: recarrega a ficha aberta
        (historico) e repinta a bolinha "Em aberto" - ela pode ter aparecido ou sumido."""
        self._recarregar_ficha_atual(selecionar=selecionar)
        self._invalidar_em_aberto()
        self._atualizar_indicadores_em_aberto()
        self.dados_atualizados.emit()

    def tem_edicao_pendente(self) -> bool:
        return self._expansor.tem_alteracoes()

    def _excluir_proposta_selecionada(self) -> None:
        """Exclui a proposta do card selecionado no historico (1 clique), com a mesma
        confirmacao de "Todas as Propostas"."""
        if not self._cpf_selecionado:
            return
        # o card expandido pode ser outro (ou este): as posicoes andam depois de excluir, entao
        # nada fica expandido - e edicao nao salva nao some sem perguntar
        if not self._expansor.liberar():
            return

        indice_real = self._indice_real_proposta_selecionada()
        if indice_real is None:
            QMessageBox.information(
                self, "Nenhuma proposta selecionada", "Clique em um card do histórico para selecionar a proposta a excluir."
            )
            return

        proposta = self._historico_atual.loc[indice_real].to_dict()
        if not excluir_proposta_com_confirmacao(self, indice_real, self._nome_label.text(), proposta):
            return

        # o card excluido nao existe mais; os indices dos seguintes mudam - nao ha o que "manter selecionado"
        self._lista_historico.setCurrentIndex(QModelIndex())
        self._lista_historico.clearSelection()
        self._depois_de_mudar_propostas()

    def _excluir_cliente(self) -> None:
        if not self._cpf_selecionado:
            return

        nome = self._nome_label.text()
        try:
            historico = propostas_mod.historico_por_cpf(self._cpf_selecionado)
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro ao carregar histórico", str(exc))
            return

        mensagem = f"Tem certeza que deseja excluir '{nome}'? Essa ação não pode ser desfeita."
        if not historico.empty:
            mensagem += (
                f"\n\nAtenção: existem {len(historico)} proposta(s) lançada(s) para este cliente. "
                "Elas NÃO serão apagadas, mas deixarão de mostrar o nome e o vendedor "
                "corretos dali pra frente (o vínculo é feito pelo CPF)."
            )

        resposta = QMessageBox.question(
            self,
            "Excluir cliente",
            mensagem,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if resposta != QMessageBox.StandardButton.Yes:
            return

        try:
            clientes_mod.remover_cliente(self._cpf_selecionado)
        except clientes_mod.ErroCliente as exc:
            QMessageBox.warning(self, "Não foi possível excluir", str(exc))
            return
        except bd.ErroArquivoBloqueado as exc:
            QMessageBox.critical(self, "Arquivo bloqueado", str(exc))
            return
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro inesperado ao excluir", str(exc))
            return

        self._invalidar_em_aberto()
        self._busca.setText("")
        self._atualizar_lista()
