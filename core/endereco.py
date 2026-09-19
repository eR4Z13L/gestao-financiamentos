"""Separa um endereco escrito em texto corrido (o campo unico "ENDERECO" que
existia antes) em CEP / logradouro / numero / complemento / bairro / cidade / UF.

Regra de ouro: NUNCA adivinhar. So devolve uma separacao quando o texto segue
um padrao claro - qualquer duvida devolve None + o motivo, pra a pessoa
revisar na mao. Errar pra "nao separei" custa uma correcao manual; errar pra
"separei errado" gruda dado errado no cadastro sem ninguem perceber.

Padrao aceito (depois de tirar o CEP, se houver, e normalizar espacos):

    LOGRADOURO, NUMERO [COMPLEMENTO] <sep> BAIRRO <sep> CIDADE <sep> UF

- LOGRADOURO: tudo antes da primeira virgula (mantido exatamente como escrito)
- NUMERO: so digitos (com uma letra opcional, ex "45A") ou "SN"/"S/N" - logo
  depois da virgula
- COMPLEMENTO (opcional): um ou mais pares "palavra + identificador" logo
  depois do numero - ex.: "apto 301", "bloco B", "casa 2", "sala 5". Qualquer
  outra forma de complemento (ex.: "C CS APTO C", "apto" sem numero) NAO e
  reconhecida e manda o endereco pra revisao
- BAIRRO e CIDADE: exatamente DOIS blocos entre o complemento e a UF,
  separados por "/", " - " ou ". "
- UF: sigla de estado valida (2 letras maiusculas) no final - sem ela nao da
  pra saber onde a cidade termina (ex.: "Tocantins" por extenso nao serve)

Caixa alta/baixa e grafia sao mantidas como digitadas (nada de "corrigir"
abreviacao ou acento).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

UFS_VALIDAS = frozenset(
    "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split()
)

# "CEP 47809999", "Cep: 60165120", "CEP- 62595-000" ou so o numero solto
_REGEX_CEP = re.compile(r"(?:\bcep\b\s*[:\-]?\s*)?(?<!\d)(\d{5})-?(\d{3})(?!\d)", re.IGNORECASE)

_REGEX_PRIMEIRA_PARTE = re.compile(
    r"^(?P<logradouro>[^,]+?)\s*,\s*(?P<numero>\d+[A-Za-z]?|S/?N)(?![\w/])(?P<resto>.*)$", re.IGNORECASE
)

_PALAVRAS_COMPLEMENTO = (
    r"(?:ap|apt|apto|apartamento|bl|bloco|casa|cs|sala|sl|loja|fundos|lt|lote|qd|quadra|andar|cj|conj|conjunto|"
    r"edif|edificio|edifício|torre|box|km)"
)

# em qualquer ponto do texto: so serve pra detectar "tem complemento, mas num
# formato que eu nao reconheco". Conservador de proposito: "Conjunto Ceara"
# (bairro de verdade) tambem cai aqui e vai pra revisao - custa uma correcao
# manual, nao um dado errado.
_REGEX_COMPLEMENTO_EM_QUALQUER_LUGAR = re.compile(rf"\b{_PALAVRAS_COMPLEMENTO}\b\.?", re.IGNORECASE)

# identificador do complemento: numero (com letra opcional) ou uma letra so
_IDENTIFICADOR = r"(?:\d+[A-Za-z]?|[A-Za-z](?![A-Za-z]))(?!\w)"
_PAR_COMPLEMENTO = rf"\b{_PALAVRAS_COMPLEMENTO}\b\.?\s+{_IDENTIFICADOR}"
# complemento no INICIO do que vem depois do numero: um ou mais pares
# "palavra + identificador" (ex.: "apto 301", "bloco B apto 12")
_REGEX_COMPLEMENTO_INICIAL = re.compile(
    rf"^{_PAR_COMPLEMENTO}(?:\s*[,\-]?\s*{_PAR_COMPLEMENTO})*", re.IGNORECASE
)

# separadores entre blocos: "/", " - " (com espacos) ou ". " (ponto + espaco)
_REGEX_SEPARADOR_BLOCOS = re.compile(r"\s*/\s*|\s+-\s+|\.\s+")
# separador entre a cidade e a UF: "/", "-" ou so espaco
_REGEX_ANTES_DA_UF = re.compile(r"[\s/\-]+([A-Z]{2})$")
_REGEX_PONTUACAO_NAS_PONTAS = re.compile(r"^[\s,.\-/]+|[\s,.\-/]+$")
_REGEX_CIDADE_BARRA_UF = re.compile(r"^(?P<cidade>.+?)\s*/\s*(?P<uf>[A-Z]{2})$")


@dataclass(frozen=True)
class EnderecoSeparado:
    cep: str  # "" se o texto nao trazia CEP (nao e erro)
    logradouro: str
    numero: str
    complemento: str  # "" se nao havia (nao e erro)
    bairro: str
    cidade: str
    uf: str


def _limpar_pontas(texto: str) -> str:
    return _REGEX_PONTUACAO_NAS_PONTAS.sub("", texto)


def separar_cidade_uf(texto: str) -> tuple[str, str]:
    """"Fortaleza/CE" -> ("Fortaleza", "CE"). Se nao terminar em "/UF" com UF
    valida, devolve (texto, "") sem mexer em nada - nunca adivinha um estado."""
    casado = _REGEX_CIDADE_BARRA_UF.match((texto or "").strip())
    if casado and casado.group("uf") in UFS_VALIDAS:
        return casado.group("cidade").strip(), casado.group("uf")
    return (texto or "").strip(), ""


def separar_endereco(texto: str) -> tuple[EnderecoSeparado | None, str]:
    """Devolve (endereco, "") se o texto segue o padrao claro, ou
    (None, motivo) se nao - o motivo e uma frase curta pra mostrar na lista de
    casos pra revisao manual."""
    original = " ".join((texto or "").split())  # colapsa espacos, tabs e quebras de linha
    if not original:
        return None, "endereço vazio"

    ceps = list(_REGEX_CEP.finditer(original))
    if len(ceps) > 1:
        return None, "mais de um CEP no texto"
    cep = ""
    resto = original
    if ceps:
        achado = ceps[0]
        cep = f"{achado.group(1)}-{achado.group(2)}"
        resto = f"{original[:achado.start()]} {original[achado.end():]}"
    resto = " ".join(_limpar_pontas(resto).split())

    casado = _REGEX_PRIMEIRA_PARTE.match(resto)
    if not casado:
        return None, "não tem o padrão 'logradouro, número' (vírgula seguida do número)"

    depois_do_numero = _limpar_pontas(casado.group("resto"))
    achou_uf = _REGEX_ANTES_DA_UF.search(depois_do_numero)
    if not achou_uf or achou_uf.group(1) not in UFS_VALIDAS:
        return None, "não termina com a sigla do estado (UF), então não dá para saber onde a cidade termina"
    uf = achou_uf.group(1)
    miolo = _limpar_pontas(depois_do_numero[: achou_uf.start()])

    complemento = ""
    achou_complemento = _REGEX_COMPLEMENTO_INICIAL.match(miolo)
    if achou_complemento:
        complemento = achou_complemento.group(0).strip()
        miolo = _limpar_pontas(miolo[achou_complemento.end():])
    if _REGEX_COMPLEMENTO_EM_QUALQUER_LUGAR.search(miolo):
        return None, (
            "tem complemento (apto/bloco/casa...) num formato que não reconheço "
            "(esperado algo como 'apto 12' ou 'bloco B' logo depois do número)"
        )

    blocos = [b.strip() for b in _REGEX_SEPARADOR_BLOCOS.split(miolo) if b.strip()]
    if len(blocos) != 2:
        return None, (
            f"entre o número e a UF há {len(blocos)} bloco(s) de texto em vez de 2 (bairro e cidade) "
            "- não dá para separar bairro de cidade com segurança"
        )
    bairro, cidade = blocos

    return (
        EnderecoSeparado(
            cep=cep,
            logradouro=casado.group("logradouro").strip(),
            numero=casado.group("numero").strip(),
            complemento=complemento,
            bairro=bairro,
            cidade=cidade,
            uf=uf,
        ),
        "",
    )
