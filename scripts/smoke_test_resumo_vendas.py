"""Testa o resumo para o WhatsApp (plano 1.5-A, core/resumo_vendas.py):

- periodo(): semana (segunda a domingo), quinzena (1-15 / 16-fim) e mes, o atual e o anterior (virada de mes e de ano,
  fevereiro bissexto);
- quais vendas entram: criada no periodo OU com movimento nele (venda ou proposta), limites inclusivos, a linha
  "conversao" que nao conta; filtro por vendedor (sem diferenciar maiusculas) e "todos";
- o texto exato de um caso pequeno (cada bloco, a etapa, os dias, o motivo, telefone ausente, o bloco Pendencias) e de
  outros dois (venda sem banco, venda com 2 bancos aprovados);
- periodo sem vendas: aviso e sinal de "vazio"; texto_da_venda (os bancos tentados e o resultado de cada um);
- nada e gravado (a planilha fica identica).

Planilha 100% ficticia em pasta temporaria (scripts/fixture_ficticia.py), preferencias isoladas e o Google desligado.
As datas sao fixas (hoje = 21/10/2026, quarta; a semana e 19/10 a 25/10): o historico e reescrito com datas combinadas.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_resumo_vendas.py
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import openpyxl
import pandas as pd

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False
import fixture_ficticia as fx
from core import clientes as clientes_mod
from core import data_store as bd
from core import data_store_sheets as nuvem
from core import propostas as propostas_mod
from core import resumo_vendas as r
from core import sessao as sessao_mod
from core import sheets_sync
from core import vendas as v
from core import vendedores as vendedores_mod

ADMIN = sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador")
HOJE = date(2026, 10, 21)
VENDEDOR_A, VENDEDOR_B, VENDEDOR_C = "Vendedor Exemplo", "Vendedora Teste Dois", "Vendedor Tres"
APROVADO, ASSINADO, NOTA = propostas_mod.STATUS_APROVADO, propostas_mod.STATUS_ASSINADO, propostas_mod.STATUS_NOTA_ENVIADA
EFETIVADO, NEGADO = propostas_mod.STATUS_EFETIVADO, propostas_mod.STATUS_NEGADO


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def d(dia: int, hora: int = 12, minuto: int = 0, mes: int = 10) -> datetime:
    return datetime(2026, mes, dia, hora, minuto)


def _recusa(funcao, *args, **kwargs) -> str:
    try:
        funcao(*args, **kwargs)
    except r.ErroResumo as exc:
        return str(exc)
    raise AssertionError("deveria recusar")


def _igual(obtido: str, esperado: str) -> None:
    assert obtido == esperado, f"\n--- obtido ---\n{obtido}\n--- esperado ---\n{esperado}"


def testar_periodos() -> None:
    linha("periodo()")
    um = lambda tipo, qual, hoje: (r.periodo(tipo, qual, hoje).inicio, r.periodo(tipo, qual, hoje).fim)
    quarta = date(2026, 10, 21)
    assert um(r.SEMANA, r.ATUAL, quarta) == (date(2026, 10, 19), date(2026, 10, 25))
    assert um(r.SEMANA, r.ANTERIOR, quarta) == (date(2026, 10, 12), date(2026, 10, 18))
    assert um(r.SEMANA, r.ATUAL, date(2026, 10, 19)) == (date(2026, 10, 19), date(2026, 10, 25))  # a propria segunda
    assert um(r.SEMANA, r.ATUAL, date(2026, 10, 25)) == (date(2026, 10, 19), date(2026, 10, 25))  # o proprio domingo
    assert um(r.SEMANA, r.ANTERIOR, date(2026, 1, 5)) == (date(2025, 12, 29), date(2026, 1, 4))  # virada de ano
    assert um(r.QUINZENA, r.ATUAL, quarta) == (date(2026, 10, 16), date(2026, 10, 31))
    assert um(r.QUINZENA, r.ATUAL, date(2026, 10, 15)) == (date(2026, 10, 1), date(2026, 10, 15))
    assert um(r.QUINZENA, r.ATUAL, date(2026, 10, 16)) == (date(2026, 10, 16), date(2026, 10, 31))
    assert um(r.QUINZENA, r.ANTERIOR, quarta) == (date(2026, 10, 1), date(2026, 10, 15))
    assert um(r.QUINZENA, r.ANTERIOR, date(2026, 10, 10)) == (date(2026, 9, 16), date(2026, 9, 30))
    assert um(r.QUINZENA, r.ANTERIOR, date(2026, 1, 5)) == (date(2025, 12, 16), date(2025, 12, 31))
    assert um(r.QUINZENA, r.ATUAL, date(2024, 2, 20)) == (date(2024, 2, 16), date(2024, 2, 29))  # bissexto
    assert um(r.MES, r.ATUAL, quarta) == (date(2026, 10, 1), date(2026, 10, 31))
    assert um(r.MES, r.ANTERIOR, quarta) == (date(2026, 9, 1), date(2026, 9, 30))
    assert um(r.MES, r.ANTERIOR, date(2026, 3, 2)) == (date(2026, 2, 1), date(2026, 2, 28))
    assert um(r.MES, r.ANTERIOR, date(2024, 3, 5)) == (date(2024, 2, 1), date(2024, 2, 29))
    assert um(r.MES, r.ANTERIOR, date(2026, 1, 5)) == (date(2025, 12, 1), date(2025, 12, 31))
    assert r.periodo(r.SEMANA, r.ATUAL, quarta).datas == "19/10 a 25/10/2026"
    assert r.periodo(r.SEMANA, r.ANTERIOR, date(2026, 1, 5)).datas == "29/12/2025 a 04/01/2026"
    assert r.periodo(r.MES, r.ANTERIOR, quarta).do_periodo == "do mês passado"
    assert r.periodo(r.QUINZENA, r.ATUAL, quarta).no_periodo == "nesta quinzena"
    assert "semana, quinzena ou mes" in _recusa(r.periodo, "ano", r.ATUAL, quarta)
    assert "atual ou anterior" in _recusa(r.periodo, r.MES, "proximo", quarta)
    assert "depois de terminar" in _recusa(r.vendas_do_periodo, date(2026, 10, 25), date(2026, 10, 19))
    print("OK")


def main() -> None:
    def _sem_rede(*_a, **_k):
        raise AssertionError("o teste tentou acessar o Google de verdade")

    nuvem._obter_cliente = sheets_sync._obter_cliente = _sem_rede
    pasta = Path(tempfile.mkdtemp(prefix="_smoke_resumo_"))
    fx.isolar_preferencias(pasta)
    caminho = fx.criar(pasta)
    fx.apontar_modulos_para(caminho)
    sessao_mod.iniciar(ADMIN)
    vendedores_mod.adicionar_vendedor(VENDEDOR_C)

    testar_periodos()

    # -- a planilha de teste --------------------------------------------------------------------------
    criadas: dict[str, date] = {}  # ID_VENDA -> DATA_CRIACAO combinada
    quando: dict[str, datetime] = {}  # ID (venda ou proposta) -> QUANDO de todas as linhas dele no historico
    cpfs: dict[str, str] = {}
    contador = [0]

    def cliente(nome: str, vendedor: str, celular: str = "") -> str:
        contador[0] += 1
        cpf = fx.cpf_ficticio(700_000_000 + contador[0] * 7919)
        clientes_mod.adicionar_cliente({"CPF/CNPJ": cpf, "CLIENTE": nome, "TIPO": "Cliente", "VENDEDOR": vendedor,
                                        "CELULAR": celular})
        cpfs[nome] = cpf
        return cpf

    def venda(nome: str, vendedor: str, equipamentos: list[str], propostas: list[dict], criada: date,
              celular: str = "", em: datetime | None = None, nas_propostas: datetime | None = None):
        """Cria cliente e venda (uma proposta por dict) e combina as datas: `em` vale para a venda, `nas_propostas`
        para as propostas. Devolve (ID_VENDA, [ID_PROPOSTA])."""
        cpf = cliente(nome, vendedor, celular)
        dia = pd.Timestamp(criada)
        if propostas:
            id_venda, primeira = v.criar_venda(cpf, equipamentos, {**propostas[0], "DATA": dia})
            ids = [primeira] + [v.mandar_a_outro_banco(id_venda, {**p, "DATA": dia}) for p in propostas[1:]]
        else:
            id_venda, _ = v.criar_venda(cpf, equipamentos)
            ids = []
        criadas[id_venda] = criada
        quando[id_venda] = em or datetime(criada.year, criada.month, criada.day, 12)
        for id_proposta in ids:
            quando[id_proposta] = nas_propostas or quando[id_venda]
        return id_venda, ids

    def ped(banco: str, valor: float, meses: int = 36, equipamento: str | None = None) -> dict:
        return {"BANCO": banco, "VALOR (R$)": valor, "MESES": meses, **({"EQUIPAMENTO": equipamento} if equipamento else {})}

    # Vendedor A: um caso de cada bloco
    venda_a, (p_a,) = venda("CLIENTE 01 EFETIVADA", VENDEDOR_A, ["Laser Exemplo"], [ped("Banco Omega", 30000, 48)],
                              date(2026, 10, 20), "(11) 90000-0001")
    v.mudar_status_proposta(p_a, APROVADO)
    v.fechar_proposta(p_a)
    v.efetivar_proposta(p_a)

    venda_b, (p_omega, p_alfa, p_beta, p_y) = venda(
        "CLIENTE 02 DUAS", VENDEDOR_A, ["Cadeira Exemplo", "Laser Exemplo"],
        [ped("Banco Omega", 30000, 48, "Cadeira Exemplo"), ped("Banco Alfa", 52000, 36, "Laser Exemplo"),
         ped("Banco Beta", 31000, 36), ped("Banco Y", 25000, 24)],
        date(2026, 10, 10), "11900000002", em=d(20))
    for id_proposta in (p_omega, p_alfa):
        v.mudar_status_proposta(id_proposta, APROVADO)
        v.fechar_proposta(id_proposta)
    v.mudar_status_proposta(p_omega, EFETIVADO)
    v.mudar_status_proposta(p_alfa, NOTA)
    v.mudar_status_proposta(p_beta, NEGADO)
    quando.update({p_omega: d(17), p_alfa: d(12), p_beta: d(10), p_y: d(18)})

    venda_c, (p_c,) = venda("CLIENTE 03 APROVADA", VENDEDOR_A, ["Mesa Exemplo"], [ped("Banco Alfa", 18000)],
                              date(2026, 10, 10), "(21) 90000-0003", em=d(20), nas_propostas=d(12))
    v.mudar_status_proposta(p_c, APROVADO)
    v.editar_venda(venda_c, ["Mesa Exemplo"], "falta anexar a biometria\n  do avalista")

    venda_d, (p_d,) = venda("CLIENTE 04 ANALISE", VENDEDOR_A, ["Cadeira Exemplo"], [ped("Banco Y", 25000)],
                              date(2026, 10, 19), "", nas_propostas=d(18))

    venda_e, (p_e1, p_e2) = venda("CLIENTE 05 NEGADA", VENDEDOR_A, ["Laser Exemplo"],
                                 [ped("Banco Alfa", 20000), ped("Banco Beta", 21000)], date(2026, 10, 21), "11900000005")
    v.mudar_status_proposta(p_e1, NEGADO)
    v.mudar_status_proposta(p_e2, NEGADO)

    venda_f, _ = venda("CLIENTE 06 PERDIDO", VENDEDOR_A, ["Mesa Exemplo"], [ped("Banco Y", 9000)], date(2026, 10, 21), "11900000006")
    v.mudar_status_venda(venda_f, v.VENDA_PERDIDA, motivo="Desistiu")

    venda_h, _ = venda("CLIENTE 08 NAO EFETIVADA", VENDEDOR_A, ["Mesa Exemplo"], [ped("Banco Y", 9000)], date(2026, 10, 20), "11900000008")
    v.mudar_status_venda(venda_h, v.VENDA_NAO_EFETIVADA)

    venda_g, (p_g,) = venda("CLIENTE 07 PENDENTE", VENDEDOR_A, ["Laser Exemplo"], [ped("Banco Alfa", 40000)],
                              date(2026, 10, 5), "1133334444", em=d(20), nas_propostas=d(5))
    v.mudar_status_proposta(p_g, APROVADO)
    v.fechar_proposta(p_g)
    v.efetivar_proposta(p_g)
    v.marcar_pendente_entrega(venda_g, "Aguardando a obra")

    # Vendedora B: os limites do periodo (a semana e 19/10 a 25/10)
    def limite(nome, criada, em, nas_propostas=None):
        return venda(nome, VENDEDOR_B, ["Mesa Exemplo"], [ped("Banco Y", 5000)], criada, "11900000009", em=em,
                     nas_propostas=nas_propostas or em)

    l1, _ = limite("L1 MOVIMENTO NO ULTIMO DIA", date(2026, 10, 10), d(25, 23, 59))
    l2, _ = limite("L2 MOVIMENTO DEPOIS", date(2026, 10, 10), d(26, 0, 0))
    l3, _ = limite("L3 CRIADA NO ULTIMO DIA", date(2026, 10, 25), d(10))
    l4, _ = limite("L4 CRIADA DEPOIS", date(2026, 10, 26), d(26))
    l5, _ = limite("L5 CRIADA NO PRIMEIRO DIA", date(2026, 10, 19), d(10))
    l6, _ = limite("L6 ANTES", date(2026, 10, 18), d(18, 23, 59))
    l7, (p_l7,) = limite("L7 SO A PROPOSTA SE MEXEU", date(2026, 10, 10), d(10))
    quando[p_l7] = d(20)
    l8, (p_l8,) = limite("L8 SO CONVERSAO", date(2026, 10, 10), d(10))
    l9, _ = limite("L9 CONVERSAO E MOVIMENTO", date(2026, 10, 10), d(10))

    # Vendedor C: venda sem banco, com um banco negado e outro esperando, com dois bancos aprovados
    venda_i, _ = venda("CLIENTE 09 SEM BANCO", VENDEDOR_C, ["Mesa Exemplo"], [], date(2026, 10, 20))
    venda_j, (p_j1, p_j2) = venda("CLIENTE 10 MISTA", VENDEDOR_C, ["Laser Exemplo"],
                                [ped("Banco Alfa", 10000), ped("Banco Beta", 20000)], date(2026, 10, 20), "11900000011",
                                nas_propostas=d(20))
    v.mudar_status_proposta(p_j1, NEGADO)
    venda_k, (p_k1, p_k2) = venda("CLIENTE 11 DOIS APROVADOS", VENDEDOR_C, ["Mesa Exemplo"],
                               [ped("Banco Alfa", 10000), ped("Banco Beta", 12000.5)], date(2026, 10, 14), "11900000012",
                               em=d(20), nas_propostas=d(15))
    v.mudar_status_proposta(p_k1, APROVADO)
    v.mudar_status_proposta(p_k2, APROVADO)
    quando[p_k2] = d(12)
    venda_l, (p_l_alfa, p_l_beta, p_l_gama) = venda(
        "CLIENTE 12 FECHOU UM", VENDEDOR_C, ["Mesa Exemplo"],
        [ped("Banco Alfa", 10000), ped("Banco Beta", 11000), ped("Banco Gama", 7000)], date(2026, 10, 20), "11900000014")
    v.mudar_status_proposta(p_l_alfa, APROVADO)
    v.mudar_status_proposta(p_l_beta, APROVADO)
    v.fechar_proposta(p_l_alfa)
    quando.update({p_l_alfa: d(19), p_l_beta: d(10), p_l_gama: d(21)})
    venda_m, (p_m,) = venda("CLIENTE 13 UM BANCO NEGOU", VENDEDOR_C, ["Laser Exemplo"], [ped("Banco Alfa", 8000)],
                              date(2026, 10, 21), "11900000013")
    v.mudar_status_proposta(p_m, NEGADO)

    # datas combinadas: as linhas do historico de cada ID levam o QUANDO acima, e a venda leva a DATA_CRIACAO
    vendas_df = bd.ler_vendas(caminho)
    vendas_df["DATA_CRIACAO"] = [pd.Timestamp(criadas[i]) for i in vendas_df["ID_VENDA"]]
    bd.escrever_vendas_e_propostas(caminho, vendas=vendas_df)
    wb = openpyxl.load_workbook(caminho)
    ws = wb[bd.ABA_HISTORICO]
    for linha_h in ws.iter_rows(min_row=2):
        if linha_h[2].value in quando:
            linha_h[0].value = quando[linha_h[2].value]
    wb.save(caminho)
    wb.close()
    # a linha "conversao" (dos dados antigos) no periodo: nao conta como movimento
    for id_ in (l8, p_l8, l9):
        bd.escrever_vendas_e_propostas(caminho, historico_novo=[
            {"QUANDO": d(20), "TIPO": v.TIPO_CONVERSAO, "ID": id_, "DE": "x", "PARA": "y", "MOTIVO": "", "COMPUTADOR": "T"}])
    bd.escrever_vendas_e_propostas(caminho, historico_novo=[
        {"QUANDO": d(20), "TIPO": v.TIPO_VENDA, "ID": l9, "DE": "", "PARA": "", "MOTIVO": "", "COMPUTADOR": "T"}])

    hash_antes = hashlib.sha256(caminho.read_bytes()).hexdigest()
    semana = r.periodo(r.SEMANA, r.ATUAL, HOJE)

    # -- quais vendas entram ------------------------------------------------------------------------------
    linha("vendas_do_periodo: limites, movimento, conversao, vendedor")
    ids = lambda lista: {x.id for x in lista}
    assert ids(r.vendas_do_periodo(semana.inicio, semana.fim, VENDEDOR_B, HOJE)) == {l1, l3, l5, l7, l9}, \
        "B: entra criada no 1o/ultimo dia, movimento no ultimo dia (23:59), so a proposta, conversao + movimento"
    for fora, motivo in ((l2, "movimento 26/10 00:00"), (l4, "criada depois"), (l6, "criada e movimento antes (18/10 23:59)"),
                         (l8, "so a linha conversao no periodo")):
        assert fora not in ids(r.vendas_do_periodo(semana.inicio, semana.fim, None, HOJE)), motivo
    assert ids(r.vendas_do_periodo(semana.inicio, semana.fim, VENDEDOR_A, HOJE)) == {venda_a, venda_b, venda_c, venda_d, venda_e, venda_f, venda_h, venda_g}
    assert ids(r.vendas_do_periodo(semana.inicio, semana.fim, "vendedor EXEMPLO ", HOJE)) == ids(
        r.vendas_do_periodo(semana.inicio, semana.fim, VENDEDOR_A, HOJE)), "o vendedor nao diferencia maiusculas"
    assert ids(r.vendas_do_periodo(semana.inicio, semana.fim, VENDEDOR_C, HOJE)) == {venda_i, venda_j, venda_k, venda_l, venda_m}
    todos = r.vendas_do_periodo(semana.inicio, semana.fim, None, HOJE)
    assert len(todos) == 8 + 5 + 5, len(todos)
    assert ids(r.vendas_do_periodo(semana.inicio, semana.fim, "Ninguem", HOJE)) == set()
    # a semana passada (12 a 18/10): so o movimento de antes
    passada = r.periodo(r.SEMANA, r.ANTERIOR, HOJE)
    assert ids(r.vendas_do_periodo(passada.inicio, passada.fim, VENDEDOR_B, HOJE)) == {l6}
    assert {venda_b, venda_c, venda_k} <= ids(r.vendas_do_periodo(passada.inicio, passada.fim, None, HOJE)), \
        "o movimento nas propostas (12 a 18/10) puxa a venda"
    print("OK")

    # -- o texto exato --------------------------------------------------------------------------------------
    linha("texto_whatsapp: Vendedor A (um caso de cada bloco)")
    resumo_a = r.montar_resumo(semana, VENDEDOR_A, HOJE)
    assert resumo_a.total == 8 and not resumo_a.vazio
    _igual(r.texto_whatsapp(resumo_a), """\
