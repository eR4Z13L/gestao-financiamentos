"""Indicador de sincronizacao, no rodape da barra lateral: uma bolinha colorida + uma frase curta
("Sincronizado há 2 min"). Clicar mostra o detalhe (a hora e, se falhou, o erro).

  ADMIN     - verde: sincronizado; ambar: sincronizando; vermelho: falhou; cinza: desativada ou
              nenhuma sincronizacao ainda. Vem de core.sheets_sync.estado_atual(), so memoria.
  VENDEDOR  - so le do Google Sheets, nunca escreve: mostra "Dados de HH:MM" (a ultima leitura,
              core.data_store_sheets.ultima_leitura()).

As frases saem de funcoes puras (descrever_*), testaveis sem tela; o widget so pinta o que
recebe.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from core import sheets_sync
from core.formatting import tempo_decorrido_curto
from desktop.theme import CORES_STATUS, TEMA_ESCURO
from desktop import settings as settings_mod
from desktop.widgets.botao_lateral import BotaoLateral


@dataclass(frozen=True)
class DescricaoDoIndicador:
    nivel: str  # um dos NIVEL_* de core.sheets_sync
    texto: str  # a frase curta ao lado da bolinha
    detalhe: str  # o tooltip e o texto da janela aberta ao clicar


def _data_e_hora(momento: datetime) -> str:
    return momento.strftime("%d/%m/%Y %H:%M")


def descrever_sincronizacao(estado: sheets_sync.EstadoSincronizacao, agora: datetime) -> DescricaoDoIndicador:
    nivel = estado.nivel
    if nivel == sheets_sync.NIVEL_DESATIVADA:
        return DescricaoDoIndicador(
            nivel,
            "Sincronização desativada",
            "A sincronização com o Google Sheets está desativada. Os dados ficam só neste computador.",
        )
    if nivel == sheets_sync.NIVEL_SINCRONIZANDO:
        quantidade = f" ({estado.em_andamento})" if estado.em_andamento > 1 else ""
        return DescricaoDoIndicador(
            nivel,
            f"Sincronizando…{quantidade}",
            f"{estado.em_andamento} envio(s) para o Google Sheets em andamento.",
        )
    if nivel == sheets_sync.NIVEL_FALHOU:
        return DescricaoDoIndicador(
            nivel,
            "Falhou — clique para ver",
            f"A última sincronização com o Google Sheets falhou em {_data_e_hora(estado.ultima_falha)}.\n\n"
            f"{estado.ultimo_erro}\n\n"
            "Os dados continuam salvos neste computador. A próxima gravação tenta enviar de novo.",
        )
    if nivel == sheets_sync.NIVEL_OK:
        return DescricaoDoIndicador(
            nivel,
            f"Sincronizado {tempo_decorrido_curto(agora - estado.ultimo_sucesso)}",
            f"Última sincronização com o Google Sheets: {_data_e_hora(estado.ultimo_sucesso)}.",
        )
    return DescricaoDoIndicador(
        nivel,
        "Sem sincronização ainda",
        "Nenhuma sincronização foi feita desde que o aplicativo abriu. A próxima gravação envia os dados ao Google Sheets.",
    )


def descrever_leitura(ultima_leitura: datetime | None, agora: datetime) -> DescricaoDoIndicador:
    """A versao do VENDEDOR: ele so le, entao o que importa e "de quando sao os dados"."""
    if ultima_leitura is None:
        return DescricaoDoIndicador(
            sheets_sync.NIVEL_AGUARDANDO,
            "Sem leitura ainda",
            "Os dados ainda não foram lidos do Google Sheets nesta execução.",
        )
    hora = ultima_leitura.strftime("%H:%M") if ultima_leitura.date() == agora.date() else ultima_leitura.strftime("%d/%m %H:%M")
    return DescricaoDoIndicador(
        sheets_sync.NIVEL_OK,
        f"Dados de {hora}",
        f"Leitura mais recente do Google Sheets: {_data_e_hora(ultima_leitura)}. "
        "Use o botão Atualizar de cada tela para ler de novo.",
    )


class IndicadorSincronizacao(BotaoLateral):
    def __init__(self, parent: QWidget | None = None):
        super().__init__("Sem sincronização ainda", "", parent)
        self._descricao = DescricaoDoIndicador(sheets_sync.NIVEL_AGUARDANDO, "Sem sincronização ainda", "")

    def definir(self, descricao: DescricaoDoIndicador) -> None:
        self._descricao = descricao
        self.definir_rotulo(descricao.texto)
        self.setToolTip(f"{descricao.texto}\n{descricao.detalhe}" if descricao.detalhe else descricao.texto)

    def descricao(self) -> DescricaoDoIndicador:
        return self._descricao

    def cor_da_bolinha(self) -> QColor:
        nivel = self._descricao.nivel
        if nivel == sheets_sync.NIVEL_OK:
            return QColor(self._paleta["sucesso"])
        if nivel == sheets_sync.NIVEL_SINCRONIZANDO:
            return QColor(CORES_STATUS.get(settings_mod.obter_tema(), CORES_STATUS[TEMA_ESCURO])["em_analise"]["faixa"])
        if nivel == sheets_sync.NIVEL_FALHOU:
            return QColor(self._paleta["erro"])
        cor = QColor(self._paleta["texto_secundario"])  # desativada / aguardando: neutra, sem alarme
        cor.setAlpha(170)
        return cor

    def _pintar_marca(self, pintor: QPainter, area: QRectF, cor: QColor) -> None:
        pintor.setPen(Qt.PenStyle.NoPen)
        pintor.setBrush(self.cor_da_bolinha())
        centro = area.center()
        pintor.drawEllipse(centro, 4.5, 4.5)
