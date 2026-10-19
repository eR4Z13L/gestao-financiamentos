"""O card da venda - a peca de toda tela que mostra vendas (Vendas, e a seguir a Ficha de Cliente e a visao por banco).

Fechado, ele serve pra VER e trocar status (desenhado com o usuario em 02 e 03/10/2026). A venda pode fechar em
varios bancos, e cada financiamento anda no seu tempo (core/vendas.py), entao quase tudo e por banco:
- a etiqueta de status: um clique abre a lista (no banco, as respostas; na venda, os desfechos manuais);
- as bolinhas ao lado do banco: avancam direto, na cor do destino - Aprovado e Negado enquanto ele nao respondeu
  (Pré-aprovado so pela lista); Efetivado num banco fechado;
- o anel verde ao lado de cada banco APROVADO: marca o banco como fechado (o cliente fechou com ele) - pode haver
  varios; o ✓ desmarca;
- a setinha ↩: volta ao status de antes da ultima troca (pelo HISTÓRICO; de novo, mais um passo); na venda, so num
  desfecho, e reabre.
A etiqueta da venda nao tem bolinha: o status dela sai dos bancos (Aguardando bancos / Em andamento / Efetivada).

Aberto (dois cliques no card, ou a setinha ⌄ do canto), ele serve pra EDITAR: cada banco ganha o ✎ (ou dois cliques
nele) que abre o formulario da proposta ali dentro, embaixo do banco - o MESMO formulario de toda tela
(FormularioProposta) -, e o rodape tem "+ Adicionar proposta", "Editar a venda" e "Abrir a ficha".

O card so desenha e avisa (sinais); quem grava e o ControleDasVendas, o mesmo pra toda tela - ele cuida dos menus,
das confirmacoes e das perguntas, e pede pra tela reler depois de gravar.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from core import data_store as bd
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import vendas as vendas_mod
from core.formatting import formatar_data, formatar_reais
from desktop import settings as settings_mod
from desktop.theme import CORES_STATUS, PALETAS
from desktop.widgets.campos_da_venda import FormularioDaVenda
from desktop.widgets.formulario_proposta import FormularioProposta
from desktop.widgets.icones_linha import icone_de_linha
from desktop.widgets.lista_cartoes import chave_cor_status
from desktop.widgets.perguntas_da_venda import perguntar_se_perdida

# o mais estreito que o card fica sem espremer as informacoes (e o formulario da proposta, aberto); a largura de
# verdade e a da coluna onde a lista o pos - mesma aberto ou fechado
LARGURA_CARD = 500
_FAIXA = 5
_RAIO = 10
NOVA = "nova"  # o que o card mostra no formulario quando e uma proposta nova (as demais: o ID_PROPOSTA)
EDITAR_VENDA = "venda"  # no formulario do card aberto: o "Editar a venda" (equipamentos e observacoes)

# as mesmas cores (ja conferidas nos dois temas) das etapas de proposta
COR_DA_VENDA = {
    vendas_mod.VENDA_AGUARDANDO: "em_analise",
    vendas_mod.VENDA_EM_ANDAMENTO: "aprovado",
    vendas_mod.VENDA_EFETIVADA: "efetivado",
    vendas_mod.VENDA_NAO_EFETIVADA: "nao_efetivado",
    vendas_mod.VENDA_PERDIDA: "negado",
}
# a resposta do banco que as bolinhas oferecem enquanto ele nao respondeu (Pré-aprovado so pela lista)
RESPOSTAS_RAPIDAS = [propostas_mod.STATUS_APROVADO, propostas_mod.STATUS_NEGADO]
ESPERANDO_RESPOSTA = {propostas_mod.ETAPA_EM_ANALISE, propostas_mod.ETAPA_PRE_APROVADO}
EFETIVAR = vendas_mod.PROPOSTA_EFETIVADA + "…"  # a bolinha de um banco fechado (pede confirmacao)


def ha_quanto(n: int | None) -> str:
    """ "hoje", "há 1 dia", "há 5 dias"."""
    return "hoje" if not n else ("há 1 dia" if n == 1 else f"há {n} dias")


def condicoes_da_proposta(proposta: vendas_mod.PropostaNaVenda, equipamentos_da_venda: str) -> str:
    """ "R$ 80.000 · 48x · 1ª em 60 dias · parcela R$ 2.150,40" (e "só X" num pedido de parte da venda)."""
    partes = []
    if proposta.valor is not None:
        partes.append(formatar_reais(proposta.valor).replace(",00", ""))
    if proposta.meses:
        partes.append(f"{proposta.meses}x")
    if proposta.carencia is not None:
        partes.append(f"1ª em {proposta.carencia} dias")
    if proposta.parcela is not None:
        partes.append(f"parcela {formatar_reais(proposta.parcela)}")
    if proposta.equipamento and proposta.equipamento.strip().upper() != equipamentos_da_venda.strip().upper():
        partes.append(f"só {proposta.equipamento}")  # pedido separado, de parte da venda
    return " · ".join(partes)


def _tema() -> str:
    return settings_mod.obter_tema()


class _ComDica(QPushButton):
    """Botao pequeno que mostra o que faz assim que o mouse passa (o tooltip comum demora quase um segundo)."""

    def __init__(self, dica: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.dica = dica
        self.setToolTip(dica)
        self.setAccessibleName(dica)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def enterEvent(self, evento) -> None:
        QToolTip.showText(self.mapToGlobal(QPoint(self.width() // 2, self.height())), self.dica, self)
        self.update()
        super().enterEvent(evento)

    def leaveEvent(self, evento) -> None:
        self.update()
        super().leaveEvent(evento)

    def _realce(self) -> bool:
        return self.underMouse() or self.hasFocus()


class Pilula(_ComDica):
    """A etiqueta de status, nas cores da etapa: um clique abre a lista para escolher o status. `clicavel=False`: so
    mostra o status (sem a setinha; quem mostra nao liga o clique)."""

    def __init__(self, texto: str, cor: str, parent: QWidget | None = None, *, clicavel: bool = True):
        super().__init__(f"{texto}: clique para escolher o status" if clicavel else texto, parent)
        self.cor = cor
        self.clicavel = clicavel
        self.setText(texto)
        if not clicavel:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def _realce(self) -> bool:
        return self.clicavel and super()._realce()

    def _rotulo(self) -> str:
        return f"{self.text()}  ▾" if self.clicavel else self.text()

    def sizeHint(self) -> QSize:
        metricas = QFontMetrics(self.font())
        return QSize(metricas.horizontalAdvance(self._rotulo()) + 22, metricas.height() + 8)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, _evento) -> None:
        cor = CORES_STATUS[_tema()][self.cor]
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        caixa = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        raio = caixa.height() / 2
        pintor.setPen(QPen(QColor(cor["faixa"]), 1))
        pintor.setBrush(QColor(cor["fundo"]))
        pintor.drawRoundedRect(caixa, raio, raio)
        if self._realce():  # foco do teclado visivel (e o "estou clicavel" do mouse)
            pintor.setPen(QPen(QColor(PALETAS[_tema()]["destaque"]), 2))
            pintor.setBrush(Qt.BrushStyle.NoBrush)
            pintor.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), raio + 0.5, raio + 0.5)
        pintor.setPen(QColor(cor["texto"]))
        pintor.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._rotulo())


class Bolinha(_ComDica):
    """Avanca direto para `destino`, na cor dele."""

    LADO = 17

    def __init__(self, destino: str, cor: str, parent: QWidget | None = None):
        super().__init__(f"→ {destino}", parent)
        self.destino = destino
        self.cor = cor
        self.setFixedSize(self.LADO, self.LADO)

    def paintEvent(self, _evento) -> None:
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        raio = 6.5 if self._realce() else 5.5
        if self.hasFocus():
            pintor.setPen(QPen(QColor(PALETAS[_tema()]["destaque"]), 1.5))
        else:
            pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(QColor(CORES_STATUS[_tema()][self.cor]["faixa"]))
        pintor.drawEllipse(QRectF(self.rect()).center(), raio, raio)


class AnelDoBanco(_ComDica):
    """Ao lado de um banco aprovado: anel vazio = marcar como fechado; ✓ cheio = fechado (o cliente fechou com ele)."""

    LADO = 20

    def __init__(self, fechado: bool, dica: str, parent: QWidget | None = None):
        super().__init__(dica, parent)
        self.fechado = fechado
        self.setFixedSize(self.LADO, self.LADO)

    def paintEvent(self, _evento) -> None:
        verde = QColor(CORES_STATUS[_tema()]["aprovado"]["faixa"])
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        centro = QRectF(self.rect()).center()
        if self.fechado:
            pintor.setPen(Qt.PenStyle.NoPen)
            pintor.setBrush(verde)
            pintor.drawEllipse(centro, 8.5, 8.5)
            pintor.setPen(QPen(QColor("#ffffff"), 2))
            pintor.drawPolyline([centro + QPointF(-4, 0), centro + QPointF(-1, 3), centro + QPointF(4, -3)])
        else:
            raio = 7 if self._realce() else 6
            pintor.setPen(QPen(verde, 2))
            pintor.setBrush(Qt.BrushStyle.NoBrush)
            pintor.drawEllipse(centro, raio, raio)


class BotaoVoltar(_ComDica):
    """A setinha ↩: volta ao status de antes da ultima troca."""

    def __init__(self, anterior: str, parent: QWidget | None = None):
        super().__init__(f"↩ Voltar para {anterior}", parent)
        self.anterior = anterior
        self.setFixedSize(22, 22)

    def paintEvent(self, _evento) -> None:
        paleta = PALETAS[_tema()]
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._realce():
            pintor.setPen(Qt.PenStyle.NoPen)
            pintor.setBrush(QColor(paleta["borda"]))
            pintor.drawRoundedRect(QRectF(self.rect()), 5, 5)
        # uma seta curva para tras (desenhada: o simbolo "↩" nao existe em toda fonte), num quadrado de 22 px
        pintor.setPen(QPen(QColor(paleta["texto"] if self._realce() else paleta["texto_secundario"]), 1.6,
                           Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        pintor.setBrush(Qt.BrushStyle.NoBrush)
        curva = QPainterPath(QPointF(7, 8))
        curva.lineTo(13, 8)
        curva.cubicTo(18, 8, 18, 16, 13, 16)
        curva.lineTo(9, 16)
        pintor.drawPath(curva)
        pintor.drawPolyline([QPointF(10, 5), QPointF(7, 8), QPointF(10, 11)])


class _BotaoIcone(_ComDica):
    """O ✎ de cada banco no card aberto (o lapis desenhado, na cor do tema)."""

    def __init__(self, icone: str, dica: str, parent: QWidget | None = None):
        super().__init__(dica, parent)
        self.setProperty("role", "botao_icone")
        self.setIcon(icone_de_linha(icone, QColor(PALETAS[_tema()]["texto_secundario"]), 16))
        self.setIconSize(QSize(16, 16))
        self.setFixedSize(26, 24)


class _LinhaDoBanco(QWidget):
    """Um banco no card: em cima o banco, o status e os controles; embaixo, alinhadas ao nome do banco, as condicoes
    (numa linha so elas nao cabiam no card). Dois cliques nela pedem o formulario desta proposta."""

    duplo_clique = Signal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setProperty("role", "transparente")

    def mouseDoubleClickEvent(self, evento) -> None:
        self.duplo_clique.emit()
        evento.accept()


def _botao_link(texto: str, parent: QWidget, ao_clicar) -> QPushButton:
    botao = QPushButton(texto, parent)
    botao.setProperty("role", "botao_link")
    botao.setCursor(Qt.CursorShape.PointingHandCursor)
    botao.clicked.connect(ao_clicar)
    return botao


# -- os controles de status de uma proposta: os mesmos no card da venda (cada banco) e no card da proposta -------------
# Os cliques saem pelos sinais de `card` (os dois cards tem os mesmos: fechamento_pedido, fechamento_desfeito,
# volta_da_proposta_pedida, lista_da_proposta_pedida, resposta_pedida, efetivacao_pedida), sempre com (venda, proposta).

def por_anel(linha: QHBoxLayout, card, venda: vendas_mod.ResumoDaVenda, proposta: vendas_mod.PropostaNaVenda,
             parent: QWidget) -> AnelDoBanco | None:
    """O anel ao lado de um banco aprovado (marcar como fechado) ou o ✓ de um fechado. Sem anel, o lugar dele fica
    vazio do mesmo tamanho: os nomes dos bancos ficam alinhados."""
    aprovada = propostas_mod.etapa_status(proposta.status) == propostas_mod.ETAPA_APROVADO
    aberta = venda.status not in vendas_mod.DESFECHOS_DA_VENDA
    anel = None
    if proposta.fechada:
        desmarcavel = aberta and proposta.status != vendas_mod.PROPOSTA_EFETIVADA
        anel = AnelDoBanco(True, "Fechado (clique para desmarcar)" if desmarcavel else "Fechado", parent)
        if desmarcavel:
            anel.clicked.connect(lambda: card.fechamento_desfeito.emit(venda, proposta))
    elif aprovada and aberta:
        anel = AnelDoBanco(False, "Marcar como fechado (o cliente fechou com este banco)", parent)
        anel.clicked.connect(lambda: card.fechamento_pedido.emit(venda, proposta))
    if anel is None:
        linha.addSpacing(AnelDoBanco.LADO)
    else:
        linha.addWidget(anel)
    return anel


def por_controles_de_status(linha: QHBoxLayout, card, venda: vendas_mod.ResumoDaVenda | None,
                            proposta: vendas_mod.PropostaNaVenda, parent: QWidget, itens: dict) -> None:
    """A ↩, a etiqueta e as bolinhas de uma proposta, nessa ordem, em `linha`; os widgets vao para `itens` ("voltar",
    "pilula", "bolinhas"). Sem `venda` (ou sem ID_PROPOSTA: as de antes das vendas, ou o VENDEDOR), so a etiqueta,
    que so mostra - o status dessas muda pelo formulario (decidido em 05/10/2026)."""
    acoes = venda is not None and bool(proposta.id)
    itens.setdefault("voltar", None)
    itens.setdefault("bolinhas", [])
    if acoes and proposta.anterior:
        voltar = BotaoVoltar(proposta.anterior, parent)
        voltar.clicked.connect(lambda: card.volta_da_proposta_pedida.emit(venda, proposta))
        linha.addWidget(voltar)
        itens["voltar"] = voltar
    pilula = Pilula(proposta.status or "Sem status", chave_cor_status(proposta.status), parent, clicavel=acoes)
    if acoes:
        pilula.clicked.connect(lambda: card.lista_da_proposta_pedida.emit(venda, proposta, pilula))
    linha.addWidget(pilula)
    itens["pilula"] = pilula
    # as bolinhas tem lugar fixo (mesmo sem nenhuma): as etiquetas ficam alinhadas entre os bancos
    caixa = QHBoxLayout()
    caixa.setSpacing(2)
    if acoes and propostas_mod.etapa_status(proposta.status) in ESPERANDO_RESPOSTA:
        for destino in RESPOSTAS_RAPIDAS:
            bolinha = Bolinha(destino, chave_cor_status(destino), parent)
            bolinha.clicked.connect(lambda _=False, d=destino: card.resposta_pedida.emit(venda, proposta, d))
            caixa.addWidget(bolinha)
            itens["bolinhas"].append(bolinha)
    elif (acoes and proposta.fechada and venda.status not in vendas_mod.DESFECHOS_DA_VENDA
          and propostas_mod.etapa_status(proposta.status) == propostas_mod.ETAPA_APROVADO):
        bolinha = Bolinha(EFETIVAR, chave_cor_status(vendas_mod.PROPOSTA_EFETIVADA), parent)
        bolinha.clicked.connect(lambda: card.efetivacao_pedida.emit(venda, proposta))
        caixa.addWidget(bolinha)
        itens["bolinhas"].append(bolinha)
    caixa.addSpacing((len(RESPOSTAS_RAPIDAS) - len(itens["bolinhas"])) * (Bolinha.LADO + caixa.spacing()))
    linha.addLayout(caixa)


class CardDaVenda(QFrame):
    # cada pedido leva a venda (e a proposta, quando e da linha de um banco); quem grava e o ControleDasVendas
    lista_da_venda_pedida = Signal(object, object)  # (ResumoDaVenda, Pilula)
    volta_da_venda_pedida = Signal(object)  # so num desfecho: reabrir
    lista_da_proposta_pedida = Signal(object, object, object)  # (ResumoDaVenda, PropostaNaVenda, Pilula)
    resposta_pedida = Signal(object, object, str)  # (ResumoDaVenda, PropostaNaVenda, status)
    volta_da_proposta_pedida = Signal(object, object)
    fechamento_pedido = Signal(object, object)  # (ResumoDaVenda, PropostaNaVenda): o anel de um banco aprovado
    fechamento_desfeito = Signal(object, object)  # o ✓ de um banco fechado
    efetivacao_pedida = Signal(object, object)  # a bolinha de um banco fechado
    # abrir/fechar e editar: a tela decide (um card aberto por vez; pergunta antes de descartar o digitado)
    abrir_pedido = Signal(object)  # ResumoDaVenda
    fechar_pedido = Signal(object)
    proposta_pedida = Signal(object, object)  # (ResumoDaVenda, PropostaNaVenda ou None = nova)
    exclusao_pedida = Signal(object, object)  # (ResumoDaVenda, PropostaNaVenda)
    edicao_da_venda_pedida = Signal(object)
    ficha_pedida = Signal(str)  # cpf

    def __init__(self, venda: vendas_mod.ResumoDaVenda, parent: QWidget | None = None, *, aberto: bool = False):
        super().__init__(parent)
        self.venda = venda
        self.aberto = aberto
        self.formulario: FormularioProposta | FormularioDaVenda | None = None
        self.editando: str | None = None  # o ID_PROPOSTA no formulario, NOVA, EDITAR_VENDA ou None
        self.caixa_do_formulario: QFrame | None = None
        self.botao_excluir: QPushButton | None = None
        self.setProperty("role", "card")
        self.setProperty("aberto", aberto)
        self.setMinimumWidth(LARGURA_CARD)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(_FAIXA + 14, 10, 12, 6)
        self._layout.setSpacing(4)

        topo = QHBoxLayout()
        topo.setSpacing(4)
        self._layout.addLayout(topo)  # ja no card: um widget num layout solto continua sem dono (e piscaria)
        cliente = QLabel(venda.cliente or f"Cliente sem cadastro ({venda.cpf})", self)
        fonte = cliente.font()
        fonte.setBold(True)
        fonte.setPointSizeF(fonte.pointSizeF() + 1)
        cliente.setFont(fonte)
        cliente.setWordWrap(True)
        topo.addWidget(cliente, stretch=1)
        self.voltar: BotaoVoltar | None = None
        if venda.anterior:  # so num desfecho (reabrir) ou Pendente de entrega (voltar a Efetivada)
            self.voltar = BotaoVoltar(venda.anterior, self)
            self.voltar.clicked.connect(lambda: self.volta_da_venda_pedida.emit(self.venda))
            topo.addWidget(self.voltar, alignment=Qt.AlignmentFlag.AlignTop)
        self.pilula = Pilula(venda.status or "Sem status", COR_DA_VENDA.get(venda.status, "neutro"), self)
        self.pilula.clicked.connect(lambda: self.lista_da_venda_pedida.emit(self.venda, self.pilula))
        topo.addWidget(self.pilula, alignment=Qt.AlignmentFlag.AlignTop)
        self.bolinha = None  # a venda nao tem etapas proprias: quem avanca sao os bancos

        detalhe = QLabel(" · ".join(p for p in (venda.equipamentos, venda.vendedor) if p) or "—", self)
        detalhe.setProperty("role", "secundario")
        detalhe.setWordWrap(True)
        self._layout.addWidget(detalhe)

        self.andamento = QLabel(self._texto_andamento(), self)
        self.andamento.setProperty("role", "aviso" if venda.parada else "secundario")
        self.andamento.setWordWrap(True)
        self._layout.addWidget(self.andamento)
        aprovadas = len(venda.aprovadas())
        self.convite: QLabel | None = None
        if venda.status == vendas_mod.VENDA_AGUARDANDO and aprovadas:
            self.convite = QLabel(
                f"{aprovadas} banco{'s' if aprovadas > 1 else ''} aprov{'aram' if aprovadas > 1 else 'ou'}: "
                "marque no anel os que fecharam", self)
            self.convite.setProperty("role", "positivo")
            self._layout.addWidget(self.convite)
        if venda.motivo:
            motivo = QLabel(f"Motivo: {venda.motivo}", self)
            motivo.setProperty("role", "secundario")
            self._layout.addWidget(motivo)
        if aberto and venda.observacoes:
            observacoes = QLabel(f"Observações: {venda.observacoes}", self)
            observacoes.setProperty("role", "secundario")
            observacoes.setWordWrap(True)
            self._layout.addWidget(observacoes)

        divisor = QFrame(self)
        divisor.setFrameShape(QFrame.Shape.HLine)
        self._layout.addSpacing(4)
        self._layout.addWidget(divisor)
        self._divisor = divisor  # acima dele, o "topo" do card: dois cliques ali fecham o card aberto

        self.linhas_de_banco: list[dict] = []  # por banco: proposta, widget, pilula, bolinhas, anel, voltar, lapis
        self.adicionar_vazio: QPushButton | None = None
        if not venda.propostas:
            vazio = QHBoxLayout()
            self._layout.addLayout(vazio)
            texto = QLabel("Nenhuma proposta ainda.", self)
            texto.setProperty("role", "secundario")
            vazio.addWidget(texto)
            if not aberto and venda.status not in vendas_mod.DESFECHOS_DA_VENDA:
                self.adicionar_vazio = _botao_link("+ Adicionar proposta", self,
                                                   lambda: self.proposta_pedida.emit(self.venda, None))
                vazio.addWidget(self.adicionar_vazio)
            vazio.addStretch()
        for proposta in venda.propostas:
            self._layout.addWidget(self._linha_do_banco(proposta))

        self.adicionar: QPushButton | None = None
        self.editar_venda: QPushButton | None = None
        self.abrir_ficha: QPushButton | None = None
        if aberto:
            divisor2 = QFrame(self)
            divisor2.setFrameShape(QFrame.Shape.HLine)
            self._layout.addWidget(divisor2)
            rodape = QHBoxLayout()
            rodape.setSpacing(18)
            self._layout.addLayout(rodape)
            if venda.status not in vendas_mod.DESFECHOS_DA_VENDA:  # uma Efetivada ainda aceita outro pedido
                self.adicionar = _botao_link("+ Adicionar proposta", self, lambda: self.proposta_pedida.emit(self.venda, None))
                rodape.addWidget(self.adicionar)
            self.editar_venda = _botao_link("Editar a venda", self, lambda: self.edicao_da_venda_pedida.emit(self.venda))
            self.editar_venda.setToolTip("Equipamentos e observações da venda")
            rodape.addWidget(self.editar_venda)
            rodape.addStretch()
            self.abrir_ficha = _botao_link("Abrir a ficha", self, lambda: self.ficha_pedida.emit(self.venda.cpf))
            rodape.addWidget(self.abrir_ficha)
        canto = QHBoxLayout()
        canto.addStretch()
        self.alternar = _botao_link("⌃ fechar" if aberto else "⌄", self, self._alternar)
        self.alternar.setToolTip("Fechar a venda" if aberto else "Abrir a venda para editar (ou dois cliques no card)")
        self.alternar.setAccessibleName(self.alternar.toolTip())
        canto.addWidget(self.alternar)
        self._layout.addLayout(canto)

    def _alternar(self) -> None:
        (self.fechar_pedido if self.aberto else self.abrir_pedido).emit(self.venda)

    def mouseDoubleClickEvent(self, evento) -> None:
        if not self.aberto:
            self.abrir_pedido.emit(self.venda)
        elif evento.position().y() < self._divisor.y():  # no topo (cliente, status, andamento): fecha, como abriu
            self.fechar_pedido.emit(self.venda)
        evento.accept()

    def _texto_andamento(self) -> str:
        v = self.venda
        partes = [f"desde {formatar_data(v.data_criacao)}"] if v.data_criacao is not None else []
        if v.dias_na_etapa is not None and not v.finalizada:
            quanto = ha_quanto(v.dias_na_etapa)
            partes.append(f"{'parada ' + quanto if v.parada else quanto} em \"{v.status}\"")
        fechados = v.bancos_fechados()
        if fechados and v.status not in vendas_mod.DESFECHOS_DA_VENDA:
            partes.append(f"{len(v.efetivados())} de {len(fechados)} banco{'s' if len(fechados) > 1 else ''} "
                          f"efetivado{'s' if len(fechados) > 1 else ''}")
        return " · ".join(partes) or "sem data"

    def _linha_do_banco(self, proposta: vendas_mod.PropostaNaVenda) -> QWidget:
        widget = _LinhaDoBanco(self)
        widget.duplo_clique.connect(lambda: self.proposta_pedida.emit(self.venda, proposta))
        bloco = QVBoxLayout(widget)
        bloco.setContentsMargins(0, 2, 0, 2)
        bloco.setSpacing(0)
        linha = QHBoxLayout()
        linha.setSpacing(8)
        bloco.addLayout(linha)
        itens = {"proposta": proposta, "widget": widget, "voltar": None, "bolinhas": [], "lapis": None}
        itens["anel"] = por_anel(linha, self, self.venda, proposta, widget)

        banco = QLabel(proposta.banco or "Sem banco", widget)
        fonte = banco.font()
        fonte.setWeight(QFont.Weight.DemiBold)
        banco.setFont(fonte)
        linha.addWidget(banco)
        linha.addStretch(1)
        valores = QLabel(condicoes_da_proposta(proposta, self.venda.equipamentos), widget)
        valores.setProperty("role", "secundario")
        valores.setWordWrap(True)
        condicoes = QHBoxLayout()
        condicoes.addSpacing(AnelDoBanco.LADO + linha.spacing())
        condicoes.addWidget(valores, stretch=1)
        bloco.addLayout(condicoes)
        if proposta.dias_esperando is not None:
            espera = QLabel(ha_quanto(proposta.dias_esperando), widget)
            espera.setToolTip("Sem resposta do banco desde o envio (ou a última troca de status)")
            espera.setProperty("role", "aviso" if proposta.dias_esperando >= propostas_mod.DIAS_PROPOSTA_PARADA else "secundario")
            linha.addWidget(espera)

        por_controles_de_status(linha, self, self.venda, proposta, widget, itens)
        if self.aberto:
            lapis = _BotaoIcone("lapis", f"Editar a proposta do {proposta.banco or 'banco'}", widget)
            lapis.clicked.connect(lambda: self.proposta_pedida.emit(self.venda, proposta))
            linha.addWidget(lapis)
            itens["lapis"] = lapis
        itens["condicoes"] = valores
        self.linhas_de_banco.append(itens)
        return widget

    def mostrar_formulario(self, editando: str, formulario: FormularioProposta | FormularioDaVenda,
                           ao_excluir: Callable[[], None] | None = None) -> None:
        """Poe o formulario embaixo do banco que esta sendo editado (ou, numa proposta nova, depois do ultimo banco)."""
        self.editando = editando
        self.formulario = formulario
        caixa = QFrame(self)
        caixa.setProperty("role", "transparente")
        corpo = QVBoxLayout(caixa)
        corpo.setContentsMargins(AnelDoBanco.LADO + 8, 4, 0, 8)
        if editando in (NOVA, EDITAR_VENDA):
            titulo = QLabel("Nova proposta" if editando == NOVA else "Editar a venda", caixa)
            titulo.setProperty("role", "rotulo_do_cartao")
            corpo.addWidget(titulo)
        formulario.setParent(caixa)
        corpo.addWidget(formulario)
        formulario.show()  # (um formulario guardado de outra montagem chega escondido)
        if ao_excluir is not None:
            excluir = _botao_link("Excluir esta proposta…", caixa, ao_excluir)
            excluir.setProperty("perigo", True)  # vermelho (ver theme.py)
            corpo.addWidget(excluir, alignment=Qt.AlignmentFlag.AlignLeft)
            self.botao_excluir = excluir
        if editando == EDITAR_VENDA:  # logo abaixo do que se edita (equipamentos e observacoes), antes dos bancos
            corpo.setContentsMargins(0, 4, 0, 8)
            self._layout.insertWidget(self._layout.indexOf(self._divisor), caixa)
            self.caixa_do_formulario = caixa
            if self.editar_venda is not None:
                self.editar_venda.hide()
            return
        posicao = None
        for itens in self.linhas_de_banco:
            if itens["proposta"].id == editando:
                posicao = self._layout.indexOf(itens["widget"]) + 1
        if posicao is None:  # proposta nova: depois do ultimo banco (ou do "Nenhuma proposta ainda")
            ultimo = self.linhas_de_banco[-1]["widget"] if self.linhas_de_banco else None
            posicao = self._layout.indexOf(ultimo) + 1 if ultimo is not None else self._layout.count() - 2
        self._layout.insertWidget(posicao, caixa)
        self.caixa_do_formulario = caixa

    def tem_alteracoes(self) -> bool:
        return self.formulario is not None and self.formulario.tem_alteracoes()

    def paintEvent(self, evento) -> None:
        super().paintEvent(evento)
        _pintar_faixa(self, COR_DA_VENDA.get(self.venda.status, "neutro"))


def _pintar_faixa(card: QFrame, chave_da_cor: str) -> None:
    """A faixa colorida da lateral, na cor da etapa da venda (como os cards de Todas as Propostas)."""
    cor = CORES_STATUS[_tema()][chave_da_cor]["faixa"]
    pintor = QPainter(card)
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    contorno = QPainterPath()
    contorno.addRoundedRect(QRectF(card.rect()).adjusted(0.5, 0.5, -0.5, -0.5), _RAIO, _RAIO)
    pintor.setClipPath(contorno)
    pintor.fillRect(QRectF(0, 0, _FAIXA, card.height()), QColor(cor))


class CardNovaVenda(QFrame):
    """O card "Nova venda" no topo da lista de vendas (sem janela, decidido com o usuario em 05/10/2026): cliente,
    equipamentos e observacoes, com "Criar venda" e "Cancelar". Criada, a lista mostra no lugar dele o card da venda,
    aberto, com o formulario do primeiro banco."""

    aberto = False  # (nao e o card de uma venda: a lista o trata a parte)

    def __init__(self, formulario: FormularioDaVenda, parent: QWidget | None = None):
        super().__init__(parent)
        self.formulario = formulario
        self.setProperty("role", "card")
        self.setProperty("aberto", True)
        self.setMinimumWidth(LARGURA_CARD)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(_FAIXA + 14, 10, 12, 10)
        titulo = QLabel("Nova venda", self)
        titulo.setProperty("role", "rotulo_do_cartao")
        layout.addWidget(titulo)
        formulario.setParent(self)
        layout.addWidget(formulario)
        formulario.show()  # (um formulario guardado de outra montagem chega escondido)

    def tem_alteracoes(self) -> bool:
        return self.formulario.tem_alteracoes()

    def paintEvent(self, evento) -> None:
        super().paintEvent(evento)
        _pintar_faixa(self, "neutro")


class DesfechoDialog(QDialog):
    """Confirma Não efetivada / Perdida, com o motivo (opcional) da lista curta."""

    def __init__(self, venda: vendas_mod.ResumoDaVenda, status: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Marcar como {status}")
        layout = QVBoxLayout(self)
        texto = QLabel(f"Marcar a venda de <b>{venda.cliente or venda.cpf}</b> ({venda.equipamentos}) como "
                       f"<b>{status}</b>?")
        texto.setWordWrap(True)
        layout.addWidget(texto)
        layout.addWidget(QLabel("Motivo (opcional)"))
        self.motivo = QComboBox()
        self.motivo.addItem("Sem motivo", "")
        for motivo in vendas_mod.MOTIVOS_DE_PERDA:
            self.motivo.addItem(motivo, motivo)
        if venda.motivo in vendas_mod.MOTIVOS_DE_PERDA:
            self.motivo.setCurrentIndex(self.motivo.findData(venda.motivo))
        layout.addWidget(self.motivo)
        botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botoes.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        botoes.button(QDialogButtonBox.StandardButton.Ok).setText(f"Marcar como {status}")
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)
        layout.addWidget(botoes)


class ControleDasVendas(QObject):
    """As acoes dos cards de venda, iguais em toda tela que os mostra: menus de status, bolinhas, anel, voltar,
    confirmacoes e as perguntas. Grava pelo core e chama `ao_gravar(aviso)` (a tela rele e mostra o aviso)."""

    def __init__(self, tela: QWidget, ao_gravar: Callable[[str], None]):
        super().__init__(tela)
        self._tela = tela
        self._ao_gravar = ao_gravar

    def conectar(self, card: CardDaVenda) -> None:
        card.lista_da_venda_pedida.connect(self._lista_da_venda)
        card.volta_da_venda_pedida.connect(self.voltar_venda)
        self.conectar_proposta(card)

    def conectar_proposta(self, card) -> None:
        """So os controles de status de uma proposta (o card da proposta tambem os tem; ver por_controles_de_status)."""
        card.lista_da_proposta_pedida.connect(self._lista_da_proposta)
        card.resposta_pedida.connect(self.mudar_proposta)
        card.volta_da_proposta_pedida.connect(self.voltar_proposta)
        card.fechamento_pedido.connect(self.fechar_banco)
        card.fechamento_desfeito.connect(self.desmarcar_banco)
        card.efetivacao_pedida.connect(self.efetivar_banco)

    # -- gravar -------------------------------------------------------------------------------------

    def executar(self, titulo_erro: str, acao):
        """Roda a acao do core mostrando o erro (nunca em silencio). Devolve (True, resultado) ou (False, None)."""
        try:
            return True, acao()
        except (vendas_mod.ErroVenda, propostas_mod.ErroProposta) as exc:
            QMessageBox.warning(self._tela, titulo_erro, str(exc))
        except sessao_mod.PermissaoNegada as exc:
            QMessageBox.warning(self._tela, "Ação não permitida", str(exc))
        except bd.ErroArquivoBloqueado as exc:
            QMessageBox.critical(self._tela, "Arquivo bloqueado", str(exc))
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self._tela, f"Erro inesperado: {titulo_erro.lower()}", f"{type(exc).__name__}: {exc}")
        return False, None

    def _gravar(self, titulo_erro: str, acao, aviso) -> bool:
        ok, resultado = self.executar(titulo_erro, acao)
        if ok:
            self._ao_gravar(aviso(resultado) if callable(aviso) else aviso)
        return ok

    @staticmethod
    def nome(venda: vendas_mod.ResumoDaVenda) -> str:
        return venda.cliente or venda.cpf

    # -- venda --------------------------------------------------------------------------------------

    def montar_menu_da_venda(self, venda: vendas_mod.ResumoDaVenda) -> QMenu:
        """A lista da etiqueta da venda: so os desfechos manuais (o resto do status vem dos bancos) e, num desfecho,
        "Reabrir"."""
        menu = QMenu(self._tela)
        pendente = venda.status == vendas_mod.VENDA_PENDENTE_ENTREGA
        if venda.status in vendas_mod.DESFECHOS_DA_VENDA:
            menu.addAction(f"Reabrir a venda (volta para \"{venda.anterior}\")", lambda: self.voltar_venda(venda))
        elif pendente:
            menu.addAction(f"Voltar a venda (volta para \"{venda.anterior}\")", lambda: self.voltar_venda(venda))
        menu.addSection("Desfechos")
        for status in vendas_mod.DESFECHOS_DA_VENDA:
            acao = menu.addAction(f"{status}…", lambda s=status: self.escolher_status_da_venda(venda, s))
            acao.setCheckable(True)
            acao.setChecked(status == venda.status)
            acao.setEnabled(not pendente)  # o core tambem recusa: marque como entregue antes
        aviso = menu.addAction("O resto vem dos bancos: o anel e o Efetivado de cada um")
        aviso.setEnabled(False)
        return menu

    def _lista_da_venda(self, venda: vendas_mod.ResumoDaVenda, pilula: Pilula) -> None:
        self.montar_menu_da_venda(venda).exec(pilula.mapToGlobal(pilula.rect().bottomLeft()))

    def escolher_status_da_venda(self, venda: vendas_mod.ResumoDaVenda, status: str) -> bool:
        if status == venda.status or status not in vendas_mod.DESFECHOS_DA_VENDA:
            return False
        return self._desfecho(venda, status)

    def voltar_venda(self, venda: vendas_mod.ResumoDaVenda) -> bool:
        """O ↩ da venda (num desfecho ou Pendente de entrega): reabrir / voltar - nunca por um clique sem querer.
        vendas_mod.voltar_venda decide: o desfecho reabre; o Pendente de entrega volta a Efetivada."""
        pendente = venda.status == vendas_mod.VENDA_PENDENTE_ENTREGA
        titulo, acao = ("Voltar a venda", "Voltar") if pendente else ("Reabrir a venda", "Reabrir")
        resposta = QMessageBox.question(
            self._tela, titulo,
            f"A venda de {self.nome(venda)} está \"{venda.status}\". {acao} (volta para \"{venda.anterior}\")?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if resposta != QMessageBox.StandardButton.Yes:
            return False
        return self._gravar(f"Não foi possível {acao.lower()}", lambda: vendas_mod.voltar_venda(venda.id),
                            lambda para: f"{self.nome(venda)}: {'voltou a' if pendente else 'reaberta'} (\"{para}\").")

    def fechar_banco(self, venda: vendas_mod.ResumoDaVenda, proposta: vendas_mod.PropostaNaVenda) -> bool:
        return self._gravar("Não foi possível marcar como fechado", lambda: vendas_mod.fechar_proposta(proposta.id),
                            f"{self.nome(venda)}: {proposta.banco} marcado como fechado.")

    def desmarcar_banco(self, venda: vendas_mod.ResumoDaVenda, proposta: vendas_mod.PropostaNaVenda) -> bool:
        return self._gravar("Não foi possível desmarcar", lambda: vendas_mod.desfazer_fechamento(proposta.id),
                            f"{self.nome(venda)}: {proposta.banco} desmarcado.")

    def efetivar_banco(self, venda: vendas_mod.ResumoDaVenda, proposta: vendas_mod.PropostaNaVenda) -> bool:
        resposta = QMessageBox.question(
            self._tela, "Efetivar",
            f"O financiamento do {proposta.banco} para {self.nome(venda)} saiu? Marcar como Efetivado.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if resposta != QMessageBox.StandardButton.Yes:
            return False

        def _aviso(status_da_venda: str) -> str:
            final = " A venda está Efetivada." if status_da_venda == vendas_mod.VENDA_EFETIVADA else ""
            return f"{self.nome(venda)}: {proposta.banco} Efetivado.{final}"

        return self._gravar("Não foi possível efetivar", lambda: vendas_mod.efetivar_proposta(proposta.id), _aviso)

    def _desfecho(self, venda: vendas_mod.ResumoDaVenda, status: str) -> bool:
        dialogo = DesfechoDialog(venda, status, self._tela)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return False
        motivo = dialogo.motivo.currentData() or ""
        return self._gravar(f"Não foi possível marcar como {status}",
                            lambda: vendas_mod.mudar_status_venda(venda.id, status, motivo=motivo),
                            f"{self.nome(venda)}: {status}.")

    # -- proposta (a resposta de cada banco) ----------------------------------------------------------

    def montar_menu_da_proposta(self, venda: vendas_mod.ResumoDaVenda, proposta: vendas_mod.PropostaNaVenda) -> QMenu:
        menu = QMenu(self._tela)
        menu.addSection(f"Resposta do {proposta.banco or 'banco'}")
        for status in vendas_mod.STATUS_DA_PROPOSTA:
            acao = menu.addAction(status, lambda s=status: self.mudar_proposta(venda, proposta, s))
            acao.setCheckable(True)
            acao.setChecked(status == proposta.status)
            if proposta.fechada and status not in vendas_mod.STATUS_DE_FECHADA:
                acao.setEnabled(False)  # o core tambem recusa: a venda contaria com um banco que nao aprovou
        if proposta.fechada:
            efetivado = menu.addAction(vendas_mod.PROPOSTA_EFETIVADA + "…", lambda: self.efetivar_banco(venda, proposta))
            efetivado.setCheckable(True)
            efetivado.setChecked(proposta.status == vendas_mod.PROPOSTA_EFETIVADA)
            efetivado.setEnabled(proposta.status != vendas_mod.PROPOSTA_EFETIVADA)
            aviso = menu.addAction("Banco fechado: desmarque o anel para mudar a resposta")
            aviso.setEnabled(False)
        return menu

    def _lista_da_proposta(self, venda, proposta, pilula: Pilula) -> None:
        self.montar_menu_da_proposta(venda, proposta).exec(pilula.mapToGlobal(pilula.rect().bottomLeft()))

    def mudar_proposta(self, venda: vendas_mod.ResumoDaVenda, proposta: vendas_mod.PropostaNaVenda, novo: str) -> bool:
        if novo == proposta.status:
            return False
        ok, todas_negadas = self.executar("Não foi possível mudar a proposta",
                                          lambda: vendas_mod.mudar_status_proposta(proposta.id, novo))
        if ok:
            self._ao_gravar(f"{proposta.banco}: \"{proposta.status}\" → \"{novo}\".")
            if todas_negadas and perguntar_se_perdida(self._tela, venda.id, self.nome(venda)):
                self._ao_gravar(f"{self.nome(venda)}: Perdida (todos os bancos negaram).")
        return ok

    def voltar_proposta(self, venda: vendas_mod.ResumoDaVenda, proposta: vendas_mod.PropostaNaVenda) -> bool:
        ok, todas_negadas = self.executar("Não foi possível voltar", lambda: vendas_mod.voltar_proposta(proposta.id))
        if ok:
            self._ao_gravar(f"{proposta.banco}: voltou para \"{proposta.anterior}\".")
            if todas_negadas and perguntar_se_perdida(self._tela, venda.id, self.nome(venda)):
                self._ao_gravar(f"{self.nome(venda)}: Perdida (todos os bancos negaram).")
        return ok

    def excluir_proposta(self, venda: vendas_mod.ResumoDaVenda, proposta: vendas_mod.PropostaNaVenda) -> bool:
        resposta = QMessageBox.question(
            self._tela, "Excluir proposta",
            f"Excluir a proposta do {proposta.banco or 'banco'} da venda de {self.nome(venda)}? "
            "Essa ação não pode ser desfeita.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if resposta != QMessageBox.StandardButton.Yes:
            return False
        return self._gravar("Não foi possível excluir", lambda: vendas_mod.excluir_proposta(proposta.id),
                            f"{self.nome(venda)}: proposta do {proposta.banco or 'banco'} excluída.")

    # -- o formulario dentro do card aberto ---------------------------------------------------------

    @staticmethod
    def base_da_nova_proposta(venda: vendas_mod.ResumoDaVenda) -> dict:
        """O ponto de partida de "+ Adicionar proposta": valor, meses e carencia do ultimo banco (o caso comum e o
        mesmo pedido a outro banco), cobrindo a venda toda; sem nenhum banco ainda, so a venda."""
        if venda.propostas:
            ultima = venda.propostas[-1]
            linha = bd.ler_propostas(propostas_mod.CAMINHO_XLSX).loc[vendas_mod.indice_da_proposta(ultima.id)]
            base = propostas_mod.dados_para_duplicar(linha.to_dict())
        else:
            base = propostas_mod.dados_para_duplicar({"CPF": venda.cpf})
        base["EQUIPAMENTO"] = venda.equipamentos
        base["ID_VENDA"] = venda.id
        return base

    def criar_formulario(self, venda: vendas_mod.ResumoDaVenda, editando: str) -> FormularioProposta:
        """O formulario de sempre, aberto direto em edicao (a leitura e a propria linha do banco)."""
        nome = self.nome(venda)
        if editando == NOVA:
            return FormularioProposta(venda.cpf, nome, base=self.base_da_nova_proposta(venda), so_edicao=True)
        indice = vendas_mod.indice_da_proposta(editando)
        proposta = bd.ler_propostas(propostas_mod.CAMINHO_XLSX).loc[indice].to_dict()
        return FormularioProposta(venda.cpf, nome, proposta=proposta, indice=indice, so_edicao=True)


def proposta_por_id(venda: vendas_mod.ResumoDaVenda, id_proposta: str) -> vendas_mod.PropostaNaVenda | None:
    return next((p for p in venda.propostas if p.id == id_proposta), None)
