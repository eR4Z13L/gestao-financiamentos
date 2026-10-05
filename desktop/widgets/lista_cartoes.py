"""O que ficou dos cards antigos de proposta (a lista desenhada com QListView + delegate, que o card de proposta
substituiu no passo 3, em 05/10/2026): as cores de cada etapa/status - as mesmas no card de proposta, no card da
venda e no funil do Dashboard - e as medidas e ajudas de desenho que a lista de clientes (lista_clientes.py, feita do
mesmo jeito) reaproveita.
"""

from __future__ import annotations

from PySide6.QtGui import QFont

from core import propostas as propostas_mod

_RAIO = 10
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
    propostas_mod.ETAPA_NAO_EFETIVADO: "nao_efetivado",
    propostas_mod.ETAPA_PROPOSTA_ENCERRADA: "encerrada",
}


def chave_cor_etapa(etapa: str) -> str:
    """Chave de CORES_STATUS (desktop/theme.py) da etapa (propostas.ETAPA_*);
    sem status ou desconhecida -> "neutro" (cinza)."""
    return _COR_POR_ETAPA.get(etapa, "neutro")


def chave_cor_status(status: str) -> str:
    """Igual a chave_cor_etapa, a partir do texto do status."""
    return chave_cor_etapa(propostas_mod.etapa_status(status))


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
