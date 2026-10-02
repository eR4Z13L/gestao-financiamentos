"""Cadastro de Bancos da aba Cadastros (Administracao): a lista fechada do campo Banco das propostas.
As regras ficam em core/bancos.py; a tela e a peca de cadastro em cards (desktop/widgets/cadastro_em_cards.py)."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from core import bancos as bancos_mod
from desktop.widgets.cadastro_em_cards import CadastroEmCards, Campo, DefinicaoDoCadastro, ItemDoCadastro


def _quantas(propostas: int) -> str:
    return "Nenhuma proposta" if not propostas else f"{propostas} proposta" + ("" if propostas == 1 else "s")


def _listar() -> list[ItemDoCadastro]:
    df = bancos_mod.listar_bancos()
    return [
        ItemDoCadastro(chave=nome, titulo=nome, detalhe=_quantas(int(propostas)), ativo=bool(ativo), valores={"nome": nome})
        for nome, ativo, propostas in zip(df["NOME"], df["ATIVO"], df["PROPOSTAS"])
    ]


def _adicionar(valores: dict) -> str:
    nome = bancos_mod.adicionar_banco(valores["nome"])
    return f"'{nome}' já aparece na lista do formulário de proposta."


def _salvar(nome: str, valores: dict) -> str:
    novo = valores["nome"]
    quantidade = bancos_mod.renomear_banco(nome, novo)
    extra = f" {quantidade} proposta(s) também foram atualizadas." if quantidade else ""
    return f"'{nome}' agora é '{' '.join(novo.split())}'.{extra}"


def _definir_ativo(nome: str, ativo: bool) -> str:
    if ativo:
        bancos_mod.reativar_banco(nome)
        return f"'{nome}' voltou para a lista do formulário."
    bancos_mod.desativar_banco(nome)
    return f"'{nome}' não aparece mais na lista do formulário."


def _excluir(nome: str) -> str:
    bancos_mod.excluir_banco(nome)
    return f"'{nome}' foi apagado do cadastro."


def definicao_bancos() -> DefinicaoDoCadastro:
    return DefinicaoDoCadastro(
        titulo="Bancos",
        nome_do_item="banco",
        explicacao=(
            "A lista do campo Banco das propostas. O lápis renomeia (as propostas também mudam); os três pontinhos "
            "desativam (sai da lista, as propostas antigas ficam como estão) ou excluem. "
            f"\"{bancos_mod.BANCO_TODOS}\" (enviada a todos os bancos) é uma opção fixa do formulário."
        ),
        campos=[Campo("nome", "Nome", obrigatorio=True, dica="Ex.: Banco do Brasil")],
        listar=_listar,
        adicionar=_adicionar,
        salvar=_salvar,
        definir_ativo=_definir_ativo,
        excluir=_excluir,
        erros_esperados=(bancos_mod.ErroBanco,),
        pergunta_ao_desativar=lambda item: (
            f"Desativar '{item.titulo}'? Ele sai da lista do formulário de proposta; as propostas antigas continuam com ele."
        ),
    )


class CadastroBancos(CadastroEmCards):
    def __init__(self, parent: QWidget | None = None, *, dentro_de_pagina: bool = False):
        super().__init__(definicao_bancos(), parent, dentro_de_pagina=dentro_de_pagina)
