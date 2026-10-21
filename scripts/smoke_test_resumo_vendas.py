"""Testa o resumo para o WhatsApp (planos 1.5-A e 1.5-B, core/resumo_vendas.py):

- periodo(): semana (segunda a domingo), quinzena (1-15 / 16-fim) e mes, o atual e o anterior (virada de mes e de ano,
  fevereiro bissexto);
- quais vendas entram: criada no periodo OU com movimento nele (venda ou proposta), limites inclusivos, a linha
  "conversao" que nao conta; filtro por vendedor (sem diferenciar maiusculas) e "todos";
- o texto exato de um caso pequeno (cada bloco, a etapa, os dias, o motivo, telefone ausente, o bloco Pendencias) e de
  outros (venda sem banco, venda com 2 bancos aprovados) e o ajuste de 20/10: qual banco aparece (o fechado ja
  Assinado ou alem, cada um numa linha; senao so o mais adiantado);
- 1.5-B: Perdida e Não efetivada num bloco so ("Não efetivadas"); periodo de duas datas livres (e as sugestoes
  como atalho); escolher os blocos do texto; Pendencias = as pendencias abertas da venda (nao as observacoes);
  nenhuma observacao em resumo algum; sem emojis; um banco por linha;
- periodo sem vendas: aviso e sinal de "vazio"; texto_da_venda (os bancos tentados e so o status de cada um, sem datas
  nem "parada ha N dias", com as pendencias abertas);
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
VENDEDOR_A, VENDEDOR_B, VENDEDOR_C, VENDEDOR_D = "Vendedor Exemplo", "Vendedora Teste Dois", "Vendedor Tres", "Vendedor Quatro"
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
    vendedores_mod.adicionar_vendedor(VENDEDOR_D)

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
    v.adicionar_pendencia(venda_c, "Cliente vai trazer\n  o avalista")  # pendencia em qualquer etapa (aqui: Aprovado)

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
    v.adicionar_pendencia(venda_g, "Aguardando a obra")
    ja_resolvida = v.adicionar_pendencia(venda_g, "Comprovante de renda")
    v.resolver_pendencia(venda_g, ja_resolvida)  # resolvida: nao aparece
    v.adicionar_pendencia(venda_g, "Falta o contrato assinado")

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

    # Vendedor D: qual banco aparece (ajuste de 20/10)
    venda_p, (p_p1, p_p2, p_p3) = venda(
        "CLIENTE 14 ASSINADO E APROVADO", VENDEDOR_D, ["Laser Exemplo", "Mesa Exemplo"],
        [ped("Banco Alfa", 10000, 36, "Laser Exemplo"), ped("Banco Beta", 12000, 36, "Mesa Exemplo"), ped("Banco Gama", 9000)],
        date(2026, 10, 20), "11900000020")
    for id_proposta in (p_p1, p_p2):
        v.mudar_status_proposta(id_proposta, APROVADO)
        v.fechar_proposta(id_proposta)
    v.mudar_status_proposta(p_p1, ASSINADO)  # o fechado ja Assinado aparece; o outro (so Aprovado) e o Negado, nao
    v.mudar_status_proposta(p_p3, NEGADO)
    venda_q, (p_q1, p_q2) = venda(
        "CLIENTE 15 DOIS ASSINADOS", VENDEDOR_D, ["Laser Exemplo", "Mesa Exemplo"],
        [ped("Banco Alfa", 11000, 36, "Laser Exemplo"), ped("Banco Beta", 12000, 36, "Mesa Exemplo")],
        date(2026, 10, 20), "11900000021")
    for id_proposta in (p_q1, p_q2):
        v.mudar_status_proposta(id_proposta, APROVADO)
        v.fechar_proposta(id_proposta)
    v.mudar_status_proposta(p_q1, NOTA)
    v.mudar_status_proposta(p_q2, ASSINADO)
    venda_r, (p_r1, p_r2, p_r3) = venda(
        "CLIENTE 16 SO RESPONDERAM", VENDEDOR_D, ["Cadeira Exemplo"],
        [ped("Banco Alfa", 9000), ped("Banco Beta", 9500), ped("Banco Gama", 9800)], date(2026, 10, 20), "11900000022")
    v.mudar_status_proposta(p_r1, propostas_mod.STATUS_PRE_APROVADO)  # o mais adiantado (os outros: Em Análise e Negado)
    v.mudar_status_proposta(p_r3, NEGADO)
    venda_s, (p_s1, p_s2) = venda(
        "CLIENTE 17 NEGADO E APROVADO", VENDEDOR_D, ["Mesa Exemplo"],
        [ped("Banco Alfa", 8000), ped("Banco Beta", 8200)], date(2026, 10, 20), "11900000023")
    v.mudar_status_proposta(p_s1, NEGADO)
    v.mudar_status_proposta(p_s2, APROVADO)
    venda_t, _ = venda("CLIENTE 18 DE HOJE", VENDEDOR_D, ["Mesa Exemplo"], [ped("Banco Alfa", 7000)], date(2026, 10, 21),
                       "11900000024")

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
    assert ids(r.vendas_do_periodo(semana.inicio, semana.fim, VENDEDOR_D, HOJE)) == {venda_p, venda_q, venda_r, venda_s, venda_t}
    todos = r.vendas_do_periodo(semana.inicio, semana.fim, None, HOJE)
    assert len(todos) == 8 + 5 + 5 + 5, len(todos)
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
    texto_a = r.texto_whatsapp(resumo_a)
    _igual(texto_a, """\
