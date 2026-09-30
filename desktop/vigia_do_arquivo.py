"""Cada tela guarda um VigiaDoArquivo: a "impressao" (momento + tamanho) do arquivo de dados na ultima
vez que ela o leu. Ao aparecer, a tela compara com a impressao atual e so rele se mudou - assim trocar de
pagina mostra sempre o dado atual (gravado em outra tela, baixado da nuvem, restaurado de um backup ou
editado por fora) sem reler a toa quando nada mudou.
"""

from __future__ import annotations

from core import data_store as bd
from core import propostas as propostas_mod
from core import sessao as sessao_mod


class VigiaDoArquivo:
    def __init__(self) -> None:
        self._impressao_lida: tuple[int, int] | None = None
        self._ja_leu = False

    @staticmethod
    def _impressao_atual() -> tuple[int, int] | None:
        # o caminho vem do modulo que as telas usam pra ler (os testes redirecionam ele pra fixture)
        return bd.assinatura_do_arquivo(propostas_mod.CAMINHO_XLSX)

    def registrar_leitura(self) -> None:
        """Chamar ANTES de ler: se o arquivo mudar durante a leitura, a proxima vez rele de novo."""
        self._impressao_lida = self._impressao_atual()
        self._ja_leu = True

    def mudou_desde_a_leitura(self) -> bool:
        """True se o arquivo mudou depois da ultima leitura desta tela. O VENDEDOR le do Google Sheets,
        nao do arquivo local: pra ele, sempre False (as telas dele seguem o botao Atualizar)."""
        if sessao_mod.eh_vendedor():
            return False
        return not self._ja_leu or self._impressao_atual() != self._impressao_lida
