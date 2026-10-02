"""Icones de linha (um traco fino, quase todos sem preenchimento) desenhados por codigo: o
QSS nao sabe colorir icone e emoji nao acompanha o tema. Cada icone usa a cor que quem
desenha passar (a do tema ativo, ou a de destaque quando selecionado), entao se refaz
sozinho quando o tema muda. Excecao: "whatsapp" preenche o fone e a caudinha do balao,
pra ficar reconhecivel como o icone oficial.

Os desenhos vivem num quadrado de 24 x 24 e sao escalados pra area pedida:

    desenhar_icone(pintor, "dashboard", QRectF(x, y, 18, 18), cor)   # direto num QPainter
    botao.setIcon(icone_de_linha("sair", cor))                        # ou como QIcon de um botao
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

_LADO_LOGICO = 24.0
_ESPESSURA = 1.7
_ESCALA_DA_IMAGEM = 2  # o QIcon e desenhado em dobro e marcado como tal: nitido em tela de alta densidade


def _dashboard(p: QPainter) -> None:
    for x, topo in ((4.0, 13.0), (10.0, 8.0), (16.0, 4.0)):  # tres barras crescentes
        p.drawRoundedRect(QRectF(x, topo, 4.0, 20.0 - topo), 1.2, 1.2)


def _ficha(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(3, 5, 18, 14), 2.2, 2.2)  # o cartao
    p.drawEllipse(QPointF(9, 10.5), 2.2, 2.2)  # cabeca
    ombros = QPainterPath(QPointF(5.4, 16.2))
    ombros.cubicTo(6.2, 13.6, 11.8, 13.6, 12.6, 16.2)
    p.drawPath(ombros)
    p.drawLine(QPointF(15, 10), QPointF(18.5, 10))
    p.drawLine(QPointF(15, 13.5), QPointF(18.5, 13.5))


def _propostas(p: QPainter) -> None:
    p.drawRoundedRect(QRectF(5, 3, 14, 18), 2.2, 2.2)  # a folha
    p.drawLine(QPointF(8.5, 8.5), QPointF(15.5, 8.5))
    p.drawLine(QPointF(8.5, 12.5), QPointF(15.5, 12.5))
    p.drawLine(QPointF(8.5, 16.5), QPointF(12.5, 16.5))


def _administracao(p: QPainter) -> None:
    # tres controles deslizantes: a linha para em volta do botao, pra nao atravessa-lo
    for y, x_botao in ((6.0, 9.0), (12.0, 15.5), (18.0, 8.0)):
        p.drawLine(QPointF(4, y), QPointF(x_botao - 2.6, y))
        p.drawLine(QPointF(x_botao + 2.6, y), QPointF(20, y))
        p.drawEllipse(QPointF(x_botao, y), 2.1, 2.1)


def _mais(p: QPainter) -> None:
    p.drawLine(QPointF(12, 5), QPointF(12, 19))
    p.drawLine(QPointF(5, 12), QPointF(19, 12))


def _sair(p: QPainter) -> None:
    porta = QPainterPath(QPointF(10, 4))
    porta.lineTo(5, 4)
    porta.lineTo(5, 20)
    porta.lineTo(10, 20)
    p.drawPath(porta)
    p.drawLine(QPointF(9.5, 12), QPointF(20, 12))  # a seta, saindo pela porta
    seta = QPainterPath(QPointF(16, 8))
    seta.lineTo(20, 12)
    seta.lineTo(16, 16)
    p.drawPath(seta)


def _sol(p: QPainter) -> None:
    p.drawEllipse(QPointF(12, 12), 4.0, 4.0)
    for i in range(8):
        angulo = math.radians(45 * i)
        dx, dy = math.cos(angulo), math.sin(angulo)
        p.drawLine(QPointF(12 + 6.6 * dx, 12 + 6.6 * dy), QPointF(12 + 9.0 * dx, 12 + 9.0 * dy))


def _lua(p: QPainter) -> None:
    disco = QPainterPath()
    disco.addEllipse(QRectF(4, 4, 16, 16))
    recorte = QPainterPath()
    recorte.addEllipse(QRectF(9.5, 1.5, 14, 14))
    p.drawPath(disco.subtracted(recorte))  # o disco menos um disco deslocado = o crescente


def _whatsapp(p: QPainter) -> None:
    # o balao (anel grosso) e o fone (preenchido) do icone oficial - unico icone
    # desta lista que preenche em vez de so contornar, pra ficar reconhecivel
    cor = p.pen().color()
    p.setPen(QPen(cor, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawEllipse(QPointF(12, 11), 7.5, 7.5)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(cor)
    cauda = QPainterPath(QPointF(7.6, 16.8))
    cauda.lineTo(4.9, 20.6)
    cauda.lineTo(9.3, 18.2)
    cauda.closeSubpath()
    p.drawPath(cauda)
    fone = QPainterPath(QPointF(8.8, 7.6))
    fone.cubicTo(9.1, 7.3, 9.5, 7.3, 9.8, 7.5)
    fone.lineTo(11.4, 9.0)
    fone.cubicTo(11.7, 9.3, 11.7, 9.7, 11.4, 10.0)
    fone.lineTo(10.7, 10.7)
    fone.cubicTo(11.3, 11.7, 12.1, 12.5, 13.1, 13.1)
    fone.lineTo(13.8, 12.4)
    fone.cubicTo(14.1, 12.1, 14.5, 12.1, 14.8, 12.4)
    fone.lineTo(16.3, 14.0)
    fone.cubicTo(16.5, 14.3, 16.5, 14.7, 16.2, 15.0)
    fone.cubicTo(15.3, 15.9, 14.0, 16.2, 12.8, 15.7)
    fone.cubicTo(11.5, 15.0, 8.8, 11.5, 7.8, 10.7)
    fone.cubicTo(7.3, 9.5, 7.6, 8.2, 8.5, 7.3)
    fone.closeSubpath()
    p.drawPath(fone)


def _link_externo(p: QPainter) -> None:
    caixa = QPainterPath(QPointF(18, 13))
    caixa.lineTo(18, 19)
    caixa.lineTo(5, 19)
    caixa.lineTo(5, 7)
    caixa.lineTo(11, 7)
    p.drawPath(caixa)
    seta_canto = QPainterPath(QPointF(14, 4))
    seta_canto.lineTo(20, 4)
    seta_canto.lineTo(20, 10)
    p.drawPath(seta_canto)
    p.drawLine(QPointF(10, 14), QPointF(20, 4))


def _cadastros(p: QPainter) -> None:
    # dois cards empilhados: o de tras so aparece pela borda de cima
    p.drawRoundedRect(QRectF(4, 8, 16, 12), 2, 2)
    p.drawLine(QPointF(6.5, 5), QPointF(17.5, 5))
    p.drawLine(QPointF(7.5, 12.5), QPointF(16.5, 12.5))
    p.drawLine(QPointF(7.5, 16), QPointF(13, 16))


def _lapis(p: QPainter) -> None:
    corpo = QPainterPath(QPointF(15.5, 5.5))
    corpo.lineTo(18.5, 8.5)
    corpo.lineTo(8.5, 18.5)
    corpo.lineTo(4.5, 19.5)
    corpo.lineTo(5.5, 15.5)
    corpo.closeSubpath()
    p.drawPath(corpo)
    p.drawLine(QPointF(13.5, 7.5), QPointF(16.5, 10.5))  # a ponta da borracha


def _tres_pontos(p: QPainter) -> None:
    p.setBrush(p.pen().color())
    for y in (6, 12, 18):
        p.drawEllipse(QPointF(12, y), 1.2, 1.2)


def _confirmar(p: QPainter) -> None:
    marca = QPainterPath(QPointF(5, 12.5))
    marca.lineTo(10, 17.5)
    marca.lineTo(19, 7)
    p.drawPath(marca)


def _fechar(p: QPainter) -> None:
    p.drawLine(QPointF(6.5, 6.5), QPointF(17.5, 17.5))
    p.drawLine(QPointF(17.5, 6.5), QPointF(6.5, 17.5))


_DESENHOS = {
    "dashboard": _dashboard,
    "ficha": _ficha,
    "propostas": _propostas,
    "administracao": _administracao,
    "mais": _mais,
    "sair": _sair,
    "sol": _sol,
    "lua": _lua,
    "whatsapp": _whatsapp,
    "link_externo": _link_externo,
    "cadastros": _cadastros,
    "lapis": _lapis,
    "tres_pontos": _tres_pontos,
    "confirmar": _confirmar,
    "fechar": _fechar,
}


def nomes_de_icones() -> list[str]:
    return sorted(_DESENHOS)


def desenhar_icone(pintor: QPainter, nome: str, area: QRectF, cor: QColor) -> None:
    """Desenha o icone `nome` dentro de `area` (mantendo o estado do `pintor`). Nome que nao
    existe e erro: um icone faltando nao pode passar em branco."""
    desenho = _DESENHOS.get(nome)
    if desenho is None:
        raise KeyError(f"Icone desconhecido: {nome!r} (existentes: {', '.join(nomes_de_icones())})")
    pintor.save()
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    pintor.translate(area.topLeft())
    pintor.scale(area.width() / _LADO_LOGICO, area.height() / _LADO_LOGICO)
    pintor.setBrush(Qt.BrushStyle.NoBrush)
    pintor.setPen(QPen(cor, _ESPESSURA, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    desenho(pintor)
    pintor.restore()


def icone_de_linha(nome: str, cor: QColor, lado: int = 18) -> QIcon:
    """O icone `nome` na cor `cor` como QIcon (pra QPushButton.setIcon)."""
    imagem = QPixmap(lado * _ESCALA_DA_IMAGEM, lado * _ESCALA_DA_IMAGEM)
    imagem.setDevicePixelRatio(_ESCALA_DA_IMAGEM)
    imagem.fill(Qt.GlobalColor.transparent)
    pintor = QPainter(imagem)
    desenhar_icone(pintor, nome, QRectF(0, 0, lado, lado), cor)
    pintor.end()
    return QIcon(imagem)
