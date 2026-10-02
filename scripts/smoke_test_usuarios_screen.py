"""Testa a tela Administração/Usuários (troca do PIN de entrada, cadastro de vendedor,
status/carteira, redefinir senha, renomear, transferir carteira, desativar/reativar) sem
abrir uma janela de verdade e sem mexer em nada real - tudo em cópias/arquivos temporários.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_usuarios_screen.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QApplication, QMessageBox

from config import CAMINHO_XLSX

import config
config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
from core import acesso, auth, conta_google
from core import bancos as bancos_mod
from core import clientes as clientes_mod
from core import data_store as bd
from core import sessao as sessao_mod
from core import vendedores as vendedores_mod
from desktop.screens.usuarios_screen import UsuariosScreen
from desktop.widgets.cadastro_vendedores import CadastroVendedores


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
    bancos_mod.CAMINHO_XLSX = clientes_mod.CAMINHO_XLSX = vendedores_mod.CAMINHO_XLSX = tmp_xlsx
    caminho_original_admin = auth.CAMINHO_CREDENCIAIS_ADMIN
    auth.CAMINHO_CREDENCIAIS_ADMIN = tmp_admin_senha
    pasta_acesso = Path(tempfile.mkdtemp(prefix="_smoke_usuarios_acesso_"))
    originais_acesso = (config.CAMINHO_CONTA_GOOGLE, config.CAMINHO_PIN_ACESSO)
    config.CAMINHO_CONTA_GOOGLE = pasta_acesso / "conta_google.dat"
    config.CAMINHO_PIN_ACESSO = pasta_acesso / "acesso_pin.dat"

    try:
        linha("1) Meu PIN: sem PIN explica; com PIN troca (só com o atual certo e 6 números)")
        tela = UsuariosScreen()
        assert not tela._cabecalho_pin.isChecked() and tela._corpo_pin.isHidden(), "recolhido por padrão"
        assert tela._campos_pin.isHidden() and not tela._sem_pin.isHidden(), "sem PIN: só a explicação"

        conta_google._gravar_conexao({"refresh_token": "falso"}, "pessoa.teste@gmail.com")
        acesso.criar_pin("111111")
        tela._atualizar_meu_pin()
        assert not tela._campos_pin.isHidden() and tela._sem_pin.isHidden()
        assert tela._pin_novo.maxLength() == 6

        def trocar(atual, novo, confirmar):
            tela._pin_atual.setText(atual)
            tela._pin_novo.setText(novo)
            tela._pin_novo_confirmar.setText(confirmar)
            tela._trocar_meu_pin()

        trocar("111111", "22222", "22222")
        assert "6 números" in mensagens[-1] and acesso.conferir_pin("111111").certo
        trocar("111111", "222222", "333333")
        assert "não são iguais" in mensagens[-1] and acesso.conferir_pin("111111").certo
        trocar("999999", "222222", "222222")
        assert "incorreto" in mensagens[-1] and acesso.conferir_pin("111111").certo
        print("OK: PIN curto, confirmação diferente e PIN atual errado não trocam nada.")

        trocar("111111", "222222", "222222")
        assert acesso.conferir_pin("222222").certo and not acesso.conferir_pin("111111").certo
        assert tela._pin_atual.text() == "" and "alterado" in mensagens[-1]
        print("OK: PIN trocado, campos limpos.")

        for _ in range(acesso.TENTATIVAS_PERMITIDAS):
            trocar("000000", "333333", "333333")
        assert not acesso.pin_configurado() and "apagado" in mensagens[-1]
        assert tela._campos_pin.isHidden() and not tela._sem_pin.isHidden()
        print("OK: PIN atual errado vezes demais apaga o PIN, e o cartão volta à explicação.")

        assert auth.forca_da_senha("abcdefgh") == "fraca", "so minusculas, sem variedade"
        assert auth.forca_da_senha("Abcdefg1") == "média"
        assert auth.forca_da_senha("Abcdefgh123!") == "forte", "12+ caracteres e 3+ tipos"
        print("OK: forca_da_senha() classifica fraca/média/forte de forma consistente.")

        linha("2) Cadastros > Vendedores (cards): cadastrar mostra a senha inicial; carteira e senha no card")
        assert not hasattr(tela, "_tabela_vendedores"), "os vendedores sairam da Administracao"
        cad = CadastroVendedores()
        cad.resize(1100, 700)
        cad.show()
        QApplication.processEvents()

        def card(nome: str):
            return next(c for c in cad.cards if c.item is not None and c.item.titulo == nome)

        total_antes = len(cad.cards)
        cad.botao_novo.click()
        cad._card_aberto().campos["nome"].setText("Vendedor Tela Teste")
        cad._card_aberto().botoes["salvar"].click()
        assert len(cad.cards) == total_antes + 1 and card("Vendedor Tela Teste").etiqueta.texto() == "Ativo"
        assert "Senha inicial de acesso" in mensagens[-1]
        senha_inicial = mensagens[-1].split("Senha inicial de acesso: ")[1].split()[0]
        assert "Nenhum cliente" in card("Vendedor Tela Teste").detalhe.text() and "senha definida" in card("Vendedor Tela Teste").detalhe.text()
        print(f"OK: '+ Novo vendedor' cadastra ({total_antes} -> {len(cad.cards)} cards), já ativo, e mostra a senha inicial.")

        linha("3) Redefinir senha (três pontinhos)")
        def _senha_local_confere(nome: str, senha: str) -> bool:
            df = bd.ler_vendedores(tmp_xlsx)
            linha_vendedor = df[df["NOME"] == nome].iloc[0]
            return auth.senha_confere(senha, linha_vendedor["SENHA_HASH"], linha_vendedor["SALT"])

        assert _senha_local_confere("Vendedor Tela Teste", senha_inicial)
        respostas_sim.append(False)
        card("Vendedor Tela Teste").acoes["Redefinir senha"].trigger()
        assert _senha_local_confere("Vendedor Tela Teste", senha_inicial), "respondendo Não, nada muda"
        card("Vendedor Tela Teste").acoes["Redefinir senha"].trigger()
        assert not _senha_local_confere("Vendedor Tela Teste", senha_inicial) and "Nova senha" in mensagens[-1]
        print("OK: redefinir senha pergunta antes; 'Sim' gera uma senha nova e invalida a antiga.")

        linha("4) Carteira no card; desativar exige carteira vazia")
        _cliente("11122233396", "CLIENTE DO TELA TESTE", "Vendedor Tela Teste")
        cad.recarregar()
        assert "1 cliente ·" in card("Vendedor Tela Teste").detalhe.text()
        card("Vendedor Tela Teste").acoes["ativo"].trigger()  # confirmação = Sim, mas o core recusa
        assert vendedores_mod.esta_ativo(bd.ler_vendedores(tmp_xlsx).set_index("NOME").loc["Vendedor Tela Teste", "ATIVO"])
        assert "carteira" in mensagens[-1].lower()
        print("OK: o card mostra a carteira; desativar com clientes é recusado, com o motivo explicado.")

        linha("5) Transferir carteira, depois desativar e reativar")
        vendedores_mod.adicionar_vendedor("Vendedor Destino")
        cad.recarregar()
        import PySide6.QtWidgets as _qw
        original_getItem = _qw.QInputDialog.getItem
        _qw.QInputDialog.getItem = staticmethod(lambda *a, **k: ("Vendedor Destino", True))
        try:
            card("Vendedor Tela Teste").acoes["Transferir carteira"].trigger()
        finally:
            _qw.QInputDialog.getItem = original_getItem
        assert clientes_mod.buscar_por_cpf("11122233396")["VENDEDOR"] == "Vendedor Destino"
        assert "1 cliente(s)" in mensagens[-1] and "Nenhum cliente" in card("Vendedor Tela Teste").detalhe.text()
        print("OK: transferir carteira move os clientes e o card atualiza a contagem.")

        card("Vendedor Tela Teste").acoes["ativo"].trigger()
        assert not vendedores_mod.esta_ativo(bd.ler_vendedores(tmp_xlsx).set_index("NOME").loc["Vendedor Tela Teste", "ATIVO"])
        assert card("Vendedor Tela Teste").etiqueta.texto() == "Inativo"
        assert "Vendedor Tela Teste" in vendedores_mod.listar_vendedores(), "some dos ativos, mas continua no histórico"
        assert card("Vendedor Tela Teste").acoes["ativo"].text() == "Reativar" and "excluir" not in card("Vendedor Tela Teste").acoes
        card("Vendedor Tela Teste").acoes["ativo"].trigger()
        assert vendedores_mod.esta_ativo(bd.ler_vendedores(tmp_xlsx).set_index("NOME").loc["Vendedor Tela Teste", "ATIVO"])
        print("OK: com a carteira vazia desativa (etiqueta 'Inativo', sem opção de excluir); reativar volta.")

        linha("6) Renomear pelo lápis (cascata pro cliente já cadastrado)")
        card("Vendedor Destino").botoes["editar"].click()
        cad._card_aberto().campos["nome"].setText("Vendedor Renomeado")
        cad._card_aberto().botoes["salvar"].click()
        assert clientes_mod.buscar_por_cpf("11122233396")["VENDEDOR"] == "Vendedor Renomeado"
        assert "Vendedor Renomeado" in vendedores_mod.listar_vendedores()
        assert "Vendedor Destino" not in vendedores_mod.listar_vendedores()
        print("OK: renomear atualiza o cadastro E o cliente que já estava com o nome antigo.")
        cad.close()

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
        config.CAMINHO_CONTA_GOOGLE, config.CAMINHO_PIN_ACESSO = originais_acesso
        shutil.rmtree(pasta_acesso, ignore_errors=True)
        bancos_mod.CAMINHO_XLSX = clientes_mod.CAMINHO_XLSX = vendedores_mod.CAMINHO_XLSX = CAMINHO_XLSX
        tmp_xlsx.unlink(missing_ok=True)
        tmp_admin_senha.unlink(missing_ok=True)
        sessao_mod.encerrar()


if __name__ == "__main__":
    main()
