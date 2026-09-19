"""Testa a tela Usuários (troca de senha do admin, cadastro de vendedor,
redefinição de senha) sem abrir uma janela de verdade e sem mexer em nada
real - tudo em cópias/arquivos temporários.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_usuarios_screen.py
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QMessageBox

from config import CAMINHO_XLSX

import config
config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
from core import auth
from core import data_store as bd
from core import sessao as sessao_mod
from core import vendedores as vendedores_mod
from desktop.screens.usuarios_screen import UsuariosScreen


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))

    mensagens: list[str] = []

    def _stub(*args, **kwargs):
        mensagens.append(args[2] if len(args) > 2 else "")
        return QMessageBox.StandardButton.Ok

    def _stub_question_sim(*args, **kwargs):
        mensagens.append(args[2] if len(args) > 2 else "")
        return QMessageBox.StandardButton.Yes

    QMessageBox.warning = staticmethod(_stub)
    QMessageBox.critical = staticmethod(_stub)
    QMessageBox.information = staticmethod(_stub)
    QMessageBox.question = staticmethod(_stub_question_sim)

    tmp_xlsx = CAMINHO_XLSX.parent / "_smoke_test_usuarios.xlsx"
    tmp_admin_senha = CAMINHO_XLSX.parent / "_smoke_test_usuarios_admin.json"
    shutil.copy(CAMINHO_XLSX, tmp_xlsx)
    vendedores_mod.CAMINHO_XLSX = tmp_xlsx
    caminho_original_admin = auth.CAMINHO_CREDENCIAIS_ADMIN
    auth.CAMINHO_CREDENCIAIS_ADMIN = tmp_admin_senha

    try:
        linha("1) Trocar a própria senha (Administrador)")
        auth.definir_senha_admin("SenhaAntiga1")

        tela = UsuariosScreen()

        # senha atual errada -> recusa, nao troca nada
        tela._senha_atual.setText("senha errada")
        tela._senha_nova.setText("SenhaNova123")
        tela._senha_nova_confirmar.setText("SenhaNova123")
        tela._trocar_minha_senha()
        assert auth.verificar_senha_admin("SenhaAntiga1"), "senha antiga deveria continuar valendo"
        assert "incorreta" in mensagens[-1].lower()
        print("OK: senha atual errada não troca nada.")

        # senhas novas diferentes -> recusa
        tela._senha_atual.setText("SenhaAntiga1")
        tela._senha_nova.setText("SenhaNova123")
        tela._senha_nova_confirmar.setText("outra-coisa")
        tela._trocar_minha_senha()
        assert auth.verificar_senha_admin("SenhaAntiga1")
        print("OK: confirmação diferente da nova senha não troca nada.")

        # caminho feliz
        tela._senha_atual.setText("SenhaAntiga1")
        tela._senha_nova.setText("SenhaNova123")
        tela._senha_nova_confirmar.setText("SenhaNova123")
        tela._trocar_minha_senha()
        assert auth.verificar_senha_admin("SenhaNova123")
        assert not auth.verificar_senha_admin("SenhaAntiga1")
        assert tela._senha_atual.text() == "", "campos deveriam ser limpos apos trocar"
        print("OK: senha trocada com sucesso, campos limpos.")

        linha("2) Cadastrar vendedor pela tela")
        total_antes = tela._modelo_vendedores.rowCount()
        vendedores_mod.adicionar_vendedor("Vendedor Tela Teste")
        geradas = vendedores_mod.gerar_senhas_iniciais_pendentes()
        assert "Vendedor Tela Teste" in geradas
        tela._carregar_vendedores()
        assert tela._modelo_vendedores.rowCount() == total_antes + 1
        print(f"OK: vendedor cadastrado aparece na tabela ({total_antes} -> {tela._modelo_vendedores.rowCount()}).")

        linha("3) Redefinir senha de um vendedor pela tela")
        # verifica a senha direto no arquivo local (nao via verificar_login,
        # que le do Google Sheets - a sincronizacao esta desligada neste
        # teste de proposito, entao o Sheets nunca veria este vendedor de
        # teste; ver core/vendedores.py sobre a fonte de leitura do login)
        assert "Vendedor Tela Teste" in vendedores_mod.listar_vendedores()

        def _senha_local_confere(nome: str, senha: str) -> bool:
            df = bd.ler_vendedores(tmp_xlsx)
            linha_vendedor = df[df["NOME"] == nome].iloc[0]
            return auth.senha_confere(senha, linha_vendedor["SENHA_HASH"], linha_vendedor["SALT"])

        indice_visual = next(
            i
            for i in range(tela._modelo_vendedores.rowCount())
            if tela._modelo_vendedores.indice_real(i) == "Vendedor Tela Teste"
        )
        tela._tabela_vendedores.selectionModel().select(
            tela._modelo_vendedores.index(indice_visual, 0),
            tela._tabela_vendedores.selectionModel().SelectionFlag.Select
            | tela._tabela_vendedores.selectionModel().SelectionFlag.Rows,
        )
        assert tela._nome_selecionado() == "Vendedor Tela Teste"

        senha_inicial = geradas["Vendedor Tela Teste"]
        assert _senha_local_confere("Vendedor Tela Teste", senha_inicial), "senha inicial deveria conferir antes de redefinir"

        tela._redefinir_senha_selecionado()
        assert "redefinida" in mensagens[-1].lower() or "Nova senha" in mensagens[-1]
        assert not _senha_local_confere("Vendedor Tela Teste", senha_inicial), "senha antiga deveria ter sido invalidada"
        print("OK: redefinir senha pela tela gera uma senha nova e invalida a antiga (conferido no arquivo local).")

        print("\nOK: sem nenhum vendedor selecionado, redefinir avisa em vez de quebrar")
        tela._tabela_vendedores.clearSelection()
        antes_msg = len(mensagens)
        tela._redefinir_senha_selecionado()
        assert len(mensagens) == antes_msg + 1
        print("OK: 'nenhum vendedor selecionado' tratado sem erro.")

        linha("TUDO OK")
    finally:
        auth.CAMINHO_CREDENCIAIS_ADMIN = caminho_original_admin
        vendedores_mod.CAMINHO_XLSX = CAMINHO_XLSX
        tmp_xlsx.unlink(missing_ok=True)
        tmp_admin_senha.unlink(missing_ok=True)
        sessao_mod.encerrar()


if __name__ == "__main__":
    main()
