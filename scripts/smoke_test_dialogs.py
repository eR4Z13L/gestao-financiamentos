"""Testa os dialogos de cadastro/edicao de cliente e lancamento de proposta,
sem precisar abrir uma janela de verdade (QT_QPA_PLATFORM=offscreen) e sem
mexer no arquivo real - tudo numa copia temporaria.

Chama dialogo._salvar() diretamente (em vez de clicar no botao OK de
verdade), simulando o clique sem precisar de QTest/interacao real.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_dialogs.py
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from config import CAMINHO_XLSX
from core import clientes as clientes_mod
from core import propostas as propostas_mod
from desktop.dialogs.cliente_dialog import ClienteDialog
from desktop.dialogs.proposta_dialog import PropostaDialog


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)

    # QMessageBox.warning/critical sao chamadas modais (.exec() proprio) -
    # em modo headless elas travam esperando um clique que nunca vem. Troca
    # por um stub que so registra a chamada, sem abrir nada.
    mensagens_capturadas: list[str] = []

    def _stub_mensagem(*args, **kwargs):
        texto = args[2] if len(args) > 2 else kwargs.get("text", "")
        mensagens_capturadas.append(str(texto))
        return QMessageBox.StandardButton.Ok

    QMessageBox.warning = staticmethod(_stub_mensagem)
    QMessageBox.critical = staticmethod(_stub_mensagem)

    tmp_path = CAMINHO_XLSX.parent / "_smoke_test_dialogs.xlsx"
    shutil.copy(CAMINHO_XLSX, tmp_path)
    clientes_mod.CAMINHO_XLSX = tmp_path
    propostas_mod.CAMINHO_XLSX = tmp_path

    try:
        linha("1) ClienteDialog - CPF invalido (deve rejeitar)")
        dialogo = ClienteDialog(cliente=None)
        dialogo._cpf.setText("111.111.111-11")
        dialogo._nome.setText("Fulano Invalido")
        dialogo._salvar()
        assert dialogo.result() != QDialog.DialogCode.Accepted
        assert mensagens_capturadas and "inválido" in mensagens_capturadas[-1]
        print(f"OK: CPF invalido nao foi aceito -> \"{mensagens_capturadas[-1]}\"")

        linha("2) ClienteDialog - cadastro valido")
        novo_cpf = "529.982.247-25"  # CPF valido (digito verificador correto), so pra teste
        dialogo = ClienteDialog(cliente=None)
        dialogo._cpf.setText(novo_cpf)
        dialogo._nome.setText("Cliente Dialogo Teste")
        dialogo._tipo.setCurrentText("Cliente")
        dialogo._vendedor.setCurrentText("TESTE")
        dialogo._celular.setText("85999998888")
        dialogo._salvar()
        assert dialogo.result() == QDialog.DialogCode.Accepted
        assert dialogo.cpf_salvo == novo_cpf

        criado = clientes_mod.buscar_por_cpf(novo_cpf)
        assert criado is not None
        assert criado["CLIENTE"] == "CLIENTE DIALOGO TESTE"  # adicionar_cliente sobe pra maiusculas
        print(f"OK: cliente criado via dialogo -> {criado['CLIENTE']} ({criado['CPF/CNPJ']})")

        linha("3) ClienteDialog - edicao")
        dialogo = ClienteDialog(cliente=criado)
        assert dialogo._nome.text() == criado["CLIENTE"]
        dialogo._email.setText("editado@teste.com")
        dialogo._salvar()
        assert dialogo.result() == QDialog.DialogCode.Accepted

        editado = clientes_mod.buscar_por_cpf(novo_cpf)
        assert editado["EMAIL"] == "editado@teste.com"
        print(f"OK: edicao via dialogo persistiu -> EMAIL={editado['EMAIL']}")

        linha("4) PropostaDialog - sem equipamento (deve rejeitar)")
        dialogo = PropostaDialog(novo_cpf, "Cliente Dialogo Teste")
        dialogo._valor.setValue(50000)
        dialogo._banco.setCurrentText("Banco Teste")
        dialogo._salvar()
        assert dialogo.result() != QDialog.DialogCode.Accepted
        assert "quipamento" in mensagens_capturadas[-1]
        print(f"OK: proposta sem equipamento nao foi aceita -> \"{mensagens_capturadas[-1]}\"")

        linha("5) PropostaDialog - lancamento valido")
        historico_antes = propostas_mod.historico_por_cpf(novo_cpf)
        dialogo = PropostaDialog(novo_cpf, "Cliente Dialogo Teste")
        dialogo._valor.setValue(75000)
        dialogo._meses.setValue(36)
        dialogo._equipamento.setCurrentText("Equipamento Dialogo Teste")
        dialogo._banco.setCurrentText("Banco Dialogo Teste")
        dialogo._salvar()
        assert dialogo.result() == QDialog.DialogCode.Accepted

        historico_depois = propostas_mod.historico_por_cpf(novo_cpf)
        assert len(historico_depois) == len(historico_antes) + 1
        nova = historico_depois.iloc[0]
        assert nova["BANCO"] == "Banco Dialogo Teste"
        assert nova["EQUIPAMENTO"] == "Equipamento Dialogo Teste"
        assert nova["VALOR (R$)"] == 75000
        assert nova["MESES"] == 36
        print(f"OK: proposta lancada via dialogo -> {nova['BANCO']} / {nova['EQUIPAMENTO']} / R$ {nova['VALOR (R$)']}")

        linha("TUDO OK")
    finally:
        tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
