"""Formatacao "ao vivo" de campos de texto (CPF/CNPJ, telefone) - aplica a
mascara certa conforme o usuario digita, detectando CPF x CNPJ (e telefone
fixo x celular) pela quantidade de digitos, sem exigir um formato fixo de
antemao.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QLineEdit

from core.validators import apenas_digitos


def _aplicar_mascara(digitos: str, mascara: str) -> str:
    """Intercala `digitos` nos espacos '#' de `mascara`, parando assim que
    os digitos acabarem (nunca deixa pontuacao "pendurada" no final)."""
    resultado = []
    i = 0
    for ch in mascara:
        if i >= len(digitos):
            break
        if ch == "#":
            resultado.append(digitos[i])
            i += 1
        else:
            resultado.append(ch)
    return "".join(resultado)


def formatar_cpf_cnpj_parcial(digitos: str) -> str:
    digitos = digitos[:14]
    mascara = "###.###.###-##" if len(digitos) <= 11 else "##.###.###/####-##"
    return _aplicar_mascara(digitos, mascara)


def formatar_telefone_parcial(digitos: str) -> str:
    digitos = digitos[:11]
    mascara = "(##) #####-####" if len(digitos) > 10 else "(##) ####-####"
    return _aplicar_mascara(digitos, mascara)


def conectar_mascara(campo: QLineEdit, formatador: Callable[[str], str]) -> None:
    """Reformata `campo` a cada tecla digitada, usando `formatador` (recebe
    so os digitos ja limpos e devolve o texto pontuado). Mantem o cursor na
    mesma posicao "relativa" (mesma quantidade de digitos antes dele), pra
    nao atrapalhar quem esta corrigindo no meio do texto.
    """

    def _ao_digitar(texto_atual: str) -> None:
        cursor_antes = campo.cursorPosition()
        digitos_antes_do_cursor = len(apenas_digitos(texto_atual[:cursor_antes]))

        texto_formatado = formatador(apenas_digitos(texto_atual))
        if texto_formatado == texto_atual:
            return

        campo.blockSignals(True)
        campo.setText(texto_formatado)

        pos = 0
        contados = 0
        while pos < len(texto_formatado) and contados < digitos_antes_do_cursor:
            if texto_formatado[pos].isdigit():
                contados += 1
            pos += 1
        campo.setCursorPosition(pos)
        campo.blockSignals(False)

    campo.textChanged.connect(_ao_digitar)
