"""Testa desktop/widgets/campo_invalido.py (marcar_invalido/limpar_invalido): marca a
propriedade QSS "invalido" + tooltip com o motivo, e desfaz - sem nenhum arquivo, so a
Qt Application. Também confere que o QSS (desktop/theme.py) tem a regra pros dois tipos
de campo mais comuns (QLineEdit e QComboBox), pros dois temas.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_campo_invalido.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit

from desktop.theme import TEMA_CLARO, TEMA_ESCURO, build_stylesheet
from desktop.widgets.campo_invalido import limpar_invalido, marcar_invalido


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)

    linha("1) marcar_invalido: liga a propriedade e o tooltip")
    campo = QLineEdit()
    assert campo.property("invalido") is None or campo.property("invalido") is False
    marcar_invalido(campo, "CPF inválido - confira os números digitados.")
    assert campo.property("invalido") is True
    assert campo.toolTip() == "CPF inválido - confira os números digitados."
    print("OK: marcar_invalido liga a propriedade 'invalido' e põe o motivo no tooltip.")

    linha("2) limpar_invalido: desliga os dois")
    limpar_invalido(campo)
    assert campo.property("invalido") is False
    assert campo.toolTip() == ""
    print("OK: limpar_invalido desliga a propriedade e limpa o tooltip.")

    linha("3) funciona em QComboBox também (não só QLineEdit)")
    combo = QComboBox()
    marcar_invalido(combo, "Selecione uma opção válida.")
    assert combo.property("invalido") is True and combo.toolTip() == "Selecione uma opção válida."
    limpar_invalido(combo)
    assert combo.property("invalido") is False
    print("OK: marcar_invalido/limpar_invalido funcionam em QComboBox também.")

    linha("4) o QSS tem a regra 'invalido' pra QLineEdit e QComboBox, nos dois temas")
    for tema in (TEMA_ESCURO, TEMA_CLARO):
        folha = build_stylesheet(tema)
        assert 'QLineEdit[invalido="true"]' in folha, f"falta a regra de QLineEdit no tema {tema}"
        assert 'QComboBox[invalido="true"]' in folha, f"falta a regra de QComboBox no tema {tema}"
    print("OK: a folha de estilo tem a borda de erro pra QLineEdit e QComboBox, nos dois temas.")

    linha("TUDO OK")


if __name__ == "__main__":
    main()