*Resumo da semana — Vendedor Exemplo*
19/10 a 25/10/2026 · 8 vendas

*Efetivadas (2)*
• CLIENTE 01 EFETIVADA · (11) 90000-0001
  Laser Exemplo · Banco Omega R$ 30.000
• CLIENTE 07 PENDENTE · (11) 3333-4444
  Laser Exemplo · Banco Alfa R$ 40.000

*Aprovadas (2)*
• CLIENTE 02 DUAS · (11) 90000-0002
  Cadeira Exemplo + Laser Exemplo
  Banco Omega R$ 30.000: Efetivado
  Banco Alfa R$ 52.000: NF enviada
• CLIENTE 03 APROVADA · (21) 90000-0003
  Mesa Exemplo · Banco Alfa R$ 18.000: Aprovado

*Em análise (1)*
• CLIENTE 04 ANALISE · sem telefone
  Cadeira Exemplo · Banco Y R$ 25.000, há 3 dias

*Negadas (1)*
• CLIENTE 05 NEGADA · (11) 90000-0005
  Laser Exemplo · Banco Alfa e Banco Beta negaram

*Não efetivadas (2)*
• CLIENTE 06 PERDIDO · (11) 90000-0006
  Mesa Exemplo · Não efetivada: Desistiu
• CLIENTE 08 NAO EFETIVADA · (11) 90000-0008
  Mesa Exemplo · Não efetivada

*Pendências*
Aprovadas que ainda não assinaram:
• CLIENTE 03 APROVADA, Banco Alfa: parada há 9 dias
Pendências em aberto:
• CLIENTE 03 APROVADA: Cliente vai trazer o avalista
• CLIENTE 07 PENDENTE: Aguardando a obra
• CLIENTE 07 PENDENTE: Falta o contrato assinado""")
    # estruturado: cada venda em UM bloco so
    blocos = [resumo_a.efetivadas, resumo_a.aprovadas, resumo_a.em_analise, resumo_a.negadas, resumo_a.nao_efetivadas]
    todas_as_linhas = [x.id_venda for b in blocos for x in b]
    assert len(todas_as_linhas) == len(set(todas_as_linhas)) == resumo_a.total
    assert resumo_a.aprovadas_sem_assinar == (("CLIENTE 03 APROVADA", "Banco Alfa", 9),)
    assert resumo_a.blocos == r.BLOCOS == ("efetivadas", "aprovadas", "em_analise", "negadas", "nao_efetivadas", "pendencias")
    # nenhuma observacao em resumo algum (so no card), e nenhum emoji
    assert "biometria" not in texto_a and "Observações" not in texto_a and "Obs." not in texto_a
    for emoji in ("✅", "🟢", "⏳", "❌", "🚫", "⚠"):
        assert emoji not in texto_a, emoji
    assert not hasattr(resumo_a, "observacoes") and not hasattr(resumo_a, "perdidas")
    print("OK")

    linha("texto_whatsapp: Vendedor C (sem banco, banco negado + outro esperando, dois aprovados) e blocos vazios")
    _igual(r.texto_whatsapp(r.montar_resumo(semana, VENDEDOR_C, HOJE)), """\
