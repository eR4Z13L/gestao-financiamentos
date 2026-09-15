"""Testa a formatacao "ao vivo" de CPF/CNPJ e telefone, e a validacao de
e-mail. Nao mexe em nenhum arquivo.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_formatters.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import math

import pandas as pd
from PySide6.QtWidgets import QApplication, QLineEdit

from core.formatting import formatar_data, formatar_meses, formatar_reais
from core.validators import email_valido
from desktop.theme import PALETA_ESCURA, TEMA_CLARO, TEMA_ESCURO, build_stylesheet
from desktop.widgets.formatters import conectar_mascara, formatar_cpf_cnpj_parcial, formatar_telefone_parcial


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def testar_formatacao_cpf_cnpj() -> None:
    linha("1) Formatação progressiva de CPF/CNPJ")

    casos = [
        ("1", "1"),
        ("123", "123"),
        ("1234", "123.4"),
        ("123456789", "123.456.789"),
        ("12345678901", "123.456.789-01"),  # 11 digitos = CPF completo
        ("123456789012", "12.345.678/9012"),  # 12 digitos, ja vira padrao CNPJ
        ("12345678901234", "12.345.678/9012-34"),  # 14 digitos = CNPJ completo
    ]
    for digitos, esperado in casos:
        resultado = formatar_cpf_cnpj_parcial(digitos)
        assert resultado == esperado, f"formatar_cpf_cnpj_parcial({digitos!r}) = {resultado!r}, esperado {esperado!r}"
        print(f"  {digitos!r:16} -> {resultado!r}")
    print("OK: CPF (até 11 dígitos) e CNPJ (12+) formatados corretamente, sem pontuação sobrando no final.")


def testar_formatacao_telefone() -> None:
    linha("2) Formatação progressiva de telefone (fixo x celular)")

    casos = [
        ("85", "(85"),
        ("8533334444", "(85) 3333-4444"),  # 10 digitos = fixo
        ("85999998888", "(85) 99999-8888"),  # 11 digitos = celular
    ]
    for digitos, esperado in casos:
        resultado = formatar_telefone_parcial(digitos)
        assert resultado == esperado, f"formatar_telefone_parcial({digitos!r}) = {resultado!r}, esperado {esperado!r}"
        print(f"  {digitos!r:16} -> {resultado!r}")
    print("OK: telefone fixo (10 dígitos) e celular (11) formatados corretamente.")


def testar_conectar_mascara() -> None:
    linha("3) conectar_mascara num QLineEdit de verdade (digitando letra por letra)")

    app = QApplication.instance() or QApplication(sys.argv)
    campo = QLineEdit()
    conectar_mascara(campo, formatar_cpf_cnpj_parcial)

    for caractere in "00603687013280":  # simula digitacao, um caractere por vez
        campo.setText(campo.text() + caractere)

    assert campo.text() == "00.603.687/0132-80", campo.text()
    print(f"  Digitado '00603687013280' um caractere por vez -> '{campo.text()}'")
    print("OK: conectar_mascara reformata em tempo real como esperado.")


def testar_email_valido() -> None:
    linha("4) Validação de e-mail")

    validos = ["fulano@dominio.com", "fulano.silva@dominio.com.br", "a@b.co"]
    invalidos = ["", "fulano", "fulano@", "fulano@dominio", "@dominio.com", "fulano dominio.com"]

    for texto in validos:
        assert email_valido(texto), f"deveria ser valido: {texto!r}"
    print(f"OK: {len(validos)} e-mails válidos aceitos.")

    for texto in invalidos:
        assert not email_valido(texto), f"deveria ser invalido: {texto!r}"
    print(f"OK: {len(invalidos)} e-mails inválidos rejeitados.")


def testar_formatacao_valor_ausente() -> None:
    linha("5) Valor/mês/data ausentes (regressão do bug \"R$ nan\")")

    # bug real encontrado: proposta com VALOR/MESES em branco na planilha
    # mostrava o texto literal "R$ nan" na tela, em vez de "—"
    for valor_ausente in [float("nan"), None, pd.NA]:
        resultado = formatar_reais(valor_ausente)
        assert resultado == "—", f"formatar_reais({valor_ausente!r}) = {resultado!r}, esperado '—'"
    assert "nan" not in formatar_reais(math.nan).lower()
    print("OK: formatar_reais(ausente) -> '—', nunca 'R$ nan'.")

    assert formatar_reais(1234.5) == "R$ 1.234,50"
    print("OK: formatar_reais ainda formata valor normal corretamente (R$ 1.234,50).")

    for meses_ausente in [float("nan"), None, pd.NA]:
        assert formatar_meses(meses_ausente) == "—", f"formatar_meses({meses_ausente!r}) deveria ser '—'"
    assert formatar_meses(36.0) == "36"
    print("OK: formatar_meses(ausente) -> '—', e formatar_meses(36.0) -> '36' (sem casas decimais).")

    assert formatar_data(None) == "—"
    assert formatar_data(pd.NaT) == "—"
    assert formatar_data(pd.Timestamp(2026, 9, 1)) == "01/09/2026"
    print("OK: formatar_data(ausente) -> '—', data válida formatada normalmente.")


def testar_tema_escuro_intocado() -> None:
    linha("6) Ajustes de contraste do tema claro não vazam pro escuro")

    # nenhuma cor da paleta escura pode ter mudado com os ajustes do claro
    esperado = {
        "bg": "#0e1117",
        "bg_secundario": "#171a21",
        "bg_card": "#1c1f2b",
        "borda": "#2b2f3a",
        "texto": "#fafafa",
        "texto_secundario": "#9aa0ac",
        "destaque": "#4f8bf9",
        "destaque_hover": "#3f74d6",
        "sucesso": "#2ecc71",
        "erro": "#ff4b4b",
    }
    for chave, valor in esperado.items():
        assert PALETA_ESCURA[chave] == valor, f"cor '{chave}' do tema escuro mudou: {PALETA_ESCURA[chave]!r}"
    assert PALETA_ESCURA["bg_sidebar"] == PALETA_ESCURA["bg_secundario"], "sidebar do escuro ganhou cor propria sem querer"
    print("OK: nenhuma cor da paleta escura foi alterada pelos ajustes do tema claro.")

    escuro = build_stylesheet(TEMA_ESCURO)
    claro = build_stylesheet(TEMA_CLARO)

    # marcadores que so devem existir no bloco exclusivo do tema claro
    marcadores_exclusivos_do_claro = [
        'QLabel[role="campo_rotulo"] {\n        font-size: 11px;',
        'QLabel[role="campo_valor"] {\n        font-size: 14px;\n        font-weight: 600;',
    ]
    for marcador in marcadores_exclusivos_do_claro:
        assert marcador not in escuro, f"ajuste exclusivo do tema claro vazou pro escuro: {marcador!r}"
        assert marcador in claro, f"ajuste esperado do tema claro nao foi aplicado: {marcador!r}"
    print("OK: os ajustes de hierarquia (botão primário preenchido, rótulo/valor) existem só no tema claro.")


def main() -> None:
    testar_formatacao_cpf_cnpj()
    testar_formatacao_telefone()
    testar_conectar_mascara()
    testar_email_valido()
    testar_formatacao_valor_ausente()
    testar_tema_escuro_intocado()
    linha("TUDO OK")


if __name__ == "__main__":
    main()
