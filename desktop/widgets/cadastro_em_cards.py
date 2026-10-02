"""Cadastro em cards - a peca reaproveitavel das listas de apoio (Bancos, e depois Vendedores, Equipamentos...).

Cada cadastro e so uma DefinicaoDoCadastro: os campos, como listar e as acoes (adicionar, salvar, ativar/desativar,
excluir), todas do core. A peca cuida do resto igual em todos: busca, um card por item (titulo, uma linha de detalhe,
etiqueta Ativo/Inativo e a faixa colorida na lateral, nas cores dos cards de Todas as Propostas), sempre com a MESMA
largura (nao estica em tela larga). Editar escolhe o jeito pelo numero de campos:

- 1 campo (Bancos): edita NO LUGAR - o titulo vira a caixa de texto, com confirmar/cancelar; o card nao muda de tamanho.
- 2+ campos (Equipamentos): o card abre PARA BAIXO, com os campos um embaixo do outro, na mesma largura.

O lapis (ou um duplo clique) edita; os tres pontinhos tem Desativar/Reativar e Excluir. Um clique simples nao faz nada
(nao entra em edicao sem querer). "+ Novo" poe um card ja em edicao no inicio. Enter salva, Esc cancela. So um card
fica em edicao por vez; trocar com algo digitado pergunta antes.

Registros grandes, com muitos campos e historico (o cliente), NAO sao para esta peca: eles ficam no formato da Ficha.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFontMetrics, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core import data_store as bd
from desktop import settings as settings_mod
from desktop.theme import CORES_STATUS, PALETAS
from desktop.widgets.icones_linha import icone_de_linha
from desktop.widgets.shadow import aplicar_sombra_suave

LARGURA_CARD = 300  # todo card tem esta largura (aberto ou fechado); cabem tantos por linha quanto a tela deixar
_ESPACO = 10
_FAIXA = 5
_RAIO = 10
_COR_ATIVO = "aprovado"  # as cores (ja conferidas nos dois temas) das etapas de proposta
_COR_INATIVO = "encerrada"


@dataclass(frozen=True)
class Campo:
    chave: str
    rotulo: str
    obrigatorio: bool = False
    dica: str = ""  # texto de exemplo dentro do campo vazio


@dataclass(frozen=True)
class ItemDoCadastro:
    chave: str  # o que identifica o item nas acoes do core (ex.: o nome do banco)
    titulo: str
    detalhe: str  # a linha de baixo do card
    ativo: bool
    valores: dict  # campo -> valor atual, pro formulario
    busca: str = ""  # texto extra procurado pela busca (alem do titulo e do detalhe)


@dataclass(frozen=True)
class AcaoExtra:
    """Mais uma opcao nos tres pontinhos (ex.: "Redefinir senha"). `executar` cuida das proprias perguntas
    (pode abrir dialogos) e devolve a mensagem de sucesso, "" pra nao mostrar nada, ou None se a pessoa
    desistiu; levanta um dos erros_esperados quando a regra recusa."""

    rotulo: str
    executar: Callable[[ItemDoCadastro, QWidget], str | None]


@dataclass
class DefinicaoDoCadastro:
    titulo: str  # "Bancos"
    nome_do_item: str  # "banco" - entra em "+ Novo banco", "Excluir banco", "Buscar banco"
    explicacao: str
    campos: list[Campo]
    listar: Callable[[], list[ItemDoCadastro]]
    # cada acao devolve a mensagem de sucesso (ou "" pra nao mostrar nada) e levanta um dos erros_esperados
    # com o motivo pronto pra pessoa quando a regra recusa
    adicionar: Callable[[dict], str]
    salvar: Callable[[str, dict], str]
    definir_ativo: Callable[[str, bool], str] | None = None
    excluir: Callable[[str], str] | None = None
    erros_esperados: tuple[type[Exception], ...] = field(default_factory=tuple)
    pergunta_ao_desativar: Callable[[ItemDoCadastro], str] | None = None
    acoes_extras: list[AcaoExtra] = field(default_factory=list)


def _paleta() -> dict:
    return PALETAS[settings_mod.obter_tema()]


class _Etiqueta(QWidget):
    """A pilula Ativo/Inativo, desenhada com as cores do tema atual (troca de tema = so repintar)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.ativo = True
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def texto(self) -> str:
        return "Ativo" if self.ativo else "Inativo"

    def sizeHint(self) -> QSize:
        metricas = QFontMetrics(self.font())
        return QSize(metricas.horizontalAdvance(self.texto()) + 18, metricas.height() + 6)

    def paintEvent(self, _evento) -> None:
        cor = CORES_STATUS[settings_mod.obter_tema()][_COR_ATIVO if self.ativo else _COR_INATIVO]
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        caixa = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        pintor.setPen(QColor(cor["faixa"]))
        pintor.setBrush(QColor(cor["fundo"]))
        pintor.drawRoundedRect(caixa, caixa.height() / 2, caixa.height() / 2)
        pintor.setPen(QColor(cor["texto"]))
        pintor.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.texto())


