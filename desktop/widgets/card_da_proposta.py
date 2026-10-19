"""O card de UMA proposta (um pedido a um banco): Todas as Propostas e, na Ficha, as propostas de antes das vendas.

Fechado (desenhado com o usuario em 04/10/2026): o BANCO em destaque; a etiqueta de status e as mesmas acoes rapidas
do card da venda (bolinhas Aprovado/Negado, o anel de "fechou com este banco", o "Efetivado…" de um banco fechado e
a ↩) - as mesmas pecas (ver card_da_venda.por_controles_de_status); o cliente e o equipamento; as condicoes; e ha
quanto tempo a proposta espera a resposta do banco (destacado quando parada). Faixa colorida pela cor do status.
A proposta de antes das vendas (sem venda) leva a etiqueta "sem venda", sem anel nem acoes: o status dela muda pelo
formulario.

Aberto (dois cliques, ou a setinha ⌄ do canto): cresce para baixo com o formulario da proposta (o mesmo
FormularioProposta de toda tela) e o rodape "Ver na venda →" e "Abrir a ficha". Dois cliques no topo (acima do
formulario) fecham.

O card so desenha e avisa (sinais); quem grava e o ControleDasVendas (as acoes de status) e a lista de propostas
(abrir, fechar, formulario, excluir).
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from core import propostas as propostas_mod
from core import vendas as vendas_mod
from desktop.theme import CORES_STATUS
from desktop.widgets.card_da_venda import (
    LARGURA_CARD,
    AnelDoBanco,
    _botao_link,
    _tema,
    condicoes_da_proposta,
    por_anel,
    por_controles_de_status,
)
from desktop.widgets.formulario_proposta import FormularioProposta
from desktop.widgets.lista_cartoes import chave_cor_status

_FAIXA = 5
_RAIO = 10


def texto_da_espera(dias: int | None) -> str:
    """ "esperando há 12 dias" (sem resposta do banco desde o envio, ou a ultima troca de status)."""
    if dias is None:
        return ""
    if dias <= 0:
        return "esperando desde hoje"
    return "esperando há 1 dia" if dias == 1 else f"esperando há {dias} dias"


def _pintar_faixa(widget: QFrame, chave_da_cor: str) -> None:
    """A faixa colorida da lateral, na cor da etapa (como o card da venda)."""
    cor = CORES_STATUS[_tema()][chave_da_cor]["faixa"]
    pintor = QPainter(widget)
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    contorno = QPainterPath()
    contorno.addRoundedRect(QRectF(widget.rect()).adjusted(0.5, 0.5, -0.5, -0.5), _RAIO, _RAIO)
    pintor.setClipPath(contorno)
    pintor.fillRect(QRectF(0, 0, _FAIXA, widget.height()), QColor(cor))


class CardDaProposta(QFrame):
    # os mesmos sinais de status do card da venda (o ControleDasVendas.conectar_proposta liga os dois do mesmo jeito)
    lista_da_proposta_pedida = Signal(object, object, object)  # (ResumoDaVenda, PropostaNaVenda, Pilula)
    resposta_pedida = Signal(object, object, str)
    volta_da_proposta_pedida = Signal(object, object)
    fechamento_pedido = Signal(object, object)
    fechamento_desfeito = Signal(object, object)
    efetivacao_pedida = Signal(object, object)
    # abrir/fechar: a lista decide (um aberto por vez; pergunta antes de descartar o digitado)
    abrir_pedido = Signal(object)  # PropostaNaLista
    fechar_pedido = Signal(object)
    venda_pedida = Signal(str, str)  # (ID_VENDA, ID_PROPOSTA): "Ver na venda" abre a venda com esta proposta
    ficha_pedida = Signal(str)  # cpf

    def __init__(self, item: vendas_mod.PropostaNaLista, parent: QWidget | None = None, *, aberto: bool = False,
                 com_ficha: bool = True):
        super().__init__(parent)
        self.item = item
        self.aberto = aberto
        self.formulario: FormularioProposta | None = None
        self.botao_excluir: QPushButton | None = None
        proposta, venda = item.proposta, item.venda
        self.setProperty("role", "card")
        self.setProperty("aberto", aberto)
        self.setMinimumWidth(LARGURA_CARD)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(_FAIXA + 14, 10, 12, 6)
        self._layout.setSpacing(4)

        topo = QHBoxLayout()
        topo.setSpacing(8)
        self._layout.addLayout(topo)  # ja no card: um widget num layout solto continua sem dono (e piscaria)
        self.controles: dict = {"anel": None}
        if venda is not None and proposta.id:
            self.controles["anel"] = por_anel(topo, self, venda, proposta, self)
        self.banco = QLabel(proposta.banco or "Sem banco", self)
        fonte = self.banco.font()
        fonte.setBold(True)
        fonte.setPointSizeF(fonte.pointSizeF() + 1)
        self.banco.setFont(fonte)
        self.banco.setWordWrap(True)
        topo.addWidget(self.banco, stretch=1)
        por_controles_de_status(topo, self, venda, proposta, self, self.controles)
        self.pilula = self.controles["pilula"]

        recuo = AnelDoBanco.LADO + topo.spacing() if self.controles["anel"] is not None else 0
        cliente = item.cliente or f"Cliente sem cadastro ({item.cpf})"
        detalhe = QHBoxLayout()
        detalhe.setSpacing(8)
        detalhe.addSpacing(recuo)
        self.cliente = QLabel(" · ".join(p for p in (cliente, proposta.equipamento) if p), self)
        self.cliente.setWordWrap(True)
        detalhe.addWidget(self.cliente, stretch=1)
        self.sem_venda: QLabel | None = None
        if venda is None and not proposta.id:
            self.sem_venda = QLabel("sem venda", self)
            self.sem_venda.setProperty("role", "secundario")
            self.sem_venda.setToolTip("Proposta de antes das vendas: ainda não está em nenhuma venda")
            detalhe.addWidget(self.sem_venda, alignment=Qt.AlignmentFlag.AlignTop)
        self._layout.addLayout(detalhe)

        # a ultima linha: as condicoes, ha quanto tempo espera e, fechado, o ⌄ (numa linha so: o card fica baixo)
        ultima = QHBoxLayout()
        ultima.setSpacing(8)
        ultima.addSpacing(recuo)
        condicoes = condicoes_da_proposta(proposta, venda.equipamentos if venda is not None else proposta.equipamento)
        self.condicoes = QLabel(condicoes or "sem valor informado", self)
        self.condicoes.setProperty("role", "secundario")
        self.condicoes.setWordWrap(True)
        ultima.addWidget(self.condicoes, stretch=1)
        self.espera: QLabel | None = None
        if proposta.dias_esperando is not None:
            self.espera = QLabel(texto_da_espera(proposta.dias_esperando), self)
            self.espera.setToolTip("Sem resposta do banco desde o envio (ou a última troca de status)")
            parada = proposta.dias_esperando >= propostas_mod.DIAS_PROPOSTA_PARADA
            self.espera.setProperty("role", "aviso" if parada else "secundario")
            ultima.addWidget(self.espera, alignment=Qt.AlignmentFlag.AlignTop)
        self._layout.addLayout(ultima)
        self.alternar = _botao_link("⌃ fechar" if aberto else "⌄", self, self._alternar)
        self.alternar.setToolTip("Fechar a proposta" if aberto else "Abrir a proposta (ou dois cliques no card)")
        self.alternar.setAccessibleName(self.alternar.toolTip())

        self._divisor: QFrame | None = None
        self.ver_na_venda: QPushButton | None = None
        self.abrir_ficha: QPushButton | None = None
        if not aberto:
            ultima.addWidget(self.alternar, alignment=Qt.AlignmentFlag.AlignTop)
            return
        self._divisor = QFrame(self)
        self._divisor.setFrameShape(QFrame.Shape.HLine)
        self._layout.addSpacing(4)
        self._layout.addWidget(self._divisor)  # acima dele, o "topo": dois cliques ali fecham o card
        self._posicao_do_formulario = self._layout.count()
        rodape = QHBoxLayout()
        rodape.setSpacing(18)
        self._layout.addLayout(rodape)
        if venda is not None:
            self.ver_na_venda = _botao_link("Ver na venda →", self, lambda: self.venda_pedida.emit(venda.id, proposta.id))
            self.ver_na_venda.setToolTip("Abre a venda desta proposta na tela Vendas")
            rodape.addWidget(self.ver_na_venda)
        rodape.addStretch()
        if com_ficha:
            self.abrir_ficha = _botao_link("Abrir a ficha", self, lambda: self.ficha_pedida.emit(self.item.cpf))
            rodape.addWidget(self.abrir_ficha)
        rodape.addWidget(self.alternar)

    def chave_da_cor(self) -> str:
        return chave_cor_status(self.item.proposta.status)

    def _alternar(self) -> None:
        (self.fechar_pedido if self.aberto else self.abrir_pedido).emit(self.item)

    def mouseDoubleClickEvent(self, evento) -> None:
        if not self.aberto:
            self.abrir_pedido.emit(self.item)
        elif self._divisor is not None and evento.position().y() < self._divisor.y():  # no topo: fecha, como abriu
            self.fechar_pedido.emit(self.item)
        evento.accept()

    def mostrar_formulario(self, formulario: FormularioProposta, ao_excluir: Callable[[], None] | None = None) -> None:
        """Poe o formulario embaixo do divisor (so no card aberto); `ao_excluir`: o "Excluir esta proposta…"."""
        self.formulario = formulario
        caixa = QFrame(self)
        caixa.setProperty("role", "transparente")
        corpo = QVBoxLayout(caixa)
        corpo.setContentsMargins(0, 4, 0, 8)
        formulario.setParent(caixa)
        corpo.addWidget(formulario)
        formulario.show()  # (um formulario que veio de outro card chega escondido)
        if ao_excluir is not None:
            self.botao_excluir = _botao_link("Excluir esta proposta…", caixa, ao_excluir)
            self.botao_excluir.setProperty("perigo", True)  # vermelho (ver theme.py)
            corpo.addWidget(self.botao_excluir, alignment=Qt.AlignmentFlag.AlignLeft)
        self._layout.insertWidget(self._posicao_do_formulario, caixa)

    def tem_alteracoes(self) -> bool:
        return self.formulario is not None and self.formulario.tem_alteracoes()

    def paintEvent(self, evento) -> None:
        super().paintEvent(evento)
        _pintar_faixa(self, self.chave_da_cor())


class CardNovaProposta(QFrame):
    """O card "Nova proposta" no topo da lista (o "Duplicar" do Dashboard, de uma proposta de antes das vendas): so o
    titulo e o formulario, ja em edicao. Gravar cria a venda junto (FormularioProposta)."""

    def __init__(self, nome_cliente: str, formulario: FormularioProposta, parent: QWidget | None = None):
        super().__init__(parent)
        self.formulario = formulario
        self.setProperty("role", "card")
        self.setProperty("aberto", True)
        self.setMinimumWidth(LARGURA_CARD)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(_FAIXA + 14, 10, 12, 10)
        titulo = QLabel(f"Nova proposta — {nome_cliente}" if nome_cliente else "Nova proposta", self)
        titulo.setProperty("role", "rotulo_do_cartao")
        layout.addWidget(titulo)
        formulario.setParent(self)
        layout.addWidget(formulario)
        formulario.show()  # (um formulario que veio de outro card chega escondido)

    def tem_alteracoes(self) -> bool:
        return self.formulario.tem_alteracoes()

    def paintEvent(self, evento) -> None:
        super().paintEvent(evento)
        _pintar_faixa(self, "neutro")
