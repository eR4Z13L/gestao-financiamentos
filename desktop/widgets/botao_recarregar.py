"""O botao "Recarregar" do cabecalho das telas: rele a planilha DESTE computador. Um so lugar pro texto e
pra dica - antes se chamava "Atualizar" e parecia sincronizar com a nuvem, o que ele nunca fez."""

from __future__ import annotations

from PySide6.QtWidgets import QPushButton

TEXTO = "Recarregar"
DICA = (
    "Lê de novo a planilha deste computador. Não mexe na nuvem: para isso, use o indicador de "
    "sincronização na barra lateral ou Administração > Sincronização e backup."
)


def criar_botao_recarregar(ao_clicar) -> QPushButton:
    botao = QPushButton(TEXTO)
    botao.setProperty("role", "botao_primario")
    botao.setToolTip(DICA)
    botao.clicked.connect(ao_clicar)
    return botao
