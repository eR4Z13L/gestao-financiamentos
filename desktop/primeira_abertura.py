"""Primeira abertura sem planilha de dados (instalacao nova, ou o arquivo sumiu): antes de montar a janela
principal, decide com a pessoa de onde vem a planilha - nunca abre com erro por falta dela.

- a nuvem tem dados -> oferece BAIXAR (liga o controle de versao, se a nuvem ainda nao tiver);
- a nuvem esta vazia, ou nao ha chave do Google, ou a sincronizacao esta desligada -> oferece comecar com
  uma planilha vazia (ou fechar, pra copiar o arquivo de outro computador);
- sem internet -> tentar de novo, comecar vazio ou fechar.

Comecar vazio nao atrapalha a nuvem: com uma planilha vazia aqui, a trava de versao impede que ela
sobrescreva os dados de la, e ao abrir com internet o app oferece baixar.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QMessageBox, QWidget

import config
from core import data_store as bd
from core import sincronizacao as sincronizacao_mod
from desktop.dialogs import escolha_dialog
from desktop.espera import rodar_esperando
from desktop.screens.usuarios_screen import texto_do_download

LIMITE_DA_CONSULTA_S = 45  # a consulta a nuvem que nao responde nisso conta como "sem internet"

_ACAO_BAIXAR = "baixar"
_ACAO_VAZIA = "vazia"
_ACAO_TENTAR = "tentar"
_ACAO_SAIR = "sair"


# a espera com janelinha "Aguarde" mora em desktop/espera.py (a Administracao usa a mesma)
_rodar_esperando = rodar_esperando


def _descrever_nuvem(linhas: dict[str, int]) -> str:
    return (
        f"{linhas.get(bd.ABA_CLIENTES, 0)} cliente(s), {linhas.get(bd.ABA_PROPOSTAS, 0)} proposta(s), "
        f"{linhas.get(bd.ABA_EQUIPAMENTOS, 0)} equipamento(s) e {linhas.get(bd.ABA_VENDEDORES, 0)} vendedor(es)"
    )


def _perguntar(parent: QWidget | None, caminho: Path, nuvem: sincronizacao_mod.NuvemParaPrimeiraAbertura) -> str:
    S = sincronizacao_mod
    falta = f"Não encontrei a planilha de dados deste aplicativo:\n{caminho}"
    copiar = (
        "Se você tem a planilha de outro computador ou de um backup, feche o aplicativo, copie o arquivo para a "
        f"pasta \"{caminho.parent}\" com o nome \"{caminho.name}\" e abra de novo. Se é a primeira vez, comece "
        "com uma planilha vazia."
    )
    if nuvem.tipo == S.NUVEM_COM_DADOS:
        escolha = escolha_dialog.escolher(
            parent,
            "Baixar os dados da nuvem",
            f"{falta}\n\nA nuvem tem {_descrever_nuvem(nuvem.linhas or {})}. Baixar esses dados para este computador?",
            ["Baixar da nuvem", "Fechar o aplicativo"],
        )
        return _ACAO_BAIXAR if escolha == 0 else _ACAO_SAIR
    if nuvem.tipo == S.NUVEM_SEM_REDE:
        escolha = escolha_dialog.escolher(
            parent,
            "Sem conexão com a nuvem",
            f"{falta}\n\nNão consegui consultar a nuvem agora ({nuvem.detalhe}).\n\nSe a nuvem tiver dados, o melhor "
            "é tentar de novo com internet. Começar com uma planilha vazia também é seguro: quando a conexão "
            "voltar, o aplicativo avisa e oferece baixar os dados da nuvem.",
            ["Tentar de novo", "Começar com uma planilha vazia", "Fechar o aplicativo"],
            aviso=True,
        )
        return {0: _ACAO_TENTAR, 1: _ACAO_VAZIA}.get(escolha, _ACAO_SAIR)
    motivo = {
        S.NUVEM_SEM_CHAVE: "A chave do Google (service_account_admin.json) não está neste computador, então não dá "
        "para buscar os dados na nuvem: o aplicativo vai funcionar só aqui até a chave ser instalada.\n\n",
        S.NUVEM_VAZIA: "A nuvem também não tem dados.\n\n",
    }.get(nuvem.tipo, "")
    escolha = escolha_dialog.escolher(
        parent,
        "Planilha de dados não encontrada",
        f"{falta}\n\n{motivo}{copiar}",
        ["Começar com uma planilha vazia", "Fechar o aplicativo"],
    )
    return _ACAO_VAZIA if escolha == 0 else _ACAO_SAIR


def _criar_vazia(parent: QWidget | None, caminho: Path) -> None:
    try:
        bd.criar_planilha_vazia(caminho)
    except Exception as exc:  # nunca falhar em silencio: a pergunta volta
        QMessageBox.critical(parent, "Não foi possível criar a planilha", f"{type(exc).__name__}: {exc}")
        return
    QMessageBox.information(
        parent,
        "Planilha criada",
        f"Comecei uma planilha nova, vazia, em:\n{caminho}\n\nCadastre clientes, equipamentos e vendedores pelo "
        "aplicativo normalmente.",
    )


def _baixar(parent: QWidget | None, caminho: Path) -> None:
    try:
        resultado = _rodar_esperando(
            parent,
            "Baixando os dados da nuvem…",
            lambda: sincronizacao_mod.baixar_da_nuvem(caminho, ligar_controle=True),
            limite_s=None,
        )
    except sincronizacao_mod.ErroNuvem as exc:
        QMessageBox.warning(parent, "Não foi possível baixar da nuvem", str(exc))
        return
    except Exception as exc:  # nunca falhar em silencio: a pergunta volta
        QMessageBox.critical(parent, "Erro ao baixar da nuvem", f"{type(exc).__name__}: {exc}")
        return
    QMessageBox.information(parent, "Dados baixados", texto_do_download(resultado))


def garantir_planilha(parent: QWidget | None = None, caminho: Path | None = None) -> bool:
    """Se nao ha planilha de dados, pergunta de onde ela vem ate existir uma (ou a pessoa desistir).
    True: ha planilha, pode abrir a janela principal. False: a pessoa escolheu fechar o aplicativo."""
    caminho = caminho or config.CAMINHO_XLSX
    while not caminho.exists():
        try:
            nuvem = _rodar_esperando(
                parent,
                "Procurando os dados na nuvem…",
                sincronizacao_mod.consultar_nuvem_para_primeira_abertura,
                limite_s=LIMITE_DA_CONSULTA_S,
            )
        except TimeoutError as exc:
            nuvem = sincronizacao_mod.NuvemParaPrimeiraAbertura(sincronizacao_mod.NUVEM_SEM_REDE, detalhe=str(exc))
        acao = _perguntar(parent, caminho, nuvem)
        if acao == _ACAO_SAIR:
            return False
        if acao == _ACAO_VAZIA:
            _criar_vazia(parent, caminho)
        elif acao == _ACAO_BAIXAR:
            _baixar(parent, caminho)
    return True
