"""Valida as telas PySide6 sem precisar abrir uma janela de verdade (roda
com QT_QPA_PLATFORM=offscreen) - confere se os valores exibidos nos cards e
nas tabelas batem com o que core/dashboard.py e core/clientes.py calculam.

Os dois primeiros testes so leem - nao mexem no arquivo real. Os demais
(exclusao, edicao de proposta) escrevem, entao rodam numa copia temporaria.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_desktop.py
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QApplication, QMessageBox

from config import CAMINHO_XLSX
from core import clientes as clientes_mod
from core import dashboard as dashboard_mod
from core import propostas as propostas_mod
from desktop.dialogs.proposta_dialog import PropostaDialog
from desktop.screens.dashboard_screen import DashboardScreen
from desktop.screens.ficha_cliente_screen import FichaClienteScreen


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def testar_dashboard_screen(app: QApplication) -> None:
    linha("1) DashboardScreen")

    tela = DashboardScreen()
    propostas = propostas_mod.listar_propostas()
    totais = dashboard_mod.totais_gerais(propostas)

    assert tela._card_total._valor.text() == str(totais["total_propostas"])
    assert tela._card_em_analise._valor.text() == str(totais["em_analise"])
    assert tela._card_aprovadas._valor.text() == str(totais["aprovadas"])
    assert tela._card_negadas._valor.text() == str(totais["negadas"])
    print(f"Cards batem com totais_gerais(): {totais}")

    detalhamento_esperado = dashboard_mod.detalhamento_por_status(propostas)
    assert tela._modelo_status.rowCount() == len(detalhamento_esperado)
    assert tela._modelo_status.columnCount() == len(detalhamento_esperado.columns)
    print(f"Tabela de detalhamento por status: {tela._modelo_status.rowCount()} linhas (esperado {len(detalhamento_esperado)})")

    vendedor_esperado = dashboard_mod.por_vendedor(propostas)
    assert tela._modelo_vendedor.rowCount() == len(vendedor_esperado)
    print(f"Tabela de desempenho por vendedor: {tela._modelo_vendedor.rowCount()} linhas (esperado {len(vendedor_esperado)})")

    print("\nOK: DashboardScreen exibe exatamente o que core/dashboard.py calcula.")


def testar_ficha_cliente_screen(app: QApplication) -> None:
    linha("2) FichaClienteScreen")

    tela = FichaClienteScreen()
    todos_clientes = clientes_mod.listar_clientes()

    assert tela._lista.count() == len(todos_clientes)
    assert tela._painel_stack.currentIndex() == 0
    print(f"Lista inicial (sem busca): {tela._lista.count()} clientes, painel no estado vazio (indice 0).")

    primeiro_nome = todos_clientes.iloc[0]["CLIENTE"]
    termo = primeiro_nome.split()[0]

    tela._busca.setText(termo)
    esperado_busca = clientes_mod.buscar(termo)
    assert tela._lista.count() == len(esperado_busca), (
        f"busca por '{termo}' deveria retornar {len(esperado_busca)} cliente(s), lista tem {tela._lista.count()}"
    )
    assert tela._painel_stack.currentIndex() == 0  # buscar de novo reseta o painel
    print(f"Busca por '{termo}' filtrou para {tela._lista.count()} cliente(s) (bate com core.clientes.buscar).")

    tela._busca.setText("")
    assert tela._lista.count() == len(todos_clientes)

    # seleciona um cliente que tem propostas (o primeiro da lista de propostas,
    # nao necessariamente o primeiro por ordem alfabetica) pra exercitar o
    # caminho "com historico" tambem, nao so o de lista vazia
    propostas = propostas_mod.listar_propostas()
    cpf_com_proposta = propostas.iloc[0]["CPF"]
    cliente_com_proposta = clientes_mod.buscar_por_cpf(cpf_com_proposta)

    indice_na_lista = next(
        i for i in range(tela._lista.count())
        if tela._lista.item(i).data(256) == cliente_com_proposta["CPF/CNPJ"]  # Qt.ItemDataRole.UserRole == 256
    )
    tela._lista.setCurrentRow(indice_na_lista)

    assert tela._painel_stack.currentIndex() == 1
    assert tela._nome_label.text() == cliente_com_proposta["CLIENTE"]
    assert tela._campo_cpf.text() == cliente_com_proposta["CPF/CNPJ"]
    assert tela._campo_vendedor.text() == (cliente_com_proposta["VENDEDOR"] or "—")

    # isVisible() so reflete a realidade quando a janela foi de fato mostrada
    # na tela (nao e o caso aqui, em modo headless) - isHidden() reflete o
    # setVisible()/hide() que o proprio codigo da tela chamou, entao e o que
    # da pra verificar sem abrir uma janela de verdade.
    historico_esperado = propostas_mod.historico_por_cpf(cpf_com_proposta)
    assert tela._modelo_historico.rowCount() == len(historico_esperado)
    assert tela._tabela_historico.isHidden() is False
    assert tela._historico_vazio.isHidden() is True
    print(
        f"Selecionar '{cliente_com_proposta['CLIENTE']}' preencheu a ficha e o historico "
        f"({tela._modelo_historico.rowCount()} proposta(s), esperado {len(historico_esperado)})."
    )

    # agora um cliente sem nenhuma proposta, pra exercitar o estado vazio do historico
    cpfs_com_proposta = set(propostas["CPF"])
    cliente_sem_proposta = next(
        clientes_mod.buscar_por_cpf(row["CPF/CNPJ"])
        for _, row in todos_clientes.iterrows()
        if row["CPF/CNPJ"] not in cpfs_com_proposta
    )
    indice_sem_proposta = next(
        i for i in range(tela._lista.count())
        if tela._lista.item(i).data(256) == cliente_sem_proposta["CPF/CNPJ"]
    )
    tela._lista.setCurrentRow(indice_sem_proposta)
    assert tela._modelo_historico.rowCount() == 0
    assert tela._tabela_historico.isHidden() is True
    assert tela._historico_vazio.isHidden() is False
    print(f"Selecionar '{cliente_sem_proposta['CLIENTE']}' (sem propostas) mostrou o estado vazio corretamente.")

    print("\nOK: FichaClienteScreen busca/filtra/seleciona e exibe dados+histórico igual ao core.")


def testar_exclusao_cliente(app: QApplication) -> None:
    linha("3) Exclusão de cliente (copia temporaria)")

    tmp_path = CAMINHO_XLSX.parent / "_smoke_test_exclusao.xlsx"
    shutil.copy(CAMINHO_XLSX, tmp_path)
    clientes_mod.CAMINHO_XLSX = tmp_path
    propostas_mod.CAMINHO_XLSX = tmp_path

    # QMessageBox.question e modal (.exec() proprio) - em modo headless trava
    # esperando um clique que nunca vem. Troca por um stub que so responde "Sim".
    mensagens: list[str] = []
    original_question = QMessageBox.question

    def _stub_question(*args, **kwargs):
        mensagens.append(args[2] if len(args) > 2 else "")
        return QMessageBox.StandardButton.Yes

    QMessageBox.question = staticmethod(_stub_question)

    try:
        tela = FichaClienteScreen()
        todos = clientes_mod.listar_clientes()
        propostas = propostas_mod.listar_propostas()
        cpfs_com_proposta = set(propostas["CPF"])

        cliente_sem_proposta = next(
            row for _, row in todos.iterrows() if row["CPF/CNPJ"] not in cpfs_com_proposta
        )
        tela._selecionar_por_cpf(cliente_sem_proposta["CPF/CNPJ"])
        assert tela._cpf_selecionado == cliente_sem_proposta["CPF/CNPJ"]

        tela._excluir_cliente()
        assert "não pode ser desfeita" in mensagens[-1]
        assert "Atenção" not in mensagens[-1]  # sem propostas vinculadas, sem aviso extra
        assert clientes_mod.buscar_por_cpf(cliente_sem_proposta["CPF/CNPJ"]) is None
        print(f"OK: '{cliente_sem_proposta['CLIENTE']}' (sem propostas) excluído, sem aviso extra na confirmação.")

        cpf_com_proposta = propostas.iloc[0]["CPF"]
        tela._selecionar_por_cpf(cpf_com_proposta)
        assert tela._cpf_selecionado == cpf_com_proposta

        tela._excluir_cliente()
        assert "Atenção" in mensagens[-1] and "proposta" in mensagens[-1]
        assert clientes_mod.buscar_por_cpf(cpf_com_proposta) is None
        # a proposta em si continua na planilha (nao apagamos historico)
        assert not propostas_mod.historico_por_cpf(cpf_com_proposta).empty
        print("OK: cliente com propostas vinculadas também foi excluído, com aviso extra na confirmação.")
        print("OK: a(s) proposta(s) dele NÃO foram apagadas (ficam órfãs de propósito, como combinado).")

        print("\nOK: exclusão de cliente funciona nos dois casos (com e sem propostas vinculadas).")
    finally:
        QMessageBox.question = original_question
        tmp_path.unlink(missing_ok=True)


def testar_edicao_proposta(app: QApplication) -> None:
    linha("4) Edição de proposta existente (cópia temporária)")

    tmp_path = CAMINHO_XLSX.parent / "_smoke_test_edicao_proposta.xlsx"
    shutil.copy(CAMINHO_XLSX, tmp_path)
    clientes_mod.CAMINHO_XLSX = tmp_path
    propostas_mod.CAMINHO_XLSX = tmp_path

    # QMessageBox.warning/critical sao modais - se a edicao for rejeitada por
    # algum motivo (valor em branco na proposta escolhida, etc.) elas travam
    # esperando um clique que nunca vem em modo headless. Stub por garantia.
    mensagens: list[str] = []
    original_warning = QMessageBox.warning
    original_critical = QMessageBox.critical

    def _stub_mensagem(*args, **kwargs):
        mensagens.append(args[2] if len(args) > 2 else "")
        return QMessageBox.StandardButton.Ok

    QMessageBox.warning = staticmethod(_stub_mensagem)
    QMessageBox.critical = staticmethod(_stub_mensagem)

    try:
        tela = FichaClienteScreen()
        propostas = propostas_mod.listar_propostas()  # 1 unica leitura do arquivo

        # pega um cliente cuja proposta MAIS RECENTE (linha 0 da tabela, que
        # e a que vamos selecionar) tem status E valor preenchidos - a
        # planilha real tem algumas propostas com esses campos em branco
        # (dado historico real, nao e bug), que sao um caso a parte. Tudo em
        # memoria a partir do `propostas` ja carregado, sem reabrir o arquivo
        # a cada CPF candidato.
        cpf_alvo = None
        for cpf_candidato, grupo in propostas.groupby("CPF"):
            mais_recente = grupo.sort_values("DATA", ascending=False).iloc[0]
            if mais_recente["STATUS"] != "" and not pd.isna(mais_recente["VALOR (R$)"]):
                cpf_alvo = cpf_candidato
                break
        assert cpf_alvo is not None, "nenhum cliente com proposta de status e valor preenchidos encontrado"

        historico_antes = propostas_mod.historico_por_cpf(cpf_alvo)
        assert not historico_antes.empty

        tela._selecionar_por_cpf(cpf_alvo)
        assert tela._cpf_selecionado == cpf_alvo

        # seleciona a primeira linha visivel da tabela de historico
        indice_visual = tela._modelo_historico.index(0, 0)
        tela._tabela_historico.selectionModel().select(
            indice_visual,
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
        )
        indice_real = tela._modelo_historico.indice_real(0)
        status_original = historico_antes.loc[indice_real, "STATUS"]

        # _editar_proposta_selecionada() cria um PropostaDialog e chama
        # .exec() nele, que abre um loop de eventos modal de verdade - sob
        # QT_QPA_PLATFORM=offscreen isso as vezes nao registra o dialogo como
        # "janela modal ativa" (QApplication.activeModalWidget() volta None),
        # entao nao da pra confiar em pegar o dialogo de fora enquanto ele
        # esta aberto. Em vez disso, troca PropostaDialog.exec por uma
        # versao que "clica OK" direto, sem depender de loop de eventos.
        original_exec = PropostaDialog.exec

        def _exec_simulando_edicao(self):
            assert self._status.currentText() == status_original, (
                f"dialogo veio com status {self._status.currentText()!r}, esperado {status_original!r}"
            )
            self._status.setCurrentText(propostas_mod.STATUS_APROVADO)
            self._observacoes.setPlainText("editado no smoke test")
            self._salvar()
            return self.result()

        PropostaDialog.exec = _exec_simulando_edicao
        try:
            tela._editar_proposta_selecionada()
        finally:
            PropostaDialog.exec = original_exec

        historico_depois = propostas_mod.historico_por_cpf(cpf_alvo)
        linha_editada = historico_depois.loc[indice_real]
        assert linha_editada["STATUS"] == propostas_mod.STATUS_APROVADO
        assert linha_editada["OBSERVAÇÕES"] == "editado no smoke test"
        # as outras propostas do mesmo cliente nao podem ter mudado
        assert len(historico_depois) == len(historico_antes)
        print(f"OK: proposta (posição real {indice_real} no arquivo) editada via tela -> STATUS={linha_editada['STATUS']}")

        if mensagens:
            raise AssertionError(f"nao deveria ter mostrado nenhuma mensagem de erro, mostrou: {mensagens}")

        print("\nOK: edição de proposta existente funciona de ponta a ponta (seleção → diálogo → gravação).")
    finally:
        QMessageBox.warning = original_warning
        QMessageBox.critical = original_critical
        tmp_path.unlink(missing_ok=True)


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    testar_dashboard_screen(app)
    testar_ficha_cliente_screen(app)
    testar_exclusao_cliente(app)
    testar_edicao_proposta(app)
    linha("TUDO OK")


if __name__ == "__main__":
    main()
