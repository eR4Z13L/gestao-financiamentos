"""Testa que as propostas de uma venda já RESOLVIDA (Efetivada, Não efetivada, Perdida) saem de
"Precisa de atenção" (paradas, a efetivar), de "A efetivar" (cartão, por vendedor, topo) e do selo da barra lateral
(contar_paradas), e que o aviso "Cliente já efetivou em outro banco" não vale para proposta que está numa venda (a venda
já resolve isso). Proposta sem venda continua como sempre; sem a coluna VENDA_RESOLVIDA (VENDEDOR, tabelas de teste)
nada muda.

Planilha 100% fictícia em pasta temporária; o Google fica desligado e qualquer acesso a ele derruba o teste.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_dashboard_vendas_resolvidas.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False
import fixture_ficticia as fx
from core import bancos as bancos_mod
from core import dashboard as dash
from core import data_store as bd
from core import data_store_sheets as nuvem
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import sheets_sync
from core import vendas as v

HOJE = date.today()
ANTIGA = pd.Timestamp(HOJE - timedelta(days=20))  # bem alem dos 7 dias de "parada"


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def indices(df: pd.DataFrame, *ids: str) -> set[int]:
    return {int(i) for i in df.index[df["ID_PROPOSTA"].isin(ids)]}


def main() -> None:
    def _sem_rede(*_a, **_k):
        raise AssertionError("o teste tentou acessar o Google de verdade")

    rede_original = (nuvem._obter_cliente, sheets_sync._obter_cliente)
    nuvem._obter_cliente = sheets_sync._obter_cliente = _sem_rede
    pasta = Path(tempfile.mkdtemp(prefix="_smoke_dashboard_resolvidas_"))
    caminho = fx.criar(pasta)
    fx.apontar_modulos_para(caminho)
    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
    try:
        b1, b2 = bancos_mod.nomes_ativos()[:2]

        def pedido(banco, status="Em Análise", equipamento=None):
            campos = {"BANCO": banco, "VALOR (R$)": 5000, "MESES": 12, "DATA": ANTIGA, "STATUS": status}
            if equipamento:
                campos["EQUIPAMENTO"] = equipamento
            return campos

        # VE: Efetivada (banco 1 efetivou); o banco 2 ficou "Aprovado" (mesmo equipamento: o aviso "ja efetivou em outro banco")
        ve, pe1 = v.criar_venda(fx.CPF_MARIA, ["Torno E"], pedido(b1, equipamento="Torno E"))
        pe2 = v.mandar_a_outro_banco(ve, pedido(b2, "Aprovado", "Torno E"))
        v.mudar_status_proposta(pe1, "Aprovado")
        v.fechar_proposta(pe1)
        v.efetivar_proposta(pe1)
        # VN: Não efetivada
        vn, pn = v.criar_venda(fx.CPF_MARIA, ["Torno N"], pedido(b1, "Aprovado", "Torno N"))
        v.mudar_status_venda(vn, v.VENDA_NAO_EFETIVADA, motivo="Desistiu")
        # VP: Perdida
        vp, pp = v.criar_venda(fx.CPF_JOAO, ["Torno P"], pedido(b1, equipamento="Torno P"))
        v.mudar_status_venda(vp, v.VENDA_PERDIDA, motivo="Outro")
        # VD: Efetivada com uma pendencia aberta (falta entregar); o segundo banco ficou Aprovado
        vd, pd1 = v.criar_venda(fx.CPF_JOAO, ["Torno D"], pedido(b1, equipamento="Torno D"))
        pd2 = v.mandar_a_outro_banco(vd, pedido(b2, "Aprovado", "Torno D"))
        v.mudar_status_proposta(pd1, "Aprovado")
        v.fechar_proposta(pd1)
        v.efetivar_proposta(pd1)
        v.adicionar_pendencia(vd, "Equipamento ainda na fábrica")
        # VA: venda ainda aberta (Aguardando bancos): continua contando
        va, pa1 = v.criar_venda(fx.CPF_ANA, ["Torno A"], pedido(b1, "Aprovado", "Torno A"))
        pa2 = v.mandar_a_outro_banco(va, pedido(b2, "Em Análise", "Torno A"))
        # sem venda (como sempre): uma Efetivada e outra em aberto do mesmo cliente+equipamento; e uma Aprovado parada
        propostas_mod.adicionar_proposta({"CPF": fx.CPF_ANA, "DATA": ANTIGA, "VALOR (R$)": 100, "MESES": 12, "EQUIPAMENTO": "Torno S",
                                          "BANCO": b1, "STATUS": "Efetivado"})
        propostas_mod.adicionar_proposta({"CPF": fx.CPF_ANA, "DATA": ANTIGA, "VALOR (R$)": 100, "MESES": 12, "EQUIPAMENTO": "Torno S",
                                          "BANCO": b2, "STATUS": "Em Análise"})
        propostas_mod.adicionar_proposta({"CPF": fx.CPF_ANA, "DATA": ANTIGA, "VALOR (R$)": 100, "MESES": 12, "EQUIPAMENTO": "Torno T",
                                          "BANCO": b1, "STATUS": "Aprovado"})

        linha("1) A coluna: marca as propostas de venda resolvida (e só elas)")
        df = propostas_mod.listar_propostas()
        resolvidas = indices(df, pe1, pe2, pn, pp, pd1, pd2)
        abertas = indices(df, pa1, pa2)
        assert propostas_mod.COLUNA_VENDA_RESOLVIDA in df.columns
        assert {int(i) for i in df.index[df[propostas_mod.COLUNA_VENDA_RESOLVIDA]]} == resolvidas
        assert not propostas_mod.fora_do_fluxo(df).loc[list(abertas)].any()
        sem_coluna = df.drop(columns=[propostas_mod.COLUNA_VENDA_RESOLVIDA])
        assert not propostas_mod.fora_do_fluxo(sem_coluna).any(), "sem a coluna nada sai (VENDEDOR, tabelas de teste)"
        print("OK: Efetivada (com ou sem pendência), Não efetivada e Perdida marcam as propostas delas; venda aberta e proposta "
              "sem venda não.")

        linha("2) 'Precisa de atenção': paradas e a efetivar")
        itens = {i.chave: set(i.indices) for i in dash.precisa_de_atencao(df, hoje=HOJE)}
        itens_antigos = {i.chave: set(i.indices) for i in dash.precisa_de_atencao(sem_coluna, hoje=HOJE)}
        em_aberto_resolvidas = indices(df, pe2, pn, pp, pd2)  # Aprovado / Em Análise dentro de venda resolvida
        assert em_aberto_resolvidas <= itens_antigos[dash.ATENCAO_PARADAS], "sem a coluna elas contariam (o teste vale)"
        assert not itens[dash.ATENCAO_PARADAS] & resolvidas, "paradas: nenhuma de venda resolvida"
        assert abertas <= itens[dash.ATENCAO_PARADAS], "as da venda aberta continuam paradas"
        assert not itens[dash.ATENCAO_A_EFETIVAR] & resolvidas and indices(df, pa1) <= itens[dash.ATENCAO_A_EFETIVAR]
        sem_venda_parada = {int(i) for i in df.index[(df["ID_VENDA"] == "") & df["STATUS"].isin(["Aprovado", "Em Análise"])
                                                     & (pd.to_datetime(df["DATA"]) == ANTIGA)]}
        assert sem_venda_parada and sem_venda_parada <= itens[dash.ATENCAO_PARADAS], "sem venda continua como hoje"
        print("OK: as propostas de venda resolvida saem de 'em aberto há mais de 7 dias' e de 'aprovadas sem efetivar'; as de venda "
              "aberta e as sem venda ficam.")

        linha("3) O selo da barra lateral (contar_paradas) e o filtro do dashboard")
        paradas = propostas_mod.contar_paradas(df)
        assert paradas == len(itens[dash.ATENCAO_PARADAS]) == len(itens_antigos[dash.ATENCAO_PARADAS]) - len(em_aberto_resolvidas)
        assert propostas_mod.contar_paradas(sem_coluna) == len(itens_antigos[dash.ATENCAO_PARADAS])
        filtro = dash.FiltroDoDashboard(dash.ATENCAO_PARADAS, "Em aberto há mais de 7 dias")
        assert dash.indices_do_filtro(df, filtro, HOJE) == itens[dash.ATENCAO_PARADAS], "o filtro de Todas as Propostas = o da lista"
        print(f"OK: selo = {paradas} (sem as de venda resolvida), igual à lista 'Precisa de atenção' e ao filtro.")

        linha("4) 'A efetivar': cartão, por vendedor e topo")
        aprovadas_pendentes = int(((df["STATUS"].map(propostas_mod.etapa_status) == propostas_mod.ETAPA_APROVADO)
                                   & ~propostas_mod.fora_do_fluxo(df)).sum())
        antigo = int((sem_coluna["STATUS"].map(propostas_mod.etapa_status) == propostas_mod.ETAPA_APROVADO).sum())
        assert antigo - aprovadas_pendentes == len(indices(df, pe2, pn, pd2)), "o teste precisa de Aprovado em venda resolvida"
        assert dash.totais_gerais(df)["aprovadas_nao_efetivadas"] == aprovadas_pendentes
        assert dash.totais_gerais(sem_coluna)["aprovadas_nao_efetivadas"] == antigo
        assert dash.indicadores_do_topo(df)["a_efetivar"]["quantidade"] == aprovadas_pendentes
        assert int(dash.por_vendedor(df)["Não Efetivadas"].sum()) == aprovadas_pendentes
        assert int(dash.por_vendedor(sem_coluna)["Não Efetivadas"].sum()) == antigo
        efetivadas = dash.totais_gerais(df)["efetivadas"]
        assert efetivadas == dash.totais_gerais(sem_coluna)["efetivadas"], "as Efetivadas continuam contando (taxa de efetivação)"
        print(f"OK: {aprovadas_pendentes} a efetivar (eram {antigo}) no cartão, no topo e na tabela por vendedor; efetivadas iguais.")

        linha("5) 'Cliente já efetivou em outro banco' só vale para proposta sem venda")
        mesma = itens.get(dash.ATENCAO_MESMA_VENDA, set())
        i_pe1, i_pe2 = next(iter(indices(df, pe1))), next(iter(indices(df, pe2)))
        assert df.loc[i_pe2, "STATUS"] == "Aprovado" and df.loc[i_pe1, "STATUS"] == "Efetivado"
        assert df.loc[i_pe1, "EQUIPAMENTO"] == df.loc[i_pe2, "EQUIPAMENTO"] and df.loc[i_pe1, "CPF"] == df.loc[i_pe2, "CPF"],             "o teste precisa de um banco efetivado e outro em aberto do mesmo cliente+equipamento, na mesma venda"
        assert not mesma & indices(df, pe2, pd2, pa2), "numa venda, quem resolve isso é a venda"
        sem_venda_em_aberto = {int(i) for i in df.index[(df["EQUIPAMENTO"] == "Torno S") & (df["STATUS"] == "Em Análise")]}
        assert sem_venda_em_aberto and sem_venda_em_aberto <= mesma, "sem venda continua como hoje"
        print("OK: o aviso fica só nas propostas sem venda.")

        linha("TUDO OK")
    finally:
        nuvem._obter_cliente, sheets_sync._obter_cliente = rede_original
        fx.restaurar_modulos()
        sessao_mod.encerrar()
        shutil.rmtree(pasta, ignore_errors=True)


if __name__ == "__main__":
    main()
