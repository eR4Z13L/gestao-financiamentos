"""Testa os filtros (vendedor, banco, equipamento, periodo) e a ordenacao (esperando resposta, data,
valor, tempo parado) de "Todas as Propostas": as regras em core/propostas.py e a
tela PropostasScreen, combinados com a busca e o filtro de status que ja existiam.
Dados FICTICIOS, em memoria (as vendas e o historico que a tela le saem de uma planilha ficticia vazia de propostas
correspondentes, numa pasta temporaria).

Rodar com: venv/Scripts/python.exe scripts/smoke_test_filtros_propostas.py
"""

from __future__ import annotations

from collections import Counter
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from PySide6.QtWidgets import QApplication, QComboBox, QMessageBox, QStyleFactory

import config
config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
import fixture_ficticia as fx
from core import data_store as bd
from core import propostas as propostas_mod
from core import vendas as vendas_mod
from core import sessao as sessao_mod
from core import vendedores as vendedores_mod
from core.propostas import (
    ORDENACAO_DATA_ANTIGA,
    ORDENACAO_DATA_RECENTE,
    ORDENACAO_ESPERANDO,
    ORDENACAO_OPCOES,
    ORDENACAO_TEMPO_PARADO,
    ORDENACAO_VALOR_MAIOR,
    ORDENACAO_VALOR_MENOR,
    filtrar_propostas,
    ordenar,
    valores_distintos,
)
from desktop.screens.propostas_screen import PropostasScreen, etapa_para_contar, resumo_por_etapa
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
        # sem os dias esperando: primeiro as que esperam resposta (Em Análise), da mais recente para a mais antiga,
        # depois as demais, tambem da mais recente (sem data no fim) - o caso com os dias esta logo abaixo
        ORDENACAO_ESPERANDO: [10, 7, 1, 0, 5, 9, 2, 4, 3, 8, 6],
    }
    assert {chave for chave, _ in ORDENACAO_OPCOES} == set(esperado), "toda opção do seletor tem teste"
    assert ORDENACAO_OPCOES[0][0] == ORDENACAO_ESPERANDO, "a primeira opção (a de quando a tela abre) é a esperando resposta"
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
    assert ordenar(vazio, ORDENACAO_ESPERANDO, dias_esperando={1: 3}).empty
    print("OK: sem nenhuma proposta, todas as ordenações devolvem vazio (sem erro).")


def testar_ordem_esperando() -> None:
    linha("1b) Ordem \"Esperando resposta há mais tempo\" (com os dias de cada uma)")
    df = _df()
    # as que esperam (Em Análise: 0, 1, 5, 7 e 10) pela espera, a maior primeiro; 0, 1 e 5 empatadas em 9 dias:
    # a data mais recente primeiro (0 e 1 no mesmo dia: a cadastrada por ultimo); a 10 nao tem o numero: no fim
    # delas. O numero de quem NAO espera (2, que esta Aprovado) nao conta: as demais vem por data, como sempre.
    dias = {0: 9, 1: 9, 5: 9, 7: 1, 10: None, 2: 30}
    assert _indices(ordenar(df, ORDENACAO_ESPERANDO, dias_esperando=dias)) == [1, 0, 5, 7, 10, 9, 2, 4, 3, 8, 6]
    assert _indices(ordenar(df, ORDENACAO_ESPERANDO, dias_esperando=pd.Series(dias))) == [1, 0, 5, 7, 10, 9, 2, 4, 3, 8, 6], \
        "aceita os dias numa Series (pelo indice) também"
    # a espera manda mais que a data: a mais antiga (5) passa na frente quando espera ha mais dias
    assert _indices(ordenar(df, ORDENACAO_ESPERANDO, dias_esperando={0: 9, 1: 9, 5: 14, 7: 20, 10: 2})) == \
        [7, 5, 1, 0, 10, 9, 2, 4, 3, 8, 6]
    # Pré-aprovado tambem espera a resposta (ainda nao e a final); "APROVADO" em caixa alta nao
    pre = df.copy()
    pre.loc[9, "STATUS"] = "Pré-aprovado"
    pre.loc[2, "STATUS"] = "APROVADO"
    assert _indices(ordenar(pre, ORDENACAO_ESPERANDO, dias_esperando={9: 40, 2: 50, 0: 1})) == \
        [9, 0, 10, 7, 1, 5, 2, 4, 3, 8, 6]
    assert list(ordenar(df, ORDENACAO_ESPERANDO, dias_esperando=dias).columns) == COLUNAS, "nada de coluna auxiliar"
    assert _indices(filtrar_propostas(df, banco="SANTANDER", ordenacao=ORDENACAO_ESPERANDO, dias_esperando=dias)) == \
        [0, 7, 10, 8], "o filtrar repassa os dias para a ordem"
    print("OK: as que esperam resposta (Em Análise / Pré-aprovado) primeiro, pela espera (empate: a mais recente; "
          "sem o número: no fim delas); depois as demais por data; o filtrar repassa os dias.")


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


