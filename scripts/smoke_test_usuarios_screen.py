"""Testa a tela Administração/Usuários (troca de senha do admin, cadastro de vendedor,
status/carteira, redefinir senha, renomear, transferir carteira, desativar/reativar) sem
abrir uma janela de verdade e sem mexer em nada real - tudo em cópias/arquivos temporários.

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
from core import clientes as clientes_mod
from core import data_store as bd
from core import sessao as sessao_mod
from core import vendedores as vendedores_mod
from desktop.screens.usuarios_screen import UsuariosScreen


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _cliente(cpf: str, nome: str, vendedor: str) -> None:
    clientes_mod.adicionar_cliente({"CPF/CNPJ": cpf, "CLIENTE": nome, "TIPO": "Cliente", "VENDEDOR": vendedor})


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))

    mensagens: list[str] = []
    respostas_sim: list[bool] = []  # fila de respostas pras confirmacoes (question); default Yes

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

    tmp_xlsx = CAMINHO_XLSX.parent / "_smoke_test_usuarios.xlsx"
    tmp_admin_senha = CAMINHO_XLSX.parent / "_smoke_test_usuarios_admin.json"
    shutil.copy(CAMINHO_XLSX, tmp_xlsx)
    clientes_mod.CAMINHO_XLSX = vendedores_mod.CAMINHO_XLSX = tmp_xlsx
    caminho_original_admin = auth.CAMINHO_CREDENCIAIS_ADMIN
    auth.CAMINHO_CREDENCIAIS_ADMIN = tmp_admin_senha

    try:
        linha("1) Trocar a própria senha (Administrador): mínimo 8, indicador de força")
        auth.definir_senha_admin("SenhaAntiga1")
        tela = UsuariosScreen()
        assert not tela._cabecalho_senha.isChecked() and tela._corpo_senha.isHidden(), "recolhida por padrão"

        tela._senha_nova.setText("curta1")
        assert "Força: fraca" in tela._forca_senha.text()
        tela._senha_atual.setText("SenhaAntiga1")
        tela._senha_nova_confirmar.setText("curta1")
        tela._trocar_minha_senha()
        assert auth.verificar_senha_admin("SenhaAntiga1"), "menos de 8 caracteres não pode trocar"
        assert "8 caracteres" in mensagens[-1]
        print("OK: senha nova com menos de 8 caracteres é recusada, com o indicador de força mostrando 'fraca'.")

        tela._senha_atual.setText("senha errada")
        tela._senha_nova.setText("SenhaNova123")
        tela._senha_nova_confirmar.setText("SenhaNova123")
        tela._trocar_minha_senha()
        assert auth.verificar_senha_admin("SenhaAntiga1")
        assert "incorreta" in mensagens[-1].lower()
        print("OK: senha atual errada não troca nada.")

        tela._senha_atual.setText("SenhaAntiga1")
        tela._senha_nova.setText("SenhaNova123")
        tela._senha_nova_confirmar.setText("outra-coisa-diferente")
        tela._trocar_minha_senha()
        assert auth.verificar_senha_admin("SenhaAntiga1")
        print("OK: confirmação diferente da nova senha não troca nada.")

        tela._senha_atual.setText("SenhaAntiga1")
        tela._senha_nova.setText("SenhaNova123")
        tela._senha_nova_confirmar.setText("SenhaNova123")
        tela._trocar_minha_senha()
        assert auth.verificar_senha_admin("SenhaNova123") and not auth.verificar_senha_admin("SenhaAntiga1")
        assert tela._senha_atual.text() == "" and tela._forca_senha.text() == "", "campos limpos após trocar"
        print("OK: senha trocada com sucesso (>= 8 caracteres), campos limpos.")

        assert auth.forca_da_senha("abcdefgh") == "fraca", "so minusculas, sem variedade"
        assert auth.forca_da_senha("Abcdefg1") == "média"
        assert auth.forca_da_senha("Abcdefgh123!") == "forte", "12+ caracteres e 3+ tipos"
        print("OK: forca_da_senha() classifica fraca/média/forte de forma consistente.")

        linha("2) Cadastrar vendedor pela tela; status/carteira/senha na tabela")
        total_antes = tela._modelo_vendedores.rowCount()
        vendedores_mod.adicionar_vendedor("Vendedor Tela Teste")
        geradas = vendedores_mod.gerar_senhas_iniciais_pendentes()
        assert "Vendedor Tela Teste" in geradas
        tela._carregar_vendedores()
        assert tela._modelo_vendedores.rowCount() == total_antes + 1
        assert tela._ativo_por_nome["Vendedor Tela Teste"] is True, "vendedor novo nasce ativo"
        print(f"OK: vendedor cadastrado aparece na tabela ({total_antes} -> {tela._modelo_vendedores.rowCount()}), já ativo.")

        def _selecionar(nome: str) -> None:
            indice_visual = next(
                i for i in range(tela._modelo_vendedores.rowCount()) if tela._modelo_vendedores.indice_real(i) == nome
            )
            tela._tabela_vendedores.selectionModel().select(
                tela._modelo_vendedores.index(indice_visual, 0),
                tela._tabela_vendedores.selectionModel().SelectionFlag.ClearAndSelect
                | tela._tabela_vendedores.selectionModel().SelectionFlag.Rows,
            )
            assert tela._nome_selecionado() == nome

        _selecionar("Vendedor Tela Teste")
        assert tela._botao_desativar.text() == "Desativar", "ativo -> o botão oferece desativar"

        linha("3) Redefinir senha de um vendedor pela tela")
        def _senha_local_confere(nome: str, senha: str) -> bool:
            df = bd.ler_vendedores(tmp_xlsx)
            linha_vendedor = df[df["NOME"] == nome].iloc[0]
            return auth.senha_confere(senha, linha_vendedor["SENHA_HASH"], linha_vendedor["SALT"])

        senha_inicial = geradas["Vendedor Tela Teste"]
        assert _senha_local_confere("Vendedor Tela Teste", senha_inicial)
        tela._redefinir_senha_selecionado()
        assert not _senha_local_confere("Vendedor Tela Teste", senha_inicial), "senha antiga invalidada"
        print("OK: redefinir senha pela tela gera uma senha nova e invalida a antiga.")

        tela._tabela_vendedores.clearSelection()
        antes_msg = len(mensagens)
        tela._redefinir_senha_selecionado()
        assert len(mensagens) == antes_msg + 1
        print("OK: sem seleção, redefinir avisa em vez de quebrar.")

        linha("4) Status, carteira e desativar (exige carteira vazia)")
        _cliente("11122233396", "CLIENTE DO TELA TESTE", "Vendedor Tela Teste")
        tela._carregar_vendedores()
        _selecionar("Vendedor Tela Teste")
        linha_visual = next(
            i for i in range(tela._modelo_vendedores.rowCount()) if tela._modelo_vendedores.indice_real(i) == "Vendedor Tela Teste"
        )
        assert tela._modelo_vendedores.data(tela._modelo_vendedores.index(linha_visual, 2)) == "1", "carteira = 1"
        antes_msg = len(mensagens)
        tela._alternar_ativo_selecionado()  # confirmação = Sim (default da fila), mas o core recusa: carteira nao vazia
        assert vendedores_mod.esta_ativo(bd.ler_vendedores(tmp_xlsx).set_index("NOME").loc["Vendedor Tela Teste", "ATIVO"])
        assert "carteira" in mensagens[-1].lower()
        print("OK: desativar com carteira não vazia é recusado, com o motivo explicado.")

        linha("5) Transferir carteira, depois desativar (agora com carteira vazia)")
        vendedores_mod.adicionar_vendedor("Vendedor Destino")
        tela._carregar_vendedores()
        _selecionar("Vendedor Tela Teste")

        import PySide6.QtWidgets as _qw
        original_getItem = _qw.QInputDialog.getItem
        _qw.QInputDialog.getItem = staticmethod(lambda *a, **k: ("Vendedor Destino", True))
        try:
            tela._transferir_carteira_selecionado()
        finally:
            _qw.QInputDialog.getItem = original_getItem
        assert clientes_mod.buscar_por_cpf("11122233396")["VENDEDOR"] == "Vendedor Destino"
        print("OK: transferir carteira move os clientes (o CPF de teste agora está com 'Vendedor Destino').")

        tela._carregar_vendedores()
        _selecionar("Vendedor Tela Teste")
        tela._alternar_ativo_selecionado()
        assert not vendedores_mod.esta_ativo(bd.ler_vendedores(tmp_xlsx).set_index("NOME").loc["Vendedor Tela Teste", "ATIVO"])
        print("OK: com a carteira vazia, desativar funciona.")

        tela._carregar_vendedores()
        assert "Vendedor Tela Teste" not in vendedores_mod.listar_vendedores_ativos()
        assert "Vendedor Tela Teste" in vendedores_mod.listar_vendedores(), "some dos ativos, mas continua no histórico"
        _selecionar("Vendedor Tela Teste")
        assert tela._botao_desativar.text() == "Reativar", "inativo -> o botão oferece reativar"

        tela._alternar_ativo_selecionado()
        assert vendedores_mod.esta_ativo(bd.ler_vendedores(tmp_xlsx).set_index("NOME").loc["Vendedor Tela Teste", "ATIVO"])
        print("OK: reativar funciona e volta a listar_vendedores_ativos().")

        linha("6) Renomear vendedor (cascata pro cliente já cadastrado)")
        import PySide6.QtWidgets as _qw
        original_getText = _qw.QInputDialog.getText
        _qw.QInputDialog.getText = staticmethod(lambda *a, **k: ("Vendedor Renomeado", True))
        try:
            tela._carregar_vendedores()
            _selecionar("Vendedor Destino")
            tela._renomear_selecionado()
        finally:
            _qw.QInputDialog.getText = original_getText
        assert clientes_mod.buscar_por_cpf("11122233396")["VENDEDOR"] == "Vendedor Renomeado"
        assert "Vendedor Renomeado" in vendedores_mod.listar_vendedores()
        assert "Vendedor Destino" not in vendedores_mod.listar_vendedores()
        print("OK: renomear atualiza o cadastro E o cliente que já estava com o nome antigo.")

        linha("7) core.vendedores: validações extras (sem passar pela tela)")
        try:
            vendedores_mod.transferir_carteira("Vendedor Renomeado", "Vendedor Que Nao Existe")
            raise AssertionError("deveria recusar destino inexistente")
        except vendedores_mod.ErroVendedor as exc:
            assert "não encontrado" in str(exc)
        try:
            vendedores_mod.transferir_carteira("Vendedor Renomeado", "Vendedor Renomeado")
            raise AssertionError("deveria recusar origem == destino")
        except vendedores_mod.ErroVendedor as exc:
            assert "mesmo vendedor" in str(exc)
        vendedores_mod.adicionar_vendedor("Vendedor Inativo Alvo")
        vendedores_mod.desativar_vendedor("Vendedor Inativo Alvo")
        try:
            vendedores_mod.transferir_carteira("Vendedor Renomeado", "Vendedor Inativo Alvo")
            raise AssertionError("deveria recusar destino desativado")
        except vendedores_mod.ErroVendedor as exc:
            assert "desativado" in str(exc)
        print("OK: transferir_carteira recusa destino inexistente, origem==destino e destino desativado.")

        try:
            vendedores_mod.renomear_vendedor("Vendedor Renomeado", "")
            raise AssertionError("deveria recusar nome em branco")
        except vendedores_mod.ErroVendedor as exc:
            assert "em branco" in str(exc)
        try:
            vendedores_mod.renomear_vendedor("Vendedor Renomeado", "vendedor inativo alvo")  # so muda a caixa
            raise AssertionError("deveria recusar duplicar outro vendedor (mesmo so na caixa)")
        except vendedores_mod.ErroVendedor as exc:
            assert "já existe" in str(exc).lower()
        try:
            vendedores_mod.desativar_vendedor("Ninguem Com Esse Nome")
            raise AssertionError("deveria recusar vendedor inexistente")
        except vendedores_mod.ErroVendedor as exc:
            assert "não encontrado" in str(exc)
        print("OK: renomear_vendedor recusa nome em branco e duplicata (mesmo só na caixa); desativar recusa inexistente.")

        # verificar_login le do Google Sheets (rede) - a recusa de vendedor desativado
        # (mesma regra de esta_ativo()) fica coberta so pelas checagens abaixo
        assert not vendedores_mod.esta_ativo("não") and not vendedores_mod.esta_ativo("NÃO") and not vendedores_mod.esta_ativo(" Não ")
        assert vendedores_mod.esta_ativo("") and vendedores_mod.esta_ativo(None) and vendedores_mod.esta_ativo("Sim")
        print("OK: esta_ativo() só desativa com 'Não' (sem diferenciar maiúsculas/espaços); vazio conta como ativo.")

        linha("TUDO OK")
    finally:
        auth.CAMINHO_CREDENCIAIS_ADMIN = caminho_original_admin
        clientes_mod.CAMINHO_XLSX = vendedores_mod.CAMINHO_XLSX = CAMINHO_XLSX
        tmp_xlsx.unlink(missing_ok=True)
        tmp_admin_senha.unlink(missing_ok=True)
        sessao_mod.encerrar()


if __name__ == "__main__":
    main()
