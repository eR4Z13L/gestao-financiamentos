"""Testa a Ficha de Cliente (cadastro/edicao inline, sem dialogo): nascimento
digitavel (com calendario como alternativa), endereco em campos separados com
botao de copiar (retraido numa linha por padrao, expande nos 7 campos), campos
novos (pai/mae/profissao), o "endereco a revisar" (editavel/apagavel) e o
painel do cliente com barra de rolagem (campos sem espremer). Tudo com
clientes FICTICIOS numa copia temporaria da planilha - nao depende dos dados
reais.

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
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

from config import CAMINHO_XLSX

import config
config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
from core import clientes as clientes_mod
from core import data_store as bd
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import vendedores as vendedores_mod
from core.validators import _digito_verificador_cpf, apenas_digitos
from desktop import settings as settings_mod
from desktop.screens.ficha_cliente_screen import FichaClienteScreen
from desktop.widgets.lista_cartoes import ALTURA_CARTAO, ESPACO
from desktop.theme import PALETAS, TEMA_CLARO, TEMA_ESCURO, build_stylesheet
from desktop.widgets import botao_copiar as botao_copiar_mod
from desktop.widgets.botao_copiar import BotaoCopiar
from desktop.widgets.campo_data import CampoData
from desktop.widgets.formatters import formatar_cep_parcial, formatar_data_parcial

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


def _botoes_de_copia(tela: FichaClienteScreen) -> list[BotaoCopiar]:
    """Os botoes de copiar VISIVEIS, na ordem visual. Com o endereco expandido:
    CEP, Logradouro, Numero, Complemento, Bairro, Cidade, UF; retraido: so o do
    endereco inteiro."""
    botoes = [b for b in tela.findChildren(BotaoCopiar) if b.isVisible()]
    return sorted(botoes, key=lambda b: (b.mapTo(tela, QPoint(0, 0)).y() // 20, b.mapTo(tela, QPoint(0, 0)).x()))


def _legenda_de(campo: QWidget) -> QLabel:
    """O QLabel do titulo (legenda) do wrapper que _criar_campo_com_widget monta -
    primeiro item do QVBoxLayout do wrapper (ver _criar_campo_com_widget)."""
    return campo.parentWidget().layout().itemAt(0).widget()


def testar_ficha(app: QApplication) -> None:
    linha("3) Ficha de Cliente: grade de dados, endereço com botão copiar, aviso de revisar")
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
    y = lambda campo: campo.mapTo(tela, QPoint(0, 0)).y()  # noqa: E731
    x = lambda campo: campo.mapTo(tela, QPoint(0, 0)).x()  # noqa: E731
    # nome no cabeçalho, resumo logo abaixo, CPF/Nascimento na 1a linha da grade (mesma
    # linha); Celular/E-mail SÃO ESSENCIAIS - aparecem mesmo vazios (só os NÃO
    # essenciais somem quando vazios)
    assert y(tela._campo_nome) < y(tela._resumo_label) < y(tela._campo_cpf)
    assert abs(y(tela._campo_cpf) - y(tela._campo_nascimento)) <= 2, "CPF e Nascimento na mesma linha da grade"
    assert not tela._campo_celular.parentWidget().isHidden(), "celular é essencial: aparece mesmo vazio"
    assert not tela._pilha_email.parentWidget().isHidden(), "e-mail é essencial: aparece mesmo vazio"
    assert tela._campo_nascimento.texto() == "20/07/1990"
    print("OK: nome no cabeçalho, CPF/Nascimento no topo da grade; Celular/E-mail aparecem mesmo vazios (são campos essenciais).")

    # CPF/Nascimento/Celular tem largura maxima propria (nao esticam) - o campo deveria
    # ficar colado no titulo (mesmo x), nao sobrar espaço vazio antes dele empurrando
    # pra direita (bug real: faltava um espaçador no final da linha, ver _criar_campo_com_widget)
    for campo in (tela._campo_cpf, tela._campo_nascimento, tela._campo_celular):
        assert x(campo) == x(_legenda_de(campo)), f"{campo.objectName() or campo}: campo deveria começar no mesmo x do título"
    print("OK: CPF/Nascimento/Celular alinhados ao título (sem sobra de espaço empurrando pra direita).")

    # rede social/vinculado/pai/mãe/profissão (vazios neste cliente, os 5 NÃO
    # essenciais) começam ESCONDIDOS atrás do link "+N campos vazios"; clicar mostra
    # todos, com "—" de placeholder
    indice_pai = tela._campos_opcionais_dados.index(tela._campo_nome_pai.parentWidget())
    assert tela._campos_opcionais_dados[indice_pai].isHidden(), "pai vazio: começa escondido"
    assert "5 campos vazios" in tela._link_dados_vazios.text()
    tela._ao_clicar_link_dados_vazios()
    assert not tela._campos_opcionais_dados[indice_pai].isHidden()
    # agora sao QLineEdit editaveis: vazio de verdade e SEM texto (o "—" e so o
    # placeholder, pra nao virar um valor de verdade quando a pessoa for editar)
    assert [tela._campo_nome_pai.text(), tela._campo_nome_mae.text(), tela._campo_profissao.text()] == [""] * 3
    assert all(c.placeholderText() == "—" for c in (tela._campo_nome_pai, tela._campo_nome_mae, tela._campo_profissao))
    # mesmo bug do CPF/Nascimento/Celular: Vinculado/Pai/Mãe/Profissão também têm largura
    # máxima própria e também precisam ficar colados no título
    for campo in (tela._campo_vinculado, tela._campo_nome_pai, tela._campo_nome_mae, tela._campo_profissao):
        assert x(campo) == x(_legenda_de(campo)), f"{campo}: campo deveria começar no mesmo x do título"
    print("OK: Vinculado/Nome do pai/Nome da mãe/Profissão também alinhados ao título.")
    tela._ao_clicar_link_dados_vazios()  # volta a esconder, pro resto do teste seguir no estado padrão
    assert tela._campos_opcionais_dados[indice_pai].isHidden()
    print("OK: campos não essenciais vazios ficam escondidos atrás de um link ('+N campos vazios').")
    assert (tela._campo_logradouro.text(), tela._campo_numero.text(), tela._campo_bairro.text(), tela._campo_cidade.text(),
            tela._campo_uf.currentText()) == ("Rua das Flores", "SN", "Centro", "Curitiba", "PR")
    # agora sao QLineEdit editaveis: vazio de verdade e SEM texto (o "—" e so o
    # placeholder, como os outros campos que viraram editaveis nesta sessao)
    assert tela._campo_cep.text() == "" and tela._campo_complemento.text() == "" and not tela._aviso_endereco_revisar.isVisible()
    assert tela._campo_cep.placeholderText() == "00000-000" and tela._campo_complemento.placeholderText() == "—"
    # a grade do endereco: CEP/Logradouro/Numero na 1a linha; Complemento/Bairro/(Cidade+UF) na 2a
    # (tolerancia de poucos pixels: QLineEdit e ComboTravavel tem altura NATURAL levemente
    # diferente, o centro de cada HBox - legenda + campo + botao - arredonda diferente)
    linha1 = [y(tela._campo_cep), y(tela._campo_logradouro), y(tela._campo_numero)]
    assert max(linha1) - min(linha1) <= 2, linha1
    linha2 = [y(tela._campo_complemento), y(tela._campo_bairro), y(tela._campo_cidade), y(tela._campo_uf)]
    assert max(linha2) - min(linha2) <= 2, linha2
    assert min(linha2) > max(linha1)
    assert tela._campo_cidade.mapTo(tela, QPoint(0, 0)).x() < tela._campo_uf.mapTo(tela, QPoint(0, 0)).x(), "UF ao lado da cidade"
    print("OK: endereço em 7 campos (CEP vazio e complemento vazio mostram '—'); UF ao lado da cidade; sem aviso de revisar.")

    botoes = _botoes_de_copia(tela)
    # essenciais com copiar (CPF, Nascimento, Celular, E-mail, Cadastrado em - Tipo e
    # Vendedor são combos, sem botão) + 6 do endereço expandido (CEP/Logradouro/Número/
    # Complemento/Bairro/Cidade - UF também é combo agora que é editável, sem botão,
    # mesmo padrão de Tipo/Vendedor); os 5 não essenciais continuam escondidos (sem valor)
    assert len(botoes) == 11, f"deveria haver 11 botões de copiar (5 essenciais + 6 do endereço), há {len(botoes)}"
    cpf_copiar, nascimento_copiar, celular_copiar, email_copiar, cadastro_copiar, cep, logr, num, compl, bairro, cidade = botoes
    clipboard = QApplication.clipboard()
    for botao, esperado in ((logr, "Rua das Flores"), (num, "SN"), (bairro, "Centro"), (cidade, "Curitiba")):
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
    _botoes_de_copia(tela)[6].click()  # [0..4]=essenciais, [5]=CEP, [6]=Logradouro
    assert clipboard.text() == longo and "​" not in clipboard.text()
    print("OK: logradouro longo é copiado exatamente como foi digitado.")

    clientes_mod.adicionar_cliente({"CPF/CNPJ": CPF_REVISAR, "CLIENTE": "Cliente Revisar", "TIPO": "Cliente"})
    tela._atualizar_lista()
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

    # o texto "a revisar" e editavel/apagavel direto na ficha: editando, a pilha
    # troca pro campo de verdade, ja preenchido com o texto antigo; apagar e
    # salvar o some de vez
    tela._alternar_edicao_cliente()
    assert tela._pilha_endereco_revisar.isVisible() and tela._pilha_endereco_revisar.currentIndex() == 1
    assert tela._campo_endereco_revisar.text() == "rua tal 12 apto 3"
    tela._campo_endereco_revisar.setText("")
    tela._salvar_edicao_cliente()
    assert not tela._pilha_endereco_revisar.isVisible(), "sem texto, a pilha inteira (aviso/campo) some"
    assert clientes_mod.buscar_por_cpf(CPF_REVISAR)["ENDEREÇO (REVISAR)"] == "", "apagou e salvou pra valer"
    print("OK: 'Endereço original (revisar)' é editável/apagável direto na ficha (some quando fica vazio).")

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


def testar_dados_sem_buraco_e_multiplos_emails(app: QApplication) -> None:
    linha("3b) grade de dados sem buraco quando campos não essenciais estão vazios; e-mails múltiplos e resumo sem redundância")
    cpf = "232.002.423-96"
    clientes_mod.adicionar_cliente(
        {"CPF/CNPJ": cpf, "CLIENTE": "Cliente Vinculado", "TIPO": "Cliente",
         "NASCIMENTO": pd.Timestamp(1985, 3, 10), "VINCULADO": "Fulano de Tal",
         "EMAIL": "primeiro@exemplo.com"}
    )
    # o formulario nunca deixaria digitar 2 e-mails grudados (adicionar_cliente valida) - mas o
    # campo pode ter vindo assim de uma edicao direta na planilha, ou de antes dessa validacao
    # existir; grava direto no arquivo (bypassa o core) pra simular esse dado ja existente.
    # IMPORTANTE: usa clientes_mod.CAMINHO_XLSX (redirecionado pro `tmp` isolado em main()),
    # NUNCA o `CAMINHO_XLSX` importado no topo deste arquivo - esse continua apontando pra
    # planilha REAL (so serviu pra montar o `tmp` no main()).
    caminho_teste = clientes_mod.CAMINHO_XLSX
    # nunca openpyxl.load_workbook() direto - usa o "with" que desliga o gc por toda a
    # duracao do uso do workbook (ver o comentario em core.data_store._carregar_planilha)
    with bd._carregar_planilha(caminho_teste) as wb:
        ws = wb[bd.ABA_CLIENTES]
        coluna_email = bd.CLIENTES_COLUNAS.index("EMAIL") + 1
        for linha_planilha in range(2, ws.max_row + 1):
            if str(ws.cell(row=linha_planilha, column=2).value or "").strip() == cpf:
                ws.cell(row=linha_planilha, column=coluna_email, value="primeiro@exemplo.com segundo@exemplo.com")
                break
        else:
            raise AssertionError("cliente de teste não encontrado na planilha pra injetar o e-mail duplo")
        wb.save(caminho_teste)
    propostas_mod.adicionar_proposta(
        {"CPF": cpf, "DATA": pd.Timestamp(2026, 4, 1), "VALOR (R$)": 2000, "MESES": 12,
         "EQUIPAMENTO": "Equipamento X", "BANCO": "Banco Teste", "STATUS": "Em Análise", "OBSERVAÇÕES": ""}
    )
    tela = FichaClienteScreen()
    tela.resize(1150, 780)
    tela.show()
    app.processEvents()
    tela._selecionar_por_cpf(cpf)
    app.processEvents()

    # rede social vazia (escondida, campo NÃO essencial); pai/mãe/profissão também vazios
    # e escondidos - Vinculado a (o único não essencial com valor) reocupa o lugar da
    # rede social, ficando colado no Cadastrado em (essencial, sempre visível): nao pode
    # sobrar buraco na grade onde a rede social estaria
    y = lambda campo: campo.mapTo(tela, QPoint(0, 0)).y()  # noqa: E731
    x = lambda campo: campo.mapTo(tela, QPoint(0, 0)).x()  # noqa: E731
    assert tela._campo_rede_social.parentWidget().isHidden(), "rede social vazia continua escondida"
    assert not tela._campo_vinculado.parentWidget().isHidden()
    # tolerancia de poucos pixels: CampoData/QLabel/QLineEdit tem altura NATURAL levemente
    # diferente, entao o centro de cada HBox (legenda + campo + botao) arredonda de um
    # jeito ligeiramente diferente - continuam na mesma LINHA da grade
    assert abs(y(tela._campo_vinculado) - y(tela._rotulo_cadastro)) <= 2, "Vinculado a e Cadastrado em na mesma linha, sem buraco"
    assert x(tela._campo_vinculado) < x(tela._rotulo_cadastro)
    print("OK: com só Vinculado a visível entre os não essenciais, ele fica colado no Cadastrado em (sem buraco no lugar da Rede social).")

    # 2 e-mails digitados juntos (separados por espaço) viram 2 links de mailto, um em cada linha
    # (em modo LEITURA quem mostra o link e _rotulo_email - _campo_email e o QLineEdit de edicao,
    # que nao renderiza HTML)
    assert tela._rotulo_email.text().count("mailto:") == 2
    assert 'href="mailto:primeiro@exemplo.com"' in tela._rotulo_email.text()
    assert 'href="mailto:segundo@exemplo.com"' in tela._rotulo_email.text()
    print("OK: dois e-mails digitados juntos no mesmo campo viram 2 links de mailto separados.")

    # caso real encontrado na planilha migrada: 2 e-mails + um TELEFONE (com espaço por
    # dentro) grudados no mesmo campo - o telefone vira texto puro intacto (não um mailto:
    # quebrado, nem fragmentado nos espaços internos dele)
    misto = FichaClienteScreen._texto_com_link_de_email("a@b.com\nc@d.com\n+55 77 9208-1246")
    assert misto.count("mailto:") == 2 and "+55 77 9208-1246" in misto and "mailto:+55" not in misto
    print("OK: um trecho que não é e-mail (ex.: telefone colado junto) vira texto puro intacto, sem virar mailto: nem se fragmentar.")

    # resumo com 0 aprovadas: sem o segmento redundante "nenhuma aprovada" (só "0 aprovadas" já diz)
    assert "aprovadas" in tela._resumo_label.text() and "nenhuma aprovada" not in tela._resumo_label.text()
    print(f"OK: resumo sem redundância quando 0 aprovadas: {tela._resumo_label.text()!r}")
    tela.close()


def testar_edicao_inline(app: QApplication, msgs: _Mensagens) -> None:
    linha("3c) Edição inline (Editar/OK/Cancelar): valida sem QMessageBox, salva, cancela descarta")
    cpf = _cpf(77)
    clientes_mod.adicionar_cliente({
        "CPF/CNPJ": cpf, "CLIENTE": "OSCAR TESTE", "TIPO": "Cliente",
        "EMAIL": "oscar@exemplo.com",
    })
    tela = FichaClienteScreen()
    tela.resize(1300, 800)
    tela.show()
    tela._selecionar_por_cpf(cpf)
    app.processEvents()

    assert tela._botao_editar_cliente.isVisible() and not tela._botao_ok_cliente.isVisible()
    assert tela._botao_copiar_email.isVisible() and tela._botao_copiar_nascimento.isVisible()
    assert not tela._cabecalho_endereco.isChecked() and tela._cabecalho_endereco.isEnabled(), "endereço começa retraído, destravado"
    tela._alternar_edicao_cliente()
    assert not tela._campo_nome.isReadOnly() and tela._botao_ok_cliente.isVisible() and not tela._botao_editar_cliente.isVisible()
    # editando, o endereco forca EXPANDIDO (campos separados) e trava o retratil - pedido
    # do usuario: "só mostrar o endereço em campos separados" enquanto edita
    assert tela._cabecalho_endereco.isChecked() and not tela._cabecalho_endereco.isEnabled()
    assert tela._endereco_campos.isVisible() and not tela._endereco_resumo.isVisible()
    # os botoes de copiar (novos: e-mail/rede social/Pessoal, e os antigos: CPF/celular)
    # so fazem sentido em LEITURA - editando, some todo mundo
    for botao in (
        tela._botao_copiar_cpf, tela._botao_copiar_celular, tela._botao_copiar_email,
        tela._botao_copiar_rede_social, tela._botao_copiar_nascimento, tela._botao_copiar_pai,
        tela._botao_copiar_mae, tela._botao_copiar_profissao, tela._botao_copiar_vinculado,
        tela._botao_copiar_cadastro,
    ):
        assert not botao.isVisible(), "botão de copiar não deveria aparecer em modo de edição"
    print("OK: 'Editar' destrava os campos, troca os botões por OK/Cancelar, e some com os botões de copiar.")

    # nome vazio: rejeitado, campo marcado invalido, SEM QMessageBox
    antes = len(msgs.textos)
    tela._campo_nome.setText("")
    tela._salvar_edicao_cliente()
    assert tela._campo_nome.property("invalido") is True
    assert not tela._modo_leitura_cliente, "continua em edição - não salvou"
    assert len(msgs.textos) == antes, "erro de validação não deveria abrir QMessageBox"
    assert clientes_mod.buscar_por_cpf(cpf)["CLIENTE"] == "OSCAR TESTE", "nada foi gravado"
    print("OK: nome vazio é rejeitado (campo marcado, sem QMessageBox, nada gravado).")

    # CPF invalido (mudou de verdade, e o novo não passa no dígito verificador)
    tela._campo_nome.setText("OSCAR TESTE")
    tela._campo_cpf.setText("111.111.111-11")
    tela._salvar_edicao_cliente()
    assert tela._campo_cpf.property("invalido") is True
    assert not tela._modo_leitura_cliente
    assert len(msgs.textos) == antes
    print("OK: CPF inválido (dígito verificador não bate) é rejeitado do mesmo jeito.")

    # e-mail invalido
    tela._campo_cpf.setText(cpf)
    tela._campo_email.setText("não é um e-mail")
    tela._salvar_edicao_cliente()
    assert tela._campo_email.property("invalido") is True
    assert not tela._modo_leitura_cliente
    assert len(msgs.textos) == antes
    print("OK: e-mail inválido é rejeitado (campo marcado, sem QMessageBox).")

    # CEP incompleto (menos de 8 dígitos)
    tela._campo_email.setText("oscar@exemplo.com")
    tela._campo_cep.setText("80000")
    tela._salvar_edicao_cliente()
    assert tela._campo_cep.property("invalido") is True
    assert not tela._modo_leitura_cliente
    assert len(msgs.textos) == antes
    assert not clientes_mod.buscar_por_cpf(cpf)["CEP"], "nada foi gravado"
    print("OK: CEP incompleto é rejeitado (campo marcado, sem QMessageBox, nada gravado).")
    tela._campo_cep.setText("")

    # corrige tudo: salva de verdade, volta pra leitura, grava no disco
    tela._campo_email.setText("oscar.novo@exemplo.com")
    tela._campo_celular.setText("11987654321")
    tela._salvar_edicao_cliente()
    assert tela._modo_leitura_cliente and tela._botao_editar_cliente.isVisible()
    assert tela._campo_nome.isReadOnly()
    # o endereco volta a retraido (o estado de antes de editar) e o retratil destrava de novo
    assert not tela._cabecalho_endereco.isChecked() and tela._cabecalho_endereco.isEnabled()
    gravado = clientes_mod.buscar_por_cpf(cpf)
    # celular tem mascara ao vivo (como o CPF) - o que fica gravado e o texto JA formatado
    assert gravado["EMAIL"] == "oscar.novo@exemplo.com" and apenas_digitos(gravado["CELULAR"]) == "11987654321"
    print("OK: corrigido, salvar grava de verdade e volta pra leitura (endereço volta a retraído).")

    # Cancelar descarta o que foi digitado e rele do disco
    tela._alternar_edicao_cliente()
    tela._campo_nome.setText("NOME RABISCADO NA EDICAO")
    tela._cancelar_edicao_cliente()
    assert tela._modo_leitura_cliente
    assert tela._campo_nome.text() == "OSCAR TESTE", "cancelar deveria reler o nome de verdade do disco"
    assert clientes_mod.buscar_por_cpf(cpf)["CLIENTE"] == "OSCAR TESTE", "cancelar nao pode ter gravado nada"
    print("OK: 'Cancelar' descarta o que foi digitado (rele do disco), nada é gravado.")

    # trocar de cliente no meio de uma edicao nao deixa o proximo destravado por engano
    outro_cpf = _cpf(78)
    clientes_mod.adicionar_cliente({"CPF/CNPJ": outro_cpf, "CLIENTE": "PAULA TESTE", "TIPO": "Cliente"})
    tela._atualizar_lista()
    tela._alternar_edicao_cliente()
    assert not tela._modo_leitura_cliente
    tela._selecionar_por_cpf(outro_cpf)
    assert tela._modo_leitura_cliente, "trocar de cliente tem que voltar pra leitura sozinho"
    assert tela._campo_nome.isReadOnly()
    print("OK: selecionar outro cliente no meio de uma edição volta sozinho pra leitura.")

    tela.close()


def testar_novo_cliente_inline(app: QApplication, msgs: _Mensagens) -> None:
    linha("3d) '+ Novo Cliente' inline: valida, salva, cancela descarta")
    tela = FichaClienteScreen()
    tela.resize(1300, 800)
    tela.show()
    app.processEvents()

    assert tela._painel_stack.currentIndex() == 0, "comeca sem cliente selecionado"
    tela._iniciar_novo_cliente()
    app.processEvents()
    assert tela._painel_stack.currentIndex() == 1 and not tela._modo_leitura_cliente
    assert tela._cpf_selecionado is None and tela._modo_novo_cliente
    assert tela._campo_nome.text() == "" and tela._campo_cpf.text() == ""
    assert tela._resumo_label.text() == "Nenhuma proposta registrada ainda."
    assert not tela._botao_nova_proposta.isVisible() and not tela._botao_excluir_proposta.isVisible()
    assert not tela._botao_novo_cliente.isEnabled(), "nao pode abrir um segundo rascunho ao mesmo tempo"
    print("OK: abre em branco, já em edição - sem histórico/botões de proposta (cliente ainda não existe).")

    # nome/CPF vazios sao rejeitados do mesmo jeito que na edicao de um cliente existente
    antes = len(msgs.textos)
    tela._salvar_edicao_cliente()
    assert tela._campo_cpf.property("invalido") is True
    assert tela._modo_novo_cliente, "continua no rascunho - nao salvou"
    assert len(msgs.textos) == antes, "erro de validação não deveria abrir QMessageBox"
    print("OK: CPF/nome vazios são rejeitados (campo marcado, sem QMessageBox, nada gravado).")

    cpf_novo = _cpf(80)
    tela._campo_cpf.setText(cpf_novo)
    tela._campo_nome.setText("BEATRIZ NOVA")
    tela._campo_email.setText("não é um e-mail")
    tela._salvar_edicao_cliente()
    assert tela._campo_email.property("invalido") is True
    assert tela._modo_novo_cliente
    assert clientes_mod.buscar_por_cpf(cpf_novo) is None, "nada gravado enquanto o e-mail for inválido"
    print("OK: e-mail inválido também é rejeitado antes de gravar.")

    tela._campo_email.setText("beatriz@exemplo.com")
    tela._salvar_edicao_cliente()
    assert not tela._modo_novo_cliente and tela._modo_leitura_cliente
    assert apenas_digitos(tela._cpf_selecionado) == apenas_digitos(cpf_novo)
    assert tela._campo_nome.text() == "BEATRIZ NOVA" and tela._painel_stack.currentIndex() == 1
    assert tela._botao_nova_proposta.isVisible() and tela._botao_excluir_proposta.isVisible()
    assert tela._botao_novo_cliente.isEnabled()
    gravado = clientes_mod.buscar_por_cpf(cpf_novo)
    assert gravado is not None and gravado["CLIENTE"] == "BEATRIZ NOVA" and gravado["EMAIL"] == "beatriz@exemplo.com"
    print("OK: corrigido, salvar grava de verdade (adicionar_cliente) e reabre a ficha do cliente criado.")

    # Cancelar um rascunho descarta tudo e volta pra pagina vazia (nao ha o que reler do disco)
    tela._iniciar_novo_cliente()
    cpf_descartado = _cpf(81)
    tela._campo_cpf.setText(cpf_descartado)
    tela._campo_nome.setText("CLIENTE DESCARTADO")
    tela._cancelar_edicao_cliente()
    assert tela._painel_stack.currentIndex() == 0 and not tela._modo_novo_cliente
    assert tela._modo_leitura_cliente and tela._botao_novo_cliente.isEnabled()
    assert clientes_mod.buscar_por_cpf(cpf_descartado) is None, "cancelar não pode ter gravado nada"
    print("OK: 'Cancelar' num rascunho de cliente novo descarta tudo e volta pra 'Selecione um cliente'.")

    tela.close()


def testar_endereco_retratil(app: QApplication, cpfs: dict[str, str]) -> None:
    linha("5) Endereço retraído (uma linha por extenso) e expandido (7 campos)")
    tela = FichaClienteScreen()
    # 1900px, nao 1300 - a grade de dados (mais flexivel que o cabecalho/Contato/Pessoal
    # antigos) permite o cartao encolher mais, entao numa janela mais estreita o endereco
    # por extenso (a linha mais larga do cartao) ja fica espremido abaixo da largura de
    # uma linha só; 1900px da folga de sobra (a lista de clientes à esquerda cresce um
    # pouco conforme mais clientes fictícios vão sendo cadastrados pelos testes
    # anteriores, entao uma folga generosa evita fragilidade). Janela estreita de
    # verdade, com quebra esperada, é testado à parte em smoke_test_desktop.py
    tela.resize(1900, 900)
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
    # retraído: os 5 campos essenciais com copiar (CPF, Nascimento, Celular, E-mail,
    # Cadastrado em - todos aparecem mesmo vazios, este cliente só tem CPF/endereço) +
    # o do endereço inteiro
    assert len(botoes) == 6, f"retraído deveriam haver 6 botões de copiar (5 essenciais + endereço), há {len(botoes)}"
    botao_endereco = botoes[-1]
    botao_endereco.click()
    assert clipboard.text() == completo and botao_endereco.estado == botao_copiar_mod.ESTADO_COPIADO
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
    assert len(botoes) == 11, f"expandido: 5 essenciais + um botão de copiar por campo de endereço (6 - UF é combo, sem botão), há {len(botoes)}"
    esperado = ["80000-000", "Rua das Palmeiras", "211", "Apto 301", "Centro", "Curitiba"]
    for botao, texto in zip(botoes[5:], esperado):  # botoes[0..4] = os 5 essenciais
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
    assert (tela._campo_logradouro.text(), tela._campo_cidade.text(), tela._campo_cep.text()) == ("Avenida Central", "Curitiba", "")
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
    botao_endereco_vazio = _botoes_de_copia(tela)[-1]  # [0] é o do CPF; o do endereço (vazio) é o último
    botao_endereco_vazio.click()
    assert clipboard.text() == "anterior" and botao_endereco_vazio.estado == botao_copiar_mod.ESTADO_VAZIO, "vazio não copia '—'"
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
            # 1900px - ver o comentário equivalente em testar_endereco_retratil
            tela.resize(1900, 900)
            tela.show()
            tela._selecionar_por_cpf(cpfs["completo"])
            for _ in range(6):
                app.processEvents()

            # o titulo "Endereço" e uma SECAO (a unica que sobrou - Contato/Pessoal viraram
            # a grade de dados, sem titulo proprio) - compara direto com o que o tema define
            # pro papel "titulo_secao", em vez de com outro titulo de secao irmao
            titulo = tela._cabecalho_endereco._rotulo
            assert titulo.property("role") == "titulo_secao"
            assert _cor_do_texto(titulo) == PALETAS[tema]["texto_secundario"], \
                f"{tema}: o título 'Endereço' deveria ter a cor de 'titulo_secao' do tema"
            assert titulo.font().pixelSize() == 12, f"{tema}: título de seção deveria ter 12px (era {titulo.font().pixelSize()})"

            # o valor (endereço por extenso) compara com outro campo "campo_valor" - agora
            # que TODOS os outros campos da ficha viraram widgets editaveis (QLineEdit/
            # CampoData/ComboTravavel, sem o role "campo_valor"), a unica referencia que
            # sobrou com a mesma fabrica (_criar_rotulo_valor) e o rotulo de e-mail em
            # LEITURA (_rotulo_email, com a propriedade "caixa" - ver _preencher_ficha).
            valor = tela._campo_endereco_completo
            referencia = tela._rotulo_email
            assert _mesma_fonte(valor, referencia) and _cor_do_texto(valor) == _cor_do_texto(referencia), \
                f"{tema}: o endereço tem a mesma fonte/cor do valor dos outros campos"
            for _ in range(6):
                app.processEvents()
            # a altura e a de UMA LINHA DE TEXTO (nao a do botao de copiar do lado -
            # e o que _linha_copiavel_compacta existe pra garantir, com AlignVCenter)
            assert abs(valor.height() - valor.fontMetrics().lineSpacing()) <= 6, \
                f"{tema}: o endereço deveria ter a altura de uma linha de texto, não a do botão de copiar ({valor.height()} px)"

            # nada de "barra": o valor ocupa so a largura do texto e o botao de copiar fica logo ao lado
            # (botoes[0] e o do CPF, no cabeçalho; o do endereço e o ultimo, retraído)
            botao = _botoes_de_copia(tela)[-1]
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
            botao_cep = _botoes_de_copia(tela)[5]  # [0..4] = os 5 campos essenciais com copiar
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
    botao = _botoes_de_copia(tela)[-1]  # [0] e o do CPF, no cabeçalho
    assert valor.heightForWidth(valor.width()) > valor.fontMetrics().lineSpacing() + 2, "endereço longo em janela estreita quebra em mais linhas"
    cartao = tela._campo_nome.parentWidget()
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
        topo_cartao = tela._campo_nome.mapTo(viewport, QPoint(0, 0)).y()
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
        cartao = tela._campo_nome.parentWidget()
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
    # este script constroi MUITAS janelas/widgets Qt em sequencia (uma FichaClienteScreen
    # por secao de teste) intercaladas com leitura/escrita via openpyxl - a combinacao pode
    # fazer o coletor de lixo CICLICO do Python disparar (automatico, por contagem de
    # alocacoes) num momento infeliz e derrubar o processo (Windows fatal exception: access
    # violation - o mesmo bug de fundo corrigido em core.data_store._carregar_planilha, so
    # que ali o desligamento e so durante o uso do workbook; aqui, um script de vida curta,
    # e mais simples desligar pro processo inteiro - o lixo ciclico que sobrar e liberado
    # pelo SO quando o script termina, sem custo nenhum).
    import gc
    gc.disable()

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
            testar_ficha(app)
            testar_dados_sem_buraco_e_multiplos_emails(app)
            testar_edicao_inline(app, msgs)
            testar_novo_cliente_inline(app, msgs)
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