*Resumo da semana — Vendedor Tres*
19/10 a 25/10/2026 · 5 vendas

*Aprovadas (2)*
• CLIENTE 11 DOIS APROVADOS · (11) 90000-0012
  Mesa Exemplo · Banco Beta R$ 12.000,50: Aprovado
• CLIENTE 12 FECHOU UM · (11) 90000-0014
  Mesa Exemplo · Banco Alfa R$ 10.000: Aprovado

*Em análise (2)*
• CLIENTE 09 SEM BANCO · sem telefone
  Mesa Exemplo · ainda sem pedido a nenhum banco
• CLIENTE 10 MISTA · (11) 90000-0011
  Laser Exemplo · Banco Beta R$ 20.000, há 1 dia

*Negadas (1)*
• CLIENTE 13 UM BANCO NEGOU · (11) 90000-0013
  Laser Exemplo · Banco Alfa negou

*Pendências*
Aprovadas que ainda não assinaram:
• CLIENTE 11 DOIS APROVADOS, Banco Alfa: parada há 6 dias
• CLIENTE 11 DOIS APROVADOS, Banco Beta: parada há 9 dias
• CLIENTE 12 FECHOU UM, Banco Alfa: parada há 2 dias""")
    # todos os vendedores, a venda singular e a semana passada (uma venda so)
    um_dia = r.Periodo(r.SEMANA, r.ATUAL, date(2026, 10, 19), date(2026, 10, 19))
    texto_um = r.texto_whatsapp(r.montar_resumo(um_dia, VENDEDOR_B, HOJE))
    assert texto_um.splitlines()[:2] == ["*Resumo da semana — Vendedora Teste Dois*", "19/10 a 19/10/2026 · 1 venda"], texto_um
    texto_todos = r.texto_whatsapp(r.montar_resumo(semana, None, HOJE))
    assert texto_todos.splitlines()[:2] == ["*Resumo da semana — Todos os vendedores*", "19/10 a 25/10/2026 · 23 vendas"], texto_todos
    assert "*Resumo da semana passada — Vendedora Teste Dois*" in r.texto_whatsapp(r.montar_resumo(passada, VENDEDOR_B, HOJE))
    assert "Pendências" not in texto_um, "sem pendencias, o bloco nao aparece"
    # negrito so nos titulos: asteriscos so no inicio das linhas de titulo
    for linha_t in texto_todos.splitlines():
        assert ("*" not in linha_t) or (linha_t.startswith("*") and linha_t.endswith("*") and linha_t.count("*") == 2), linha_t
    print("OK")

    linha("Qual banco aparece (ajuste de 20/10): o fechado ja Assinado ou alem; senao so o mais adiantado")
    _igual(r.texto_whatsapp(r.montar_resumo(semana, VENDEDOR_D, HOJE)), """\
*Resumo da semana — Vendedor Quatro*
19/10 a 25/10/2026 · 5 vendas

*Aprovadas (3)*
• CLIENTE 14 ASSINADO E APROVADO · (11) 90000-0020
  Laser Exemplo + Mesa Exemplo · Banco Alfa R$ 10.000: Assinado
