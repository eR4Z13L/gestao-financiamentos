"""Cadastro de Vendedores da tela Cadastros. As regras ficam em core/vendedores.py; a tela e a peca de cadastro
em cards (desktop/widgets/cadastro_em_cards.py). O vendedor nunca e excluido (o historico aponta pra ele): sai
de cena desativado, e so com a carteira vazia (Transferir carteira antes)."""

from __future__ import annotations

from PySide6.QtWidgets import QInputDialog, QMessageBox, QWidget

from core import vendedores as vendedores_mod
from desktop.widgets.cadastro_em_cards import AcaoExtra, CadastroEmCards, Campo, DefinicaoDoCadastro, ItemDoCadastro


def _quantos(clientes: int) -> str:
    return "Nenhum cliente" if not clientes else f"{clientes} cliente" + ("" if clientes == 1 else "s")


def _listar() -> list[ItemDoCadastro]:
    df = vendedores_mod.listar_vendedores_detalhado()
    carteiras = vendedores_mod.carteiras()
    itens = []
    for nome, ativo in zip(df["NOME"], df["ATIVO"]):
        if not nome:
            continue
        itens.append(ItemDoCadastro(
            chave=nome, titulo=nome, detalhe=_quantos(carteiras.get(nome.strip().upper(), 0)),
            ativo=vendedores_mod.esta_ativo(ativo), valores={"nome": nome},
        ))
    return sorted(itens, key=lambda i: i.titulo.upper())


def _adicionar(valores: dict) -> str:
    ja_cadastrados = {n.strip().upper() for n in vendedores_mod.listar_vendedores_detalhado()["NOME"] if n}
    nome = vendedores_mod.adicionar_vendedor(valores["nome"])
    if nome.strip().upper() in ja_cadastrados:
        return f"'{nome}' já estava cadastrado - nada mudou."
    return f"'{nome}' cadastrado."


def _salvar(nome: str, valores: dict) -> str:
    novo = vendedores_mod.renomear_vendedor(nome, valores["nome"])
    return f"'{nome}' agora é '{novo}' (os clientes dele já estão com o nome novo)."


def _definir_ativo(nome: str, ativo: bool) -> str:
    if ativo:
        vendedores_mod.reativar_vendedor(nome)
        return f"'{nome}' voltou a aparecer para escolher nos cadastros."
    vendedores_mod.desativar_vendedor(nome)
    return f"'{nome}' não aparece mais para escolher nos cadastros novos."


def _transferir_carteira(item: ItemDoCadastro, parent: QWidget) -> str | None:
    candidatos = [n for n in vendedores_mod.listar_vendedores_ativos() if n.upper() != item.chave.upper()]
    if not candidatos:
        QMessageBox.information(parent, "Sem destino disponível", "Não há outro vendedor ativo para receber a carteira.")
        return None
    destino, ok = QInputDialog.getItem(
        parent, "Transferir carteira", f"Passar os clientes de '{item.titulo}' para:", candidatos, 0, False
    )
    if not ok:
        return None
    quantidade = vendedores_mod.transferir_carteira(item.chave, destino)
    if not quantidade:
        return f"'{item.titulo}' não tinha nenhum cliente - nada para transferir."
    return f"{quantidade} cliente(s) de '{item.titulo}' agora estão com '{destino}'."


def definicao_vendedores() -> DefinicaoDoCadastro:
    return DefinicaoDoCadastro(
        titulo="Vendedores",
        nome_do_item="vendedor",
        explicacao=(
            "Quem vendeu o quê (clientes e propostas). O lápis renomeia (os clientes também mudam); nos três "
            "pontinhos: transferir a carteira e desativar (só com a carteira vazia)."
        ),
        campos=[Campo("nome", "Nome", obrigatorio=True, dica="Ex.: Maria Silva")],
        listar=_listar,
        adicionar=_adicionar,
        salvar=_salvar,
        definir_ativo=_definir_ativo,
        erros_esperados=(vendedores_mod.ErroVendedor,),
        pergunta_ao_desativar=lambda item: (
            f"Desativar '{item.titulo}'? Ele(a) deixa de aparecer para escolher em cadastros novos; o histórico "
            "continua intacto."
        ),
        acoes_extras=[AcaoExtra("Transferir carteira", _transferir_carteira)],
    )


class CadastroVendedores(CadastroEmCards):
    def __init__(self, parent: QWidget | None = None, *, dentro_de_pagina: bool = False):
        super().__init__(definicao_vendedores(), parent, dentro_de_pagina=dentro_de_pagina)
