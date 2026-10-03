"""Tela Vendas: um card por venda (cliente + equipamentos), com uma linha por banco para onde ela foi mandada.

O fluxo de cada card (desenhado com o usuario em 02/10/2026), na VENDA (topo) e em cada BANCO (linha):
- a etiqueta de status: um clique abre a lista para escolher qualquer status (na venda, as etapas e os desfechos;
  no banco, as 4 respostas);
- as bolinhas ao lado: avancam direto, na cor do status de destino - no banco, Aprovado e Negado (Pré-aprovado so
  pela lista); na venda, a proxima etapa a partir de Banco escolhido;
- o anel verde ao lado de cada banco APROVADO: escolhe (ou troca) o banco, e a venda vai sozinha para "Banco
  escolhido"; o ✓ do escolhido desfaz a escolha. Some depois da Nota fiscal;
- a setinha ↩: volta ao status de antes da ultima troca (pelo HISTÓRICO; de novo, mais um passo).
Efetivada, Não efetivada e Perdida pedem confirmacao (as duas ultimas com um motivo opcional). Quando o ultimo banco
nega, o app pergunta se a venda esta Perdida (nunca decide sozinho).

"+ Nova venda" cria a venda com o primeiro pedido; "Mandar a outro banco" (o antigo Duplicar) poe mais um pedido
na mesma venda. Propostas de antes das vendas, ainda nao juntadas, aparecem num aviso com o "Juntar em vendas...".
So o ADMIN ve esta tela (a do VENDEDOR, so leitura, ainda nao existe).
"""

from __future__ import annotations

from collections import Counter

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
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
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from core import data_store as bd
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import vendas as vendas_mod
from core.formatting import formatar_data, formatar_reais
from core.validators import apenas_digitos
from desktop import settings as settings_mod
from desktop.dialogs import organizar_vendas_dialog
from desktop.dialogs.pedido_venda_dialog import PedidoVendaDialog
from desktop.theme import CORES_STATUS, PALETAS
from desktop.vigia_do_arquivo import VigiaDoArquivo
from desktop.widgets.botao_recarregar import criar_botao_recarregar
from desktop.widgets.lista_cartoes import chave_cor_status

LARGURA_CARD = 500
_ESPACO = 12
_FAIXA = 5
_RAIO = 10
TAMANHO_PAGINA = 30
SEGUNDOS_DO_AVISO = 8

# as mesmas cores (ja conferidas nos dois temas) das etapas de proposta
COR_DA_VENDA = {
    vendas_mod.VENDA_AGUARDANDO: "em_analise",
    vendas_mod.VENDA_BANCO_ESCOLHIDO: "aprovado",
    vendas_mod.VENDA_NOTA_FISCAL: "nota_fiscal",
    vendas_mod.VENDA_GARANTIA: "garantia",
    vendas_mod.VENDA_EFETIVADA: "efetivado",
    vendas_mod.VENDA_NAO_EFETIVADA: "nao_efetivado",
    vendas_mod.VENDA_PERDIDA: "negado",
}
# a resposta do banco que as bolinhas oferecem enquanto ele nao respondeu (Pré-aprovado so pela lista)
RESPOSTAS_RAPIDAS = [propostas_mod.STATUS_APROVADO, propostas_mod.STATUS_NEGADO]
ESPERANDO_RESPOSTA = {propostas_mod.ETAPA_EM_ANALISE, propostas_mod.ETAPA_PRE_APROVADO}
# enquanto o banco ainda pode ser escolhido ou trocado no anel (depois da Nota fiscal, so voltando a venda)
ESCOLHA_ABERTA = {vendas_mod.VENDA_AGUARDANDO, vendas_mod.VENDA_BANCO_ESCOLHIDO}

FILTRO_EM_ANDAMENTO = "Em andamento"
FILTRO_PARADAS = f"Paradas há {vendas_mod.DIAS_PARA_ALERTA} dias ou mais"
FILTRO_EFETIVADAS = "Efetivadas"
FILTRO_PERDIDAS = "Perdidas e não efetivadas"
FILTRO_TODAS = "Todas"
FILTROS = [FILTRO_EM_ANDAMENTO, FILTRO_PARADAS, FILTRO_EFETIVADAS, FILTRO_PERDIDAS, FILTRO_TODAS]

_FRASE_STATUS = {  # (singular, plural) na contagem do topo
    vendas_mod.VENDA_AGUARDANDO: ("aguardando bancos", "aguardando bancos"),
    vendas_mod.VENDA_BANCO_ESCOLHIDO: ("com banco escolhido", "com banco escolhido"),
    vendas_mod.VENDA_NOTA_FISCAL: ("na nota fiscal", "na nota fiscal"),
    vendas_mod.VENDA_GARANTIA: ("na garantia", "na garantia"),
    vendas_mod.VENDA_EFETIVADA: ("efetivada", "efetivadas"),
    vendas_mod.VENDA_NAO_EFETIVADA: ("não efetivada", "não efetivadas"),
    vendas_mod.VENDA_PERDIDA: ("perdida", "perdidas"),
}