*Resumo da semana — Vendedor Exemplo*
19/10 a 25/10/2026 · 8 vendas

*✅ Efetivadas (2)*
• CLIENTE 01 EFETIVADA · (11) 90000-0001
  Laser Exemplo · Banco Omega R$ 30.000
• CLIENTE 07 PENDENTE · (11) 3333-4444
  Laser Exemplo · Banco Alfa R$ 40.000

*🟢 Aprovadas (2)*
• CLIENTE 02 DUAS · (11) 90000-0002
  Cadeira Exemplo + Laser Exemplo
  Banco Omega R$ 30.000: Efetivado · Banco Alfa R$ 52.000: Nota fiscal enviada
• CLIENTE 03 APROVADA · (21) 90000-0003
  Mesa Exemplo · Banco Alfa R$ 18.000: Aprovado

*⏳ Em análise (1)*
• CLIENTE 04 ANALISE · sem telefone
  Cadeira Exemplo · Banco Y R$ 25.000, há 3 dias

*❌ Negadas (1)*
• CLIENTE 05 NEGADA · (11) 90000-0005
  Laser Exemplo · Banco Alfa e Banco Beta negaram

*🚫 Perdidas e não efetivadas (2)*
• CLIENTE 06 PERDIDO · (11) 90000-0006
  Mesa Exemplo · Perdida: Desistiu
