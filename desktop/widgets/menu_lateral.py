"""Menu de navegacao da barra lateral: uma lista de itens (icone de linha + rotulo), em grupos
com titulo discreto, e um selo opcional por item (a contagem de "propostas paradas", por
exemplo). E um QListWidget - o Qt cuida da selecao, do mouse e do teclado (setas) - mas
cada linha e desenhada por um delegate proprio, porque o QSS nao sabe colorir icone nem
posicionar um selo.

Recolhido (so os icones, na barra estreita): o titulo do grupo vira um filete e o selo
vira uma bolinha no canto do icone; o rotulo e o detalhe do selo passam pro tooltip.

    menu = MenuLateral()
    menu.definir_itens([GrupoDoMenu("Visão geral", [ItemDoMenu("dashboard", "Dashboard", "dashboard")])])
    menu.pagina_escolhida.connect(ir_para)     # recebe a chave do item escolhido
    menu.definir_selo("propostas", 31, "31 propostas em aberto há mais de 7 dias")
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QWidget,
)

from desktop import settings as settings_mod
from desktop.theme import CORES_STATUS, PALETAS, TEMA_ESCURO
from desktop.widgets.icones_linha import desenhar_icone

_PAPEL_CHAVE = Qt.ItemDataRole.UserRole  # None nas linhas de titulo de grupo
_PAPEL_ICONE = Qt.ItemDataRole.UserRole + 1
_PAPEL_SELO = Qt.ItemDataRole.UserRole + 2  # int (contagem) ou None
_PAPEL_SELO_ERRO = Qt.ItemDataRole.UserRole + 3  # texto do erro ("" = sem erro)

_LIMITE_DO_SELO = 99  # acima disso o selo mostra "99+"


@dataclass(frozen=True)
class ItemDoMenu:
    chave: str  # o que identifica a tela (nunca a posicao: ela muda conforme o papel de quem entrou)
    rotulo: str
    icone: str  # nome em icones_linha
    atalho: str = ""  # so pro tooltip (ex.: "Ctrl+1")


@dataclass(frozen=True)
class GrupoDoMenu:
    titulo: str | None
    itens: list[ItemDoMenu]


class MenuLateral(QListWidget):
    pagina_escolhida = Signal(str)  # a chave do item que ficou selecionado (clique, seta ou codigo)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("role", "menu_lateral")
        self.setFrameShape(QFrame.Shape.NoFrame)
        # poucos itens fixos: nunca precisa rolar (e o menu ja e retratil)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        self._recolhido = False
        self._itens_por_chave: dict[str, QListWidgetItem] = {}
        self._rotulos: dict[str, str] = {}
        self._atalhos: dict[str, str] = {}
        self._delegado = _DelegadoDoMenu(self)
        self.setItemDelegate(self._delegado)
        self.currentItemChanged.connect(self._ao_mudar_item_atual)

    # -- montagem -----------------------------------------------------------------

    def definir_itens(self, grupos: list[GrupoDoMenu]) -> None:
        """Monta o menu. O titulo do grupo so aparece quando ha mais de um grupo (com um so, o
        titulo nao separa nada)."""
        self.blockSignals(True)
        self.clear()
        self.blockSignals(False)
        self._itens_por_chave.clear()
        self._rotulos.clear()
        self._atalhos.clear()

        mostrar_titulos = len(grupos) > 1
        for grupo in grupos:
            if mostrar_titulos and grupo.titulo:
                cabecalho = QListWidgetItem(grupo.titulo)
                cabecalho.setData(_PAPEL_CHAVE, None)
                cabecalho.setFlags(Qt.ItemFlag.NoItemFlags)  # nao seleciona, nao recebe foco
                self.addItem(cabecalho)
            for item in grupo.itens:
                linha = QListWidgetItem(item.rotulo)
                linha.setData(_PAPEL_CHAVE, item.chave)
                linha.setData(_PAPEL_ICONE, item.icone)
                linha.setData(_PAPEL_SELO, None)
                linha.setData(_PAPEL_SELO_ERRO, "")
                self.addItem(linha)
                self._itens_por_chave[item.chave] = linha
                self._rotulos[item.chave] = item.rotulo
                self._atalhos[item.chave] = item.atalho
                self._atualizar_dica(item.chave, "")

    def chaves(self) -> list[str]:
        return list(self._itens_por_chave)

    def atalho(self, chave: str) -> str:
        return self._atalhos[chave]

    # -- escolha -----------------------------------------------------------------

    def escolher(self, chave: str) -> None:
        """Seleciona o item `chave` (e emite pagina_escolhida se ele nao era o atual)."""
        item = self._itens_por_chave.get(chave)
        if item is None:
            raise KeyError(f"Item de menu inexistente: {chave!r}")
        self.setCurrentItem(item)

    def chave_atual(self) -> str | None:
        item = self.currentItem()
        return None if item is None else item.data(_PAPEL_CHAVE)

    def _ao_mudar_item_atual(self, atual: QListWidgetItem | None, _anterior) -> None:
        chave = None if atual is None else atual.data(_PAPEL_CHAVE)
        if chave:
            self.pagina_escolhida.emit(chave)

    # -- recolher -----------------------------------------------------------------

    def esta_recolhido(self) -> bool:
        return self._recolhido

    def definir_recolhido(self, recolhido: bool) -> None:
        self._recolhido = recolhido
        self._delegado.definir_recolhido(recolhido)
        self.doItemsLayout()  # as alturas dos titulos mudam: refaz ja, nao no proximo ciclo de eventos
        self.viewport().update()

    # -- selo ---------------------------------------------------------------------

    def definir_selo(self, chave: str, quantidade: int | None, dica: str = "", erro: str = "") -> None:
        """Poe (ou tira) o selo do item. `quantidade` None ou 0: sem selo. `erro` preenchido: em
        vez do numero mostra "!" e o texto do erro vai no tooltip - assim uma contagem que falhou
        nunca some sem aviso."""
        item = self._itens_por_chave[chave]
        item.setData(_PAPEL_SELO, quantidade if quantidade else None)
        item.setData(_PAPEL_SELO_ERRO, erro)
        self._atualizar_dica(chave, erro or dica)
        self.viewport().update()

    def selo(self, chave: str) -> int | None:
        return self._itens_por_chave[chave].data(_PAPEL_SELO)

    def selo_erro(self, chave: str) -> str:
        return self._itens_por_chave[chave].data(_PAPEL_SELO_ERRO) or ""

    def texto_do_selo(self, chave: str) -> str:
        """O que o selo mostra: "" (sem selo), "!" (erro), "7" ou "99+"."""
        return texto_do_selo(self.selo(chave), self.selo_erro(chave))

    def _atualizar_dica(self, chave: str, detalhe: str) -> None:
        atalho = self._atalhos.get(chave, "")
        titulo = f"{self._rotulos[chave]}  ({atalho})" if atalho else self._rotulos[chave]
        self._itens_por_chave[chave].setToolTip(f"{titulo}\n{detalhe}" if detalhe else titulo)

    # -- tema ---------------------------------------------------------------------

    def changeEvent(self, evento: QEvent) -> None:
        # trocar o tema reaplica o stylesheet do app (StyleChange): e o sinal pra reler as cores
        if evento.type() == QEvent.Type.StyleChange:
            self._delegado.atualizar_paleta()
            self.viewport().update()
        super().changeEvent(evento)


def texto_do_selo(quantidade: int | None, erro: str = "") -> str:
    if erro:
        return "!"
    if not quantidade:
        return ""
    return f"{_LIMITE_DO_SELO}+" if quantidade > _LIMITE_DO_SELO else str(quantidade)


class _DelegadoDoMenu(QStyledItemDelegate):
    _ALTURA_ITEM = 40
    _ALTURA_TITULO = 30
    _ALTURA_TITULO_RECOLHIDO = 14
    _LADO_ICONE = 18
    _MARGEM_ESQUERDA = 14  # do canto do item ate o icone (expandido)
    _ESPACO_ICONE_TEXTO = 10
    _ALTURA_SELO = 18

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._recolhido = False
        self.atualizar_paleta()

    def definir_recolhido(self, recolhido: bool) -> None:
        self._recolhido = recolhido

    def atualizar_paleta(self) -> None:
        tema = settings_mod.obter_tema()
        self._paleta = PALETAS.get(tema, PALETAS[TEMA_ESCURO])
        self._cores_selo = CORES_STATUS.get(tema, CORES_STATUS[TEMA_ESCURO])["em_analise"]

    # -- tamanho ------------------------------------------------------------------

    def sizeHint(self, opcao, indice) -> QSize:
        if indice.data(_PAPEL_CHAVE) is None:
            return QSize(0, self._ALTURA_TITULO_RECOLHIDO if self._recolhido else self._ALTURA_TITULO)
        return QSize(0, self._ALTURA_ITEM)  # a largura o QListWidget estica ate a da lista

    # -- desenho ------------------------------------------------------------------

    def paint(self, pintor: QPainter, opcao, indice) -> None:
        pintor.save()
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        if indice.data(_PAPEL_CHAVE) is None:
            self._pintar_titulo(pintor, opcao, indice)
        else:
            self._pintar_item(pintor, opcao, indice)
        pintor.restore()

    def _pintar_titulo(self, pintor: QPainter, opcao, indice) -> None:
        p = self._paleta
        area = QRectF(opcao.rect)
        if self._recolhido:
            if indice.row() > 0:  # o primeiro grupo nao precisa de filete por cima
                pintor.setPen(QPen(QColor(p["borda"]), 1))
                y = area.center().y()
                pintor.drawLine(int(area.center().x() - 12), int(y), int(area.center().x() + 12), int(y))
            return
        fonte = QFont(opcao.font)
        fonte.setPixelSize(10)
        fonte.setWeight(QFont.Weight.DemiBold)
        fonte.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.8)
        pintor.setFont(fonte)
        cor = QColor(p["texto_secundario"])
        cor.setAlpha(200)
        pintor.setPen(cor)
        pintor.drawText(
            QRectF(area.left() + self._MARGEM_ESQUERDA, area.top(), area.width() - self._MARGEM_ESQUERDA, area.height() - 4),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
            indice.data(Qt.ItemDataRole.DisplayRole).upper(),
        )

    def _pintar_item(self, pintor: QPainter, opcao, indice) -> None:
        p = self._paleta
        area = QRectF(opcao.rect).adjusted(0, 2, 0, -2)
        selecionado = bool(opcao.state & QStyle.StateFlag.State_Selected)
        sob_o_mouse = bool(opcao.state & QStyle.StateFlag.State_MouseOver)

        if selecionado:
            fundo, cor_do_texto = QColor(p["destaque"]), QColor("white")
        elif sob_o_mouse:
            fundo, cor_do_texto = QColor(p["bg_card"]), QColor(p["texto"])
        else:
            fundo, cor_do_texto = None, QColor(p["texto_secundario"])

        if fundo is not None:
            pintor.setPen(Qt.PenStyle.NoPen)
            pintor.setBrush(fundo)
            pintor.drawRoundedRect(area, 8, 8)

        lado = float(self._LADO_ICONE)
        x_icone = area.center().x() - lado / 2 if self._recolhido else area.left() + self._MARGEM_ESQUERDA
        y_icone = area.center().y() - lado / 2
        desenhar_icone(pintor, indice.data(_PAPEL_ICONE), QRectF(x_icone, y_icone, lado, lado), cor_do_texto)

        texto_selo = texto_do_selo(indice.data(_PAPEL_SELO), indice.data(_PAPEL_SELO_ERRO) or "")
        erro = bool(indice.data(_PAPEL_SELO_ERRO))

        if self._recolhido:
            if texto_selo:
                self._pintar_bolinha(pintor, area, x_icone + lado, y_icone, erro, fundo)
            return

        fonte = QFont(opcao.font)
        fonte.setWeight(QFont.Weight.DemiBold if selecionado else QFont.Weight.Normal)
        largura_do_selo = self._pintar_selo(pintor, area, texto_selo, erro, opcao.font) if texto_selo else 0.0

        x_texto = area.left() + self._MARGEM_ESQUERDA + lado + self._ESPACO_ICONE_TEXTO
        limite = area.right() - 10 - (largura_do_selo + 8 if largura_do_selo else 0)
        largura_texto = max(limite - x_texto, 0.0)
        pintor.setFont(fonte)
        pintor.setPen(cor_do_texto)
        texto = QFontMetrics(fonte).elidedText(
            indice.data(Qt.ItemDataRole.DisplayRole), Qt.TextElideMode.ElideRight, int(largura_texto)
        )
        pintor.drawText(
            QRectF(x_texto, area.top(), largura_texto, area.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            texto,
        )

    def _cores_do_selo(self, erro: bool) -> tuple[QColor, QColor, QColor]:
        """(fundo, borda, texto) do selo: ambar (as mesmas cores da etapa "Em analise", com
        contraste ja conferido) pra contagem, vermelho pro erro."""
        if erro:
            return QColor(self._paleta["erro"]), QColor(self._paleta["erro"]), QColor("white")
        return QColor(self._cores_selo["fundo"]), QColor(self._cores_selo["faixa"]), QColor(self._cores_selo["texto"])

    def _pintar_selo(self, pintor: QPainter, area: QRectF, texto: str, erro: bool, fonte_base: QFont) -> float:
        """Desenha o selo colado na direita do item e devolve a largura dele."""
        fonte = QFont(fonte_base)
        fonte.setPixelSize(11)
        fonte.setWeight(QFont.Weight.Bold)
        largura = max(float(self._ALTURA_SELO), QFontMetrics(fonte).horizontalAdvance(texto) + 12.0)
        retangulo = QRectF(area.right() - 10 - largura, area.center().y() - self._ALTURA_SELO / 2, largura, self._ALTURA_SELO)
        fundo, borda, cor_do_texto = self._cores_do_selo(erro)
        pintor.setBrush(fundo)
        pintor.setPen(QPen(borda, 1))
        pintor.drawRoundedRect(retangulo, self._ALTURA_SELO / 2, self._ALTURA_SELO / 2)
        pintor.setFont(fonte)
        pintor.setPen(cor_do_texto)
        pintor.drawText(retangulo, Qt.AlignmentFlag.AlignCenter, texto)
        return largura

    def _pintar_bolinha(self, pintor: QPainter, area: QRectF, x: float, y: float, erro: bool, fundo: QColor | None) -> None:
        """O selo, recolhido: uma bolinha no canto de cima do icone, com um anel da cor do
        fundo em volta (pra ela "recortar" o icone em vez de se misturar com ele)."""
        _, borda, _ = self._cores_do_selo(erro)
        anel = fundo if fundo is not None else QColor(self._paleta["bg_sidebar"])
        pintor.setBrush(borda)
        pintor.setPen(QPen(anel, 2))
        pintor.drawEllipse(QRectF(x - 6, y - 2, 9, 9))
