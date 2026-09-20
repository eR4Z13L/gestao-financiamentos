"""Testa o FormularioProposta (o conteudo do card expandido): proposta existente abre travada,
com botao de copiar em cada campo, e so vira formulario de edicao depois de "Editar"; Cancel
volta pra leitura, so Recolher recolhe o card. Tambem: o campo de DATA (o mesmo dos filtros:
da pra selecionar tudo, apagar tudo e digitar a data inteira), a deteccao de alteracoes nao
salvas e a protecao contra gravar por cima de outra proposta - sem abrir janela de verdade e
sem mexer em nada real: tudo numa copia temporaria da planilha.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_proposta_leitura.py
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from PySide6.QtCore import QDate, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from config import CAMINHO_XLSX

import config
config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
from core import clientes as clientes_mod
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from desktop.widgets import botao_copiar as botao_copiar_mod
from desktop.widgets.formulario_proposta import FormularioProposta


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _escolher_proposta_completa() -> tuple[int, dict]:
    """Uma proposta com TODOS os campos preenchidos - pra conferir cada Copiar."""
    todas = propostas_mod.listar_propostas()
    completas = todas[
        todas["DATA"].notna()
        & (todas["VALOR (R$)"].fillna(0) > 0)
        & (todas["MESES"].fillna(0) > 0)
        & (todas["BANCO"].astype(str) != "")
        & (todas["STATUS"].astype(str) != "")
        & (todas["EQUIPAMENTO"].astype(str) != "")
    ]
    assert not completas.empty, "a planilha de teste precisa ter ao menos uma proposta completa"
    escolhida = completas.iloc[0]
    return escolhida.name, escolhida.to_dict()


def _abrir(proposta: dict, indice: int) -> FormularioProposta:
    dialogo = FormularioProposta(proposta["CPF"], proposta["CLIENTE"], proposta=proposta, indice=indice)
    _registrar_eventos(dialogo)
    dialogo.show()
    return dialogo


def _registrar_eventos(dialogo: FormularioProposta) -> None:
    """O formulario nao recolhe nada sozinho: avisa por sinais (quem o hospeda decide).
    `dialogo.eventos` guarda o que foi avisado, na ordem. As funcoes ligadas aos sinais
    capturam so a LISTA, nunca o formulario (formulario -> sinal -> funcao -> formulario
    seria um ciclo, o mesmo que ja derrubou testes com "Aborted")."""
    eventos: list[str] = []
    dialogo.eventos = eventos
    dialogo.gravada.connect(lambda: eventos.append("gravada"))
    dialogo.recolher_pedido.connect(lambda: eventos.append("recolher"))
    dialogo.cancelada.connect(lambda: eventos.append("cancelada"))
    dialogo.duplicacao_pedida.connect(lambda: eventos.append("duplicar"))


def _travados(dialogo: FormularioProposta) -> bool:
    """Todos os campos somente leitura - e nenhum "desabilitado" (desabilitado
    apagaria a caixa e impediria selecionar o texto)."""
    return (
        dialogo._data.somente_leitura()
        and dialogo._valor.isReadOnly()
        and dialogo._meses.isReadOnly()
        and dialogo._observacoes.isReadOnly()
        and all(c.travado() and c.lineEdit().isReadOnly() for c in (dialogo._equipamento, dialogo._banco, dialogo._status))
    )


def _todos_habilitados(dialogo: FormularioProposta) -> bool:
    return all(c.isEnabled() for c in dialogo._campos_editaveis())


def _estado_leitura(dialogo: FormularioProposta) -> bool:
    return (
        dialogo._modo_leitura
        and _travados(dialogo)
        and all(b.isVisible() for b in dialogo._botoes_copiar)
        and dialogo._botao_recolher.isVisible()
        and dialogo._botao_editar.isVisible()
        and dialogo._botao_duplicar.isVisible()
        and not dialogo._botao_ok.isVisible()
        and not dialogo._botao_cancelar.isVisible()
    )


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))

    mensagens: list[tuple[str, str]] = []  # (titulo, texto)

    def _stub(*args, **kwargs):
        mensagens.append((str(args[1]) if len(args) > 1 else "", str(args[2]) if len(args) > 2 else ""))
        return QMessageBox.StandardButton.Ok

    def _stub_question_sim(*args, **kwargs):
        mensagens.append((str(args[1]) if len(args) > 1 else "", str(args[2]) if len(args) > 2 else ""))
        return QMessageBox.StandardButton.Yes

    original_msg = (QMessageBox.warning, QMessageBox.critical, QMessageBox.information, QMessageBox.question)
    QMessageBox.warning = staticmethod(_stub)
    QMessageBox.critical = staticmethod(_stub)
    QMessageBox.information = staticmethod(_stub)
    QMessageBox.question = staticmethod(_stub_question_sim)

    tmp_xlsx = CAMINHO_XLSX.parent / "_smoke_test_proposta_leitura.xlsx"
    shutil.copy(CAMINHO_XLSX, tmp_xlsx)
    clientes_mod.CAMINHO_XLSX = tmp_xlsx
    propostas_mod.CAMINHO_XLSX = tmp_xlsx
    duracao_original = botao_copiar_mod.DURACAO_FEEDBACK_MS

    try:
        indice, proposta = _escolher_proposta_completa()

        linha("1) Proposta existente abre em modo leitura (campos com caixa, so leitura)")
        dialogo = _abrir(proposta, indice)
        assert _estado_leitura(dialogo)
        assert _todos_habilitados(dialogo), "campos ficam habilitados (com a caixa de sempre) - so nao editam"
        assert len(dialogo._botoes_copiar) == len(dialogo._campos_editaveis()) == 7
        assert dialogo._botao_recolher.text() == "Recolher" and dialogo._botao_editar.text() == "Editar"
        assert dialogo._botao_duplicar.text() == "Duplicar"
        print("OK: 7 campos somente leitura (habilitados), 7 botões de copiar, Editar + Duplicar + Recolher (sem OK/Cancel).")

        assert dialogo._data.texto() == proposta["DATA"].strftime("%d/%m/%Y")
        assert dialogo._equipamento.currentText() == proposta["EQUIPAMENTO"]
        assert dialogo._banco.currentText() == proposta["BANCO"]
        assert dialogo._status.currentText() == proposta["STATUS"]
        assert dialogo._observacoes.toPlainText() == proposta["OBSERVAÇÕES"]
        assert dialogo._equipamento.lineEdit().cursorPosition() == 0 and dialogo._banco.lineEdit().cursorPosition() == 0, \
            "um nome comprido tem que mostrar o COMECO no campo, nao so o final"
        print("OK: campos mostram os valores da proposta (o começo do texto, se for comprido).")

        dialogo._observacoes.selectAll()
        assert dialogo._observacoes.textCursor().selectedText() == proposta["OBSERVAÇÕES"]
        dialogo._data.campo.selectAll()
        assert dialogo._data.campo.selectedText() == proposta["DATA"].strftime("%d/%m/%Y")
        print("OK: texto continua selecionável em modo leitura (inclusive a data).")

        linha("1b) Travado de verdade: nada muda por teclado/lista")
        meses_antes = dialogo._meses.value()
        QTest.keyClick(dialogo._meses, Qt.Key.Key_Up)
        assert dialogo._meses.value() == meses_antes, "seta pra cima nao deve mexer num campo travado"
        data_antes = dialogo._data.texto()
        QTest.keyClicks(dialogo._data.campo, "99")
        assert dialogo._data.texto() == data_antes, "digitar num campo de data travado nao muda nada"
        for combo in (dialogo._equipamento, dialogo._banco, dialogo._status):
            texto_antes = combo.currentText()
            combo.showPopup()
            assert not combo.view().isVisible(), "lista de opcoes nao deve abrir num combo travado"
            QTest.keyClick(combo, Qt.Key.Key_Down)
            assert combo.currentText() == texto_antes, "seta pra baixo nao deve trocar a opcao"
        print("OK: spin/data/combos travados não mudam por teclado nem abrem a lista.")

        linha("2) Copiar manda cada valor pra area de transferencia")
        clipboard = QApplication.clipboard()
        data = proposta["DATA"]
        digitos_valor = f"{float(proposta['VALOR (R$)']):.2f}".replace(".", "")
        esperados = {
            0: data.strftime("%d/%m/%Y"),
            2: str(int(proposta["MESES"])),
            3: proposta["EQUIPAMENTO"],
            4: proposta["BANCO"],
            5: proposta["STATUS"],
        }
        if proposta["OBSERVAÇÕES"]:
            esperados[6] = proposta["OBSERVAÇÕES"].strip()
        for posicao, esperado in esperados.items():
            dialogo._botoes_copiar[posicao].click()
            assert clipboard.text() == esperado, f"campo {posicao}: copiou {clipboard.text()!r}, esperado {esperado!r}"
        print(f"OK: data, meses, equipamento, banco, status{' e observações' if 6 in esperados else ''} copiados corretamente.")

        dialogo._botoes_copiar[1].click()
        copiado = clipboard.text()
        assert "R$" not in copiado, f"valor copiado nao deveria levar o prefixo R$: {copiado!r}"
        assert re.sub(r"\D", "", copiado) == digitos_valor, f"valor copiado {copiado!r} nao bate com {proposta['VALOR (R$)']}"
        print(f"OK: valor copiado sem 'R$' -> {copiado!r}")

        linha("3) Feedback discreto do botao (icone vira check, sem mexer no layout)")
        botao = dialogo._botoes_copiar[1]
        assert botao.estado == botao_copiar_mod.ESTADO_COPIADO
        assert botao.toolTip() == botao_copiar_mod.DICA_COPIADO
        assert botao.text() == "", "botao so tem icone, sem texto"
        tamanho_botao = botao.size()
        geometria_campo = dialogo._valor.geometry()
        botao_copiar_mod.DURACAO_FEEDBACK_MS = 30
        botao.click()  # reinicia o temporizador com a duracao curta
        assert botao.size() == tamanho_botao and dialogo._valor.geometry() == geometria_campo, "layout nao pode se mexer"
        QTest.qWait(150)
        assert botao.estado == botao_copiar_mod.ESTADO_NORMAL, "deveria voltar ao icone normal"
        assert botao.toolTip() == botao_copiar_mod.DICA_PADRAO
        assert botao.size() == tamanho_botao and dialogo._valor.geometry() == geometria_campo
        print("OK: ícone vira check ('Copiado!') e volta sozinho; tamanho do botão e posição do campo não mudam.")

        linha("4) Campo em branco: nao apaga a area de transferencia")
        # Valor e Meses em branco (0 = nao preenchido) -> nada a copiar
        proposta_vazia = dict(proposta, **{"VALOR (R$)": float("nan"), "MESES": float("nan")})
        dialogo_vazio = _abrir(proposta_vazia, indice)
        clipboard.setText("texto-anterior")
        dialogo_vazio._botoes_copiar[1].click()
        dialogo_vazio._botoes_copiar[2].click()
        assert clipboard.text() == "texto-anterior", "copiar campo em branco nao pode sobrescrever o que ja estava copiado"
        assert dialogo_vazio._botoes_copiar[1].estado == botao_copiar_mod.ESTADO_VAZIO
        dialogo_vazio.close()
        print("OK: valor/meses em branco sinalizam 'vazio' e preservam a área de transferência.")

        linha("5) Recolher (leitura) pede pra recolher o card e nao grava nada")
        obs_antes = propostas_mod.listar_propostas().loc[indice, "OBSERVAÇÕES"]
        dialogo._botao_recolher.click()
        assert dialogo.eventos == ["recolher"], dialogo.eventos
        assert propostas_mod.listar_propostas().loc[indice, "OBSERVAÇÕES"] == obs_antes
        print("OK: Recolher avisa o card (que recolhe) sem alterar a proposta.")

        linha("6) _salvar() em modo leitura nao grava")
        dialogo = _abrir(proposta, indice)
        dialogo._observacoes.setPlainText("NAO DEVE GRAVAR")  # setPlainText funciona mesmo travado, via codigo
        dialogo._salvar()
        assert propostas_mod.listar_propostas().loc[indice, "OBSERVAÇÕES"] == obs_antes
        assert dialogo.eventos == [], "nao grava, entao nao avisa que gravou"
        assert not dialogo.tem_alteracoes(), "em leitura nao ha 'alteracao nao salva' (nao da pra editar)"
        dialogo.close()
        print("OK: barreira de segurança - salvar em modo leitura é ignorado.")

        linha("7) Editar vira o formulario de edicao")
        dialogo = _abrir(proposta, indice)
        dialogo._botao_editar.click()
        assert not dialogo._modo_leitura
        assert not dialogo._data.somente_leitura() and dialogo._data._botao_calendario.isVisible(), "a data volta a ter o calendario"
        assert not any([dialogo._valor.isReadOnly(), dialogo._meses.isReadOnly(), dialogo._observacoes.isReadOnly()])
        assert not any(c.travado() for c in (dialogo._equipamento, dialogo._banco, dialogo._status))
        assert not dialogo._status.isEditable(), "Status volta a ser lista fechada (so opcoes oficiais)"
        assert dialogo._equipamento.isEditable() and dialogo._banco.isEditable()
        assert dialogo._status.currentText() == proposta["STATUS"], "trocar de modo nao pode mudar o status"
        assert not any(b.isVisible() for b in dialogo._botoes_copiar), "Copiar some ao editar"
        assert dialogo._botao_ok.isVisible() and dialogo._botao_cancelar.isVisible()
        assert not dialogo._botao_recolher.isVisible() and not dialogo._botao_editar.isVisible() and not dialogo._botao_duplicar.isVisible()
        dialogo._banco.showPopup()
        assert dialogo._banco.view().isVisible(), "editando, a lista de bancos deve abrir"
        dialogo._banco.hidePopup()
        print("OK: campos destravam, Copiar some, OK/Cancel aparecem, Editar/Duplicar/Recolher somem.")

        assert not dialogo.tem_alteracoes(), "recem aberto para edicao: nada digitado ainda"
        dialogo._observacoes.setPlainText("editado apos habilitar edicao")
        assert dialogo.tem_alteracoes(), "digitou algo: ha alteracao nao salva"
        dialogo._botao_ok.click()
        assert dialogo.eventos == ["gravada"], dialogo.eventos
        assert dialogo.indice_gravado == indice
        assert propostas_mod.listar_propostas().loc[indice, "OBSERVAÇÕES"] == "editado apos habilitar edicao"
        print("OK: OK grava a edição e diz qual proposta gravou; 'tem alterações' só depois de digitar.")

        linha("8) Cancelar descarta e VOLTA pra leitura (nao recolhe)")
        original = propostas_mod.listar_propostas().loc[indice].to_dict()
        dialogo = _abrir(original, indice)
        dialogo._botao_editar.click()
        dialogo._observacoes.setPlainText("NAO DEVE GRAVAR 2")
        dialogo._valor.setValue(1.5)
        dialogo._meses.setValue(7)
        dialogo._equipamento.setCurrentText("Equip Digitado")
        dialogo._banco.setCurrentText("Banco Digitado")
        dialogo._data.campo.setText("01/01/2001")
        assert dialogo.tem_alteracoes()
        dialogo._botao_cancelar.click()
        assert dialogo.isVisible() and dialogo.eventos == [], "Cancel nao recolhe o card (nem avisa nada)"
        assert _estado_leitura(dialogo), "deveria estar de volta no modo leitura"
        assert dialogo._observacoes.toPlainText() == original["OBSERVAÇÕES"], "observacoes deveria ser restaurada"
        assert abs(dialogo._valor.value() - float(original["VALOR (R$)"])) < 0.01, "valor deveria ser restaurado"
        assert dialogo._meses.value() == int(original["MESES"])
        assert dialogo._equipamento.currentText() == original["EQUIPAMENTO"]
        assert dialogo._banco.currentText() == original["BANCO"]
        assert dialogo._status.currentText() == original["STATUS"]
        assert dialogo._data.texto() == original["DATA"].strftime("%d/%m/%Y"), "a data digitada tambem e descartada"
        assert propostas_mod.listar_propostas().loc[indice, "OBSERVAÇÕES"] == original["OBSERVAÇÕES"], "nada gravado"
        print("OK: Cancel descarta as alterações e volta pra leitura, card continua aberto.")

        dialogo._botao_editar.click()
        assert not dialogo._modo_leitura, "da pra habilitar a edicao de novo depois de cancelar"
        QTest.keyClick(dialogo, Qt.Key.Key_Escape)
        assert dialogo.eventos == [] and dialogo._modo_leitura, "Esc em edicao age como Cancel"
        print("OK: dá pra editar de novo; Esc em edição também só volta pra leitura.")

        dialogo._botao_recolher.click()
        assert dialogo.eventos == ["recolher"], "so Recolher (na leitura) pede pra recolher o card"
        print("OK: Recolher, na leitura, é o que realmente recolhe o card.")

        dialogo = _abrir(original, indice)
        QTest.keyClick(dialogo, Qt.Key.Key_Escape)
        assert dialogo.eventos == ["recolher"], "Esc em leitura recolhe"
        print("OK: Esc na leitura recolhe o card.")

        # Enter aperta o botao padrao (o QDialog fazia isso sozinho): Recolher na leitura, OK na edicao
        dialogo = _abrir(original, indice)
        QTest.keyClick(dialogo, Qt.Key.Key_Return)
        assert dialogo.eventos == ["recolher"], "Enter na leitura aperta Recolher (nao 'Editar' nem 'Duplicar')"
        dialogo = _abrir(original, indice)
        dialogo._botao_editar.click()
        QTest.keyClick(dialogo._meses, Qt.Key.Key_Return)  # Enter num campo de numero: sobe ate o formulario
        assert dialogo.eventos == ["gravada"], dialogo.eventos
        dialogo = _abrir(original, indice)
        dialogo._botao_editar.click()
        dialogo._observacoes.setFocus()
        QTest.keyClick(dialogo._observacoes, Qt.Key.Key_Return)
        assert dialogo.eventos == [], "Enter nas observacoes so quebra a linha"
        print("OK: Enter aperta o botão padrão (Recolher na leitura, OK na edição), menos nas observações.")

        linha("8b) O formulario nao deixa o Enter/Esc/teclas subirem pra lista de cards")
        # o formulario mora dentro da lista, cujo Enter expande/recolhe o card: uma tecla que ninguem usou
        # (ex.: Enter com o foco num botao sem acao padrao) nao pode subir
        from PySide6.QtGui import QKeyEvent
        from PySide6.QtCore import QEvent
        dialogo = _abrir(original, indice)
        for tecla in (Qt.Key.Key_Return, Qt.Key.Key_Escape, Qt.Key.Key_Down, Qt.Key.Key_A):
            evento = QKeyEvent(QEvent.Type.KeyPress, tecla, Qt.KeyboardModifier.NoModifier)
            evento.ignore()
            dialogo.keyPressEvent(evento)
            assert evento.isAccepted(), f"tecla {tecla}: o formulario aceita tudo"
        dialogo.close()
        print("OK: o formulário consome todas as teclas que chegam a ele.")

        linha("9) Proposta nova abre direto em edicao (e Cancelar avisa)")
        novo = FormularioProposta(proposta["CPF"], proposta["CLIENTE"])
        _registrar_eventos(novo)
        novo.show()
        assert not novo._modo_leitura
        assert not novo._data.somente_leitura() and not novo._observacoes.isReadOnly()
        assert novo._data.texto() == QDate.currentDate().toString("dd/MM/yyyy"), "a data padrao e a de hoje"
        assert not any(c.travado() for c in (novo._equipamento, novo._banco, novo._status))
        assert not any(b.isVisible() for b in novo._botoes_copiar)
        assert novo._botao_ok.isVisible() and not novo._botao_editar.isVisible() and not novo._botao_duplicar.isVisible()
        assert not novo.tem_alteracoes(), "uma proposta nova em branco (so com a data de hoje) nao tem 'alteracao'"
        novo._valor.setValue(10)
        assert novo.tem_alteracoes()
        novo._botao_cancelar.click()
        assert novo.eventos == ["cancelada"], "numa proposta nova nao ha leitura pra onde voltar: Cancel avisa"
        avulso = FormularioProposta(cpf=None)
        assert avulso._cliente_combo is not None and avulso._cliente_combo.isEnabled()
        avulso.close()
        print("OK: proposta nova (com cliente fixo ou avulsa) abre editável, sem Copiar, com a data de hoje; Cancel avisa `cancelada`.")

        linha("10) VENDEDOR abre em leitura e nao ve 'Editar' nem 'Duplicar'")
        sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_VENDEDOR, nome_usuario="Qualquer"))
        try:
            dialogo = _abrir(proposta, indice)
            assert dialogo._modo_leitura
            assert not dialogo._botao_editar.isVisible()
            assert not dialogo._botao_duplicar.isVisible(), "duplicar cria proposta: tambem e so do ADMIN"
            assert dialogo._botao_recolher.isVisible()
            dialogo.close()
        finally:
            sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
        print("OK: sem permissão de escrita, os botões de editar e de duplicar nem aparecem.")

        linha("11) O campo de DATA: selecionar tudo, apagar tudo e digitar a data inteira de uma vez")
        # o bug: no QDateEdit so dava pra editar dia, mes e ano um de cada vez. Agora e o mesmo campo dos filtros.
        dialogo = _abrir(original, indice)
        dialogo._botao_editar.click()
        campo = dialogo._data.campo
        campo.setFocus()
        QTest.keyClick(campo, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        assert campo.selectedText() == original["DATA"].strftime("%d/%m/%Y"), "Ctrl+A seleciona a data inteira"
        QTest.keyClick(campo, Qt.Key.Key_Delete)
        assert dialogo._data.texto() == "", "apagar a selecao apaga a data toda (nao so ate a barra)"
        QTest.keyClicks(campo, "15032026")
        assert dialogo._data.texto() == "15/03/2026", "digita so os numeros: as barras entram sozinhas"
        campo.selectAll()
        QTest.keyClicks(campo, "01/02/2027")  # digitar por cima da selecao, com as barras e tudo (como colar)
        assert dialogo._data.texto() == "01/02/2027", dialogo._data.texto()
        campo.setText("")
        QTest.keyClicks(campo, "07")
        QTest.keyClick(campo, Qt.Key.Key_Backspace)
        QTest.keyClick(campo, Qt.Key.Key_Backspace)
        assert dialogo._data.texto() == "", "Backspace tambem apaga (inclusive a barra)"
        data_ok, erro = dialogo._data.avaliar()
        assert data_ok is None and erro == ""
        dialogo._data.definir_data(QDate(2027, 2, 1))
        assert dialogo._data.avaliar()[0] == QDate(2027, 2, 1), "uma data futura e aceita (como no filtro 'ate')"
        print("OK: Ctrl+A + Delete apaga a data inteira, digitar 15032026 vira 15/03/2026, dá pra digitar por cima da seleção.")

        obs_gravada = propostas_mod.listar_propostas().loc[indice].to_dict()
        # data em branco/incompleta/invalida: recusa com aviso claro e nao grava
        for texto, titulo_esperado in (("", "Data em branco"), ("15/0", "Data inválida"), ("31/02/2026", "Data inválida")):
            mensagens.clear()
            dialogo._data.campo.setText(texto)
            dialogo._salvar()
            assert dialogo.eventos == [] and mensagens and mensagens[-1][0] == titulo_esperado, (texto, mensagens)
        assert propostas_mod.listar_propostas().loc[indice].to_dict() == obs_gravada, "nada foi gravado com data ruim"
        # data valida escolhida de uma vez: grava
        dialogo._data.campo.setText("")
        QTest.keyClicks(dialogo._data.campo, "10112025")
        dialogo._salvar()
        assert dialogo.eventos == ["gravada"]
        assert propostas_mod.listar_propostas().loc[indice, "DATA"] == pd.Timestamp(2025, 11, 10)
        print("OK: data em branco, incompleta ou impossível não grava (aviso claro); digitada de uma vez, grava.")

        linha("12) Nao grava por cima de OUTRA proposta (a posicao ficou velha)")
        atual = propostas_mod.listar_propostas().loc[indice].to_dict()
        dialogo = _abrir(atual, indice)
        dialogo._botao_editar.click()
        # enquanto o card estava aberto, "outra tela" mudou a proposta na planilha
        propostas_mod.atualizar_proposta(indice, {"OBSERVAÇÕES": "mudou em outra tela"})
        dialogo._observacoes.setPlainText("o que eu digitei")
        mensagens.clear()
        dialogo._salvar()
        assert dialogo.eventos == [] and mensagens[-1][0] == "Não foi possível salvar" and "alterada ou excluída" in mensagens[-1][1], mensagens
        assert propostas_mod.listar_propostas().loc[indice, "OBSERVAÇÕES"] == "mudou em outra tela", "o que a outra tela gravou fica"
        print("OK: se a proposta mudou desde que o card abriu, gravar é recusado com um aviso (sem sobrescrever).")

        # o mesmo no core (excluir tambem): linha_confere ignora so o que e vazio/espaco e o tipo do numero
        assert propostas_mod.linha_confere(
            {"DATA": pd.Timestamp(2026, 1, 1), "CPF": "x", "VALOR (R$)": 5, "MESES": float("nan"), "EQUIPAMENTO": " A ",
             "BANCO": None, "STATUS": "", "OBSERVAÇÕES": None},
            {"DATA": pd.Timestamp(2026, 1, 1), "CPF": "x", "VALOR (R$)": 5.0, "MESES": None, "EQUIPAMENTO": "A",
             "BANCO": "", "STATUS": None, "OBSERVAÇÕES": ""},
        ), "vazios e espacos das pontas nao contam como diferenca"
        assert not propostas_mod.linha_confere({"EQUIPAMENTO": "A"}, {"EQUIPAMENTO": "B"})
        total = len(propostas_mod.listar_propostas())
        try:
            propostas_mod.remover_proposta(indice, esperado=dict(atual))  # 'atual' e o de ANTES da outra tela mexer
            raise AssertionError("deveria recusar excluir uma linha que ja nao e a esperada")
        except propostas_mod.ErroProposta:
            pass
        assert len(propostas_mod.listar_propostas()) == total, "nada foi excluido"
        print("OK: excluir também confere a linha antes; vazios e espaços das pontas não contam como diferença.")

        if mensagens and any(titulo not in ("Data em branco", "Data inválida", "Não foi possível salvar") for titulo, _ in mensagens):
            raise AssertionError(f"mensagem inesperada: {mensagens}")
        linha("TUDO OK")
    finally:
        botao_copiar_mod.DURACAO_FEEDBACK_MS = duracao_original
        (QMessageBox.warning, QMessageBox.critical, QMessageBox.information, QMessageBox.question) = original_msg
        clientes_mod.CAMINHO_XLSX = CAMINHO_XLSX
        propostas_mod.CAMINHO_XLSX = CAMINHO_XLSX
        tmp_xlsx.unlink(missing_ok=True)
        sessao_mod.encerrar()


if __name__ == "__main__":
    main()
