"""Tela Ficha de Cliente.

Busca por nome/CPF + lista de clientes + a ficha do cliente selecionado: dados (editaveis ali mesmo), as VENDAS
do cliente - os mesmos cards da tela Vendas (desktop/widgets/lista_de_vendas.py), com "+ Nova venda" ja com o
cliente - e, se houver, as propostas de antes das vendas (ainda nao juntadas em nenhuma venda), no mesmo card de
proposta de Todas as Propostas (desktop/widgets/lista_de_propostas.py; dois cliques abrem o formulario). O VENDEDOR
(so leitura) ve o historico de propostas inteiro, no mesmo card, sem acoes. Um formulario aberto por vez na ficha.
O painel da ficha rola na vertical, e o endereco aparece retraido (uma linha por extenso) com a opcao de expandir
nos campos individuais.
"""

from __future__ import annotations

import re
from typing import Callable

import pandas as pd
from PySide6.QtCore import QDate, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core import clientes as clientes_mod
from core import consulta_externa as consulta_mod
from core import data_store as bd
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import vendas as vendas_mod
from core import vendedores as vendedores_mod
from core.formatting import (
    formatar_data,
    formatar_endereco,
    formatar_reais,
    iniciais_do_nome,
)
from core.endereco import UFS_VALIDAS
from core.validators import apenas_digitos, cpf_cnpj_valido, email_valido
from desktop.vigia_do_arquivo import VigiaDoArquivo
from desktop.widgets.botao_copiar import BotaoCopiar
from desktop.widgets.botao_icone_link import BotaoIconeLink
from desktop.widgets.botao_recarregar import criar_botao_recarregar
from desktop.widgets.cabecalho_retratil import CabecalhoRetratil
from desktop.widgets.campo_data import CampoData, ler_periodo
from desktop.widgets.campo_invalido import limpar_invalido, marcar_invalido
from desktop.espera import rodar_esperando
from desktop.widgets.combo_travavel import ComboTravavel
from desktop.widgets.formatters import conectar_mascara, formatar_cep_parcial, formatar_cpf_cnpj_parcial, formatar_telefone_parcial
from desktop.widgets.identidade_usuario import _Avatar
from desktop.widgets.lista_clientes import ListaClientes, rotulo_do_tipo
from desktop.widgets.lista_de_propostas import ListaDePropostas
from desktop.widgets.lista_de_vendas import FaixaDeAviso, ListaDeVendas, resumo_por_status
from desktop.widgets.quebra_texto import texto_quebravel
from desktop.widgets.rotulo_uma_linha import RotuloUmaLinha

_TEXTO_PADRAO_PAINEL = "Selecione um cliente na lista ao lado, ou cadastre um novo."

_MARGEM_PAINEL = 10  # em volta do conteudo do painel do cliente: da espaco pra sombra do cartao


_TAMANHO_DO_AVATAR = 40  # maior que o da barra lateral: aqui e o foco da tela

# host -> nome curto pro link de rede social ("instagram.com/fulano" -> "Instagram ↗")
_REDES_CONHECIDAS = {
    "instagram.com": "Instagram", "facebook.com": "Facebook", "wa.me": "WhatsApp",
    "tiktok.com": "TikTok", "linkedin.com": "LinkedIn", "twitter.com": "Twitter", "x.com": "X",
    "youtube.com": "YouTube",
}


def _link_da_rede_social(texto: str) -> tuple[str, str] | None:
    """Se `texto` parece uma URL de verdade, devolve (rótulo curto, URL) pro link. Um
    handle solto ("@fulano123", sem domínio) devolve None: mostra só como texto, sem
    link - nunca inventa um destino pra abrir."""
    bruto = (texto or "").strip()
    if not bruto:
        return None
    alvo = bruto if bruto.lower().startswith(("http://", "https://")) else f"https://{bruto}"
    host = QUrl(alvo).host().lower().removeprefix("www.")
    if not host or "." not in host:
        return None
    for dominio, nome in _REDES_CONHECIDAS.items():
        if host == dominio or host.endswith("." + dominio):
            return nome, alvo
    return host, alvo


def _numero_whatsapp(celular: str) -> str | None:
    """Os dígitos do celular prontos pro link do WhatsApp (wa.me), com o "55" do Brasil
    na frente quando faltar (10 ou 11 dígitos = DDD+número, sem DDI). None se não
    parecer um número de verdade - nunca monta um link que provavelmente falha."""
    digitos = apenas_digitos(celular)
    if len(digitos) in (10, 11):
        return "55" + digitos
    if len(digitos) in (12, 13) and digitos.startswith("55"):
        return digitos
    return None


def _resumo_do_cliente(historico: pd.DataFrame) -> dict:
    """Números da faixa de resumo: total de propostas, quantas aprovadas (a categoria
    completa - Efetivado incluso), valor aprovado e a data da proposta mais recente
    (qualquer status: é "última atividade", não "última decisão")."""
    total = len(historico)
    if total == 0:
        return {"total": 0, "aprovadas": 0, "valor_aprovado": 0.0, "ultima_atividade": None}
    categoria = historico["STATUS"].map(propostas_mod.categoria_status)
    aprovada = categoria == "Aprovado"
    return {
        "total": total,
        "aprovadas": int(aprovada.sum()),
        "valor_aprovado": float(historico.loc[aprovada, "VALOR (R$)"].sum()),
        "ultima_atividade": pd.to_datetime(historico["DATA"], errors="coerce").max(),
    }


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _resumo_com_vendas(vendas: list[vendas_mod.ResumoDaVenda], historico: pd.DataFrame, antigas: int) -> str:
    """A faixa de resumo contando VENDAS: quantas e como estao, o valor ja efetivado, as propostas de antes das
    vendas (se houver) e a ultima atividade (a proposta ou a venda mais recente)."""
    if not vendas and not antigas:
        return "Nenhuma venda registrada ainda."
    partes = []
    if len(vendas) == 1:
        partes.append(f"1 venda {resumo_por_status(vendas).removeprefix('1 ')}")
    elif vendas:
        partes.append(f"{len(vendas)} vendas ({resumo_por_status(vendas).replace(' · ', ', ')})")
    else:
        partes.append("nenhuma venda ainda")
    efetivado = sum(p.valor or 0 for v in vendas for p in v.propostas if p.status == vendas_mod.PROPOSTA_EFETIVADA)
    if efetivado:
        partes.append(f"{formatar_reais(efetivado)} efetivado")
    if antigas:
        partes.append(_plural(antigas, "proposta de antes das vendas", "propostas de antes das vendas"))
    datas = [*pd.to_datetime(historico["DATA"], errors="coerce"), *(v.data_criacao for v in vendas)]
    datas = [d for d in datas if d is not None and not pd.isna(d)]
    partes.append(f"última atividade {_formatar_ultima_atividade(max(datas) if datas else None)}")
    return " · ".join(partes)


def _formatar_ultima_atividade(data) -> str:
    """Dias desde `data` (a DATA de uma proposta, não a coluna TEMPO - por isso não
    reaproveita formatar_tempo, que lê "Encerrado"/"N dias" já calculados)."""
    if data is None or pd.isna(data):
        return "—"
    dias = (pd.Timestamp.today().normalize() - pd.Timestamp(data).normalize()).days
    if dias < 0:
        return "data futura"
    if dias == 0:
        return "hoje"
    return "há 1 dia" if dias == 1 else f"há {dias} dias"


