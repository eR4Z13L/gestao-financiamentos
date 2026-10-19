"""Testa a regra de transição do status "Não efetivado" (só a partir de "Aprovado") e que "Encerrada" ainda se
grava pelo core. O diálogo "Encerrar as outras propostas desta venda?" e as funções de "mesma venda em bancos
diferentes" saíram no plano 1.3 (o conversor dos dados antigos pergunta o que fazer com cada "Encerrada").
Dados FICTÍCIOS numa planilha temporária; preferências isoladas (nunca toca o registro real do Windows).

Rodar com: venv/Scripts/python.exe scripts/smoke_test_mesma_venda.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl
from PySide6.QtWidgets import QApplication

import config
config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
import fixture_ficticia as fx
from core import bancos as bancos_mod
from core import clientes as clientes_mod
from core import data_store as bd
from core import equipamentos as equipamentos_mod
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import vendedores as vendedores_mod
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


def _cliente(cpf: str, nome: str) -> None:
    clientes_mod.adicionar_cliente({"CPF/CNPJ": cpf, "CLIENTE": nome, "TIPO": "Cliente", "VENDEDOR": "ANA"})


def testar_transicao(arquivo: Path) -> None:
    linha("1) 'Não efetivado' só a partir de 'Aprovado'; 'Encerrada' pode ser escolhida à mão")
    cpf = _cpf(0)
    _cliente(cpf, "CLIENTE TRANSICAO")

    try:
        propostas_mod.adicionar_proposta(
            {"CPF": cpf, "VALOR (R$)": 1000, "EQUIPAMENTO": "EQ", "BANCO": "Banco A", "STATUS": "Não efetivado"}
        )
    except propostas_mod.ErroProposta as exc:
        assert "Aprovado" in str(exc)
    else:
        raise AssertionError("deveria recusar 'Não efetivado' numa proposta nova")

    indice = propostas_mod.adicionar_proposta(
        {"CPF": cpf, "VALOR (R$)": 1000, "EQUIPAMENTO": "EQ", "BANCO": "Banco A", "STATUS": "Em Análise"}
    )
    try:
        propostas_mod.atualizar_proposta(indice, {"STATUS": "Não efetivado"})
    except propostas_mod.ErroProposta as exc:
        assert "Aprovado" in str(exc)
    else:
        raise AssertionError("deveria recusar a partir de 'Em Análise'")

    propostas_mod.atualizar_proposta(indice, {"STATUS": "Aprovado"})
    propostas_mod.atualizar_proposta(indice, {"STATUS": "Não efetivado"})  # agora pode
    assert bd.ler_propostas(arquivo).loc[indice, "STATUS"] == "Não efetivado"
    print("OK: 'Não efetivado' só a partir de uma proposta que estava exatamente 'Aprovado' (nunca ao criar).")

    indice2 = propostas_mod.adicionar_proposta(
        {"CPF": cpf, "VALOR (R$)": 1500, "EQUIPAMENTO": "EQ2", "BANCO": "Banco B", "STATUS": "Em Análise"}
    )
    propostas_mod.atualizar_proposta(indice2, {"STATUS": "Encerrada"})
    assert bd.ler_propostas(arquivo).loc[indice2, "STATUS"] == "Encerrada"
    print("OK: 'Encerrada' ainda se grava pelo core (dado de antes: o conversor pergunta a resposta de cada uma).")


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    registro_antes = fx.instantaneo_do_registro()
    tmp = Path(tempfile.mkdtemp(prefix="_smoke_mesma_venda_"))
    fx.isolar_preferencias(tmp)
    try:
        arquivo = tmp / "controle.xlsx"
        _criar_planilha_vazia(arquivo)
        bancos_mod.CAMINHO_XLSX = clientes_mod.CAMINHO_XLSX = propostas_mod.CAMINHO_XLSX = vendedores_mod.CAMINHO_XLSX = equipamentos_mod.CAMINHO_XLSX = arquivo
        sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
        vendedores_mod.adicionar_vendedor("ANA")

        testar_transicao(arquivo)

        linha("TUDO OK")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        assert fx.instantaneo_do_registro() == registro_antes, "não pode ter mexido no registro real"


if __name__ == "__main__":
    main()
