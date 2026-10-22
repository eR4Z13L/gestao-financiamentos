"""Cartao de metrica reaproveitavel (titulo pequeno + valor grande) - usado
no Dashboard e, provavelmente, em telas futuras que precisem do mesmo formato.

Abaixo do valor ha linhas opcionais: o detalhe ("R$ 927.000,00 · so 10 tem valor"), que pode ir
em destaque de aviso (ambar) quando o numero merece atencao, e a comparacao com o periodo anterior.
O cartao pode ser CLICAVEL (`tornar_clicavel`: mouse, ou Enter/Espaco com o foco) e o proprio numero pode
ficar em ambar (`definir_valor_em_aviso`).
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from desktop import settings as settings_mod
from desktop.theme import CORES_STATUS, TEMA_ESCURO
from desktop.widgets.shadow import aplicar_sombra_suave


class MetricCard(QFrame):
    clicado = Signal()  # so em um cartao clicavel (tornar_clicavel)

    def __init__(self, titulo: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("role", "card")
        self._valor_em_aviso = False
        self._clicavel = False
        aplicar_sombra_suave(self, settings_mod.obter_tema())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        legenda = QLabel(titulo)
        legenda.setProperty("role", "secundario")
        legenda.setWordWrap(True)
        layout.addWidget(legenda)
        self._legenda = legenda

        self._valor = QLabel("—")
        self._valor.setProperty("role", "valor_metrica")
        layout.addWidget(self._valor)

        # linha pequena opcional abaixo do valor (ex.: a porcentagem que
        # acompanha um numero absoluto) - so aparece se definir_detalhe() for chamado
        self._detalhe = QLabel("")
        self._detalhe.setProperty("role", "secundario")
        self._detalhe.setWordWrap(True)
        self._detalhe.setVisible(False)
        layout.addWidget(self._detalhe)

        # a diferenca contra o periodo anterior ("▲ +3 vs. os 7 dias anteriores"): so quando da pra comparar
        self._comparacao = QLabel("")
        self._comparacao.setProperty("role", "secundario")
        self._comparacao.setWordWrap(True)
        self._comparacao.setVisible(False)
        layout.addWidget(self._comparacao)

        # "Ver na tela Vendas →": so num cartao clicavel
        self._acao = QLabel("")
        self._acao.setProperty("role", "secundario")
        self._acao.setVisible(False)
        layout.addWidget(self._acao)
        layout.addStretch(1)  # cartoes lado a lado tem a mesma altura: a sobra fica embaixo e os titulos alinham

    def titulo(self) -> str:
        return self._legenda.text()

    def valor(self) -> str:
        return self._valor.text()

    def detalhe(self) -> str:
        return self._detalhe.text()

    def comparacao(self) -> str:
        return self._comparacao.text()

    def detalhe_em_aviso(self) -> bool:
        return self._detalhe.property("role") == "aviso"

    def definir_valor(self, texto: str) -> None:
        self._valor.setText(texto)

    def definir_detalhe(self, texto: str, aviso: bool = False) -> None:
        """`aviso`: o detalhe aparece em destaque (ambar, negrito) - pro que o numero sozinho esconde."""
        self._detalhe.setText(texto)
        self._detalhe.setVisible(bool(texto))
        papel = "aviso" if aviso else "secundario"
        if self._detalhe.property("role") != papel:
            self._detalhe.setProperty("role", papel)
            self._detalhe.style().unpolish(self._detalhe)  # o QSS so reavalia a propriedade depois disto
            self._detalhe.style().polish(self._detalhe)

    def definir_comparacao(self, texto: str) -> None:
        self._comparacao.setText(texto)
        self._comparacao.setVisible(bool(texto))

    # -- clicavel ---------------------------------------------------------------------------

    def tornar_clicavel(self, texto_da_acao: str) -> None:
        """O cartao vira um botao: `clicado` e emitido com o mouse ou com Enter/Espaco (com o foco)."""
        self._clicavel = True
        self._acao.setText(texto_da_acao)
        self._acao.setVisible(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAccessibleName(self._legenda.text())

    def acao(self) -> str:
        return self._acao.text()

    def eh_clicavel(self) -> bool:
        return self._clicavel

    def mouseReleaseEvent(self, evento) -> None:
        if self._clicavel and evento.button() == Qt.MouseButton.LeftButton and self.rect().contains(evento.position().toPoint()):
            self.clicado.emit()
        super().mouseReleaseEvent(evento)

    def keyPressEvent(self, evento) -> None:
        if self._clicavel and evento.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.clicado.emit()
            return
        super().keyPressEvent(evento)

    # -- numero em ambar ---------------------------------------------------------------------

    def valor_em_aviso(self) -> bool:
        return self._valor_em_aviso

    def definir_valor_em_aviso(self, aviso: bool) -> None:
        """O numero grande em ambar (a mesma cor do aviso do detalhe) quando ele pede atencao."""
        self._valor_em_aviso = aviso
        self._pintar_valor()

    def _pintar_valor(self) -> None:
        if not self._valor_em_aviso:
            self._valor.setStyleSheet("")
            return
        tema = settings_mod.obter_tema()
        cor = CORES_STATUS[tema if tema in CORES_STATUS else TEMA_ESCURO]["em_analise"]["texto"]
        self._valor.setStyleSheet(f"color: {cor};")

    def changeEvent(self, evento) -> None:
        if evento.type() == QEvent.Type.StyleChange and getattr(self, "_valor_em_aviso", False):
            self._pintar_valor()  # trocou o tema: refaz a cor ambar
        super().changeEvent(evento)
