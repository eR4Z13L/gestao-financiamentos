"""Ajuda um QLabel com word wrap a quebrar linha mesmo dentro de um texto sem
nenhum espaco (ex.: uma URL ou um slug longo colado na Rede Social) - o
word wrap padrao do Qt so quebra em espaco/pontuacao, entao um trecho sem
nenhum ponto de quebra faz o layout inteiro esticar pra caber nele em vez de
quebrar linha.

A solucao e inserir um espaco de largura zero (invisivel) a cada N
caracteres dentro de qualquer trecho "colado" - isso da ao Qt pontos de
quebra artificiais sem mudar nada do que aparece na tela. Usar so na hora de
EXIBIR o texto (nunca no valor que e validado/gravado no .xlsx).
"""

from __future__ import annotations

import re

_TAMANHO_MAXIMO_SEM_QUEBRA = 20
_ESPACO_LARGURA_ZERO = "​"  # ZERO WIDTH SPACE - ponto de quebra invisivel


def texto_quebravel(texto: str, tamanho_maximo: int = _TAMANHO_MAXIMO_SEM_QUEBRA) -> str:
    if not texto:
        return texto
    partes = re.split(r"(\s+)", texto)
    pedacos = []
    for parte in partes:
        if not parte or parte.isspace():
            pedacos.append(parte)
            continue
        trechos = [parte[i : i + tamanho_maximo] for i in range(0, len(parte), tamanho_maximo)]
        pedacos.append(_ESPACO_LARGURA_ZERO.join(trechos))
    return "".join(pedacos)