• CLIENTE 15 DOIS ASSINADOS · (11) 90000-0021
  Laser Exemplo + Mesa Exemplo
  Banco Alfa R$ 11.000: NF enviada
  Banco Beta R$ 12.000: Assinado
• CLIENTE 17 NEGADO E APROVADO · (11) 90000-0023
  Mesa Exemplo · Banco Beta R$ 8.200: Aprovado

*Em análise (2)*
• CLIENTE 16 SO RESPONDERAM · (11) 90000-0022
  Cadeira Exemplo · Banco Alfa R$ 9.000: Pré-aprovado, há 1 dia
• CLIENTE 18 DE HOJE · (11) 90000-0024
  Mesa Exemplo · Banco Alfa R$ 7.000, desde hoje

*Pendências*
Aprovadas que ainda não assinaram:
• CLIENTE 14 ASSINADO E APROVADO, Banco Beta: parada há 1 dia
• CLIENTE 17 NEGADO E APROVADO, Banco Beta: parada há 1 dia""")
    # o "hoje" da chamada manda (nao o do relogio): os dias esperando contam dele
    amanha = r.texto_whatsapp(r.montar_resumo(semana, VENDEDOR_D, date(2026, 10, 22)))
    assert "Banco Alfa R$ 9.000: Pré-aprovado, há 2 dias" in amanha and "Banco Alfa R$ 7.000, há 1 dia" in amanha, amanha
    assert "• CLIENTE 17 NEGADO E APROVADO, Banco Beta: parada há 2 dias" in amanha
    resumo_d = r.montar_resumo(semana, VENDEDOR_D, HOJE)
    assert [x.id_venda for x in resumo_d.aprovadas] == [venda_p, venda_q, venda_s] and [x.id_venda for x in resumo_d.em_analise] == [venda_r, venda_t]
    # o banco fechado so Aprovado da venda 14 nao aparece na linha, mas TAMBEM conta como "ainda nao assinou"
    assert resumo_d.aprovadas_sem_assinar == (("CLIENTE 14 ASSINADO E APROVADO", "Banco Beta", 1),
                                              ("CLIENTE 17 NEGADO E APROVADO", "Banco Beta", 1))
    # o desempate do "mais adiantado" e o mais parado (nunca a ordem da lista) e Negado so quando TODOS negaram
    agora = pd.Timestamp(HOJE)

    def banco_(id_, nome, status, data, fechada=False):
        return v.PropostaNaVenda(id_, 0, nome, status, 1000.0, None, pd.Timestamp(data), "", fechada, None)

    def venda_com(*propostas, status=v.VENDA_AGUARDANDO):
        return v.ResumoDaVenda("V-x", "cpf", "Cli", "Vend", "Eq", status, "", (), None, None, "", tuple(propostas))

    novo, antigo = banco_("P-1", "Banco Alfa", APROVADO, "2026-10-15"), banco_("P-2", "Banco Zeta", APROVADO, "2026-10-12")
    for ordem in ((novo, antigo), (antigo, novo)):
        assert r._classificar(venda_com(*ordem), {}, agora) == (r.APROVADAS, ("Banco Zeta R$ 1.000: Aprovado",)), ordem
        assert r._aprovadas_sem_assinar(venda_com(*ordem), {}, agora) == (
            [("Banco Alfa", 6), ("Banco Zeta", 9)] if ordem[0] is novo else [("Banco Zeta", 9), ("Banco Alfa", 6)])
    fechado_novo = banco_("P-1", "Banco Alfa", APROVADO, "2026-10-15", fechada=True)
    assert r._classificar(venda_com(antigo, fechado_novo), {}, agora)[1] == ("Banco Alfa R$ 1.000: Aprovado",), "empate: o fechado"
    assert r._aprovadas_sem_assinar(venda_com(antigo, fechado_novo), {}, agora) == [("Banco Alfa", 6)], "com fechado, so os fechados"
    em_analise_velho = banco_("P-3", "Banco X", propostas_mod.STATUS_EM_ANALISE, "2026-10-01")
    assert r._classificar(venda_com(em_analise_velho, novo), {}, agora)[0] == r.APROVADAS
    # Negado so quando TODAS as propostas negaram; vazio ou desconhecido nao conta como negado
    negado_a, negado_b = banco_("P-4", "Banco A", NEGADO, "2026-10-15"), banco_("P-5", "Banco B", NEGADO, "2026-10-15")
    assert r._classificar(venda_com(negado_a, negado_b), {}, agora) == (r.NEGADAS, ("Banco A e Banco B negaram",))
    assert r._classificar(venda_com(negado_a), {}, agora) == (r.NEGADAS, ("Banco A negou",))
    sem_status = banco_("P-6", "Banco B", "", "2026-10-15")
    assert r._classificar(venda_com(negado_a, sem_status), {}, agora) == (r.EM_ANALISE, ("Banco B R$ 1.000",))
    esquisito = banco_("P-7", "Banco B", "Status Esquisito", "2026-10-15")
    assert r._classificar(venda_com(negado_a, esquisito), {}, agora) == (r.EM_ANALISE, ("Banco B R$ 1.000: Status Esquisito",))
    assert r._classificar(venda_com(negado_a, novo), {}, agora)[0] == r.APROVADAS
    # as aprovadas sem assinar: nenhuma numa venda ja resolvida
    for resolvida in (v.VENDA_EFETIVADA, v.VENDA_PERDIDA, v.VENDA_NAO_EFETIVADA):
        assert r._aprovadas_sem_assinar(venda_com(novo, status=resolvida), {}, agora) == []

    # as regras de "banco assinado ou alem", direto (dado de antes da 1.2 incluso)
    def banco(status, fechada):
        return v.PropostaNaVenda("P-x", 0, "Banco", status, None, None, None, "", fechada, None)

    for status in (ASSINADO, NOTA, EFETIVADO, "Nota fiscal enviada", "Garantia Assinada", "Nota Fiscal Anexada"):
        assert r._assinado_ou_alem(banco(status, True)), status
        assert not r._assinado_ou_alem(banco(status, False)), f"{status}: so um banco FECHADO conta"
    for status in (APROVADO, propostas_mod.STATUS_PRE_APROVADO, NEGADO, ""):
        assert not r._assinado_ou_alem(banco(status, True)), status
    # o bloco Pendencias so com pendencia de venda (nenhuma "aprovada sem assinar")
    so_da_venda = r.ResumoDoVendedor(semana, None, 1, (), (), (), (), (), com_pendencias=(("CLIENTE X", ("falta a obra", "falta o contrato")),))
    assert so_da_venda.tem_pendencias and not r.ResumoDoVendedor(semana, None, 1, (), (), (), (), ()).tem_pendencias
    assert r.texto_whatsapp(so_da_venda).endswith(
        "*Pendências*\nPendências em aberto:\n• CLIENTE X: falta a obra\n• CLIENTE X: falta o contrato")
    print("OK")

    linha("Perdida e Não efetivada: um bloco so; periodo de duas datas livres; escolher os blocos")
    assert [x.id_venda for x in resumo_a.nao_efetivadas] == [venda_f, venda_h]
    assert "Perdidas" not in texto_a and "Perdida:" not in texto_a
    # duas datas livres: as da semana (ou quinzena, ou mes) viram a sugestao; as outras, "livre"
    assert r.periodo_das_datas(date(2026, 10, 19), date(2026, 10, 25), HOJE) == r.periodo(r.SEMANA, r.ATUAL, HOJE)
    assert r.periodo_das_datas(date(2026, 10, 12), date(2026, 10, 18), HOJE) == r.periodo(r.SEMANA, r.ANTERIOR, HOJE)
    assert r.periodo_das_datas(date(2026, 10, 16), date(2026, 10, 31), HOJE) == r.periodo(r.QUINZENA, r.ATUAL, HOJE)
    assert r.periodo_das_datas(date(2026, 9, 1), date(2026, 9, 30), HOJE) == r.periodo(r.MES, r.ANTERIOR, HOJE)
    livre = r.periodo_das_datas(date(2026, 10, 20), date(2026, 10, 22), HOJE)
    assert livre.tipo == r.LIVRE and (livre.inicio, livre.fim) == (date(2026, 10, 20), date(2026, 10, 22))
    assert livre.do_periodo == "do período" and livre.no_periodo == "no período de 20/10 a 22/10/2026"
    assert "depois de terminar" in _recusa(r.periodo_das_datas, date(2026, 10, 25), date(2026, 10, 19), HOJE)
    texto_livre = r.texto_whatsapp(r.montar_resumo(livre, VENDEDOR_A, HOJE))
    assert texto_livre.splitlines()[:2] == ["*Resumo do período — Vendedor Exemplo*", "20/10 a 22/10/2026 · 7 vendas"], texto_livre
    sem_vendas = r.periodo_das_datas(date(2026, 1, 7), date(2026, 1, 9), HOJE)
    assert r.texto_whatsapp(r.montar_resumo(sem_vendas, VENDEDOR_A, HOJE)) == \
        "Nenhuma venda de Vendedor Exemplo no período de 07/01 a 09/01/2026"
    # um dia so (de = ate) vale
    assert r.montar_resumo(r.periodo_das_datas(date(2026, 10, 19), date(2026, 10, 19), HOJE), VENDEDOR_B, HOJE).total == 1
    # os blocos do texto: so os marcados
    so_efetivadas_e_pendencias = r.montar_resumo(semana, VENDEDOR_A, HOJE, blocos=[r.EFETIVADAS, r.PENDENCIAS])
    assert so_efetivadas_e_pendencias.total == 8 and so_efetivadas_e_pendencias.aprovadas == ()
    assert so_efetivadas_e_pendencias.blocos == (r.EFETIVADAS, r.PENDENCIAS)
    t = r.texto_whatsapp(so_efetivadas_e_pendencias)
    assert "*Efetivadas (2)*" in t and "*Pendências*" in t
    for fora in ("*Aprovadas", "*Em análise", "*Negadas", "*Não efetivadas"):
        assert fora not in t, fora
    # o mesmo pelo parametro do texto
    t2 = r.texto_whatsapp(resumo_a, blocos=[r.NEGADAS, r.NAO_EFETIVADAS])
    assert "*Negadas (1)*" in t2 and "*Não efetivadas (2)*" in t2 and "Efetivadas (2)" not in t2 and "Pendências" not in t2
    assert t2.splitlines()[:2] == texto_a.splitlines()[:2], "o titulo e a contagem de vendas ficam"
    sem_pendencias = r.texto_whatsapp(resumo_a, blocos=[b for b in r.BLOCOS if b != r.PENDENCIAS])
    assert "Pendências" not in sem_pendencias and "Aprovadas que ainda não assinaram" not in sem_pendencias
    assert r.montar_resumo(semana, VENDEDOR_A, HOJE, blocos=[r.EFETIVADAS]).com_pendencias == ()
    # nada marcado: recusa; bloco desconhecido: recusa; blocos marcados sem venda: avisa
    assert "pelo menos um bloco" in _recusa(r.texto_whatsapp, resumo_a, blocos=[])
    assert "pelo menos um bloco" in _recusa(r.texto_whatsapp, r.montar_resumo(semana, VENDEDOR_A, HOJE, blocos=[]))
    assert "Bloco desconhecido" in _recusa(r.montar_resumo, semana, VENDEDOR_A, HOJE, blocos=["observacoes"])
    assert "Bloco desconhecido" in _recusa(r.texto_whatsapp, resumo_a, blocos=["perdidas"])
    vazio_de_blocos = r.texto_whatsapp(r.montar_resumo(semana, VENDEDOR_B, HOJE, blocos=[r.NEGADAS]))
    assert vazio_de_blocos.endswith("\n\nNada nos blocos escolhidos neste período."), vazio_de_blocos
    print("OK")

    linha("periodo sem vendas: aviso e sinal de vazio")
    vazio_a = r.montar_resumo(r.periodo(r.SEMANA, r.ATUAL, date(2026, 1, 7)), VENDEDOR_A, HOJE)
    assert vazio_a.vazio and vazio_a.total == 0 and not vazio_a.tem_pendencias
    assert r.texto_whatsapp(vazio_a) == "Nenhuma venda de Vendedor Exemplo nesta semana"
    vazio_todos = r.montar_resumo(r.periodo(r.MES, r.ANTERIOR, date(2026, 1, 7)), None, HOJE)
    assert vazio_todos.vazio and r.texto_whatsapp(vazio_todos) == "Nenhuma venda no mês passado"
    print("OK")

    # -- o resumo de uma venda ----------------------------------------------------------------------------
    linha("texto_da_venda: so o status de cada banco, sem datas, sem 'parada', sem observacoes, com as pendencias abertas")
    _igual(r.texto_da_venda(venda_b, HOJE), """\
