"""Uma pergunta com botoes de TEXTO proprio ("Baixar da nuvem", "Manter o meu"...), em vez do
Sim/Nao padrao - as decisoes de sincronizacao nao se explicam com Sim/Nao. Uma funcao so pra os
testes poderem trocar por uma resposta pronta (as caixas de mensagem de verdade sao modais).
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget


def escolher(
    parent: QWidget | None,
    titulo: str,
    texto: str,
    opcoes: list[str],
    *,
    aviso: bool = False,
    padrao: int = 0,
) -> int | None:
    """Mostra `texto` com um botao por opcao e devolve o INDICE da escolhida. A ULTIMA opcao e a
    saida segura ("Agora nao", "Decidir depois"): e a que Esc e o X da janela escolhem. `padrao` e o
    botao que o Enter aciona."""
    caixa = QMessageBox(parent)
    caixa.setWindowTitle(titulo)
    caixa.setText(texto)
    caixa.setIcon(QMessageBox.Icon.Warning if aviso else QMessageBox.Icon.Question)
    botoes = []
    for posicao, rotulo in enumerate(opcoes):
        papel = QMessageBox.ButtonRole.RejectRole if posicao == len(opcoes) - 1 else QMessageBox.ButtonRole.AcceptRole
        botoes.append(caixa.addButton(rotulo, papel))
    caixa.setDefaultButton(botoes[padrao])
    caixa.setEscapeButton(botoes[-1])
    caixa.exec()
    clicado = caixa.clickedButton()
    return botoes.index(clicado) if clicado in botoes else None