class _Card(QFrame):
    """Um item do cadastro (ou, com item None, o card de um item novo). Sempre da mesma largura."""

    editar_pedido = Signal(object)  # self
    agir = Signal(str, object)  # (acao, self): "salvar", "cancelar", "ativo", "excluir"

    def __init__(self, item: ItemDoCadastro | None, definicao: DefinicaoDoCadastro, parent: QWidget | None = None):
        super().__init__(parent)
        self.item = item
        self._definicao = definicao
        self.no_lugar = len(definicao.campos) == 1
        self.setProperty("role", "card")
        self.setFixedWidth(LARGURA_CARD)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(_FAIXA + 12, 8, 8, 10)
        layout.setSpacing(4)

        # o _topo entra no card JA: um widget posto num layout ainda solto continua sem dono, e o setVisible
        # dele (logo abaixo) o mostraria como uma janelinha solta piscando na tela
        self._topo = QHBoxLayout()
        self._topo.setSpacing(4)
        layout.addLayout(self._topo)
        self.titulo = QLabel(item.titulo if item else f"Novo {definicao.nome_do_item}")
        self.titulo.setProperty("role", "transparente")
        fonte = self.titulo.font()
        fonte.setBold(True)
        fonte.setPointSizeF(fonte.pointSizeF() + 1)
        self.titulo.setFont(fonte)
        self._topo.addWidget(self.titulo, stretch=1)
        self.etiqueta = _Etiqueta(self)
        self.etiqueta.ativo = item.ativo if item else True
        self.etiqueta.setVisible(item is not None)
        self._topo.addWidget(self.etiqueta, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.botoes: dict[str, QPushButton] = {}
        self.acoes: dict[str, QAction] = {}
        self.botoes["editar"] = self._botao_icone("lapis", f"Editar {definicao.nome_do_item}",
                                                  lambda: self.editar_pedido.emit(self))
        self._menu = QMenu(self)
        for extra in definicao.acoes_extras if item is not None else []:
            self.acoes[extra.rotulo] = self._menu.addAction(extra.rotulo, lambda e=extra: self.agir.emit(e.rotulo, self))
        if item is not None and definicao.definir_ativo is not None:
            self.acoes["ativo"] = self._menu.addAction("Desativar" if item.ativo else "Reativar",
                                                       lambda: self.agir.emit("ativo", self))
        if item is not None and definicao.excluir is not None:
            self.acoes["excluir"] = self._menu.addAction("Excluir…", lambda: self.agir.emit("excluir", self))
        self.botoes["menu"] = self._botao_icone("tres_pontos", "Mais ações", self._abrir_menu)
        self.botoes["menu"].setVisible(bool(self.acoes))
        self.botoes["editar"].setVisible(item is not None)

        self.detalhe = QLabel(item.detalhe if item else "Digite e tecle Enter.")
        self.detalhe.setProperty("role", "secundario")
        self.detalhe.setWordWrap(True)
        layout.addWidget(self.detalhe)

        self.campos: dict[str, QLineEdit] = {}
        self._editor: QWidget | None = None
        self._aplicar_icones()

    def _botao_icone(self, icone: str, dica: str, ao_clicar) -> QPushButton:
        botao = QPushButton(self)
        botao.setProperty("role", "botao_icone")
        botao.setProperty("icone", icone)
        botao.setToolTip(dica)
        botao.setAccessibleName(dica)
        botao.setIconSize(QSize(16, 16))
        botao.setCursor(Qt.CursorShape.PointingHandCursor)
        botao.clicked.connect(ao_clicar)
        self._topo.addWidget(botao)
        return botao

    def _aplicar_icones(self) -> None:
        cor = QColor(_paleta()["texto_secundario"])
        for botao in self.botoes.values():
            if botao.property("icone"):
                botao.setIcon(icone_de_linha(botao.property("icone"), cor, 16))

    def changeEvent(self, evento) -> None:
        if evento.type() == QEvent.Type.StyleChange:  # trocou o tema: os icones sao desenhados numa cor fixa
            self._aplicar_icones()
        super().changeEvent(evento)

    def _abrir_menu(self) -> None:
        botao = self.botoes["menu"]
        self._menu.exec(botao.mapToGlobal(botao.rect().bottomLeft()))

    def aberto(self) -> bool:
        return bool(self.campos)

    def abrir(self) -> None:
        """Entra em edicao: no lugar (1 campo) ou para baixo (2+ campos)."""
        if self.aberto():
            return
        valores = self.item.valores if self.item else {}
        self.botoes["editar"].hide()
        if self.no_lugar:
            caixa = self._caixa(self._definicao.campos[0], valores)
            self.titulo.hide()
            self.etiqueta.hide()  # a caixa de texto precisa do espaco; o card nao muda de tamanho
            self._topo.insertWidget(0, caixa, stretch=1)
            self.botoes["salvar"] = self._botao_icone("confirmar", "Salvar (Enter)", lambda: self.agir.emit("salvar", self))
            self.botoes["cancelar"] = self._botao_icone("fechar", "Cancelar (Esc)", lambda: self.agir.emit("cancelar", self))
            # confirmar/cancelar logo depois da caixa; a etiqueta e os tres pontinhos continuam onde estavam
            for posicao, nome in enumerate(("salvar", "cancelar"), start=1):
                self._topo.removeWidget(self.botoes[nome])
                self._topo.insertWidget(posicao, self.botoes[nome])
        else:
            self._editor = QWidget()
            self._editor.setProperty("role", "transparente")
            corpo = QVBoxLayout(self._editor)
            corpo.setContentsMargins(0, 6, 4, 0)
            corpo.setSpacing(4)
            for campo in self._definicao.campos:
                rotulo = QLabel(campo.rotulo + (" *" if campo.obrigatorio else ""))
                rotulo.setProperty("role", "secundario")
                corpo.addWidget(rotulo)
                corpo.addWidget(self._caixa(campo, valores))
            linha = QHBoxLayout()
            salvar = QPushButton("Salvar" if self.item else "Adicionar")
            salvar.setProperty("role", "botao_primario")
            salvar.clicked.connect(lambda: self.agir.emit("salvar", self))
            cancelar = QPushButton("Cancelar")
            cancelar.clicked.connect(lambda: self.agir.emit("cancelar", self))
            linha.addWidget(salvar)
            linha.addWidget(cancelar)
            linha.addStretch()
            corpo.addSpacing(4)
            corpo.addLayout(linha)
            self.botoes["salvar"], self.botoes["cancelar"] = salvar, cancelar
            self.layout().addWidget(self._editor)
        self._aplicar_icones()
        primeiro = next(iter(self.campos.values()))
        primeiro.setFocus()
        primeiro.selectAll()

    def _caixa(self, campo: Campo, valores: dict) -> QLineEdit:
        caixa = QLineEdit(str(valores.get(campo.chave, "") or ""))
        caixa.setPlaceholderText(campo.dica or campo.rotulo)
        caixa.setAccessibleName(campo.rotulo)
        caixa.returnPressed.connect(lambda: self.agir.emit("salvar", self))
        self.campos[campo.chave] = caixa
        return caixa

    def valores(self) -> dict:
        return {chave: caixa.text().strip() for chave, caixa in self.campos.items()}

    def tem_alteracoes(self) -> bool:
        originais = self.item.valores if self.item else {}
        return any(str(originais.get(c, "") or "").strip() != v for c, v in self.valores().items())

    def keyPressEvent(self, evento) -> None:
        if evento.key() == Qt.Key.Key_Escape and self.aberto():
            self.agir.emit("cancelar", self)
            return
        super().keyPressEvent(evento)

    def mouseDoubleClickEvent(self, evento) -> None:
        if not self.aberto() and self.item is not None:
            self.editar_pedido.emit(self)
        super().mouseDoubleClickEvent(evento)

    def paintEvent(self, evento) -> None:
        super().paintEvent(evento)
        # a faixa colorida da lateral, como nos cards de Todas as Propostas (o card novo usa a cor de destaque)
        if self.item is None:
            cor = _paleta()["destaque"]
        else:
            cor = CORES_STATUS[settings_mod.obter_tema()][_COR_ATIVO if self.etiqueta.ativo else _COR_INATIVO]["faixa"]
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        contorno = QPainterPath()
        contorno.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), _RAIO, _RAIO)
        pintor.setClipPath(contorno)
        pintor.fillRect(QRectF(0, 0, _FAIXA, self.height()), QColor(cor))


