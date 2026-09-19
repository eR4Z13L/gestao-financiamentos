"""Sessao do usuario logado (ADMIN ou VENDEDOR) - um singleton em memoria,
valido so durante a execucao do app (nunca persistido em disco).

Toda funcao de escrita das camadas de negocio (core/clientes.py,
core/propostas.py, core/equipamentos.py, core/vendedores.py) comeca chamando
exigir_admin(). Isso bloqueia a escrita de verdade - nao e so a tela
escondendo o botao - mesmo que alguem chame a funcao por fora do fluxo
normal da interface (ex: um script, ou uma versao adulterada da tela).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

PAPEL_ADMIN = "ADMIN"
PAPEL_VENDEDOR = "VENDEDOR"


@dataclass(frozen=True)
class Sessao:
    papel: str
    nome_usuario: str  # "Administrador" pro admin, ou o nome do vendedor logado


class PermissaoNegada(Exception):
    """A acao exige o papel ADMIN - o usuario logado nao tem essa permissao."""


_sessao_atual: Sessao | None = None


def iniciar(sessao: Sessao) -> None:
    global _sessao_atual
    _sessao_atual = sessao


def encerrar() -> None:
    global _sessao_atual
    _sessao_atual = None


def atual() -> Sessao | None:
    return _sessao_atual


def eh_admin() -> bool:
    return _sessao_atual is not None and _sessao_atual.papel == PAPEL_ADMIN


def eh_vendedor() -> bool:
    return _sessao_atual is not None and _sessao_atual.papel == PAPEL_VENDEDOR


def exigir_admin() -> None:
    if not eh_admin():
        raise PermissaoNegada("Esta ação está disponível apenas para o Administrador.")


def filtrar_por_vendedor_logado(df: pd.DataFrame, coluna_vendedor: str = "VENDEDOR") -> pd.DataFrame:
    """Se quem esta logado e um VENDEDOR, devolve so as linhas daquele
    vendedor (comparando sem diferenciar maiusculas/minusculas); se for
    ADMIN (ou ninguem logado ainda), devolve `df` sem alterar."""
    if not eh_vendedor():
        return df
    nome = _sessao_atual.nome_usuario.strip().upper()
    return df[df[coluna_vendedor].str.strip().str.upper() == nome]
