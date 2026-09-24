"""Testa core.propostas.bancos_distintos/mesclar_bancos (E10): reescreve o campo BANCO de
propostas antigas, mescla grafias diferentes do mesmo banco, sempre com um backup do estado
atual antes. Planilha fictícia numa pasta temporária - nunca em data/.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_mesclar_bancos.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl
import pandas as pd

import config
config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
import fixture_ficticia as fx
from core import backup as backup_mod
from core import clientes as clientes_mod
from core import data_store as bd
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core.validators import _digito_verificador_cpf


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _cpf(n: int) -> str:
    base = f"{123456780 + n:09d}"
    return base + _digito_verificador_cpf(base)


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


def _proposta(cpf: str, banco: str, valor: float = 10000) -> int:
    return propostas_mod.adicionar_proposta(
        {"CPF": cpf, "DATA": pd.Timestamp.now(), "STATUS": propostas_mod.STATUS_EM_ANALISE,
         "BANCO": banco, "EQUIPAMENTO": "Equipamento X", "VALOR (R$)": valor, "MESES": 36}
    )


def testar_bancos_distintos(cpf: str) -> None:
    linha("1) bancos_distintos(): cada grafia LITERAL separada, com contagem, sem vazio")
    _proposta(cpf, "Hubcred BV")
    _proposta(cpf, "Hubcred BV")
    _proposta(cpf, "HUBCRED BV")
    _proposta(cpf, "Santander")
    _proposta(cpf, "")  # banco em branco nunca aparece na lista

    bancos = dict(propostas_mod.bancos_distintos())
    assert bancos == {"Hubcred BV": 2, "HUBCRED BV": 1, "Santander": 1}, bancos
    print(f"OK: 3 grafias distintas listadas com a contagem certa ({bancos}), banco vazio de fora.")


def testar_validacoes(cpf: str) -> None:
    linha("2) mesclar_bancos(): recusa menos de 2 grafias ou grafia final em branco")
    try:
        propostas_mod.mesclar_bancos(["Hubcred BV"], "Hubcred BV")
        raise AssertionError("deveria recusar so 1 grafia")
    except propostas_mod.ErroProposta as exc:
        assert "pelo menos 2" in str(exc)
    try:
        propostas_mod.mesclar_bancos(["Hubcred BV", "HUBCRED BV"], "   ")
        raise AssertionError("deveria recusar grafia final em branco")
    except propostas_mod.ErroProposta as exc:
        assert "grafia final" in str(exc).lower()
    try:
        propostas_mod.mesclar_bancos(["Hubcred BV", "Hubcred BV", ""], "Hubcred BV")
        raise AssertionError("grafias repetidas/vazias nao contam como '2 distintas'")
    except propostas_mod.ErroProposta as exc:
        assert "pelo menos 2" in str(exc)
    print("OK: menos de 2 grafias distintas ou grafia final em branco são recusados, com o motivo explicado.")


def testar_mesclar(cpf: str, arquivo: Path) -> None:
    linha("3) mesclar_bancos(): reescreve só as grafias marcadas, faz backup antes")
    pasta_backups = backup_mod._pasta_backups(arquivo)
    backups_antes = len(list(pasta_backups.glob("*.xlsx"))) if pasta_backups.exists() else 0

    quantidade = propostas_mod.mesclar_bancos(["Hubcred BV", "HUBCRED BV"], "Hubcred BV")
    assert quantidade == 3, quantidade  # 2 "Hubcred BV" + 1 "HUBCRED BV"

    df = propostas_mod.listar_propostas()
    assert (df["BANCO"] == "Hubcred BV").sum() == 3
    assert "HUBCRED BV" not in df["BANCO"].tolist()
    assert (df["BANCO"] == "Santander").sum() == 1, "banco nao selecionado fica intacto"
    print(f"OK: {quantidade} propostas reescritas para 'Hubcred BV'; Santander (não selecionado) intacto.")

    backups_depois = list(pasta_backups.glob("*.xlsx"))
    assert len(backups_depois) == backups_antes + 1, (backups_antes, len(backups_depois))
    ultimo = max(backups_depois, key=lambda p: p.stat().st_mtime)
    analisado = backup_mod._analisar_nome(ultimo.name)
    assert analisado is not None and analisado[0] == backup_mod.MOTIVO_PRE_MESCLAGEM, analisado
    print(f"OK: um backup 'pre-mesclagem' foi criado antes de reescrever ({ultimo.name}).")


def testar_mesclar_nao_afeta_grafia_nao_selecionada() -> None:
    linha("4) uma grafia parecida mas NÃO selecionada (comparação é exata) fica de fora")
    cpf2 = _cpf(999)
    clientes_mod.adicionar_cliente({"CPF/CNPJ": cpf2, "CLIENTE": "CLIENTE DOIS", "TIPO": "Cliente", "VENDEDOR": "ANA"})
    _proposta(cpf2, "hubcred bv")  # minusculo - grafia DIFERENTE das que foram mescladas
    antes = dict(propostas_mod.bancos_distintos())
    propostas_mod.mesclar_bancos(["Hubcred BV", "Santander"], "Hubcred BV")
    depois = dict(propostas_mod.bancos_distintos())
    assert "hubcred bv" in depois, "a grafia so em minusculo nao tinha sido marcada - fica como estava"
    assert "Santander" not in depois, "Santander foi selecionada e mesclada desta vez"
    assert depois["Hubcred BV"] == antes["Hubcred BV"] + antes.get("Santander", 0)
    print("OK: a comparação é por igualdade exata - uma grafia parecida mas não marcada não é tocada.")


def testar_exige_admin() -> None:
    linha("5) mesclar_bancos() exige ADMIN")
    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_VENDEDOR, nome_usuario="Vendedor Exemplo"))
    try:
        propostas_mod.mesclar_bancos(["Hubcred BV", "Santander"], "Hubcred BV")
        raise AssertionError("vendedor nao pode mesclar bancos")
    except sessao_mod.PermissaoNegada:
        pass
    finally:
        sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
    print("OK: um VENDEDOR logado recebe PermissaoNegada ao tentar mesclar.")


def main() -> None:
    registro_antes = fx.instantaneo_do_registro()
    tmp = Path(tempfile.mkdtemp(prefix="_smoke_mesclar_bancos_"))
    try:
        arquivo = tmp / "controle.xlsx"
        _criar_planilha_vazia(arquivo)
        fx.apontar_modulos_para(arquivo)
        sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
        cpf = _cpf(1)
        clientes_mod.adicionar_cliente({"CPF/CNPJ": cpf, "CLIENTE": "CLIENTE UM", "TIPO": "Cliente", "VENDEDOR": "ANA"})

        testar_bancos_distintos(cpf)
        testar_validacoes(cpf)
        testar_mesclar(cpf, arquivo)
        testar_mesclar_nao_afeta_grafia_nao_selecionada()
        testar_exige_admin()

        linha("TUDO OK")
    finally:
        fx.restaurar_modulos()
        sessao_mod.encerrar()
        shutil.rmtree(tmp, ignore_errors=True)
        assert fx.instantaneo_do_registro() == registro_antes, "não pode ter mexido no registro real"


if __name__ == "__main__":
    main()
