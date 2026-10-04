"""Perguntas sobre a venda que qualquer tela que grava uma proposta faz igual (a tela Vendas, o formulario da
proposta na Ficha e em Todas as Propostas): o app sugere, a pessoa decide."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget

from core import data_store as bd
from core import sessao as sessao_mod
from core import vendas as vendas_mod


def perguntar_se_perdida(parent: QWidget | None, id_venda: str, nome: str) -> bool:
    """Depois que a ultima proposta da venda foi negada: marcar a venda como Perdida? True se marcou."""
    resposta = QMessageBox.question(
        parent, "Todos os bancos negaram",
        f"Todos os bancos da venda de {nome} negaram. Marcar a venda como Perdida (motivo: Todos os bancos negaram)?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
    )
    if resposta != QMessageBox.StandardButton.Yes:
        return False
    try:
        vendas_mod.mudar_status_venda(id_venda, vendas_mod.VENDA_PERDIDA, motivo="Todos os bancos negaram")
    except (vendas_mod.ErroVenda, sessao_mod.PermissaoNegada) as exc:
        QMessageBox.warning(parent, "Não foi possível marcar como Perdida", str(exc))
        return False
    except bd.ErroArquivoBloqueado as exc:
        QMessageBox.critical(parent, "Arquivo bloqueado", str(exc))
        return False
    except Exception as exc:  # nunca falhar em silencio
        QMessageBox.critical(parent, "Erro inesperado ao marcar como Perdida", f"{type(exc).__name__}: {exc}")
        return False
    return True