class FichaClienteScreen(QWidget):
    # lancou, editou, duplicou ou excluiu uma proposta aqui: quem mostra algo derivado das
    # propostas (o selo da barra lateral) pode se atualizar
    dados_atualizados = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)

        self._cpf_selecionado: str | None = None
        self._modo_leitura_cliente = True  # False = dados do cliente (grade de campos) em edicao
        self._modo_novo_cliente = False  # True = a ficha esta em branco, editando um cliente AINDA NAO salvo
        self._vigia = VigiaDoArquivo()
        self._dados_mostrar_vazios = False  # link "+N campos vazios" (campos NAO essenciais da grade)
        self._endereco_estava_expandido = False  # lembrado ao forcar expandido durante a edicao (ver _aplicar_modo_edicao_cliente)
        self._endereco_forcado_expandido = False
        self._historico_atual: pd.DataFrame = pd.DataFrame()  # valores "crus" (indice = posicao real no arquivo)
        self._vendas_do_cliente: list[vendas_mod.ResumoDaVenda] = []
        # o VENDEDOR (so leitura) ve o historico de propostas inteiro, sem os cards de venda (que sao de edicao)
        self._so_historico = sessao_mod.eh_vendedor()
        # CPFs (so digitos) de quem tem proposta em aberto - pinta a bolinha nos cards de cliente.
        # Fica em cache: a lista e refeita a cada tecla da busca, e reler as propostas a cada
        # vez seria lento; so se relê quando algo pode ter mudado (ver _invalidar_em_aberto)
        self._cpfs_em_aberto: set[str] = set()
        self._em_aberto_desatualizado = True
        # ultimo periodo (de, ate, avisos) aplicado na lista - digitar uma data
        # dispara um evento por tecla, e so vale reler a lista quando o que
        # valeria mudou de fato (ex.: "15/0" -> "15/03/" nao muda nada)
        self._estado_periodo: tuple = (None, None, ())

        layout_principal = QVBoxLayout(self)
        layout_principal.setContentsMargins(24, 24, 24, 24)
        layout_principal.setSpacing(16)

        cabecalho = QHBoxLayout()
        titulo = QLabel("🗂️ Ficha de Cliente")
        titulo.setProperty("role", "titulo")
        cabecalho.addWidget(titulo)
        cabecalho.addStretch()
        self._botao_recarregar = criar_botao_recarregar(self._ao_recarregar)
        cabecalho.addWidget(self._botao_recarregar)
        layout_principal.addLayout(cabecalho)

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
        self._botao_novo_cliente.clicked.connect(self._iniciar_novo_cliente)
        coluna_lista.addWidget(self._botao_novo_cliente)

        corpo.addLayout(coluna_lista, 1)

        self._painel_stack = QStackedWidget()
        self._painel_stack.addWidget(self._construir_pagina_vazia())  # indice 0
        self._painel_stack.addWidget(self._construir_pagina_ficha())  # indice 1
        corpo.addWidget(self._painel_stack, 2)

        layout_principal.addLayout(corpo, stretch=1)

        # um formulario aberto por vez na ficha: o de um card de venda ou o de uma proposta de antes das vendas (que
        # se guia pela posicao da proposta no arquivo, e ela muda quando uma proposta de venda e excluida)
        self.lista_vendas.antes_de_editar = self.lista_antigas.liberar
        self.lista_antigas.antes_de_editar = self.lista_vendas.liberar

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
        self._botao_menu_cliente.setVisible(False)  # o menu "..." so tem "Excluir cliente"
        self._botao_nova_venda.setVisible(False)
        for parte in (self._titulo_vendas, self.lista_vendas, self._dica_antigas):
            parte.setVisible(False)
        # dois cliques num card do historico seguem abrindo a proposta: pro VENDEDOR, o formulario travado (sem
        # editar), e e por ele que ele ve meses/observacoes

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
        layout.setSpacing(12)
        self._rolagem_ficha.setWidget(conteudo)
        layout_pagina.addWidget(self._rolagem_ficha, stretch=1)

        cartao = QFrame()
        cartao.setProperty("role", "card")
        # sem sombra: o card segue o mesmo visual FLAT (borda + cantos arredondados, sem
        # "flutuar") dos cards de proposta em Todas as Propostas (DelegateCartao) - lá
        # tambem nao ha sombra, so contorno.
        layout_cartao = QVBoxLayout(cartao)
        layout_cartao.setContentsMargins(16, 14, 16, 14)
        layout_cartao.setSpacing(10)

        # -- cabecalho: so avatar + nome + Editar/OK/Cancelar + "..." com Excluir (menos
        # facil de clicar sem querer que um botao vermelho colado no Editar) - CPF, Tipo,
        # Vendedor e Cadastrado em viraram campos DA GRADE, ver abaixo -----------------
        cabecalho_ficha = QHBoxLayout()
        cabecalho_ficha.setSpacing(12)
        self._avatar = _Avatar("")
        cabecalho_ficha.addWidget(self._avatar)

        self._campo_nome = QLineEdit()
        self._campo_nome.setProperty("role", "subtitulo")
        self._campo_nome.setReadOnly(True)
        cabecalho_ficha.addWidget(self._campo_nome, 1)

        self._botao_editar_cliente = QPushButton("Editar")
        self._botao_editar_cliente.setProperty("role", "botao_primario")
        self._botao_editar_cliente.clicked.connect(self._alternar_edicao_cliente)
        cabecalho_ficha.addWidget(self._botao_editar_cliente)

        self._botao_ok_cliente = QPushButton("OK")
        self._botao_ok_cliente.setProperty("role", "botao_primario")
        self._botao_ok_cliente.clicked.connect(self._salvar_edicao_cliente)
        self._botao_ok_cliente.setVisible(False)
        cabecalho_ficha.addWidget(self._botao_ok_cliente)

        self._botao_cancelar_cliente = QPushButton("Cancelar")
        self._botao_cancelar_cliente.clicked.connect(self._cancelar_edicao_cliente)
        self._botao_cancelar_cliente.setVisible(False)
        cabecalho_ficha.addWidget(self._botao_cancelar_cliente)

        self._botao_menu_cliente = QPushButton("⋯")
        self._botao_menu_cliente.setFixedWidth(34)
        self._botao_menu_cliente.setToolTip("Mais ações")
        self._menu_cliente = QMenu(self._botao_menu_cliente)
        self._acao_excluir_cliente = self._menu_cliente.addAction("Excluir cliente")
        self._acao_excluir_cliente.triggered.connect(self._excluir_cliente)
        self._botao_menu_cliente.setMenu(self._menu_cliente)
        cabecalho_ficha.addWidget(self._botao_menu_cliente)
        layout_cartao.addLayout(cabecalho_ficha)

        # -- resumo: numero de propostas, aprovadas, valor aprovado, ultima atividade -
        # responde "esse cliente vale a pena?" sem abrir nada
        self._resumo_label = QLabel("")
        self._resumo_label.setProperty("role", "secundario")
        self._resumo_label.setWordWrap(True)
        layout_cartao.addWidget(self._resumo_label)

        # -- grade de dados: CPF/CNPJ, Nascimento, Tipo, Celular, E-mail, Vendedor, Rede
        # social, Vinculado a, Cadastrado em, Nome do pai, Nome da mãe, Profissão - todos
        # numa unica grade de 3 colunas (pedido do usuario, comparando com uma versao
        # anterior do app). Cada campo e sempre o MESMO widget em leitura/edicao (so
        # trava/destrava - ver _aplicar_modo_edicao_cliente), com a MESMA caixa nos dois
        # modos. CPF/Nascimento/Tipo/Celular/E-mail/Vendedor/Cadastrado em sao
        # "essenciais" (sempre visiveis, mesmo vazios); Rede social/Vinculado a/Nome do
        # pai/Nome da mae/Profissao somem quando vazios em LEITURA (ver
        # _reordenar_grade_dados) - os outros reocupam o lugar, sem deixar buraco.
        self._grade_dados = self._nova_grade()
        layout_cartao.addLayout(self._grade_dados)

        self._campo_cpf = QLineEdit()
        self._campo_cpf.setReadOnly(True)
        self._campo_cpf.setMaximumWidth(170)
        conectar_mascara(self._campo_cpf, formatar_cpf_cnpj_parcial)
        self._botao_buscar_cnpj = self._criar_botao_buscar(self._buscar_cnpj)
        self._campo_cpf.textChanged.connect(self._atualizar_botoes_buscar)
        wrap_cpf, self._botao_copiar_cpf = self._criar_campo_com_widget(
            "CPF/CNPJ", self._campo_cpf, lambda: self._cpf_selecionado or "", extras=[self._botao_buscar_cnpj]
        )

        self._campo_nascimento = CampoData()
        self._campo_nascimento.definir_somente_leitura(True)
        self._campo_nascimento.setMaximumWidth(140)  # só o tamanho de "dd/mm/aaaa" + o botão de calendário
        wrap_nascimento, self._botao_copiar_nascimento = self._criar_campo_com_widget(
            "Nascimento", self._campo_nascimento, lambda: self._campo_nascimento.texto()
        )

        self._campo_tipo = ComboTravavel()
        self._campo_tipo.addItems(clientes_mod.TIPO_OPCOES)
        self._campo_tipo.definir_travado(True)
        wrap_tipo, _ = self._criar_campo_com_widget("Tipo", self._campo_tipo)

        self._campo_celular = QLineEdit()
        self._campo_celular.setReadOnly(True)
        self._campo_celular.setMaximumWidth(140)
        conectar_mascara(self._campo_celular, formatar_telefone_parcial)
        self._botao_whatsapp = BotaoIconeLink("whatsapp", self._abrir_whatsapp)
        wrap_celular, self._botao_copiar_celular = self._criar_campo_com_widget(
            "Celular", self._campo_celular, lambda: self._campo_celular.text(), extras=[self._botao_whatsapp]
        )

        # e-mail: em LEITURA mostra um QLabel com link(s) clicavel(is) - o campo pode ter
        # mais de um endereco (ver _texto_com_link_de_email), cada um na sua linha; em
        # EDICAO vira QLineEdit comum. QLineEdit nao renderiza HTML/links, por isso os
        # dois modos precisam de widgets diferentes (trocados por um QStackedWidget) -
        # mas o rotulo ganha a MESMA caixa do QLineEdit (role "campo_valor" + propriedade
        # "caixa"), pro campo nao mudar de formato ao trocar entre leitura e edicao.
        self._pilha_email = QStackedWidget()
        self._pilha_email.setProperty("role", "transparente")
        self._rotulo_email = self._criar_rotulo_valor()
        self._rotulo_email.setProperty("caixa", True)
        self._preparar_rotulo_com_link(self._rotulo_email)
        self._campo_email = QLineEdit()
        self._campo_email.textChanged.connect(self._validar_email_ao_vivo_cliente)
        self._pilha_email.addWidget(self._rotulo_email)
        self._pilha_email.addWidget(self._campo_email)
        wrap_email, self._botao_copiar_email = self._criar_campo_com_widget(
            "E-mail", self._pilha_email, lambda: self._campo_email.text()
        )

        self._campo_vendedor = ComboTravavel()
        self._campo_vendedor.definir_travado(True)
        wrap_vendedor, _ = self._criar_campo_com_widget("Vendedor", self._campo_vendedor)

        # rede social: SEMPRE o mesmo QLineEdit (mostra o link/handle cru, igual editando)
        # - o botao do lado abre o link (mesmo padrao do WhatsApp), com o nome da rede
        # detectada aparece no tooltip do icone ("Abrir no Instagram", "Abrir no
        # Facebook"...); sem link reconhecido, o botao some
        self._campo_rede_social = QLineEdit()
        self._campo_rede_social.setReadOnly(True)
        self._campo_rede_social.setMaximumWidth(260)
        self._campo_rede_social.textChanged.connect(self._atualizar_botao_rede_social)
        self._botao_abrir_rede_social = BotaoIconeLink("link_externo", self._abrir_rede_social)
        self._botao_abrir_rede_social.setVisible(False)
        wrap_rede_social, self._botao_copiar_rede_social = self._criar_campo_com_widget(
            "Rede social", self._campo_rede_social, lambda: self._campo_rede_social.text(),
            extras=[self._botao_abrir_rede_social],
        )

        self._campo_vinculado = QLineEdit()
        self._campo_vinculado.setReadOnly(True)
        self._campo_vinculado.setPlaceholderText("—")
        self._campo_vinculado.setMaximumWidth(260)
        wrap_vinculado, self._botao_copiar_vinculado = self._criar_campo_com_widget(
            "Vinculado a", self._campo_vinculado, lambda: self._campo_vinculado.text()
        )

        self._rotulo_cadastro = QLabel("—")  # nunca editavel - a data e gravada so no cadastro
        self._rotulo_cadastro.setProperty("role", "campo_valor")
        self._rotulo_cadastro.setProperty("caixa", True)
        wrap_cadastro, self._botao_copiar_cadastro = self._criar_campo_com_widget(
            "Cadastrado em", self._rotulo_cadastro, lambda: self._rotulo_cadastro.text()
        )

        self._campo_nome_pai = QLineEdit()
        self._campo_nome_pai.setReadOnly(True)
        self._campo_nome_pai.setPlaceholderText("—")
        self._campo_nome_pai.setMaximumWidth(260)
        wrap_pai, self._botao_copiar_pai = self._criar_campo_com_widget(
            "Nome do pai", self._campo_nome_pai, lambda: self._campo_nome_pai.text()
        )
        self._campo_nome_mae = QLineEdit()
        self._campo_nome_mae.setReadOnly(True)
        self._campo_nome_mae.setPlaceholderText("—")
        self._campo_nome_mae.setMaximumWidth(260)
        wrap_mae, self._botao_copiar_mae = self._criar_campo_com_widget(
            "Nome da mãe", self._campo_nome_mae, lambda: self._campo_nome_mae.text()
        )
        self._campo_profissao = QLineEdit()
        self._campo_profissao.setReadOnly(True)
        self._campo_profissao.setPlaceholderText("—")
        self._campo_profissao.setMaximumWidth(260)
        wrap_profissao, self._botao_copiar_profissao = self._criar_campo_com_widget(
            "Profissão", self._campo_profissao, lambda: self._campo_profissao.text()
        )

        # ordem de exibicao (linha 1: CPF/Nascimento/Tipo; linha 2: Celular/E-mail/
        # Vendedor; linha 3: Rede social/Vinculado a/Cadastrado em; linha 4: pai/mae/
        # profissao) - a grade so recebe os widgets de verdade em _reordenar_grade_dados,
        # remontada a cada mudanca, pra um campo escondido nunca deixar buraco na posicao
        # fixa que ele teria.
        self._campos_essenciais_dados = [wrap_cpf, wrap_nascimento, wrap_tipo, wrap_celular, wrap_email, wrap_vendedor, wrap_cadastro]
        self._campos_opcionais_dados = [wrap_rede_social, wrap_vinculado, wrap_pai, wrap_mae, wrap_profissao]
        self._todos_campos_dados = [
            wrap_cpf, wrap_nascimento, wrap_tipo,
            wrap_celular, wrap_email, wrap_vendedor,
            wrap_rede_social, wrap_vinculado, wrap_cadastro,
            wrap_pai, wrap_mae, wrap_profissao,
        ]

        self._link_dados_vazios = QLabel("")
        self._link_dados_vazios.setProperty("role", "link_discreto")
        self._link_dados_vazios.setTextFormat(Qt.TextFormat.RichText)
        self._link_dados_vazios.linkActivated.connect(self._ao_clicar_link_dados_vazios)
        layout_cartao.addWidget(self._link_dados_vazios)

        # -- Endereco: o mesmo widget retratil de sempre, agora como secao propria
        # (nao mais numa grade compartilhada com os outros campos) -------------------
        self._cabecalho_endereco = CabecalhoRetratil(
            "Endereço",
            dica_expandir="Mostrar os campos do endereço (CEP, logradouro, número...)",
            dica_recolher="Voltar ao endereço em uma linha",
            papel_do_titulo="titulo_secao",
        )
        self._cabecalho_endereco.toggled.connect(self._ao_alternar_endereco)
        linha_legenda_endereco = QHBoxLayout()
        linha_legenda_endereco.addWidget(self._cabecalho_endereco)
        linha_legenda_endereco.addStretch()

        # contorno igual aos outros campos (pedido do usuario) - a caixa fica no
        # CONTENTOR (WA_StyledBackground, senao um QWidget comum nao pinta borda de QSS),
        # nao no RotuloUmaLinha: o sizeHint dele mede so o texto, sem contar padding/borda
        self._endereco_resumo = QWidget()
        self._endereco_resumo.setProperty("role", "caixa_campo")
        self._endereco_resumo.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        linha_resumo, self._campo_endereco_completo = self._linha_copiavel_compacta()
        linha_resumo.setContentsMargins(8, 6, 8, 6)
        self._endereco_resumo.setLayout(linha_resumo)

        self._secao_endereco = QWidget()
        self._secao_endereco.setProperty("role", "transparente")
        coluna_endereco = QVBoxLayout(self._secao_endereco)
        coluna_endereco.setContentsMargins(0, 0, 0, 0)
        coluna_endereco.setSpacing(2)  # o mesmo espaco entre legenda e valor dos outros campos
        coluna_endereco.addLayout(linha_legenda_endereco)
        coluna_endereco.addWidget(self._endereco_resumo)

        # expandido: cada campo do endereco EDITAVEL (mesmo padrao Editar/OK/Cancelar do
        # resto do card - ver _aplicar_modo_edicao_cliente), com seu botao de copiar (a
        # ideia e copiar um de cada vez pra colar em outro sistema). Posicao FIXA na
        # grade (nao passa pelo "esconde se vazio" da grade de dados la em cima - os 7
        # campos sempre aparecem juntos quando o endereco esta expandido).
        self._endereco_campos = QWidget()
        self._endereco_campos.setProperty("role", "transparente")
        grade_endereco = self._nova_grade()
        grade_endereco.setContentsMargins(0, 0, 0, 0)
        self._endereco_campos.setLayout(grade_endereco)
        self._endereco_campos.setVisible(False)
        coluna_endereco.addWidget(self._endereco_campos)
        layout_cartao.addWidget(self._secao_endereco)

        self._campo_cep = QLineEdit()
        self._campo_cep.setPlaceholderText("00000-000")
        conectar_mascara(self._campo_cep, formatar_cep_parcial)
        self._botao_buscar_cep = self._criar_botao_buscar(self._buscar_cep)
        self._campo_cep.textChanged.connect(self._atualizar_botoes_buscar)
        wrap_cep, self._botao_copiar_cep = self._criar_campo_com_widget(
            "CEP", self._campo_cep, lambda: self._campo_cep.text(), extras=[self._botao_buscar_cep]
        )
        grade_endereco.addWidget(wrap_cep, 0, 0)

        self._campo_logradouro = QLineEdit()
        self._campo_logradouro.setPlaceholderText("—")
        wrap_logradouro, self._botao_copiar_logradouro = self._criar_campo_com_widget(
            "Logradouro", self._campo_logradouro, lambda: self._campo_logradouro.text()
        )
        grade_endereco.addWidget(wrap_logradouro, 0, 1)

        self._campo_numero = QLineEdit()
        self._campo_numero.setPlaceholderText("—")
        wrap_numero, self._botao_copiar_numero = self._criar_campo_com_widget(
            "Número", self._campo_numero, lambda: self._campo_numero.text()
        )
        grade_endereco.addWidget(wrap_numero, 0, 2)

        self._campo_complemento = QLineEdit()
        self._campo_complemento.setPlaceholderText("—")
        wrap_complemento, self._botao_copiar_complemento = self._criar_campo_com_widget(
            "Complemento", self._campo_complemento, lambda: self._campo_complemento.text()
        )
        grade_endereco.addWidget(wrap_complemento, 1, 0)

        self._campo_bairro = QLineEdit()
        self._campo_bairro.setPlaceholderText("—")
        wrap_bairro, self._botao_copiar_bairro = self._criar_campo_com_widget(
            "Bairro", self._campo_bairro, lambda: self._campo_bairro.text()
        )
        grade_endereco.addWidget(wrap_bairro, 1, 1)

        # Cidade e UF dividem a 3a coluna (a UF e curta) - assim a grade
        # continua com as mesmas 3 colunas da grade de dados, la em cima
        self._campo_cidade = QLineEdit()
        self._campo_cidade.setPlaceholderText("—")
        wrap_cidade, self._botao_copiar_cidade = self._criar_campo_com_widget(
            "Cidade", self._campo_cidade, lambda: self._campo_cidade.text()
        )
        self._campo_uf = ComboTravavel()
        self._campo_uf.addItem("")  # UF e opcional
        self._campo_uf.addItems(sorted(UFS_VALIDAS))
        self._campo_uf.definir_travado(True)
        wrap_uf, _ = self._criar_campo_com_widget("UF", self._campo_uf)
        linha_cidade_uf = QHBoxLayout()
        linha_cidade_uf.setSpacing(12)
        linha_cidade_uf.addWidget(wrap_cidade, 3)
        linha_cidade_uf.addWidget(wrap_uf, 1)
        grade_endereco.addLayout(linha_cidade_uf, 1, 2)

        # so aparece pra quem tem endereco antigo que a migracao nao separou - em
        # leitura, um aviso (so texto, role "secundario"); editando, vira campo de
        # verdade (mesmo padrao do e-mail - QStackedWidget - so que aqui pra dar pra
        # apagar o texto depois de preencher CEP/Logradouro/etc acima)
        self._aviso_endereco_revisar = QLabel("")
        self._aviso_endereco_revisar.setProperty("role", "secundario")
        self._aviso_endereco_revisar.setWordWrap(True)

        self._campo_endereco_revisar = QLineEdit()
        self._campo_endereco_revisar.setToolTip(
            "Endereço como estava antes de ser separado em campos. Preencha CEP, Logradouro, "
            "Número, Bairro e Cidade acima e depois apague este texto."
        )
        wrap_endereco_revisar, _ = self._criar_campo_com_widget("Endereço original (revisar)", self._campo_endereco_revisar)

        self._pilha_endereco_revisar = QStackedWidget()
        self._pilha_endereco_revisar.setProperty("role", "transparente")
        self._pilha_endereco_revisar.addWidget(self._aviso_endereco_revisar)
        self._pilha_endereco_revisar.addWidget(wrap_endereco_revisar)
        self._pilha_endereco_revisar.setVisible(False)
        layout_cartao.addWidget(self._pilha_endereco_revisar)

        layout.addWidget(cartao)

        # os mesmos cards da tela Vendas; sem barra de rolagem propria (quem rola e o painel)
        self._titulo_vendas = QLabel("Vendas do cliente")
        self._titulo_vendas.setProperty("role", "subtitulo")
        layout.addWidget(self._titulo_vendas)
        self.lista_vendas = ListaDeVendas(self._rolagem_ficha, conteudo, com_ficha=False, uma_coluna=True)
        self.lista_vendas.gravou.connect(self._depois_de_gravar_venda)
        layout.addWidget(self.lista_vendas)

        self._titulo_historico = QLabel("Histórico de propostas" if self._so_historico else "Propostas de antes das vendas")
        self._titulo_historico.setProperty("role", "subtitulo")
        layout.addWidget(self._titulo_historico)
        self._dica_antigas = QLabel(
            "Ainda não estão em nenhuma venda. Para juntá-las numa venda, use \"Juntar em vendas…\" na tela Vendas."
        )
        self._dica_antigas.setProperty("role", "secundario")
        self._dica_antigas.setWordWrap(True)
        layout.addWidget(self._dica_antigas)

        self._historico_vazio = QLabel("Nenhuma proposta registrada para este cliente ainda.")
        self._historico_vazio.setProperty("role", "secundario")
        layout.addWidget(self._historico_vazio)

        # o mesmo card de proposta de Todas as Propostas, numa coluna so; sem barra de rolagem propria (quem rola e o
        # painel). Excluir so de dentro do formulario do card aberto, com confirmacao
        self.lista_antigas = ListaDePropostas(self._rolagem_ficha, self._linha_da_proposta, conteudo, com_ficha=False,
                                              uma_coluna=True)
        self.lista_antigas.gravou.connect(self._depois_de_gravar_venda)
        layout.addWidget(self.lista_antigas)
        layout.addStretch(1)  # conteudo curto fica no topo, sem esticar o cartao

        # fixos embaixo (fora da rolagem), alinhados com o cartao
        self._faixa_aviso = FaixaDeAviso()
        self._linha_aviso = QHBoxLayout()
        self._linha_aviso.setContentsMargins(_MARGEM_PAINEL, 0, _MARGEM_PAINEL, 0)
        self._linha_aviso.addWidget(self._faixa_aviso)
        layout_pagina.addLayout(self._linha_aviso)
        self._linha_botoes_ficha = QHBoxLayout()
        self._linha_botoes_ficha.setContentsMargins(_MARGEM_PAINEL, 0, _MARGEM_PAINEL, _MARGEM_PAINEL)
        self._linha_botoes_ficha.addStretch()
        self._botao_nova_venda = QPushButton("+ Nova venda")
        self._botao_nova_venda.setProperty("role", "botao_primario")
        self._botao_nova_venda.setToolTip("Nova venda para este cliente")
        self._botao_nova_venda.clicked.connect(self._nova_venda)
        self._linha_botoes_ficha.addWidget(self._botao_nova_venda)
        layout_pagina.addLayout(self._linha_botoes_ficha)
        self._rolagem_ficha.verticalScrollBar().rangeChanged.connect(self._ajustar_margem_dos_botoes)

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
    def _criar_campo_com_widget(
        titulo: str, widget: QWidget, copiar: Callable[[], str] | None = None, extras: list[QWidget] | None = None
    ) -> tuple[QWidget, BotaoCopiar | None]:
        """Legenda + um widget de valor JÁ PRONTO (QLineEdit, CampoData, ComboTravavel...)
        - usado por todos os campos da grade de dados da Ficha (o valor edita e trava/
        destrava, a legenda nunca muda). `copiar`: se passado, põe um BotaoCopiar do lado
        (só aparece em leitura - ver _aplicar_modo_edicao_cliente). `extras`: outros
        widgets pra por depois do botão de copiar (ex.: o botão "WhatsApp" do celular, ou
        o de abrir a rede social). Devolve (o wrapper INTEIRO - legenda incluída, pra
        poder esconder o par quando o valor estiver vazio e reposicionar os que sobraram
        sem deixar buraco, ver _reordenar_grade_dados - e o botão de copiar, ou None se
        `copiar` não foi passado)."""
        wrapper = QWidget()
        wrapper.setProperty("role", "transparente")
        caixa = QVBoxLayout(wrapper)
        caixa.setContentsMargins(0, 0, 0, 0)
        caixa.setSpacing(2)
        legenda = QLabel(titulo)
        legenda.setProperty("role", "campo_rotulo")
        caixa.addWidget(legenda)
        if copiar is None and not extras:
            caixa.addWidget(widget)
            return wrapper, None
        linha = QHBoxLayout()
        linha.setSpacing(4)
        # stretch bem maior que o do espacador do final (1, alguns campos abaixo): senao os
        # dois disputam o espaço sobrando quase de igual pra igual e o campo fica bem mais
        # estreito que a largura maxima dele, mesmo tendo espaco de sobra na coluna
        linha.addWidget(widget, 100)
        botao = None
        if copiar is not None:
            botao = BotaoCopiar(copiar)
            linha.addWidget(botao)
        for extra in extras or []:
            linha.addWidget(extra)
        # campo com largura maxima propria (CPF, Nascimento, Celular, Vinculado, Pai/Mae/
        # Profissao) nao deveria esticar - sem esse espacador no final, o espaco sobrando
        # empurra o campo pra direita em vez de sobrar depois do botao de copiar
        if widget.maximumWidth() < 16777215:  # 16777215 = QWIDGETSIZE_MAX (Qt nao expõe a constante ao Python)
            linha.addStretch(1)
        caixa.addLayout(linha)
        return wrapper, botao

    @staticmethod
    def _linha_copiavel_compacta() -> tuple[QHBoxLayout, RotuloUmaLinha]:
        """Valor + botao Copiar ao lado, numa linha - pro endereco por extenso: o valor
        tem o MESMO estilo e altura dos outros campos (nao a altura do botao) e ocupa so
        a largura do proprio texto, em vez de uma barra pela largura toda. So quebra em
        mais linhas se nao couber. O que o botao copia e o texto CRU guardado na
        propriedade "texto_cru" (ver _definir_valor_copiavel), nunca o que aparece no
        QLabel: la o texto tem "—" quando vazio e pontos de quebra invisiveis
        (texto_quebravel)."""
        valor = RotuloUmaLinha("—")
        valor.setProperty("role", "campo_valor")
        botao = BotaoCopiar(lambda: valor.property("texto_cru") or "")
        linha = QHBoxLayout()
        linha.setSpacing(4)
        # AlignLeft explicito (alem do AlignVCenter): deixa claro que o valor NUNCA deve
        # esticar pra preencher a linha - e o addStretch(1) no fim que ocupa o resto,
        # nao o rotulo (e exatamente a "barra pela largura toda" que este metodo existe
        # pra evitar, ver docstring)
        linha.addWidget(valor, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        linha.addWidget(botao, alignment=Qt.AlignmentFlag.AlignVCenter)
        linha.addStretch(1)
        return linha, valor

    @staticmethod
    def _definir_valor_copiavel(rotulo: QLabel, texto: str) -> None:
        rotulo.setProperty("texto_cru", texto)
        rotulo.setText(texto_quebravel(texto) or "—")

    # -- contato: WhatsApp, e-mail e rede social clicaveis --------------------

    @staticmethod
    def _preparar_rotulo_com_link(rotulo: QLabel) -> None:
        """Deixa `rotulo` pronto pra mostrar um link clicavel quando o texto vier com
        HTML (ver _texto_com_link_de_email) - texto puro ("—", sem valor) continua
        aparecendo normal."""
        rotulo.setTextFormat(Qt.TextFormat.RichText)
        rotulo.setOpenExternalLinks(True)
        rotulo.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)

    _PADRAO_EMAIL = re.compile(r"[^\s,;]+@[^\s,;]+\.[^\s,;]+")

    @staticmethod
    def _texto_com_link_de_email(email: str) -> str:
        """Normalmente 1 e-mail só - mas o campo às vezes tem mais de um, digitados juntos
        (separados por espaço, vírgula, ponto-e-vírgula ou quebra de linha), e às vezes até
        outra coisa junto (achamos um caso real com um telefone colado depois dos e-mails).
        Acha cada trecho que PARECE um e-mail (via regex, sem espaço dentro) e cada um vira
        o seu próprio link de mailto, numa linha - o que sobrar (não é nenhum e-mail
        encontrado) aparece como texto puro na última linha, sem virar um mailto: quebrado
        nem ser cortado no meio (um telefone "+55 77 9208-1246" tem espaço por dentro -
        dividir por espaço/vírgula ignorando isso o fragmentaria em 3 pedaços sem sentido)."""
        limpo = (email or "").strip()
        if not limpo:
            return "—"
        enderecos = FichaClienteScreen._PADRAO_EMAIL.findall(limpo)
        if not enderecos:
            return texto_quebravel(limpo)  # nada parece e-mail: mostra como veio, sem tentar link
        linhas = [f'<a href="mailto:{e}">{texto_quebravel(e)}</a>' for e in enderecos]
        sobra = limpo
        for endereco in enderecos:
            sobra = sobra.replace(endereco, " ")
        sobra = " ".join(sobra.split())
        if sobra:
            linhas.append(texto_quebravel(sobra))
        return "<br>".join(linhas)

    def _abrir_whatsapp(self) -> None:
        numero = self._botao_whatsapp.property("numero_whatsapp")
        if numero:
            QDesktopServices.openUrl(QUrl(f"https://wa.me/{numero}"))

    def _atualizar_botao_rede_social(self, texto: str) -> None:
        """O botao (um icone de "abrir link") mostra no tooltip a rede detectada ("Abrir
        no Instagram", "Abrir no Facebook"...) e some quando o texto nao parece um link
        de verdade - mesmo padrao do WhatsApp ao lado do celular, so que a rede muda de
        acordo com o link (varias sao reconhecidas, ver _REDES_CONHECIDAS)."""
        link = _link_da_rede_social(texto)
        self._botao_abrir_rede_social.setVisible(link is not None)
        if link is not None:
            self._botao_abrir_rede_social.setToolTip(f"Abrir no {link[0]}")

    def _abrir_rede_social(self) -> None:
        link = _link_da_rede_social(self._campo_rede_social.text())
        if link is not None:
            QDesktopServices.openUrl(QUrl(link[1]))

    # -- grade de dados: campos NAO essenciais vazios ficam escondidos atras do link ---

    @staticmethod
    def _definir_campo_opcional(wrapper: QWidget, campo: QLineEdit, texto: str) -> None:
        limpo = (texto or "").strip()
        wrapper.setProperty("vazio", not limpo)
        campo.setText(limpo)
        # setText() deixa o cursor no FIM - num campo estreito (a grade so tem 1/3 da
        # largura do card), um texto comprido apareceria cortado pelo começo em vez do
        # fim; volta o cursor pro inicio, pra sempre mostrar o começo do texto
        campo.setCursorPosition(0)

    def _ao_clicar_link_dados_vazios(self, _href: str = "") -> None:
        self._dados_mostrar_vazios = not self._dados_mostrar_vazios
        self._atualizar_visibilidade_dados()

    def _reordenar_grade_dados(self) -> None:
        """Remonta a grade só com os campos visíveis, na ORDEM de exibição (campos
        essenciais sempre entram; os NÃO essenciais só quando têm valor, "mostrar
        vazios" estiver ligado, OU o card estiver em EDIÇÃO - editar exige ver todos,
        mesmo vazios), preenchendo 3 por linha sem pular posição - diferente de só
        chamar setVisible(), isso nunca deixa buraco onde um campo escondido estaria
        (os campos depois dele reocupam o lugar)."""
        mostrar_tudo = self._dados_mostrar_vazios or not self._modo_leitura_cliente
        essenciais = set(self._campos_essenciais_dados)
        visiveis = [
            w for w in self._todos_campos_dados
            if w in essenciais or mostrar_tudo or not w.property("vazio")
        ]
        for wrapper in self._todos_campos_dados:
            self._grade_dados.removeWidget(wrapper)
        for indice, wrapper in enumerate(visiveis):
            self._grade_dados.addWidget(wrapper, indice // 3, indice % 3)
            wrapper.setVisible(True)
        for wrapper in self._todos_campos_dados:
            if wrapper not in visiveis:
                wrapper.setVisible(False)

    def _atualizar_visibilidade_dados(self) -> None:
        self._reordenar_grade_dados()
        vazios = [w for w in self._campos_opcionais_dados if w.property("vazio")]
        if not vazios or not self._modo_leitura_cliente:
            self._link_dados_vazios.setVisible(False)
            return
        self._link_dados_vazios.setVisible(True)
        if self._dados_mostrar_vazios:
            texto = "Ocultar campos vazios"
        else:
            plural = len(vazios) != 1
            texto = f"+ {len(vazios)} campo{'s' if plural else ''} vazio{'s' if plural else ''}"
        self._link_dados_vazios.setText(f'<a href="#">{texto}</a>')

    # -- endereco retratil, rolagem do painel --------------------------------

    def _ao_alternar_endereco(self, expandido: bool) -> None:
        """Retraido: o endereco numa linha (com copiar). Expandido: os 7 campos,
        cada um com o seu copiar. A escolha vale pra qualquer cliente que se abra
        depois (e uma preferencia de visualizacao, nao um dado do cliente) - EXCETO
        durante a edicao do cliente, que forca expandido (ver _aplicar_modo_edicao_cliente:
        "so mostrar o endereco em campos separados" ao editar)."""
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
        self._linha_aviso.setContentsMargins(_MARGEM_PAINEL, 0, _MARGEM_PAINEL + largura_barra, 0)

    # -- carregamento de dados ----------------------------------------------

    def showEvent(self, evento) -> None:
        super().showEvent(evento)
        # alguem pode ter cadastrado um vendedor em outra tela (Usuarios) desde a
        # ultima vez que esta tela apareceu - e uma proposta pode ter mudado de
        # status em "Todas as Propostas": a bolinha "Em aberto" precisa refletir isso
        if self._vigia.mudou_desde_a_leitura():
            self._reler_lista_e_ficha()
            return
        self._invalidar_em_aberto()
        if self._recarregar_vendedores_filtro():
            self._atualizar_lista()
        else:
            self._atualizar_indicadores_em_aberto()

    def recarregar_se_mudou(self) -> None:
        """Chamado a cada tique da janela com esta tela aberta: se a planilha mudou por fora (baixou da
        nuvem, restaurou backup, editou no Excel), rele sozinha - sem atropelar quem esta editando."""
        if self._vigia.mudou_desde_a_leitura():
            self._reler_lista_e_ficha()

    def _reler_lista_e_ficha(self) -> None:
        """Rele a lista (e o filtro de vendedores) e, se ninguem esta editando, a ficha aberta."""
        self._invalidar_em_aberto()
        self._recarregar_vendedores_filtro()
        self._atualizar_lista()
        if self._ficha_pode_ser_relida():
            self._recarregar_ficha_atual()

    def _ao_recarregar(self, *_args) -> None:
        """Botao Recarregar: rele a lista e a ficha aberta. Com algo em edicao nao salvo (dados do cliente,
        cliente novo ou proposta), pergunta antes - e so descarta se a pessoa confirmar."""
        cliente_em_edicao = not self._modo_leitura_cliente or self._modo_novo_cliente
        if cliente_em_edicao or self.tem_edicao_pendente():
            resposta = QMessageBox.question(
                self,
                "Alterações não salvas",
                "Há alterações nesta ficha que ainda não foram salvas. Recarregar descarta essas alterações. Continuar?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if resposta != QMessageBox.StandardButton.Yes:
                return
            self.lista_antigas.descartar()
            self.lista_vendas.descartar()
            if cliente_em_edicao:
                self._cancelar_edicao_cliente()  # cliente novo: volta pra pagina vazia; existente: volta pra leitura
        self._reler_lista_e_ficha()

    def _ficha_pode_ser_relida(self) -> bool:
        """A ficha aberta so e relida do disco se ninguem esta editando nada nela: dados do cliente
        destravados, cliente novo ainda nao salvo ou proposta com alteracao pendente ficam como estao."""
        return (
            self._cpf_selecionado is not None
            and self._painel_stack.currentIndex() == 1
            and self._modo_leitura_cliente
            and not self._modo_novo_cliente
            and not self.tem_edicao_pendente()
        )

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
        self._vigia.registrar_leitura()
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
            historico, vendas = self._ler_propostas_e_vendas(cpf)
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro ao carregar cliente", str(exc))
            return

        if cliente is None:
            QMessageBox.warning(self, "Cliente não encontrado", "Este cliente pode ter sido removido.")
            self._cpf_selecionado = None
            self._painel_stack.setCurrentIndex(0)
            return

        self._cpf_selecionado = cpf
        self._preencher_ficha(cliente, historico, vendas)
        self._rolagem_ficha.verticalScrollBar().setValue(0)  # outro cliente: o painel volta pro topo
        self._painel_stack.setCurrentIndex(1)

    def _preencher_ficha(
        self, cliente: dict, historico: pd.DataFrame, vendas: list[vendas_mod.ResumoDaVenda] | tuple = (),
        mesmo_cliente: bool = False,
    ) -> None:
        """`mesmo_cliente`: recarregando a ficha JA aberta (depois de editar ou
        lancar uma proposta) - o card aberto (de venda ou de proposta) e a pagina carregada
        se mantem; abrindo outro cliente, tudo comeca limpo."""
        self._preencher_cliente(cliente)
        self._preencher_propostas(historico, vendas, mesmo_cliente=mesmo_cliente)

    def _preencher_cliente(self, cliente: dict) -> None:
        # toda releitura do disco (outro cliente, ou o mesmo depois de salvar) comeca
        # em modo leitura - evita ficar com campos "destravados" mostrando dado que ja nao bate
        self._aplicar_modo_edicao_cliente(leitura=True)
        if self._modo_novo_cliente:
            # rascunho de cliente novo terminou (salvou de verdade, ou a pessoa abriu
            # outro cliente no meio do rascunho - descarta) - o "+ Nova venda"
            # tinha sumido em _iniciar_novo_cliente (nao dava pra lancar venda
            # pra quem ainda nao existia)
            self._modo_novo_cliente = False
            self._botao_nova_venda.setVisible(not self._so_historico)

        self._avatar.definir_iniciais(iniciais_do_nome(cliente["CLIENTE"]))
        # QLineEdit nao quebra linha - texto_quebravel (pontos de quebra invisiveis pra
        # QLabel) nao se aplica mais aqui, e sujaria o texto de verdade do campo
        self._campo_nome.setText(cliente["CLIENTE"])
        self._campo_cpf.setText(cliente["CPF/CNPJ"])
        self._campo_cpf.setCursorPosition(0)  # CNPJ formatado pode nao caber inteiro na caixa compacta

        self._definir_texto_tipo(cliente["TIPO"])
        self._recarregar_vendedores_do_cabecalho(cliente["VENDEDOR"] or "")

        self._rotulo_cadastro.setText(formatar_data(cliente.get("DATA CADASTRO")))

        celular = cliente["CELULAR"] or ""
        self._campo_celular.setText(celular)
        numero_whats = _numero_whatsapp(celular)
        self._botao_whatsapp.setProperty("numero_whatsapp", numero_whats)
        self._botao_whatsapp.setEnabled(bool(numero_whats))
        self._botao_whatsapp.setToolTip(
            "Abrir no WhatsApp" if numero_whats else "Celular sem DDD/dígitos suficientes para abrir o WhatsApp"
        )

        email = cliente["EMAIL"] or ""
        self._rotulo_email.setText(self._texto_com_link_de_email(email))
        self._campo_email.setText(email)
        self._campo_email.setCursorPosition(0)  # mostra o começo, nao o fim de um e-mail comprido

        # campos_opcionais_dados = [rede_social, vinculado, pai, mae, profissao] - ordem
        # em que foram criados (ver _construir_pagina_ficha)
        rede_social = cliente["REDE SOCIAL"] or ""
        self._definir_campo_opcional(self._campos_opcionais_dados[0], self._campo_rede_social, rede_social)
        self._definir_campo_opcional(self._campos_opcionais_dados[1], self._campo_vinculado, cliente["VINCULADO"])
        self._definir_campo_opcional(self._campos_opcionais_dados[2], self._campo_nome_pai, cliente["NOME DO PAI"])
        self._definir_campo_opcional(self._campos_opcionais_dados[3], self._campo_nome_mae, cliente["NOME DA MÃE"])
        self._definir_campo_opcional(self._campos_opcionais_dados[4], self._campo_profissao, cliente["PROFISSÃO"])

        nascimento_atual = cliente.get("NASCIMENTO")
        if isinstance(nascimento_atual, pd.Timestamp) and not pd.isna(nascimento_atual):
            self._campo_nascimento.definir_data(QDate(nascimento_atual.year, nascimento_atual.month, nascimento_atual.day))
        else:
            self._campo_nascimento.limpar()
        self._dados_mostrar_vazios = False
        self._atualizar_visibilidade_dados()

        self._campo_cep.setText(cliente["CEP"] or "")
        self._campo_logradouro.setText(cliente["LOGRADOURO"] or "")
        self._campo_logradouro.setCursorPosition(0)
        self._campo_numero.setText(cliente["NÚMERO"] or "")
        self._campo_complemento.setText(cliente["COMPLEMENTO"] or "")
        self._campo_complemento.setCursorPosition(0)
        self._campo_bairro.setText(cliente["BAIRRO"] or "")
        self._campo_bairro.setCursorPosition(0)
        self._campo_cidade.setText(cliente["CIDADE"] or "")
        self._campo_cidade.setCursorPosition(0)
        self._definir_texto_uf(cliente["UF"])
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
        self._pilha_endereco_revisar.setVisible(bool(texto_revisar))
        if texto_revisar:
            self._aviso_endereco_revisar.setText(
                f"⚠ Endereço a revisar (ainda não separado nos campos acima): {texto_quebravel(texto_revisar)}"
            )
        self._campo_endereco_revisar.setText(texto_revisar or "")
        self._campo_endereco_revisar.setCursorPosition(0)

    def _preencher_propostas(
        self, historico: pd.DataFrame, vendas: list[vendas_mod.ResumoDaVenda] | tuple, *,
        mesmo_cliente: bool,
    ) -> None:
        """Resumo, vendas e propostas de antes das vendas (os dados do cliente nao mudam)."""
        # guarda os valores "crus" (Timestamp/float, indice = posicao real no
        # arquivo) - os cards mostram uma versao formatada pra leitura, mas
        # editar uma proposta precisa dos valores originais
        self._historico_atual = historico
        self._vendas_do_cliente = list(vendas)
        if self._so_historico:
            antigas = historico
            self._resumo_label.setText(self._resumo_do_historico(historico))
        else:
            # as que nao estao numa venda DESTE cliente: nenhuma proposta dele fica sem aparecer
            antigas = historico[~historico["ID_VENDA"].isin({v.id for v in vendas})]
            self._resumo_label.setText(_resumo_com_vendas(self._vendas_do_cliente, historico, len(antigas)))
            if self._cpf_selecionado:
                vazio = "Nenhuma venda para este cliente ainda. Clique em \"+ Nova venda\"."
            else:
                vazio = "Salve o cliente para lançar a primeira venda."
            self.lista_vendas.definir_vendas(self._vendas_do_cliente, texto_vazio=vazio,
                                             voltar_ao_inicio=not mesmo_cliente)

        # a mais recente primeiro (na mesma data, a cadastrada por ultimo); os dias esperando resposta, pelo HISTÓRICO
        ordenado = propostas_mod.ordenar(antigas)
        if self._so_historico or ordenado.empty:  # o VENDEDOR le do Google Sheets: sem o historico (conta da DATA)
            por_indice = vendas_mod.propostas_na_lista(ordenado)
        else:
            por_indice = vendas_mod.propostas_na_lista(ordenado, (), bd.ler_historico(propostas_mod.CAMINHO_XLSX))
        self.lista_antigas.definir_propostas([por_indice[i] for i in ordenado.index],
                                             voltar_ao_inicio=not mesmo_cliente)
        self._atualizar_visibilidade_do_historico()

    @staticmethod
    def _resumo_do_historico(historico: pd.DataFrame) -> str:
        """O resumo contando propostas (o do VENDEDOR, que ve o historico inteiro)."""
        resumo = _resumo_do_cliente(historico)
        if resumo["total"] == 0:
            return "Nenhuma proposta registrada ainda."
        partes = [
            f"{resumo['total']} proposta{'s' if resumo['total'] != 1 else ''}",
            f"{resumo['aprovadas']} aprovada{'s' if resumo['aprovadas'] != 1 else ''}",
        ]
        # so mostra o valor aprovado quando ha alguma - com 0 aprovadas, "0 aprovadas"
        # ja diz tudo (um segmento "nenhuma aprovada" a mais seria redundante)
        if resumo["aprovadas"]:
            partes.append(f"{formatar_reais(resumo['valor_aprovado'])} aprovado")
        partes.append(f"última atividade {_formatar_ultima_atividade(resumo['ultima_atividade'])}")
        return " · ".join(partes)

    def _atualizar_visibilidade_do_historico(self, *_args) -> None:
        """O historico (os cards) aparece se ha propostas ou o card "Nova proposta"; senao, o aviso (VENDEDOR) ou
        nada (as propostas de antes das vendas so aparecem se ainda houver alguma)."""
        ha_cards = self.lista_antigas.total() > 0 or self.lista_antigas.rascunho is not None
        self.lista_antigas.setVisible(ha_cards)
        if self._so_historico:
            self._historico_vazio.setVisible(not ha_cards)
            return
        self._historico_vazio.setVisible(False)
        for parte in (self._titulo_historico, self._dica_antigas):
            parte.setVisible(ha_cards)

    def _descartar_expansao(self) -> None:
        """Recolhe o card expandido e o formulario do card de venda (a ficha mudou de assunto); avisa se havia
        edicao nao salva."""
        tinha = self.lista_vendas.tem_edicao_pendente()
        self.lista_vendas.descartar()
        if self.lista_antigas.descartar() or tinha:
            QMessageBox.information(
                self,
                "Alterações descartadas",
                "A proposta que estava sendo editada foi fechada e as alterações que não tinham sido salvas foram descartadas.",
            )

    def _linha_da_proposta(self, indice_real: int) -> dict | None:
        """A proposta na posicao `indice_real` como a ficha a leu (o formulario do card aberto abre com ela)."""
        if not self._cpf_selecionado or indice_real not in self._historico_atual.index:
            return None
        return self._historico_atual.loc[indice_real].to_dict()

    # -- cadastro de cliente novo (inline, mesmo padrao Editar/OK/Cancelar da edicao) --

    def _iniciar_novo_cliente(self) -> None:
        """Abre a ficha em branco, direto em modo edicao (ver
        _salvar_edicao_cliente/_cancelar_edicao_cliente pro resto do fluxo: salvar
        chama adicionar_cliente em vez de atualizar_cliente, cancelar descarta o
        rascunho em vez de reler do disco)."""
        self._lista.clearSelection()  # dispara _selecionar_cliente(""), que so mostra a pagina vazia - sobrescrita abaixo
        self._cpf_selecionado = None
        cliente_vazio = {coluna: "" for coluna in bd.CLIENTES_COLUNAS}
        historico_vazio = pd.DataFrame(columns=bd.PROPOSTAS_COLUNAS)
        self._preencher_ficha(cliente_vazio, historico_vazio)
        self._modo_novo_cliente = True  # depois do preencher: ele reseta essa flag pra False
        self._painel_stack.setCurrentIndex(1)
        self._rolagem_ficha.verticalScrollBar().setValue(0)
        # nao da pra lancar venda pra um cliente que ainda nao foi salvo
        self._botao_nova_venda.setVisible(False)
        self._aplicar_modo_edicao_cliente(leitura=False)
        self._campo_nome.setFocus()

    # -- edicao INLINE do cliente (cabecalho/Contato/Pessoal), tanto pra um cliente
    # EXISTENTE ("Editar") quanto pra um cliente NOVO ("+ Novo Cliente") ------------------

    def _definir_texto_tipo(self, tipo_cru: str) -> None:
        # tira qualquer item "fora do padrao" de uma rodada anterior, antes de adicionar o novo
        while self._campo_tipo.count() > len(clientes_mod.TIPO_OPCOES):
            self._campo_tipo.removeItem(self._campo_tipo.count() - 1)
        tipo_atual = (tipo_cru or "").strip()
        if not tipo_atual:
            self._campo_tipo.setCurrentIndex(0)
            return
        correspondente = next((op for op in clientes_mod.TIPO_OPCOES if op.upper() == tipo_atual.upper()), None)
        if correspondente:
            self._campo_tipo.setCurrentText(correspondente)
        else:
            # valor fora do padrao (ex.: editado direto no Excel) - mostra como esta,
            # em vez de trocar pro primeiro item da lista sem avisar
            self._campo_tipo.addItem(tipo_atual)
            self._campo_tipo.setCurrentText(tipo_atual)

    def _definir_texto_uf(self, uf_crua: str) -> None:
        # tira qualquer item "fora do padrao" de uma rodada anterior, antes de adicionar o novo
        while self._campo_uf.count() > len(UFS_VALIDAS) + 1:  # +1 do item vazio ("")
            self._campo_uf.removeItem(self._campo_uf.count() - 1)
        uf_atual = (uf_crua or "").strip().upper()
        if not uf_atual:
            self._campo_uf.setCurrentIndex(0)
            return
        if uf_atual in UFS_VALIDAS:
            self._campo_uf.setCurrentText(uf_atual)
        else:
            # valor fora do padrao (ex.: editado direto no Excel) - mostra como esta,
            # em vez de trocar pra vazio sem avisar
            self._campo_uf.addItem(uf_atual)
            self._campo_uf.setCurrentText(uf_atual)

    def _recarregar_vendedores_do_cabecalho(self, selecionado: str = "") -> None:
        self._campo_vendedor.blockSignals(True)
        self._campo_vendedor.clear()
        self._campo_vendedor.addItem("")  # vendedor e opcional
        nomes = vendedores_mod.listar_vendedores()
        self._campo_vendedor.addItems(nomes)
        if selecionado and selecionado.upper() not in {n.upper() for n in nomes}:
            # vendedor antigo que nao esta (mais) cadastrado - mostra o valor atual
            # em vez de trocar silenciosamente pra vazio
            self._campo_vendedor.addItem(selecionado)
        self._campo_vendedor.setCurrentText(selecionado)
        self._campo_vendedor.blockSignals(False)

    def _aplicar_modo_edicao_cliente(self, leitura: bool) -> None:
        """Trava/destrava a grade de dados do cliente (Endereco tem sua propria regra -
        ver abaixo). O mesmo padrao de FormularioProposta: o campo e sempre o MESMO
        widget, so alterna somente-leitura - inclusive visualmente: o campo mantem a
        MESMA caixa em leitura e edicao (pedido do usuario), so o cursor/possibilidade
        de digitar muda. E-mail e excecao (vira um QLabel com link em leitura - ver
        _pilha_email; a caixa dele usa role "campo_valor" + propriedade "caixa" pra
        parecer igual ao QLineEdit). "Cadastrado em" nunca fica editavel (a data e
        gravada so no cadastro - ver _salvar_edicao_cliente)."""
        self._modo_leitura_cliente = leitura
        for campo in (
            self._campo_nome, self._campo_cpf, self._campo_celular, self._campo_rede_social,
            self._campo_nome_pai, self._campo_nome_mae, self._campo_profissao, self._campo_vinculado,
            self._campo_cep, self._campo_logradouro, self._campo_numero, self._campo_complemento,
            self._campo_bairro, self._campo_cidade, self._campo_endereco_revisar,
        ):
            campo.setReadOnly(leitura)
        self._campo_email.setReadOnly(leitura)
        self._campo_nascimento.definir_somente_leitura(leitura)
        self._campo_tipo.definir_travado(leitura)
        self._campo_vendedor.definir_travado(leitura)
        self._campo_uf.definir_travado(leitura)

        self._pilha_email.setCurrentIndex(0 if leitura else 1)
        self._pilha_endereco_revisar.setCurrentIndex(0 if leitura else 1)

        for botao in (
            self._botao_copiar_cpf, self._botao_copiar_celular, self._botao_copiar_email,
            self._botao_copiar_rede_social, self._botao_copiar_nascimento, self._botao_copiar_pai,
            self._botao_copiar_mae, self._botao_copiar_profissao, self._botao_copiar_vinculado,
            self._botao_copiar_cadastro, self._botao_copiar_cep, self._botao_copiar_logradouro,
            self._botao_copiar_numero, self._botao_copiar_complemento, self._botao_copiar_bairro,
            self._botao_copiar_cidade,
        ):
            botao.setVisible(leitura)

        self._botao_buscar_cep.setVisible(not leitura)
        self._botao_buscar_cnpj.setVisible(not leitura)
        self._atualizar_botoes_buscar()

        self._botao_editar_cliente.setVisible(leitura)
        self._botao_ok_cliente.setVisible(not leitura)
        self._botao_cancelar_cliente.setVisible(not leitura)
        self._botao_menu_cliente.setVisible(leitura)  # excluir cliente no meio de uma edicao nao faz sentido
        self._botao_novo_cliente.setEnabled(leitura)  # nao dava pra ter dois rascunhos abertos ao mesmo tempo

        # Endereco: "so mostrar em campos separados" ao editar (pedido do usuario) - forca
        # expandido e trava o retratil, lembrando o estado de antes pra devolver ao sair
        # da edicao (a escolha retraido/expandido e uma preferencia do usuario, nao um
        # dado do cliente - nao pode "vazar" um forcado pra fora da edicao)
        if leitura:
            if self._endereco_forcado_expandido:
                self._cabecalho_endereco.setChecked(self._endereco_estava_expandido)
                self._endereco_forcado_expandido = False
            self._cabecalho_endereco.setEnabled(True)
        else:
            self._endereco_estava_expandido = self._cabecalho_endereco.isChecked()
            self._endereco_forcado_expandido = True
            self._cabecalho_endereco.setChecked(True)
            self._cabecalho_endereco.setEnabled(False)

        if leitura:
            for campo in (self._campo_nome, self._campo_cpf, self._campo_email, self._campo_cep):
                limpar_invalido(campo)
            limpar_invalido(self._campo_nascimento.campo)
        self._atualizar_visibilidade_dados()  # editando, mostra TODOS os campos (mesmo vazios)

    def _alternar_edicao_cliente(self) -> None:
        if not self._cpf_selecionado:
            return
        self._aplicar_modo_edicao_cliente(leitura=False)
        self._campo_nome.setFocus()
        self._campo_nome.selectAll()

    def _cancelar_edicao_cliente(self) -> None:
        """Descarta o que foi digitado e volta pra leitura - rele o cliente do disco
        (mais simples e sempre correto do que guardar um snapshot a parte; _preencher_ficha
        ja volta pro modo leitura sozinho). Cliente novo (ainda sem CPF salvo): nao ha o
        que reler - descarta o rascunho inteiro e volta pra pagina vazia."""
        if self._modo_novo_cliente:
            self._modo_novo_cliente = False
            self._botao_nova_venda.setVisible(not self._so_historico)
            self._aplicar_modo_edicao_cliente(leitura=True)
            self._painel_stack.setCurrentIndex(0)
            return
        if not self._cpf_selecionado:
            return
        cliente = clientes_mod.buscar_por_cpf(self._cpf_selecionado)
        if cliente is None:
            self._aplicar_modo_edicao_cliente(leitura=True)
            return
        self._preencher_cliente(cliente)

    # -- consulta de CEP e CNPJ (so ao clicar em "Buscar"; nada e gravado, o usuario revisa e salva) ----

    @staticmethod
    def _criar_botao_buscar(ao_clicar: Callable[[], None]) -> QPushButton:
        botao = QPushButton("Buscar")
        botao.setFixedWidth(64)
        botao.clicked.connect(ao_clicar)
        return botao

    def _atualizar_botoes_buscar(self, *_args) -> None:
        digitos_cep = apenas_digitos(self._campo_cep.text())
        self._botao_buscar_cep.setEnabled(len(digitos_cep) == 8)
        self._botao_buscar_cep.setToolTip(
            "Preencher o endereço a partir do CEP" if len(digitos_cep) == 8 else "Digite os 8 números do CEP para buscar"
        )
        digitos_doc = apenas_digitos(self._campo_cpf.text())
        self._botao_buscar_cnpj.setEnabled(len(digitos_doc) == 14)
        self._botao_buscar_cnpj.setToolTip(
            "Preencher nome e endereço a partir do CNPJ"
            if len(digitos_doc) == 14
            else "A busca vale só para CNPJ (14 números); o CPF nunca é consultado"
        )

    def _buscar_cep(self) -> None:
        self._consultar_e_preencher("CEP", lambda: consulta_mod.consultar_cep(self._campo_cep.text()), {})

    def _buscar_cnpj(self) -> None:
        self._consultar_e_preencher(
            "CNPJ", lambda: consulta_mod.consultar_cnpj(self._campo_cpf.text()), {"razao_social": ("Nome", self._campo_nome)}
        )

    def _campos_do_endereco_consultado(self) -> dict[str, tuple[str, QWidget]]:
        return {
            "cep": ("CEP", self._campo_cep),
            "logradouro": ("Logradouro", self._campo_logradouro),
            "numero": ("Número", self._campo_numero),
            "complemento": ("Complemento", self._campo_complemento),
            "bairro": ("Bairro", self._campo_bairro),
            "cidade": ("Cidade", self._campo_cidade),
            "uf": ("UF", self._campo_uf),
        }

    @staticmethod
    def _texto_do_campo(campo: QWidget) -> str:
        return (campo.currentText() if isinstance(campo, QComboBox) else campo.text()).strip()

    def _colocar_no_campo(self, campo: QWidget, valor: str) -> None:
        if campo is self._campo_uf:
            self._definir_texto_uf(valor)
        else:
            campo.setText(valor)
            campo.setCursorPosition(0)

    def _consultar_e_preencher(
        self, o_que: str, consultar: Callable[[], dict[str, str]], extras: dict[str, tuple[str, QWidget]]
    ) -> None:
        """Roda a consulta fora da thread da tela (janelinha "Aguarde") e preenche o formulario: campo vazio recebe
        direto; campo com texto diferente so muda se o usuario confirmar. Falha = aviso e o formulario segue como estava."""
        try:
            achados = rodar_esperando(self, f"Consultando o {o_que}…", consultar, limite_s=consulta_mod.TIMEOUT_S * 2 + 2)
        except consulta_mod.ErroConsultaExterna as exc:
            QMessageBox.warning(self, f"Consulta de {o_que}", str(exc))
            return
        except TimeoutError:
            QMessageBox.warning(self, f"Consulta de {o_que}", f"A consulta de {o_que} demorou demais. Tente de novo mais tarde.")
            return
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, f"Consulta de {o_que}", f"Erro inesperado na consulta de {o_que}: {exc}")
            return
        if self._modo_leitura_cliente:
            QMessageBox.information(
                self, f"Consulta de {o_que}",
                "A ficha foi recarregada enquanto a consulta rodava. Clique em Editar e busque de novo.",
            )
            return
        campos = {**self._campos_do_endereco_consultado(), **extras}
        # a consulta do CEP nao devolve o proprio CEP, e a do CNPJ so o devolve junto do resto
        achados = {chave: valor for chave, valor in achados.items() if chave in campos}
        atuais = {chave: self._texto_do_campo(campos[chave][1]) for chave in achados}
        vazios, conflitos = consulta_mod.separar_preenchimentos(atuais, achados)
        substituir = False
        if conflitos:
            linhas = "\n".join(f"{campos[c][0]}:  \"{atuais[c]}\"  →  \"{novo}\"" for c, novo in conflitos.items())
            resposta = QMessageBox.question(
                self, f"Consulta de {o_que}",
                f"Estes campos já têm outro texto. Substituir pelo que veio da consulta?\n\n{linhas}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
            )
            substituir = resposta == QMessageBox.StandardButton.Yes
        for chave, valor in {**vazios, **(conflitos if substituir else {})}.items():
            self._colocar_no_campo(campos[chave][1], valor)

    def _validar_email_ao_vivo_cliente(self, texto: str) -> None:
        """So um aviso visual enquanto digita - quem realmente impede salvar com
        e-mail invalido e core.clientes (ver _salvar_edicao_cliente)."""
        if not texto.strip() or email_valido(texto):
            limpar_invalido(self._campo_email)
        else:
            marcar_invalido(self._campo_email, "E-mail inválido - confira o endereço digitado.")

    def _salvar_edicao_cliente(self) -> None:
        if not self._modo_novo_cliente and not self._cpf_selecionado:
            return
        for campo in (self._campo_nome, self._campo_cpf, self._campo_email, self._campo_cep):
            limpar_invalido(campo)
        limpar_invalido(self._campo_nascimento.campo)

        # data invalida NUNCA vira "nao informado" em silencio - marca o campo e nao salva
        nascimento, erro_nascimento = self._campo_nascimento.avaliar()
        if erro_nascimento:
            marcar_invalido(self._campo_nascimento.campo, erro_nascimento)
            self._campo_nascimento.campo.setFocus()
            return

        cpf_texto = self._campo_cpf.text().strip()
        nome_texto = self._campo_nome.text().strip()
        email_texto = self._campo_email.text().strip()
        cep_texto = self._campo_cep.text().strip()

        if not cpf_texto:
            marcar_invalido(self._campo_cpf, "CPF/CNPJ é obrigatório.")
            self._campo_cpf.setFocus()
            return
        cpf_mudou = apenas_digitos(cpf_texto) != apenas_digitos(self._cpf_selecionado)
        if cpf_mudou and not cpf_cnpj_valido(cpf_texto):
            marcar_invalido(self._campo_cpf, "CPF/CNPJ inválido - confira os números digitados.")
            self._campo_cpf.setFocus()
            return
        if not nome_texto:
            marcar_invalido(self._campo_nome, "Nome do cliente é obrigatório.")
            self._campo_nome.setFocus()
            return
        if email_texto and not email_valido(email_texto):
            marcar_invalido(self._campo_email, "E-mail inválido - confira o endereço digitado.")
            self._campo_email.setFocus()
            return
        # a mascara ja limita a 8 digitos - so falta rejeitar um CEP incompleto (a mesma
        # regra de core.clientes._normalizar_cep, checada aqui antes pra marcar o campo
        # em vez de abrir um QMessageBox)
        if cep_texto and len(apenas_digitos(cep_texto)) != 8:
            marcar_invalido(self._campo_cep, "CEP inválido - o CEP tem 8 números (ex.: 60165-120).")
            self._campo_cep.setFocus()
            return

        campos = {
            "CPF/CNPJ": cpf_texto,
            "CLIENTE": nome_texto,
            "TIPO": self._campo_tipo.currentText(),
            "VENDEDOR": self._campo_vendedor.currentText().strip(),
            "CELULAR": self._campo_celular.text().strip(),
            "EMAIL": email_texto,
            "REDE SOCIAL": self._campo_rede_social.text().strip(),
            "NASCIMENTO": pd.Timestamp(nascimento.year(), nascimento.month(), nascimento.day()) if nascimento else "",
            "VINCULADO": self._campo_vinculado.text().strip(),
            "NOME DO PAI": self._campo_nome_pai.text().strip(),
            "NOME DA MÃE": self._campo_nome_mae.text().strip(),
            "PROFISSÃO": self._campo_profissao.text().strip(),
            "CEP": cep_texto,
            "LOGRADOURO": self._campo_logradouro.text().strip(),
            "NÚMERO": self._campo_numero.text().strip(),
            "COMPLEMENTO": self._campo_complemento.text().strip(),
            "BAIRRO": self._campo_bairro.text().strip(),
            "CIDADE": self._campo_cidade.text().strip(),
            "UF": self._campo_uf.currentText().strip(),
            "ENDEREÇO (REVISAR)": self._campo_endereco_revisar.text().strip(),
        }
        try:
            if self._modo_novo_cliente:
                clientes_mod.adicionar_cliente(campos)
            else:
                clientes_mod.atualizar_cliente(self._cpf_selecionado, campos)
        except clientes_mod.ErroCliente as exc:
            QMessageBox.warning(self, "Não foi possível salvar", str(exc))
            return
        except sessao_mod.PermissaoNegada as exc:
            QMessageBox.warning(self, "Ação não permitida", str(exc))
            return
        except bd.ErroArquivoBloqueado as exc:
            QMessageBox.critical(self, "Arquivo bloqueado", str(exc))
            return
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro inesperado ao salvar", str(exc))
            return

        self._aplicar_modo_edicao_cliente(leitura=True)
        self._invalidar_em_aberto()  # o CPF pode ter mudado: as propostas em aberto sao ligadas a ele
        self._recarregar_vendedores_filtro()
        self._busca.setText("")
        self._atualizar_lista()
        self._mostrar_cliente(cpf_texto)

    def _recarregar_ficha_atual(self) -> bool:
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
            historico, vendas = self._ler_propostas_e_vendas(self._cpf_selecionado)
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro ao recarregar cliente", str(exc))
            return False
        if cliente is None:
            QMessageBox.warning(self, "Cliente não encontrado", "Este cliente pode ter sido removido.")
            self._cpf_selecionado = None
            self._painel_stack.setCurrentIndex(0)
            return False
        self._preencher_ficha(cliente, historico, vendas, mesmo_cliente=True)
        return True

    def _ler_propostas_e_vendas(self, cpf: str) -> tuple[pd.DataFrame, list[vendas_mod.ResumoDaVenda]]:
        historico = propostas_mod.historico_por_cpf(cpf)
        return historico, [] if self._so_historico else vendas_mod.vendas_do_cliente(cpf)

    def _nova_venda(self) -> bool:
        """"+ Nova venda" com o cliente da ficha: o card "Nova venda" no topo da lista de vendas dele, ja com o
        cliente; criada, o card dela fica aberto com o formulario do primeiro banco."""
        if not self._cpf_selecionado:
            return False
        return self.lista_vendas.nova_venda(self._cpf_selecionado)

    def _depois_de_gravar_venda(self, aviso: str = "") -> None:
        """Gravou algo num card de venda: rele as vendas e as propostas - os dados do cliente (talvez em edicao)
        ficam como estao."""
        if not self._cpf_selecionado:
            return
        try:
            historico, vendas = self._ler_propostas_e_vendas(self._cpf_selecionado)
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro ao recarregar as vendas", str(exc))
            return
        self._preencher_propostas(historico, vendas, mesmo_cliente=True)
        self._invalidar_em_aberto()
        self._atualizar_lista()  # a "impressao" da planilha em dia: a propria gravacao nao parece mudanca de fora
        self.dados_atualizados.emit()
        self._faixa_aviso.avisar(aviso)

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

    def tem_edicao_pendente(self) -> bool:
        return self.lista_antigas.tem_edicao_pendente() or self.lista_vendas.tem_edicao_pendente()

    def _excluir_cliente(self) -> None:
        if not self._cpf_selecionado:
            return

        nome = self._campo_nome.text()
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