def testar_propostas_na_lista() -> None:
    linha("1c) A venda e os dias esperando de cada card (core.vendas.propostas_na_lista)")
    hoje = pd.Timestamp(2026, 9, 30)
    df = _df()
    df["ID_PROPOSTA"] = ""
    df.loc[1, "ID_PROPOSTA"] = "P-um"
    na_venda = vendas_mod.PropostaNaVenda("P-um", 1, "PORTOBANK", "Em Análise", 50000.0, 12, pd.Timestamp(2026, 9, 10),
                                          "LASER", False, 4)
    venda = vendas_mod.ResumoDaVenda("V-um", df.loc[1, "CPF"], "ANA A", "ANA", "LASER", vendas_mod.VENDA_AGUARDANDO, "", (),
                                     pd.Timestamp(2026, 9, 10), 4, "", (na_venda,))
    itens = vendas_mod.propostas_na_lista(df, [venda], None, hoje)
    assert itens[1].venda is venda and itens[1].proposta is na_venda, "a da venda leva a venda (e o que ela já calculou)"
    assert itens[0].venda is None and itens[0].proposta.dias_esperando == 20, "a de antes das vendas: dias pela DATA"
    # outra leitura, em que a posicao 1 ja e outra proposta (sem o ID da venda): nunca mistura as duas
    outra = df.copy()
    outra.loc[1, "ID_PROPOSTA"] = ""
    assert vendas_mod.propostas_na_lista(outra, [venda], None, hoje)[1].venda is None, "a posição bate, o ID não: sem venda"
    vazia = vendas_mod.PropostaNaVenda("", 1, "PORTOBANK", "Em Análise", 50000.0, 12, None, "LASER", False, 4)
    venda_sem_id = vendas_mod.ResumoDaVenda(*[getattr(venda, c) for c in ("id", "cpf", "cliente", "vendedor", "equipamentos",
                                            "status", "motivo", "fechadas", "data_criacao", "dias_na_etapa", "observacoes")],
                                            (vazia,))
    assert vendas_mod.propostas_na_lista(outra, [venda_sem_id], None, hoje)[1].venda is None, "proposta sem ID nunca casa"
    # com o historico: uma proposta com ID (fora de venda) conta da ultima troca, nao da DATA
    historico = pd.DataFrame([{"QUANDO": pd.Timestamp(2026, 9, 28, 15), "TIPO": "proposta", "ID": "P-um", "DE": "",
                               "PARA": "Em Análise", "MOTIVO": "", "COMPUTADOR": ""}])
    assert vendas_mod.propostas_na_lista(df, [], historico, hoje)[1].proposta.dias_esperando == 2
    assert vendas_mod.propostas_na_lista(df, [], None, hoje)[1].proposta.dias_esperando == 20
    print("OK: a da venda leva a venda; a posição sem o mesmo ID nunca mistura; os dias contam do histórico e, sem ele, da DATA.")


