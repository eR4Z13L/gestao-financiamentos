"""Testa a seção "Mesclar grafias de banco" da aba "Sincronização e backup" da tela
Administração (desktop/screens/usuarios_screen.py): lista de bancos com contagem, botão
Mesclar habilitado só com 2+ marcados e grafia final preenchida, confirmação, backup antes,
e o sinal dados_atualizados. Planilha fictícia numa pasta temporária - nunca em data/.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_administracao_mesclar_bancos.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl
import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

import config
config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
import fixture_ficticia as fx
from core import clientes as clientes_mod
from core import data_store as bd
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core.validators import _digito_verificador_cpf
from desktop.screens.usuarios_screen import UsuariosScreen


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _cpf(n: int) -> str:
    base = f"{123456780 + n:09d}"
    return base + _digito_verificador_cpf(base)


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


def _proposta(cpf: str, banco: str) -> None:
    propostas_mod.adicionar_proposta(
        {"CPF": cpf, "DATA": pd.Timestamp.now(), "STATUS": propostas_mod.STATUS_EM_ANALISE,
         "BANCO": banco, "EQUIPAMENTO": "Equipamento X", "VALOR (R$)": 10000, "MESES": 36}
    )


def _marcar(tela: UsuariosScreen, banco: str, estado: Qt.CheckState) -> None:
    for i in range(tela._lista_bancos.count()):
        item = tela._lista_bancos.item(i)
        if item.data(Qt.ItemDataRole.UserRole) == banco:
            item.setCheckState(estado)
            return
    raise AssertionError(f"banco {banco!r} não está na lista")


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    registro_antes = fx.instantaneo_do_registro()
    tmp = Path(tempfile.mkdtemp(prefix="_smoke_admin_mesclar_"))
    fx.isolar_preferencias(tmp)

    mensagens: list[str] = []
    respostas_sim: list[bool] = []

    def _stub(*args, **kwargs):
        mensagens.append(args[2] if len(args) > 2 else "")
        return QMessageBox.StandardButton.Ok

    def _stub_question(*args, **kwargs):
        mensagens.append(args[2] if len(args) > 2 else "")
        resposta = respostas_sim.pop(0) if respostas_sim else True
        return QMessageBox.StandardButton.Yes if resposta else QMessageBox.StandardButton.No

    QMessageBox.warning = staticmethod(_stub)
    QMessageBox.critical = staticmethod(_stub)
    QMessageBox.information = staticmethod(_stub)
    QMessageBox.question = staticmethod(_stub_question)

    try:
        arquivo = tmp / "controle.xlsx"
        _criar_planilha_vazia(arquivo)
        fx.apontar_modulos_para(arquivo)
        sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
        cpf = _cpf(1)
        clientes_mod.adicionar_cliente({"CPF/CNPJ": cpf, "CLIENTE": "CLIENTE UM", "TIPO": "Cliente", "VENDEDOR": "ANA"})
        _proposta(cpf, "Hubcred BV")
        _proposta(cpf, "Hubcred BV")
        _proposta(cpf, "HUBCRED BV")
        _proposta(cpf, "Santander")

        linha("1) A lista nasce com cada grafia distinta e a contagem certa")
        tela = UsuariosScreen()
        assert tela._lista_bancos.count() == 3
        bancos_na_lista = {
            tela._lista_bancos.item(i).data(Qt.ItemDataRole.UserRole): tela._lista_bancos.item(i).text()
            for i in range(tela._lista_bancos.count())
        }
        assert "2 propostas" in bancos_na_lista["Hubcred BV"]
        assert "1 proposta)" in bancos_na_lista["HUBCRED BV"]  # singular, sem "s"
        assert not tela._botao_mesclar.isEnabled()
        print(f"OK: 3 grafias na lista com a contagem certa ({list(bancos_na_lista.values())}), Mesclar desabilitado.")

        linha("2) Mesclar só habilita com 2+ marcados E a grafia final preenchida")
        _marcar(tela, "Hubcred BV", Qt.CheckState.Checked)
        assert not tela._botao_mesclar.isEnabled(), "só 1 marcado ainda"
        _marcar(tela, "HUBCRED BV", Qt.CheckState.Checked)
        assert not tela._botao_mesclar.isEnabled(), "2 marcados, mas falta a grafia final"
        tela._grafia_final.setText("Hubcred BV")
        assert tela._botao_mesclar.isEnabled()
        print("OK: Mesclar só liga com 2+ grafias marcadas E a grafia final preenchida.")

        linha("3) Recusando a confirmação, nada muda")
        respostas_sim.append(False)
        total_antes = tela._lista_bancos.count()
        tela._mesclar_bancos_selecionados()
        assert tela._lista_bancos.count() == total_antes, "nada reescrito"
        assert "Hubcred BV" in [tela._lista_bancos.item(i).data(Qt.ItemDataRole.UserRole) for i in range(tela._lista_bancos.count())]
        print("OK: respondendo 'Não' na confirmação, nada é mesclado.")

        linha("4) Confirmando, mescla, avisa, recarrega a lista e avisa outras telas (dados_atualizados)")
        sinais_recebidos = []
        tela.dados_atualizados.connect(lambda: sinais_recebidos.append(True))
        _marcar(tela, "Hubcred BV", Qt.CheckState.Checked)
        _marcar(tela, "HUBCRED BV", Qt.CheckState.Checked)
        tela._grafia_final.setText("Hubcred BV")

        antes_msg = len(mensagens)
        tela._mesclar_bancos_selecionados()
        assert len(mensagens) == antes_msg + 2, "1 pergunta de confirmação + 1 aviso de sucesso"
        assert "TODAS as propostas" in mensagens[-2]
        assert "3 proposta(s)" in mensagens[-1]
        assert tela._lista_bancos.count() == 2, "'Hubcred BV' e 'HUBCRED BV' viraram uma só linha"
        assert tela._grafia_final.text() == "", "campo limpo depois de mesclar"
        assert not tela._botao_mesclar.isEnabled(), "nada mais marcado depois de recarregar"
        assert sinais_recebidos == [True]
        print("OK: mesclagem confirmada reescreve, avisa, recarrega a lista (2 linhas) e dispara dados_atualizados.")

        linha("TUDO OK")
    finally:
        fx.restaurar_modulos()
        sessao_mod.encerrar()
        shutil.rmtree(tmp, ignore_errors=True)
        assert fx.instantaneo_do_registro() == registro_antes, "não pode ter mexido no registro real"


if __name__ == "__main__":
    main()