• CLIENTE 08 NAO EFETIVADA · (11) 90000-0008
  Mesa Exemplo · Não efetivada

*⚠️ Pendências*
Aprovadas que ainda não assinaram:
• CLIENTE 03 APROVADA, parada há 9 dias
Pendentes de entrega:
• CLIENTE 07 PENDENTE: Aguardando a obra
Observações (o que falta):
• CLIENTE 03 APROVADA: falta anexar a biometria do avalista""")
    # estruturado: cada venda em UM bloco so
    blocos = [resumo_a.efetivadas, resumo_a.aprovadas, resumo_a.em_analise, resumo_a.negadas, resumo_a.perdidas]
    todas_as_linhas = [x.id_venda for b in blocos for x in b]
    assert len(todas_as_linhas) == len(set(todas_as_linhas)) == resumo_a.total
    assert resumo_a.aprovadas_sem_assinar == (("CLIENTE 03 APROVADA", 9),)
    print("OK")

    linha("texto_whatsapp: Vendedor C (sem banco, banco negado + outro esperando, dois aprovados) e blocos vazios")
    _igual(r.texto_whatsapp(r.montar_resumo(semana, VENDEDOR_C, HOJE)), """\
*Resumo da semana — Vendedor Tres*
19/10 a 25/10/2026 · 5 vendas