def passa_no_filtro(venda: vendas_mod.ResumoDaVenda, filtro: str) -> bool:
    if filtro == FILTRO_EM_ANDAMENTO:
        return not venda.finalizada
    if filtro == FILTRO_PARADAS:
        return venda.parada
    if filtro == FILTRO_EFETIVADAS:
        return venda.status == vendas_mod.VENDA_EFETIVADA
    if filtro == FILTRO_PERDIDAS:
        return venda.status in vendas_mod.DESFECHOS_DA_VENDA
    return True


def passa_na_busca(venda: vendas_mod.ResumoDaVenda, termo: str) -> bool:
    termo = termo.strip().upper()
    if not termo:
        return True
    texto = " ".join([venda.cliente, venda.cpf, venda.equipamentos, venda.vendedor,
                      *(p.banco for p in venda.propostas), *(p.equipamento for p in venda.propostas)]).upper()
    digitos = apenas_digitos(termo)
    return termo in texto or (len(digitos) >= 3 and digitos in apenas_digitos(venda.cpf))


def resumo_por_status(vendas: list[vendas_mod.ResumoDaVenda]) -> str:
    contagem = Counter(v.status for v in vendas)
    partes = []
    for status in vendas_mod.STATUS_DA_VENDA:
        if contagem.get(status):
            singular, plural = _FRASE_STATUS[status]
            partes.append(f"{contagem[status]} {singular if contagem[status] == 1 else plural}")
    return " · ".join(partes)


def proxima_pela_bolinha(status: str) -> str | None:
    """A etapa que a bolinha da venda oferece. Em "Aguardando bancos" nao ha: o proximo passo e escolher o banco,
    e isso se faz no anel da linha dele."""
    if status == vendas_mod.VENDA_AGUARDANDO:
        return None
    return vendas_mod.proxima_etapa(status)


def _ha_quanto(n: int | None) -> str:
    """ "hoje", "há 1 dia", "há 5 dias"."""
    return "hoje" if not n else ("há 1 dia" if n == 1 else f"há {n} dias")


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
    """A etiqueta de status, nas cores da etapa: um clique abre a lista para escolher o status."""

    def __init__(self, texto: str, cor: str, parent: QWidget | None = None):
        super().__init__(f"{texto}: clique para escolher o status", parent)
        self.cor = cor
        self.setText(texto)

    def _rotulo(self) -> str:
        return f"{self.text()}  ▾"

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
    """Ao lado de um banco aprovado: anel vazio = escolher este banco; ✓ cheio = o banco escolhido."""

    LADO = 20

    def __init__(self, escolhido: bool, dica: str, parent: QWidget | None = None):
        super().__init__(dica, parent)
        self.escolhido = escolhido
        self.setFixedSize(self.LADO, self.LADO)

    def paintEvent(self, _evento) -> None:
        verde = QColor(CORES_STATUS[_tema()]["aprovado"]["faixa"])
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        centro = QRectF(self.rect()).center()
        if self.escolhido:
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


