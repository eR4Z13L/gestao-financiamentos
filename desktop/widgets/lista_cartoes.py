"""Lista de "cards" de propostas (tela Todas as Propostas): um card por
proposta, com o essencial pra reconhecer uma proposta de relance - nome do
cliente, "Equipamento . Banco" (a linha que diferencia as propostas do mesmo
cliente na mesma data), data + tempo ("ha 7 dias"/"Encerrado") e o status
numa pilula colorida, com uma faixa da mesma cor na lateral. Os detalhes
(valor, meses, observacoes...) aparecem quando o card EXPANDE, com um duplo clique
nele (um clique so o seleciona): ver ListaCartoes.expandir e ExpansorDeProposta.

Feito com QListView + delegate (o card e DESENHADO, nao e um widget por
proposta): continua leve com muitas propostas, e ganha de graca selecao,
rolagem e navegacao por teclado. So o card expandido leva um widget de verdade
(o formulario). As cores vem de desktop/theme.py e se refazem sozinhas quando o
tema muda com o app aberto.

Paginacao: o modelo mostra TAMANHO_PAGINA cards por vez e termina com um card
"Carregar mais" (tracejado) - clicar nele (ou Enter) mostra os proximos.
"""

from __future__ import annotations

import time

from PySide6.QtCore import (
    QAbstractListModel,
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QFrame, QListView, QStyle, QStyledItemDelegate, QWidget

from core import propostas as propostas_mod
from desktop import settings as settings_mod
from desktop.theme import CORES_STATUS, PALETAS, TEMA_ESCURO

PAPEL_CARTAO = Qt.ItemDataRole.UserRole  # devolve o dict do card (ver ModeloCartoes)
RASCUNHO = "rascunho"  # a "chave" do card expandido "Nova proposta" (as demais sao o indice real da proposta)

ALTURA_CARTAO = 100
ALTURA_CABECALHO = 46  # o topo do card EXPANDIDO (titulo + status); embaixo dele fica o formulario
_RODAPE_EXPANDIDO = 12  # espaco embaixo do formulario, dentro do card expandido
LARGURA_MINIMA_CARTAO = 300  # abaixo disso o card perde uma coluna em vez de encolher
ESPACO = 12  # entre cards (na horizontal e na vertical)
TAMANHO_PAGINA = 30  # cards mostrados por vez; o resto vem por "Carregar mais"
_RAIO = 10
_FAIXA = 6  # largura da faixa colorida lateral
_MARGEM = 14  # entre a faixa/borda e o texto
_ALFA_SELECAO = 40  # opacidade (0-255) da cor de destaque sobre o fundo do card selecionado

_COR_POR_ETAPA = {
    propostas_mod.ETAPA_APROVADO: "aprovado",
    propostas_mod.ETAPA_EFETIVADO: "efetivado",
    propostas_mod.ETAPA_NEGADO: "negado",
    propostas_mod.ETAPA_EM_ANALISE: "em_analise",
    propostas_mod.ETAPA_PRE_APROVADO: "pre_aprovado",
    propostas_mod.ETAPA_NF_ANEXADA: "nota_fiscal",
    propostas_mod.ETAPA_GARANTIA_ASSINADA: "garantia",
}


def chave_cor_etapa(etapa: str) -> str:
    """Chave de CORES_STATUS (desktop/theme.py) da etapa (propostas.ETAPA_*);
    sem status ou desconhecida -> "neutro" (cinza)."""
    return _COR_POR_ETAPA.get(etapa, "neutro")


def chave_cor_status(status: str) -> str:
    """Igual a chave_cor_etapa, a partir do texto do status."""
    return chave_cor_etapa(propostas_mod.etapa_status(status))


def linha_equipamento_banco(item: dict) -> str:
    """"Equipamento . Banco" do card; se so um dos dois existe, mostra so ele;
    se nenhum, "—" (a linha nunca some, pra os cards terem todos a mesma altura)."""
    partes = [(item.get("equipamento") or "").strip(), (item.get("banco") or "").strip()]
    return " · ".join(p for p in partes if p) or "—"


def linha_data_e_tempo(item: dict) -> str:
    """"11/09/2026 . ha 7 dias" (ou ". Encerrado"); sem tempo, so a data."""
    partes = [item.get("data") or "", (item.get("tempo") or "").strip()]
    return " · ".join(p for p in partes if p)


def titulo_do_card(item: dict) -> str:
    """O destaque do card: o cliente (Todas as Propostas) - ou o que o item
    trouxer em "titulo" (no historico do cliente, o banco)."""
    return item["titulo"] if "titulo" in item else item["cliente"]


def titulo_vazio_do_card(item: dict) -> str:
    """O que aparece no lugar do titulo quando ele esta em branco."""
    return item.get("titulo_vazio", "(cliente não encontrado)")


def segunda_linha_do_card(item: dict) -> str:
    """"Equipamento . Banco" (Todas as Propostas) - ou o que o item trouxer em
    "linha2" (no historico do cliente, "Equipamento . Valor")."""
    return item["linha2"] if "linha2" in item else linha_equipamento_banco(item)


class ModeloCartoes(QAbstractListModel):
    """Uma linha por card. Cada item e um dict com: "indice" (posicao real da
    proposta no arquivo - a que editar/excluir precisam), "cliente", "status",
    "data" (ja formatada), "equipamento", "banco" e "tempo" (ja formatado).
    Opcionais, pra outro uso do card (o historico do cliente): "titulo" e
    "titulo_vazio" (no lugar do cliente) e "linha2" (no lugar de "Equipamento .
    Banco"). "etapa" e "cor" pintam a faixa e a pilula do status.

    So as primeiras `pagina` linhas aparecem; se sobram itens, a linha depois
    da ultima e o card "Carregar mais" (ver eh_mais/mostrar_mais).

    Alem dos itens, pode haver UM card "Nova proposta" (rascunho) na linha 0, ainda
    nao gravado (ver definir_rascunho): ele nao e uma proposta do arquivo, entao nao
    conta na paginacao nem tem "indice"."""

    def __init__(self, parent: QWidget | None = None, tamanho_pagina: int = TAMANHO_PAGINA):
        super().__init__(parent)
        self._todos: list[dict] = []
        self._rascunho: dict | None = None  # o card "Nova proposta", na linha 0
        self._pagina = tamanho_pagina
        self._limite = tamanho_pagina
        self._tem_mais = False  # ha o card "Carregar mais" no fim
        # o que o card "Carregar mais" mostra ("Carregar mais 30", "mostrando 30 de
        # 65"). Fica numa "foto" atualizada SO depois de inserir as linhas novas:
        # inserir linhas nao pode alterar os dados das que ja existiam (contrato
        # do QAbstractItemModel, conferido pelo QAbstractItemModelTester nos testes)
        self._dados_mais: dict = {}

    def definir_itens(self, itens: list[dict], manter_limite: bool = False, garantir_visivel: int | None = None) -> None:
        """`manter_limite`: recarregar (ex.: depois de editar) sem voltar pra
        primeira pagina; `garantir_visivel`: indice real de uma proposta que
        precisa estar entre as mostradas (ex.: o card selecionado)."""
        self.beginResetModel()
        self._todos = itens
        if not manter_limite:
            self._limite = self._pagina
        if garantir_visivel is not None:
            posicao = next((i for i, item in enumerate(itens) if item["indice"] == garantir_visivel), None)
            if posicao is not None and posicao >= self._limite:
                self._limite = (posicao // self._pagina + 1) * self._pagina
        self._tem_mais = self._limite < len(self._todos)
        self._atualizar_dados_mais()
        self.endResetModel()

    def _atualizar_dados_mais(self) -> None:
        self._dados_mais = {"tipo": "mais", "proximos": self.proximos(), "visiveis": self.visiveis(), "total": self.total()}

    # -- paginacao --------------------------------------------------------------

    def total(self) -> int:
        return len(self._todos)

    def visiveis(self) -> int:
        return min(self._limite, len(self._todos))

    def restantes(self) -> int:
        return len(self._todos) - self.visiveis()

    def proximos(self) -> int:
        """Quantos cards o proximo "Carregar mais" traz."""
        return min(self._pagina, self.restantes())

    def _deslocamento(self) -> int:
        """Quantas linhas vem ANTES dos itens (1 se ha o card "Nova proposta")."""
        return 0 if self._rascunho is None else 1

    def eh_mais(self, linha: int) -> bool:
        return self._tem_mais and linha == self.visiveis() + self._deslocamento()

    def mostrar_mais(self) -> None:
        if not self._tem_mais:
            return
        antes = self.visiveis()
        novo = min(antes + self._pagina, len(self._todos))
        desloc = self._deslocamento()
        # os cards novos entram ANTES do card "Carregar mais" (que era a linha
        # `antes` e passa a ser a `novo`) - inserir linhas de verdade, em vez de
        # resetar o modelo, mantem a rolagem e a selecao onde estavam
        self.beginInsertRows(QModelIndex(), antes + desloc, novo - 1 + desloc)
        self._limite = novo
        self.endInsertRows()
        if novo >= len(self._todos):
            self.beginRemoveRows(QModelIndex(), novo + desloc, novo + desloc)
            self._tem_mais = False
            self.endRemoveRows()
        else:
            self._atualizar_dados_mais()
            indice = self.index(novo + desloc)
            self.dataChanged.emit(indice, indice)  # o card "Carregar mais" muda de texto

    # -- card "Nova proposta" -----------------------------------------------------

    def tem_rascunho(self) -> bool:
        return self._rascunho is not None

    def eh_rascunho(self, linha: int) -> bool:
        return self._rascunho is not None and linha == 0

    def definir_rascunho(self, item: dict | None) -> None:
        """Poe (ou tira, com None) o card "Nova proposta" no topo da lista. Persiste
        quando os itens sao recarregados (`definir_itens`): quem o criou e quem o tira."""
        if item is None and self._rascunho is not None:
            self.beginRemoveRows(QModelIndex(), 0, 0)
            self._rascunho = None
            self.endRemoveRows()
        elif item is not None and self._rascunho is None:
            self.beginInsertRows(QModelIndex(), 0, 0)
            self._rascunho = item
            self.endInsertRows()
        elif item is not None:
            self._rascunho = item
            self.dataChanged.emit(self.index(0), self.index(0))

    # -- acesso -------------------------------------------------------------------

    def item(self, linha: int) -> dict | None:
        if self.eh_rascunho(linha):
            return self._rascunho
        posicao = linha - self._deslocamento()
        if 0 <= posicao < self.visiveis():
            return self._todos[posicao]
        return None

    def indice_real(self, linha: int) -> int | None:
        """Posicao real da proposta no arquivo; None nos cards "Carregar mais" e
        "Nova proposta" (que nao sao propostas do arquivo)."""
        item = self.item(linha)
        return None if item is None else item.get("indice")

    def linha_do_indice_real(self, indice_real: int) -> int | None:
        """Linha do card dessa proposta ENTRE OS MOSTRADOS (None se nao esta
        na pagina atual)."""
        desloc = self._deslocamento()
        return next((i + desloc for i in range(self.visiveis()) if self._todos[i]["indice"] == indice_real), None)

    def linha_da_chave(self, chave) -> int | None:
        """Linha do card expandido identificado por `chave`: o indice real de uma
        proposta, ou RASCUNHO (o card "Nova proposta")."""
        if chave == RASCUNHO:
            return 0 if self._rascunho is not None else None
        return self.linha_do_indice_real(chave)

    # -- QAbstractListModel -------------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else self.visiveis() + (1 if self._tem_mais else 0) + self._deslocamento()

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= self.rowCount():
            return None
        if self.eh_mais(index.row()):
            mais = self._dados_mais
            if role == PAPEL_CARTAO:
                return mais
            if role == Qt.ItemDataRole.DisplayRole:
                return f"Carregar mais {mais['proximos']}"
            if role == Qt.ItemDataRole.ToolTipRole:
                return f"Mostrando {mais['visiveis']} de {mais['total']} — clique para carregar mais {mais['proximos']}"
            return None

        item = self.item(index.row())
        if item is None:
            return None
        if role == PAPEL_CARTAO:
            return item
        if role == Qt.ItemDataRole.DisplayRole:
            return titulo_do_card(item)
        if role == Qt.ItemDataRole.ToolTipRole and item.get("tipo") == "rascunho":
            return "Nova proposta (ainda não gravada)"
        if role == Qt.ItemDataRole.ToolTipRole:
            # o texto no card pode aparecer cortado ("..."): o hover mostra inteiro
            return (
                f"{titulo_do_card(item) or titulo_vazio_do_card(item)}\n"
                f"{segunda_linha_do_card(item)}\n"
                f"{item['status'] or 'Sem status'} · {linha_data_e_tempo(item)}\n"
                "Duplo clique para ver os detalhes"
            )
        return None


def _alinhar(*flags) -> int:
    """Combina flags de alinhamento (Qt.AlignmentFlag e Qt.TextFlag) no inteiro
    que QPainter.drawText espera - o PySide6 nao mistura os dois tipos com "|"."""
    resultado = 0
    for flag in flags:
        resultado |= flag.value
    return resultado


def _fonte(base: QFont, delta: float = 0, negrito: bool = False) -> QFont:
    fonte = QFont(base)
    if fonte.pixelSize() > 0:
        fonte.setPixelSize(max(9, round(fonte.pixelSize() + delta)))
    else:
        fonte.setPointSizeF(max(7.0, fonte.pointSizeF() + delta * 0.75))
    fonte.setBold(negrito)
    return fonte


class DelegateCartao(QStyledItemDelegate):
    """Desenha os cards. UM card pode estar EXPANDIDO (ver ListaCartoes.expandir): ele
    fica maior - a largura de uma linha inteira da grade e a altura do formulario que
    leva dentro - e o resto da lista se ajusta em volta. O delegate pinta so o fundo e o
    cabecalho do card expandido; o formulario e um widget de verdade, posto por cima."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._largura = LARGURA_MINIMA_CARTAO
        self._largura_expandida = LARGURA_MINIMA_CARTAO
        self._expandido: QPersistentModelIndex | None = None
        self._altura_formulario = 0
        self.atualizar_tema()

    def atualizar_tema(self) -> None:
        tema = settings_mod.obter_tema()
        self._tema = tema if tema in PALETAS else TEMA_ESCURO

    def paleta(self) -> dict:
        return PALETAS[self._tema]

    def definir_largura(self, largura: int, largura_expandida: int | None = None) -> None:
        self._largura = largura
        self._largura_expandida = largura if largura_expandida is None else largura_expandida

    # -- card expandido ---------------------------------------------------------

    def definir_expandido(self, indice: QPersistentModelIndex | None, altura_formulario: int = 0) -> None:
        self._expandido = indice
        self._altura_formulario = altura_formulario

    def linha_expandida(self) -> int | None:
        if self._expandido is not None and self._expandido.isValid():
            return self._expandido.row()
        return None

    def eh_expandido(self, index: QModelIndex) -> bool:
        return index.isValid() and index.row() == self.linha_expandida()

    def altura_expandida(self) -> int:
        """Altura do CARD expandido (sem o espaco entre cards)."""
        return ALTURA_CABECALHO + self._altura_formulario + _RODAPE_EXPANDIDO

    def retangulo_do_cartao(self, retangulo_da_celula: QRect, expandido: bool = False) -> QRect:
        """O card ocupa so o canto da celula - o resto e o espaco entre cards."""
        if expandido:
            return QRect(retangulo_da_celula.left(), retangulo_da_celula.top(), self._largura_expandida, self.altura_expandida())
        return QRect(retangulo_da_celula.left(), retangulo_da_celula.top(), self._largura, ALTURA_CARTAO)

    def area_do_formulario(self, cartao: QRect) -> QRect:
        """Onde fica o formulario dentro do card expandido: abaixo do cabecalho, depois da faixa."""
        esquerda = cartao.left() + _FAIXA + _MARGEM
        return QRect(esquerda, cartao.top() + ALTURA_CABECALHO, cartao.right() - _MARGEM - esquerda + 1, self._altura_formulario)

    def updateEditorGeometry(self, editor: QWidget, option, index: QModelIndex) -> None:
        editor.setGeometry(self.area_do_formulario(self.retangulo_do_cartao(option.rect, expandido=True)))

    def destroyEditor(self, editor: QWidget, index: QModelIndex) -> None:
        # o Qt "destroi" o widget do card expandido quando o modelo e recarregado; quem manda
        # nele e a ListaCartoes (que o poe de volta no lugar, ou o descarta): so esconde
        editor.hide()

    def sizeHint(self, option, index) -> QSize:
        if self.eh_expandido(index):
            return QSize(self._largura_expandida + ESPACO, self.altura_expandida() + ESPACO)
        return QSize(self._largura + ESPACO, ALTURA_CARTAO + ESPACO)

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        item = index.data(PAPEL_CARTAO)
        if not item:
            return
        selecionado = bool(option.state & QStyle.StateFlag.State_Selected)
        sobre = bool(option.state & QStyle.StateFlag.State_MouseOver)
        expandido = self.eh_expandido(index)
        cartao = QRectF(self.retangulo_do_cartao(option.rect, expandido)).adjusted(0.5, 0.5, -0.5, -0.5)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        if item.get("tipo") == "mais":
            self._pintar_carregar_mais(painter, option, item, cartao, selecionado, sobre)
        elif expandido:
            self._pintar_expandido(painter, option, item, cartao, selecionado, sobre)
        else:
            self._pintar_proposta(painter, option, item, cartao, selecionado, sobre)
        painter.restore()

    def _cor_do_item(self, item: dict) -> dict:
        """Faixa/pilula do card: a do status; o card "Nova proposta" usa a cor de destaque do tema."""
        if item.get("tipo") == "rascunho":
            destaque = self.paleta()["destaque"]
            return {"faixa": destaque, "fundo": destaque, "texto": "#ffffff"}
        return CORES_STATUS[self._tema][item.get("cor") or chave_cor_status(item["status"])]

    def _pintar_fundo(self, painter: QPainter, cartao: QRectF, cor: dict, selecionado: bool, sobre: bool) -> None:
        """Fundo arredondado, faixa colorida lateral e borda (mais grossa e azulada se selecionado)."""
        paleta = self.paleta()
        contorno = QPainterPath()
        contorno.addRoundedRect(cartao, _RAIO, _RAIO)
        painter.fillPath(contorno, QColor(paleta["bg_card"]))
        if selecionado:
            # o clique so seleciona: alem da borda mais grossa, um fundo azulado
            # (o texto secundario segue com contraste >= 4,5:1 nos dois temas)
            realce = QColor(paleta["destaque"])
            realce.setAlpha(_ALFA_SELECAO)
            painter.fillPath(contorno, realce)
        # faixa colorida: pintada recortada pelo contorno arredondado do card
        painter.save()
        painter.setClipPath(contorno)
        painter.fillRect(QRectF(cartao.left(), cartao.top(), _FAIXA, cartao.height()), QColor(cor["faixa"]))
        painter.restore()

        if selecionado:
            caneta = QPen(QColor(paleta["destaque"]), 2)
        elif sobre:
            caneta = QPen(QColor(paleta["destaque"]), 1)
        else:
            caneta = QPen(QColor(paleta["borda"]), 1)
        painter.setPen(caneta)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(contorno)

    def _pintar_pilula(self, painter: QPainter, option, item: dict, cor: dict, direita: float, centro_y: float, largura_texto: float) -> float:
        """A pilula colorida com o status, encostada em `direita`; devolve a largura dela."""
        fonte_pilula = _fonte(option.font, delta=-2, negrito=True)
        metricas = QFontMetrics(fonte_pilula)
        texto_status = item["status"] or "Sem status"
        largura_pilula = min(metricas.horizontalAdvance(texto_status) + 20, int(largura_texto * 0.55))
        pilula = QRectF(direita - largura_pilula, centro_y - 11, largura_pilula, 22)
        painter.setPen(QPen(QColor(cor["faixa"]), 1))
        painter.setBrush(QColor(cor["fundo"]))
        painter.drawRoundedRect(pilula, 11, 11)
        painter.setFont(fonte_pilula)
        painter.setPen(QColor(cor["texto"]))
        painter.drawText(
            pilula.adjusted(8, 0, -8, 0),
            _alinhar(Qt.AlignmentFlag.AlignCenter),
            metricas.elidedText(texto_status, Qt.TextElideMode.ElideRight, int(pilula.width() - 16)),
        )
        return largura_pilula

    def _pintar_expandido(self, painter: QPainter, option, item: dict, cartao: QRectF, selecionado: bool, sobre: bool) -> None:
        """O card expandido: o mesmo fundo/faixa/borda, e no topo so o destaque (cliente ou banco)
        com a pilula do status; o resto (data, valor, equipamento...) e o formulario, por cima."""
        paleta = self.paleta()
        cor = self._cor_do_item(item)
        self._pintar_fundo(painter, cartao, cor, selecionado, sobre)

        esquerda = cartao.left() + _FAIXA + _MARGEM
        direita = cartao.right() - _MARGEM
        largura_texto = direita - esquerda
        centro_y = cartao.top() + ALTURA_CABECALHO / 2

        largura_pilula = 0.0
        if item.get("tipo") != "rascunho":  # o card "Nova proposta" ainda nao tem status gravado
            largura_pilula = self._pintar_pilula(painter, option, item, cor, direita, centro_y, largura_texto)

        fonte_nome = _fonte(option.font, delta=1, negrito=True)
        painter.setFont(fonte_nome)
        titulo = titulo_do_card(item)
        painter.setPen(QColor(paleta["texto"] if titulo else paleta["texto_secundario"]))
        texto = QFontMetrics(fonte_nome).elidedText(
            titulo or titulo_vazio_do_card(item), Qt.TextElideMode.ElideRight, max(0, int(largura_texto - largura_pilula - 12))
        )
        painter.drawText(
            QRectF(esquerda, cartao.top(), largura_texto, ALTURA_CABECALHO),
            _alinhar(Qt.AlignmentFlag.AlignLeft, Qt.AlignmentFlag.AlignVCenter),
            texto,
        )

        # separador entre o cabecalho e o formulario
        painter.setPen(QPen(QColor(paleta["borda"]), 1))
        y = cartao.top() + ALTURA_CABECALHO - 2
        painter.drawLine(QPointF(esquerda, y), QPointF(direita, y))

    def _pintar_proposta(self, painter: QPainter, option, item: dict, cartao: QRectF, selecionado: bool, sobre: bool) -> None:
        paleta = self.paleta()
        cor = self._cor_do_item(item)

        self._pintar_fundo(painter, cartao, cor, selecionado, sobre)

        esquerda = cartao.left() + _FAIXA + _MARGEM
        direita = cartao.right() - _MARGEM
        largura_texto = int(direita - esquerda)
        alinhamento_esquerda = _alinhar(Qt.AlignmentFlag.AlignLeft, Qt.AlignmentFlag.AlignVCenter)

        # -- 1a linha: o destaque do card (o cliente; no historico, o banco) ------
        fonte_nome = _fonte(option.font, delta=1, negrito=True)
        painter.setFont(fonte_nome)
        titulo = titulo_do_card(item)
        if titulo:
            painter.setPen(QColor(paleta["texto"]))
            texto_nome = titulo
        else:
            painter.setPen(QColor(paleta["texto_secundario"]))
            texto_nome = titulo_vazio_do_card(item)
        texto_nome = QFontMetrics(fonte_nome).elidedText(texto_nome, Qt.TextElideMode.ElideRight, largura_texto)
        painter.drawText(QRectF(esquerda, cartao.top() + 10, largura_texto, 22), alinhamento_esquerda, texto_nome)

        # -- 2a linha: Equipamento . Banco (discreta) -------------------------
        # e o que diferencia as varias propostas do mesmo cliente na mesma data
        # (no historico do cliente: Equipamento . Valor)
        fonte_secundaria = _fonte(option.font, delta=-1)
        painter.setFont(fonte_secundaria)
        painter.setPen(QColor(paleta["texto_secundario"]))
        texto_produto = QFontMetrics(fonte_secundaria).elidedText(
            segunda_linha_do_card(item), Qt.TextElideMode.ElideRight, largura_texto
        )
        painter.drawText(QRectF(esquerda, cartao.top() + 34, largura_texto, 18), alinhamento_esquerda, texto_produto)

        # -- 3a linha: data + tempo (esquerda) e pilula do status (direita) ---
        faixa_de_baixo = QRectF(esquerda, cartao.top() + 58, largura_texto, 30)

        largura_pilula = self._pintar_pilula(
            painter, option, item, cor, direita, faixa_de_baixo.center().y(), largura_texto
        )

        painter.setFont(fonte_secundaria)
        painter.setPen(QColor(paleta["texto_secundario"]))
        largura_data = max(0, int(largura_texto - largura_pilula - 8))
        texto_data = QFontMetrics(fonte_secundaria).elidedText(
            linha_data_e_tempo(item), Qt.TextElideMode.ElideRight, largura_data
        )
        painter.drawText(QRectF(esquerda, faixa_de_baixo.top(), largura_data, faixa_de_baixo.height()), alinhamento_esquerda, texto_data)

    def _pintar_carregar_mais(self, painter: QPainter, option, item: dict, cartao: QRectF, selecionado: bool, sobre: bool) -> None:
        """O card do fim da lista: tracejado, sem faixa nem pilula, so o convite
        pra mostrar os proximos."""
        paleta = self.paleta()
        contorno = QPainterPath()
        contorno.addRoundedRect(cartao, _RAIO, _RAIO)
        destacado = selecionado or sobre
        caneta = QPen(QColor(paleta["destaque"] if destacado else paleta["texto_secundario"]), 2 if selecionado else 1.5)
        caneta.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(caneta)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(contorno)

        centro = _alinhar(Qt.AlignmentFlag.AlignCenter)
        fonte_titulo = _fonte(option.font, delta=1, negrito=True)
        painter.setFont(fonte_titulo)
        painter.setPen(QColor(paleta["destaque"] if destacado else paleta["texto"]))
        painter.drawText(QRectF(cartao.left(), cartao.top() + 24, cartao.width(), 24), centro, f"+ Carregar mais {item['proximos']}")
        painter.setFont(_fonte(option.font, delta=-1))
        painter.setPen(QColor(paleta["texto_secundario"]))
        painter.drawText(
            QRectF(cartao.left(), cartao.top() + 50, cartao.width(), 20), centro, f"mostrando {item['visiveis']} de {item['total']}"
        )


class ListaCartoes(QListView):
    """Grade de cards que se ajusta a largura da janela: quantas colunas
    couberem (cada card com pelo menos LARGURA_MINIMA_CARTAO), esticando os
    cards pra preencher a linha.

    Um clique num card so o SELECIONA (destaque visual, sem abrir nada); o duplo
    clique (ou Enter) emite `acionado` com o numero da linha - e quem abre os
    detalhes. O card "Carregar mais" nao e uma proposta: um clique (ou Enter)
    nele mostra os proximos cards e NAO emite `acionado`.

    `altura_automatica`: a lista tem a altura dos seus cards (sem barra de
    rolagem propria) - pra ficar dentro de um painel que ja rola (o historico
    de propostas da Ficha de Cliente).

    EXPANDIR um card (`expandir`): ele cresce, ocupando uma linha INTEIRA da grade,
    e leva dentro um widget (o formulario da proposta) - os cards de baixo descem, nada
    fica coberto. So um por vez. O card expandido e identificado pela CHAVE (o indice
    real da proposta, ou RASCUNHO): se o modelo e recarregado, ele volta pro lugar (ou,
    se a proposta saiu da lista, e descartado e `expansao_perdida` avisa)."""

    acionado = Signal(int)
    altura_mudou = Signal(int)  # so no modo `altura_automatica`: a nova altura da lista
    expansao_perdida = Signal(object)  # a chave do card expandido que saiu da lista (o widget foi descartado)
    rolar_pedido = Signal(QRect)  # so no modo `altura_automatica`: area (em coordenadas da lista) a mostrar

    def __init__(self, parent: QWidget | None = None, altura_automatica: bool = False):
        super().__init__(parent)
        self._delegate = DelegateCartao(self)
        self.setItemDelegate(self._delegate)
        self._altura_automatica = altura_automatica
        self._mensagem_vazia = ""
        self._dimensoes = (0, 0)  # (largura do card, largura do card expandido) da ultima grade calculada
        self._chave_expandida = None
        self._widget_expandido: QWidget | None = None
        self._instante_carregar_mais = float("-inf")  # ver mouseDoubleClickEvent
        self._area_carregar_mais = QRect()

        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setWrapping(True)
        self.setFlow(QListView.Flow.LeftToRight)
        # tamanhos variaveis (o card expandido e maior) e SEM grade fixa: cada item vale o
        # tamanho que o delegate diz (o card + o espaco depois dele)
        self.setUniformItemSizes(False)
        self.setSpacing(0)
        self.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.setEditTriggers(QListView.EditTrigger.NoEditTriggers)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        if altura_automatica:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)  # quem rola e o painel em volta
        self.setMouseTracking(True)

        self.clicked.connect(self._ao_clicar)
        self.doubleClicked.connect(self._ao_duplo_clique)
        self._ajustar_colunas()

    def setModel(self, modelo) -> None:
        super().setModel(modelo)
        if modelo is None:
            return
        # o card expandido precisa voltar pro lugar ANTES de a altura ser recalculada
        modelo.modelReset.connect(self._ao_recarregar_modelo)
        modelo.rowsRemoved.connect(self._ao_remover_linhas)
        if self._altura_automatica:
            for sinal in (modelo.rowsInserted, modelo.rowsRemoved, modelo.modelReset, modelo.layoutChanged):
                sinal.connect(self._ajustar_altura)
            self._ajustar_altura()

    def definir_mensagem_vazia(self, texto: str) -> None:
        self._mensagem_vazia = texto
        self.viewport().update()

    def linha_atual(self) -> int | None:
        indice = self.currentIndex()
        return indice.row() if indice.isValid() else None

    # -- card expandido ----------------------------------------------------------

    def expandir(self, chave, widget: QWidget) -> bool:
        """Expande o card da `chave` (indice real da proposta, ou RASCUNHO) com `widget`
        dentro; o que estava expandido antes e recolhido (e o widget dele, descartado).
        False se a chave nao esta na lista."""
        modelo = self.model()
        linha = modelo.linha_da_chave(chave) if isinstance(modelo, ModeloCartoes) else None
        if linha is None:
            return False
        self.recolher()
        self._chave_expandida = chave
        self._widget_expandido = widget
        widget.ensurePolished()  # a altura do card vem do tamanho do widget: com o estilo do tema ja aplicado
        self._anexar(linha)
        return True

    def recolher(self) -> None:
        """Volta o card expandido ao tamanho normal e descarta o widget que ele levava."""
        widget, self._widget_expandido = self._widget_expandido, None
        self._chave_expandida = None
        if widget is None:
            return
        indice = self._delegate._expandido
        self._delegate.definir_expandido(None)
        widget.hide()  # o Qt so APAGA o widget no proximo ciclo de eventos: ate la ele ainda seria desenhado
        if indice is not None and indice.isValid():
            self.setIndexWidget(self.model().index(indice.row()), None)  # o Qt apaga o widget
        widget.deleteLater()
        self._depois_de_mudar_o_tamanho()

    def chave_expandida(self):
        return self._chave_expandida

    def widget_expandido(self) -> QWidget | None:
        return self._widget_expandido

    def linha_expandida(self) -> int | None:
        return self._delegate.linha_expandida()

    def atualizar_tamanho_do_expandido(self) -> None:
        """O widget do card expandido mudou de tamanho: o card acompanha."""
        if self._widget_expandido is None:
            return
        self._delegate.definir_expandido(self._delegate._expandido, self._widget_expandido.sizeHint().height())
        self._depois_de_mudar_o_tamanho()

    def _anexar(self, linha: int) -> None:
        """Poe o widget guardado no card da `linha` e deixa o card crescer."""
        indice = self.model().index(linha)
        widget = self._widget_expandido
        self._delegate.definir_expandido(QPersistentModelIndex(indice), widget.sizeHint().height())
        self.setIndexWidget(indice, widget)
        widget.show()
        self._depois_de_mudar_o_tamanho()

    def _depois_de_mudar_o_tamanho(self) -> None:
        self.doItemsLayout()  # na hora: o card cresce e os de baixo descem ja
        self._ajustar_altura()
        self.viewport().update()

    def _ao_recarregar_modelo(self) -> None:
        """O Qt descarta os widgets dos itens quando o modelo e recarregado: o do card
        expandido volta pro lugar dele, e se a proposta nao esta mais na lista, sai."""
        if self._widget_expandido is None:
            return
        linha = self.model().linha_da_chave(self._chave_expandida)
        if linha is None:
            self._perder_expansao()
        else:
            self._anexar(linha)

    def _ao_remover_linhas(self, *_args) -> None:
        if self._widget_expandido is not None and self.model().linha_da_chave(self._chave_expandida) is None:
            self._perder_expansao()

    def _perder_expansao(self) -> None:
        chave = self._chave_expandida
        self._delegate.definir_expandido(None)
        self._depois_de_mudar_o_tamanho()
        # o widget so e apagado depois de avisar: quem escuta ainda pode olhar o que havia nele
        self.expansao_perdida.emit(chave)
        widget, self._widget_expandido = self._widget_expandido, None
        self._chave_expandida = None
        if widget is not None:
            widget.hide()
            widget.deleteLater()

    def garantir_visivel(self, linha: int) -> None:
        """Rola ate mostrar o card da `linha` (o card expandido e alto: se nao cabe, o topo dele)."""
        indice = self.model().index(linha)
        if not indice.isValid():
            return
        if self._altura_automatica:
            # a lista nao rola sozinha: quem rola e o painel em volta, que decide
            self.doItemsLayout()
            self.rolar_pedido.emit(self.visualRect(indice))
            return
        cabe = self.visualRect(indice).height() <= self.viewport().height()
        self.scrollTo(indice, QListView.ScrollHint.EnsureVisible if cabe else QListView.ScrollHint.PositionAtTop)

    # -- layout responsivo ---------------------------------------------------

    def _largura_util(self) -> int:
        """Largura disponivel pros cards, contando SEMPRE com o espaco da barra
        de rolagem (aparecendo ou nao): assim o numero de colunas nao depende
        de a barra estar visivel - senao ela aparecendo/sumindo mudaria a
        largura, e com ela as colunas, e o layout oscilaria. A folga de 2px e
        porque a grade do Qt quebra a linha se a soma das celulas for igual a
        largura do viewport. (Sem barra propria - `altura_automatica` - nao ha
        o que reservar.)"""
        barra = 0 if self._altura_automatica else self.verticalScrollBar().sizeHint().width()
        return self.width() - 2 * self.frameWidth() - barra - 2

    def _ajustar_colunas(self) -> None:
        util = self._largura_util()
        if util <= 0:
            return
        # a grade do Qt precisa que as CELULAS (card + espaco) caibam inteiras na
        # largura - inclusive a da ultima coluna, cujo espaco fica sobrando no canto
        colunas = max(1, util // (LARGURA_MINIMA_CARTAO + ESPACO))
        celula = util // colunas
        largura = max(120, celula - ESPACO)
        # o card expandido vale a linha toda: termina na mesma borda direita do ultimo card da linha
        largura_expandida = max(largura, colunas * celula - ESPACO)
        if (largura, largura_expandida) == self._dimensoes:
            return
        self._dimensoes = (largura, largura_expandida)
        self._delegate.definir_largura(largura, largura_expandida)
        self.scheduleDelayedItemsLayout()

    def _altura_do_conteudo(self) -> int:
        """Altura de todas as linhas de cards. A do card expandido e outra, e ele fica numa
        linha so dele: os cards antes dele enchem as suas linhas (a ultima pode ficar
        incompleta) e os de depois recomecam numa linha nova."""
        modelo = self.model()
        total = modelo.rowCount() if modelo is not None else 0
        colunas = self.colunas()
        expandida = self._delegate.linha_expandida()
        if expandida is None or expandida >= total:
            return -(-total // colunas) * (ALTURA_CARTAO + ESPACO)
        antes = -(-expandida // colunas)
        depois = -(-(total - expandida - 1) // colunas)
        return (antes + depois) * (ALTURA_CARTAO + ESPACO) + self._delegate.altura_expandida() + ESPACO

    def _ajustar_altura(self, *_args) -> None:
        """Modo `altura_automatica`: a altura acompanha o numero de linhas de
        cards (que depende de quantas colunas cabem na largura atual) e o card
        expandido, se houver."""
        if not self._altura_automatica:
            return
        altura = self._altura_do_conteudo() + 2 * self.frameWidth()
        if altura != self.height():
            self.setFixedHeight(altura)
            self.altura_mudou.emit(altura)

    def resizeEvent(self, evento) -> None:
        super().resizeEvent(evento)
        self._ajustar_colunas()
        self._ajustar_altura()

    def colunas(self) -> int:
        return max(1, self._largura_util() // (LARGURA_MINIMA_CARTAO + ESPACO))

    def largura_do_cartao(self) -> int:
        """Largura de cada card (normal) na grade de agora."""
        return self._dimensoes[0]

    def largura_do_cartao_expandido(self) -> int:
        return self._dimensoes[1]

    # -- interacao ---------------------------------------------------------------

    def indexAt(self, ponto: QPoint) -> QModelIndex:
        """So conta como "dentro do card" o desenho do card - o espaco entre
        cards (que faz parte da celula) nao seleciona nem aciona nada."""
        indice = super().indexAt(ponto)
        if indice.isValid():
            cartao = self._delegate.retangulo_do_cartao(self.visualRect(indice), self._delegate.eh_expandido(indice))
            if not cartao.contains(ponto):
                return QModelIndex()
        return indice

    def _eh_carregar_mais(self, linha: int) -> bool:
        modelo = self.model()
        return isinstance(modelo, ModeloCartoes) and modelo.eh_mais(linha)

    def _carregar_mais(self, area: QRect | None = None) -> None:
        """`area`: onde estava o card "Carregar mais" (se foi um clique), pra
        reconhecer o 2o clique de um duplo clique - ver mouseDoubleClickEvent."""
        self._instante_carregar_mais = time.monotonic()
        self._area_carregar_mais = QRect() if area is None else area
        self.model().mostrar_mais()

    def _ao_clicar(self, indice: QModelIndex) -> None:
        # num card de proposta o clique so seleciona (o Qt ja fez isso); so o
        # "Carregar mais" reage a um clique so, porque nao e uma proposta
        if self._eh_carregar_mais(indice.row()):
            self._carregar_mais(self.visualRect(indice))

    def _ao_duplo_clique(self, indice: QModelIndex) -> None:
        if not self._eh_carregar_mais(indice.row()):
            self.acionado.emit(indice.row())

    def mouseDoubleClickEvent(self, evento) -> None:
        """Duplo clique no "Carregar mais": o 1o clique ja mostrou os proximos
        cards e um deles ocupa agora o lugar do "Carregar mais" - o 2o clique
        cairia nele, selecionando (ou abrindo) uma proposta que a pessoa nao
        escolheu. Por isso o 2o clique, no mesmo lugar e logo depois de carregar
        mais, e ignorado. (Um duplo clique em OUTRO card segue valendo.)"""
        recente = time.monotonic() - self._instante_carregar_mais < QApplication.doubleClickInterval() / 1000
        if recente and self._area_carregar_mais.contains(evento.position().toPoint()):
            evento.accept()
            return
        super().mouseDoubleClickEvent(evento)

    def keyPressEvent(self, evento) -> None:
        # Enter e o "duplo clique" do teclado: abre a proposta selecionada
        if evento.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.currentIndex().isValid():
            linha = self.currentIndex().row()
            if self._eh_carregar_mais(linha):
                self._carregar_mais()
            else:
                self.acionado.emit(linha)
            return
        super().keyPressEvent(evento)

    def mouseMoveEvent(self, evento) -> None:
        sobre_card = self.indexAt(evento.position().toPoint()).isValid()
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if sobre_card else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(evento)

    # -- desenho / tema ---------------------------------------------------------

    def changeEvent(self, evento) -> None:
        # trocar o tema reaplica o stylesheet do app inteiro (StyleChange)
        if evento.type() == QEvent.Type.StyleChange:
            self._delegate.atualizar_tema()
            self.viewport().update()
        super().changeEvent(evento)

    def paintEvent(self, evento) -> None:
        super().paintEvent(evento)
        modelo = self.model()
        if self._mensagem_vazia and modelo is not None and modelo.rowCount() == 0:
            pintor = QPainter(self.viewport())
            pintor.setPen(QColor(self._delegate.paleta()["texto_secundario"]))
            pintor.drawText(
                self.viewport().rect().adjusted(16, 24, -16, 0),
                _alinhar(Qt.AlignmentFlag.AlignHCenter, Qt.AlignmentFlag.AlignTop, Qt.TextFlag.TextWordWrap),
                self._mensagem_vazia,
            )


class ContentorDeListaAutomatica(QWidget):
    """Guarda uma ListaCartoes em modo `altura_automatica` e a faz ESPACO px mais
    larga que o contentor (o excesso, que e so espaco vazio, fica cortado na
    direita). Motivo: a grade do Qt so acomoda celulas INTEIRAS (card + o espaco
    depois dele, tambem na ultima coluna); sem isto o ultimo card termina ESPACO px
    antes da borda direita do que esta em volta - ex.: o cartao de dados do cliente,
    logo acima do historico. A altura do contentor acompanha a da lista."""

    def __init__(self, lista: ListaCartoes, parent: QWidget | None = None):
        super().__init__(parent)
        self._lista = lista
        lista.setParent(self)
        lista.altura_mudou.connect(self.setFixedHeight)
        self.setFixedHeight(lista.height())

    def resizeEvent(self, evento) -> None:
        super().resizeEvent(evento)
        self._lista.setGeometry(0, 0, self.width() + ESPACO, self._lista.height())
