"""Testa filtros (vendedor, tipo, periodo de cadastro), ordenacao e contador da
lista de clientes - as regras em core/clientes.py e a tela FichaClienteScreen.
Tudo com clientes FICTICIOS numa planilha temporaria (nomes com acento, empates
de data, cliente sem data de cadastro e um vendedor com grafia diferente).

Rodar com: venv/Scripts/python.exe scripts/smoke_test_filtros_clientes.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl
import pandas as pd
from PySide6.QtCore import QDate
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

import config
config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
from core import clientes as clientes_mod
from core import data_store as bd
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import vendedores as vendedores_mod
from core.validators import apenas_digitos, cpf_cnpj_valido, _digito_verificador_cpf
from desktop.dialogs.cliente_dialog import ClienteDialog
from desktop.screens.ficha_cliente_screen import FichaClienteScreen


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _cpf(n: int) -> str:
    base = f"{123456780 + n:09d}"
    cpf = base + _digito_verificador_cpf(base)
    assert cpf_cnpj_valido(cpf), cpf
    return cpf


# (nome, vendedor, tipo, data de cadastro)
CLIENTES = [
    ("ÁLVARO ZETA", "ANA", "Cliente", pd.Timestamp(2026, 1, 10)),
    ("BRUNA ALFA", "BIA", "Cliente", pd.Timestamp(2026, 2, 15)),
    ("CARLA OMEGA", "BIA", "Cliente", pd.Timestamp(2026, 1, 5)),
    ("DANIEL GAMA", "BIA", "Avalista", pd.Timestamp(2026, 3, 1)),
    ("ÉRICA BETA", "ANA", "Avalista", pd.Timestamp(2026, 2, 15)),
    ("FÁBIO DELTA", "ANA", "Cliente", pd.Timestamp(2026, 3, 20)),
    ("GABRIELA SEM DATA", "ANA", "Cliente", None),
    ("HELENA EXTRA", "ana", "Cliente", pd.Timestamp(2026, 1, 10)),  # grafia diferente do vendedor
]

A_Z = ["ÁLVARO ZETA", "BRUNA ALFA", "CARLA OMEGA", "DANIEL GAMA", "ÉRICA BETA", "FÁBIO DELTA", "GABRIELA SEM DATA", "HELENA EXTRA"]
MAIS_RECENTE = ["FÁBIO DELTA", "DANIEL GAMA", "BRUNA ALFA", "ÉRICA BETA", "ÁLVARO ZETA", "HELENA EXTRA", "CARLA OMEGA", "GABRIELA SEM DATA"]
MAIS_ANTIGO = ["CARLA OMEGA", "ÁLVARO ZETA", "HELENA EXTRA", "BRUNA ALFA", "ÉRICA BETA", "DANIEL GAMA", "FÁBIO DELTA", "GABRIELA SEM DATA"]


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


def _nomes(df: pd.DataFrame) -> list[str]:
    return df["CLIENTE"].tolist()


def _nomes_da_lista(tela: FichaClienteScreen) -> list[str]:
    return [tela._lista.item(i).text().split(" — ")[0] for i in range(tela._lista.count())]


def testar_core() -> None:
    linha("1) core/clientes.py - ordenação")
    assert _nomes(clientes_mod.listar_clientes()) == A_Z, "A-Z sem acento: ÁLVARO antes de BRUNA, ÉRICA entre DANIEL e FÁBIO"
    assert _nomes(clientes_mod.buscar("")) == A_Z
    for chave, esperado in (
        (clientes_mod.ORDENACAO_NOME_AZ, A_Z),
        (clientes_mod.ORDENACAO_NOME_ZA, A_Z[::-1]),
        (clientes_mod.ORDENACAO_CADASTRO_RECENTE, MAIS_RECENTE),
        (clientes_mod.ORDENACAO_CADASTRO_ANTIGO, MAIS_ANTIGO),
    ):
        assert _nomes(clientes_mod.listar_clientes(chave)) == esperado, (chave, _nomes(clientes_mod.listar_clientes(chave)))
    assert [r for _, r in clientes_mod.ORDENACAO_OPCOES] == [
        "Nome (A-Z)", "Nome (Z-A)", "Data de cadastro (mais recente primeiro)", "Data de cadastro (mais antigo primeiro)"]
    try:
        clientes_mod.listar_clientes("qualquer_coisa")
        raise AssertionError("ordenação desconhecida deveria dar erro")
    except ValueError:
        pass
    print("OK: 4 ordenações certas (nome sem acento; empate de data desempata por nome; sem data de cadastro sempre no fim).")

    linha("1b) core/clientes.py - filtros combináveis")
    assert _nomes(clientes_mod.buscar(vendedor="ANA")) == ["ÁLVARO ZETA", "ÉRICA BETA", "FÁBIO DELTA", "GABRIELA SEM DATA", "HELENA EXTRA"], \
        "vendedor sem diferenciar maiúsculas ('ana' entra em 'ANA')"
    assert _nomes(clientes_mod.buscar(vendedor="  bia ")) == ["BRUNA ALFA", "CARLA OMEGA", "DANIEL GAMA"]
    assert _nomes(clientes_mod.buscar(tipo="Avalista")) == ["DANIEL GAMA", "ÉRICA BETA"]
    assert _nomes(clientes_mod.buscar(vendedor="ANA", tipo="Cliente")) == ["ÁLVARO ZETA", "FÁBIO DELTA", "GABRIELA SEM DATA", "HELENA EXTRA"]
    print("OK: vendedor e tipo filtram (sem diferenciar maiúsculas) e combinam entre si.")

    d = pd.Timestamp
    assert _nomes(clientes_mod.buscar(cadastro_de=d(2026, 2, 15), cadastro_ate=d(2026, 3, 1))) == ["BRUNA ALFA", "DANIEL GAMA", "ÉRICA BETA"], \
        "as duas pontas do período entram"
    assert _nomes(clientes_mod.buscar(cadastro_de=d(2026, 3, 1))) == ["DANIEL GAMA", "FÁBIO DELTA"]
    assert _nomes(clientes_mod.buscar(cadastro_ate=d(2026, 1, 10))) == ["ÁLVARO ZETA", "CARLA OMEGA", "HELENA EXTRA"]
    assert "GABRIELA SEM DATA" not in _nomes(clientes_mod.buscar(cadastro_de=d(2000, 1, 1))), "sem data de cadastro nunca entra num período"
    assert _nomes(clientes_mod.buscar(cadastro_de=d(2026, 3, 1), cadastro_ate=d(2026, 2, 1))) == [], "período invertido: vazio"
    print("OK: período de cadastro com as duas pontas incluídas; quem não tem data fica de fora.")

    assert _nomes(clientes_mod.buscar("eta", vendedor="ANA", cadastro_de=d(2026, 2, 1))) == ["ÉRICA BETA"]
    assert _nomes(clientes_mod.buscar("eta", vendedor="ANA")) == ["ÁLVARO ZETA", "ÉRICA BETA"]
    cpf_bruna = clientes_mod.buscar("BRUNA").iloc[0]["CPF/CNPJ"]
    assert _nomes(clientes_mod.buscar(apenas_digitos(cpf_bruna), tipo="Cliente")) == ["BRUNA ALFA"]
    assert _nomes(clientes_mod.buscar(cpf_bruna, tipo="Avalista")) == [], "busca por CPF + filtro que exclui = vazio"
    assert _nomes(clientes_mod.buscar("a", vendedor="ANA", tipo="Cliente", ordenacao=clientes_mod.ORDENACAO_CADASTRO_ANTIGO)) == \
        ["ÁLVARO ZETA", "HELENA EXTRA", "FÁBIO DELTA", "GABRIELA SEM DATA"]
    print("OK: busca por nome/CPF + vendedor + tipo + período + ordenação, todos ao mesmo tempo.")


class _Mensagens:
    def __init__(self) -> None:
        self.textos: list[str] = []
        self._orig = (QMessageBox.warning, QMessageBox.critical, QMessageBox.information)

    def __enter__(self):
        def _stub(*args, **kwargs):
            self.textos.append(str(args[2]) if len(args) > 2 else "")
            return QMessageBox.StandardButton.Ok

        QMessageBox.warning = QMessageBox.critical = QMessageBox.information = staticmethod(_stub)
        return self

    def __exit__(self, *_):
        QMessageBox.warning, QMessageBox.critical, QMessageBox.information = self._orig


def _escolher(combo, texto: str) -> None:
    indice = combo.findText(texto)
    assert indice >= 0, f"{texto!r} nao esta no combo: {[combo.itemText(i) for i in range(combo.count())]}"
    combo.setCurrentIndex(indice)


def testar_tela(app: QApplication, msgs: _Mensagens, arquivo: Path) -> None:
    linha("2) Tela: controles, contador e combinação")
    tela = FichaClienteScreen()
    tela.show()
    app.processEvents()

    assert _nomes_da_lista(tela) == A_Z and tela._contador.text() == "8 cliente(s)"
    assert [tela._filtro_vendedor.itemText(i) for i in range(tela._filtro_vendedor.count())] == ["Todos", "ANA", "BIA"]
    assert [tela._filtro_tipo.itemText(i) for i in range(tela._filtro_tipo.count())] == ["Todos", "Cliente", "Avalista"]
    assert [tela._ordenacao.itemText(i) for i in range(tela._ordenacao.count())] == [r for _, r in clientes_mod.ORDENACAO_OPCOES]
    assert not tela._botao_limpar_filtros.isEnabled(), "sem filtro ativo nao ha o que limpar"
    print("OK: abre com todos os clientes em A-Z, contador '8 cliente(s)', combos com as opções certas.")

    _escolher(tela._filtro_vendedor, "ANA")
    assert len(_nomes_da_lista(tela)) == 5 and tela._contador.text() == "5 cliente(s)"
    _escolher(tela._filtro_tipo, "Cliente")
    assert _nomes_da_lista(tela) == ["ÁLVARO ZETA", "FÁBIO DELTA", "GABRIELA SEM DATA", "HELENA EXTRA"]
    assert tela._contador.text() == "4 cliente(s)" and tela._botao_limpar_filtros.isEnabled()
    tela._busca.setText("zeta")
    assert _nomes_da_lista(tela) == ["ÁLVARO ZETA"] and tela._contador.text() == "1 cliente(s)"
    tela._busca.setText("")
    assert tela._contador.text() == "4 cliente(s)"
    print("OK: vendedor + tipo combinados (8 -> 5 -> 4) e em conjunto com a busca; contador acompanha.")

    linha("2b) Período de cadastro (digitando)")
    _escolher(tela._filtro_vendedor, "Todos")
    _escolher(tela._filtro_tipo, "Todos")
    chamadas: list[int] = []
    original_buscar = clientes_mod.buscar
    clientes_mod.buscar = lambda *a, **k: (chamadas.append(1), original_buscar(*a, **k))[1]
    try:
        QTest.keyClicks(tela._filtro_cadastro_de.campo, "15022026")
        assert len(chamadas) == 1, f"a lista deveria ser relida SO quando a data ficou completa, foi {len(chamadas)}x"
        assert tela._contador.text() == "4 cliente(s)"  # BRUNA, ÉRICA, DANIEL, FÁBIO: exclui cadastro antes de 15/02 e quem nao tem data
        QTest.keyClicks(tela._filtro_cadastro_ate.campo, "01032026")
    finally:
        clientes_mod.buscar = original_buscar
    assert sorted(_nomes_da_lista(tela)) == ["BRUNA ALFA", "DANIEL GAMA", "ÉRICA BETA"] and tela._contador.text() == "3 cliente(s)"
    print("OK: digitar a data só relê a lista quando ela fica completa; 15/02 a 01/03 -> 3 clientes.")

    tela._filtro_cadastro_de.campo.setText("01/03/2026")
    tela._filtro_cadastro_ate.campo.setText("15/02/2026")
    assert tela._lista.count() == 0 and "0 cliente(s)" in tela._contador.text() and "maior que a final" in tela._contador.text()
    tela._filtro_cadastro_de.campo.setText("31/02/2026")  # completa e inexistente
    assert tela._filtro_cadastro_de.esta_invalido() and "inválida (ignorada)" in tela._contador.text()
    assert tela._filtro_cadastro_de.campo.property("invalido") is True
    tela._filtro_cadastro_de.limpar()
    tela._filtro_cadastro_ate.campo.setText("31/12/2099")  # futuro e aceito em filtro
    assert not tela._filtro_cadastro_ate.esta_invalido() and tela._lista.count() == 7
    print("OK: período invertido mostra aviso (0 clientes); data inexistente é ignorada com aviso; futuro é aceito.")

    linha("2c) Limpar filtros (mantém busca e ordenação)")
    _escolher(tela._filtro_vendedor, "BIA")
    _escolher(tela._ordenacao, "Nome (Z-A)")
    tela._busca.setText("a")
    tela._botao_limpar_filtros.click()
    assert tela._filtro_vendedor.currentIndex() == 0 and tela._filtro_tipo.currentIndex() == 0
    assert tela._filtro_cadastro_de.texto() == "" and tela._filtro_cadastro_ate.texto() == ""
    assert tela._busca.text() == "a" and tela._ordenacao.currentText() == "Nome (Z-A)"
    esperado = _nomes(clientes_mod.buscar("a", ordenacao=clientes_mod.ORDENACAO_NOME_ZA))
    assert _nomes_da_lista(tela) == esperado and tela._contador.text() == f"{len(esperado)} cliente(s)"
    assert not tela._botao_limpar_filtros.isEnabled()
    tela._busca.setText("")
    print("OK: 'Limpar filtros' zera vendedor/tipo/período; a busca e a ordenação continuam.")

    linha("3) Tela: ordenação")
    for texto, esperado in (
        ("Nome (A-Z)", A_Z),
        ("Nome (Z-A)", A_Z[::-1]),
        ("Data de cadastro (mais recente primeiro)", MAIS_RECENTE),
        ("Data de cadastro (mais antigo primeiro)", MAIS_ANTIGO),
    ):
        _escolher(tela._ordenacao, texto)
        assert _nomes_da_lista(tela) == esperado, (texto, _nomes_da_lista(tela))
    print("OK: as 4 opções reordenam a lista (nome sem acento; data com desempate por nome).")

    linha("3b) Ficha aberta sobrevive a mudar ordenação/filtro (se o cliente continua na lista)")
    _escolher(tela._ordenacao, "Nome (A-Z)")
    cpf_daniel = tela._lista.item(A_Z.index("DANIEL GAMA")).data(256)
    tela._selecionar_por_cpf(cpf_daniel)
    assert tela._painel_stack.currentIndex() == 1 and tela._nome_label.text() == "DANIEL GAMA"
    _escolher(tela._ordenacao, "Data de cadastro (mais recente primeiro)")
    assert tela._painel_stack.currentIndex() == 1 and tela._cpf_selecionado == cpf_daniel, "reordenar nao pode fechar a ficha"
    assert tela._lista.currentRow() == MAIS_RECENTE.index("DANIEL GAMA") and tela._lista.currentRow() == 1
    _escolher(tela._filtro_tipo, "Avalista")  # DANIEL e Avalista: continua
    assert tela._painel_stack.currentIndex() == 1 and tela._cpf_selecionado == cpf_daniel
    _escolher(tela._filtro_tipo, "Cliente")  # DANIEL nao e Cliente: sai da lista
    assert tela._painel_stack.currentIndex() == 0 and tela._cpf_selecionado is None
    tela._botao_limpar_filtros.click()
    print("OK: ficha continua aberta enquanto o cliente está na lista; some junto se um filtro o exclui.")

    linha("4) Cadastrar/editar com filtro ativo não pode 'sumir' com o cliente")
    original_exec = ClienteDialog.exec
    try:
        _escolher(tela._filtro_vendedor, "ANA")
        _escolher(tela._filtro_tipo, "Cliente")
        assert tela._contador.text() == "4 cliente(s)"

        cpf_novo = _cpf(50)

        def _exec_cadastro(self):  # simula preencher e salvar um cliente do vendedor BIA (fora do filtro ANA)
            clientes_mod.adicionar_cliente({"CPF/CNPJ": cpf_novo, "CLIENTE": "IRENE NOVA", "TIPO": "Cliente", "VENDEDOR": "BIA"})
            self.cpf_salvo = cpf_novo
            self.accept()
            return QDialog.DialogCode.Accepted

        ClienteDialog.exec = _exec_cadastro
        tela._abrir_cadastro_cliente()
        assert tela._filtro_vendedor.currentIndex() == 0 and tela._filtro_tipo.currentIndex() == 0, "filtros limpos pra mostrar o novo"
        assert tela._cpf_selecionado == cpf_novo and tela._nome_label.text() == "IRENE NOVA" and tela._painel_stack.currentIndex() == 1
        assert tela._contador.text() == "9 cliente(s)"
        print("OK: cliente novo fora do filtro atual: filtros limpos e a ficha dele abre.")

        # editar mantendo o cliente dentro do filtro: filtro e ficha atualizada continuam
        _escolher(tela._filtro_vendedor, "BIA")
        tela._selecionar_por_cpf(cpf_novo)

        def _exec_edicao_email(self):
            clientes_mod.atualizar_cliente(cpf_novo, {"CPF/CNPJ": cpf_novo, "CLIENTE": "IRENE NOVA", "TIPO": "Cliente", "EMAIL": "irene@exemplo.com"})
            self.cpf_salvo = cpf_novo
            self.accept()
            return QDialog.DialogCode.Accepted

        ClienteDialog.exec = _exec_edicao_email
        tela._abrir_edicao_cliente()
        assert tela._filtro_vendedor.currentText() == "BIA", "continua no filtro: nao precisa limpar"
        assert tela._campo_email.text() == "irene@exemplo.com", "ficha aberta tem que mostrar o que acabou de ser salvo"
        print("OK: editar quem continua no filtro mantém o filtro e atualiza a ficha aberta.")

        # editar tirando o cliente do filtro (troca de vendedor)
        def _exec_troca_vendedor(self):
            clientes_mod.atualizar_cliente(cpf_novo, {"CPF/CNPJ": cpf_novo, "CLIENTE": "IRENE NOVA", "TIPO": "Cliente", "VENDEDOR": "ANA"})
            self.cpf_salvo = cpf_novo
            self.accept()
            return QDialog.DialogCode.Accepted

        ClienteDialog.exec = _exec_troca_vendedor
        tela._abrir_edicao_cliente()
        assert tela._filtro_vendedor.currentIndex() == 0 and tela._cpf_selecionado == cpf_novo
        assert tela._campo_vendedor.text() == "ANA"
        print("OK: editar e sair do filtro atual: filtros limpos e a ficha continua na tela.")
    finally:
        ClienteDialog.exec = original_exec

    linha("5) Vendedores novos aparecem no filtro")
    _escolher(tela._filtro_vendedor, "BIA")
    vendedores_mod.adicionar_vendedor("CARLOS")
    tela.hide()
    tela.show()  # trocar de tela no app dispara showEvent
    app.processEvents()
    assert [tela._filtro_vendedor.itemText(i) for i in range(tela._filtro_vendedor.count())] == ["Todos", "ANA", "BIA", "CARLOS"]
    assert tela._filtro_vendedor.currentText() == "BIA", "a escolha atual é mantida ao repovoar"
    tela._botao_limpar_filtros.click()
    tela.close()
    print("OK: vendedor cadastrado depois aparece no filtro sem perder a escolha atual.")

    linha("6) Perfil VENDEDOR: sem filtro de vendedor, só vê os próprios")
    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_VENDEDOR, nome_usuario="ANA"))
    fonte_original = clientes_mod._ler_da_fonte_ativa
    clientes_mod._ler_da_fonte_ativa = lambda: bd.ler_clientes(arquivo)  # sem rede: le do arquivo de teste
    try:
        tela_v = FichaClienteScreen()
        assert tela_v._bloco_filtro_vendedor.isHidden(), "vendedor não filtra por vendedor"
        assert all(n in [c[0] for c in CLIENTES if c[1].upper() == "ANA"] + ["IRENE NOVA"] for n in _nomes_da_lista(tela_v))
        assert "CARLA OMEGA" not in _nomes_da_lista(tela_v) and "BRUNA ALFA" not in _nomes_da_lista(tela_v)
        _escolher(tela_v._filtro_tipo, "Avalista")
        assert _nomes_da_lista(tela_v) == ["ÉRICA BETA"]
        _escolher(tela_v._ordenacao, "Nome (Z-A)")
        _escolher(tela_v._filtro_tipo, "Todos")
        assert _nomes_da_lista(tela_v) == sorted(_nomes_da_lista(tela_v), key=lambda n: clientes_mod._chave_nome(n), reverse=True)
        tela_v.close()
    finally:
        clientes_mod._ler_da_fonte_ativa = fonte_original
        sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
    print("OK: o vendedor não vê o filtro de vendedor nem clientes de outros; tipo e ordenação funcionam.")


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))

    pasta = Path(tempfile.mkdtemp(prefix="_smoke_filtros_"))
    arquivo = pasta / "controle.xlsx"
    _criar_planilha_vazia(arquivo)
    clientes_mod.CAMINHO_XLSX = arquivo
    propostas_mod.CAMINHO_XLSX = arquivo
    vendedores_mod.CAMINHO_XLSX = arquivo
    try:
        vendedores_mod.adicionar_vendedor("ANA")
        vendedores_mod.adicionar_vendedor("BIA")
        for i, (nome, vendedor, tipo, cadastro) in enumerate(CLIENTES):
            clientes_mod.adicionar_cliente(
                {"CPF/CNPJ": _cpf(i), "CLIENTE": nome, "TIPO": tipo, "VENDEDOR": vendedor,
                 "DATA CADASTRO": cadastro if cadastro is not None else ""}
            )
        testar_core()
        with _Mensagens() as msgs:
            testar_tela(app, msgs, arquivo)
        assert not msgs.textos, f"nenhuma mensagem de erro era esperada, apareceu: {msgs.textos}"
        linha("TUDO OK")
    finally:
        clientes_mod.CAMINHO_XLSX = config.CAMINHO_XLSX
        propostas_mod.CAMINHO_XLSX = config.CAMINHO_XLSX
        vendedores_mod.CAMINHO_XLSX = config.CAMINHO_XLSX
        sessao_mod.encerrar()
        shutil.rmtree(pasta, ignore_errors=True)


if __name__ == "__main__":
    main()