def testar_propostas_do_arquivo() -> None:
    linha("1d) propostas_na_lista_do_arquivo lê o HISTÓRICO do arquivo (planilha fictícia)")
    fx.apontar_modulos_para(fx.criar(Path(tempfile.mkdtemp(prefix="filtros_historico_"))))
    try:
        caminho = propostas_mod.CAMINHO_XLSX
        propostas = bd.ler_propostas(caminho)[bd.PROPOSTAS_COLUNAS_EDITAVEIS].copy()
        alvo = int(propostas.index[propostas["STATUS"] == propostas_mod.STATUS_EM_ANALISE][0])
        propostas.loc[alvo, "ID_PROPOSTA"] = "P-sem-venda"  # uma proposta com ID e sem venda
        propostas.loc[alvo, "DATA"] = pd.Timestamp.today().normalize() - pd.Timedelta(days=30)
        bd.escrever_vendas_e_propostas(caminho, propostas=propostas, historico_novo=[
            {"QUANDO": pd.Timestamp.today().normalize(), "TIPO": "proposta", "ID": "P-sem-venda", "DE": "",
             "PARA": propostas_mod.STATUS_EM_ANALISE, "MOTIVO": "", "COMPUTADOR": ""}])
        itens = vendas_mod.propostas_na_lista_do_arquivo(propostas_mod.listar_propostas())
        assert itens[alvo].venda is None and itens[alvo].proposta.dias_esperando == 0, itens[alvo].proposta.dias_esperando
    finally:
        fx.restaurar_modulos()
    print("OK: a espera de uma proposta com ID conta da última troca no histórico do arquivo (0 dias), não da DATA (30).")


