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
    for nome, senha_hash, ativo in zip(df["NOME"], df["SENHA_HASH"], df["ATIVO"]):
        if not nome:
            continue
        senha = "senha definida" if senha_hash else "senha pendente"
        itens.append(ItemDoCadastro(
            chave=nome, titulo=nome, detalhe=f"{_quantos(carteiras.get(nome.strip().upper(), 0))} · {senha}",
            ativo=vendedores_mod.esta_ativo(ativo), valores={"nome": nome},
        ))
    return sorted(itens, key=lambda i: i.titulo.upper())


def _adicionar(valores: dict) -> str:
    nome = vendedores_mod.adicionar_vendedor(valores["nome"])
    senha = vendedores_mod.gerar_senhas_iniciais_pendentes().get(nome)
    if not senha:
        return f"'{nome}' já estava cadastrado - nada mudou."
    return (f"'{nome}' cadastrado. Senha inicial de acesso: {senha}\n\n"
            "Anote ou avise agora: essa senha não pode ser recuperada depois (só redefinida).")


def _salvar(nome: str, valores: dict) -> str:
    novo = vendedores_mod.renomear_vendedor(nome, valores["nome"])
    return f"'{nome}' agora é '{novo}' (os clientes dele já estão com o nome novo)."


def _definir_ativo(nome: str, ativo: bool) -> str:
    if ativo:
        vendedores_mod.reativar_vendedor(nome)
        return f"'{nome}' voltou a aparecer para escolher nos cadastros."
    vendedores_mod.desativar_vendedor(nome)
    return f"'{nome}' não aparece mais para escolher nos cadastros novos."


def _redefinir_senha(item: ItemDoCadastro, parent: QWidget) -> str | None:
    resposta = QMessageBox.question(
        parent, "Redefinir senha", f"Gerar uma nova senha para '{item.titulo}'? A senha atual deixa de funcionar.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
    )
    if resposta != QMessageBox.StandardButton.Yes:
        return None
    senha = vendedores_mod.redefinir_senha(item.chave)
    return (f"Nova senha para '{item.titulo}': {senha}\n\n"
            "Anote ou avise agora: essa senha não pode ser recuperada depois (só redefinida de novo).")


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
            "pontinhos: redefinir a senha, transferir a carteira e desativar (só com a carteira vazia)."
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
        acoes_extras=[AcaoExtra("Redefinir senha", _redefinir_senha), AcaoExtra("Transferir carteira", _transferir_carteira)],
    )


class CadastroVendedores(CadastroEmCards):
    def __init__(self, parent: QWidget | None = None, *, dentro_de_pagina: bool = False):
        super().__init__(definicao_vendedores(), parent, dentro_de_pagina=dentro_de_pagina)