class CadastroEmCards(QFrame):
    alterado = Signal()  # algo foi gravado: as outras telas releem

    def __init__(self, definicao: DefinicaoDoCadastro, parent: QWidget | None = None, *, dentro_de_pagina: bool = False):
        """`dentro_de_pagina`: uma secao entre outras numa pagina que rola (a tela de Cadastros) - sem
        rolagem nem busca proprias (a pagina tem uma busca unica que escreve em `busca`); os cards ocupam a
        altura que precisarem."""
        super().__init__(parent)
        self.definicao = definicao
        self.setProperty("role", "card")
        aplicar_sombra_suave(self, settings_mod.obter_tema())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        cabecalho = QHBoxLayout()
        layout.addLayout(cabecalho)  # ja no card: ver o comentario do _topo em _Card
        subtitulo = QLabel(definicao.titulo)
        subtitulo.setProperty("role", "subtitulo")
        cabecalho.addWidget(subtitulo)
        cabecalho.addStretch()
        self.busca = QLineEdit()
        self.busca.setPlaceholderText(f"Buscar {definicao.nome_do_item}")
        self.busca.setClearButtonEnabled(True)
        self.busca.setMaximumWidth(260)
        self.busca.textChanged.connect(self._montar)
        cabecalho.addWidget(self.busca)
        self.busca.setVisible(not dentro_de_pagina)
        self.botao_novo = QPushButton(f"+ Novo {definicao.nome_do_item}")
        self.botao_novo.setProperty("role", "botao_primario")
        self.botao_novo.clicked.connect(self._novo)
        cabecalho.addWidget(self.botao_novo)

        explicacao = QLabel(definicao.explicacao)
        explicacao.setProperty("role", "secundario")
        explicacao.setWordWrap(True)
        layout.addWidget(explicacao)

        self._conteudo = QWidget()
        self._conteudo.setProperty("role", "transparente")
        self._grade = QGridLayout(self._conteudo)
        self._grade.setContentsMargins(0, 0, 4, 0)
        self._grade.setSpacing(_ESPACO)
        # cards de largura fixa encostados a esquerda e no topo: o que sobra fica livre a direita e embaixo
        self._grade.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        if dentro_de_pagina:
            layout.addWidget(self._conteudo)
        else:
            rolagem = QScrollArea()
            rolagem.setWidgetResizable(True)
            rolagem.setFrameShape(QFrame.Shape.NoFrame)
            rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            # dentro de um card: sem isto a area de rolagem pinta o fundo da JANELA numa faixa atras dos cards
            rolagem.setProperty("role", "transparente")
            rolagem.viewport().setProperty("role", "transparente")
            rolagem.viewport().setAutoFillBackground(False)
            rolagem.setWidget(self._conteudo)
            layout.addWidget(rolagem, stretch=1)

        self.vazio = QLabel("", self._conteudo)  # com dono desde ja: sem ele, viraria uma janela solta
        self.vazio.setProperty("role", "secundario")

        self._itens: list[ItemDoCadastro] = []
        self.cards: list[_Card] = []
        self._aberto: str | None = None  # a chave do item em edicao ("" = o card de um item novo)
        self._colunas = 1
        self.recarregar()

    # -- dados ------------------------------------------------------------------------------------

    def recarregar(self) -> None:
        """Rele a lista do core. Com algo digitado num card em edicao, nao rele (perderia o que foi digitado)."""
        aberto = self._card_aberto()
        if aberto is not None and aberto.tem_alteracoes():
            return
        try:
            self._itens = self.definicao.listar()
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, f"Erro ao carregar {self.definicao.titulo.lower()}", f"{type(exc).__name__}: {exc}")
            return
        if self._aberto and self._aberto not in {i.chave for i in self._itens}:
            self._aberto = None
        self._montar()

    def _visiveis(self) -> list[ItemDoCadastro]:
        termo = self.busca.text().strip().upper()
        if not termo:
            return self._itens
        return [i for i in self._itens if termo in f"{i.titulo} {i.detalhe} {i.busca}".upper()]

    # -- montagem ---------------------------------------------------------------------------------

    def _montar(self, *_args) -> None:
        aberto_antes = self._card_aberto()
        # remontar (busca) nao pode perder o que foi digitado no card que continua em edicao
        digitado = None
        if aberto_antes is not None:
            chave_antes = "" if aberto_antes.item is None else aberto_antes.item.chave
            if chave_antes == self._aberto:
                digitado = aberto_antes.valores()
        while self._grade.count():
            widget = self._grade.takeAt(0).widget()
            if widget is not None and widget is not self.vazio:
                widget.hide()  # some ja: o deleteLater so apaga no proximo ciclo, e ate la ele seria desenhado
                widget.deleteLater()
        self.cards = []

        itens: list[ItemDoCadastro | None] = ([None] if self._aberto == "" else []) + self._visiveis()
        for item in itens:
            card = _Card(item, self.definicao, self._conteudo)
            card.editar_pedido.connect(self._editar)
            card.agir.connect(self._agir)
            if ("" if item is None else item.chave) == self._aberto:
                card.abrir()
                for campo, valor in (digitado or {}).items():
                    card.campos[campo].setText(valor)
            self.cards.append(card)
        self.vazio.setText(
            f"Nenhum {self.definicao.nome_do_item} encontrado." if self.busca.text().strip()
            else f"Nenhum {self.definicao.nome_do_item} cadastrado. Clique em \"+ Novo {self.definicao.nome_do_item}\"."
        )
        self._posicionar()

    def _posicionar(self) -> None:
        """Poe os cards ja criados na grade, no numero de colunas atual. Nao cria nem apaga nada: e o que roda
        quando a largura muda (recriar os cards no meio da abertura da janela atrapalhava o foco do teclado)."""
        while self._grade.count():
            self._grade.takeAt(0)
        for indice, card in enumerate(self.cards):
            self._grade.addWidget(card, indice // self._colunas, indice % self._colunas, Qt.AlignmentFlag.AlignTop)
        self.vazio.setVisible(not self.cards)
        if not self.cards:
            self._grade.addWidget(self.vazio, 0, 0)

    def resizeEvent(self, evento) -> None:
        super().resizeEvent(evento)
        # a largura do PROPRIO cadastro (a da area de rolagem ainda e a antiga neste momento)
        largura = self.contentsRect().width() - 32 - 4
        colunas = max(1, (largura + _ESPACO) // (LARGURA_CARD + _ESPACO))
        if colunas != self._colunas:
            self._colunas = colunas
            self._posicionar()

    def _card_aberto(self) -> _Card | None:
        return next((c for c in self.cards if c.aberto()), None)

    # -- acoes ------------------------------------------------------------------------------------

    def _pode_trocar(self) -> bool:
        """Ha um card em edicao com algo digitado? Pergunta antes de descartar."""
        aberto = self._card_aberto()
        if aberto is None or not aberto.tem_alteracoes():
            return True
        resposta = QMessageBox.question(
            self, "Descartar alterações", "Há alterações não salvas neste cadastro. Descartar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        return resposta == QMessageBox.StandardButton.Yes

    def _abrir(self, chave: str | None) -> None:
        self._aberto = chave
        self._montar()

    def _editar(self, card: _Card) -> None:
        if self._pode_trocar():
            self._abrir(card.item.chave)

    def _novo(self) -> None:
        if self._pode_trocar():
            self.busca.clear()
            self._abrir("")

    def _executar(self, titulo_erro: str, acao) -> str | None:
        """Roda a acao do core mostrando o erro (nunca em silencio). None = nao deu certo."""
        try:
            return acao()
        except self.definicao.erros_esperados as exc:
            QMessageBox.warning(self, titulo_erro, str(exc))
        except bd.ErroArquivoBloqueado as exc:
            QMessageBox.critical(self, "Arquivo bloqueado", str(exc))
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, f"Erro inesperado: {titulo_erro.lower()}", f"{type(exc).__name__}: {exc}")
        return None

    def _depois_de_gravar(self, titulo: str, mensagem: str) -> None:
        self._abrir(None)  # sai da edicao (o que foi digitado ja esta gravado) antes de reler
        self.recarregar()
        self.alterado.emit()
        if mensagem:
            QMessageBox.information(self, titulo, mensagem)

    def _agir(self, acao: str, card: _Card) -> None:
        nome = self.definicao.nome_do_item
        if acao == "cancelar":
            self._abrir(None)
            return
        if acao == "salvar":
            valores = card.valores()
            faltando = [c.rotulo for c in self.definicao.campos if c.obrigatorio and not valores.get(c.chave)]
            if faltando:
                QMessageBox.warning(self, "Campo obrigatório", "Preencha: " + ", ".join(faltando) + ".")
                return
            if card.item is None:
                mensagem = self._executar("Não foi possível cadastrar", lambda: self.definicao.adicionar(valores))
                titulo = f"{nome.capitalize()} cadastrado"
            else:
                if not card.tem_alteracoes():
                    self._abrir(None)
                    return
                mensagem = self._executar("Não foi possível salvar", lambda: self.definicao.salvar(card.item.chave, valores))
                titulo = "Alterações salvas"
            if mensagem is not None:
                self._depois_de_gravar(titulo, mensagem)
            return
        if card is not self._card_aberto() and not self._pode_trocar():  # outro card com uma edicao pela metade
            return
        item = card.item
        if acao == "ativo":
            if item.ativo:
                pergunta = (self.definicao.pergunta_ao_desativar(item) if self.definicao.pergunta_ao_desativar
                            else f"Desativar '{item.titulo}'?")
                resposta = QMessageBox.question(
                    self, f"Desativar {nome}", pergunta,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
                )
                if resposta != QMessageBox.StandardButton.Yes:
                    return
            erro = "Não foi possível desativar" if item.ativo else "Não foi possível reativar"
            mensagem = self._executar(erro, lambda: self.definicao.definir_ativo(item.chave, not item.ativo))
            if mensagem is not None:
                self._depois_de_gravar(f"{nome.capitalize()} {'desativado' if item.ativo else 'reativado'}", mensagem)
            return
        extra = next((e for e in self.definicao.acoes_extras if e.rotulo == acao), None)
        if extra is not None:
            mensagem = self._executar(f"Não foi possível: {acao.lower()}", lambda: extra.executar(item, self))
            if mensagem is not None:
                self._depois_de_gravar(acao, mensagem)
            return
        if acao == "excluir":
            resposta = QMessageBox.question(
                self, f"Excluir {nome}", f"Excluir '{item.titulo}'? Essa ação não pode ser desfeita.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
            )
            if resposta != QMessageBox.StandardButton.Yes:
                return
            mensagem = self._executar("Não foi possível excluir", lambda: self.definicao.excluir(item.chave))
            if mensagem is not None:
                self._depois_de_gravar(f"{nome.capitalize()} excluído", mensagem)