*🟢 Aprovadas (2)*
• CLIENTE 11 DOIS APROVADOS · (11) 90000-0012
  Mesa Exemplo
  Banco Alfa R$ 10.000: Aprovado · Banco Beta R$ 12.000,50: Aprovado
• CLIENTE 12 FECHOU UM · (11) 90000-0014
  Mesa Exemplo · Banco Alfa R$ 10.000: Aprovado

*⏳ Em análise (2)*
• CLIENTE 09 SEM BANCO · sem telefone
  Mesa Exemplo · ainda sem pedido a nenhum banco
• CLIENTE 10 MISTA · (11) 90000-0011
  Laser Exemplo · Banco Beta R$ 20.000, há 1 dia

*❌ Negadas (1)*
• CLIENTE 13 UM BANCO NEGOU · (11) 90000-0013
  Laser Exemplo · Banco Alfa negou

*⚠️ Pendências*
Aprovadas que ainda não assinaram:
• CLIENTE 11 DOIS APROVADOS, parada há 9 dias
• CLIENTE 12 FECHOU UM, parada há 2 dias""")
    # todos os vendedores, a venda singular e a semana passada (uma venda so)
    um_dia = r.Periodo(r.SEMANA, r.ATUAL, date(2026, 10, 19), date(2026, 10, 19))
    texto_um = r.texto_whatsapp(r.montar_resumo(um_dia, VENDEDOR_B, HOJE))
    assert texto_um.splitlines()[:2] == ["*Resumo da semana — Vendedora Teste Dois*", "19/10 a 19/10/2026 · 1 venda"], texto_um
    texto_todos = r.texto_whatsapp(r.montar_resumo(semana, None, HOJE))
    assert texto_todos.splitlines()[:2] == ["*Resumo da semana — Todos os vendedores*", "19/10 a 25/10/2026 · 18 vendas"], texto_todos
    assert "*Resumo da semana passada — Vendedora Teste Dois*" in r.texto_whatsapp(r.montar_resumo(passada, VENDEDOR_B, HOJE))
    assert "Pendências" not in texto_um, "sem pendencias, o bloco nao aparece"
    # negrito so nos titulos: asteriscos so no inicio das linhas de titulo
    for linha_t in texto_todos.splitlines():
        assert ("*" not in linha_t) or (linha_t.startswith("*") and linha_t.endswith("*") and linha_t.count("*") == 2), linha_t
    print("OK")

    linha("periodo sem vendas: aviso e sinal de vazio")
    vazio_a = r.montar_resumo(r.periodo(r.SEMANA, r.ATUAL, date(2026, 1, 7)), VENDEDOR_A, HOJE)
    assert vazio_a.vazio and vazio_a.total == 0 and not vazio_a.tem_pendencias
    assert r.texto_whatsapp(vazio_a) == "Nenhuma venda de Vendedor Exemplo nesta semana"
    vazio_todos = r.montar_resumo(r.periodo(r.MES, r.ANTERIOR, date(2026, 1, 7)), None, HOJE)
    assert vazio_todos.vazio and r.texto_whatsapp(vazio_todos) == "Nenhuma venda no mês passado"
    print("OK")

    # -- o resumo de uma venda ----------------------------------------------------------------------------
    linha("texto_da_venda")
    _igual(r.texto_da_venda(venda_b, HOJE), """\
