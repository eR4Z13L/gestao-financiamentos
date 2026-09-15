"""Testa a camada de regras de negocio (clientes/equipamentos/propostas/dashboard)
numa COPIA temporaria do arquivo real - nunca mexe nos dados verdadeiros.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_business.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import CAMINHO_XLSX
from core import clientes as clientes_mod
from core import dashboard as dashboard_mod
from core import equipamentos as equipamentos_mod
from core import propostas as propostas_mod


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def main() -> None:
    tmp_path = CAMINHO_XLSX.parent / "_smoke_test_business.xlsx"
    shutil.copy(CAMINHO_XLSX, tmp_path)

    # aponta todos os modulos pra copia temporaria, nao pro arquivo real
    clientes_mod.CAMINHO_XLSX = tmp_path
    equipamentos_mod.CAMINHO_XLSX = tmp_path
    propostas_mod.CAMINHO_XLSX = tmp_path

    try:
        linha("1) CLIENTES - busca e validacao")
        todos = clientes_mod.listar_clientes()
        print(f"total clientes: {len(todos)}")
        primeiro_cpf = todos.iloc[0]["CPF/CNPJ"]
        primeiro_nome = todos.iloc[0]["CLIENTE"]

        achou_por_cpf = clientes_mod.buscar_por_cpf(primeiro_cpf)
        assert achou_por_cpf is not None and achou_por_cpf["CLIENTE"] == primeiro_nome
        print(f"buscar_por_cpf OK: {primeiro_cpf} -> {achou_por_cpf['CLIENTE']}")

        resultado_busca = clientes_mod.buscar(primeiro_nome.split()[0])
        assert len(resultado_busca) >= 1
        print(f"buscar por nome OK: {len(resultado_busca)} resultado(s) para '{primeiro_nome.split()[0]}'")

        try:
            clientes_mod.adicionar_cliente({"CPF/CNPJ": "111.111.111-11", "CLIENTE": "TESTE CPF INVALIDO", "TIPO": "Cliente"})
            raise SystemExit("deveria ter rejeitado CPF invalido")
        except clientes_mod.ErroCliente as exc:
            print(f"validacao de CPF invalido OK -> {exc}")

        try:
            clientes_mod.adicionar_cliente({"CPF/CNPJ": primeiro_cpf, "CLIENTE": "DUPLICADO", "TIPO": "Cliente"})
            raise SystemExit("deveria ter rejeitado CPF duplicado")
        except clientes_mod.ErroCliente as exc:
            print(f"validacao de CPF duplicado OK -> {exc}")

        try:
            clientes_mod.adicionar_cliente(
                {"CPF/CNPJ": "390.533.447-05", "CLIENTE": "EMAIL INVALIDO", "TIPO": "Cliente", "EMAIL": "nao-e-email"}
            )
            raise SystemExit("deveria ter rejeitado email invalido")
        except clientes_mod.ErroCliente as exc:
            assert "mail" in str(exc)
            print(f"validacao de e-mail invalido OK -> {exc}")

        novo_cpf = "529.982.247-25"  # CPF valido (digito verificador correto) so pra teste
        clientes_mod.adicionar_cliente(
            {"CPF/CNPJ": novo_cpf, "CLIENTE": "Cliente Smoke Test", "TIPO": "Cliente", "VENDEDOR": "TESTE"}
        )
        criado = clientes_mod.buscar_por_cpf(novo_cpf)
        assert criado is not None
        print(f"adicionar_cliente OK: {criado['CLIENTE']} ({criado['CPF/CNPJ']})")

        clientes_mod.atualizar_cliente(novo_cpf, {"CPF/CNPJ": novo_cpf, "CLIENTE": "Cliente Smoke Test", "TIPO": "Cliente", "EMAIL": "teste@teste.com"})
        atualizado = clientes_mod.buscar_por_cpf(novo_cpf)
        assert atualizado["EMAIL"] == "teste@teste.com"
        print("atualizar_cliente OK: email atualizado")

        cpf_para_remover = "111.444.777-35"  # CPF valido (digito verificador correto), so pra teste
        clientes_mod.adicionar_cliente({"CPF/CNPJ": cpf_para_remover, "CLIENTE": "Cliente Para Remover", "TIPO": "Cliente"})
        assert clientes_mod.buscar_por_cpf(cpf_para_remover) is not None
        clientes_mod.remover_cliente(cpf_para_remover)
        assert clientes_mod.buscar_por_cpf(cpf_para_remover) is None
        print("remover_cliente OK: cliente sem propostas removido.")

        try:
            clientes_mod.remover_cliente(cpf_para_remover)
            raise SystemExit("deveria ter rejeitado remover cliente ja removido")
        except clientes_mod.ErroCliente as exc:
            print(f"remover_cliente OK, recusa remover de novo -> {exc}")

        linha("2) EQUIPAMENTOS")
        equipamentos_mod.adicionar_equipamento({"FORNECEDOR": "TESTE", "EQUIPAMENTO": "Equip Smoke", "PARCELAS": 12, "VALOR PARCELA (R$)": 500})
        nomes = equipamentos_mod.listar_nomes_equipamento()
        assert "Equip Smoke" in nomes
        print(f"adicionar_equipamento OK, {len(nomes)} nomes distintos disponiveis pra sugestao")

        linha("3) PROPOSTAS - validacao e cadastro")
        try:
            propostas_mod.adicionar_proposta({"CPF": "000.000.000-00", "VALOR (R$)": 1000, "EQUIPAMENTO": "X", "BANCO": "Y"})
            raise SystemExit("deveria ter rejeitado CPF sem cliente cadastrado")
        except propostas_mod.ErroProposta as exc:
            print(f"validacao de CPF sem cliente OK -> {exc}")

        propostas_mod.adicionar_proposta(
            {"CPF": novo_cpf, "VALOR (R$)": 50000, "MESES": 24, "EQUIPAMENTO": "Equip Smoke", "BANCO": "Santander", "STATUS": propostas_mod.STATUS_EM_ANALISE}
        )
        historico = propostas_mod.historico_por_cpf(novo_cpf)
        assert len(historico) == 1
        idx = historico.index[0]
        print(f"adicionar_proposta OK, historico do cliente novo: {len(historico)} proposta(s), status={historico.iloc[0]['STATUS']}")

        propostas_mod.atualizar_proposta(idx, {"STATUS": propostas_mod.STATUS_APROVADO, "OBSERVAÇÕES": "aprovado no smoke test"})
        historico2 = propostas_mod.historico_por_cpf(novo_cpf)
        assert historico2.iloc[0]["STATUS"] == propostas_mod.STATUS_APROVADO
        print(f"atualizar_proposta OK: status agora é {historico2.iloc[0]['STATUS']}")

        linha("4) DASHBOARD")
        todas_propostas = propostas_mod.listar_propostas()
        totais = dashboard_mod.totais_gerais(todas_propostas)
        print("totais_gerais:", totais)
        assert totais["total_propostas"] == len(todas_propostas)
        assert totais["aprovadas"] >= 1

        detalhe = dashboard_mod.detalhamento_por_status(todas_propostas)
        print("\ndetalhamento_por_status:")
        print(detalhe.to_string(index=False))
        assert propostas_mod.STATUS_APROVADO in detalhe["STATUS"].values

        pv = dashboard_mod.por_vendedor(todas_propostas)
        print("\npor_vendedor (top 5):")
        print(pv.head(5).to_string(index=False))
        assert "TESTE" in pv["Vendedor"].values

        for status_extra in [propostas_mod.STATUS_PRE_APROVADO, propostas_mod.STATUS_NF_ANEXADA, propostas_mod.STATUS_GARANTIA_ASSINADA, "STATUS BEM NOVO QUE NAO EXISTE AINDA"]:
            assert propostas_mod.categoria_status(status_extra) == "Aprovado", status_extra
        assert propostas_mod.categoria_status("Negado") == "Negado"
        assert propostas_mod.categoria_status("Em Análise") == "Em Análise"
        print("\nOK: status extras/futuros contam como 'Aprovado', Negado/Em Análise ficam corretos.")

        linha("TUDO OK")
    finally:
        tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
