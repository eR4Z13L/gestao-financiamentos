"""Gera exemplo/controle_financiamentos_exemplo.xlsx - mesma estrutura do
banco de dados real (3 abas, mesmas colunas/formulas), mas com dados 100%
ficticios. Serve de referencia no repositorio, ja que o arquivo real (com
dados verdadeiros de clientes) nunca e versionado - ver .gitignore.

Reaproveita as proprias funcoes de cadastro do app (core/clientes.py,
core/equipamentos.py, core/propostas.py), pra garantir que a estrutura
gerada bate exatamente com o que o app de verdade produz.

Rodar com: venv/Scripts/python.exe scripts/gerar_planilha_exemplo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl

from core import clientes as clientes_mod
from core import data_store as bd
from core import equipamentos as equipamentos_mod
from core import propostas as propostas_mod

DESTINO = Path(__file__).resolve().parent.parent / "exemplo" / "controle_financiamentos_exemplo.xlsx"


def _criar_planilha_vazia(caminho: Path) -> None:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for nome, colunas in (
        (bd.ABA_CLIENTES, bd.CLIENTES_COLUNAS),
        (bd.ABA_EQUIPAMENTOS, bd.EQUIPAMENTOS_COLUNAS),
        (bd.ABA_PROPOSTAS, bd.PROPOSTAS_COLUNAS),
    ):
        ws = wb.create_sheet(nome)
        ws.append(colunas)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    wb.save(caminho)


def main() -> None:
    DESTINO.unlink(missing_ok=True)
    _criar_planilha_vazia(DESTINO)

    # aponta as 3 camadas de negocio pra planilha de exemplo, nao pra real
    clientes_mod.CAMINHO_XLSX = DESTINO
    equipamentos_mod.CAMINHO_XLSX = DESTINO
    propostas_mod.CAMINHO_XLSX = DESTINO

    clientes_mod.adicionar_cliente(
        {
            "CPF/CNPJ": "529.982.247-25",
            "CLIENTE": "Maria Exemplo da Silva",
            "TIPO": "Cliente",
            "VENDEDOR": "Vendedor Exemplo",
            "CELULAR": "(11) 91234-5678",
            "EMAIL": "maria.exemplo@email.com",
            "ENDEREÇO": "Rua Fictícia, 123 - Bairro Exemplo - Cidade/UF",
            "REDE SOCIAL": "@maria.exemplo",
        }
    )
    clientes_mod.adicionar_cliente(
        {
            "CPF/CNPJ": "111.444.777-35",
            "CLIENTE": "João Exemplo Souza",
            "TIPO": "Cliente",
            "VENDEDOR": "Vendedor Exemplo",
            "CELULAR": "(21) 98888-7777",
            "EMAIL": "joao.exemplo@email.com",
            "ENDEREÇO": "Avenida Modelo, 456 - Bairro Teste - Cidade/UF",
        }
    )
    clientes_mod.adicionar_cliente(
        {
            "CPF/CNPJ": "390.533.447-05",
            "CLIENTE": "Ana Exemplo Costa",
            "TIPO": "Avalista",
            "VENDEDOR": "Vendedor Exemplo",
            "CELULAR": "(31) 97777-6666",
            "EMAIL": "ana.exemplo@email.com",
            "VINCULADO": "Maria Exemplo da Silva",
            "ENDEREÇO": "Praça Amostra, 789 - Bairro Fake - Cidade/UF",
        }
    )

    equipamentos_mod.adicionar_equipamento(
        {
            "FORNECEDOR": "Fornecedor Exemplo A",
            "EQUIPAMENTO": "Equipamento Modelo X",
            "PARCELAS": 36,
            "VALOR PARCELA (R$)": 2500,
            "VALOR LÍQUIDO/REFERÊNCIA (R$)": 65000,
            "OBSERVAÇÕES": "Valor mínimo de faturamento: R$ 65.000,00 (dado fictício)",
        }
    )
    equipamentos_mod.adicionar_equipamento(
        {
            "FORNECEDOR": "Fornecedor Exemplo B",
            "EQUIPAMENTO": "Equipamento Modelo Y",
            "PARCELAS": 24,
            "VALOR PARCELA (R$)": 1800,
            "VALOR LÍQUIDO/REFERÊNCIA (R$)": 35000,
            "OBSERVAÇÕES": "Dado fictício, só de referência",
        }
    )

    propostas_mod.adicionar_proposta(
        {
            "CPF": "529.982.247-25",
            "VALOR (R$)": 65000,
            "MESES": 36,
            "EQUIPAMENTO": "Equipamento Modelo X",
            "BANCO": "Banco Exemplo",
            "STATUS": propostas_mod.STATUS_APROVADO,
            "OBSERVAÇÕES": "Proposta fictícia de exemplo",
        }
    )
    propostas_mod.adicionar_proposta(
        {
            "CPF": "111.444.777-35",
            "VALOR (R$)": 35000,
            "MESES": 24,
            "EQUIPAMENTO": "Equipamento Modelo Y",
            "BANCO": "Outro Banco Exemplo",
            "STATUS": propostas_mod.STATUS_EM_ANALISE,
        }
    )
    propostas_mod.adicionar_proposta(
        {
            "CPF": "111.444.777-35",
            "VALOR (R$)": 40000,
            "MESES": 36,
            "EQUIPAMENTO": "Equipamento Modelo X",
            "BANCO": "Banco Exemplo",
            "STATUS": propostas_mod.STATUS_NEGADO,
            "OBSERVAÇÕES": "Negado na pré-análise (exemplo)",
        }
    )

    print(f"Planilha de exemplo gerada em: {DESTINO}")


if __name__ == "__main__":
    main()
