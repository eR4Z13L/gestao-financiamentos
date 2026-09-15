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

from PySide6.QtWidgets import QApplication, QLineEdit

from core.validators import email_valido
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


def main() -> None:
    testar_formatacao_cpf_cnpj()
    testar_formatacao_telefone()
    testar_conectar_mascara()
    testar_email_valido()
    linha("TUDO OK")


if __name__ == "__main__":
    main()
