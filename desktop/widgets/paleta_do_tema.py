"""Cores do tema ativo pra widgets desenhados por codigo (paintEvent): o QSS nao sabe colorir o que o
codigo desenha, e o tema pode mudar com o app aberto. Ponha `UsaPaletaDoTema` ANTES do widget do Qt
nas bases, chame `self._resolver_paleta()` no fim do __init__ e use `self._paleta` (as cores da
interface: "texto", "borda", "destaque"...) e `self._cores_de_status` (as de CORES_STATUS):

    class Grafico(UsaPaletaDoTema, QWidget): ...

Trocar o tema reaplica o stylesheet do app inteiro, o que manda StyleChange pra todo widget: e o sinal
pra reler as cores e repintar (feito aqui, na propria classe).
"""

from __future__ import annotations

from PySide6.QtCore import QEvent

from desktop import settings as settings_mod
from desktop.theme import CORES_STATUS, PALETAS, TEMA_ESCURO


class UsaPaletaDoTema:
    def _resolver_paleta(self) -> None:
        tema = settings_mod.obter_tema()
        self._tema = tema if tema in PALETAS else TEMA_ESCURO
        self._paleta = PALETAS[self._tema]
        self._cores_de_status = CORES_STATUS[self._tema]

    def changeEvent(self, evento: QEvent) -> None:
        if evento.type() == QEvent.Type.StyleChange:
            self._resolver_paleta()
            self.update()
        super().changeEvent(evento)
