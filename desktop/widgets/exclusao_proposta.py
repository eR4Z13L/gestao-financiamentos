"""Excluir uma proposta, com a confirmacao de sempre: o MESMO fluxo em "Todas as Propostas" e no
historico da Ficha de Cliente (as duas telas chamam esta funcao, entao mensagem e tratamento de
erro nunca divergem)."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget

from core import data_store as bd
from core import propostas as propostas_mod
from core.formatting import formatar_reais


def excluir_proposta_com_confirmacao(parent: QWidget, indice_real: int, nome_cliente: str, proposta: dict) -> bool:
    """Pergunta e, se a pessoa confirmar, exclui a proposta na posicao `indice_real` do arquivo.
    `proposta` e como a tela a mostrava: a exclusao so acontece se a linha do arquivo ainda for
    essa (senao os indices andaram e apagaria outra). True se excluiu; qualquer erro e mostrado
    e devolve False."""
    valor_texto = formatar_reais(proposta["VALOR (R$)"])
    resposta = QMessageBox.question(
        parent,
        "Excluir proposta",
        f"Tem certeza que deseja excluir a proposta de '{nome_cliente}' "
        f"({proposta['BANCO'] or 'sem banco'}, {valor_texto})? Essa ação não pode ser desfeita.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    if resposta != QMessageBox.StandardButton.Yes:
        return False

    try:
        propostas_mod.remover_proposta(indice_real, esperado=proposta)
    except propostas_mod.ErroProposta as exc:
        QMessageBox.warning(parent, "Não foi possível excluir", str(exc))
        return False
    except bd.ErroArquivoBloqueado as exc:
        QMessageBox.critical(parent, "Arquivo bloqueado", str(exc))
        return False
    except Exception as exc:  # nunca falhar em silencio
        QMessageBox.critical(parent, "Erro inesperado ao excluir", str(exc))
        return False
    return True
