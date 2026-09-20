"""Formatacao de valores pra exibicao nas telas. Um valor ausente (None/NaN)
sempre vira "—" - nunca um numero quebrado tipo "R$ nan" ou uma celula em
branco sem explicacao (existia na planilha um caso assim: proposta antiga
sem VALOR/MESES preenchido, e a tela mostrava "R$ nan" literalmente).
"""

from __future__ import annotations

import re
from datetime import timedelta

import pandas as pd

_AUSENTE = "—"
_REGEX_DIAS = re.compile(r"(-?\d+)\s+dias?", re.IGNORECASE)


def formatar_reais(valor) -> str:
    if pd.isna(valor):
        return _AUSENTE
    texto = f"{valor:,.2f}"
    return "R$ " + texto.replace(",", "X").replace(".", ",").replace("X", ".")


def formatar_data(valor) -> str:
    if isinstance(valor, pd.Timestamp) and not pd.isna(valor):
        return valor.strftime("%d/%m/%Y")
    return _AUSENTE


def formatar_meses(valor) -> str:
    if pd.isna(valor):
        return _AUSENTE
    return str(int(valor))


def formatar_equipamento_e_valor(equipamento, valor) -> str:
    """"HAKON · R$ 75.000,00": o equipamento e o valor da proposta numa linha so.
    O que faltar fica de fora (so o equipamento, ou so o valor); sem nenhum dos
    dois, "—" - a linha nunca some, pra os cards terem todos a mesma altura."""
    partes = [_texto_limpo(equipamento)]
    if valor is not None and not pd.isna(valor):
        partes.append(formatar_reais(valor))
    return " · ".join(p for p in partes if p) or _AUSENTE


def _texto_limpo(valor) -> str:
    """Texto sem espacos nas pontas; ausente (None/NaN) vira ""."""
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        return ""
    return str(valor).strip()


def formatar_endereco(*, logradouro="", numero="", complemento="", bairro="", cidade="", uf="", cep="") -> str:
    """O endereco por extenso, numa linha so:
    "Rua das Palmeiras, 211, Apto 301 - Centro, Curitiba/PR - CEP 80000-000".
    O que estiver em branco fica de fora, sem sobrar virgula, barra ou traco
    ("Rua das Palmeiras - Curitiba - CEP 80000-000"); tudo em branco devolve "".
    Um CEP de 8 digitos sem o hifen (planilha antiga) sai como 00000-000; qualquer
    outro formato e mostrado como esta - nunca se adivinha um CEP."""
    rua = ", ".join(p for p in (_texto_limpo(logradouro), _texto_limpo(numero), _texto_limpo(complemento)) if p)
    cidade_uf = "/".join(p for p in (_texto_limpo(cidade), _texto_limpo(uf)) if p)
    localidade = ", ".join(p for p in (_texto_limpo(bairro), cidade_uf) if p)

    cep_texto = _texto_limpo(cep)
    digitos_cep = re.sub(r"\D", "", cep_texto)
    if len(digitos_cep) == 8:
        cep_texto = f"{digitos_cep[:5]}-{digitos_cep[5:]}"
    cep_completo = f"CEP {cep_texto}" if cep_texto else ""

    return " - ".join(p for p in (rua, localidade, cep_completo) if p)


def dias_do_tempo(tempo) -> int | None:
    """Dias em aberto lidos da coluna TEMPO ("7 dias" -> 7; negativo se a data
    da proposta esta no futuro). None quando nao ha um numero de dias:
    "Encerrado", vazio ou um texto que nao conhecemos."""
    if tempo is None or (not isinstance(tempo, str) and pd.isna(tempo)):
        return None
    casado = _REGEX_DIAS.fullmatch(str(tempo).strip())
    return int(casado.group(1)) if casado else None


def formatar_tempo(tempo) -> str:
    """Coluna TEMPO de uma proposta ("7 dias" / "Encerrado" / "") num texto
    curto pra ler de relance: "há 7 dias", "há 1 dia", "hoje", "Encerrado".
    Sem dado devolve "" (quem chama decide se mostra alguma coisa)."""
    if tempo is None or (not isinstance(tempo, str) and pd.isna(tempo)):
        return ""
    texto = str(tempo).strip()
    if not texto:
        return ""
    if texto.upper() == "ENCERRADO":
        return "Encerrado"
    dias = dias_do_tempo(texto)
    if dias is None:
        return texto  # formato que nao conhecemos: mostra como veio, nunca inventa
    if dias < 0:
        return "data futura"  # DATA da proposta depois de hoje - quase sempre erro de digitacao
    if dias == 0:
        return "hoje"
    return "há 1 dia" if dias == 1 else f"há {dias} dias"


def iniciais_do_nome(nome) -> str:
    """As iniciais que vao no avatar: primeira letra da primeira e da ultima palavra
    ("Maria Exemplo da Silva" -> "MS"); uma palavra so, so a primeira letra
    ("Administrador" -> "A"). Sem nenhuma letra/numero, "?" - nunca um avatar vazio."""
    palavras = [p for p in _texto_limpo(nome).split() if any(c.isalnum() for c in p)]
    letras = [next(c for c in p if c.isalnum()).upper() for p in palavras]
    if not letras:
        return "?"
    return letras[0] if len(letras) == 1 else letras[0] + letras[-1]


def tempo_decorrido_curto(decorrido: timedelta) -> str:
    """"agora" (menos de 1 min), "há 5 min", "há 3 h", "há 2 dias": quanto tempo faz
    que algo aconteceu, pra ler de relance. Tempo negativo (relogio ajustado pra tras)
    conta como "agora"."""
    segundos = decorrido.total_seconds()
    if segundos < 60:
        return "agora"
    minutos = int(segundos // 60)
    if minutos < 60:
        return f"há {minutos} min"
    horas = minutos // 60
    if horas < 24:
        return f"há {horas} h"
    dias = horas // 24
    return "há 1 dia" if dias == 1 else f"há {dias} dias"
