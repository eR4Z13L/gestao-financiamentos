"""Testa a aba "Sincronização e backup" da tela Administração (desktop/screens/usuarios_screen.py):
"Fazer backup agora", a tabela de backups e "Restaurar" (com o backup de segurança automático
antes, e o sinal dados_atualizados). Planilha fictícia numa pasta temporária - nunca em data/.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_administracao_backup.py
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
from PySide6.QtWidgets import QApplication, QMessageBox

import config
config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
import fixture_ficticia as fx
from core import backup as backup_mod
from core import data_store as bd
from core import sessao as sessao_mod
from core import vendedores as vendedores_mod
from desktop.screens.usuarios_screen import UsuariosScreen


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


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


def _selecionar_backup(tela: UsuariosScreen, caminho) -> None:
    indice_visual = next(
        i for i in range(tela._modelo_backups.rowCount()) if tela._modelo_backups.indice_real(i) == str(caminho)
    )
    tela._tabela_backups.selectionModel().select(
        tela._modelo_backups.index(indice_visual, 0),
        tela._tabela_backups.selectionModel().SelectionFlag.ClearAndSelect
        | tela._tabela_backups.selectionModel().SelectionFlag.Rows,
    )


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    registro_antes = fx.instantaneo_do_registro()
    tmp = Path(tempfile.mkdtemp(prefix="_smoke_admin_backup_"))
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
        vendedores_mod.adicionar_vendedor("Vendedora Original")

        linha("1) A aba nasce vazia (nenhum backup ainda) e Restaurar começa desabilitado")
        tela = UsuariosScreen()
        assert tela._modelo_backups.rowCount() == 0
        assert not tela._botao_restaurar.isEnabled()
        print("OK: sem nenhum backup, a tabela está vazia e o botão Restaurar começa desabilitado.")

        linha("2) 'Fazer backup agora' cria um backup manual e aparece na tabela")
        antes = len(mensagens)
        tela._fazer_backup_agora()
        assert tela._modelo_backups.rowCount() == 1
        assert len(mensagens) == antes + 1
        assert "Backup salvo" in mensagens[-1]
        backups = backup_mod.listar_backups(arquivo)
        assert len(backups) == 1 and backups[0].motivo == backup_mod.MOTIVO_MANUAL
        print(f"OK: backup manual criado ({backups[0].caminho.name}) e listado na tabela.")

        linha("3) Selecionar uma linha habilita Restaurar")
        _selecionar_backup(tela, backups[0].caminho)
        assert tela._backup_selecionado() is not None
        assert tela._botao_restaurar.isEnabled()
        print("OK: com uma linha selecionada, Restaurar fica habilitado.")

        linha("4) Restaurar pede confirmação, faz backup de segurança do estado atual e reflete na tela")
        vendedores_mod.adicionar_vendedor("Vendedora Depois Do Backup")
        tela._carregar_vendedores()
        assert "Vendedora Depois Do Backup" in tela._ativo_por_nome

        sinais_recebidos = []
        tela.dados_atualizados.connect(lambda: sinais_recebidos.append(True))

        antes_msg = len(mensagens)
        antes_backups = tela._modelo_backups.rowCount()
        tela._restaurar_selecionado()

        assert len(mensagens) == antes_msg + 2, "1 pergunta de confirmação + 1 aviso de sucesso"
        assert "TODOS os dados atuais" in mensagens[-2], "a pergunta avisa que é uma substituição completa"
        assert "restaurados" in mensagens[-1].lower()
        assert tela._modelo_backups.rowCount() == antes_backups + 1, "o backup de segurança entrou na lista"
        assert "Vendedora Depois Do Backup" not in tela._ativo_por_nome, "a tabela de vendedores já reflete a restauração"
        assert "Vendedora Original" in tela._ativo_por_nome
        assert sinais_recebidos == [True], "dados_atualizados disparado exatamente uma vez"
        print("OK: Restaurar confirma, cria o backup de segurança, atualiza vendedores na tela e avisa outras telas (dados_atualizados).")

        linha("5) Sem seleção, Restaurar avisa em vez de quebrar")
        tela._tabela_backups.clearSelection()
        antes_msg = len(mensagens)
        tela._restaurar_selecionado()
        assert len(mensagens) == antes_msg + 1
        assert "selecione um backup" in mensagens[-1].lower()
        print("OK: sem seleção, Restaurar avisa (não tenta restaurar nada).")

        linha("6) Recusando a confirmação, nada muda")
        _selecionar_backup(tela, backup_mod.listar_backups(arquivo)[0].caminho)
        respostas_sim.append(False)
        total_antes = tela._modelo_backups.rowCount()
        vendedores_antes = set(tela._ativo_por_nome)
        tela._restaurar_selecionado()
        assert tela._modelo_backups.rowCount() == total_antes, "nenhum backup novo (nem de segurança) foi criado"
        assert set(tela._ativo_por_nome) == vendedores_antes, "nada foi restaurado"
        print("OK: respondendo 'Não' na confirmação, Restaurar não faz nada.")

        linha("7) showEvent recarrega a lista de backups (outro backup pode ter sido feito enquanto a tela sumida)")
        backup_mod.fazer_backup(backup_mod.MOTIVO_MANUAL, arquivo)
        antes = tela._modelo_backups.rowCount()
        tela.show()
        app.processEvents()
        assert tela._modelo_backups.rowCount() == antes + 1
        tela.hide()
        print("OK: reaparecer a tela relê os backups do disco.")

        linha("TUDO OK")
    finally:
        fx.restaurar_modulos()
        sessao_mod.encerrar()
        shutil.rmtree(tmp, ignore_errors=True)
        assert fx.instantaneo_do_registro() == registro_antes, "não pode ter mexido no registro real"


if __name__ == "__main__":
    main()
