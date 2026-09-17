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
from core import vendedores as vendedores_mod


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def main() -> None:
    tmp_path = CAMINHO_XLSX.parent / "_smoke_test_business.xlsx"
    shutil.copy(CAMINHO_XLSX, tmp_path)

    # aponta todos os modulos pra copia temporaria, nao pro arquivo real
    clientes_mod.CAMINHO_XLSX = tmp_path
    equipamentos_mod.CAMINHO_XLSX = tmp_path
    propostas_mod.CAMINHO_XLSX = tmp_path
    vendedores_mod.CAMINHO_XLSX = tmp_path

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
        vendedores_mod.adicionar_vendedor("TESTE")  # precisa estar no cadastro oficial pra aparecer no dashboard
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

        for status_extra in [propostas_mod.STATUS_PRE_APROVADO, propostas_mod.STATUS_NF_ANEXADA, propostas_mod.STATUS_GARANTIA_ASSINADA]:
            assert propostas_mod.categoria_status(status_extra) == "Aprovado", status_extra
        assert propostas_mod.categoria_status("Negado") == "Negado"
        assert propostas_mod.categoria_status("Cancelado") == "Negado"
        assert propostas_mod.categoria_status("Em Análise") == "Em Análise"
        # status desconhecido/mal digitado NAO conta como aprovado - isso
        # inflaria a taxa de aprovacao e o valor aprovado com dado ruim
        assert propostas_mod.categoria_status("STATUS BEM NOVO QUE NAO EXISTE AINDA") == "Não identificado"
        assert propostas_mod.categoria_status("") == ""
        print("\nOK: etapas oficiais do funil contam como 'Aprovado'; status desconhecido vira 'Não identificado'.")

        linha("4b) DASHBOARD - gap de status em branco/desconhecido em totais_gerais (achado C8)")
        # proposta com STATUS em branco - nao pode ser contabilizada em
        # nenhum dos 3 cards (Aprovadas/Negadas/Em Análise), mas TEM que
        # continuar entrando no Total e aparecer em totais["sem_status"]
        propostas_mod.adicionar_proposta(
            {"CPF": novo_cpf, "VALOR (R$)": 1000, "EQUIPAMENTO": "Equip Smoke", "BANCO": "Santander", "STATUS": ""}
        )
        # proposta com STATUS preenchido mas fora de qualquer categoria
        # conhecida - tambem nao pode inflar "Aprovadas"
        propostas_mod.adicionar_proposta(
            {
                "CPF": novo_cpf, "VALOR (R$)": 2000, "EQUIPAMENTO": "Equip Smoke", "BANCO": "Santander",
                "STATUS": "Status Maluco Que Nao Existe",
            }
        )

        antes = totais  # totais calculado em 4), antes de adicionar essas 2 propostas
        propostas_atualizadas = propostas_mod.listar_propostas()
        depois = dashboard_mod.totais_gerais(propostas_atualizadas)
        print("totais_gerais depois de status em branco + desconhecido:", depois)

        assert depois["total_propostas"] == antes["total_propostas"] + 2
        assert depois["sem_status"] == antes["sem_status"] + 1
        assert depois["nao_identificado"] == antes["nao_identificado"] + 1
        # nenhuma das duas pode ter sido contada como aprovada/negada/em analise
        assert depois["aprovadas"] == antes["aprovadas"]
        assert depois["negadas"] == antes["negadas"]
        assert depois["em_analise"] == antes["em_analise"]
        gap = depois["total_propostas"] - depois["aprovadas"] - depois["negadas"] - depois["em_analise"]
        assert gap == depois["sem_status"] + depois["nao_identificado"], "o gap tem que bater exatamente com sem_status+nao_identificado"
        print(f"OK: {gap} proposta(s) fora dos 3 cards ficam visiveis em sem_status/nao_identificado, sem sumir nem virar 'Aprovado'.")

        linha("4c) DASHBOARD - 'Aprovado' sem VALOR não vira R$0 silenciosamente (achado #22)")
        # cria com um valor valido (adicionar_proposta exige) e depois edita
        # removendo o valor - e o unico jeito de chegar num "Aprovado sem
        # valor" pelo fluxo normal (editar proposta antiga sem valor e permitido,
        # lançar uma nova sem valor não é - achado #16)
        propostas_mod.adicionar_proposta(
            {
                "CPF": novo_cpf, "VALOR (R$)": 999, "EQUIPAMENTO": "Equip Smoke", "BANCO": "Santander",
                "STATUS": propostas_mod.STATUS_APROVADO, "OBSERVAÇÕES": "marcador smoke test 4c",
            }
        )
        # varias propostas do mesmo CPF caem na mesma data ("hoje") neste
        # teste - sort_values por DATA usa quicksort (nao estavel), entao
        # ".index[0]" poderia pegar OUTRA proposta em caso de empate. Acha a
        # que acabou de ser criada pelo marcador, em vez de confiar na ordem.
        historico_novo_cpf = propostas_mod.historico_por_cpf(novo_cpf)
        idx_aprovada_sem_valor = historico_novo_cpf.index[
            historico_novo_cpf["OBSERVAÇÕES"] == "marcador smoke test 4c"
        ][0]
        propostas_mod.atualizar_proposta(idx_aprovada_sem_valor, {"VALOR (R$)": ""})

        antes_c = depois
        totais_c = dashboard_mod.totais_gerais(propostas_mod.listar_propostas())
        assert totais_c["aprovadas_sem_valor"] == antes_c["aprovadas_sem_valor"] + 1
        # ainda conta como aprovada (o status é válido) mas o valor "ausente"
        # não pode ter entrado como 0 na soma - valor_aprovado so pode ter
        # subido pelas OUTRAS aprovadas que tem valor de verdade, nunca por essa
        assert totais_c["valor_aprovado"] == antes_c["valor_aprovado"]
        print(
            f"OK: aprovadas_sem_valor foi de {antes_c['aprovadas_sem_valor']} para {totais_c['aprovadas_sem_valor']}, "
            f"e valor_aprovado não mudou (R$ {totais_c['valor_aprovado']:.2f}) - valor ausente não virou R$0."
        )

        linha("TUDO OK")
    finally:
        tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
