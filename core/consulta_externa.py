"""Consulta de CEP (ViaCEP) e de CNPJ (BrasilAPI) para preencher o cadastro do cliente.

So sai do PC o que e preciso: o CEP (8 digitos) ou o CNPJ (14 digitos, valido). CPF (11 digitos) NUNCA e enviado.
Toda falha vira ErroConsultaExterna com texto claro - nunca falha em silencio. O HTTP acontece num ponto so
(`_http_get`), que os testes trocam por uma resposta simulada.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request

from core.validators import apenas_digitos, cnpj_valido

TIMEOUT_S = 5
_URL_CEP = "https://viacep.com.br/ws/{cep}/json/"
_URL_CNPJ = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"


class ErroConsultaExterna(Exception):
    """A consulta nao deu certo; o texto explica o motivo em linguagem de usuario."""


def _http_get(url: str, timeout: float) -> bytes:
    """O unico lugar que fala com a internet. Levanta os erros crus do urllib/socket (quem traduz e _buscar_json)."""
    pedido = urllib.request.Request(url, headers={"User-Agent": "GestaoFinanciamentos", "Accept": "application/json"})
    with urllib.request.urlopen(pedido, timeout=timeout) as resposta:
        return resposta.read()


def _buscar_json(url: str, o_que: str, nao_encontrado: tuple[int, ...]) -> object:
    """Faz o GET e devolve o JSON. `o_que` ("CEP"/"CNPJ") entra nas mensagens; `nao_encontrado`: codigos HTTP que
    significam "nao existe"."""
    try:
        corpo = _http_get(url, TIMEOUT_S)
    except urllib.error.HTTPError as exc:
        if exc.code in nao_encontrado:
            raise ErroConsultaExterna(f"{o_que} não encontrado.") from exc
        if exc.code == 429:
            raise ErroConsultaExterna(
                f"Muitas consultas seguidas ao serviço de {o_que}. Aguarde um minuto e tente de novo."
            ) from exc
        raise ErroConsultaExterna(f"O serviço de consulta de {o_que} respondeu com erro (código {exc.code}).") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise ErroConsultaExterna(
            f"O serviço de consulta de {o_que} demorou demais para responder (mais de {TIMEOUT_S} segundos)."
        ) from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            raise ErroConsultaExterna(
                f"O serviço de consulta de {o_que} demorou demais para responder (mais de {TIMEOUT_S} segundos)."
            ) from exc
        raise ErroConsultaExterna(
            f"Não foi possível consultar o {o_que}: sem conexão com a internet ({exc.reason})."
        ) from exc
    except OSError as exc:
        raise ErroConsultaExterna(f"Não foi possível consultar o {o_que}: falha de conexão ({exc}).") from exc
    try:
        return json.loads(corpo.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ErroConsultaExterna(f"O serviço de consulta de {o_que} devolveu uma resposta que não deu para entender.") from exc


def _texto(dados: dict, chave: str, o_que: str) -> str:
    valor = dados.get(chave)
    if valor is None:
        return ""
    if isinstance(valor, bool) or not isinstance(valor, (str, int)):
        raise ErroConsultaExterna(f"A resposta do serviço de {o_que} veio com o campo \"{chave}\" num formato inesperado.")
    return str(valor).strip()


def consultar_cep(cep: str) -> dict[str, str]:
    """Endereco do CEP: logradouro, complemento, bairro, cidade, uf (campo que a ViaCEP nao traz fica "")."""
    digitos = apenas_digitos(cep)
    if len(digitos) != 8:
        raise ErroConsultaExterna("O CEP precisa ter 8 números para ser consultado.")
    dados = _buscar_json(_URL_CEP.format(cep=digitos), "CEP", nao_encontrado=(400, 404))
    if not isinstance(dados, dict):
        raise ErroConsultaExterna("O serviço de consulta de CEP devolveu uma resposta que não deu para entender.")
    if dados.get("erro") in (True, "true"):
        raise ErroConsultaExterna("CEP não encontrado.")
    if "localidade" not in dados:
        raise ErroConsultaExterna("O serviço de consulta de CEP devolveu uma resposta que não deu para entender.")
    return {
        "logradouro": _texto(dados, "logradouro", "CEP"),
        "complemento": _texto(dados, "complemento", "CEP"),
        "bairro": _texto(dados, "bairro", "CEP"),
        "cidade": _texto(dados, "localidade", "CEP"),
        "uf": _texto(dados, "uf", "CEP").upper(),
    }


def consultar_cnpj(cnpj: str) -> dict[str, str]:
    """Dados do CNPJ: razao_social, logradouro, numero, complemento, bairro, cidade, uf, cep (so digitos)."""
    digitos = apenas_digitos(cnpj)
    if len(digitos) != 14:
        raise ErroConsultaExterna("A consulta vale só para CNPJ (14 números); o CPF não é consultado.")
    if not cnpj_valido(digitos):
        raise ErroConsultaExterna("CNPJ inválido - confira os números digitados.")
    dados = _buscar_json(_URL_CNPJ.format(cnpj=digitos), "CNPJ", nao_encontrado=(400, 404))
    if not isinstance(dados, dict) or not _texto(dados, "razao_social", "CNPJ"):
        raise ErroConsultaExterna("O serviço de consulta de CNPJ devolveu uma resposta que não deu para entender.")
    tipo = _texto(dados, "descricao_tipo_de_logradouro", "CNPJ")
    logradouro = _texto(dados, "logradouro", "CNPJ")
    # a BrasilAPI traz o tipo ("AVENIDA") separado do nome; junta, sem repetir se ele ja vier no nome
    if tipo and logradouro and not logradouro.upper().startswith(tipo.upper()):
        logradouro = f"{tipo} {logradouro}"
    return {
        "razao_social": _texto(dados, "razao_social", "CNPJ"),
        "logradouro": logradouro,
        "numero": _texto(dados, "numero", "CNPJ"),
        "complemento": _texto(dados, "complemento", "CNPJ"),
        "bairro": _texto(dados, "bairro", "CNPJ"),
        "cidade": _texto(dados, "municipio", "CNPJ"),
        "uf": _texto(dados, "uf", "CNPJ").upper(),
        "cep": apenas_digitos(_texto(dados, "cep", "CNPJ")),
    }


def _normalizado(chave: str, valor: str) -> str:
    if chave == "cep":
        return apenas_digitos(valor)
    return " ".join((valor or "").split()).casefold()


def separar_preenchimentos(atuais: dict[str, str], novos: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """Decide o que fazer com cada valor consultado, sem sobrescrever o que o usuario digitou.
    Devolve (para_preencher, para_perguntar): o primeiro e o que cai em campo vazio (entra direto); o segundo, o que
    tem texto diferente no campo (o usuario decide). Valor consultado vazio, ou igual ao do campo, e ignorado."""
    para_preencher: dict[str, str] = {}
    para_perguntar: dict[str, str] = {}
    for chave, novo in novos.items():
        if not (novo or "").strip():
            continue
        atual = (atuais.get(chave) or "").strip()
        if not atual:
            para_preencher[chave] = novo
        elif _normalizado(chave, atual) != _normalizado(chave, novo):
            para_perguntar[chave] = novo
    return para_preencher, para_perguntar
