"""Testa as dúvidas e as garantias do conversor dos dados antigos que o primeiro teste (smoke_test_converter_legado.py)
não cobre (plano 1.3, revisão): propostas órfãs, venda com status de antes, "Não efetivado" numa venda que já existia,
resposta de banco fechado a um status desconhecido, o relógio do histórico (alertas e dias iguais antes e depois, o ↩
que ignora a conversão) e qualquer erro depois do backup (restaura e diz o nome do backup).

Planilha 100% fictícia em pasta temporária; o Google fica desligado e qualquer acesso a ele derruba o teste.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_converter_legado_duvidas.py
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
from core import backup as backup_mod
from core import data_store as bd
from core import data_store_sheets as nuvem
from core import migracao_legado as leg
from core import sheets_sync
from core import vendas as v
from smoke_test_converter_legado import esperar_erro, linha, sha

HOJE = date.today()
M, J, A = fx.CPF_MARIA, fx.CPF_JOAO, fx.CPF_ANA


def d(dias_atras: int) -> pd.Timestamp:
    return pd.Timestamp(HOJE - timedelta(days=dias_atras))


def _p(cpf, dias_atras, equip, banco, status, id_proposta="", id_venda="") -> dict:
    return {"DATA": d(dias_atras), "CPF": cpf, "VALOR (R$)": 1000 + dias_atras, "MESES": 12, "EQUIPAMENTO": equip,
            "BANCO": banco, "STATUS": status, "OBSERVAÇÕES": "", "ID_PROPOSTA": id_proposta, "ID_VENDA": id_venda,
            "CARÊNCIA (DIAS)": None, "PARCELA (R$)": None}


def _v(id_venda, cpf, equip, status, fechadas="", criada=30, motivo="") -> dict:
    return {"ID_VENDA": id_venda, "CPF": cpf, "EQUIPAMENTOS": equip, "STATUS": status, "BANCO_ESCOLHIDO": fechadas,
            "MOTIVO": motivo, "DATA_CRIACAO": d(criada), "OBSERVAÇÕES": ""}


def _h(quando_dias_atras, tipo, id_, de, para) -> dict:
    return {"QUANDO": d(quando_dias_atras), "TIPO": tipo, "ID": id_, "DE": de, "PARA": para, "MOTIVO": "", "COMPUTADOR": "teste"}


PROPOSTAS = [
    # Maria, venda V-A ja existente (com historico): o relogio de cada proposta nao pode mudar
    _p(M, 30, "Cadeira A", "Banco A", "Em Análise", "P-A1", "V-A"),  # 0: historico a 12 dias
    _p(M, 30, "Cadeira A", "Banco B", "EM ANALISE", "P-A2", "V-A"),  # 1: sem historico (conta da DATA)
    _p(M, 40, "Cadeira A", "Banco C", "Garantia Assinada", "P-A3", "V-A"),  # 2: banco fechado, historico a 20 dias
    # orfas: ID_VENDA de venda que nao existe
    _p(M, 10, "Tomografo A", "Banco A", "Em Análise", "P-O1", "V-SUMIU"),  # 3
    _p(M, 10, "Tomografo A", "Banco B", "Aprovado"),  # 4 (sem venda, junto da 3 se a resposta for juntar)
    _p(J, 8, "Torno B", "Banco A", "Em Análise", "P-O2", "V-SUMIU2"),  # 5
    _p(J, 8, "Torno B", "Banco B", "Negado"),  # 6
    # vendas com status de antes
    _p(J, 60, "Fresa C", "Banco A", "Efetivado", "P-W1", "V-OLD1"),  # 7: venda "Nota fiscal", banco fechado = P-W1
    _p(J, 50, "Fresa D", "Banco A", "Em Análise", "P-W2", "V-OLD2"),  # 8: venda "Banco escolhido", nenhum banco fechado
    # Nao efetivado em venda que ja existia
    _p(A, 70, "Laser N", "Banco A", "Não efetivado", "P-N1", "V-NE1"),  # 9
    _p(A, 71, "Laser M", "Banco A", "Não efetivado", "P-N2", "V-NE2"),  # 10
    _p(A, 72, "Laser K", "Banco A", "Não efetivado", "P-N3", "V-NE3"),  # 11: a venda ja esta Nao efetivada: sem duvida
    # status desconhecido respondido com status de banco fechado
    _p(A, 90, "Mesa U", "Banco A", "Pendente de coisa"),  # 12 (sem venda) -> Efetivado
    _p(A, 120, "Mesa T", "Banco A", "Xpto"),  # 13 (sem venda) -> Assinado
    _p(A, 100, "Mesa V", "Banco A", "Xpto", "P-U1", "V-U"),  # 14 (numa venda) -> Assinado
    # orfa sozinha no grupo dela: respondida "criar venda so para ela", o grupo esvazia e nao pode virar venda vazia
    _p(J, 30, "Torno C", "Banco A", "Em Análise", "P-O3", "V-SUMIU3"),  # 15
    _p(A, 130, "Mesa Z", "Banco A", "Yyy"),  # 16 (sem venda) -> NF enviada
]
VENDAS = [
    _v("V-A", M, "Cadeira A", v.VENDA_EM_ANDAMENTO, "P-A3", criada=40),
    _v("V-OLD1", J, "Fresa C", "Nota fiscal", "P-W1", criada=60),
    _v("V-OLD2", J, "Fresa D", "Banco escolhido", "", criada=50),
    _v("V-NE1", A, "Laser N", v.VENDA_AGUARDANDO, criada=70),
    _v("V-NE2", A, "Laser M", v.VENDA_AGUARDANDO, criada=71),
    _v("V-NE3", A, "Laser K", v.VENDA_NAO_EFETIVADA, criada=72),
    _v("V-U", A, "Mesa V", v.VENDA_AGUARDANDO, criada=100),
]
HISTORICO = [
    _h(40, v.TIPO_VENDA, "V-A", "", v.VENDA_AGUARDANDO),
    _h(45, v.TIPO_VENDA, "V-OLD1", "", "Nota fiscal"),
    _h(12, v.TIPO_PROPOSTA, "P-A1", "", "Em Análise"),
    _h(25, v.TIPO_PROPOSTA, "P-A3", "Em Análise", "Aprovado"),
    _h(20, v.TIPO_PROPOSTA, "P-A3", "Aprovado", "Garantia Assinada"),
]


def nova_planilha(base: Path, nome: str) -> Path:
    pasta = base / nome
    pasta.mkdir()
    caminho = fx.criar(pasta)
    bd.escrever_vendas_e_propostas(caminho, propostas=pd.DataFrame(PROPOSTAS), vendas=pd.DataFrame(VENDAS, columns=bd.VENDAS_COLUNAS),
                                   historico_novo=HISTORICO)
    return caminho


def relogios(caminho: Path) -> tuple[set, dict, dict]:
    """O que depende do relogio: os alertas (tipo, id, dias), os dias de cada venda e os dias de espera de cada proposta."""
    fx.apontar_modulos_para(caminho)
    alertas = {(a.tipo, a.id, a.dias) for a in v.alertas(HOJE)}
    vendas = v.listar_vendas(HOJE)
    dias_venda = {x.id: x.dias_na_etapa for x in vendas}
    espera = {p.id: p.dias_esperando for x in vendas for p in x.propostas}
    return alertas, dias_venda, espera


def main() -> None:
    def _sem_rede(*_a, **_k):
        raise AssertionError("o teste tentou acessar o Google de verdade")

    rede_original = (nuvem._obter_cliente, sheets_sync._obter_cliente)
    nuvem._obter_cliente = sheets_sync._obter_cliente = _sem_rede
    base = Path(tempfile.mkdtemp(prefix="_smoke_converter_duvidas_"))
    try:
        linha("1) As dúvidas novas: órfã, Não efetivado em venda, venda com status de antes, status desconhecido")
        caminho = nova_planilha(base, "principal")
        antes_relogios = relogios(caminho)
        pilhas_antes = v._pilhas_de_anteriores(bd.ler_historico(caminho))
        # a proposta orfa conta como "sem venda" para o aviso ao abrir
        assert leg.contar_dados_antigos(caminho).sem_venda >= 4
        plano = leg.planejar(caminho)
        assert not plano.problemas, plano.problemas
        por_tipo = {}
        for dv in plano.duvidas:
            por_tipo.setdefault(dv.tipo, []).append(dv)
        assert {t: len(x) for t, x in por_tipo.items()} == {
            leg.TIPO_ORFA: 3, leg.TIPO_NAO_EFETIVADO_EM_VENDA: 2, leg.TIPO_VENDA_STATUS_ANTIGO: 1,
            leg.TIPO_STATUS_DESCONHECIDO: 4}, {t: len(x) for t, x in por_tipo.items()}
        chaves = {dv.chave for dv in plano.duvidas}
        assert {"O3", "O5", "O15", "N9", "N10", "S12", "S13", "S14", "S16"} <= chaves, chaves
        assert "N11" not in chaves, "a venda ja esta Não efetivada: sem dúvida"
        assert por_tipo[leg.TIPO_ORFA][0].opcoes == ("juntar como proposta sem venda", "criar venda só para ela")
        assert por_tipo[leg.TIPO_NAO_EFETIVADO_EM_VENDA][0].opcoes == ("venda Não efetivada", "só Aprovado")
        assert por_tipo[leg.TIPO_VENDA_STATUS_ANTIGO][0].opcoes == ("Aguardando bancos", "Perdida", "Não efetivada")
        assert len(por_tipo[leg.TIPO_STATUS_DESCONHECIDO][0].opcoes) == 7
        chave_v = por_tipo[leg.TIPO_VENDA_STATUS_ANTIGO][0].chave
        assert chave_v == "V2", "a V-OLD2 (a de 'Banco escolhido', sem banco fechado); a V-OLD1 tem banco fechado e se recalcula sozinha"
        assert not [dv for dv in plano.duvidas if dv.tipo == leg.TIPO_FECHADO_SEM_FECHAR], "nenhum banco fechado sem fechar"
        print("OK: 2 órfãs, 2 'Não efetivado' em venda (a da venda já Não efetivada não pergunta), 1 venda de status antigo sem "
              "banco fechado (a com banco fechado se recalcula), 3 status desconhecidos com as 7 opções.")

        linha("2) Responder e converter")
        decisoes = {"O3": "juntar como proposta sem venda", "O5": "criar venda só para ela", "N9": "venda Não efetivada",
                    "N10": "só Aprovado", chave_v: "Perdida", "S12": "Efetivado", "S13": "Assinado", "S14": "Assinado",
                    "O15": "criar venda só para ela", "S16": "NF enviada"}
        resumo = leg.aplicar(plano, decisoes)
        propostas = bd.ler_propostas(caminho)
        por_id = propostas.set_index("ID_PROPOSTA")
        vendas = bd.ler_vendas(caminho).set_index("ID_VENDA")
        assert (propostas["ID_VENDA"] != "").all() and propostas["ID_VENDA"].isin(vendas.index).all()
        assert not leg.contar_dados_antigos(caminho)
        # orfa: junto com a outra sem venda do mesmo equipamento (resposta "juntar")
        outra = propostas[(propostas["EQUIPAMENTO"] == "Tomografo A") & (propostas["ID_PROPOSTA"] != "P-O1")].iloc[0]
        assert por_id.at["P-O1", "ID_VENDA"] == outra["ID_VENDA"] and outra["ID_VENDA"] != "V-SUMIU"
        # orfa "so para ela": a venda tem so ela
        assert len(propostas[propostas["ID_VENDA"] == por_id.at["P-O2", "ID_VENDA"]]) == 1
        negada = propostas[(propostas["EQUIPAMENTO"] == "Torno B") & (propostas["ID_PROPOSTA"] != "P-O2")].iloc[0]
        assert negada["ID_VENDA"] != por_id.at["P-O2", "ID_VENDA"]
        # venda com status antigo: recalcula pelo banco fechado / resposta da duvida
        assert vendas.at["V-OLD1", "STATUS"] == v.VENDA_EFETIVADA and vendas.at["V-OLD2", "STATUS"] == v.VENDA_PERDIDA
        # Nao efetivado em venda existente
        assert vendas.at["V-NE1", "STATUS"] == v.VENDA_NAO_EFETIVADA and vendas.at["V-NE2", "STATUS"] == v.VENDA_AGUARDANDO
        assert vendas.at["V-NE3", "STATUS"] == v.VENDA_NAO_EFETIVADA
        assert {por_id.at[i, "STATUS"] for i in ("P-N1", "P-N2", "P-N3")} == {"Aprovado"}
        # status desconhecido respondido com status de banco fechado: o banco ja sai fechado
        mesa_u = propostas[propostas["EQUIPAMENTO"] == "Mesa U"].iloc[0]
        mesa_t = propostas[propostas["EQUIPAMENTO"] == "Mesa T"].iloc[0]
        mesa_z = propostas[propostas["EQUIPAMENTO"] == "Mesa Z"].iloc[0]
        assert mesa_u["STATUS"] == "Efetivado" and mesa_t["STATUS"] == "Assinado" and mesa_z["STATUS"] == "NF enviada"
        assert vendas.at[mesa_z["ID_VENDA"], "STATUS"] == v.VENDA_EM_ANDAMENTO
        assert v.fechadas_da_venda(vendas.at[mesa_z["ID_VENDA"], "BANCO_ESCOLHIDO"]) == [mesa_z["ID_PROPOSTA"]]
        assert v.fechadas_da_venda(vendas.at[mesa_t["ID_VENDA"], "BANCO_ESCOLHIDO"]) == [mesa_t["ID_PROPOSTA"]]
        # a orfa sozinha: uma venda so dela, e nenhuma venda fica sem proposta
        assert len(propostas[propostas["ID_VENDA"] == por_id.at["P-O3", "ID_VENDA"]]) == 1
        assert vendas.index.isin(propostas["ID_VENDA"]).all(), "nenhuma venda vazia"
        assert vendas.at[mesa_u["ID_VENDA"], "STATUS"] == v.VENDA_EFETIVADA
        assert v.fechadas_da_venda(vendas.at[mesa_u["ID_VENDA"], "BANCO_ESCOLHIDO"]) == [mesa_u["ID_PROPOSTA"]]
        assert vendas.at[mesa_t["ID_VENDA"], "STATUS"] == v.VENDA_EM_ANDAMENTO
        assert por_id.at["P-U1", "STATUS"] == "Assinado" and v.fechadas_da_venda(vendas.at["V-U", "BANCO_ESCOLHIDO"]) == ["P-U1"]
        assert vendas.at["V-U", "STATUS"] == v.VENDA_EM_ANDAMENTO, "a venda ja existia: fechar o banco recalcula"
        print("OK: órfã junta ou ganha venda própria; status antigo de venda recalcula pelo banco fechado ou pela resposta; "
              "'Não efetivado' vira venda Não efetivada só se pedido; Assinado/Nota/Efetivado respondidos já fecham o banco.")

        linha("3) O relógio: alertas e dias iguais antes e depois; o histórico é datado de onde o relógio já contava; o ↩ ignora")
        alertas_depois, dias_venda_depois, espera_depois = relogios(caminho)
        alertas_antes, dias_venda_antes, espera_antes = antes_relogios
        ids_antes = {"V-A", "P-A1", "P-A2", "P-A3"}
        assert alertas_antes, "o teste precisa de alertas para valer"
        assert {a for a in alertas_antes if a[1] in ids_antes} == {a for a in alertas_depois if a[1] in ids_antes}, \
            (alertas_antes, alertas_depois)
        assert {a[2] for a in alertas_antes if a[1] == "P-A1"} == {12} and {a[2] for a in alertas_antes if a[1] == "P-A2"} == {30}
        assert {a[2] for a in alertas_antes if a[1] == "P-A3"} == {20}, "parado em Garantia Assinada ha 20 dias"
        assert dias_venda_antes["V-A"] == dias_venda_depois["V-A"] == 40
        for id_ in ("P-A1", "P-A2", "P-A3"):
            assert espera_antes[id_] == espera_depois[id_], id_
        assert espera_depois["P-O1"] == 10 and espera_depois["P-A1"] == 12 and espera_depois["P-A2"] == 30, "contam da DATA / do historico"
        # as vendas que mudaram de status pela conversao tambem nao zeram: contam da criacao
        assert dias_venda_depois["V-NE1"] == 70 and dias_venda_depois["V-OLD2"] == 50
        assert dias_venda_antes["V-OLD1"] == dias_venda_depois["V-OLD1"] == 45, "a venda com historico conta da ultima mudanca dela"
        hist = bd.ler_historico(caminho)
        novos = hist.iloc[len(HISTORICO):]
        motivo = f"conversão dos dados antigos em {HOJE:%d/%m/%Y}"
        conv = novos[novos["TIPO"] == v.TIPO_CONVERSAO]
        assert (conv["MOTIVO"] == motivo).all() and len(conv) >= 10
        assert (novos["TIPO"] == v.TIPO_PROPOSTA).sum() == 0
        antes_do_a2 = conv[conv["ID"] == "P-A2"]
        assert list(zip(antes_do_a2["DE"], antes_do_a2["PARA"])) == [("EM ANALISE", "Em Análise")]
        assert pd.Timestamp(antes_do_a2["QUANDO"].iloc[0]) == d(30), "sem historico: a DATA da proposta"
        a3 = conv[conv["ID"] == "P-A3"]
        assert pd.Timestamp(a3["QUANDO"].iloc[0]) == d(20), "com historico: a ultima mudanca dela"
        ne1 = conv[conv["ID"] == "V-NE1"]
        assert list(zip(ne1["DE"], ne1["PARA"])) == [(v.VENDA_AGUARDANDO, v.VENDA_NAO_EFETIVADA)]
        assert pd.Timestamp(ne1["QUANDO"].iloc[0]) == d(70), "a criacao da venda"
        old1 = conv[conv["ID"] == "V-OLD1"]
        assert list(zip(old1["DE"], old1["PARA"])) == [("Nota fiscal", v.VENDA_EFETIVADA)]
        assert pd.Timestamp(old1["QUANDO"].iloc[0]) == d(45), "venda com historico: a ultima mudanca dela"
        pilhas_depois = v._pilhas_de_anteriores(hist)
        for id_ in ("P-A1", "P-A2", "P-A3"):
            assert pilhas_depois.get(id_) == pilhas_antes.get(id_), f"o ↩ de {id_} não vê a conversão"
        assert pilhas_antes["P-A3"] == ["Em Análise", "Aprovado"], "o teste precisa de uma pilha para valer"
        print("OK: alertas, dias das vendas e dias de espera iguais; cada linha datada da última mudança (ou da DATA / criação); "
              "o ↩ não enxerga as linhas 'conversao'.")

        linha("4) Qualquer erro depois do backup restaura e diz o nome do backup")
        gravar_original = bd.escrever_vendas_e_propostas
        restaurar_original = backup_mod.restaurar_backup
        conferir_original = leg._conferir_gravacao

        def planeja_de_novo(nome: str):
            caminho_ = nova_planilha(base, nome)
            plano_ = leg.planejar(caminho_)
            return caminho_, plano_, sha(caminho_), {dv.chave: dv.opcoes[0] for dv in plano_.duvidas}

        def nome_do_backup(caminho_) -> str:
            (so_um,) = [b.caminho for b in backup_mod.listar_backups(caminho_) if b.motivo == backup_mod.MOTIVO_PRE_CONVERSAO]
            return so_um.name

        # (a) a gravacao grava e DEPOIS falha
        caminho_a, plano_a, hash_a, resp_a = planeja_de_novo("erro_a")

        def grava_e_falha(c, **k):
            gravar_original(c, **k)
            raise RuntimeError("disco cheio de teste")

        bd.escrever_vendas_e_propostas = grava_e_falha
        try:
            exc = esperar_erro(lambda: leg.aplicar(plano_a, resp_a), "disco cheio de teste")
        finally:
            bd.escrever_vendas_e_propostas = gravar_original
        assert nome_do_backup(caminho_a) in str(exc) and "A restauração deu certo" in str(exc), str(exc)
        assert sha(caminho_a) == hash_a, "restaurado: igual ao de antes"
        # (b) erro de arquivo bloqueado (nada chegou a ser gravado)
        caminho_b, plano_b, hash_b, resp_b = planeja_de_novo("erro_b")

        def bloqueado(c, **k):
            raise bd.ErroArquivoBloqueado("aberto no Excel de teste")

        bd.escrever_vendas_e_propostas = bloqueado
        try:
            exc = esperar_erro(lambda: leg.aplicar(plano_b, resp_b), "aberto no Excel de teste")
        finally:
            bd.escrever_vendas_e_propostas = gravar_original
        assert nome_do_backup(caminho_b) in str(exc) and "restaura" in str(exc).lower() and sha(caminho_b) == hash_b
        # (c) erro na propria conferencia
        caminho_c, plano_c, hash_c, resp_c = planeja_de_novo("erro_c")

        def conferencia_quebra(*a, **k):
            raise ValueError("conferência quebrou de teste")

        leg._conferir_gravacao = conferencia_quebra
        try:
            exc = esperar_erro(lambda: leg.aplicar(plano_c, resp_c), "conferência quebrou de teste")
        finally:
            leg._conferir_gravacao = conferir_original
        assert nome_do_backup(caminho_c) in str(exc) and "A restauração deu certo" in str(exc) and sha(caminho_c) == hash_c
        # (d) a restauracao tambem falha: a mensagem diz isso e o nome do backup
        caminho_d, plano_d, hash_d, resp_d = planeja_de_novo("erro_d")

        def restaurar_falha(*a, **k):
            raise OSError("pasta sumiu de teste")

        bd.escrever_vendas_e_propostas = grava_e_falha
        backup_mod.restaurar_backup = restaurar_falha
        try:
            exc = esperar_erro(lambda: leg.aplicar(plano_d, resp_d), "A RESTAURAÇÃO FALHOU")
        finally:
            bd.escrever_vendas_e_propostas = gravar_original
            backup_mod.restaurar_backup = restaurar_original
        assert nome_do_backup(caminho_d) in str(exc) and "pasta sumiu de teste" in str(exc) and "restaure o backup à mão" in str(exc)
        # (e) a restauracao "roda" mas o arquivo nao fica igual ao backup
        caminho_e, plano_e, hash_e, resp_e = planeja_de_novo("erro_e")
        bd.escrever_vendas_e_propostas = grava_e_falha
        backup_mod.restaurar_backup = lambda *a, **k: None
        try:
            exc = esperar_erro(lambda: leg.aplicar(plano_e, resp_e), "NÃO ficou igual ao backup")
        finally:
            bd.escrever_vendas_e_propostas = gravar_original
            backup_mod.restaurar_backup = restaurar_original
        assert nome_do_backup(caminho_e) in str(exc)
        print("OK: erro ao gravar, arquivo bloqueado, erro na conferência, restauração que falha e restauração que não "
              "iguala: sempre o nome do backup e se a restauração deu certo.")

        linha("TUDO OK")
    finally:
        nuvem._obter_cliente, sheets_sync._obter_cliente = rede_original
        fx.restaurar_modulos()
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    main()
