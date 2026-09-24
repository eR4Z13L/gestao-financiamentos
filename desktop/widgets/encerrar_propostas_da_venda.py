"""Depois de marcar uma proposta como Efetivado, pergunta se as OUTRAS propostas em aberto do
mesmo cliente + equipamento (a mesma venda em bancos diferentes) devem virar "Encerrada". O app
NUNCA decide isso sozinho - so pergunta, com todas pre-marcadas pra agilizar (ver
core.propostas.propostas_em_aberto_da_mesma_venda / encerrar_propostas)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from core import data_store as bd
from core import propostas as propostas_mod
from core.formatting import formatar_reais


def perguntar_e_encerrar(parent: QWidget, cpf: str, equipamento: str, indice_efetivado: int) -> None:
    """Busca as outras propostas em aberto do mesmo cliente+equipamento; se houver alguma, pergunta
    quais encerrar (todas pre-marcadas) e grava so as escolhidas. Sem nenhuma, nao faz nada (nem
    abre dialogo)."""
    try:
        outras = propostas_mod.propostas_em_aberto_da_mesma_venda(cpf, equipamento, indice_efetivado)
    except Exception:
        return  # checagem extra nao pode travar o fluxo normal (a proposta ja foi gravada)
    if outras.empty:
        return

    plural = len(outras) > 1
    dialogo = QDialog(parent)
    dialogo.setWindowTitle("Encerrar as outras propostas desta venda?")
    layout = QVBoxLayout(dialogo)

    aviso = QLabel(
        f"Esta proposta foi efetivada. Há {len(outras)} outra{'s' if plural else ''} "
        f"proposta{'s' if plural else ''} em aberto do mesmo cliente para o mesmo equipamento "
        "(provavelmente a mesma venda em outro banco). Marque as que devem virar \"Encerrada\":"
    )
    aviso.setWordWrap(True)
    layout.addWidget(aviso)

    caixas: dict[int, QCheckBox] = {}
    for indice, linha in outras.iterrows():
        valor = formatar_reais(linha["VALOR (R$)"])
        caixa = QCheckBox(f"{linha['BANCO'] or 'sem banco'} — {linha['STATUS'] or 'sem status'} — {valor}")
        caixa.setChecked(True)
        layout.addWidget(caixa)
        caixas[int(indice)] = caixa

    botoes = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    botoes.button(QDialogButtonBox.StandardButton.Ok).setText("Encerrar as marcadas")
    botoes.button(QDialogButtonBox.StandardButton.Cancel).setText("Não encerrar agora")
    botoes.accepted.connect(dialogo.accept)
    botoes.rejected.connect(dialogo.reject)
    layout.addWidget(botoes)

    if dialogo.exec() != QDialog.DialogCode.Accepted:
        return
    escolhidas = [indice for indice, caixa in caixas.items() if caixa.isChecked()]
    if not escolhidas:
        return
    try:
        propostas_mod.encerrar_propostas(escolhidas)
    except bd.ErroArquivoBloqueado as exc:
        QMessageBox.critical(parent, "Arquivo bloqueado", str(exc))
    except Exception as exc:  # nunca falhar em silencio
        QMessageBox.critical(parent, "Erro inesperado ao encerrar", str(exc))
