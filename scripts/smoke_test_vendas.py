"""Testa a base das vendas (core/vendas.py e as abas VENDAS/HISTÓRICO de core/data_store.py): criar venda com um ou
mais equipamentos, mandar a outro banco, as regras de status da proposta e da venda, o historico, os alertas de 7
dias, planilha antiga sem as colunas novas e a sincronizacao das abas novas (inclusive com uma nuvem sem elas).

Tudo numa planilha 100% ficticia em pasta temporaria (scripts/fixture_ficticia.py); o Google fica desligado.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_vendas.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import gspread
import openpyxl
import pandas as pd

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False
import fixture_ficticia as fx
from core import data_store as bd
from core import data_store_sheets as nuvem
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import sheets_sync
from core import sincronizacao
from core import vendas as v

ADMIN = sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador")


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _recusa(trecho: str, funcao, *args, **kwargs) -> None:
    try:
        funcao(*args, **kwargs)
    except v.ErroVenda as exc:
        assert trecho in str(exc), (trecho, str(exc))
        return
    raise AssertionError(f"deveria recusar ({trecho})")


def _pedido(banco: str, valor: float = 50000, **extra) -> dict:
    return {"BANCO": banco, "VALOR (R$)": valor, "MESES": 36, **extra}


def main() -> None:
    def _sem_rede(*_a, **_k):
        raise AssertionError("o teste tentou acessar o Google de verdade")

    rede_original = (nuvem._obter_cliente, sheets_sync._obter_cliente)
    nuvem._obter_cliente = sheets_sync._obter_cliente = _sem_rede
    pasta = Path(tempfile.mkdtemp(prefix="_smoke_vendas_"))
    caminho = fx.criar(pasta)
    fx.apontar_modulos_para(caminho)
    sessao_mod.iniciar(ADMIN)
    try:
        linha("1) Planilha de antes das vendas: lê sem as colunas e abas novas, e editar não estraga nada")
        antes = bd.ler_propostas(caminho)
        assert (antes["ID_PROPOSTA"] == "").all() and (antes["ID_VENDA"] == "").all()
        assert bd.ler_vendas(caminho).empty and bd.ler_historico(caminho).empty
        with open(caminho, "rb") as f:
            assert {bd.ABA_VENDAS, bd.ABA_HISTORICO}.isdisjoint(openpyxl.load_workbook(f).sheetnames), "ler nunca cria aba"
        print("OK: planilha antiga lê normal (IDs em branco, sem abas novas) e ler não grava nada.")

        linha("2) Criar venda: venda + 1ª proposta + histórico, numa gravação só")
        id_venda, id_p1 = v.criar_venda(fx.CPF_MARIA, ["Cadeira Exemplo", "  laser exemplo ", "CADEIRA EXEMPLO"], _pedido("Banco Exemplo"))
        vendas = bd.ler_vendas(caminho)
        assert len(vendas) == 1 and id_venda.startswith("V-") and id_p1.startswith("P-")
        venda = vendas.iloc[0]
        assert venda["EQUIPAMENTOS"] == "Cadeira Exemplo + laser exemplo", "repetido some, espaços saem"
        assert venda["STATUS"] == v.VENDA_AGUARDANDO and venda["BANCO_ESCOLHIDO"] == ""
        p1 = bd.ler_propostas(caminho).set_index("ID_PROPOSTA").loc[id_p1]
        assert p1["ID_VENDA"] == id_venda and p1["EQUIPAMENTO"] == venda["EQUIPAMENTOS"], "sem equipamento: cobre a venda toda"
        assert p1["STATUS"] == propostas_mod.STATUS_EM_ANALISE
        hist = bd.ler_historico(caminho)
        assert list(hist["ID"]) == [id_venda, id_p1] and list(hist["PARA"]) == [v.VENDA_AGUARDANDO, propostas_mod.STATUS_EM_ANALISE]
        assert hist["COMPUTADOR"].iloc[0] == sheets_sync.nome_desta_maquina() and hist["QUANDO"].notna().all()
        with open(caminho, "rb") as f:
            ws = openpyxl.load_workbook(f)[bd.ABA_PROPOSTAS]
            assert [ws.cell(row=1, column=j).value for j in (12, 13)] == ["ID_PROPOSTA", "ID_VENDA"]
        print("OK: venda com 2 equipamentos, pedido cobrindo os dois, histórico com quando/de quem; cabeçalhos novos gravados.")
        _recusa("pelo menos um equipamento", v.criar_venda, fx.CPF_MARIA, ["  "], _pedido("Banco Exemplo"))
        _recusa("Status de proposta", v.criar_venda, fx.CPF_MARIA, ["X"], _pedido("Banco Exemplo", STATUS="Efetivado"))
        _recusa("Informe o banco", v.criar_venda, fx.CPF_MARIA, ["X"], _pedido(""))
        try:
            v.criar_venda("000.000.000-00", ["X"], _pedido("Banco Exemplo"))
            raise AssertionError("cliente não cadastrado deveria ser recusado pela validação de sempre")
        except propostas_mod.ErroProposta:
            pass
        assert len(bd.ler_vendas(caminho)) == 1, "recusa não grava nada"
        print("OK: sem equipamento, sem banco, status de venda numa proposta e cliente não cadastrado são recusados, sem gravar nada.")

        linha("3) Mandar a outro banco (inclusive um pedido só de parte da venda)")
        id_p2 = v.mandar_a_outro_banco(id_venda, _pedido("Outro Banco Exemplo"))
        id_p3 = v.mandar_a_outro_banco(id_venda, _pedido("Banco Terceiro", 20000, EQUIPAMENTO="laser exemplo"))
        da_venda = v.propostas_da_venda(id_venda).set_index("ID_PROPOSTA")
        assert list(da_venda.index) == [id_p1, id_p2, id_p3]
        assert da_venda.loc[id_p3, "EQUIPAMENTO"] == "laser exemplo" and da_venda.loc[id_p2, "EQUIPAMENTO"] == venda["EQUIPAMENTOS"]
        print("OK: 3 propostas na mesma venda; uma delas só com o laser.")

        linha("4) Status da proposta: só os 4 do banco; 'todas negadas' sugere Perdida")
        _recusa("Status de proposta", v.mudar_status_proposta, id_p1, "Nota Fiscal Anexada")
        assert v.mudar_status_proposta(id_p1, propostas_mod.STATUS_NEGADO) is False
        assert v.mudar_status_proposta(id_p2, propostas_mod.STATUS_NEGADO) is False, "ainda falta uma"
        assert v.mudar_status_proposta(id_p3, propostas_mod.STATUS_NEGADO) is True, "a última negada sugere Perdida"
        assert bd.ler_vendas(caminho).iloc[0]["STATUS"] == v.VENDA_AGUARDANDO, "o app nunca marca Perdida sozinho"
        assert v.mudar_status_proposta(id_p3, propostas_mod.STATUS_NEGADO) is False, "sem mudança, nada a sugerir"
        trocas = bd.ler_historico(caminho)
        assert list(trocas[trocas["ID"] == id_p1]["PARA"]) == [propostas_mod.STATUS_EM_ANALISE, propostas_mod.STATUS_NEGADO]
        assert trocas[trocas["ID"] == id_p1]["DE"].iloc[-1] == propostas_mod.STATUS_EM_ANALISE
        print("OK: só Em Análise/Pré-aprovado/Aprovado/Negado; a última negada sugere Perdida (sem marcar sozinho); histórico com de→para.")

        linha("5) Status da venda: banco escolhido, efetivada, desfechos, voltar atrás")
        _recusa("Escolha qual banco", v.mudar_status_venda, id_venda, v.VENDA_BANCO_ESCOLHIDO)
        _recusa("que aprovou", v.mudar_status_venda, id_venda, v.VENDA_BANCO_ESCOLHIDO, proposta_escolhida=id_p2)
        _recusa("Escolha o banco antes", v.mudar_status_venda, id_venda, v.VENDA_EFETIVADA)
        v.mudar_status_proposta(id_p2, propostas_mod.STATUS_APROVADO)
        outra_venda, outra_p = v.criar_venda(fx.CPF_JOAO, ["Mesa Exemplo"], _pedido("Banco Exemplo"))
        v.mudar_status_proposta(outra_p, propostas_mod.STATUS_APROVADO)
        _recusa("outra venda", v.mudar_status_venda, id_venda, v.VENDA_BANCO_ESCOLHIDO, proposta_escolhida=outra_p)
        v.mudar_status_venda(id_venda, v.VENDA_BANCO_ESCOLHIDO, proposta_escolhida=id_p2)
        assert bd.ler_vendas(caminho).set_index("ID_VENDA").loc[id_venda, "BANCO_ESCOLHIDO"] == id_p2
        _recusa("banco escolhido", v.mudar_status_proposta, id_p2, propostas_mod.STATUS_NEGADO)
        v.mudar_status_venda(id_venda, v.VENDA_GARANTIA)  # a ordem nota/garantia é livre
        v.mudar_status_venda(id_venda, v.VENDA_NOTA_FISCAL)
        v.mudar_status_venda(id_venda, v.VENDA_EFETIVADA)
        _recusa("já está", v.mandar_a_outro_banco, id_venda, _pedido("Banco Exemplo"))
        print("OK: só escolhe banco que aprovou e da própria venda; efetivada só com banco; nota e garantia em qualquer ordem.")

        _recusa("só vale para", v.mudar_status_venda, outra_venda, v.VENDA_BANCO_ESCOLHIDO, proposta_escolhida=outra_p, motivo="Desistiu")
        _recusa("Motivo inválido", v.mudar_status_venda, outra_venda, v.VENDA_PERDIDA, motivo="Porque sim")
        v.mudar_status_venda(outra_venda, v.VENDA_BANCO_ESCOLHIDO, proposta_escolhida=outra_p)
        v.mudar_status_venda(outra_venda, v.VENDA_NAO_EFETIVADA, motivo="Comprou à vista")
        assert bd.ler_vendas(caminho).set_index("ID_VENDA").loc[outra_venda, "MOTIVO"] == "Comprou à vista"
        v.mudar_status_venda(outra_venda, v.VENDA_AGUARDANDO)  # desfazer
        reaberta = bd.ler_vendas(caminho).set_index("ID_VENDA").loc[outra_venda]
        assert reaberta["MOTIVO"] == "" and reaberta["BANCO_ESCOLHIDO"] == ""
        v.mudar_status_venda(outra_venda, v.VENDA_PERDIDA)  # motivo é opcional
        print("OK: motivo só nos desfechos, da lista e opcional; voltar atrás limpa motivo e banco escolhido.")

        assert v.proxima_etapa(v.VENDA_AGUARDANDO) == v.VENDA_BANCO_ESCOLHIDO and v.proxima_etapa(v.VENDA_GARANTIA) == v.VENDA_EFETIVADA
        assert v.proxima_etapa(v.VENDA_EFETIVADA) is None and v.proxima_etapa(v.VENDA_PERDIDA) is None
        print("OK: 'Avançar para…' sabe a próxima etapa (e não oferece nada depois do fim).")

        linha("6) Alertas de 7 dias")
        dez_dias = pd.Timestamp(date.today() - timedelta(days=10))
        id_v3, id_p4 = v.criar_venda(fx.CPF_ANA, ["Autoclave Exemplo"], _pedido("Banco Exemplo", DATA=dez_dias))
        hist = bd.ler_historico(caminho)
        hist.loc[hist["ID"].isin([id_v3, id_p4]), "QUANDO"] = dez_dias  # como se tivesse sido criada há 10 dias
        bd.escrever_tudo(caminho, bd.ler_clientes(caminho), bd.ler_equipamentos(caminho), bd.ler_vendedores(caminho),
                         bd.ler_propostas(caminho), historico=hist)
        alertas = {(a.tipo, a.id): a for a in v.alertas()}
        assert (v.TIPO_PROPOSTA, id_p4) in alertas and alertas[(v.TIPO_PROPOSTA, id_p4)].dias == 10
        assert (v.TIPO_VENDA, id_v3) in alertas and "parada" in alertas[(v.TIPO_VENDA, id_v3)].texto
        assert (v.TIPO_VENDA, id_venda) not in alertas, "venda efetivada não alerta"
        assert all(a.id for a in alertas.values()), "propostas antigas sem ID não entram"
        v.mudar_status_proposta(id_p4, propostas_mod.STATUS_PRE_APROVADO)
        assert (v.TIPO_PROPOSTA, id_p4) not in {(a.tipo, a.id) for a in v.alertas()}, "mudou hoje: zera a contagem"
        assert not {(a.tipo, a.id) for a in v.alertas(date.today() - timedelta(days=5))} & {(v.TIPO_VENDA, id_v3)}
        print("OK: proposta sem resposta e venda parada há 10 dias alertam; mudar hoje zera; finalizada não alerta.")

        linha("7) Editar uma proposta pelo caminho antigo mantém o vínculo com a venda")
        indice = int(bd.ler_propostas(caminho).index[bd.ler_propostas(caminho)["ID_PROPOSTA"] == id_p1][0])
        propostas_mod.atualizar_proposta(indice, {"OBSERVAÇÕES": "editada pela tela de sempre"})
        editada = bd.ler_propostas(caminho).loc[indice]
        assert editada["ID_PROPOSTA"] == id_p1 and editada["ID_VENDA"] == id_venda
        print("OK: atualizar_proposta preserva ID_PROPOSTA e ID_VENDA.")

        linha("8) Sincronização: as abas novas vão para a nuvem; nuvem sem elas não apaga as daqui")
        enviados = []
        original = sheets_sync.sincronizar_em_background
        sheets_sync.sincronizar_em_background = lambda aba, df: enviados.append(aba)
        try:
            v.mandar_a_outro_banco(id_v3, _pedido("Outro Banco Exemplo"))
            assert enviados == [bd.ABA_PROPOSTAS, bd.ABA_HISTORICO], enviados
            enviados.clear()
            v.mudar_status_venda(id_v3, v.VENDA_PERDIDA)
            assert enviados == [bd.ABA_VENDAS, bd.ABA_HISTORICO], enviados
            enviados.clear()
            sincronizacao.sincronizar_tudo_agora(caminho)
            assert {bd.ABA_VENDAS, bd.ABA_HISTORICO} <= set(enviados) and len(enviados) == 7, enviados
        finally:
            sheets_sync.sincronizar_em_background = original
        print("OK: cada gravação envia só as abas que mudaram; 'Sincronizar agora' envia as 7.")

        leitores = {n: getattr(nuvem, n) for n in ("ler_clientes", "ler_equipamentos", "ler_vendedores", "ler_propostas",
                                                     "ler_bancos", "ler_vendas", "ler_historico")}
        try:
            for nome, df in (("ler_clientes", bd.ler_clientes(caminho)), ("ler_equipamentos", bd.ler_equipamentos(caminho)),
                             ("ler_vendedores", bd.ler_vendedores(caminho)), ("ler_propostas", bd.ler_propostas(caminho))):
                setattr(nuvem, nome, lambda df=df: df.copy())

            def _sem_aba(nome):
                def _ler():
                    raise gspread.WorksheetNotFound(nome)
                return _ler

            for nome in ("ler_bancos", "ler_vendas", "ler_historico"):
                setattr(nuvem, nome, _sem_aba(nome))
            vendas_antes, hist_antes = bd.ler_vendas(caminho), bd.ler_historico(caminho)
            dados = sincronizacao._ler_dados_da_nuvem()
            assert set(dados) == {bd.ABA_CLIENTES, bd.ABA_EQUIPAMENTOS, bd.ABA_VENDEDORES, bd.ABA_PROPOSTAS}
            sincronizacao._recusar_se_a_nuvem_parece_vazia_por_engano(dados, caminho)
            sincronizacao._gravar_dados_no_arquivo(caminho, dados)
            assert bd.ler_vendas(caminho).equals(vendas_antes) and len(bd.ler_historico(caminho)) == len(hist_antes)
            assert (bd.ler_propostas(caminho)["ID_VENDA"] != "").sum() >= 6, "os vínculos das propostas vêm junto"
        finally:
            for nome, funcao in leitores.items():
                setattr(nuvem, nome, funcao)
        print("OK: nuvem de antes das vendas: baixa o resto e as vendas/histórico daqui ficam iguais.")

        linha("9) Só o Administrador grava")
        sessao_mod.encerrar()
        try:
            v.criar_venda(fx.CPF_MARIA, ["X"], _pedido("Banco Exemplo"))
            raise AssertionError("sem sessão não pode gravar")
        except sessao_mod.PermissaoNegada:
            pass
        print("OK: sem sessão de Administrador, criar venda é recusado.")
        linha("TUDO OK")
    finally:
        nuvem._obter_cliente, sheets_sync._obter_cliente = rede_original
        fx.restaurar_modulos()
        sessao_mod.encerrar()


if __name__ == "__main__":
    main()