class CardDaVenda(QFrame):
    # cada pedido leva a venda (e a proposta, quando e da linha de um banco); quem grava e a tela
    lista_da_venda_pedida = Signal(object, object)  # (ResumoDaVenda, Pilula)
    avanco_da_venda_pedido = Signal(object, str)  # (ResumoDaVenda, status)
    volta_da_venda_pedida = Signal(object)
    lista_da_proposta_pedida = Signal(object, object, object)  # (ResumoDaVenda, PropostaNaVenda, Pilula)
    resposta_pedida = Signal(object, object, str)  # (ResumoDaVenda, PropostaNaVenda, status)
    volta_da_proposta_pedida = Signal(object, object)
    escolha_pedida = Signal(object, object)  # (ResumoDaVenda, PropostaNaVenda)
    escolha_desfeita = Signal(object)
    outro_banco_pedido = Signal(object)
    ficha_pedida = Signal(str)  # cpf

    def __init__(self, venda: vendas_mod.ResumoDaVenda, parent: QWidget | None = None):
        super().__init__(parent)
        self.venda = venda
        self.setProperty("role", "card")
        self.setFixedWidth(LARGURA_CARD)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(_FAIXA + 14, 10, 12, 10)
        layout.setSpacing(4)

        topo = QHBoxLayout()
        topo.setSpacing(4)
        layout.addLayout(topo)  # ja no card: um widget num layout solto continua sem dono (e piscaria como janela)
        cliente = QLabel(venda.cliente or f"Cliente sem cadastro ({venda.cpf})", self)
        fonte = cliente.font()
        fonte.setBold(True)
        fonte.setPointSizeF(fonte.pointSizeF() + 1)
        cliente.setFont(fonte)
        cliente.setWordWrap(True)
        topo.addWidget(cliente, stretch=1)
        self.voltar: BotaoVoltar | None = None
        if venda.anterior:
            self.voltar = BotaoVoltar(venda.anterior, self)
            self.voltar.clicked.connect(lambda: self.volta_da_venda_pedida.emit(self.venda))
            topo.addWidget(self.voltar, alignment=Qt.AlignmentFlag.AlignTop)
        self.pilula = Pilula(venda.status or "Sem status", COR_DA_VENDA.get(venda.status, "neutro"), self)
        self.pilula.clicked.connect(lambda: self.lista_da_venda_pedida.emit(self.venda, self.pilula))
        topo.addWidget(self.pilula, alignment=Qt.AlignmentFlag.AlignTop)
        self.bolinha: Bolinha | None = None
        proxima = proxima_pela_bolinha(venda.status)
        if proxima:
            self.bolinha = Bolinha(proxima + ("…" if proxima == vendas_mod.VENDA_EFETIVADA else ""),
                                   COR_DA_VENDA[proxima], self)
            self.bolinha.clicked.connect(lambda: self.avanco_da_venda_pedido.emit(self.venda, proxima))
            topo.addWidget(self.bolinha, alignment=Qt.AlignmentFlag.AlignTop)

        detalhe = QLabel(" · ".join(p for p in (venda.equipamentos, venda.vendedor) if p) or "—", self)
        detalhe.setProperty("role", "secundario")
        detalhe.setWordWrap(True)
        layout.addWidget(detalhe)

        self.andamento = QLabel(self._texto_andamento(), self)
        self.andamento.setProperty("role", "aviso" if venda.parada else "secundario")
        self.andamento.setWordWrap(True)
        layout.addWidget(self.andamento)
        aprovadas = len(venda.aprovadas())
        self.convite: QLabel | None = None
        if venda.status == vendas_mod.VENDA_AGUARDANDO and aprovadas:
            self.convite = QLabel(
                f"{aprovadas} banco{'s' if aprovadas > 1 else ''} aprov{'aram' if aprovadas > 1 else 'ou'}: "
                "escolha no anel ao lado", self)
            self.convite.setProperty("role", "positivo")
            layout.addWidget(self.convite)
        if venda.motivo:
            motivo = QLabel(f"Motivo: {venda.motivo}", self)
            motivo.setProperty("role", "secundario")
            layout.addWidget(motivo)

        linha = QFrame(self)
        linha.setFrameShape(QFrame.Shape.HLine)
        layout.addSpacing(4)
        layout.addWidget(linha)

        self.linhas_de_banco: list[dict] = []  # por banco: proposta, pilula, bolinhas, anel, voltar
        if not venda.propostas:
            vazio = QLabel("Nenhum banco ainda.", self)
            vazio.setProperty("role", "secundario")
            layout.addWidget(vazio)
        for proposta in venda.propostas:
            layout.addLayout(self._linha_do_banco(proposta))

        rodape = QHBoxLayout()
        layout.addSpacing(2)
        layout.addLayout(rodape)
        self.botao_outro_banco = QPushButton("+ Mandar a outro banco", self)
        self.botao_outro_banco.setProperty("role", "botao_link")
        self.botao_outro_banco.setCursor(Qt.CursorShape.PointingHandCursor)
        self.botao_outro_banco.clicked.connect(lambda: self.outro_banco_pedido.emit(self.venda))
        self.botao_outro_banco.setVisible(not venda.finalizada)
        rodape.addWidget(self.botao_outro_banco)
        rodape.addStretch()
        ficha = QPushButton("Abrir a ficha", self)
        ficha.setProperty("role", "botao_link")
        ficha.setCursor(Qt.CursorShape.PointingHandCursor)
        ficha.clicked.connect(lambda: self.ficha_pedida.emit(self.venda.cpf))
        rodape.addWidget(ficha)

    def _texto_andamento(self) -> str:
        v = self.venda
        partes = [f"desde {formatar_data(v.data_criacao)}"] if v.data_criacao is not None else []
        if v.dias_na_etapa is not None and not v.finalizada:
            quanto = _ha_quanto(v.dias_na_etapa)
            partes.append(f"{'parada ' + quanto if v.parada else quanto} em \"{v.status}\"")
        return " · ".join(partes) or "sem data"

    def _linha_do_banco(self, proposta: vendas_mod.PropostaNaVenda) -> QVBoxLayout:
        """Duas linhas: em cima o banco, o status e os controles; embaixo, alinhadas ao nome do banco, as condicoes
        (valor, meses, carencia, parcela) - numa linha so elas nao cabiam no card."""
        bloco = QVBoxLayout()
        bloco.setSpacing(0)
        linha = QHBoxLayout()
        linha.setSpacing(8)
        bloco.addLayout(linha)
        itens = {"proposta": proposta, "anel": None, "voltar": None, "bolinhas": []}

        # o anel ocupa sempre o mesmo lugar (mesmo sem anel), pros nomes dos bancos ficarem alinhados
        aprovada = propostas_mod.etapa_status(proposta.status) == propostas_mod.ETAPA_APROVADO
        if proposta.escolhida:
            dica = "Banco escolhido (clique para desfazer a escolha)" \
                if self.venda.status == vendas_mod.VENDA_BANCO_ESCOLHIDO else "Banco escolhido"
            anel = AnelDoBanco(True, dica, self)
            if self.venda.status == vendas_mod.VENDA_BANCO_ESCOLHIDO:
                anel.clicked.connect(lambda: self.escolha_desfeita.emit(self.venda))
            linha.addWidget(anel)
            itens["anel"] = anel
        elif aprovada and self.venda.status in ESCOLHA_ABERTA:
            ja_tem = any(p.escolhida for p in self.venda.propostas)
            anel = AnelDoBanco(False, "Trocar para este banco" if ja_tem else "Escolher este banco", self)
            anel.clicked.connect(lambda: self.escolha_pedida.emit(self.venda, proposta))
            linha.addWidget(anel)
            itens["anel"] = anel
        else:
            linha.addSpacing(AnelDoBanco.LADO)

        banco = QLabel(proposta.banco or "Sem banco", self)
        fonte = banco.font()
        fonte.setWeight(QFont.Weight.DemiBold)
        banco.setFont(fonte)
        linha.addWidget(banco)
        partes = []
        if proposta.valor is not None:
            partes.append(formatar_reais(proposta.valor).replace(",00", ""))
        if proposta.meses:
            partes.append(f"{proposta.meses}x")
        if proposta.carencia is not None:
            partes.append(f"1ª em {proposta.carencia} dias")
        if proposta.parcela is not None:
            partes.append(f"parcela {formatar_reais(proposta.parcela)}")
        if proposta.equipamento and proposta.equipamento.strip().upper() != self.venda.equipamentos.strip().upper():
            partes.append(f"só {proposta.equipamento}")  # pedido separado, de parte da venda
        valores = QLabel(" · ".join(partes), self)
        valores.setProperty("role", "secundario")
        valores.setWordWrap(True)
        linha.addStretch(1)
        condicoes = QHBoxLayout()
        condicoes.addSpacing(AnelDoBanco.LADO + linha.spacing())
        condicoes.addWidget(valores, stretch=1)
        bloco.addLayout(condicoes)
        if proposta.dias_esperando is not None:
            espera = QLabel(_ha_quanto(proposta.dias_esperando), self)
            espera.setToolTip("Sem resposta do banco desde o envio (ou a última troca de status)")
            espera.setProperty("role", "aviso" if proposta.dias_esperando >= vendas_mod.DIAS_PARA_ALERTA else "secundario")
            linha.addWidget(espera)

        if proposta.anterior:
            voltar = BotaoVoltar(proposta.anterior, self)
            voltar.clicked.connect(lambda: self.volta_da_proposta_pedida.emit(self.venda, proposta))
            linha.addWidget(voltar)
            itens["voltar"] = voltar
        pilula = Pilula(proposta.status or "Sem status", chave_cor_status(proposta.status), self)
        pilula.clicked.connect(lambda: self.lista_da_proposta_pedida.emit(self.venda, proposta, pilula))
        linha.addWidget(pilula)
        itens["pilula"] = pilula
        # as bolinhas tem lugar fixo (mesmo sem nenhuma): as etiquetas ficam alinhadas entre os bancos
        caixa = QHBoxLayout()
        caixa.setSpacing(2)
        if propostas_mod.etapa_status(proposta.status) in ESPERANDO_RESPOSTA:
            for destino in RESPOSTAS_RAPIDAS:
                bolinha = Bolinha(destino, chave_cor_status(destino), self)
                bolinha.clicked.connect(lambda _=False, d=destino: self.resposta_pedida.emit(self.venda, proposta, d))
                caixa.addWidget(bolinha)
                itens["bolinhas"].append(bolinha)
        caixa.addSpacing((len(RESPOSTAS_RAPIDAS) - len(itens["bolinhas"])) * (Bolinha.LADO + caixa.spacing()))
        linha.addLayout(caixa)
        itens["condicoes"] = valores
        self.linhas_de_banco.append(itens)
        return bloco

    def paintEvent(self, evento) -> None:
        super().paintEvent(evento)
        # a faixa colorida da lateral, na cor da etapa da venda (como os cards de Todas as Propostas)
        cor = CORES_STATUS[_tema()][COR_DA_VENDA.get(self.venda.status, "neutro")]["faixa"]
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
        contorno = QPainterPath()
        contorno.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), _RAIO, _RAIO)
        pintor.setClipPath(contorno)
        pintor.fillRect(QRectF(0, 0, _FAIXA, self.height()), QColor(cor))


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
        botoes.button(QDialogButtonBox.StandardButton.Ok).setText(f"Marcar como {status}")
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)
        layout.addWidget(botoes)


