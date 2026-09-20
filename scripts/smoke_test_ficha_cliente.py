"""Testa a Ficha de Cliente e o dialogo de cliente depois da separacao do
endereco: nascimento digitavel (com calendario como alternativa), endereco em
campos separados com botao de copiar (retraido numa linha por padrao, expande
nos 7 campos), campos novos (pai/mae/profissao), o aviso de "endereco a
revisar" e o painel do cliente com barra de rolagem (campos sem espremer). Tudo
com clientes FICTICIOS numa copia temporaria da planilha - nao depende dos
dados reais.

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
from PySide6.QtCore import QDate, QPoint, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QFormLayout, QLabel, QMessageBox

from config import CAMINHO_XLSX

import config
config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
from core import clientes as clientes_mod
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import vendedores as vendedores_mod
from core.validators import _digito_verificador_cpf
from desktop import settings as settings_mod
from desktop.dialogs.cliente_dialog import ClienteDialog
from desktop.screens.ficha_cliente_screen import FichaClienteScreen
from desktop.widgets.lista_cartoes import ALTURA_CARTAO, ESPACO
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
    """Os botoes de copiar VISIVEIS, na ordem visual. Com o endereco expandido:
    CEP, Logradouro, Numero, Complemento, Bairro, Cidade, UF; retraido: so o do
    endereco inteiro."""
    botoes = [b for b in tela.findChildren(BotaoCopiar) if b.isVisible()]
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
    assert not tela._cabecalho_endereco.isChecked(), "o endereço abre retraído (o retraído é testado na seção 5)"
    tela._cabecalho_endereco.setChecked(True)  # aqui interessam os 7 campos
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


def _cpf(n: int) -> str:
    base = f"{300000000 + n:09d}"
    return base + _digito_verificador_cpf(base)


def _sem_invisiveis(rotulo: QLabel) -> str:
    """Texto do QLabel sem os pontos de quebra invisiveis (texto_quebravel)."""
    return rotulo.text().replace("​", "")


def _cadastrar_clientes_de_endereco() -> dict[str, str]:
    """Clientes FICTICIOS com o endereco completo, parcial, vazio e so 'a revisar'."""
    cadastros = {
        "completo": {"CLIENTE": "Cliente Endereco Completo", "LOGRADOURO": "Rua das Palmeiras", "NÚMERO": "211",
                     "COMPLEMENTO": "Apto 301", "BAIRRO": "Centro", "CIDADE": "Curitiba", "UF": "PR", "CEP": "80000-000"},
        "parcial": {"CLIENTE": "Cliente Endereco Parcial", "LOGRADOURO": "Avenida Central", "CIDADE": "Curitiba"},
        "vazio": {"CLIENTE": "Cliente Sem Endereco"},
        "pendente": {"CLIENTE": "Cliente Endereco Pendente", "ENDEREÇO (REVISAR)": "rua tal 12 apto 3"},
        "longo": {"CLIENTE": "Cliente Endereco Longo", "LOGRADOURO": "Avenida Presidente Juscelino Kubitschek de Oliveira Filho",
                  "NÚMERO": "1500", "COMPLEMENTO": "Bloco B, Sala 1203, Edificio Comercial Central", "BAIRRO": "Jardim das Acacias do Norte",
                  "CIDADE": "Sao Jose dos Campos", "UF": "SP", "CEP": "12200-000"},
    }
    cpfs = {}
    for n, (chave, campos) in enumerate(cadastros.items(), start=1):
        cpfs[chave] = _cpf(n)
        clientes_mod.adicionar_cliente({"CPF/CNPJ": cpfs[chave], "TIPO": "Cliente", **campos})
    return cpfs


def testar_endereco_retratil(app: QApplication, cpfs: dict[str, str]) -> None:
    linha("5) Endereço retraído (uma linha por extenso) e expandido (7 campos)")
    tela = FichaClienteScreen()
    tela.resize(1300, 800)
    tela.show()
    app.processEvents()
    cabecalho = tela._cabecalho_endereco
    clipboard = QApplication.clipboard()
    campos = (tela._campo_cep, tela._campo_logradouro, tela._campo_numero, tela._campo_complemento,
              tela._campo_bairro, tela._campo_cidade, tela._campo_uf)
    completo = "Rua das Palmeiras, 211, Apto 301 - Centro, Curitiba/PR - CEP 80000-000"

    # -- retraido por padrao ------------------------------------------------------
    tela._selecionar_por_cpf(cpfs["completo"])
    app.processEvents()
    assert not cabecalho.isChecked(), "por padrão o endereço vem retraído"
    assert tela._endereco_resumo.isVisible() and not tela._endereco_campos.isVisible()
    assert not any(c.isVisible() for c in campos), "retraído: os 7 campos individuais não aparecem"
    assert _sem_invisiveis(tela._campo_endereco_completo) == completo
    rotulo = tela._campo_endereco_completo
    assert rotulo.heightForWidth(rotulo.width()) <= rotulo.fontMetrics().lineSpacing() + 2, "o endereço retraído cabe numa única linha"
    botoes = _botoes_de_copia(tela)
    assert len(botoes) == 1, f"retraído há um único botão de copiar (o do endereço inteiro), há {len(botoes)}"
    botoes[0].click()
    assert clipboard.text() == completo and botoes[0].estado == botao_copiar_mod.ESTADO_COPIADO
    assert "​" not in clipboard.text(), "copia o endereço exato, sem caracteres invisíveis"
    print(f"OK: abre retraído: uma linha ('{completo}') e um botão que copia o endereço inteiro.")

    # -- expandir com um clique no titulo --------------------------------------
    assert "Mostrar" in cabecalho.toolTip()
    imagem_fechado = cabecalho.grab().toImage()
    QTest.mouseClick(cabecalho, Qt.MouseButton.LeftButton)
    app.processEvents()
    assert cabecalho.isChecked() and tela._endereco_campos.isVisible() and not tela._endereco_resumo.isVisible()
    assert all(c.isVisible() for c in campos), "expandido: os 7 campos aparecem"
    assert "Voltar" in cabecalho.toolTip(), "a dica muda: agora recolhe"
    assert cabecalho.grab().toImage() != imagem_fechado, "a seta muda de direção"
    botoes = _botoes_de_copia(tela)
    assert len(botoes) == 7, f"expandido há um botão de copiar por campo (7), há {len(botoes)}"
    esperado = ["80000-000", "Rua das Palmeiras", "211", "Apto 301", "Centro", "Curitiba", "PR"]
    for botao, texto in zip(botoes, esperado):
        clipboard.setText("")
        botao.click()
        assert clipboard.text() == texto and botao.estado == botao_copiar_mod.ESTADO_COPIADO, (texto, clipboard.text())
    print("OK: um clique no título expande: os 7 campos, cada um com o seu botão (copia só o seu valor); a seta e a dica mudam.")

    # -- recolher; a escolha vale pra qualquer cliente aberto depois -----------------
    QTest.mouseClick(cabecalho, Qt.MouseButton.LeftButton)
    app.processEvents()
    assert not cabecalho.isChecked() and tela._endereco_resumo.isVisible() and not tela._endereco_campos.isVisible()
    cabecalho.setChecked(True)
    tela._selecionar_por_cpf(cpfs["parcial"])
    app.processEvents()
    assert cabecalho.isChecked() and tela._endereco_campos.isVisible(), "expandido segue expandido ao abrir outro cliente"
    assert (tela._campo_logradouro.text(), tela._campo_cidade.text(), tela._campo_cep.text()) == ("Avenida Central", "Curitiba", "—")
    cabecalho.setChecked(False)
    tela._selecionar_por_cpf(cpfs["completo"])
    app.processEvents()
    assert not cabecalho.isChecked() and tela._endereco_resumo.isVisible(), "retraído segue retraído ao abrir outro cliente"
    print("OK: recolher volta à linha única; expandido/retraído continua assim ao trocar de cliente.")

    # -- teclado: Tab foca o titulo e Espaco alterna --------------------------------
    cabecalho.setFocus()
    QTest.keyClick(cabecalho, Qt.Key.Key_Space)
    assert cabecalho.isChecked(), "Espaço expande"
    QTest.keyClick(cabecalho, Qt.Key.Key_Space)
    assert not cabecalho.isChecked(), "Espaço recolhe"
    print("OK: pelo teclado também: Espaço no título expande e recolhe.")

    # -- o que falta fica de fora; vazio nao copia nada ---------------------------------
    tela._selecionar_por_cpf(cpfs["parcial"])
    app.processEvents()
    assert _sem_invisiveis(tela._campo_endereco_completo) == "Avenida Central - Curitiba"
    tela._selecionar_por_cpf(cpfs["vazio"])
    app.processEvents()
    assert _sem_invisiveis(tela._campo_endereco_completo) == "—", "sem endereço nenhum: '—', como os outros campos"
    clipboard.setText("anterior")
    botao_unico = _botoes_de_copia(tela)[0]
    botao_unico.click()
    assert clipboard.text() == "anterior" and botao_unico.estado == botao_copiar_mod.ESTADO_VAZIO, "vazio não copia '—'"
    print("OK: 'Avenida Central - Curitiba' (só o que existe, sem sobras); sem endereço mostra '—' e o copiar não sobrescreve a área de transferência.")

    # -- o aviso de 'endereco a revisar' aparece nos dois estados ------------------------
    tela._selecionar_por_cpf(cpfs["pendente"])
    app.processEvents()
    assert _sem_invisiveis(tela._campo_endereco_completo) == "—"
    assert tela._aviso_endereco_revisar.isVisible() and "rua tal 12 apto 3" in tela._aviso_endereco_revisar.text()
    cabecalho.setChecked(True)
    app.processEvents()
    assert tela._aviso_endereco_revisar.isVisible(), "expandido, o aviso continua aparecendo"
    cabecalho.setChecked(False)
    tela._selecionar_por_cpf(cpfs["completo"])
    assert not tela._aviso_endereco_revisar.isVisible()
    print("OK: o aviso 'endereço a revisar' aparece retraído e expandido, só pro cliente que tem o texto pendente.")

    # -- tema --------------------------------------------------------------------------
    original_obter = settings_mod.obter_tema
    try:
        for tema in (TEMA_CLARO, TEMA_ESCURO, TEMA_CLARO):
            settings_mod.obter_tema = lambda t=tema: t  # o app grava o tema antes de reaplicar o stylesheet
            app.setStyleSheet(build_stylesheet(tema))
            app.processEvents()
            assert cabecalho._paleta is PALETAS[tema], f"o título deveria ter a paleta do tema {tema}"
    finally:
        settings_mod.obter_tema = original_obter
        app.setStyleSheet("")
    print("OK: a seta e o título refazem as cores ao trocar o tema com o app aberto.")
    tela.close()


def _mesma_fonte(a: QLabel, b: QLabel) -> bool:
    fa, fb = a.font(), b.font()
    return (fa.family(), fa.pixelSize(), fa.pointSizeF(), fa.weight(), fa.italic()) == (fb.family(), fb.pixelSize(), fb.pointSizeF(), fb.weight(), fb.italic())


def _cor_do_texto(rotulo: QLabel) -> str:
    return rotulo.palette().color(QPalette.ColorRole.WindowText).name()


def testar_endereco_como_os_outros_campos(app: QApplication, cpfs: dict[str, str]) -> None:
    linha("5b) Endereço retraído com o MESMO visual dos outros campos (fonte, caixa, sem barra)")
    original_obter = settings_mod.obter_tema
    tela = None
    try:
        for tema in (TEMA_ESCURO, TEMA_CLARO):
            settings_mod.obter_tema = lambda t=tema: t
            app.setStyleSheet(build_stylesheet(tema))  # as fontes e cores dos campos vem do tema
            tela = FichaClienteScreen()
            tela.resize(1300, 800)
            tela.show()
            tela._selecionar_por_cpf(cpfs["completo"])
            for _ in range(6):
                app.processEvents()

            legenda_outra = next(r for r in tela.findChildren(QLabel) if r.text() == "Nome do pai")
            titulo = tela._cabecalho_endereco._rotulo
            assert _mesma_fonte(titulo, legenda_outra) and _cor_do_texto(titulo) == _cor_do_texto(legenda_outra), \
                f"{tema}: o título 'Endereço' tem a mesma fonte/cor das legendas dos outros campos"
            assert titulo.property("role") == "campo_rotulo"

            valor = tela._campo_endereco_completo
            assert _mesma_fonte(valor, tela._campo_cpf) and _cor_do_texto(valor) == _cor_do_texto(tela._campo_cpf), \
                f"{tema}: o endereço tem a mesma fonte/cor do valor dos outros campos"
            assert abs(valor.height() - tela._campo_cpf.height()) <= 1, \
                f"{tema}: caixa do endereço ({valor.height()} px) com a altura da dos outros campos ({tela._campo_cpf.height()} px)"
            assert abs(titulo.height() - legenda_outra.height()) <= 1, f"{tema}: legenda com a altura das outras"

            # nada de "barra": o valor ocupa so a largura do texto e o botao de copiar fica logo ao lado
            botao = _botoes_de_copia(tela)[0]
            largura_texto = valor.fontMetrics().horizontalAdvance(_sem_invisiveis(valor))
            assert valor.width() <= largura_texto + 12, f"{tema}: valor de {valor.width()} px para um texto de {largura_texto} px (esticou)"
            folga = botao.mapTo(tela, QPoint(0, 0)).x() - valor.mapTo(tela, QPoint(valor.width(), 0)).x()
            assert 0 <= folga <= 8, f"{tema}: o botão de copiar deveria ficar colado ao valor (folga de {folga} px)"
            assert tela._cabecalho_endereco.width() < 150, "o título ocupa só o próprio texto + a seta"

            # ...e nenhum fundo diferente atras/ao lado do campo: as areas vazias sao a cor do card
            card = PALETAS[tema]["bg_card"]
            imagem = tela.grab().toImage()
            y_meio = valor.mapTo(tela, QPoint(0, valor.height() // 2)).y()
            x_apos_botao = botao.mapTo(tela, QPoint(botao.width() + 60, 0)).x()
            assert imagem.pixelColor(x_apos_botao, y_meio).name() == QColor(card).name(), \
                f"{tema}: depois do botão de copiar o fundo tem que ser o do card (não uma barra escura pela largura toda)"
            # expandido: o contentor dos 7 campos tambem nao pode pintar uma faixa atras da grade
            tela._cabecalho_endereco.setChecked(True)
            for _ in range(6):
                app.processEvents()
            imagem = tela.grab().toImage()
            botao_cep = _botoes_de_copia(tela)[0]
            direita_col0 = botao_cep.mapTo(tela, QPoint(botao_cep.width(), 0)).x()
            esquerda_col1 = tela._campo_logradouro.mapTo(tela, QPoint(0, 0)).x()
            x_vao, y_linha = (direita_col0 + esquerda_col1) // 2, tela._campo_cep.mapTo(tela, QPoint(0, tela._campo_cep.height() // 2)).y()
            assert imagem.pixelColor(x_vao, y_linha).name() == QColor(card).name(), \
                f"{tema}: entre as colunas dos 7 campos o fundo tem que ser o do card ({imagem.pixelColor(x_vao, y_linha).name()})"
            tela.close()
            tela = None
        print("OK (escuro e claro): o título 'Endereço' tem a fonte/cor das outras legendas; o valor tem a fonte, a cor e a "
              "altura de caixa dos outros valores; ocupa só a largura do texto, com o botão de copiar colado; sem faixa "
              "atrás do campo (retraído) nem da grade (expandido).")
    finally:
        if tela is not None:
            tela.close()
        settings_mod.obter_tema = original_obter
        app.setStyleSheet("")

    # janela estreita + endereco muito longo: quebra em mais linhas em vez de estourar o card
    tela = FichaClienteScreen()
    tela.setMinimumSize(100, 100)
    tela.resize(820, 800)
    tela.show()
    tela._selecionar_por_cpf(cpfs["longo"])
    for _ in range(6):
        app.processEvents()
    valor = tela._campo_endereco_completo
    botao = _botoes_de_copia(tela)[0]
    assert valor.heightForWidth(valor.width()) > valor.fontMetrics().lineSpacing() + 2, "endereço longo em janela estreita quebra em mais linhas"
    cartao = tela._nome_label.parentWidget()
    borda_cartao = cartao.mapTo(tela, QPoint(cartao.width(), 0)).x()
    assert botao.mapTo(tela, QPoint(botao.width(), 0)).x() <= borda_cartao, "o botão de copiar não vaza do cartão"
    assert valor.mapTo(tela, QPoint(valor.width(), 0)).x() <= borda_cartao
    assert not tela._rolagem_ficha.horizontalScrollBar().isVisible()
    assert _rotulos_espremidos(tela) == [], _rotulos_espremidos(tela)
    assert _sem_invisiveis(valor).startswith("Avenida Presidente Juscelino") and "CEP 12200-000" in _sem_invisiveis(valor)
    botao.click()
    assert QApplication.clipboard().text() == _sem_invisiveis(valor), "copia o endereço inteiro mesmo quebrado em linhas"
    tela.close()
    print("OK: endereço longo numa janela estreita quebra em mais linhas, sem vazar do cartão nem espremer os campos; "
          "o botão copia o endereço inteiro.")


def _rotulos_espremidos(tela: FichaClienteScreen) -> list[tuple[str, int, int]]:
    """Rotulos do painel do cliente com altura MENOR que a necessaria - o Qt os
    espreme (e o texto se sobrepoe) quando o painel e forcado a caber num espaco
    menor que o seu conteudo."""
    ruins = []
    for rotulo in tela._painel_stack.currentWidget().findChildren(QLabel):
        if not rotulo.isVisible() or not rotulo.text():
            continue
        precisa = rotulo.heightForWidth(rotulo.width()) if rotulo.hasHeightForWidth() else rotulo.sizeHint().height()
        if rotulo.height() < precisa:
            ruins.append((rotulo.text()[:20], rotulo.height(), precisa))
    return ruins


def testar_rolagem(app: QApplication, cpfs: dict[str, str]) -> None:
    linha("6) Painel do cliente com barra de rolagem: campos com espaço normal (sem espremer)")
    for n in range(5):  # 5 propostas pro cliente completo, 1 pro parcial (a lista de cards acompanha o numero)
        propostas_mod.adicionar_proposta(
            {"CPF": cpfs["completo"], "DATA": pd.Timestamp(2026, 3, 1 + n), "VALOR (R$)": 1000 * (n + 1), "MESES": 12,
             "EQUIPAMENTO": f"Laser {n}", "BANCO": "Banco Teste", "STATUS": "Em Análise", "OBSERVAÇÕES": f"obs {n}"}
        )
    propostas_mod.adicionar_proposta(
        {"CPF": cpfs["parcial"], "DATA": pd.Timestamp(2026, 3, 9), "VALOR (R$)": 500, "MESES": 6, "EQUIPAMENTO": "Mesa",
         "BANCO": "Banco Teste", "STATUS": "Negado", "OBSERVAÇÕES": ""}
    )

    original_obter = settings_mod.obter_tema
    settings_mod.obter_tema = lambda: TEMA_ESCURO
    app.setStyleSheet(build_stylesheet(TEMA_ESCURO))  # a barra discreta vem do tema do app
    tela = None
    try:
        tela = FichaClienteScreen()
        minimo_pedido = tela.minimumSizeHint().height()
        assert minimo_pedido < 500, f"o painel não pode exigir a altura toda do conteúdo (o layout pede {minimo_pedido} px)"
        tela.setMinimumSize(100, 100)  # como numa janela maximizada em tela baixa: o Qt nao a impede de ficar menor
        tela.resize(1150, 560)
        tela.show()
        tela._selecionar_por_cpf(cpfs["completo"])
        for _ in range(6):
            app.processEvents()

        rolagem = tela._rolagem_ficha
        barra = rolagem.verticalScrollBar()
        assert barra.maximum() > 0 and barra.isVisible(), "janela baixa: o painel ganha barra de rolagem"
        assert rolagem.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        assert not rolagem.horizontalScrollBar().isVisible(), "nunca rola pro lado"
        assert barra.sizeHint().width() <= 12, f"barra discreta (do tema): {barra.sizeHint().width()} px de largura"
        assert _rotulos_espremidos(tela) == [], f"campos espremidos: {_rotulos_espremidos(tela)}"
        print(f"OK: janela de 560 px de altura: o layout pede só {minimo_pedido} px, o painel ganha barra fina "
              f"({barra.sizeHint().width()} px) e nenhum campo fica espremido.")

        # rolar mostra o fim (historico); a barra do topo/fim funciona
        assert barra.value() == 0
        barra.setValue(barra.maximum())
        app.processEvents()
        viewport = rolagem.viewport()
        fim_historico = tela._lista_historico.mapTo(viewport, QPoint(0, tela._lista_historico.height())).y()
        assert fim_historico <= viewport.height() + 1, "rolado até o fim, o histórico de propostas aparece inteiro"
        topo_cartao = tela._nome_label.mapTo(viewport, QPoint(0, 0)).y()
        assert topo_cartao < 0, "e o topo do cartão saiu pra cima (rolou de verdade)"

        # os botoes de proposta ficam FIXOS embaixo, fora da rolagem
        y_botao = tela._botao_nova_proposta.mapTo(tela, QPoint(0, 0)).y()
        barra.setValue(0)
        app.processEvents()
        assert tela._botao_nova_proposta.mapTo(tela, QPoint(0, 0)).y() == y_botao, "os botões não rolam"
        assert tela._botao_nova_proposta.isVisible() and tela._botao_excluir_proposta.isVisible()
        assert y_botao + tela._botao_nova_proposta.height() <= tela.height()
        print("OK: rolar até o fim mostra o histórico inteiro; 'Excluir Proposta Selecionada' e '+ Nova Proposta' ficam fixos embaixo.")

        # alinhados com o cartao, com e sem a barra de rolagem
        cartao = tela._nome_label.parentWidget()
        borda = lambda w: w.mapTo(tela, QPoint(w.width(), 0)).x()  # noqa: E731
        assert abs(borda(cartao) - borda(tela._botao_nova_proposta)) <= 1, (borda(cartao), borda(tela._botao_nova_proposta))
        tela.resize(1150, 1300)
        for _ in range(6):
            app.processEvents()
        assert barra.maximum() == 0 and not barra.isVisible(), "janela alta: cabe tudo, sem barra"
        assert _rotulos_espremidos(tela) == []
        assert abs(borda(cartao) - borda(tela._botao_nova_proposta)) <= 1, "sem a barra os botões seguem alinhados com o cartão"
        tela.resize(1150, 560)
        for _ in range(6):
            app.processEvents()
        assert abs(borda(cartao) - borda(tela._botao_nova_proposta)) <= 1, "com a barra de volta, alinhados de novo"
        print("OK: os botões de baixo ficam alinhados com o cartão com a barra de rolagem e sem ela.")

        # a lista de cards do historico tem a altura das linhas de cards (sem barra de rolagem propria)
        colunas = tela._lista_historico.colunas()
        altura_5 = tela._lista_historico.height()
        assert altura_5 == -(-5 // colunas) * (ALTURA_CARTAO + ESPACO), (altura_5, colunas)
        tela._selecionar_por_cpf(cpfs["parcial"])
        app.processEvents()
        altura_1 = tela._lista_historico.height()
        assert altura_1 == ALTURA_CARTAO + ESPACO < altura_5, (altura_1, altura_5)
        tela._selecionar_por_cpf(cpfs["vazio"])
        app.processEvents()
        assert not tela._contentor_historico.isVisible() and tela._historico_vazio.isVisible()
        print(f"OK: o histórico em cards tem {altura_5} px com 5 propostas ({colunas} por linha) e {altura_1} px com 1; sem proposta aparece o aviso.")

        # outro cliente: o painel volta pro topo
        tela._selecionar_por_cpf(cpfs["completo"])
        app.processEvents()
        barra.setValue(barra.maximum())
        assert barra.value() > 0
        tela._selecionar_por_cpf(cpfs["parcial"])
        app.processEvents()
        assert barra.value() == 0, "trocar de cliente volta o painel pro topo"

        # expandir o endereco com o painel rolado/janela baixa: rola ate os campos
        tela.resize(1150, 470)
        tela._selecionar_por_cpf(cpfs["completo"])
        for _ in range(6):
            app.processEvents()
        tela._cabecalho_endereco.setChecked(False)
        barra.setValue(0)
        tela._cabecalho_endereco.setChecked(True)
        for _ in range(6):
            app.processEvents()
        campos = tela._endereco_campos
        fundo_campos = campos.mapTo(rolagem.viewport(), QPoint(0, campos.height())).y()
        assert fundo_campos <= rolagem.viewport().height() + 1, "ao expandir, o painel rola pra mostrar os 7 campos"
        assert _rotulos_espremidos(tela) == [], _rotulos_espremidos(tela)
        print("OK: trocar de cliente volta ao topo; expandir o endereço numa janela baixa rola até mostrar os 7 campos.")
    finally:
        if tela is not None:
            tela.close()
        settings_mod.obter_tema = original_obter
        app.setStyleSheet("")


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
            cpfs = _cadastrar_clientes_de_endereco()
            testar_endereco_retratil(app, cpfs)
            testar_endereco_como_os_outros_campos(app, cpfs)
            testar_rolagem(app, cpfs)
        linha("TUDO OK")
    finally:
        tmp.unlink(missing_ok=True)
        sessao_mod.encerrar()


if __name__ == "__main__":
    main()
