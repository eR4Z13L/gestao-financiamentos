"""Testa o modo leitura do PropostaDialog (proposta existente abre travada,
com botao de copiar em cada campo, e so vira formulario de edicao depois de
"Habilitar edicao"; Cancelar volta pra leitura, so Fechar fecha) - sem abrir
janela de verdade e sem mexer em nada real: tudo numa copia temporaria da
planilha.

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

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QMessageBox

from config import CAMINHO_XLSX

import config
config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
from core import clientes as clientes_mod
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from desktop.dialogs.proposta_dialog import PropostaDialog
from desktop.widgets import botao_copiar as botao_copiar_mod


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


def _abrir(proposta: dict, indice: int) -> PropostaDialog:
    dialogo = PropostaDialog(proposta["CPF"], proposta["CLIENTE"], proposta=proposta, indice=indice)
    dialogo.show()
    return dialogo


def _botao(dialogo: PropostaDialog, padrao: QDialogButtonBox.StandardButton):
    return dialogo._botoes.button(padrao)


def _travados(dialogo: PropostaDialog) -> bool:
    """Todos os campos somente leitura - e nenhum "desabilitado" (desabilitado
    apagaria a caixa e impediria selecionar o texto)."""
    return (
        dialogo._data.isReadOnly()
        and dialogo._valor.isReadOnly()
        and dialogo._meses.isReadOnly()
        and dialogo._observacoes.isReadOnly()
        and all(c.travado() and c.lineEdit().isReadOnly() for c in (dialogo._equipamento, dialogo._banco, dialogo._status))
    )


def _todos_habilitados(dialogo: PropostaDialog) -> bool:
    return all(c.isEnabled() for c in dialogo._campos_editaveis())


def _estado_leitura(dialogo: PropostaDialog) -> bool:
    return (
        dialogo._modo_leitura
        and _travados(dialogo)
        and all(b.isVisible() for b in dialogo._botoes_copiar)
        and _botao(dialogo, QDialogButtonBox.StandardButton.Close).isVisible()
        and dialogo._botao_habilitar_edicao.isVisible()
        and not _botao(dialogo, QDialogButtonBox.StandardButton.Ok).isVisible()
        and not _botao(dialogo, QDialogButtonBox.StandardButton.Cancel).isVisible()
    )


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
        assert _botao(dialogo, QDialogButtonBox.StandardButton.Close).text() == "Fechar"
        assert dialogo.windowTitle().startswith("Proposta —"), dialogo.windowTitle()
        print("OK: 7 campos somente leitura (habilitados), 7 botões de copiar, Fechar + Habilitar edição (sem OK/Cancel).")

        assert dialogo._equipamento.currentText() == proposta["EQUIPAMENTO"]
        assert dialogo._banco.currentText() == proposta["BANCO"]
        assert dialogo._status.currentText() == proposta["STATUS"]
        assert dialogo._observacoes.toPlainText() == proposta["OBSERVAÇÕES"]
        print("OK: campos mostram os valores da proposta.")

        dialogo._observacoes.selectAll()
        assert dialogo._observacoes.textCursor().selectedText() == proposta["OBSERVAÇÕES"]
        print("OK: texto continua selecionável em modo leitura.")

        linha("1b) Travado de verdade: nada muda por teclado/lista")
        meses_antes = dialogo._meses.value()
        QTest.keyClick(dialogo._meses, Qt.Key.Key_Up)
        assert dialogo._meses.value() == meses_antes, "seta pra cima nao deve mexer num campo travado"
        for combo in (dialogo._equipamento, dialogo._banco, dialogo._status):
            texto_antes = combo.currentText()
            combo.showPopup()
            assert not combo.view().isVisible(), "lista de opcoes nao deve abrir num combo travado"
            QTest.keyClick(combo, Qt.Key.Key_Down)
            assert combo.currentText() == texto_antes, "seta pra baixo nao deve trocar a opcao"
        print("OK: spin/combos travados não mudam por teclado nem abrem a lista.")

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

        linha("5) Fechar (leitura) fecha e nao grava nada")
        obs_antes = propostas_mod.listar_propostas().loc[indice, "OBSERVAÇÕES"]
        _botao(dialogo, QDialogButtonBox.StandardButton.Close).click()
        assert dialogo.result() == QDialog.DialogCode.Rejected
        assert not dialogo.isVisible(), "Fechar deve fechar o dialogo"
        assert propostas_mod.listar_propostas().loc[indice, "OBSERVAÇÕES"] == obs_antes
        print("OK: Fechar fecha o diálogo sem alterar a proposta.")

        linha("6) _salvar() em modo leitura nao grava")
        dialogo = _abrir(proposta, indice)
        dialogo._observacoes.setPlainText("NAO DEVE GRAVAR")  # setPlainText funciona mesmo travado, via codigo
        dialogo._salvar()
        assert propostas_mod.listar_propostas().loc[indice, "OBSERVAÇÕES"] == obs_antes
        assert dialogo.result() != QDialog.DialogCode.Accepted
        dialogo.close()
        print("OK: barreira de segurança - salvar em modo leitura é ignorado.")

        linha("7) Habilitar edicao vira o formulario de edicao")
        dialogo = _abrir(proposta, indice)
        dialogo._botao_habilitar_edicao.click()
        assert not dialogo._modo_leitura
        assert not any([dialogo._data.isReadOnly(), dialogo._valor.isReadOnly(), dialogo._meses.isReadOnly(), dialogo._observacoes.isReadOnly()])
        assert not any(c.travado() for c in (dialogo._equipamento, dialogo._banco, dialogo._status))
        assert not dialogo._status.isEditable(), "Status volta a ser lista fechada (so opcoes oficiais)"
        assert dialogo._equipamento.isEditable() and dialogo._banco.isEditable()
        assert dialogo._status.currentText() == proposta["STATUS"], "trocar de modo nao pode mudar o status"
        assert not any(b.isVisible() for b in dialogo._botoes_copiar), "Copiar some ao editar"
        assert _botao(dialogo, QDialogButtonBox.StandardButton.Ok).isVisible()
        assert _botao(dialogo, QDialogButtonBox.StandardButton.Cancel).isVisible()
        assert not _botao(dialogo, QDialogButtonBox.StandardButton.Close).isVisible()
        assert not dialogo._botao_habilitar_edicao.isVisible()
        assert dialogo.windowTitle().startswith("Editar proposta"), dialogo.windowTitle()
        dialogo._banco.showPopup()
        assert dialogo._banco.view().isVisible(), "editando, a lista de bancos deve abrir"
        dialogo._banco.hidePopup()
        print("OK: campos destravam, Copiar some, OK/Cancel aparecem, Fechar/Habilitar somem.")

        dialogo._observacoes.setPlainText("editado apos habilitar edicao")
        _botao(dialogo, QDialogButtonBox.StandardButton.Ok).click()
        assert dialogo.result() == QDialog.DialogCode.Accepted
        assert propostas_mod.listar_propostas().loc[indice, "OBSERVAÇÕES"] == "editado apos habilitar edicao"
        print("OK: OK grava a edição.")

        linha("8) Cancelar descarta e VOLTA pra leitura (nao fecha)")
        original = propostas_mod.listar_propostas().loc[indice].to_dict()
        dialogo = _abrir(original, indice)
        dialogo._botao_habilitar_edicao.click()
        dialogo._observacoes.setPlainText("NAO DEVE GRAVAR 2")
        dialogo._valor.setValue(1.5)
        dialogo._meses.setValue(7)
        dialogo._equipamento.setCurrentText("Equip Digitado")
        dialogo._banco.setCurrentText("Banco Digitado")
        _botao(dialogo, QDialogButtonBox.StandardButton.Cancel).click()
        assert dialogo.isVisible(), "Cancelar nao pode fechar o dialogo"
        assert _estado_leitura(dialogo), "deveria estar de volta no modo leitura"
        assert dialogo._observacoes.toPlainText() == original["OBSERVAÇÕES"], "observacoes deveria ser restaurada"
        assert abs(dialogo._valor.value() - float(original["VALOR (R$)"])) < 0.01, "valor deveria ser restaurado"
        assert dialogo._meses.value() == int(original["MESES"])
        assert dialogo._equipamento.currentText() == original["EQUIPAMENTO"]
        assert dialogo._banco.currentText() == original["BANCO"]
        assert dialogo._status.currentText() == original["STATUS"]
        assert propostas_mod.listar_propostas().loc[indice, "OBSERVAÇÕES"] == original["OBSERVAÇÕES"], "nada gravado"
        print("OK: Cancelar descarta as alterações e volta pra leitura, diálogo continua aberto.")

        dialogo._botao_habilitar_edicao.click()
        assert not dialogo._modo_leitura, "da pra habilitar a edicao de novo depois de cancelar"
        QTest.keyClick(dialogo, Qt.Key.Key_Escape)
        assert dialogo.isVisible() and dialogo._modo_leitura, "Esc em edicao age como Cancelar"
        print("OK: dá pra editar de novo; Esc em edição também só volta pra leitura.")

        _botao(dialogo, QDialogButtonBox.StandardButton.Close).click()
        assert not dialogo.isVisible(), "so Fechar (na leitura) fecha"
        assert dialogo.result() == QDialog.DialogCode.Rejected
        print("OK: Fechar, na leitura, é o que realmente fecha.")

        dialogo = _abrir(original, indice)
        QTest.keyClick(dialogo, Qt.Key.Key_Escape)
        assert not dialogo.isVisible(), "Esc em leitura fecha"
        dialogo = _abrir(original, indice)
        dialogo._botao_habilitar_edicao.click()
        dialogo.close()  # botao X da janela
        assert not dialogo.isVisible(), "X fecha de verdade mesmo em modo edicao"
        print("OK: Esc na leitura fecha; o X da janela fecha até em modo edição.")

        linha("9) Proposta nova abre direto em edicao (e Cancelar fecha)")
        novo = PropostaDialog(proposta["CPF"], proposta["CLIENTE"])
        novo.show()
        assert not novo._modo_leitura
        assert not novo._data.isReadOnly() and not novo._observacoes.isReadOnly()
        assert not any(c.travado() for c in (novo._equipamento, novo._banco, novo._status))
        assert not any(b.isVisible() for b in novo._botoes_copiar)
        assert _botao(novo, QDialogButtonBox.StandardButton.Ok).isVisible()
        assert not novo._botao_habilitar_edicao.isVisible()
        assert novo.windowTitle().startswith("Nova proposta")
        _botao(novo, QDialogButtonBox.StandardButton.Cancel).click()
        assert not novo.isVisible(), "numa proposta nova nao ha leitura pra onde voltar: Cancelar fecha"
        avulso = PropostaDialog(cpf=None)
        assert avulso._cliente_combo is not None and avulso._cliente_combo.isEnabled()
        avulso.close()
        print("OK: proposta nova (com cliente fixo ou avulsa) abre editável, sem Copiar; Cancelar fecha.")

        linha("10) VENDEDOR abre em leitura e nao ve 'Habilitar edicao'")
        sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_VENDEDOR, nome_usuario="Qualquer"))
        try:
            dialogo = _abrir(proposta, indice)
            assert dialogo._modo_leitura
            assert not dialogo._botao_habilitar_edicao.isVisible()
            assert _botao(dialogo, QDialogButtonBox.StandardButton.Close).isVisible()
            dialogo.close()
        finally:
            sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
        print("OK: sem permissão de escrita, o botão de habilitar edição nem aparece.")

        if mensagens:
            raise AssertionError(f"nenhuma mensagem de erro era esperada, apareceu: {mensagens}")
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