class VendasScreen(QWidget):
    dados_atualizados = Signal()  # gravou algo: quem mostra dado derivado (Dashboard, selo) rele
    ficha_pedida = Signal(str)  # cpf

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._vigia = VigiaDoArquivo()
        self._vendas: list[vendas_mod.ResumoDaVenda] = []
        self._limite = TAMANHO_PAGINA
        self._colunas = 1
        self.cards: list[CardDaVenda] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        cabecalho = QHBoxLayout()
        layout.addLayout(cabecalho)
        titulo = QLabel("💼 Vendas")
        titulo.setProperty("role", "titulo")
        cabecalho.addWidget(titulo)
        cabecalho.addStretch()
        cabecalho.addWidget(criar_botao_recarregar(lambda *_: self.carregar()))
        self.botao_nova = QPushButton("+ Nova venda")
        self.botao_nova.setProperty("role", "botao_primario")
        self.botao_nova.clicked.connect(self.nova_venda)
        cabecalho.addWidget(self.botao_nova)

        self.aviso_sem_venda = QFrame()
        self.aviso_sem_venda.setProperty("role", "chip_filtro")
        linha_aviso = QHBoxLayout(self.aviso_sem_venda)
        linha_aviso.setContentsMargins(12, 6, 8, 6)
        self.texto_sem_venda = QLabel("")
        self.texto_sem_venda.setWordWrap(True)
        linha_aviso.addWidget(self.texto_sem_venda, stretch=1)
        juntar = QPushButton("Juntar em vendas…")
        juntar.clicked.connect(self._juntar_em_vendas)
        linha_aviso.addWidget(juntar)
        self.aviso_sem_venda.setVisible(False)
        layout.addWidget(self.aviso_sem_venda)

        filtros = QHBoxLayout()
        layout.addLayout(filtros)
        self.busca = QLineEdit()
        self.busca.setPlaceholderText("🔎 Buscar por cliente, CPF, equipamento ou banco")
        self.busca.setClearButtonEnabled(True)
        self.busca.textChanged.connect(lambda *_: self._montar(voltar_ao_inicio=True))
        filtros.addWidget(self.busca, stretch=1)
        self.filtro = QComboBox()
        self.filtro.addItems(FILTROS)
        self.filtro.currentIndexChanged.connect(lambda *_: self._montar(voltar_ao_inicio=True))
        filtros.addWidget(self.filtro)

        self.contador = QLabel("")
        self.contador.setProperty("role", "secundario")
        layout.addWidget(self.contador)

        self._conteudo = QWidget()
        self._conteudo.setProperty("role", "transparente")
        coluna = QVBoxLayout(self._conteudo)
        coluna.setContentsMargins(0, 0, 4, 0)
        self._grade = QGridLayout()
        self._grade.setSpacing(_ESPACO)
        self._grade.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        coluna.addLayout(self._grade)
        self.vazio = QLabel("", self._conteudo)
        self.vazio.setProperty("role", "secundario")
        coluna.addWidget(self.vazio)
        self.botao_mais = QPushButton("Carregar mais", self._conteudo)
        self.botao_mais.clicked.connect(self._carregar_mais)
        coluna.addWidget(self.botao_mais, alignment=Qt.AlignmentFlag.AlignLeft)
        coluna.addStretch()
        self.rolagem = QScrollArea()
        self.rolagem.setWidgetResizable(True)
        self.rolagem.setFrameShape(QFrame.Shape.NoFrame)
        self.rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rolagem.setWidget(self._conteudo)
        layout.addWidget(self.rolagem, stretch=1)

        # "Santander: "Em Análise" → "Aprovado"." - o que acabou de mudar; some sozinha (desfazer = a setinha ↩)
        self.faixa_aviso = QFrame()
        self.faixa_aviso.setProperty("role", "chip_filtro")
        linha_faixa = QHBoxLayout(self.faixa_aviso)
        linha_faixa.setContentsMargins(12, 6, 8, 6)
        self.texto_aviso = QLabel("")
        linha_faixa.addWidget(self.texto_aviso, stretch=1)
        self.faixa_aviso.setVisible(False)
        layout.addWidget(self.faixa_aviso)
        self._relogio_aviso = QTimer(self)
        self._relogio_aviso.setSingleShot(True)
        self._relogio_aviso.timeout.connect(lambda: self.faixa_aviso.setVisible(False))

        self.carregar()

    # -- dados --------------------------------------------------------------------------------------

    def carregar(self) -> bool:
        self._vigia.registrar_leitura()
        try:
            self._vendas = vendas_mod.listar_vendas()
            sem_venda = vendas_mod.contar_propostas_sem_venda()
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, "Erro ao carregar as vendas", f"{type(exc).__name__}: {exc}")
            return False
        self.texto_sem_venda.setText(
            f"{sem_venda} proposta(s) de antes das vendas ainda não estão em nenhuma venda e não aparecem aqui."
        )
        self.aviso_sem_venda.setVisible(sem_venda > 0)
        self._montar()
        return True

    def recarregar_se_mudou(self) -> bool:
        """A cada tique da janela com esta tela aberta: rele se o arquivo mudou por fora (outra tela gravou,
        baixou da nuvem, restaurou backup). True se releu."""
        if self._vigia.mudou_desde_a_leitura():
            return self.carregar()
        return False

    def showEvent(self, evento) -> None:
        super().showEvent(evento)
        self.recarregar_se_mudou()

    def vendas_visiveis(self) -> list[vendas_mod.ResumoDaVenda]:
        filtro = self.filtro.currentText()
        return [v for v in self._vendas if passa_no_filtro(v, filtro) and passa_na_busca(v, self.busca.text())]

    # -- montagem -----------------------------------------------------------------------------------

    def _montar(self, voltar_ao_inicio: bool = False) -> None:
        if voltar_ao_inicio:
            self._limite = TAMANHO_PAGINA
        rolagem = self.rolagem.verticalScrollBar().value()
        for card in self.cards:
            card.hide()  # some ja: o deleteLater so apaga no proximo ciclo
            card.deleteLater()
        self.cards = []
        visiveis = self.vendas_visiveis()
        for venda in visiveis[: self._limite]:
            card = CardDaVenda(venda, self._conteudo)
            card.lista_da_venda_pedida.connect(self._lista_da_venda)
            card.avanco_da_venda_pedido.connect(self._avancar_venda)
            card.volta_da_venda_pedida.connect(self._voltar_venda)
            card.lista_da_proposta_pedida.connect(self._lista_da_proposta)
            card.resposta_pedida.connect(self._mudar_proposta)
            card.volta_da_proposta_pedida.connect(self._voltar_proposta)
            card.escolha_pedida.connect(self._escolher_banco)
            card.escolha_desfeita.connect(self._desfazer_escolha)
            card.outro_banco_pedido.connect(self._mandar_a_outro_banco)
            card.ficha_pedida.connect(self.ficha_pedida)
            self.cards.append(card)
        resumo = resumo_por_status(visiveis)
        self.contador.setText(f"{len(visiveis)} venda(s)" + (f" · {resumo}" if resumo else ""))
        if self._vendas:
            self.vazio.setText("Nenhuma venda encontrada com esses filtros.")
        else:
            self.vazio.setText("Nenhuma venda ainda. Clique em \"+ Nova venda\".")
        self.vazio.setVisible(not visiveis)
        self.botao_mais.setVisible(len(visiveis) > self._limite)
        self._posicionar()
        if not voltar_ao_inicio:
            QTimer.singleShot(0, lambda: self.rolagem.verticalScrollBar().setValue(rolagem))

    def _posicionar(self) -> None:
        while self._grade.count():
            self._grade.takeAt(0)
        for indice, card in enumerate(self.cards):
            self._grade.addWidget(card, indice // self._colunas, indice % self._colunas, Qt.AlignmentFlag.AlignTop)

    def resizeEvent(self, evento) -> None:
        super().resizeEvent(evento)
        largura = self.width() - 48 - 4 - self.rolagem.verticalScrollBar().sizeHint().width()
        colunas = max(1, (largura + _ESPACO) // (LARGURA_CARD + _ESPACO))
        if colunas != self._colunas:
            self._colunas = colunas
            self._posicionar()

    def _carregar_mais(self) -> None:
        self._limite += TAMANHO_PAGINA
        self._montar()

    # -- gravar -------------------------------------------------------------------------------------

    def _executar(self, titulo_erro: str, acao):
        """Roda a acao do core mostrando o erro (nunca em silencio). Devolve (True, resultado) ou (False, None)."""
        try:
            return True, acao()
        except (vendas_mod.ErroVenda, propostas_mod.ErroProposta) as exc:
            QMessageBox.warning(self, titulo_erro, str(exc))
        except sessao_mod.PermissaoNegada as exc:
            QMessageBox.warning(self, "Ação não permitida", str(exc))
        except bd.ErroArquivoBloqueado as exc:
            QMessageBox.critical(self, "Arquivo bloqueado", str(exc))
        except Exception as exc:  # nunca falhar em silencio
            QMessageBox.critical(self, f"Erro inesperado: {titulo_erro.lower()}", f"{type(exc).__name__}: {exc}")
        return False, None

    def _gravar(self, titulo_erro: str, acao, aviso: str | None = None) -> bool:
        ok, resultado = self._executar(titulo_erro, acao)
        if not ok:
            return False
        self.carregar()
        self.dados_atualizados.emit()
        if aviso:
            self.avisar(aviso(resultado) if callable(aviso) else aviso)
        return True

    def avisar(self, texto: str) -> None:
        self.texto_aviso.setText(texto)
        self.faixa_aviso.setVisible(True)
        self._relogio_aviso.start(SEGUNDOS_DO_AVISO * 1000)

    @staticmethod
    def _nome(venda: vendas_mod.ResumoDaVenda) -> str:
        return venda.cliente or venda.cpf

    # -- venda --------------------------------------------------------------------------------------

    def montar_menu_da_venda(self, venda: vendas_mod.ResumoDaVenda) -> QMenu:
        """A lista da etiqueta da venda: as etapas (menos "Banco escolhido", que se escolhe no anel do banco) e os
        desfechos; a atual vem marcada."""
        menu = QMenu(self)
        for status in vendas_mod.ETAPAS_DA_VENDA:
            if status == vendas_mod.VENDA_BANCO_ESCOLHIDO:
                continue
            texto = status + ("…" if status == vendas_mod.VENDA_EFETIVADA else "")
            acao = menu.addAction(texto, lambda s=status: self._escolher_status_da_venda(venda, s))
            acao.setCheckable(True)
            acao.setChecked(status == venda.status)
        menu.addSection("Desfechos")
        for status in vendas_mod.DESFECHOS_DA_VENDA:
            acao = menu.addAction(f"{status}…", lambda s=status: self._escolher_status_da_venda(venda, s))
            acao.setCheckable(True)
            acao.setChecked(status == venda.status)
        return menu

    def _lista_da_venda(self, venda: vendas_mod.ResumoDaVenda, pilula: Pilula) -> None:
        self.montar_menu_da_venda(venda).exec(pilula.mapToGlobal(pilula.rect().bottomLeft()))

    def _escolher_status_da_venda(self, venda: vendas_mod.ResumoDaVenda, status: str) -> bool:
        if status == venda.status:
            return False
        if status == vendas_mod.VENDA_EFETIVADA:
            return self._efetivar(venda)
        if status in vendas_mod.DESFECHOS_DA_VENDA:
            return self._desfecho(venda, status)
        return self._gravar("Não foi possível mudar a venda",
                            lambda: vendas_mod.mudar_status_venda(venda.id, status),
                            f"{self._nome(venda)}: \"{venda.status}\" → \"{status}\".")

    def _avancar_venda(self, venda: vendas_mod.ResumoDaVenda, status: str) -> bool:
        return self._escolher_status_da_venda(venda, status)

    def _voltar_venda(self, venda: vendas_mod.ResumoDaVenda) -> bool:
        if venda.finalizada:  # reabrir uma venda fechada nunca acontece por um clique sem querer
            resposta = QMessageBox.question(
                self, "Reabrir a venda",
                f"A venda de {self._nome(venda)} está \"{venda.status}\". Voltar para \"{venda.anterior}\"?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
            )
            if resposta != QMessageBox.StandardButton.Yes:
                return False
        return self._gravar("Não foi possível voltar", lambda: vendas_mod.voltar_venda(venda.id),
                            lambda para: f"{self._nome(venda)}: voltou para \"{para}\".")

    def _escolher_banco(self, venda: vendas_mod.ResumoDaVenda, proposta: vendas_mod.PropostaNaVenda) -> bool:
        troca = any(p.escolhida for p in venda.propostas)
        return self._gravar(
            "Não foi possível escolher o banco",
            lambda: vendas_mod.mudar_status_venda(venda.id, vendas_mod.VENDA_BANCO_ESCOLHIDO, proposta_escolhida=proposta.id),
            f"{self._nome(venda)}: banco escolhido {'trocado para' if troca else '→'} {proposta.banco}.",
        )

    def _desfazer_escolha(self, venda: vendas_mod.ResumoDaVenda) -> bool:
        return self._gravar("Não foi possível desfazer a escolha",
                            lambda: vendas_mod.mudar_status_venda(venda.id, vendas_mod.VENDA_AGUARDANDO),
                            f"{self._nome(venda)}: escolha desfeita, a venda voltou para \"Aguardando bancos\".")

    def _efetivar(self, venda: vendas_mod.ResumoDaVenda) -> bool:
        escolhida = next((p for p in venda.propostas if p.escolhida), None)
        if escolhida is None:
            QMessageBox.warning(self, "Escolha o banco antes",
                                "Para marcar como Efetivada, escolha antes o banco (o anel ao lado do banco aprovado).")
            return False
        resposta = QMessageBox.question(
            self, "Marcar como Efetivada",
            f"Marcar a venda de {self._nome(venda)} como Efetivada, pelo {escolhida.banco}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if resposta != QMessageBox.StandardButton.Yes:
            return False
        return self._gravar("Não foi possível efetivar",
                            lambda: vendas_mod.mudar_status_venda(venda.id, vendas_mod.VENDA_EFETIVADA),
                            f"{self._nome(venda)}: Efetivada.")

    def _desfecho(self, venda: vendas_mod.ResumoDaVenda, status: str) -> bool:
        dialogo = DesfechoDialog(venda, status, self)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return False
        motivo = dialogo.motivo.currentData() or ""
        return self._gravar(f"Não foi possível marcar como {status}",
                            lambda: vendas_mod.mudar_status_venda(venda.id, status, motivo=motivo),
                            f"{self._nome(venda)}: {status}.")

    # -- proposta (a resposta de cada banco) ----------------------------------------------------------

    def montar_menu_da_proposta(self, venda: vendas_mod.ResumoDaVenda, proposta: vendas_mod.PropostaNaVenda) -> QMenu:
        menu = QMenu(self)
        menu.addSection(f"Resposta do {proposta.banco or 'banco'}")
        for status in vendas_mod.STATUS_DA_PROPOSTA:
            acao = menu.addAction(status, lambda s=status: self._mudar_proposta(venda, proposta, s))
            acao.setCheckable(True)
            acao.setChecked(status == proposta.status)
            if proposta.escolhida and status != propostas_mod.STATUS_APROVADO:
                acao.setEnabled(False)  # o core tambem recusa: a venda ficaria com um banco que nao aprovou
        if proposta.escolhida:
            aviso = menu.addAction("É o banco escolhido da venda: desfaça a escolha antes")
            aviso.setEnabled(False)
        return menu

    def _lista_da_proposta(self, venda, proposta, pilula: Pilula) -> None:
        self.montar_menu_da_proposta(venda, proposta).exec(pilula.mapToGlobal(pilula.rect().bottomLeft()))

    def _depois_da_resposta(self, venda: vendas_mod.ResumoDaVenda, todas_negadas: bool) -> None:
        if not todas_negadas:
            return
        resposta = QMessageBox.question(
            self, "Todos os bancos negaram",
            f"Todos os bancos da venda de {self._nome(venda)} negaram. Marcar a venda como Perdida "
            "(motivo: Todos os bancos negaram)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if resposta == QMessageBox.StandardButton.Yes:
            self._gravar("Não foi possível marcar como Perdida",
                         lambda: vendas_mod.mudar_status_venda(venda.id, vendas_mod.VENDA_PERDIDA,
                                                               motivo="Todos os bancos negaram"),
                         f"{self._nome(venda)}: Perdida (todos os bancos negaram).")

    def _mudar_proposta(self, venda: vendas_mod.ResumoDaVenda, proposta: vendas_mod.PropostaNaVenda, novo: str) -> bool:
        if novo == proposta.status:
            return False
        ok, todas_negadas = self._executar("Não foi possível mudar a proposta",
                                           lambda: vendas_mod.mudar_status_proposta(proposta.id, novo))
        if not ok:
            return False
        self.carregar()
        self.dados_atualizados.emit()
        self.avisar(f"{proposta.banco}: \"{proposta.status}\" → \"{novo}\".")
        self._depois_da_resposta(venda, todas_negadas)
        return True

    def _voltar_proposta(self, venda: vendas_mod.ResumoDaVenda, proposta: vendas_mod.PropostaNaVenda) -> bool:
        ok, todas_negadas = self._executar("Não foi possível voltar",
                                           lambda: vendas_mod.voltar_proposta(proposta.id))
        if not ok:
            return False
        self.carregar()
        self.dados_atualizados.emit()
        self.avisar(f"{proposta.banco}: voltou para \"{proposta.anterior}\".")
        self._depois_da_resposta(venda, todas_negadas)
        return True

    # -- criar --------------------------------------------------------------------------------------

    def nova_venda(self) -> bool:
        if not sessao_mod.eh_admin():
            return False
        dialogo = PedidoVendaDialog(self)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return False
        self.busca.clear()
        self.filtro.setCurrentText(FILTRO_EM_ANDAMENTO)
        self.carregar()
        self.dados_atualizados.emit()
        return True

    def _mandar_a_outro_banco(self, venda: vendas_mod.ResumoDaVenda) -> bool:
        dialogo = PedidoVendaDialog(self, venda=venda)
        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return False
        self.carregar()
        self.dados_atualizados.emit()
        return True

    def _juntar_em_vendas(self) -> None:
        if organizar_vendas_dialog.organizar(self):
            self.carregar()
            self.dados_atualizados.emit()