def testar_resumo_por_etapa() -> None:
    linha("3b) A contagem por status do topo (resumo_por_etapa)")
    assert resumo_por_etapa({"em_analise": 12, "aprovado": 5, "negado": 30}) == "12 em análise · 5 aprovadas · 30 negadas"
    assert resumo_por_etapa({"negado": 1, "aprovado": 1, "efetivado": 1, "em_analise": 1}) ==         "1 em análise · 1 aprovada · 1 efetivada · 1 negada"
    assert resumo_por_etapa({"em_analise": 0, "negado": 2}) == "2 negadas", "zeros não aparecem"
    assert resumo_por_etapa({}) == ""
    assert resumo_por_etapa({"desconhecida": 1, "": 3, "aprovado": 2}) == "2 aprovadas · 1 com status não reconhecido · 3 sem status", "ordem do funil"
    # os status de antes (Garantia assinada, Nota fiscal anexada, Não efetivado, Encerrada) nao tem mais frase propria: contam
    # como "status não reconhecido" ate a conversao (nunca somem da contagem)
    for antigo in ("Garantia Assinada", "Nota Fiscal Anexada", "Nota fiscal enviada", "Não efetivado", "Encerrada", "APROVADO", "Texto solto"):
        assert etapa_para_contar(antigo) == "desconhecida", antigo
    for oficial, etapa in (("Em Análise", "em_analise"), ("Pré-aprovado", "pre_aprovado"), ("Aprovado", "aprovado"),
                           ("Negado", "negado"), ("Assinado", "aprovado"), ("NF enviada", "aprovado"),
                           ("Efetivado", "efetivado"), ("", "")):
        assert etapa_para_contar(oficial) == etapa, oficial
    contagem = Counter(etapa_para_contar(s) for s in ("Aprovado", "Encerrada", "Garantia Assinada", "", "Negado"))
    assert resumo_por_etapa(contagem) == "1 aprovada · 1 negada · 2 com status não reconhecido · 1 sem status", resumo_por_etapa(contagem)
    print("OK: '12 em análise · 5 aprovadas · 30 negadas' (singular/plural, na ordem do funil, sem zeros).")


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
    por stubs que guardam o texto (modais travariam o teste). A tela tambem le as vendas e o historico do arquivo:
    aponta para uma planilha ficticia, numa pasta temporaria (nunca a real)."""

    def __enter__(self):
        fx.apontar_modulos_para(fx.criar(Path(tempfile.mkdtemp(prefix="filtros_propostas_"))))
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
        fx.restaurar_modulos()


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
    """As propostas dos cards montados (a pagina carregada), na ordem da lista."""
    return [card.item.proposta.indice for card in tela.lista.cards]


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
    assert tela._ordenacao.currentData() == ORDENACAO_ESPERANDO, "abre com as que esperam resposta há mais tempo primeiro"
    assert not tela._botao_limpar_filtros.isEnabled(), "sem filtro nenhum, não há o que limpar"
    print("OK: vendedores cadastrados, bancos e equipamentos das propostas (cada um com 'Todos' antes); "
          "6 ordenações; abre com as que esperam resposta há mais tempo primeiro.")

    # tudo cabe na janela padrao (1200 - menu), sem controle cortado
    for controle in (tela._filtro_vendedor, tela._filtro_banco, tela._filtro_equipamento, tela._filtro_de, tela._filtro_ate,
                     tela._botao_limpar_filtros, tela._ordenacao, tela._busca):
        canto = controle.mapTo(tela, controle.rect().bottomRight())
        assert 0 < canto.x() <= tela.width() - 24 + 1, f"{controle} vaza pela direita ({canto.x()} de {tela.width()})"
    print(f"OK: na janela padrão (conteúdo de {tela.width()} px) nenhum controle vaza da tela.")

    # sem historico, a espera conta da DATA: 5 (05/09), 0 e 1 (10/09), 7 (18/09) e 10 (25/09) - a que esta ha
    # mais tempo primeiro (0 e 1 empatadas: a cadastrada por ultimo); depois as demais, da mais recente
    assert _na_lista(tela) == [5, 1, 0, 7, 10, 9, 2, 4, 3, 8, 6], _na_lista(tela)
    for chave, ordem in (
        (ORDENACAO_DATA_ANTIGA, [8, 3, 4, 2, 5, 0, 1, 7, 9, 10, 6]),
        (ORDENACAO_VALOR_MAIOR, [3, 8, 1, 0, 10, 5, 2, 9, 7, 4, 6]),
        (ORDENACAO_VALOR_MENOR, [7, 9, 5, 2, 10, 1, 0, 3, 8, 4, 6]),
        (ORDENACAO_TEMPO_PARADO, [2, 5, 1, 0, 7, 9, 10, 4, 3, 8, 6]),
        (ORDENACAO_ESPERANDO, [5, 1, 0, 7, 10, 9, 2, 4, 3, 8, 6]),
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
    opcoes = [tela._filtro_status.itemText(i) for i in range(tela._filtro_status.count())]
    assert opcoes == ["Todos", "Em Análise", "Pré-aprovado", "Aprovado", "Negado", "Assinado", "NF enviada", "Efetivado"],         "o filtro Resposta oferece só os status oficiais, não os valores crus da planilha"

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
        assert tela.lista.total() == 0
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
    lista = tela.lista
    assert (lista.total(), len(lista.cards)) == (70, 30) and not lista.botao_mais.isHidden()
    lista.botao_mais.click()
    assert len(lista.cards) == 60
    tela._carregar_dados()
    assert len(lista.cards) == 60, "recarregar mantém a página"
    _digitar_data(tela._filtro_de, "01/03/20")  # data ainda incompleta: nao e filtro
    assert len(lista.cards) == 60, "digitar uma data ainda incompleta não refaz a lista nem volta pra primeira página"
    _digitar_data(tela._filtro_de, "")
    assert len(lista.cards) == 60
    _escolher(tela._filtro_vendedor, "ANA")
    assert lista.total() == 24 and len(lista.cards) == 24 and lista.botao_mais.isHidden(), "24 < 30: sem 'Carregar mais'"
    _escolher(tela._filtro_vendedor, None)
    lista.botao_mais.click()
    assert len(lista.cards) == 60
    _escolher(tela._ordenacao, ORDENACAO_TEMPO_PARADO)
    assert len(lista.cards) == 30, "mudar a ordenação volta pra primeira página"
    assert _na_lista(tela)[:3] == [69, 68, 67], "a mais parada (69 dias) primeiro"
    lista.botao_mais.click()
    _escolher(tela._filtro_banco, "BANCO 1")
    assert len(lista.cards) == min(30, lista.total()), "mudar um filtro volta pra primeira página"
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
    testar_ordem_esperando()
    testar_propostas_na_lista()
    testar_propostas_do_arquivo()
    testar_filtros()
    testar_valores_distintos()
    testar_resumo_por_etapa()
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
