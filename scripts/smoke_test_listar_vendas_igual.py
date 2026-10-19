"""Prova que listar_vendas (core/vendas.py) devolve EXATAMENTE o mesmo depois de ficar mais rapida (plano 1.6, parte 1):
monta uma planilha ficticia com todos os casos (status calculado e manual, bancos fechados, propostas sem venda, sem
ID, com datas iguais ou ausentes, historico com "voltar", CPF com e sem mascara...) e compara a saida inteira (todos
os campos de ResumoDaVenda e de PropostaNaVenda, na ordem) com a referencia gerada pelo codigo ANTIGO
(scripts/referencias/listar_vendas_1_6.txt). Tambem prova que escrever_vendas_e_propostas sem sincronizacao nao relê o
arquivo so para montar o envio, e que com ela ligada o que vai para a nuvem e o mesmo de antes.

Tudo numa planilha 100% ficticia em pasta temporaria; o Google fica desligado.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_listar_vendas_igual.py
Gerar a referencia de novo (so com o codigo cuja saida e a correta): ... smoke_test_listar_vendas_igual.py --gerar
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from datetime import date, datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False
import fixture_ficticia as fx
from core import data_store as bd
from core import propostas as P
from core import sessao as sessao_mod
from core import sheets_sync
from core import vendas as v

REFERENCIA = Path(__file__).resolve().parent / "referencias" / "listar_vendas_1_6.txt"
HOJE = date(2026, 10, 19)
ADMIN = sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador")


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _d(dia: str) -> pd.Timestamp:
    return pd.Timestamp(dia)


def _proposta(id_p, id_v, cpf, banco, status, data, valor=50000.0, meses=36, equip="Equipamento Modelo X", carencia=None,
              parcela=None) -> dict:
    return {"DATA": _d(data) if data else None, "CPF": cpf, "VALOR (R$)": valor, "MESES": meses, "EQUIPAMENTO": equip,
            "BANCO": banco, "STATUS": status, "OBSERVAÇÕES": "", "ID_PROPOSTA": id_p, "ID_VENDA": id_v,
            "CARÊNCIA (DIAS)": carencia, "PARCELA (R$)": parcela}


def _venda(id_v, cpf, equip, status, fechadas, motivo, criacao, obs="") -> dict:
    return {"ID_VENDA": id_v, "CPF": cpf, "EQUIPAMENTOS": equip, "STATUS": status, "BANCO_ESCOLHIDO": fechadas,
            "MOTIVO": motivo, "DATA_CRIACAO": _d(criacao) if criacao else None, "OBSERVAÇÕES": obs}


def _h(quando, tipo, id_, de, para, motivo="") -> dict:
    return {"QUANDO": datetime.fromisoformat(quando), "TIPO": tipo, "ID": id_, "DE": de, "PARA": para, "MOTIVO": motivo,
            "COMPUTADOR": "PC-FICTICIO"}


def montar_planilha(caminho: Path) -> None:
    """Acrescenta ao exemplo (as propostas antigas, sem venda, com datas fixas) as vendas e propostas de cada caso."""
    maria, joao, ana = fx.CPF_MARIA, fx.CPF_JOAO, fx.CPF_ANA
    sem_mascara = "".join(c for c in maria if c.isdigit())
    antigas = bd.ler_propostas(caminho)[bd.PROPOSTAS_COLUNAS_EDITAVEIS].copy()
    antigas["DATA"] = [pd.Timestamp(2026, 9, 1) + pd.Timedelta(days=i) for i in range(len(antigas))]
    novas = pd.DataFrame([
        # V-1: Em andamento, 2 fechadas (uma Efetivada, uma Assinado), 1 aberta e 1 negada; datas iguais (desempate)
        _proposta("P-a1", "V-1", maria, "Banco Exemplo", P.STATUS_EFETIVADO, "2026-09-02", carencia=30, parcela=1800.5),
        _proposta("P-a2", "V-1", maria, "Outro Banco Exemplo", P.STATUS_ASSINADO, "2026-09-02", valor=31000.0, meses=48),
        _proposta("P-a3", "V-1", maria, "Banco Terceiro", P.STATUS_EM_ANALISE, "2026-09-02"),
        _proposta("P-a4", "V-1", maria, "Banco Quarto", P.STATUS_NEGADO, "2026-08-30", valor=None, meses=None),
        # V-2: Aguardando, so respostas pendentes (dias esperando pelo historico e pela DATA)
        _proposta("P-b1", "V-2", joao, "Banco Exemplo", P.STATUS_EM_ANALISE, "2026-10-01"),
        _proposta("P-b2", "V-2", joao, "Outro Banco Exemplo", P.STATUS_PRE_APROVADO, "2026-10-05", carencia=45),
        _proposta("P-b3", "V-2", joao, "Banco Terceiro", P.STATUS_APROVADO, None),  # sem data: vai pro fim
        # V-3: Efetivada gravada; fechada Efetivada
        _proposta("P-c1", "V-3", ana, "Banco Exemplo", P.STATUS_EFETIVADO, "2026-08-21"),
        # V-4: Nao efetivada (manual) com fechada que sumiu da lista
        _proposta("P-d1", "V-4", maria, "Banco Exemplo", P.STATUS_APROVADO, "2026-09-12"),
        # V-5: Perdida (manual), tudo negado
        _proposta("P-e1", "V-5", joao, "Banco Exemplo", P.STATUS_NEGADO, "2026-09-11"),
        _proposta("P-e2", "V-5", joao, "Banco Terceiro", P.STATUS_NEGADO, "2026-09-11"),
        # V-6: Pendente de entrega (manual) com fechada Efetivada
        _proposta("P-f1", "V-6", ana, "Banco Exemplo", P.STATUS_EFETIVADO, "2026-07-30"),
        # V-8: status de antes da 1.2 em banco fechado
        _proposta("P-g1", "V-8", ana, "Banco Exemplo", P.STATUS_GARANTIA_ASSINADA, "2026-09-20"),
        _proposta("P-g2", "V-8", ana, "Banco Terceiro", P.STATUS_NF_ANEXADA, "2026-09-21"),
        # proposta com venda e sem ID_PROPOSTA (de antes), e proposta que aponta para uma venda que nao existe
        _proposta("", "V-2", joao, "Banco Antigo", P.STATUS_EM_ANALISE, "2026-10-02"),
        _proposta("P-z1", "V-INEXISTENTE", ana, "Banco Exemplo", P.STATUS_EM_ANALISE, "2026-10-03"),
        # ID_PROPOSTA repetido (a mesma proposta duas vezes)
        _proposta("P-a4", "V-8", ana, "Banco Quarto", P.STATUS_APROVADO, "2026-09-22"),
    ])
    todas = pd.concat([antigas, novas], ignore_index=True)
    vendas = pd.DataFrame([
        _venda("V-1", sem_mascara, "Laser X + Cadeira Y", "Em andamento", "P-a1;P-a2", "", "2026-09-01", "obs 1"),
        _venda("V-2", joao, "Equipamento Modelo X", "Aguardando bancos", "", "", "2026-09-10"),
        _venda("V-3", ana, "Equipamento Modelo Y", "Efetivada", "P-c1", "", "2026-08-20"),
        _venda("V-4", maria, "Equipamento Modelo X", "Não efetivada", "P-d1;P-fantasma", "Cliente desistiu", "2026-09-10"),
        _venda("V-5", joao, "Equipamento Modelo X", "Perdida", "", "Todos os bancos negaram", "2026-09-10"),
        _venda("V-6", ana, "Equipamento Modelo Y", "Pendente de entrega", "P-f1", "Aguardando o frete", "2026-07-29"),
        _venda("V-7", "00000000000", "Equipamento Modelo Z", "Em andamento", "", "", None),  # cliente fora do cadastro
        _venda("V-8", ana, "Equipamento Modelo Y", "Banco escolhido", " P-g1 ; P-a4 ;", "", "2026-09-19"),
        _venda("", maria, "Venda sem ID", "Aguardando bancos", "", "", "2026-09-15"),  # junta as propostas sem ID_VENDA
        _venda("V-9", maria, "Equipamento Modelo X", "Efetivada", "P-d1", "", "2026-09-10"),  # fechada de outra venda
    ])
    historico = [
        _h("2026-09-01 10:00:00", v.TIPO_VENDA, "V-1", "", "Aguardando bancos"),
        _h("2026-09-02 10:00:00", v.TIPO_PROPOSTA, "P-a1", "", "Em Análise"),
        _h("2026-09-05 10:00:00", v.TIPO_PROPOSTA, "P-a1", "Em Análise", "Pré-aprovado"),
        _h("2026-09-06 10:00:00", v.TIPO_PROPOSTA, "P-a1", "Pré-aprovado", "Aprovado"),
        _h("2026-09-07 10:00:00", v.TIPO_PROPOSTA, "P-a1", "Aprovado", "Pré-aprovado"),  # voltou: desempilha
        _h("2026-09-08 10:00:00", v.TIPO_PROPOSTA, "P-a1", "Pré-aprovado", "Aprovado"),
        _h("2026-09-09 10:00:00", v.TIPO_PROPOSTA, "P-a1", "Aprovado", "Efetivado"),
        _h("2026-09-09 11:00:00", v.TIPO_FECHAMENTO, "P-a1", "", "Fechada"),
        _h("2026-09-12 10:00:00", v.TIPO_PROPOSTA, "P-a2", "Aprovado", "Assinado"),
        _h("2026-09-13 10:00:00", v.TIPO_PROPOSTA, "P-a2", "Assinado", "Assinado"),  # de == para: ignora
        _h("2026-09-14 10:00:00", v.TIPO_CONVERSAO, "P-a2", "Aprovado", "Assinado"),
        _h("2026-10-03 10:00:00", v.TIPO_PROPOSTA, "P-b1", "Em Análise", "Em Análise", "mexeu e voltou"),
        _h("2026-10-08 09:00:00", v.TIPO_PROPOSTA, "P-b2", "Em Análise", "Pré-aprovado"),
        _h("2026-10-12 09:00:00", v.TIPO_VENDA, "V-2", "", "Aguardando bancos"),
        _h("2026-09-30 09:00:00", v.TIPO_VENDA, "V-4", "Em andamento", "Não efetivada", "Cliente desistiu"),
        _h("2026-10-10 09:00:00", v.TIPO_VENDA, "V-6", "Efetivada", "Pendente de entrega", "Aguardando o frete"),
        _h("2026-09-25 09:00:00", v.TIPO_PROPOSTA, "P-g1", "Aprovado", "Garantia Assinada"),
        _h("2026-09-26 09:00:00", v.TIPO_PROPOSTA, "P-g2", "Aprovado", "Status Esquisito"),  # "voltar" a status que nao volta
        _h("2026-09-27 09:00:00", v.TIPO_PROPOSTA, "P-g2", "Status Esquisito", "Nota Fiscal Anexada"),
    ]
    bd.escrever_vendas_e_propostas(caminho, propostas=todas, vendas=vendas, historico_novo=historico)


def como_texto(resumos) -> str:
    """Cada venda e cada proposta, com TODOS os campos, uma por linha (o repr do dataclass os traz todos)."""
    saida = []
    for r in resumos:
        saida.append(repr(r))
    return "\n".join(saida) + "\n"


def main() -> None:
    gerar = "--gerar" in sys.argv
    pasta = Path(tempfile.mkdtemp(prefix="_smoke_listar_vendas_"))
    fx.isolar_preferencias(pasta)
    caminho = fx.criar(pasta)
    fx.apontar_modulos_para(caminho)
    sessao_mod.iniciar(ADMIN)
    try:
        montar_planilha(caminho)
        resumos = v.listar_vendas(HOJE)
        texto = como_texto(resumos)

        linha("1) A fixture exercita todos os casos")
        status = {r.status for r in resumos}
        assert status == set(v.STATUS_DA_VENDA), status
        assert len(resumos) == 10 and sum(len(r.propostas) for r in resumos) >= 17
        assert any(r.data_criacao is None for r in resumos) and any(r.cliente == "" for r in resumos)
        assert any(r.anterior for r in resumos) and any(p.anterior for r in resumos for p in r.propostas)
        assert any(p.dias_esperando is not None for r in resumos for p in r.propostas)
        assert any(p.valor is None for r in resumos for p in r.propostas)
        assert any(not p.id for r in resumos for p in r.propostas), "proposta sem ID_PROPOSTA dentro de uma venda"
        print(f"OK: {len(resumos)} vendas, {sum(len(r.propostas) for r in resumos)} propostas, todos os status de venda.")

        if gerar:
            REFERENCIA.parent.mkdir(exist_ok=True)
            REFERENCIA.write_text(texto, encoding="utf-8", newline="\n")
            print(f"Referencia gravada em {REFERENCIA} ({len(texto)} caracteres). Rode de novo sem --gerar.")
            return

        linha("2) listar_vendas devolve exatamente a referencia (codigo antigo), campo a campo")
        esperado = REFERENCIA.read_text(encoding="utf-8")
        if texto != esperado:
            for n, (a, b) in enumerate(zip(texto.splitlines(), esperado.splitlines()), start=1):
                if a != b:
                    raise AssertionError(f"linha {n} difere:\n  agora:      {a}\n  referencia: {b}")
            raise AssertionError(f"numero de linhas difere: {len(texto.splitlines())} x {len(esperado.splitlines())}")
        print("OK: a saida inteira e identica a gerada pelo codigo antigo.")

        linha("3) Gravar sem sincronizacao nao relê o arquivo so para montar o envio; com ela, envia o mesmo de antes")
        leituras = []
        originais = {nome: getattr(bd, nome) for nome in ("ler_propostas", "ler_vendas", "ler_historico", "ler_clientes")}
        for nome, original in originais.items():
            def espiao(*a, _n=nome, _o=original, **k):
                leituras.append(_n)
                return _o(*a, **k)
            setattr(bd, nome, espiao)
        try:
            propostas = originais["ler_propostas"](caminho)[bd.PROPOSTAS_COLUNAS_EDITAVEIS].copy()
            vendas = originais["ler_vendas"](caminho)
            historico = [_h("2026-10-18 10:00:00", v.TIPO_PROPOSTA, "P-b1", "Em Análise", "Pré-aprovado")]
            vendas.loc[vendas["ID_VENDA"] == "V-2", "OBSERVAÇÕES"] = "gravado pelo teste"
            leituras.clear()
            bd.escrever_vendas_e_propostas(caminho, propostas=propostas, vendas=vendas, historico_novo=historico)
            assert leituras == [], f"sem sincronizacao, gravar nao deveria reler o arquivo: {leituras}"
            assert originais["ler_vendas"](caminho).set_index("ID_VENDA").loc["V-2", "OBSERVAÇÕES"] == "gravado pelo teste"
            assert originais["ler_historico"](caminho)["QUANDO"].max() == pd.Timestamp("2026-10-18 10:00:00")

            # com a sincronizacao LIGADA (a real, so o envio ao Google e trocado por uma captura): o df de cada aba que
            # chega ao envio e o lido do arquivo gravado
            enviados = {}
            envio_original, cliente_original = sheets_sync._sincronizar_agora, sheets_sync._obter_cliente

            def _sem_rede(*_a, **_k):
                raise AssertionError("o teste tentou acessar o Google de verdade")

            sheets_sync._obter_cliente = _sem_rede
            sheets_sync._sincronizar_agora = lambda aba, df: enviados.update({aba: df})
            sheets_sync._reiniciar_estado()
            config.SINCRONIZACAO_GOOGLE_ATIVADA = True
            try:
                bd.escrever_vendas_e_propostas(caminho, propostas=propostas, vendas=vendas, historico_novo=historico)
                limite = time.monotonic() + 10
                while len(enviados) < 3 and time.monotonic() < limite:
                    time.sleep(0.02)
            finally:
                config.SINCRONIZACAO_GOOGLE_ATIVADA = False
                sheets_sync._sincronizar_agora, sheets_sync._obter_cliente = envio_original, cliente_original
                time.sleep(0.2)  # a thread de envio termina de registrar o fim
                sheets_sync._reiniciar_estado()
            assert set(enviados) == {bd.ABA_PROPOSTAS, bd.ABA_VENDAS, bd.ABA_HISTORICO}, set(enviados)
            for aba, leitor in ((bd.ABA_PROPOSTAS, originais["ler_propostas"]), (bd.ABA_VENDAS, originais["ler_vendas"]),
                                (bd.ABA_HISTORICO, originais["ler_historico"])):
                assert isinstance(enviados[aba], pd.DataFrame), "o envio recebe a tabela pronta, nao a funcao"
                pd.testing.assert_frame_equal(enviados[aba], leitor(caminho))
            print("OK: sem sincronizacao nao relê nada; com ela, as tres abas enviadas sao as lidas do arquivo gravado.")
        finally:
            for nome, original in originais.items():
                setattr(bd, nome, original)
        linha("TUDO OK")
    finally:
        fx.restaurar_modulos()
        sessao_mod.encerrar()


if __name__ == "__main__":
    main()
