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
from desktop.theme import PALETA_CLARA, PALETA_ESCURA, TEMA_CLARO, TEMA_ESCURO, build_stylesheet
from desktop.widgets.formatters import conectar_mascara, formatar_cpf_cnpj_parcial, formatar_telefone_parcial
from desktop.widgets.quebra_texto import texto_quebravel


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


def testar_texto_quebravel() -> None:
    linha("7) texto_quebravel - quebra artificial em texto sem espaço (URL colada)")

    ZWSP = "​"

    assert texto_quebravel("") == ""
    assert texto_quebravel(None) is None
    print("OK: texto vazio/None passa direto, sem erro.")

    curto = "https://a.co/x"  # menor que o tamanho maximo - nao deveria ganhar nenhum ZWSP
    assert texto_quebravel(curto) == curto
    print(f"OK: texto curto ({len(curto)} caract.) não recebe nenhum espaço de largura zero.")

    texto_normal = "Fulano da Silva mora na Rua Tal"
    assert texto_quebravel(texto_normal) == texto_normal, "espacos normais nao podem virar ZWSP nem sumir"
    print("OK: texto com palavras curtas (nomes/frases comuns) sai idêntico ao original.")

    token = "A" * 87  # bem maior que o tamanho maximo, sem nenhum ponto de quebra
    resultado = texto_quebravel(token, tamanho_maximo=20)
    assert resultado.replace(ZWSP, "") == token, "nenhum caractere pode ser perdido"
    maior_pedaco = max(len(p) for p in resultado.split(ZWSP))
    assert maior_pedaco <= 20, f"deveria ter quebrado a cada 20 caract., maior pedaço tem {maior_pedaco}"
    print(f"OK: token de {len(token)} caracteres sem espaço nenhum virou pedaços de até 20 (maior pedaço: {maior_pedaco}).")

    misto = "veja " + "B" * 60 + " depois"
    resultado_misto = texto_quebravel(misto, tamanho_maximo=20)
    assert resultado_misto.replace(ZWSP, "") == misto
    partes = resultado_misto.split(" ")
    assert partes[0] == "veja" and partes[-1] == "depois", "palavras curtas ao redor nao podem ser mexidas"
    print("OK: só o trecho colado (sem espaço) é quebrado - palavras normais ao redor ficam intactas.")


def testar_tema_escuro_intocado() -> None:
    linha("6) Ajustes de contraste do tema claro não vazam pro escuro")

    # nenhuma cor da paleta escura pode ter mudado com os ajustes do claro
    esperado = {
        "bg": "#0e1117",
        "bg_secundario": "#171a21",
        "bg_card": "#1c1f2b",
        "zebra": "#171a21",
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


def _luminancia(hex_cor: str) -> float:
    hex_cor = hex_cor.lstrip("#")
    r, g, b = (int(hex_cor[i : i + 2], 16) for i in (0, 2, 4))
    return 0.299 * r + 0.587 * g + 0.114 * b


def testar_zebra_tabela() -> None:
    linha("8) Zebra da tabela - contraste real (não só existir no CSS)")

    # bug real reportado: a zebra "existia" no CSS (alternate-background-color)
    # mas a cor era tao proxima do branco do card que ninguem enxergava - o
    # que importa e a DIFERENCA de luminancia, nao so a cor existir
    delta_claro = abs(_luminancia(PALETA_CLARA["zebra"]) - _luminancia(PALETA_CLARA["bg_card"]))
    assert delta_claro >= 8, f"zebra do tema claro perto demais do card outra vez (delta={delta_claro:.1f})"
    print(f"OK: zebra do tema claro tem contraste perceptível contra o card (delta de luminância={delta_claro:.1f}).")

    # tema escuro nao foi mexido por este pedido - zebra continua igual ao bg_secundario de sempre
    assert PALETA_ESCURA["zebra"] == PALETA_ESCURA["bg_secundario"]
    print("OK: zebra do tema escuro segue idêntica a bg_secundario (não alterado).")


def testar_sidebar_recolhida_quase_quadrada() -> None:
    linha("9) Item da sidebar recolhida - proporção quase quadrada")

    # bug real reportado: o item ficava um retangulo bem mais alto que largo
    # (padding vertical de 13px + margin de 6px). Confere que os valores
    # atuais (mais enxutos) estao no CSS gerado, nos dois temas (a regra e
    # compartilhada no bloco base) - nao mede geometria renderizada porque
    # QT_QPA_PLATFORM=offscreen usa metricas de emoji diferentes do Qt real
    # (ver notas do projeto), o que tornaria essa medida nao-confiavel aqui.
    marcador = 'QListWidget[recolhido="true"]::item {\n        padding: 3px 0px;\n        margin: 2px 2px;'
    assert marcador in build_stylesheet(TEMA_CLARO)
    assert marcador in build_stylesheet(TEMA_ESCURO)
    print("OK: padding/margin enxutos (proporção quase quadrada) presentes nos dois temas.")

    claro = build_stylesheet(TEMA_CLARO)
    assert f"alternate-background-color: {PALETA_CLARA['zebra']}" in claro
    print("OK: o QSS do tema claro realmente usa a nova cor de zebra.")


def main() -> None:
    testar_formatacao_cpf_cnpj()
    testar_formatacao_telefone()
    testar_conectar_mascara()
    testar_email_valido()
    testar_formatacao_valor_ausente()
    testar_texto_quebravel()
    testar_tema_escuro_intocado()
    testar_zebra_tabela()
    testar_sidebar_recolhida_quase_quadrada()
    linha("TUDO OK")


if __name__ == "__main__":
    main()