*Venda de CLIENTE 02 DUAS* · (11) 90000-0002
Cadeira Exemplo + Laser Exemplo · Vendedor Exemplo
Desde 10/10/2026 · Em andamento

Bancos tentados:
• Banco Omega R$ 30.000 (48x): Aprovado, seguiu com este · Efetivado em 17/10
• Banco Alfa R$ 52.000 (36x): Aprovado, seguiu com este · Nota fiscal enviada, parada há 9 dias
• Banco Beta R$ 31.000 (36x): Negado
• Banco Y R$ 25.000 (24x): Em Análise há 3 dias""")
    _igual(r.texto_da_venda(venda_c, HOJE), """\
*Venda de CLIENTE 03 APROVADA* · (21) 90000-0003
Mesa Exemplo · Vendedor Exemplo
Desde 10/10/2026 · Aguardando bancos

Bancos tentados:
• Banco Alfa R$ 18.000 (36x): Aprovado

Obs.: falta anexar a biometria do avalista""")
    _igual(r.texto_da_venda(venda_i, HOJE), """\
*Venda de CLIENTE 09 SEM BANCO* · sem telefone
Mesa Exemplo · Vendedor Tres
Desde 20/10/2026 · Aguardando bancos

Bancos tentados:
Nenhum banco ainda.""")
    assert r.texto_da_venda(venda_f, HOJE).splitlines()[2] == "Desde 21/10/2026 · Perdida: Desistiu"
    assert r.texto_da_venda(venda_g, HOJE).splitlines()[2] == "Desde 05/10/2026 · Pendente de entrega: Aguardando a obra"
    assert "• Banco Gama R$ 7.000 (36x): Em Análise desde hoje" in r.texto_da_venda(venda_l, HOJE).splitlines()
    assert "Venda não encontrada" in _recusa(r.texto_da_venda, "V-nao-existe", HOJE)
    print("OK")

    linha("nada e gravado")
    assert hashlib.sha256(caminho.read_bytes()).hexdigest() == hash_antes, "o resumo mexeu na planilha"
    print("OK")
    print("\nTUDO OK")


if __name__ == "__main__":
    main()