*Venda de CLIENTE 02 DUAS* · (11) 90000-0002
Cadeira Exemplo + Laser Exemplo · Vendedor Exemplo
Em andamento

Bancos tentados:
• Banco Omega R$ 30.000 (48x): Efetivado, seguiu com este
• Banco Alfa R$ 52.000 (36x): NF enviada, seguiu com este
• Banco Beta R$ 31.000 (36x): Negado
• Banco Y R$ 25.000 (24x): Em Análise""")
    _igual(r.texto_da_venda(venda_c, HOJE), """\
*Venda de CLIENTE 03 APROVADA* · (21) 90000-0003
Mesa Exemplo · Vendedor Exemplo
Aguardando bancos

Bancos tentados:
• Banco Alfa R$ 18.000 (36x): Aprovado

Pendências em aberto:
• Cliente vai trazer o avalista""")
    _igual(r.texto_da_venda(venda_i, HOJE), """\
*Venda de CLIENTE 09 SEM BANCO* · sem telefone
Mesa Exemplo · Vendedor Tres
Aguardando bancos

Bancos tentados:
Nenhum banco ainda.""")
    assert r.texto_da_venda(venda_f, HOJE).splitlines()[2] == "Perdida: Desistiu"
    assert r.texto_da_venda(venda_g, HOJE).splitlines()[2] == "Efetivada"
    assert r.texto_da_venda(venda_g, HOJE).splitlines()[-2:] == ["• Aguardando a obra", "• Falta o contrato assinado"], "uma por linha"
    assert "• Banco Gama R$ 7.000 (36x): Em Análise" in r.texto_da_venda(venda_l, HOJE).splitlines()
    for id_venda in (venda_a, venda_b, venda_c, venda_g, venda_k, venda_l):
        texto_v = r.texto_da_venda(id_venda, HOJE)
        assert "Desde" not in texto_v and "parada" not in texto_v and "há " not in texto_v and "desde" not in texto_v, texto_v
        assert "Obs." not in texto_v and "biometria" not in texto_v and "Observações" not in texto_v, texto_v
        assert not any(c.isdigit() and "/" in linha_v for linha_v in texto_v.splitlines() for c in linha_v), "sem datas"
        for emoji in ("✅", "🟢", "⏳", "❌", "🚫", "⚠"):
            assert emoji not in texto_v
    assert "Venda não encontrada" in _recusa(r.texto_da_venda, "V-nao-existe", HOJE)
    print("OK")

    linha("nada e gravado")
    assert hashlib.sha256(caminho.read_bytes()).hexdigest() == hash_antes, "o resumo mexeu na planilha"
    print("OK")
    print("\nTUDO OK")


if __name__ == "__main__":
    main()
