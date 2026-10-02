"""Conectar a conta Google pela tela (login e Administracao): abre o navegador, espera a pessoa autorizar e
confere na hora se a conta abre a planilha - senao a sincronizacao pararia sem ninguem saber."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget

from core import conta_google
from core import data_store_sheets as leitura_sheets
from core import sheets_sync
from desktop.espera import rodar_esperando


def esquecer_conexoes() -> None:
    """As conexoes com a planilha guardam a credencial antiga: depois de trocar a conta, recriar."""
    sheets_sync.esquecer_conexao()
    leitura_sheets.esquecer_conexao()


def conectar_e_conferir(parent: QWidget | None) -> conta_google.ContaConectada | None:
    """Conecta a conta e confere o acesso a planilha. None (ja avisado): nao conectou ou a conta nao abre a
    planilha - nesse caso a conexao e desfeita e tudo fica como estava."""
    try:
        conta = rodar_esperando(
            parent, "Entre na sua conta Google no navegador que abriu e autorize o aplicativo…",
            conta_google.conectar, limite_s=None,
        )
    except conta_google.ErroContaGoogle as exc:
        QMessageBox.warning(parent, "Não foi possível conectar", str(exc))
        return None
    except Exception as exc:  # nunca falhar em silencio
        QMessageBox.critical(parent, "Erro ao conectar com o Google", f"{type(exc).__name__}: {exc}")
        return None
    esquecer_conexoes()
    try:
        rodar_esperando(parent, "Conferindo o acesso à planilha…", sheets_sync.ler_meta_da_nuvem, limite_s=60)
    except Exception as exc:
        conta_google.desconectar()
        esquecer_conexoes()
        QMessageBox.warning(
            parent,
            "Conta sem acesso à planilha",
            f"A conta {conta.email} entrou, mas não conseguiu abrir a planilha da nuvem ({type(exc).__name__}: {exc}).\n\n"
            "Peça para quem é dono da planilha compartilhá-la com essa conta como Editor e tente de novo.",
        )
        return None
    return conta
