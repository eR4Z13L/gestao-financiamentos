"""Testa os filtros (vendedor, banco, equipamento, periodo) e a ordenacao (data,
valor, tempo parado) de "Todas as Propostas": as regras em core/propostas.py e a
tela PropostasScreen, combinados com a busca e o filtro de status que ja existiam.
Dados FICTICIOS, em memoria (nenhuma planilha).

Rodar com: venv/Scripts/python.exe scripts/smoke_test_filtros_propostas.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from PySide6.QtWidgets import QApplication, QComboBox, QMessageBox, QStyleFactory

import config
config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import vendedores as vendedores_mod
from core.propostas import (
    ORDENACAO_DATA_ANTIGA,
    ORDENACAO_DATA_RECENTE,
    ORDENACAO_OPCOES,
    ORDENACAO_TEMPO_PARADO,
    ORDENACAO_VALOR_MAIOR,
    ORDENACAO_VALOR_MENOR,
    filtrar_propostas,
    ordenar,
    valores_distintos,
)
from desktop.screens.propostas_screen import PropostasScreen
from desktop.theme import TEMA_ESCURO, build_stylesheet

NAN = float("nan")
COLUNAS = ["DATA", "VENDEDOR", "CLIENTE", "CPF", "EQUIPAMENTO", "BANCO", "VALOR (R$)", "MESES", "STATUS", "TEMPO", "OBSERVAÇÕES"]

# (cliente, vendedor, equipamento, banco, valor, status, data, tempo) - a POSICAO na lista e o
# indice real da proposta no arquivo. Casos de proposito: 0 e 1 iguais em tudo menos o banco;
# 2 e 3 com o mesmo banco escrito de dois jeitos; 6 sem data, valor, status e tempo; 10 no futuro.
PROPOSTAS = [
    ("ANA A", "ANA", "LASER", "SANTANDER", 50000.0, "Em Análise", pd.Timestamp(2026, 9, 10), "9 dias"),
    ("ANA A", "ANA", "LASER", "PORTOBANK", 50000.0, "Em Análise", pd.Timestamp(2026, 9, 10), "9 dias"),
    ("BIA B", "BIA", "MESA", "Hubcred BV", 20000.0, "Aprovado", pd.Timestamp(2026, 9, 1), "18 dias"),
    ("CAI C", "BIA", "LASER", "HUBCRED BV", 75000.0, "Efetivado", pd.Timestamp(2026, 8, 15), "Encerrado"),
    ("DAN D", "ANA", "BISTURI", "SMART", NAN, "Negado", pd.Timestamp(2026, 8, 20), "Encerrado"),
    ("EVA E", "BIA", "MESA", "SMART", 20000.0, "Em Análise", pd.Timestamp(2026, 9, 5), "14 dias"),
    ("FLA F", "ANA", "", "", NAN, "", pd.NaT, ""),
    ("GIO G", "BIA", "LASER", "SANTANDER", 100.0, "Em Análise", pd.Timestamp(2026, 9, 18), "1 dias"),
    ("HEL H", "ANA", "LASER", "SANTANDER", 75000.0, "Negado", pd.Timestamp(2026, 7, 1), "Encerrado"),
    ("IVO I", "BIA", "PTOLOMEU", "PORTOBANK", 5000.0, "Aprovado", pd.Timestamp(2026, 9, 19), "0 dias"),
    ("JOA J", "ANA", "MESA", "SANTANDER", 30000.0, "Em Análise", pd.Timestamp(2026, 9, 25), "-6 dias"),
]


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _df(propostas=PROPOSTAS) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"DATA": data, "VENDEDOR": vendedor, "CLIENTE": cliente, "CPF": f"{i:011d}", "EQUIPAMENTO": equip, "BANCO": banco,
             "VALOR (R$)": valor, "MESES": 12, "STATUS": status, "TEMPO": tempo, "OBSERVAÇÕES": ""}
            for i, (cliente, vendedor, equip, banco, valor, status, data, tempo) in enumerate(propostas)
        ]
    )


def _indices(df: pd.DataFrame) -> list[int]:
    return [int(i) for i in df.index]


# ---------------------------------------------------------------------------
# regras (core)

def testar_ordenacao() -> None:
    linha("1) Ordenação (core.propostas.ordenar)")
    df = _df()
    esperado = {
        # mais recente primeiro; empate de data: cadastrada por ultimo (1 antes de 0); sem data no fim
        ORDENACAO_DATA_RECENTE: [10, 9, 7, 1, 0, 5, 2, 4, 3, 8, 6],
        # o inverso, mas quem nao tem data continua no fim
        ORDENACAO_DATA_ANTIGA: [8, 3, 4, 2, 5, 0, 1, 7, 9, 10, 6],
        # maior valor primeiro; empate de valor: data mais recente; sem valor (4 e 6) no fim
        ORDENACAO_VALOR_MAIOR: [3, 8, 1, 0, 10, 5, 2, 9, 7, 4, 6],
        ORDENACAO_VALOR_MENOR: [7, 9, 5, 2, 10, 1, 0, 3, 8, 4, 6],
        # mais dias em aberto primeiro (18, 14, 9, 9, 1, 0, -6); depois os Encerrado (mais recente
        # primeiro); por ultimo quem nao tem TEMPO
        ORDENACAO_TEMPO_PARADO: [2, 5, 1, 0, 7, 9, 10, 4, 3, 8, 6],
    }
    assert {chave for chave, _ in ORDENACAO_OPCOES} == set(esperado), "toda opção do seletor tem teste"
    for chave, ordem in esperado.items():
        resultado = ordenar(df, chave)
        assert _indices(resultado) == ordem, f"{chave}: {_indices(resultado)} != {ordem}"
    assert list(ordenar(df, ORDENACAO_TEMPO_PARADO).columns) == COLUNAS, "nenhuma coluna auxiliar vaza pro resultado"
    assert _indices(df) == list(range(11)), "o DataFrame original não é reordenado"
    print("OK: data (recente/antiga), valor (maior/menor) e tempo parado, com empates, sem dado no fim, "
          "'Encerrado' depois de quem tem dias em aberto; o índice (posição no arquivo) fica intacto.")

    try:
        ordenar(df, "qualquer_coisa")
        raise SystemExit("deveria ter recusado uma ordenação desconhecida")
    except ValueError as exc:
        print(f"OK: ordenação desconhecida é recusada -> {exc}")

    vazio = pd.DataFrame(columns=COLUNAS)
    for chave, _ in ORDENACAO_OPCOES:
        assert ordenar(vazio, chave).empty
    print("OK: sem nenhuma proposta, todas as ordenações devolvem vazio (sem erro).")


def testar_filtros() -> None:
    linha("2) Filtros (core.propostas.filtrar_propostas)")
    df = _df()
    todos = _indices(filtrar_propostas(df))
    assert todos == [10, 9, 7, 1, 0, 5, 2, 4, 3, 8, 6], "sem filtro: tudo, da mais recente à mais antiga"

    assert _indices(filtrar_propostas(df, vendedor="ana")) == [10, 1, 0, 4, 8, 6], "vendedor sem diferenciar maiúsculas"
    assert _indices(filtrar_propostas(df, banco="hubcred bv")) == [2, 3], "'Hubcred BV' e 'HUBCRED BV' são o mesmo banco"
    assert _indices(filtrar_propostas(df, banco="SANTANDER")) == [10, 7, 0, 8]
    assert _indices(filtrar_propostas(df, equipamento="laser")) == [7, 1, 0, 3, 8]
    assert _indices(filtrar_propostas(df, equipamento="LAS")) == [], "equipamento é igualdade, não 'contém'"
    assert _indices(filtrar_propostas(df, status="Aprovado")) == [9, 2]
    assert _indices(filtrar_propostas(df, vendedor="", banco=None, equipamento="")) == todos, "filtro em branco = sem filtro"
    print("OK: vendedor, banco (com as duas grafias), equipamento e status, cada um sozinho.")

    inicio, fim = pd.Timestamp(2026, 9, 1), pd.Timestamp(2026, 9, 10)
    assert _indices(filtrar_propostas(df, data_de=inicio, data_ate=fim)) == [1, 0, 5, 2], "as duas pontas entram; sem data (6) nunca entra"
    assert _indices(filtrar_propostas(df, data_de=pd.Timestamp(2026, 9, 18))) == [10, 9, 7], "só a data inicial"
    assert _indices(filtrar_propostas(df, data_ate=pd.Timestamp(2026, 8, 15))) == [3, 8], "só a data final (sem data fica de fora)"
    assert _indices(filtrar_propostas(df, data_de=fim, data_ate=inicio)) == [], "inicial maior que a final: nenhum resultado"
    assert _indices(filtrar_propostas(df, data_de=pd.Timestamp(2026, 9, 10), data_ate=pd.Timestamp(2026, 9, 10))) == [1, 0], "um dia só"
    print("OK: período com as duas pontas incluídas, só início, só fim, um dia, invertido; proposta sem data nunca entra.")

    # combinados (E), com busca e status, e na ordenacao pedida
    assert _indices(filtrar_propostas(df, vendedor="ANA", banco="PORTOBANK")) == [1]
    assert _indices(filtrar_propostas(df, status="Em Análise", equipamento="LASER", vendedor="BIA")) == [7]
    assert _indices(filtrar_propostas(df, "laser", vendedor="BIA")) == [7, 3], "busca + vendedor"
    assert _indices(filtrar_propostas(df, status="Em Análise", data_de=inicio)) == [10, 7, 1, 0, 5]
    assert _indices(filtrar_propostas(df, status="Em Análise", data_de=inicio, ordenacao=ORDENACAO_VALOR_MAIOR)) == [1, 0, 10, 5, 7]
    assert _indices(filtrar_propostas(df, "santander", vendedor="ANA", status="Negado", data_de=pd.Timestamp(2026, 6, 1))) == [8]
    assert _indices(filtrar_propostas(df, vendedor="ANA", banco="HUBCRED BV")) == [], "combinação sem nenhuma proposta"
    print("OK: filtros combinados entre si e com busca/status/ordenação.")

    assert _indices(filtrar_propostas(df, "hubcred")) == [2, 3]
    assert _indices(filtrar_propostas(df, "00000000003")) == [3], "CPF só com os dígitos"
    assert _indices(filtrar_propostas(df, "  ptolomeu ")) == [9]
    for especial in ("(", "C++", "a[b", "*", "\\", "?"):
        assert _indices(filtrar_propostas(df, especial)) == [], f"a busca por {especial!r} é texto, não regex (sem erro)"
    print("OK: busca por nome/banco/equipamento/CPF continua igual; caracteres especiais ('(' , 'C++') não quebram mais a busca.")

    vazio = pd.DataFrame(columns=COLUNAS)
    assert filtrar_propostas(vazio, "abc", vendedor="X", data_de=pd.Timestamp(2026, 1, 1)).empty
    assert filtrar_propostas(vazio, "123").empty
    print("OK: sem nenhuma proposta, buscar/filtrar devolve vazio (sem erro).")


def testar_valores_distintos() -> None:
    linha("3) Opções dos filtros (core.propostas.valores_distintos)")
    df = _df()
    assert valores_distintos(df, "BANCO") == ["HUBCRED BV", "PORTOBANK", "SANTANDER", "SMART"], valores_distintos(df, "BANCO")
    assert valores_distintos(df, "EQUIPAMENTO") == ["BISTURI", "LASER", "MESA", "PTOLOMEU"]
    print("OK: sem vazios, em ordem alfabética, 'Hubcred BV' + 'HUBCRED BV' = uma opção só (empate: a em maiúsculas).")

    grafias = pd.DataFrame({"BANCO": ["Medicalsan", "Medicalsan", "MEDICALSAN", " Medicalsan "]})
    assert valores_distintos(grafias, "BANCO") == ["Medicalsan"], "fica a grafia mais usada (e espaços nas pontas não contam)"
    sujo = pd.DataFrame({"BANCO": ["ZETA", None, NAN, "", "   ", "ÁGUIA", "BETA", pd.NA]})
    assert valores_distintos(sujo, "BANCO") == ["ÁGUIA", "BETA", "ZETA"], "ausentes ignorados; 'ÁGUIA' ordena junto do 'A', não depois do 'Z'"
    assert valores_distintos(pd.DataFrame(columns=COLUNAS), "BANCO") == []
    print("OK: grafia mais usada vence; vazio/ausente ignorado; acento não desloca a ordem; sem propostas = lista vazia.")


# ---------------------------------------------------------------------------
# tela

class _Contexto:
    """Serve as propostas e os vendedores em memoria e troca as caixas de mensagem
    por stubs que guardam o texto (modais travariam o teste)."""

    def __enter__(self):
        self.originais = (QMessageBox.warning, QMessageBox.critical, QMessageBox.information, QMessageBox.question,
                          propostas_mod.listar_propostas, vendedores_mod.listar_vendedores)
        self.mensagens: list[str] = []
        self.leituras_de_vendedores = 0

        def _msg(*args, **kwargs):
            self.mensagens.append(str(args[2]) if len(args) > 2 else "")
            return QMessageBox.StandardButton.Ok

        QMessageBox.warning = QMessageBox.critical = QMessageBox.information = staticmethod(_msg)
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
        self.vendedores = ["ANA", "BIA", "CLA"]  # CLA esta cadastrada mas nao tem proposta nenhuma

        def _vendedores():
            self.leituras_de_vendedores += 1
            if isinstance(self.vendedores, Exception):
                raise self.vendedores
            return list(self.vendedores)

        vendedores_mod.listar_vendedores = _vendedores
        self.usar(_df())
        return self

    def usar(self, df: pd.DataFrame) -> None:
        propostas_mod.listar_propostas = lambda: df

    def __exit__(self, *_):
        (QMessageBox.warning, QMessageBox.critical, QMessageBox.information, QMessageBox.question,
         propostas_mod.listar_propostas, vendedores_mod.listar_vendedores) = self.originais


def _ciclos(app: QApplication, n: int = 4) -> None:
    for _ in range(n):
        app.processEvents()


def _opcoes(combo: QComboBox) -> list[str]:
    return [combo.itemText(i) for i in range(combo.count())]


def _escolher(combo: QComboBox, dado) -> None:
    indice = combo.findData(dado)
    assert indice >= 0, f"opção {dado!r} não existe em {_opcoes(combo)}"
    combo.setCurrentIndex(indice)


def _na_lista(tela: PropostasScreen) -> list[int]:
    m = tela._modelo
    return [m.indice_real(i) for i in range(m.rowCount()) if not m.eh_mais(i)]


def _digitar_data(campo, texto: str) -> None:
    campo.campo.setText(texto)


def testar_controles(app: QApplication, ctx: _Contexto) -> PropostasScreen:
    linha("4) A tela: controles, opções e ordenação")
    tela = PropostasScreen()
    tela.resize(1200 - 230, 700)  # a janela abre em 1200 de largura; o menu lateral ocupa 230
    tela.show()
    _ciclos(app)

    assert _opcoes(tela._filtro_vendedor) == ["Todos", "ANA", "BIA", "CLA"], "vendedores CADASTRADOS (mesmo sem proposta)"
    assert _opcoes(tela._filtro_banco) == ["Todos", "HUBCRED BV", "PORTOBANK", "SANTANDER", "SMART"]
    assert _opcoes(tela._filtro_equipamento) == ["Todos", "BISTURI", "LASER", "MESA", "PTOLOMEU"]
    assert _opcoes(tela._ordenacao) == [rotulo for _, rotulo in ORDENACAO_OPCOES]
    assert tela._ordenacao.currentData() == ORDENACAO_DATA_RECENTE, "abre na ordem de sempre: mais recente primeiro"
    assert not tela._botao_limpar_filtros.isEnabled(), "sem filtro nenhum, não há o que limpar"
    print("OK: vendedores cadastrados, bancos e equipamentos das propostas (cada um com 'Todos' antes); "
          "5 ordenações; abre na mais recente primeiro.")

    # tudo cabe na janela padrao (1200 - menu), sem controle cortado
    for controle in (tela._filtro_vendedor, tela._filtro_banco, tela._filtro_equipamento, tela._filtro_de, tela._filtro_ate,
                     tela._botao_limpar_filtros, tela._ordenacao, tela._busca):
        canto = controle.mapTo(tela, controle.rect().bottomRight())
        assert 0 < canto.x() <= tela.width() - 24 + 1, f"{controle} vaza pela direita ({canto.x()} de {tela.width()})"
    print(f"OK: na janela padrão (conteúdo de {tela.width()} px) nenhum controle vaza da tela.")

    assert _na_lista(tela) == [10, 9, 7, 1, 0, 5, 2, 4, 3, 8, 6]
    for chave, ordem in (
        (ORDENACAO_DATA_ANTIGA, [8, 3, 4, 2, 5, 0, 1, 7, 9, 10, 6]),
        (ORDENACAO_VALOR_MAIOR, [3, 8, 1, 0, 10, 5, 2, 9, 7, 4, 6]),
        (ORDENACAO_VALOR_MENOR, [7, 9, 5, 2, 10, 1, 0, 3, 8, 4, 6]),
        (ORDENACAO_TEMPO_PARADO, [2, 5, 1, 0, 7, 9, 10, 4, 3, 8, 6]),
        (ORDENACAO_DATA_RECENTE, [10, 9, 7, 1, 0, 5, 2, 4, 3, 8, 6]),
    ):
        _escolher(tela._ordenacao, chave)
        assert _na_lista(tela) == ordem, f"{chave}: {_na_lista(tela)}"
    print("OK: escolher cada ordenação reordena os cards da Lista.")
    assert not ctx.mensagens, ctx.mensagens
    return tela


def testar_lista_do_combo(app: QApplication, ctx: _Contexto) -> None:
    linha("4b) A lista aberta de um combo mostra o nome inteiro (estilo do Windows + tema, como no app)")
    # o estilo padrao do Qt sem tela (Fusion) alarga a lista sozinho e esconderia o problema: no Windows
    # a lista nasce com a largura do combo fechado e corta o nome. Por isso o teste usa o estilo do
    # Windows e o tema do app.
    estilos = [e for e in ("windows11", "windowsvista") if e in QStyleFactory.keys()]
    if not estilos:
        print("AVISO: este Qt não tem o estilo do Windows - checagem da lista dos combos pulada.")
        return
    original = app.style().objectName()
    # (mais largo que o combo fechado, mas cabendo na "tela" de 800 px do modo sem janela)
    comprido = "VELARYAN E ULTRAMED HIFU COM APLICADOR"
    ctx.usar(_df(PROPOSTAS + [("KIA K", "ANA", comprido, "SANTANDER", 1.0, "Em Análise", pd.Timestamp(2026, 9, 1), "1 dias")]))
    app.setStyle(estilos[0])
    app.setStyleSheet(build_stylesheet(TEMA_ESCURO))
    tela = None
    try:
        tela = PropostasScreen()
        tela.resize(1200 - 230, 700)
        tela.show()
        _ciclos(app)
        combo = tela._filtro_equipamento
        combo.showPopup()
        _ciclos(app)
        lista = combo.view().window()
        texto_inteiro = combo.fontMetrics().horizontalAdvance(comprido)
        assert texto_inteiro > combo.width(), "o teste só vale se o texto for mais largo que o combo fechado"
        assert lista.width() >= texto_inteiro, f"a lista de {lista.width()} px corta um texto de {texto_inteiro} px"
        combo.hidePopup()
        print(f"OK ({estilos[0]}): o combo fechado tem {combo.width()} px, mas a lista abre com {lista.width()} px "
              f"e mostra o nome inteiro ({texto_inteiro} px).")
    finally:
        if tela is not None:
            tela.close()
        app.setStyleSheet("")
        app.setStyle(original)
        ctx.usar(_df())


def testar_filtros_na_tela(app: QApplication, ctx: _Contexto, tela: PropostasScreen) -> None:
    linha("5) A tela: filtros, contagem e 'Limpar filtros' (Lista)")
    total = "11 proposta(s) · 5 em análise · 2 aprovadas · 1 efetivada · 2 negadas · 1 sem status"
    assert tela._contador.text() == total, tela._contador.text()

    _escolher(tela._filtro_vendedor, "ANA")
    assert _na_lista(tela) == [10, 1, 0, 4, 8, 6]
    assert tela._contador.text() == "6 proposta(s) · 3 em análise · 2 negadas · 1 sem status", tela._contador.text()
    assert tela._botao_limpar_filtros.isEnabled()
    _escolher(tela._filtro_banco, "SANTANDER")
    assert _na_lista(tela) == [10, 0, 8]
    assert tela._contador.text() == "3 proposta(s) · 2 em análise · 1 negada", "a contagem e o resumo são só do resultado filtrado"
    _escolher(tela._filtro_equipamento, "LASER")
    assert _na_lista(tela) == [0, 8]
    assert tela._contador.text() == "2 proposta(s) · 1 em análise · 1 negada"
    tela._filtro_status.setCurrentText("Negado")
    assert _na_lista(tela) == [8] and tela._contador.text() == "1 proposta(s) · 1 negada"
    print("OK: vendedor + banco + equipamento + status combinam; a contagem e o resumo por status acompanham só o filtrado.")

    tela._limpar_filtros()
    assert _na_lista(tela) == [10, 9, 7, 1, 0, 5, 2, 4, 3, 8, 6] and tela._contador.text() == total
    for combo in (tela._filtro_status, tela._filtro_vendedor, tela._filtro_banco, tela._filtro_equipamento):
        assert combo.currentIndex() == 0
    assert not tela._botao_limpar_filtros.isEnabled()
    print("OK: 'Limpar filtros' volta tudo pra 'Todos' e a lista completa.")

    # busca e ordenacao NAO sao filtros: sobrevivem ao "Limpar filtros"
    tela._busca.setText("laser")
    _escolher(tela._ordenacao, ORDENACAO_VALOR_MAIOR)
    _escolher(tela._filtro_vendedor, "BIA")
    assert _na_lista(tela) == [3, 7]
    tela._botao_limpar_filtros.click()
    assert tela._filtro_vendedor.currentIndex() == 0 and tela._busca.text() == "laser"
    assert tela._ordenacao.currentData() == ORDENACAO_VALOR_MAIOR
    assert _na_lista(tela) == [3, 8, 1, 0, 7], "sem o filtro de vendedor; a busca e a ordenação continuam"
    tela._busca.setText("")
    _escolher(tela._ordenacao, ORDENACAO_DATA_RECENTE)
    print("OK: 'Limpar filtros' não mexe na busca nem na ordenação.")

    # a busca deixa de estourar com caracteres de regex
    for especial in ("(", "C++", "a[b"):
        tela._busca.setText(especial)
        assert tela._modelo.total() == 0
        assert tela._contador.text().startswith("0 proposta(s)")
    tela._busca.setText("")
    assert not ctx.mensagens, ctx.mensagens
    print("OK: digitar '(' ou 'C++' na busca só não acha nada (antes dava erro).")


def testar_periodo_na_tela(app: QApplication, ctx: _Contexto, tela: PropostasScreen) -> None:
    linha("6) A tela: período (de / até)")
    _digitar_data(tela._filtro_de, "01/09/2026")
    _digitar_data(tela._filtro_ate, "10/09/2026")
    assert _na_lista(tela) == [1, 0, 5, 2], "as duas pontas entram"
    assert tela._botao_limpar_filtros.isEnabled()
    _digitar_data(tela._filtro_ate, "")
    assert _na_lista(tela) == [10, 9, 7, 1, 0, 5, 2], "só a data inicial"
    _digitar_data(tela._filtro_de, "")
    _digitar_data(tela._filtro_ate, "15/08/2026")
    assert _na_lista(tela) == [3, 8], "só a data final; proposta sem data fica de fora"
    print("OK: período com as duas pontas, só o início, só o fim.")

    # combinado com os outros filtros e com a ordenacao
    _digitar_data(tela._filtro_de, "01/08/2026")
    _digitar_data(tela._filtro_ate, "")
    _escolher(tela._filtro_banco, "SANTANDER")
    assert _na_lista(tela) == [10, 7, 0], "período + banco"
    tela._filtro_status.setCurrentText("Em Análise")
    _escolher(tela._ordenacao, ORDENACAO_VALOR_MAIOR)
    assert _na_lista(tela) == [0, 10, 7], "período + banco + status, por valor"
    tela._limpar_filtros()
    assert tela._filtro_de.texto() == "" and tela._filtro_ate.texto() == "" and len(_na_lista(tela)) == 11
    _escolher(tela._ordenacao, ORDENACAO_DATA_RECENTE)
    print("OK: período combinado com banco/status/ordenação; 'Limpar filtros' esvazia as datas.")

    # data invalida / inicial maior que a final: avisa, nunca vira outro filtro em silencio
    _digitar_data(tela._filtro_de, "31/02/2026")
    assert len(_na_lista(tela)) == 11 and "data inicial inválida (ignorada)" in tela._contador.text(), tela._contador.text()
    _digitar_data(tela._filtro_de, "10/09/2026")
    _digitar_data(tela._filtro_ate, "01/09/2026")
    assert _na_lista(tela) == [] and "a data inicial é maior que a final" in tela._contador.text(), tela._contador.text()
    assert tela._contador.text().startswith("0 proposta(s)")
    tela.grab()  # o estado vazio (mensagem no lugar dos cards) nao pode quebrar o desenho
    tela._limpar_filtros()
    assert tela._contador.text().startswith("11 proposta(s)") and " — " not in tela._contador.text()
    print("OK: '31/02/2026' é ignorada com aviso; inicial maior que a final avisa e não mostra nada; o aviso some ao limpar.")


def testar_recarga_e_paginacao(app: QApplication, ctx: _Contexto, tela: PropostasScreen) -> None:
    linha("7) A tela: recarregar (Atualizar / editar) e paginação")
    _escolher(tela._filtro_banco, "SMART")
    _escolher(tela._ordenacao, ORDENACAO_VALOR_MAIOR)
    assert _na_lista(tela) == [5, 4]
    tela._carregar_dados()  # "Atualizar"
    assert tela._filtro_banco.currentData() == "SMART" and tela._ordenacao.currentData() == ORDENACAO_VALOR_MAIOR
    assert _na_lista(tela) == [5, 4], "Atualizar mantém filtros e ordenação"

    # a grafia do banco muda entre duas leituras: continua o mesmo filtro
    mudou = _df()
    mudou.loc[[4, 5], "BANCO"] = "Smart"
    ctx.usar(mudou)
    tela._carregar_dados()
    assert tela._filtro_banco.currentData() == "Smart" and _na_lista(tela) == [5, 4], "mesma escolha, mesmo com a caixa diferente"

    # o banco escolhido deixa de existir (a unica proposta dele foi editada): volta pra Todos e mostra tudo
    sem_smart = _df()
    sem_smart.loc[[4, 5], "BANCO"] = "SANTANDER"
    ctx.usar(sem_smart)
    tela._carregar_dados()
    assert tela._filtro_banco.currentIndex() == 0 and "SMART" not in _opcoes(tela._filtro_banco)
    assert len(_na_lista(tela)) == 11, "sem o banco, o filtro volta pra 'Todos' - não fica 'preso' num filtro sem opção"
    print("OK: Atualizar mantém filtros e ordenação; a escolha sobrevive à mudança de caixa; opção que sumiu volta pra 'Todos'.")

    # vendedor: a lista e refeita quando a tela reaparece (alguem cadastrou outro em "Usuários")
    _escolher(tela._filtro_vendedor, "BIA")
    ctx.vendedores = ["ANA", "BIA", "CLA", "DEA"]
    tela.hide()
    tela.show()
    assert _opcoes(tela._filtro_vendedor) == ["Todos", "ANA", "BIA", "CLA", "DEA"] and tela._filtro_vendedor.currentData() == "BIA"
    ctx.vendedores = ["ANA", "CLA"]  # o vendedor escolhido deixou de existir no cadastro
    tela.hide()
    tela.show()
    assert tela._filtro_vendedor.currentIndex() == 0 and len(_na_lista(tela)) == 11
    print("OK: ao reabrir a tela o filtro de vendedor reflete o cadastro; vendedor que sumiu volta pra 'Todos' e a lista é refeita.")

    ctx.vendedores = RuntimeError("planilha bloqueada")
    tela._carregar_dados()
    assert any("planilha bloqueada" in m for m in ctx.mensagens), ctx.mensagens
    assert len(_na_lista(tela)) == 11, "sem a lista de vendedores a tela continua funcionando"
    ctx.mensagens.clear()
    ctx.vendedores = ["ANA", "BIA", "CLA"]
    ctx.usar(_df())
    tela._carregar_dados()
    print("OK: se o cadastro de vendedores não abre, avisa (não falha em silêncio) e o resto da tela funciona.")

    # paginacao: 70 propostas de 3 vendedores
    muitas = _df([(f"CLIENTE {i:02d}", ("ANA", "BIA", "CLA")[i % 3], f"EQUIP {i % 5}", f"BANCO {i % 4}", 1000.0 + i, "Em Análise",
                   pd.Timestamp(2026, 3, 1) + pd.Timedelta(days=i), f"{i} dias") for i in range(70)])
    ctx.usar(muitas)
    tela._carregar_dados()
    assert (tela._modelo.total(), tela._modelo.visiveis()) == (70, 30)
    tela._modelo.mostrar_mais()
    assert tela._modelo.visiveis() == 60
    tela._carregar_dados()
    assert tela._modelo.visiveis() == 60, "recarregar mantém a página"
    _digitar_data(tela._filtro_de, "01/03/20")  # data ainda incompleta: nao e filtro
    assert tela._modelo.visiveis() == 60, "digitar uma data ainda incompleta não refaz a lista nem volta pra primeira página"
    _digitar_data(tela._filtro_de, "")
    assert tela._modelo.visiveis() == 60
    _escolher(tela._filtro_vendedor, "ANA")
    assert tela._modelo.total() == 24 and tela._modelo.visiveis() == 24 and not tela._modelo.eh_mais(24), "24 < 30: sem 'Carregar mais'"
    _escolher(tela._filtro_vendedor, None)
    tela._modelo.mostrar_mais()
    assert tela._modelo.visiveis() == 60
    _escolher(tela._ordenacao, ORDENACAO_TEMPO_PARADO)
    assert tela._modelo.visiveis() == 30, "mudar a ordenação volta pra primeira página"
    assert _na_lista(tela)[:3] == [69, 68, 67], "a mais parada (69 dias) primeiro"
    tela._modelo.mostrar_mais()
    _escolher(tela._filtro_banco, "BANCO 1")
    assert tela._modelo.visiveis() == min(30, tela._modelo.total()), "mudar um filtro volta pra primeira página"
    _escolher(tela._ordenacao, ORDENACAO_DATA_RECENTE)
    tela._limpar_filtros()
    print("OK: 70 propostas: recarregar mantém a página; mudar filtro/ordenação volta à primeira; "
          "data ainda incompleta não refaz a lista; 24 resultados não têm 'Carregar mais'.")

    ctx.usar(_df())  # devolve os dados-modelo pras proximas secoes
    tela._carregar_dados()
    assert not ctx.mensagens, ctx.mensagens


def testar_perfil_vendedor(app: QApplication, ctx: _Contexto) -> None:
    linha("8) Perfil VENDEDOR")
    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_VENDEDOR, nome_usuario="ANA"))
    try:
        leituras = ctx.leituras_de_vendedores
        tela = PropostasScreen()
        tela.resize(1000, 700)
        tela.show()
        _ciclos(app)
        assert tela._bloco_filtro_vendedor.isHidden(), "vendedor só vê as próprias propostas: filtrar por vendedor não faz sentido"
        assert not tela._filtro_banco.isHidden() and not tela._filtro_equipamento.isHidden() and not tela._filtro_de.isHidden()
        assert not tela._ordenacao.isHidden()
        assert ctx.leituras_de_vendedores == leituras, "o vendedor nem lê o cadastro de vendedores"
        _escolher(tela._filtro_banco, "SANTANDER")
        _escolher(tela._ordenacao, ORDENACAO_TEMPO_PARADO)
        assert _na_lista(tela) == [0, 7, 10, 8], "SANTANDER por tempo parado: 9, 1 e -6 dias, e por último a Encerrada"
        tela.close()
    finally:
        sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
    print("OK: o vendedor não vê (nem carrega) o filtro de vendedor, mas usa banco, equipamento, período e ordenação.")


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
    testar_ordenacao()
    testar_filtros()
    testar_valores_distintos()
    try:
        with _Contexto() as ctx:
            tela = testar_controles(app, ctx)
            testar_lista_do_combo(app, ctx)
            testar_filtros_na_tela(app, ctx, tela)
            testar_periodo_na_tela(app, ctx, tela)
            testar_recarga_e_paginacao(app, ctx, tela)
            tela.close()
            testar_perfil_vendedor(app, ctx)
        linha("TUDO OK")
    finally:
        sessao_mod.encerrar()


if __name__ == "__main__":
    main()
