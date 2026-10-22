"""Testa as etapas de um banco fechado depois de Aprovado (plano 1.2-A, regra em core/; a pendencia e o smoke_test_pendencias):

- Aprovado -> Assinado -> NF enviada -> Efetivado (pode pular etapa; so num banco FECHADO), com a venda
  Efetivada so quando todos os bancos fechados efetivaram (dois bancos em etapas diferentes: Em andamento);
- desmarcar o fechamento so com o banco em Aprovado; o ↩ volta etapa por etapa;
- o Pendente de entrega saiu (pendencia em qualquer etapa nao trava nada);
- alertas de 7 dias em qualquer etapa (e a venda Em andamento sem alerta proprio); um limite so em todo o app;
- Assinado / NF enviada contam como Aprovado nas taxas e no funil; ida e volta com a nuvem simulada.

Planilha 100% ficticia em pasta temporaria (scripts/fixture_ficticia.py), preferencias isoladas e o Google desligado.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_etapas_pos_aprovacao.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False
import fixture_ficticia as fx
from core import dashboard as dashboard_mod
from core import data_store as bd
from core import data_store_sheets as nuvem
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import sheets_sync
from core import vendas as v

ADMIN = sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador")
ASSINADO, NOTA, EFETIVADO = propostas_mod.STATUS_ASSINADO, propostas_mod.STATUS_NOTA_ENVIADA, propostas_mod.STATUS_EFETIVADO
APROVADO = propostas_mod.STATUS_APROVADO


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
    pasta = Path(tempfile.mkdtemp(prefix="_smoke_etapas_"))
    fx.isolar_preferencias(pasta)
    caminho = fx.criar(pasta)
    fx.apontar_modulos_para(caminho)
    sessao_mod.iniciar(ADMIN)

    def venda_(id_venda):
        return bd.ler_vendas(caminho).set_index("ID_VENDA").loc[id_venda]

    def status_de(id_proposta):
        return bd.ler_propostas(caminho).set_index("ID_PROPOSTA").loc[id_proposta, "STATUS"]

    def resumo(id_venda):
        return next(r for r in v.listar_vendas() if r.id == id_venda)

    def forcar_status(id_proposta, status):
        """Grava um status direto na planilha, sem passar pelas regras: como um dado de antes da 1.2 (Garantia Assinada,
        Nota Fiscal Anexada, EFETIVADO em caixa alta...)."""
        propostas, _ = v._ler()
        propostas.loc[propostas["ID_PROPOSTA"] == id_proposta, "STATUS"] = status
        bd.escrever_vendas_e_propostas(caminho, propostas=propostas)

    def com_banco_fechado(cpf, equipamento, banco="Banco Exemplo"):
        """Uma venda de 1 equipamento com 1 banco ja fechado (Aprovado). Devolve (id_venda, id_proposta)."""
        id_venda, id_proposta = v.criar_venda(cpf, [equipamento], _pedido(banco, EQUIPAMENTO=equipamento))
        v.mudar_status_proposta(id_proposta, APROVADO)
        v.fechar_proposta(id_proposta)
        return id_venda, id_proposta

    try:
        linha("1) A ordem das etapas e as listas")
        assert (ASSINADO, NOTA) == ("Assinado", "NF enviada")
        assert v.ETAPAS_DO_FECHADO == [APROVADO, ASSINADO, NOTA, EFETIVADO], v.ETAPAS_DO_FECHADO
        assert v.STATUS_DE_FECHADA == v.ETAPAS_DO_FECHADO
        assert v.STATUS_DA_PROPOSTA == [propostas_mod.STATUS_EM_ANALISE, propostas_mod.STATUS_PRE_APROVADO, APROVADO,
                                        propostas_mod.STATUS_NEGADO], "a resposta do banco continua so com as 4"
        assert not set(v.ETAPAS_DEPOIS_DO_APROVADO) & set(v.STATUS_DA_PROPOSTA)
        assert not hasattr(v, "DIAS_PARA_ALERTA"), "o limite de dias e um so (propostas.DIAS_PROPOSTA_PARADA)"
        print("OK: Aprovado -> Assinado -> NF enviada -> Efetivado; a lista da resposta do banco segue com as 4.")

        linha("2) Um banco: Aprovado -> Assinado -> NF enviada -> Efetivado, e a venda vira Efetivada")
        id_v1, id_p1 = com_banco_fechado(fx.CPF_MARIA, "Cadeira Exemplo")
        assert venda_(id_v1)["STATUS"] == v.VENDA_EM_ANDAMENTO
        for etapa in (ASSINADO, NOTA):
            assert v.mudar_status_proposta(id_p1, etapa) is False
            assert status_de(id_p1) == etapa and venda_(id_v1)["STATUS"] == v.VENDA_EM_ANDAMENTO, etapa
        assert v.efetivar_proposta(id_p1) == v.VENDA_EFETIVADA
        assert venda_(id_v1)["STATUS"] == v.VENDA_EFETIVADA
        hist = bd.ler_historico(caminho)
        da_proposta = hist[(hist["ID"] == id_p1) & (hist["TIPO"] == v.TIPO_PROPOSTA)]
        assert list(da_proposta["PARA"]) == [propostas_mod.STATUS_EM_ANALISE, APROVADO, ASSINADO, NOTA, EFETIVADO]
        assert list(da_proposta["DE"])[1:] == [propostas_mod.STATUS_EM_ANALISE, APROVADO, ASSINADO, NOTA]
        assert list(hist[hist["ID"] == id_v1]["PARA"]) == [v.VENDA_AGUARDANDO, v.VENDA_EM_ANDAMENTO, v.VENDA_EFETIVADA]
        print("OK: cada troca vai pro histórico; a venda só fica Efetivada quando o banco efetiva.")

        # pular etapa e permitido (a lista da tela deixa escolher qualquer uma)
        id_v1b, id_p1b = com_banco_fechado(fx.CPF_MARIA, "Mesa Exemplo")
        v.mudar_status_proposta(id_p1b, NOTA)
        assert status_de(id_p1b) == NOTA
        v.mudar_status_proposta(id_p1b, EFETIVADO)
        assert venda_(id_v1b)["STATUS"] == v.VENDA_EFETIVADA
        print("OK: pode pular etapa (Aprovado -> NF enviada -> Efetivado).")

        linha("3) Dois bancos fechados em etapas diferentes: a venda fica Em andamento até os dois efetivarem")
        id_v2, id_a = v.criar_venda(fx.CPF_JOAO, ["Cadeira Exemplo", "Laser Exemplo"],
                                    _pedido("Banco Exemplo", EQUIPAMENTO="Cadeira Exemplo"))
        id_b = v.mandar_a_outro_banco(id_v2, _pedido("Outro Banco Exemplo", EQUIPAMENTO="Laser Exemplo"))
        for p in (id_a, id_b):
            v.mudar_status_proposta(p, APROVADO)
            v.fechar_proposta(p)
        v.mudar_status_proposta(id_a, ASSINADO)
        assert v.efetivar_proposta(id_b) == v.VENDA_EM_ANDAMENTO, "um efetivado e o outro Assinado"
        assert status_de(id_a) == ASSINADO and status_de(id_b) == EFETIVADO
        v.mudar_status_proposta(id_a, NOTA)
        assert venda_(id_v2)["STATUS"] == v.VENDA_EM_ANDAMENTO
        assert v.efetivar_proposta(id_a) == v.VENDA_EFETIVADA
        print("OK: um Efetivado e o outro em Assinado / NF enviada: Em andamento; os dois Efetivado: Efetivada.")

        linha("4) Só um banco FECHADO chega a Assinado, NF enviada ou Efetivado")
        id_v3, id_c = v.criar_venda(fx.CPF_ANA, ["Autoclave Exemplo"], _pedido("Banco Exemplo"))
        for etapa in (ASSINADO, NOTA, EFETIVADO):  # em análise
            _recusa("marcado como fechado", v.mudar_status_proposta, id_c, etapa)
            _recusa("marcado como fechado", v.editar_proposta, id_c, {"STATUS": etapa})
        v.mudar_status_proposta(id_c, APROVADO)
        for etapa in (ASSINADO, NOTA, EFETIVADO):  # aprovado, mas não fechado
            _recusa("marcado como fechado", v.mudar_status_proposta, id_c, etapa)
        assert status_de(id_c) == APROVADO
        _recusa("Status de proposta", v.criar_venda, fx.CPF_ANA, ["X"], _pedido("Banco Exemplo", STATUS=ASSINADO))
        _recusa("Status de proposta", v.mandar_a_outro_banco, id_v3, _pedido("Banco Exemplo", STATUS=NOTA))
        _recusa("Status de proposta", v.mudar_status_proposta, id_c, "Garantia Assinada")
        print("OK: banco não fechado (em análise ou só aprovado) recusa as 3 etapas; proposta nova não nasce nelas.")

        linha("5) Desmarcar o fechamento só com o banco em Aprovado; um fechado não muda a resposta")
        v.fechar_proposta(id_c)
        v.mudar_status_proposta(id_c, ASSINADO)
        _recusa("já está Assinado", v.desfazer_fechamento, id_c)
        _recusa("a setinha", v.desfazer_fechamento, id_c)
        _recusa("Desmarque o anel", v.mudar_status_proposta, id_c, propostas_mod.STATUS_NEGADO)
        _recusa("Desmarque o anel", v.mudar_status_proposta, id_c, propostas_mod.STATUS_EM_ANALISE)
        v.mudar_status_proposta(id_c, NOTA)
        _recusa("já está NF enviada", v.desfazer_fechamento, id_c)
        v.mudar_status_proposta(id_c, EFETIVADO)
        _recusa("já está Efetivado", v.desfazer_fechamento, id_c)
        assert v.fechadas_da_venda(venda_(id_v3)["BANCO_ESCOLHIDO"]) == [id_c]
        v.voltar_proposta(id_c)
        v.voltar_proposta(id_c)
        v.voltar_proposta(id_c)
        assert status_de(id_c) == APROVADO
        v.desfazer_fechamento(id_c)  # em Aprovado pode
        assert venda_(id_v3)["BANCO_ESCOLHIDO"] == "" and venda_(id_v3)["STATUS"] == v.VENDA_AGUARDANDO
        # status de antes da 1.2: so "Aprovado" (sem diferenciar maiusculas) desmarca; qualquer outro pede o ↩
        id_v3b, id_c2 = com_banco_fechado(fx.CPF_ANA, "Autoclave Exemplo 2")
        for antigo in ("Garantia Assinada", "Nota Fiscal Anexada", "EFETIVADO", "Pré-aprovado"):
            forcar_status(id_c2, antigo)
            _recusa(f"já está {antigo}", v.desfazer_fechamento, id_c2)
            _recusa("a setinha", v.desfazer_fechamento, id_c2)
            assert v.fechadas_da_venda(venda_(id_v3b)["BANCO_ESCOLHIDO"]) == [id_c2], antigo
        forcar_status(id_c2, "APROVADO")
        v.desfazer_fechamento(id_c2)
        assert venda_(id_v3b)["BANCO_ESCOLHIDO"] == ""
        print("OK: Assinado / NF enviada / Efetivado não desmarcam (a mensagem pede a setinha); em Aprovado desmarca; "
              "status antigos (Garantia Assinada, EFETIVADO...) também pedem a setinha, e APROVADO em caixa alta desmarca.")

        linha("6) O ↩ volta etapa por etapa")
        id_v4, id_d = com_banco_fechado(fx.CPF_MARIA, "Laser Exemplo")
        for etapa in (ASSINADO, NOTA, EFETIVADO):
            v.mudar_status_proposta(id_d, etapa)
        assert venda_(id_v4)["STATUS"] == v.VENDA_EFETIVADA
        for esperado_antes, esperado_depois in ((NOTA, v.VENDA_EM_ANDAMENTO), (ASSINADO, v.VENDA_EM_ANDAMENTO),
                                                (APROVADO, v.VENDA_EM_ANDAMENTO)):
            assert resumo(id_v4).propostas[0].anterior == esperado_antes, (esperado_antes, resumo(id_v4).propostas[0].anterior)
            v.voltar_proposta(id_d)
            assert status_de(id_d) == esperado_antes and venda_(id_v4)["STATUS"] == esperado_depois
        assert resumo(id_v4).propostas[0].anterior == propostas_mod.STATUS_EM_ANALISE, "antes de Aprovado: Em Análise"
        # depois de pular etapas, o ↩ volta ao de onde saiu
        v.mudar_status_proposta(id_d, EFETIVADO)
        assert resumo(id_v4).propostas[0].anterior == APROVADO
        v.voltar_proposta(id_d)
        assert status_de(id_d) == APROVADO
        print("OK: Efetivado ← NF enviada ← Assinado ← Aprovado, um passo de cada vez; a venda reabre; pulou, volta de onde saiu.")

        linha("7) O Pendente de entrega saiu: a pendência é uma etiqueta (ver smoke_test_pendencias.py)")
        id_v5, id_e = com_banco_fechado(fx.CPF_JOAO, "Cadeira Exemplo")
        id_extra = v.mandar_a_outro_banco(id_v5, _pedido("Banco Terceiro", EQUIPAMENTO="Laser Exemplo"))  # outro equipamento
        v.efetivar_proposta(id_e)
        assert venda_(id_v5)["STATUS"] == v.VENDA_EFETIVADA
        for saiu in ("VENDA_PENDENTE_ENTREGA", "marcar_pendente_entrega", "marcar_entregue", "_sair_de_pendente"):
            assert not hasattr(v, saiu), saiu
        assert v.STATUS_DA_VENDA == [v.VENDA_AGUARDANDO, v.VENDA_EM_ANDAMENTO, v.VENDA_EFETIVADA, v.VENDA_NAO_EFETIVADA,
                                     v.VENDA_PERDIDA]
        _recusa("vem dos bancos", v.mudar_status_venda, id_v5, "Pendente de entrega")
        # com uma pendência aberta nada trava (o que o Pendente travava)
        v.adicionar_pendencia(id_v5, "Obra do consultório atrasada")
        assert resumo(id_v5).status == v.VENDA_EFETIVADA and resumo(id_v5).pendencias_abertas == 1
        v.mandar_a_outro_banco(id_v5, _pedido("Banco Quarto"))
        v.mudar_status_proposta(id_extra, propostas_mod.STATUS_APROVADO)
        v.fechar_proposta(id_extra)
        assert venda_(id_v5)["STATUS"] == v.VENDA_EM_ANDAMENTO
        v.desfazer_fechamento(id_extra)
        v.mudar_status_proposta(id_e, ASSINADO)
        v.voltar_proposta(id_e)
        v.mudar_status_venda(id_v5, v.VENDA_NAO_EFETIVADA, motivo="Desistiu")
        assert v.voltar_venda(id_v5) in (v.VENDA_EFETIVADA, v.VENDA_EM_ANDAMENTO)
        print("OK: sem status Pendente de entrega; a pendência aberta não trava mandar a outro banco, fechar, mudar etapa nem desfecho.")

        linha("8) Alertas de 7 dias, em qualquer etapa")
        limite = propostas_mod.DIAS_PROPOSTA_PARADA
        assert limite == 7
        a_venda, a_prop = v.criar_venda(fx.CPF_ANA, ["Item A"], _pedido("Banco Alfa", EQUIPAMENTO="Item A"))  # em análise
        b_venda, b_prop = com_banco_fechado(fx.CPF_ANA, "Item B", "Banco Beta")  # Aprovado
        c_venda, c_prop = com_banco_fechado(fx.CPF_ANA, "Item C", "Banco Gama")
        v.mudar_status_proposta(c_prop, ASSINADO)
        d_venda, d_prop = com_banco_fechado(fx.CPF_ANA, "Item D", "Banco Delta")
        v.mudar_status_proposta(d_prop, NOTA)
        e_venda, e_prop = com_banco_fechado(fx.CPF_ANA, "Item E", "Banco Epsilon")
        v.efetivar_proposta(e_prop)
        f_venda, f_prop = com_banco_fechado(fx.CPF_ANA, "Item F", "Banco Zeta")
        v.efetivar_proposta(f_prop)
        v.adicionar_pendencia(f_venda, "Aguardando a obra")  # pendencia aberta: nunca alerta
        g_venda, g_efetivado = com_banco_fechado(fx.CPF_ANA, "Item G1", "Banco Eta")  # 2 bancos: um efetivado, outro em Nota
        v.efetivar_proposta(g_efetivado)
        g_nota = v.mandar_a_outro_banco(g_venda, _pedido("Banco Teta", EQUIPAMENTO="Item G2"))
        v.mudar_status_proposta(g_nota, APROVADO)
        v.fechar_proposta(g_nota)
        v.mudar_status_proposta(g_nota, NOTA)
        h_venda, h_prop = v.criar_venda(fx.CPF_ANA, ["Item H"], _pedido("Banco Iota", EQUIPAMENTO="Item H"))
        v.mudar_status_proposta(h_prop, APROVADO)  # aprovado mas nao fechado: o cliente ainda nao decidiu
        i_venda, i_prop = com_banco_fechado(fx.CPF_ANA, "Item I", "Banco Kappa")
        v.mudar_status_proposta(i_prop, ASSINADO)
        v.mudar_status_venda(i_venda, v.VENDA_PERDIDA)  # desistida: os bancos dela nao alertam
        # fechados com status de antes da 1.2 (a conversao e a 1.3): nenhuma venda andando fica sem aviso
        j_venda, j_prop = com_banco_fechado(fx.CPF_ANA, "Item J", "Banco Jota")
        forcar_status(j_prop, "Garantia Assinada")
        k_venda, k_prop = com_banco_fechado(fx.CPF_ANA, "Item K", "Banco Kilo")
        forcar_status(k_prop, "Nota Fiscal Anexada")
        l_venda, l_prop = com_banco_fechado(fx.CPF_ANA, "Item L", "Banco Lima")
        forcar_status(l_prop, "EFETIVADO")  # em caixa alta, conta como efetivado: nao alerta
        assert resumo(g_venda).status == v.VENDA_EM_ANDAMENTO and resumo(f_venda).status == v.VENDA_EFETIVADA

        def alertas_em(dias):
            return {(a.tipo, a.id): a for a in v.alertas(date.today() + timedelta(days=dias))}

        meus = {a_venda, a_prop, b_venda, b_prop, c_venda, c_prop, d_venda, d_prop, e_venda, e_prop, f_venda, f_prop,
                g_venda, g_efetivado, g_nota, h_venda, h_prop, i_venda, i_prop, j_venda, j_prop, k_venda, k_prop,
                l_venda, l_prop}
        em_6 = {k for k in alertas_em(limite - 1) if k[1] in meus}
        assert em_6 == set(), f"6 dias não alerta: {em_6}"
        em_7 = alertas_em(limite)
        em_7_meus = {k for k in em_7 if k[1] in meus}
        esperado = {
            (v.TIPO_PROPOSTA, a_prop), (v.TIPO_VENDA, a_venda),            # sem resposta + venda aguardando bancos
            (v.TIPO_PROPOSTA, b_prop), (v.TIPO_PROPOSTA, c_prop), (v.TIPO_PROPOSTA, d_prop),  # fechado parado
            (v.TIPO_PROPOSTA, j_prop), (v.TIPO_PROPOSTA, k_prop),           # fechado com status antigo
            (v.TIPO_PROPOSTA, g_nota),                                      # so o banco que falta
            (v.TIPO_VENDA, h_venda),                                        # aguardando bancos (aprovado, nao fechado)
        }
        assert em_7_meus == esperado, (em_7_meus ^ esperado)
        assert em_7[(v.TIPO_PROPOSTA, a_prop)].texto == f"Banco Alfa: sem resposta há {limite} dias"
        assert em_7[(v.TIPO_PROPOSTA, b_prop)].texto == f"Banco Beta: parado em Aprovado há {limite} dias"
        assert em_7[(v.TIPO_PROPOSTA, c_prop)].texto == f"Banco Gama: parado em Assinado há {limite} dias"
        assert em_7[(v.TIPO_PROPOSTA, d_prop)].texto == f"Banco Delta: parado em NF enviada há {limite} dias"
        assert em_7[(v.TIPO_PROPOSTA, j_prop)].texto == f"Banco Jota: parado em Garantia Assinada há {limite} dias"
        assert em_7[(v.TIPO_PROPOSTA, k_prop)].texto == f"Banco Kilo: parado em Nota Fiscal Anexada há {limite} dias"
        em_30 = alertas_em(30)
        assert em_30[(v.TIPO_PROPOSTA, j_prop)].dias == 30 and "Garantia Assinada há 30 dias" in em_30[(v.TIPO_PROPOSTA, j_prop)].texto
        assert (v.TIPO_PROPOSTA, l_prop) not in em_7 and (v.TIPO_PROPOSTA, l_prop) not in em_30, "EFETIVADO em caixa alta: efetivado"
        assert (v.TIPO_VENDA, f_venda) not in em_7 and (v.TIPO_PROPOSTA, f_prop) not in em_7, "pendência aberta não alerta"
        assert (v.TIPO_VENDA, f_venda) not in alertas_em(60), "nem 60 dias depois"
        assert em_7[(v.TIPO_VENDA, a_venda)].texto == f"parada em \"Aguardando bancos\" há {limite} dias"
        assert all(a.dias == limite for k, a in em_7.items() if k[1] in meus)
        for venda_em_andamento in (b_venda, c_venda, d_venda, g_venda):
            assert (v.TIPO_VENDA, venda_em_andamento) not in em_7, "Em andamento: os bancos avisam, a venda não duplica"
        assert (v.TIPO_PROPOSTA, e_prop) not in em_7 and (v.TIPO_PROPOSTA, g_efetivado) not in em_7, "Efetivado não para"
        assert (v.TIPO_PROPOSTA, i_prop) not in em_7 and (v.TIPO_VENDA, i_venda) not in em_7, "venda perdida não alerta"
        assert (v.TIPO_PROPOSTA, h_prop) not in em_7, "aprovado e não fechado: ninguém está esperando o banco"
        # mudar de etapa hoje zera a contagem daquele banco
        v.mudar_status_proposta(c_prop, NOTA)
        assert (v.TIPO_PROPOSTA, c_prop) not in alertas_em(0), "mudou hoje: zera a contagem"
        assert (v.TIPO_PROPOSTA, c_prop) in alertas_em(limite), "e volta a contar 7 dias depois"
        def venda_em(id_, dias):  # a venda como a tela a lê daqui a `dias` dias
            return next(r for r in v.listar_vendas(date.today() + timedelta(days=dias)) if r.id == id_)

        assert venda_em(a_venda, limite).parada and not venda_em(a_venda, limite - 1).parada
        assert not venda_em(f_venda, 60).parada, "venda com pendência aberta não fica 'parada' por causa dela"
        # um limite so: quem muda a constante muda os alertas, o cartao "Paradas" do Dashboard e os filtros dele
        antiga = fx.montar_propostas({"STATUS": propostas_mod.STATUS_EM_ANALISE, "DATA": pd.Timestamp(date.today() - timedelta(days=5))})
        filtro_paradas = dashboard_mod.FiltroDoDashboard(dashboard_mod.ATENCAO_PARADAS, "paradas")
        assert dashboard_mod.indices_do_filtro(antiga, filtro_paradas) == set(), "5 dias < 7"
        assert dashboard_mod.numeros_das_vendas([venda_em(a_venda, limite - 1)]).paradas == 0
        assert dashboard_mod.numeros_das_vendas([venda_em(a_venda, limite)]).paradas == 1, "o cartao Paradas do Dashboard usa o mesmo limite"
        try:
            propostas_mod.DIAS_PROPOSTA_PARADA = 3
            assert dashboard_mod.indices_do_filtro(antiga, filtro_paradas) == {0}, "o Dashboard lê a constante na hora, não copia no import"
            assert dashboard_mod.numeros_das_vendas([venda_em(a_venda, 3)]).dias_de_parada == 3, "o cartão Paradas também"
            assert propostas_mod.contar_paradas(antiga) == 1
        finally:
            propostas_mod.DIAS_PROPOSTA_PARADA = limite
        # (nada de copia do 7)
        original = propostas_mod.DIAS_PROPOSTA_PARADA
        try:
            propostas_mod.DIAS_PROPOSTA_PARADA = 3
            em_3 = alertas_em(3)
            assert {(v.TIPO_PROPOSTA, a_prop), (v.TIPO_PROPOSTA, b_prop), (v.TIPO_PROPOSTA, d_prop),
                    (v.TIPO_VENDA, a_venda)} <= set(em_3), "limite 3"
            assert not {k for k in alertas_em(2) if k[1] in meus}, "limite 3: 2 dias não alerta"
            assert venda_em(a_venda, 3).parada and not venda_em(a_venda, 2).parada, "o selo de 'parada' da venda lê o mesmo limite"
        finally:
            propostas_mod.DIAS_PROPOSTA_PARADA = original
        print("OK: cada etapa parada há 7 dias alerta (6 não); Em andamento não duplica; pendência não alerta; "
              "o limite vem de uma constante só.")

        linha("9) Assinado e NF enviada contam como Aprovado")
        for status in (ASSINADO, NOTA, "ASSINADO", "nf enviada", "Nota fiscal enviada", "NOTA FISCAL ENVIADA"):  # as duas grafias
            assert propostas_mod.etapa_status(status) == propostas_mod.ETAPA_APROVADO, status
            assert propostas_mod.categoria_status(status) == "Aprovado", status
            assert propostas_mod.eh_aprovado_nao_efetivado(status), status
            assert propostas_mod.esta_em_aberto(status), status
            assert not propostas_mod.eh_efetivado(status)
        assert propostas_mod.etapa_status(EFETIVADO) == propostas_mod.ETAPA_EFETIVADO
        assert propostas_mod.etapa_status("Garantia Assinada") == propostas_mod.ETAPA_GARANTIA_ASSINADA, "o antigo segue"
        assert propostas_mod.categoria_status("Assinada pelo cliente") == "Não identificado", "nada de chute"
        df = fx.montar_propostas({"STATUS": ASSINADO}, {"STATUS": NOTA}, {"STATUS": APROVADO}, {"STATUS": EFETIVADO},
                                 {"STATUS": propostas_mod.STATUS_NEGADO})
        totais = dashboard_mod.totais_gerais(df)
        assert totais["aprovadas"] == 4 and totais["nao_identificado"] == 0 and totais["negadas"] == 1
        assert totais["efetivadas"] == 1 and totais["aprovadas_nao_efetivadas"] == 3, totais
        assert propostas_mod.contar_paradas(fx.montar_propostas(
            {"STATUS": ASSINADO, "DATA": pd.Timestamp(date.today() - timedelta(days=30))},
            {"STATUS": EFETIVADO, "DATA": pd.Timestamp(date.today() - timedelta(days=30))})) == 1, "Efetivado encerra; Assinado não"
        print("OK: no funil, nas taxas e em 'aprovadas a efetivar' elas são Aprovado; só Efetivado encerra.")

        linha("10) Ida e volta com a nuvem simulada: nenhum status se perde")
        locais = {bd.ABA_PROPOSTAS: bd.ler_propostas(caminho), bd.ABA_VENDAS: bd.ler_vendas(caminho),
                  bd.ABA_HISTORICO: bd.ler_historico(caminho)}
        original_bruta = nuvem._ler_aba_bruta

        def _aba_da_nuvem(nome):  # o que o Google devolveria depois do envio: as linhas exatamente como foram mandadas
            linhas = sheets_sync._preparar_linhas(locais[nome])
            return pd.DataFrame(linhas[1:], columns=linhas[0]) if len(linhas) > 1 else pd.DataFrame()

        nuvem._ler_aba_bruta = _aba_da_nuvem
        try:
            da_nuvem = {bd.ABA_PROPOSTAS: nuvem.ler_propostas(), bd.ABA_VENDAS: nuvem.ler_vendas(),
                        bd.ABA_HISTORICO: nuvem.ler_historico()}
        finally:
            nuvem._ler_aba_bruta = original_bruta
        locais_p, nuvem_p = locais[bd.ABA_PROPOSTAS], da_nuvem[bd.ABA_PROPOSTAS]
        assert list(nuvem_p["STATUS"]) == list(locais_p["STATUS"]) and list(nuvem_p["ID_PROPOSTA"]) == list(locais_p["ID_PROPOSTA"])
        assert {ASSINADO, NOTA, EFETIVADO} <= set(nuvem_p["STATUS"]), "os status novos foram na ida"
        nuvem_v, locais_v = da_nuvem[bd.ABA_VENDAS], locais[bd.ABA_VENDAS]
        assert list(nuvem_v["STATUS"]) == list(locais_v["STATUS"]) and list(nuvem_v["PENDENCIAS"]) == list(locais_v["PENDENCIAS"])
        assert list(nuvem_v["MOTIVO"]) == list(locais_v["MOTIVO"]) and list(nuvem_v["BANCO_ESCOLHIDO"]) == list(locais_v["BANCO_ESCOLHIDO"])
        assert list(da_nuvem[bd.ABA_HISTORICO]["PARA"]) == list(locais[bd.ABA_HISTORICO]["PARA"])
        assert list(da_nuvem[bd.ABA_HISTORICO]["MOTIVO"]) == list(locais[bd.ABA_HISTORICO]["MOTIVO"])
        # a volta: gravar o que veio da nuvem no arquivo nao muda nada
        bd.escrever_tudo(caminho, bd.ler_clientes(caminho), bd.ler_equipamentos(caminho), bd.ler_vendedores(caminho),
                         nuvem_p, vendas=nuvem_v, historico=da_nuvem[bd.ABA_HISTORICO])
        assert list(bd.ler_propostas(caminho)["STATUS"]) == list(locais_p["STATUS"])
        assert list(bd.ler_vendas(caminho)["STATUS"]) == list(locais_v["STATUS"])
        assert sum(r.pendencias_abertas for r in v.listar_vendas()) == 2
        print("OK: os status novos e a pendência vão e voltam pela nuvem simulada.")

        linha("11) O que a tela das etapas le: proxima etapa, parada por banco e por venda, desde e datas das etapas")
        assert [v.indice_da_etapa(s) for s in (APROVADO, ASSINADO, NOTA, EFETIVADO)] == [0, 1, 2, 3]
        for escrito in ("Nota fiscal enviada", " nf ENVIADA ", "NOTA FISCAL ENVIADA", "nf  enviada"):
            assert v.indice_da_etapa(escrito) == 2, escrito  # o nome de antes e o novo, sem diferenciar maiusculas/espacos
        for nao_e_etapa in ("Em Análise", "Pré-aprovado", "Negado", "Garantia Assinada", "Nota Fiscal Anexada", "", None):
            assert v.indice_da_etapa(nao_e_etapa) is None and v.proxima_etapa(nao_e_etapa) is None, nao_e_etapa
        assert [v.proxima_etapa(s) for s in (APROVADO, ASSINADO, NOTA, EFETIVADO)] == [ASSINADO, NOTA, EFETIVADO, None]
        assert v.proxima_etapa("Nota fiscal enviada") == EFETIVADO, "uma etapa so: de NF enviada, Efetivado"

        class _Relogio(datetime):
            agora_combinado = datetime(2026, 1, 1)

            @classmethod
            def now(cls, tz=None):
                return cls.agora_combinado

        def _em(dias_atras: int) -> None:
            _Relogio.agora_combinado = datetime.combine(date.today() - timedelta(days=dias_atras), datetime.min.time()) \
                + timedelta(hours=9)

        datetime_original = v.datetime
        v.datetime = _Relogio
        try:
            _em(12)  # dois bancos fechados: um parado ha 12 dias em Aprovado, outro ha 9 em Assinado
            id_t, p_t1 = v.criar_venda(fx.CPF_MARIA, ["Item T1", "Item T2"], _pedido("Banco Alfa", EQUIPAMENTO="Item T1"))
            p_t2 = v.mandar_a_outro_banco(id_t, _pedido("Banco Beta", EQUIPAMENTO="Item T2"))
            for p in (p_t1, p_t2):
                v.mudar_status_proposta(p, APROVADO)
                v.fechar_proposta(p)
            _em(9)
            v.mudar_status_proposta(p_t2, ASSINADO)
            _em(6)  # um terceiro, fechado ha 6 dias: ainda nao esta parado
            id_u, p_u = com_banco_fechado(fx.CPF_JOAO, "Item U", "Banco Gama")
            _em(30)  # fechado e efetivado ha muito tempo: Efetivado nunca fica parado
            id_w, p_w = com_banco_fechado(fx.CPF_ANA, "Item W", "Banco Delta")
            v.efetivar_proposta(p_w)
        finally:
            v.datetime = datetime_original
        agora = date.today()
        r = resumo(id_t)
        b1, b2 = r.propostas
        assert (b1.dias_na_etapa, b2.dias_na_etapa) == (12, 9) and b1.parada and b2.parada
        assert b1.desde.date() == agora - timedelta(days=12) and b2.desde.date() == agora - timedelta(days=9)
        assert dict(b2.datas_das_etapas)[APROVADO].date() == agora - timedelta(days=12)
        assert dict(b2.datas_das_etapas)[ASSINADO].date() == agora - timedelta(days=9)
        assert r.dias_parada == 12 and r.parada and r.bancos_parados() == [b1, b2], "a maior parada, nao a menor"
        assert resumo(id_u).propostas[0].dias_na_etapa == 6 and not resumo(id_u).propostas[0].parada and not resumo(id_u).parada
        efetivada = resumo(id_w)
        assert efetivada.propostas[0].dias_na_etapa == 30 and not efetivada.propostas[0].parada and efetivada.dias_parada is None
        # exatamente 7 dias e parada; 6 nao (um limite so)
        for dias, esperado in ((limite - 1, False), (limite, True)):
            visto = next(x for x in v.listar_vendas(agora - timedelta(days=6) + timedelta(days=dias)) if x.id == id_u)
            assert visto.propostas[0].parada is esperado and visto.parada is esperado, dias
        # um banco que nao e o fechado nunca fica parado (nem com dias na etapa)
        solto = v.PropostaNaVenda("P-x", 0, "Banco", APROVADO, None, None, None, "", False, None, dias_na_etapa=40)
        assert not solto.parada
        # venda desistida/perdida: os bancos dela nao alertam (nem selo)
        v.mudar_status_venda(id_t, v.VENDA_PERDIDA, motivo="Desistiu")
        perdida = resumo(id_t)
        assert perdida.bancos_parados() == [] and perdida.dias_parada is None and not perdida.parada
        v.reabrir_venda(id_t)
        # Aguardando bancos: a propria venda
        _em(10)
        v.datetime = _Relogio
        try:
            id_x, _ = v.criar_venda(fx.CPF_ANA, ["Item X"])
        finally:
            v.datetime = datetime_original
        assert resumo(id_x).dias_parada == 10 and resumo(id_x).parada
        print("OK: proxima etapa e indice (nome antigo incluso); parada por banco (7 dias, só fechado, nunca Efetivado) e "
              "por venda (a maior; perdida não); desde e a data de cada etapa.")

        linha("TUDO OK")
    finally:
        nuvem._obter_cliente, sheets_sync._obter_cliente = rede_original
        fx.restaurar_modulos()
        sessao_mod.encerrar()


if __name__ == "__main__":
    main()
