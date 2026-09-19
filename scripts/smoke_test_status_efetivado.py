"""Testa o status "Efetivado" (etapa depois de "Aprovado": aprovada E compra
concluida): lista de status, regra de "Encerrado" na coluna TEMPO (leitura e
formula gravada no Excel), taxa de aprovacao do dashboard (nao pode cair so
por separar a etapa), indicador "Aprovados nao efetivados" (card e tabela por
vendedor) e a atualizacao das formulas de uma planilha gravada com a regra
antiga. Tudo com dados FICTICIOS numa planilha temporaria.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_status_efetivado.py
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

import config
config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
from core import clientes as clientes_mod
from core import dashboard as dashboard_mod
from core import data_store as bd
from core import equipamentos as equipamentos_mod
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import vendedores as vendedores_mod
from core.validators import _digito_verificador_cpf
from desktop.dialogs.proposta_dialog import PropostaDialog
from desktop.screens.dashboard_screen import DashboardScreen


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _cpf(n: int) -> str:
    base = f"{123456780 + n:09d}"
    return base + _digito_verificador_cpf(base)


def _hash(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def _criar_planilha_vazia(caminho: Path) -> None:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for nome, colunas in (
        (bd.ABA_CLIENTES, bd.CLIENTES_COLUNAS),
        (bd.ABA_EQUIPAMENTOS, bd.EQUIPAMENTOS_COLUNAS),
        (bd.ABA_PROPOSTAS, bd.PROPOSTAS_COLUNAS),
        (bd.ABA_VENDEDORES, bd.VENDEDORES_COLUNAS),
    ):
        wb.create_sheet(nome).append(colunas)
    wb.save(caminho)


def _df(statuses: list[str], vendedores: list[str] | None = None) -> pd.DataFrame:
    """Propostas em memoria (so as colunas que o dashboard usa)."""
    return pd.DataFrame(
        {
            "STATUS": statuses,
            "VALOR (R$)": [1000.0] * len(statuses),
            "VENDEDOR": vendedores or ["ANA"] * len(statuses),
        }
    )


# ---------------------------------------------------------------------------

def testar_regras() -> None:
    linha("1) Lista de status e categorias")
    assert propostas_mod.STATUS_OPCOES == [
        "Em Análise", "Pré-aprovado", "Aprovado", "Nota Fiscal Anexada", "Garantia Assinada", "Efetivado", "Negado",
    ], propostas_mod.STATUS_OPCOES
    assert propostas_mod.STATUS_OPCOES.index("Efetivado") > propostas_mod.STATUS_OPCOES.index("Aprovado"), "vem DEPOIS de Aprovado"
    for s in ("Efetivado", "EFETIVADO", " efetivada "):
        assert propostas_mod.categoria_status(s) == "Aprovado", s
        assert propostas_mod.eh_efetivado(s) and not propostas_mod.eh_aprovado_nao_efetivado(s)
    for s in ("Aprovado", "APROVADO", "aprovada"):
        assert propostas_mod.eh_aprovado_nao_efetivado(s) and not propostas_mod.eh_efetivado(s)
    for s in ("Pré-aprovado", "Nota Fiscal Anexada", "Garantia Assinada", "Em Análise", "Negado", ""):
        assert not propostas_mod.eh_aprovado_nao_efetivado(s) and not propostas_mod.eh_efetivado(s), s
    print("OK: 'Efetivado' entra depois de Garantia Assinada; conta como categoria Aprovado; só o status exato "
          "'Aprovado' é 'aprovado não efetivado'.")

    linha("2) TEMPO (leitura): Efetivado e Negado encerram; Aprovado NÃO")
    dez_dias_atras = datetime.today() - timedelta(days=10)
    for status in ("Efetivado", "EFETIVADO", "Efetivada", "Negado", "NEGADO", "Reprovado", "Cancelado"):
        assert bd._calcular_tempo(dez_dias_atras, status) == "Encerrado", status
    for status in ("Aprovado", "APROVADO", "Em Análise", "Pré-aprovado", "Nota Fiscal Anexada", "Garantia Assinada", ""):
        assert bd._calcular_tempo(dez_dias_atras, status) == "10 dias", status
    assert bd._calcular_tempo(None, "Aprovado") == "", "sem data nao ha o que contar"
    assert "APROVADO" not in bd.STATUS_ENCERRADO and "EFETIVADO" in bd.STATUS_ENCERRADO
    print("OK: Encerrado = Efetivado + Negado/Reprovado/Cancelado; Aprovado e as etapas em aberto contam dias.")

    linha("2b) TEMPO (fórmula do Excel): mesma regra da leitura")
    formula = bd._formula_tempo(7)
    palavras_na_formula = set(re.findall(r'UPPER\(J7\)="([^"]+)"', formula))
    assert palavras_na_formula == set(bd.STATUS_ENCERRADO), "a fórmula tem que testar exatamente os status encerrados do app"
    assert '"APROVADO"' not in formula and 'UPPER(J7)="EFETIVADO"' in formula and 'UPPER(J7)="NEGADO"' in formula
    assert formula.startswith('=IF(A7="","",IF(OR(') and formula.endswith('"Encerrado",TODAY()-A7&" dias"))')
    print("OK: a fórmula gravada testa exatamente os mesmos status que o app (Efetivado, Negado...; sem Aprovado).")


def testar_dashboard_core() -> None:
    linha("3) Dashboard: taxa de aprovação NÃO cai ao separar Efetivado")
    antes = _df(["Aprovado"] * 4 + ["Nota Fiscal Anexada"] + ["Negado"] * 3 + ["Em Análise"] * 2)
    depois = _df(["Aprovado"] * 2 + ["Efetivado"] * 2 + ["Nota Fiscal Anexada"] + ["Negado"] * 3 + ["Em Análise"] * 2)
    t_antes, t_depois = dashboard_mod.totais_gerais(antes), dashboard_mod.totais_gerais(depois)
    assert t_antes["aprovadas"] == t_depois["aprovadas"] == 5
    assert t_antes["taxa_aprovacao"] == t_depois["taxa_aprovacao"] == 62.5, "5 aprovadas de 8 decididas, antes e depois"
    assert t_antes["valor_aprovado"] == t_depois["valor_aprovado"] == 5000.0
    assert t_depois["negadas"] == 3 and t_depois["em_analise"] == 2
    print("OK: 2 dos 4 'Aprovado' viram 'Efetivado' e a taxa (62,5%) e o valor aprovado continuam iguais.")

    linha("3b) Indicador 'Aprovados não efetivados'")
    assert (t_antes["efetivadas"], t_antes["aprovadas_nao_efetivadas"], t_antes["pct_aprovadas_nao_efetivadas"]) == (0, 4, 100.0)
    assert (t_depois["efetivadas"], t_depois["aprovadas_nao_efetivadas"], t_depois["pct_aprovadas_nao_efetivadas"]) == (2, 2, 50.0)
    # Nota Fiscal Anexada / Garantia Assinada / Pre-aprovado nao entram nem no numero nem na base
    com_etapas = _df(["Aprovado", "Efetivado", "Efetivado", "Garantia Assinada", "Garantia Assinada", "Pré-aprovado", "Nota Fiscal Anexada"])
    t = dashboard_mod.totais_gerais(com_etapas)
    assert (t["aprovadas_nao_efetivadas"], t["efetivadas"]) == (1, 2)
    assert abs(t["pct_aprovadas_nao_efetivadas"] - 100 / 3) < 1e-9, "1 de (1 Aprovado + 2 Efetivado)"
    assert dashboard_mod.totais_gerais(_df(["Efetivado", "EFETIVADA"]))["pct_aprovadas_nao_efetivadas"] == 0.0
    vazio = dashboard_mod.totais_gerais(_df(["Em Análise", "Negado"]))
    assert (vazio["aprovadas_nao_efetivadas"], vazio["efetivadas"], vazio["pct_aprovadas_nao_efetivadas"]) == (0, 0, 0.0), "sem divisão por zero"
    print("OK: número absoluto e % sobre (Aprovado + Efetivado); outras etapas ficam fora; 0 de 0 não quebra.")

    detalhe = dashboard_mod.detalhamento_por_status(depois)
    assert detalhe.loc[detalhe["STATUS"] == "Efetivado", "Categoria"].tolist() == ["Aprovado"]
    print("OK: no detalhamento por status, 'Efetivado' aparece com categoria 'Aprovado'.")

    linha("3c) Desempenho por vendedor")
    listar_original = vendedores_mod.listar_vendedores
    vendedores_mod.listar_vendedores = lambda: ["ANA", "BIA"]  # cadastro oficial (por_vendedor agrupa quem nao esta nele em "Não identificado")
    try:
        pv = dashboard_mod.por_vendedor(
            _df(["Aprovado", "Aprovado", "Efetivado", "Nota Fiscal Anexada", "Efetivado", "Efetivado", "Em Análise"],
                ["ANA", "ANA", "ANA", "ANA", "BIA", "BIA", "BIA"])
        ).set_index("Vendedor")
        colunas_vazio = list(dashboard_mod.por_vendedor(_df([])).columns)
    finally:
        vendedores_mod.listar_vendedores = listar_original
    assert pv.loc["ANA", "Não Efetivadas"] == 2 and pv.loc["ANA", "Não Efetivadas (%)"] == 66.7  # 2 de (2 Aprovado + 1 Efetivado)
    assert pv.loc["BIA", "Não Efetivadas"] == 0 and pv.loc["BIA", "Não Efetivadas (%)"] == 0.0
    assert pv.loc["ANA", "Taxa Aprovação (%)"] == 100.0 and pv.loc["ANA", "Aprovadas"] == 4, "as colunas de sempre não mudam"
    assert colunas_vazio == dashboard_mod._COLUNAS_POR_VENDEDOR
    assert "Não Efetivadas" in dashboard_mod._COLUNAS_POR_VENDEDOR and "Não Efetivadas (%)" in dashboard_mod._COLUNAS_POR_VENDEDOR
    print("OK: a quebra por vendedor traz 'Não Efetivadas' (número e %); as demais colunas ficam como estavam.")


def _texto_celula(modelo, linha_: int, coluna: str) -> str:
    colunas = [modelo.headerData(c, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole) for c in range(modelo.columnCount())]
    return str(modelo.data(modelo.index(linha_, colunas.index(coluna)), Qt.ItemDataRole.DisplayRole))


def testar_telas_e_arquivo(app: QApplication, pasta: Path) -> None:
    class _Stubs:
        def __enter__(self):
            self.orig = (QMessageBox.warning, QMessageBox.critical, QMessageBox.information, QMessageBox.question)
            self.textos: list[str] = []

            def _msg(*args, **kwargs):
                self.textos.append(str(args[2]) if len(args) > 2 else "")
                return QMessageBox.StandardButton.Ok

            QMessageBox.warning = QMessageBox.critical = QMessageBox.information = staticmethod(_msg)
            QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
            return self

        def __exit__(self, *_):
            QMessageBox.warning, QMessageBox.critical, QMessageBox.information, QMessageBox.question = self.orig

    arquivo = pasta / "controle.xlsx"
    _criar_planilha_vazia(arquivo)
    clientes_mod.CAMINHO_XLSX = propostas_mod.CAMINHO_XLSX = vendedores_mod.CAMINHO_XLSX = equipamentos_mod.CAMINHO_XLSX = arquivo
    vendedores_mod.adicionar_vendedor("ANA")
    vendedores_mod.adicionar_vendedor("BIA")
    for i, vendedor in enumerate(("ANA", "BIA")):
        clientes_mod.adicionar_cliente({"CPF/CNPJ": _cpf(i), "CLIENTE": f"CLIENTE {vendedor}", "TIPO": "Cliente", "VENDEDOR": vendedor})

    linha("4) Formulário de proposta: 'Efetivado' na lista, grava e encerra o TEMPO")
    with _Stubs() as stubs:
        dialogo = PropostaDialog(_cpf(0), "CLIENTE ANA")
        assert [dialogo._status.itemText(i) for i in range(dialogo._status.count())] == propostas_mod.STATUS_OPCOES
        assert dialogo._status.findText("Efetivado") > dialogo._status.findText("Garantia Assinada")
        dialogo._valor.setValue(11111)
        dialogo._equipamento.setCurrentText("Equip Efetivado")
        dialogo._banco.setCurrentText("Banco Teste")
        dialogo._status.setCurrentText("Efetivado")
        dialogo._salvar()
        assert dialogo.result() == QDialog.DialogCode.Accepted, stubs.textos
    print("OK: 'Efetivado' está na lista do formulário (depois de Garantia Assinada) e a proposta grava.")

    # cenario do dashboard: ANA: Aprovado x2, Efetivado x1 (a de cima), NF x1 ; BIA: Efetivado x2, Em Analise x1
    def _add(cpf: str, status: str, valor: int) -> None:
        propostas_mod.adicionar_proposta(
            {"CPF": cpf, "VALOR (R$)": valor, "MESES": 12, "EQUIPAMENTO": f"Equip {valor}", "BANCO": "Banco Teste", "STATUS": status}
        )

    for valor, status in ((22222, "Aprovado"), (33333, "Aprovado"), (44444, "Nota Fiscal Anexada")):
        _add(_cpf(0), status, valor)
    for valor, status in ((55555, "Efetivado"), (66666, "Efetivado"), (77777, "Em Análise")):
        _add(_cpf(1), status, valor)

    p = bd.ler_propostas(arquivo)
    assert len(p) == 7
    por_status = p.groupby("STATUS")["TEMPO"].agg(list).to_dict()
    assert all(t == "Encerrado" for t in por_status["Efetivado"]) and len(por_status["Efetivado"]) == 3
    assert all(t.endswith("dias") for t in por_status["Aprovado"]), por_status["Aprovado"]
    ws = openpyxl.load_workbook(arquivo)[bd.ABA_PROPOSTAS]
    for linha_excel in range(2, ws.max_row + 1):
        assert ws.cell(row=linha_excel, column=9).value == bd._formula_tempo(linha_excel), "fórmula gravada = regra atual"
    print("OK: gravada, a proposta 'Efetivado' mostra TEMPO 'Encerrado' e as 'Aprovado' contam dias; "
          "a fórmula de cada linha do Excel é a da regra atual.")

    linha("5) Dashboard (tela): card e tabela por vendedor")
    tela = DashboardScreen()
    assert tela._card_nao_efetivadas._valor.text() == "2"
    assert tela._card_nao_efetivadas._detalhe.text() == "40.0% de 5 (Aprovado + Efetivado)"
    assert not tela._card_nao_efetivadas._detalhe.isHidden()
    assert tela._card_taxa_aprovacao._valor.text() == "100.0%", "5 aprovadas + 3 efetivadas... só aprovadas/(aprovadas+negadas)"
    colunas = [tela._modelo_vendedor.headerData(c, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
               for c in range(tela._modelo_vendedor.columnCount())]
    assert "Não Efetivadas" in colunas and "Não Efetivadas (%)" not in colunas, "uma coluna só (número + %) pra não poluir"
    linhas_por_vendedor = {_texto_celula(tela._modelo_vendedor, r, "Vendedor"): r for r in range(tela._modelo_vendedor.rowCount())}
    assert _texto_celula(tela._modelo_vendedor, linhas_por_vendedor["ANA"], "Não Efetivadas") == "2 (66.7%)"
    assert _texto_celula(tela._modelo_vendedor, linhas_por_vendedor["BIA"], "Não Efetivadas") == "0 (0.0%)"
    tela.close()
    print("OK: card mostra '2' e '40.0% de 5 (Aprovado + Efetivado)'; a tabela por vendedor tem uma coluna 'Não Efetivadas' "
          "('2 (66.7%)' / '0 (0.0%)').")

    linha("5b) Dashboard sem nenhuma Aprovada/Efetivada")
    arquivo2 = pasta / "controle2.xlsx"
    _criar_planilha_vazia(arquivo2)
    clientes_mod.CAMINHO_XLSX = propostas_mod.CAMINHO_XLSX = vendedores_mod.CAMINHO_XLSX = equipamentos_mod.CAMINHO_XLSX = arquivo2
    vendedores_mod.adicionar_vendedor("ANA")
    clientes_mod.adicionar_cliente({"CPF/CNPJ": _cpf(0), "CLIENTE": "CLIENTE ANA", "TIPO": "Cliente", "VENDEDOR": "ANA"})
    _add(_cpf(0), "Em Análise", 1000)
    tela = DashboardScreen()
    assert tela._card_nao_efetivadas._valor.text() == "0"
    assert tela._card_nao_efetivadas._detalhe.text() == "Nenhuma proposta Aprovada ou Efetivada"
    tela.close()
    clientes_mod.CAMINHO_XLSX = propostas_mod.CAMINHO_XLSX = vendedores_mod.CAMINHO_XLSX = equipamentos_mod.CAMINHO_XLSX = arquivo
    print("OK: sem Aprovadas nem Efetivadas o card mostra 0 e um texto claro (sem divisão por zero).")

    linha("6) Planilha gravada com a regra antiga: atualizar só as fórmulas de TEMPO")

    def _formula_antiga(i: int) -> str:
        palavras = sorted({"APROVADO"} | bd.PALAVRAS_STATUS_NEGADO)  # regra de antes: Aprovado encerrava
        condicoes = ",".join('UPPER(J%d)="%s"' % (i, palavra) for palavra in palavras)
        return '=IF(A%d="","",IF(OR(%s),"Encerrado",TODAY()-A%d&" dias"))' % (i, condicoes, i)

    wb = openpyxl.load_workbook(arquivo)
    ws = wb[bd.ABA_PROPOSTAS]
    for i in range(2, ws.max_row + 1):
        ws.cell(row=i, column=9).value = _formula_antiga(i)
    ws.cell(row=4, column=9).value = "digitado à mão"  # nao e formula: nao pode ser tocado
    wb.save(arquivo)
    wb.close()

    def _tudo_menos_tempo() -> list:
        w = openpyxl.load_workbook(arquivo)
        try:
            return [(s.title, c.coordinate, c.value) for s in w.worksheets for row in s.iter_rows() for c in row
                    if not (s.title == bd.ABA_PROPOSTAS and c.column == 9 and c.row > 1)]
        finally:
            w.close()

    antes = _tudo_menos_tempo()
    hash_antes = _hash(arquivo)
    assert bd.atualizar_formulas_tempo(arquivo, gravar=False) == 6, "6 fórmulas antigas (a da linha 4 foi digitada à mão)"
    assert _hash(arquivo) == hash_antes, "gravar=False só conta, não grava"
    assert bd.atualizar_formulas_tempo(arquivo) == 6
    assert bd.atualizar_formulas_tempo(arquivo) == 0, "segunda vez: já está em dia"
    assert _tudo_menos_tempo() == antes, "nenhuma outra célula pode ter mudado"
    ws = openpyxl.load_workbook(arquivo)[bd.ABA_PROPOSTAS]
    assert ws.cell(row=4, column=9).value == "digitado à mão"
    assert all(ws.cell(row=i, column=9).value == bd._formula_tempo(i) for i in (2, 3, 5, 6, 7, 8))
    assert "APROVADO" not in ws.cell(row=2, column=9).value
    bd.ler_propostas(arquivo)  # o app continua lendo
    print("OK: 6 fórmulas antigas atualizadas (Aprovado deixou de encerrar); a digitada à mão e todas as outras "
          "células ficaram intactas; rodar de novo não muda nada.")


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
    testar_regras()
    testar_dashboard_core()

    pasta = Path(tempfile.mkdtemp(prefix="_smoke_efetivado_"))
    try:
        testar_telas_e_arquivo(app, pasta)
        linha("TUDO OK")
    finally:
        for modulo in (clientes_mod, propostas_mod, vendedores_mod, equipamentos_mod):
            modulo.CAMINHO_XLSX = config.CAMINHO_XLSX
        sessao_mod.encerrar()
        shutil.rmtree(pasta, ignore_errors=True)


if __name__ == "__main__":
    main()
