"""Funil por etapa, desenhado por codigo: uma barra horizontal por etapa (a cor e a do status, a mesma
dos cards de proposta), com o rotulo, o tamanho proporcional e a quantidade. "Negado" fica separado das
demais por um filete (sair do funil nao e uma etapa dele). Clicar numa barra emite `etapa_clicada`
(so as que tem alguma proposta: uma lista vazia nao leva a lugar nenhum). O valor e "so N tem valor"
de cada etapa vao no tooltip.

Tambem responde ao teclado: Tab foca, setas movem a linha, Enter/Espaco abre.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from core import propostas as propostas_mod
from core.dashboard import EtapaDoFunil
from core.formatting import formatar_reais
from desktop.widgets.lista_cartoes import chave_cor_etapa
from desktop.widgets.paleta_do_tema import UsaPaletaDoTema

_ALTURA_DA_LINHA = 30
_FOLGA_ANTES_DO_NEGADO = 14
_LARGURA_DO_ROTULO = 118
_LARGURA_DO_NUMERO = 40
_ALTURA_DA_BARRA = 14
_ETAPAS_FORA_DO_FUNIL = (propostas_mod.ETAPA_NEGADO, propostas_mod.ETAPA_SEM_STATUS, propostas_mod.ETAPA_DESCONHECIDA)


class FunilDeEtapas(UsaPaletaDoTema, QWidget):
    etapa_clicada = Signal(str)  # a etapa (propostas.ETAPA_*)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._resolver_paleta()
        self._etapas: list[EtapaDoFunil] = []
        self._sob_o_mouse: int | None = None
        self._foco: int | None = None
        self._apertada: int | None = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    # -- dados ------------------------------------------------------------------------

    def definir_etapas(self, etapas: list[EtapaDoFunil]) -> None:
        self._etapas = list(etapas)
        self._sob_o_mouse = self._foco = self._apertada = None
        self.setFixedHeight(self._altura_total())
        self.setToolTip("")
        self.update()

    def etapas(self) -> list[EtapaDoFunil]:
        return list(self._etapas)

    # -- geometria --------------------------------------------------------------------

    def _altura_total(self) -> int:
        folga = _FOLGA_ANTES_DO_NEGADO if any(e.etapa in _ETAPAS_FORA_DO_FUNIL for e in self._etapas) else 0
        return max(len(self._etapas), 1) * _ALTURA_DA_LINHA + folga + 2

    def _linhas(self) -> list[QRectF]:
        """O retangulo de cada etapa (na ordem de `etapas`): "Negado" e o que vem depois dele descem uma folga."""
        retangulos = []
        y = 0.0
        separou = False
        for e in self._etapas:
            if e.etapa in _ETAPAS_FORA_DO_FUNIL and not separou:
                y += _FOLGA_ANTES_DO_NEGADO
                separou = True
            retangulos.append(QRectF(0, y, self.width(), _ALTURA_DA_LINHA))
            y += _ALTURA_DA_LINHA
        return retangulos

    def retangulo_da_etapa(self, etapa: str) -> QRectF:
        for e, r in zip(self._etapas, self._linhas()):
            if e.etapa == etapa:
                return r
        raise KeyError(etapa)

    def _indice_em(self, ponto: QPointF) -> int | None:
        for i, r in enumerate(self._linhas()):
            if r.contains(ponto):
                return i
        return None

    def sizeHint(self) -> QSize:
        return QSize(300, self._altura_total())

    def minimumSizeHint(self) -> QSize:
        return QSize(240, self._altura_total())

    # -- desenho ------------------------------------------------------------------------

    def cor_da_etapa(self, etapa: str) -> QColor:
        return QColor(self._cores_de_status[chave_cor_etapa(etapa)]["faixa"])

    def paintEvent(self, _evento) -> None:
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        maior = max((e.quantidade for e in self._etapas), default=0)
        linhas = self._linhas()

        primeiro_fora = next((i for i, e in enumerate(self._etapas) if e.etapa in _ETAPAS_FORA_DO_FUNIL), None)
        if primeiro_fora is not None and primeiro_fora > 0:
            y = linhas[primeiro_fora].top() - _FOLGA_ANTES_DO_NEGADO / 2
            pintor.setPen(QPen(QColor(self._paleta["borda"]), 1, Qt.PenStyle.DashLine))
            pintor.drawLine(QPointF(0, y), QPointF(self.width(), y))

        fonte_negrito = QFont(self.font())
        fonte_negrito.setWeight(QFont.Weight.DemiBold)
        for i, (e, r) in enumerate(zip(self._etapas, linhas)):
            if i in (self._sob_o_mouse, self._foco) and e.quantidade:
                fundo = QColor(self._paleta["borda"])
                fundo.setAlpha(90)
                pintor.setPen(Qt.PenStyle.NoPen)
                pintor.setBrush(fundo)
                pintor.drawRoundedRect(r.adjusted(0, 1, 0, -1), 6, 6)

            vazia = e.quantidade == 0
            cor_do_texto = QColor(self._paleta["texto_secundario" if vazia else "texto"])
            pintor.setPen(cor_do_texto)
            pintor.setFont(self.font())
            rotulo = self.fontMetrics().elidedText(e.rotulo, Qt.TextElideMode.ElideRight, _LARGURA_DO_ROTULO - 12)
            pintor.drawText(QRectF(r.left() + 6, r.top(), _LARGURA_DO_ROTULO - 8, r.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, rotulo)

            x0 = r.left() + _LARGURA_DO_ROTULO
            largura_util = max(r.right() - _LARGURA_DO_NUMERO - 8 - x0, 20.0)
            trilho = QRectF(x0, r.center().y() - _ALTURA_DA_BARRA / 2, largura_util, _ALTURA_DA_BARRA)
            cor_do_trilho = QColor(self._paleta["borda"])
            cor_do_trilho.setAlpha(80)
            pintor.setPen(Qt.PenStyle.NoPen)
            pintor.setBrush(cor_do_trilho)
            pintor.drawRoundedRect(trilho, 4, 4)
            if e.quantidade:
                largura = max(largura_util * e.quantidade / maior, 6.0)
                pintor.setBrush(self.cor_da_etapa(e.etapa))
                pintor.drawRoundedRect(QRectF(trilho.left(), trilho.top(), largura, trilho.height()), 4, 4)

            pintor.setPen(cor_do_texto)
            pintor.setFont(fonte_negrito if e.quantidade else self.font())
            pintor.drawText(QRectF(r.right() - _LARGURA_DO_NUMERO, r.top(), _LARGURA_DO_NUMERO - 4, r.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, str(e.quantidade))

            if i == self._foco and self.hasFocus():
                pintor.setPen(QPen(QColor(self._paleta["destaque"]), 1))
                pintor.setBrush(Qt.BrushStyle.NoBrush)
                pintor.drawRoundedRect(r.adjusted(0.5, 1.5, -0.5, -1.5), 6, 6)

    # -- mouse e teclado -----------------------------------------------------------------

    def _tooltip_de(self, e: EtapaDoFunil) -> str:
        n = f"{e.quantidade} proposta" + ("" if e.quantidade == 1 else "s")
        if not e.quantidade:
            return f"{e.rotulo}: nenhuma proposta"
        valor = f"{formatar_reais(e.valor)}" if e.com_valor else "nenhuma com valor"
        parcial = f" (só {e.com_valor} de {e.quantidade} têm valor)" if 0 < e.com_valor < e.quantidade else ""
        return f"{e.rotulo}: {n} · {valor}{parcial}\nClique para ver as propostas"

    def mouseMoveEvent(self, evento) -> None:
        indice = self._indice_em(evento.position())
        if indice != self._sob_o_mouse:
            self._sob_o_mouse = indice
            self.setToolTip("" if indice is None else self._tooltip_de(self._etapas[indice]))
            self.setCursor(Qt.CursorShape.PointingHandCursor if indice is not None and self._etapas[indice].quantidade else Qt.CursorShape.ArrowCursor)
            self.update()
        super().mouseMoveEvent(evento)

    def leaveEvent(self, evento) -> None:
        self._sob_o_mouse = None
        self.update()
        super().leaveEvent(evento)

    def mousePressEvent(self, evento) -> None:
        if evento.button() == Qt.MouseButton.LeftButton:
            self._apertada = self._indice_em(evento.position())
        super().mousePressEvent(evento)

    def mouseReleaseEvent(self, evento) -> None:
        indice = self._indice_em(evento.position())
        apertada, self._apertada = self._apertada, None
        if evento.button() == Qt.MouseButton.LeftButton and indice is not None and indice == apertada:
            self._abrir(indice)
        super().mouseReleaseEvent(evento)

    def _abrir(self, indice: int) -> None:
        if self._etapas[indice].quantidade:
            self.etapa_clicada.emit(self._etapas[indice].etapa)

    def focusInEvent(self, evento) -> None:
        if self._foco is None and self._etapas:
            self._foco = 0
        self.update()
        super().focusInEvent(evento)

    def focusOutEvent(self, evento) -> None:
        self.update()
        super().focusOutEvent(evento)

    def keyPressEvent(self, evento: QKeyEvent) -> None:
        tecla = evento.key()
        if tecla in (Qt.Key.Key_Down, Qt.Key.Key_Up) and self._etapas:
            passo = 1 if tecla == Qt.Key.Key_Down else -1
            self._foco = 0 if self._foco is None else max(0, min(len(self._etapas) - 1, self._foco + passo))
            self.update()
        elif tecla in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space) and self._foco is not None:
            self._abrir(self._foco)
        else:
            super().keyPressEvent(evento)
