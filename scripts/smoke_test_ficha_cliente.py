"""Testa a Ficha de Cliente e o dialogo de cliente depois da separacao do
endereco: nascimento digitavel (com calendario como alternativa), endereco em
campos separados com botao de copiar, campos novos (pai/mae/profissao) e o
aviso de "endereco a revisar". Tudo com clientes FICTICIOS numa copia
temporaria da planilha - nao depende dos dados reais.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_ficha_cliente.py
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from PySide6.QtCore import QDate, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QFormLayout, QMessageBox

from config import CAMINHO_XLSX

import config
config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
from core import clientes as clientes_mod
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import vendedores as vendedores_mod
from desktop import settings as settings_mod
from desktop.dialogs.cliente_dialog import ClienteDialog
from desktop.screens.ficha_cliente_screen import FichaClienteScreen
from desktop.theme import PALETAS, TEMA_CLARO, TEMA_ESCURO, build_stylesheet
from desktop.widgets import botao_copiar as botao_copiar_mod
from desktop.widgets.botao_copiar import BotaoCopiar
from desktop.widgets.campo_data import CampoData
from desktop.widgets.formatters import formatar_cep_parcial, formatar_data_parcial

CPF_NOVO = "111.444.777-35"
CPF_SEPARADO = "529.982.247-25"
CPF_REVISAR = "390.533.447-05"


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def testar_mascaras() -> None:
    linha("0) Máscaras de data e CEP")
    assert formatar_data_parcial("1") == "1"
    assert formatar_data_parcial("15") == "15"
    assert formatar_data_parcial("150") == "15/0"
    assert formatar_data_parcial("15031985") == "15/03/1985"
    assert formatar_data_parcial("150319851234") == "15/03/1985"  # excesso e cortado
    assert formatar_cep_parcial("60165") == "60165"
    assert formatar_cep_parcial("601651") == "60165-1"
    assert formatar_cep_parcial("60165120999") == "60165-120"
    print("OK: as barras e o hífen entram sozinhos e o excesso de dígitos é cortado.")


def testar_campo_data(app: QApplication) -> None:
    linha("1) Nascimento: digitação direta, colar e calendário")
    campo = CampoData()

    QTest.keyClicks(campo.campo, "15031985")  # digitando tecla por tecla
    assert campo.texto() == "15/03/1985", campo.texto()
    data, erro = campo.avaliar()
    assert (data, erro) == (QDate(1985, 3, 15), "")
    print("OK: digitar 15031985 vira 15/03/1985 (as barras entram sozinhas) e é uma data válida.")

    campo.campo.setText("20/07/1990")  # colar ja formatado
    assert campo.avaliar()[0] == QDate(1990, 7, 20)
    campo.campo.clear()
    assert campo.avaliar() == (None, ""), "em branco = não informado, sem erro"
    print("OK: colar '20/07/1990' funciona; em branco = 'não informado' (sem erro).")

    for texto, trecho in (
        ("15/03/19", "incompleta"),
        ("31/02/2000", "não é uma data válida"),
        ("01/01/1899", "anterior a 1900"),
        (f"01/01/{QDate.currentDate().year() + 1}", "futuro"),
    ):
        campo.campo.setText(texto)
        data, erro = campo.avaliar()
        assert data is None and trecho in erro, f"{texto!r}: {erro!r}"
    print("OK: incompleta, dia inexistente, antes de 1900 e futura são recusadas com mensagem clara.")

    campo.campo.setText("15/0")
    assert campo.campo.property("invalido") is False, "enquanto digita ('15/0') não pode piscar vermelho"
    campo.campo.setText("31/02/2000")
    assert campo.campo.property("invalido") is True, "completa e inválida: borda vermelha"
    campo.campo.setText("28/02/2000")
    assert campo.campo.property("invalido") is False
    print("OK: borda vermelha só quando a data está completa e inválida.")

    campo.campo.clear()
    campo._calendario.clicked.emit(QDate(1975, 12, 5))  # escolher no calendario (alternativa a digitar)
    assert campo.texto() == "05/12/1975" and campo.avaliar()[0] == QDate(1975, 12, 5)
    campo.definir_data(QDate(2001, 1, 31))
    assert campo.texto() == "31/01/2001"
    campo.definir_data(None)
    assert campo.texto() == ""
    print("OK: o calendário continua funcionando como alternativa e preenche o campo.")


class _Mensagens:
    def __init__(self) -> None:
        self.titulos: list[str] = []
        self.textos: list[str] = []
        self._orig = (QMessageBox.warning, QMessageBox.critical, QMessageBox.information)

    def __enter__(self):
        def _stub(*args, **kwargs):
            self.titulos.append(str(args[1]) if len(args) > 1 else "")
            self.textos.append(str(args[2]) if len(args) > 2 else "")
            return QMessageBox.StandardButton.Ok

        QMessageBox.warning = QMessageBox.critical = QMessageBox.information = staticmethod(_stub)
        return self

    def __exit__(self, *_):
        QMessageBox.warning, QMessageBox.critical, QMessageBox.information = self._orig


def _linha_do_form(dialogo: ClienteDialog, campo) -> int:
    formulario = dialogo.findChild(QFormLayout)
    return formulario.getWidgetPosition(campo)[0]


def testar_dialogo(msgs: _Mensagens) -> None:
    linha("2) ClienteDialog: nascimento digitável, endereço em campos, campos novos")
    vendedores_mod.adicionar_vendedor("VENDEDOR TESTE")
    assert clientes_mod.buscar_por_cpf(CPF_NOVO) is None, "CPF de teste ja existe na planilha"

    dialogo = ClienteDialog(cliente=None)
    # ordem: nascimento logo abaixo de CPF e nome (antes de tipo/celular/endereco...)
    assert _linha_do_form(dialogo, dialogo._cpf) == 0 and _linha_do_form(dialogo, dialogo._nome) == 1
    assert _linha_do_form(dialogo, dialogo._nascimento) == 2, "nascimento deve ficar logo abaixo do nome"
    assert _linha_do_form(dialogo, dialogo._nascimento) < _linha_do_form(dialogo, dialogo._tipo) < _linha_do_form(dialogo, dialogo._cep)
    ordem_endereco = [dialogo._cep, dialogo._logradouro, dialogo._numero, dialogo._complemento, dialogo._bairro, dialogo._cidade, dialogo._uf]
    linhas = [_linha_do_form(dialogo, c) for c in ordem_endereco]
    assert linhas == sorted(linhas) and len(set(linhas)) == 7, "CEP, logradouro, número, complemento, bairro, cidade, UF em sequência"
    assert dialogo._uf.currentText() == "" and dialogo._uf.count() == 28, "lista fechada: em branco + 27 estados"
    assert _linha_do_form(dialogo, dialogo._nome_pai) > _linha_do_form(dialogo, dialogo._vinculado), "pai/mãe/profissão são secundários"
    assert _linha_do_form(dialogo, dialogo._rede_social) < _linha_do_form(dialogo, dialogo._nome_pai) < _linha_do_form(dialogo, dialogo._nome_mae) < _linha_do_form(dialogo, dialogo._profissao)
    assert dialogo._endereco_revisar is None, "cliente novo nao tem endereco a revisar"
    print("OK: Nascimento na 3ª linha (logo abaixo de CPF e nome); pai/mãe/profissão junto dos secundários.")

    dialogo._cpf.setText(CPF_NOVO)
    dialogo._nome.setText("Cliente Ficha Teste")
    dialogo._tipo.setCurrentText("Cliente")
    dialogo._vendedor.setCurrentText("VENDEDOR TESTE")
    QTest.keyClicks(dialogo._nascimento.campo, "15031985")
    QTest.keyClicks(dialogo._cep, "60165120")
    assert dialogo._cep.text() == "60165-120"
    dialogo._logradouro.setText("Avenida Beira Mar")
    dialogo._numero.setText("2120")
    dialogo._complemento.setText("apto 12")
    dialogo._bairro.setText("Meireles")
    dialogo._cidade.setText("Fortaleza")
    dialogo._uf.setCurrentText("CE")
    dialogo._nome_pai.setText("Pai Teste")
    dialogo._nome_mae.setText("Mãe Teste")
    dialogo._profissao.setText("Engenheiro")
    dialogo._salvar()
    assert dialogo.result() == QDialog.DialogCode.Accepted, msgs.textos
    salvo = clientes_mod.buscar_por_cpf(CPF_NOVO)
    assert salvo["NASCIMENTO"] == pd.Timestamp(1985, 3, 15)
    assert (salvo["CEP"], salvo["LOGRADOURO"], salvo["NÚMERO"], salvo["COMPLEMENTO"], salvo["BAIRRO"], salvo["CIDADE"], salvo["UF"]) == (
        "60165-120", "Avenida Beira Mar", "2120", "apto 12", "Meireles", "Fortaleza", "CE")
    assert (salvo["NOME DO PAI"], salvo["NOME DA MÃE"], salvo["PROFISSÃO"]) == ("Pai Teste", "Mãe Teste", "Engenheiro")
    print("OK: cliente cadastrado digitando o nascimento (15031985) e com endereço/pai/mãe/profissão nos campos certos.")

    linha("2b) Validações do diálogo")
    total = len(clientes_mod.listar_clientes())
    d2 = ClienteDialog(cliente=None)
    d2._cpf.setText("529.982.247-25")
    d2._nome.setText("Nasc Invalido")
    d2._tipo.setCurrentText("Cliente")
    d2._nascimento.campo.setText("31/02/2000")
    d2._salvar()
    assert d2.result() != QDialog.DialogCode.Accepted and "Nascimento inválido" in msgs.titulos[-1]
    assert "válida" in msgs.textos[-1]
    d2._nascimento.campo.clear()
    d2._cep.setText("1234")
    d2._salvar()
    assert d2.result() != QDialog.DialogCode.Accepted and "CEP" in msgs.textos[-1]
    d2._cep.clear()
    d2._uf.addItem("Ceara")  # valor fora da lista (ex.: veio de edicao direta no Excel)
    d2._uf.setCurrentText("Ceara")
    d2._salvar()
    assert d2.result() != QDialog.DialogCode.Accepted and "UF" in msgs.textos[-1]
    assert len(clientes_mod.listar_clientes()) == total, "nada pode ser gravado quando a validacao falha"
    print("OK: data inválida, CEP incompleto e UF fora da lista são recusados com aviso (sem gravar e sem virar 'não informado' em silêncio).")

    linha("2c) Endereço 'a revisar' no diálogo")
    clientes_mod.adicionar_cliente(
        {"CPF/CNPJ": CPF_REVISAR, "CLIENTE": "Cliente Revisar", "TIPO": "Cliente", "ENDEREÇO (REVISAR)": "rua tal 12 apto 3"}
    )
    d3 = ClienteDialog(cliente=clientes_mod.buscar_por_cpf(CPF_REVISAR))
    assert d3._endereco_revisar is not None and d3._endereco_revisar.text() == "rua tal 12 apto 3"
    d3._salvar()  # sem mexer: o texto original nao pode sumir
    assert clientes_mod.buscar_por_cpf(CPF_REVISAR)["ENDEREÇO (REVISAR)"] == "rua tal 12 apto 3"
    d3 = ClienteDialog(cliente=clientes_mod.buscar_por_cpf(CPF_REVISAR))
    d3._logradouro.setText("Rua Tal")
    d3._numero.setText("12")
    d3._endereco_revisar.clear()  # revisado: apaga o texto original
    d3._salvar()
    revisado = clientes_mod.buscar_por_cpf(CPF_REVISAR)
    assert (revisado["LOGRADOURO"], revisado["NÚMERO"], revisado["ENDEREÇO (REVISAR)"]) == ("Rua Tal", "12", "")
    assert ClienteDialog(cliente=revisado)._endereco_revisar is None, "revisado: a linha some do formulário"
    print("OK: texto original aparece no diálogo, sobrevive a um salvar sem mexer e some depois de apagado.")


def _botoes_de_copia(tela: FichaClienteScreen) -> list[BotaoCopiar]:
    """Na ordem visual: CEP, Logradouro, Número, Bairro, Cidade."""
    botoes = tela.findChildren(BotaoCopiar)
    return sorted(botoes, key=lambda b: (b.mapTo(tela, QPoint(0, 0)).y() // 20, b.mapTo(tela, QPoint(0, 0)).x()))


def testar_ficha(app: QApplication) -> None:
    linha("3) Ficha de Cliente: ordem dos campos, endereço com botão copiar, aviso de revisar")
    clientes_mod.adicionar_cliente(
        {"CPF/CNPJ": CPF_SEPARADO, "CLIENTE": "Cliente Separado", "TIPO": "Cliente",
         "NASCIMENTO": pd.Timestamp(1990, 7, 20),
         "CEP": "", "LOGRADOURO": "Rua das Flores", "NÚMERO": "SN", "COMPLEMENTO": "", "BAIRRO": "Centro",
         "CIDADE": "Curitiba", "UF": "PR"}
    )
    tela = FichaClienteScreen()
    tela.resize(1150, 780)
    tela.show()
    app.processEvents()

    tela._selecionar_por_cpf(CPF_SEPARADO)
    app.processEvents()
    # nascimento na mesma linha do CPF/CNPJ (topo), acima dos campos secundarios
    y = lambda campo: campo.mapTo(tela, QPoint(0, 0)).y()  # noqa: E731
    assert y(tela._campo_nascimento) == y(tela._campo_cpf), "nascimento na mesma linha do CPF/CNPJ"
    assert y(tela._campo_nascimento) < y(tela._campo_rede_social) < y(tela._campo_nome_pai) < y(tela._campo_cep)
    assert y(tela._campo_celular) < y(tela._campo_rede_social), "celular/e-mail (principais) acima de rede social"
    assert y(tela._campo_nome_pai) == y(tela._campo_nome_mae) == y(tela._campo_profissao)
    assert tela._campo_nascimento.text() == "20/07/1990"
    print("OK: Nascimento na linha do CPF/CNPJ (topo); pai/mãe/profissão na área secundária, acima do endereço.")

    assert [tela._campo_nome_pai.text(), tela._campo_nome_mae.text(), tela._campo_profissao.text()] == ["—"] * 3
    assert (tela._campo_logradouro.text(), tela._campo_numero.text(), tela._campo_bairro.text(), tela._campo_cidade.text(),
            tela._campo_uf.text()) == ("Rua das Flores", "SN", "Centro", "Curitiba", "PR")
    assert tela._campo_cep.text() == "—" and tela._campo_complemento.text() == "—" and not tela._aviso_endereco_revisar.isVisible()
    # a grade do endereco: CEP/Logradouro/Numero na 1a linha; Complemento/Bairro/(Cidade+UF) na 2a
    assert y(tela._campo_cep) == y(tela._campo_logradouro) == y(tela._campo_numero)
    assert y(tela._campo_complemento) == y(tela._campo_bairro) == y(tela._campo_cidade) == y(tela._campo_uf) > y(tela._campo_cep)
    assert tela._campo_cidade.mapTo(tela, QPoint(0, 0)).x() < tela._campo_uf.mapTo(tela, QPoint(0, 0)).x(), "UF ao lado da cidade"
    print("OK: endereço em 7 campos (CEP vazio e complemento vazio mostram '—'); UF ao lado da cidade; sem aviso de revisar.")

    botoes = _botoes_de_copia(tela)
    assert len(botoes) == 7, f"deveria haver 7 botões de copiar (um por campo de endereço), há {len(botoes)}"
    cep, logr, num, compl, bairro, cidade, uf = botoes
    clipboard = QApplication.clipboard()
    for botao, esperado in ((logr, "Rua das Flores"), (num, "SN"), (bairro, "Centro"), (cidade, "Curitiba"), (uf, "PR")):
        botao.click()
        assert clipboard.text() == esperado and botao.estado == botao_copiar_mod.ESTADO_COPIADO, (esperado, clipboard.text())
    clipboard.setText("anterior")
    for vazio in (cep, compl):
        vazio.click()
        assert clipboard.text() == "anterior" and vazio.estado == botao_copiar_mod.ESTADO_VAZIO, "campo vazio não copia '—'"
    print("OK: cada botão copia só o valor do seu campo (sem '—' nem caracteres invisíveis); campo vazio não sobrescreve.")

    # texto longo/quebravel: o que vai pra area de transferencia e o texto cru, sem pontos de quebra invisiveis
    longo = "Avenida Presidente Juscelino Kubitschek de Oliveira Filho/Norte"
    clientes_mod.atualizar_cliente(CPF_SEPARADO, {"CPF/CNPJ": CPF_SEPARADO, "CLIENTE": "Cliente Separado", "TIPO": "Cliente", "LOGRADOURO": longo})
    tela._selecionar_por_cpf(CPF_SEPARADO)
    tela._recarregar_ficha_atual()
    _botoes_de_copia(tela)[1].click()
    assert clipboard.text() == longo and "​" not in clipboard.text()
    print("OK: logradouro longo é copiado exatamente como foi digitado.")

    tela._selecionar_por_cpf(CPF_REVISAR)
    app.processEvents()
    assert tela._aviso_endereco_revisar.isHidden() or "revisar" not in tela._aviso_endereco_revisar.text()
    clientes_mod.atualizar_cliente(
        CPF_REVISAR,
        {"CPF/CNPJ": CPF_REVISAR, "CLIENTE": "Cliente Revisar", "TIPO": "Cliente", "ENDEREÇO (REVISAR)": "rua tal 12 apto 3",
         "LOGRADOURO": "", "NÚMERO": ""},
    )
    tela._selecionar_por_cpf(CPF_REVISAR)
    tela._recarregar_ficha_atual()
    app.processEvents()
    assert tela._aviso_endereco_revisar.isVisible() and "rua tal 12 apto 3" in tela._aviso_endereco_revisar.text()
    tela._selecionar_por_cpf(CPF_SEPARADO)
    assert not tela._aviso_endereco_revisar.isVisible(), "aviso não pode vazar de um cliente para o outro"
    print("OK: aviso 'endereço a revisar' aparece só para o cliente que tem o texto pendente.")

    linha("4) Botão de copiar acompanha a troca de tema")
    botao = _botoes_de_copia(tela)[0]
    original_obter = settings_mod.obter_tema
    try:
        for tema in (TEMA_CLARO, TEMA_ESCURO, TEMA_CLARO):
            settings_mod.obter_tema = lambda t=tema: t  # o app grava o tema antes de reaplicar o stylesheet
            app.setStyleSheet(build_stylesheet(tema))
            app.processEvents()
            assert botao._paleta is PALETAS[tema], f"botão deveria ter a paleta do tema {tema}"
    finally:
        settings_mod.obter_tema = original_obter
        app.setStyleSheet("")
    print("OK: ao trocar o tema com o app aberto, o ícone de copiar refaz as cores.")
    tela.close()


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
    testar_mascaras()
    testar_campo_data(app)

    tmp = CAMINHO_XLSX.parent / "_smoke_test_ficha_cliente.xlsx"
    shutil.copy(CAMINHO_XLSX, tmp)
    clientes_mod.CAMINHO_XLSX = tmp
    propostas_mod.CAMINHO_XLSX = tmp
    vendedores_mod.CAMINHO_XLSX = tmp
    try:
        with _Mensagens() as msgs:
            testar_dialogo(msgs)
            testar_ficha(app)
        linha("TUDO OK")
    finally:
        tmp.unlink(missing_ok=True)
        sessao_mod.encerrar()


if __name__ == "__main__":
    main()
