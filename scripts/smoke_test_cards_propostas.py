"""Testa as cores de cada status (as mesmas no card de proposta, no card da venda e no funil): a cor de cada status
oficial (grafias antigas em CAIXA ALTA incluidas) e o contraste, nos dois temas, do texto da etiqueta e da faixa sobre o
card. (O resto do que este arquivo testava - a lista antiga de cards de Todas as Propostas - saiu com ela no passo 3,
em 05/10/2026; o card de proposta e testado em scripts/smoke_test_todas_as_propostas.py.)

Rodar com: venv/Scripts/python.exe scripts/smoke_test_cards_propostas.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QColor

from core import propostas as propostas_mod
from desktop.theme import CORES_STATUS, PALETAS, TEMA_CLARO, TEMA_ESCURO
from desktop.widgets.lista_cartoes import chave_cor_status


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _luminancia(cor_hex: str) -> float:
    c = QColor(cor_hex)

    def canal(v: float) -> float:
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * canal(c.redF()) + 0.7152 * canal(c.greenF()) + 0.0722 * canal(c.blueF())


def _contraste(a: str, b: str) -> float:
    claro, escuro = sorted((_luminancia(a), _luminancia(b)), reverse=True)
    return (claro + 0.05) / (escuro + 0.05)


def testar_cores() -> None:
    linha("1) Cor de cada status")
    esperado = {
        "Em Análise": "em_analise", "EM ANALISE": "em_analise", "Pré-aprovado": "pre_aprovado", "PRE-APROVADO": "pre_aprovado",
        "Aprovado": "aprovado", "APROVADO": "aprovado", "Nota Fiscal Anexada": "nota_fiscal", "Garantia Assinada": "garantia",
        "Efetivado": "efetivado", "EFETIVADO": "efetivado", "Não efetivado": "nao_efetivado", "NÃO EFETIVADO": "nao_efetivado",
        "Encerrada": "encerrada", "ENCERRADA": "encerrada", "Negado": "negado", "NEGADO": "negado", "Reprovado": "negado",
        "Cancelado": "negado", "": "neutro", "Status Maluco": "neutro",
    }
    for status, chave in esperado.items():
        assert chave_cor_status(status) == chave, (status, chave_cor_status(status))
    for status in propostas_mod.STATUS_OFICIAIS:
        assert chave_cor_status(status) != "neutro", f"status oficial sem cor propria: {status}"
    print("OK: cada status oficial tem cor própria (grafias antigas em CAIXA ALTA incluídas); vazio/desconhecido = cinza.")

    linha("1b) Contraste nos dois temas (WCAG)")
    for tema in (TEMA_ESCURO, TEMA_CLARO):
        cartao = PALETAS[tema]["bg_card"]
        assert set(CORES_STATUS[tema]) == {
            "aprovado", "efetivado", "negado", "em_analise", "pre_aprovado", "nota_fiscal", "garantia",
            "nao_efetivado", "encerrada", "neutro",
        }
        for chave, cor in CORES_STATUS[tema].items():
            texto_na_pilula = _contraste(cor["texto"], cor["fundo"])
            faixa_no_card = _contraste(cor["faixa"], cartao)
            assert texto_na_pilula >= 4.5, f"{tema}/{chave}: texto da pílula {texto_na_pilula:.2f} < 4.5"
            assert faixa_no_card >= 3.0, f"{tema}/{chave}: faixa sobre o card {faixa_no_card:.2f} < 3"
        faixas = {k: v["faixa"] for k, v in CORES_STATUS[tema].items() if k not in ("efetivado", "neutro")}
        assert len(set(faixas.values())) == len(faixas), f"{tema}: etapas diferentes precisam de cores diferentes"
        assert CORES_STATUS[tema]["aprovado"]["faixa"] == CORES_STATUS[tema]["efetivado"]["faixa"], "Aprovado e Efetivado: os dois verdes"
        assert CORES_STATUS[tema]["efetivado"]["fundo"] != CORES_STATUS[tema]["aprovado"]["fundo"], "Efetivado tem a pílula preenchida"
    print("OK: texto da pílula ≥ 4,5:1 e faixa sobre o card ≥ 3:1 em todas as 8 cores, no escuro e no claro; "
          "Aprovado/Efetivado verdes (Efetivado com pílula preenchida) e as demais etapas com cores distintas.")


def main() -> None:
    testar_cores()
    linha("TUDO OK")


if __name__ == "__main__":
    main()
