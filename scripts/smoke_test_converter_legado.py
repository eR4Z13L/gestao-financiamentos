"""Testa a conversao dos dados antigos (core/migracao_legado.py e scripts/converter_legado.py, plano 1.3):
cada linha da tabela de status, as duvidas (juntar, Encerrada, texto desconhecido, banco fechado sem fechar), simular
sem gravar, a recusa de aplicar sem decisao, o backup, as contagens antes e depois, a restauracao quando a conferencia
falha, o script sem caminho e o script nunca tocando os dados reais.

Planilha 100% ficticia em pasta temporaria; o Google fica desligado e qualquer acesso a ele derruba o teste.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_converter_legado.py
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False
import fixture_ficticia as fx
from core import backup as backup_mod
from core import data_store as bd
from core import data_store_sheets as nuvem
from core import migracao_legado as leg
from core import propostas as propostas_mod
from core import sheets_sync
from core import vendas as v

HOJE = date(2026, 9, 1)
M, J, A = fx.CPF_MARIA, fx.CPF_JOAO, fx.CPF_ANA
SCRIPT = RAIZ / "scripts" / "converter_legado.py"


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def _p(cpf: str, dias: int, equip: str, banco: str, status: str, id_proposta: str = "", id_venda: str = "") -> dict:
    return {"DATA": pd.Timestamp(HOJE + timedelta(days=dias)), "CPF": cpf, "VALOR (R$)": 1000 + dias, "MESES": 12,
            "EQUIPAMENTO": equip, "BANCO": banco, "STATUS": status, "OBSERVAÇÕES": "",
            "ID_PROPOSTA": id_proposta, "ID_VENDA": id_venda, "CARÊNCIA (DIAS)": None, "PARCELA (R$)": None}


LINHAS = [
    # Maria: cadeira em 3 bancos (Garantia assinada e Nota fiscal anexada = bancos fechados); laser 2 dias depois
    _p(M, 0, "Cadeira X", "Banco A", "Garantia Assinada"),  # 0
    _p(M, 0, "Cadeira X", "Banco B", "Aprovada"),  # 1
    _p(M, 1, "Cadeira X", "Banco C", "Nota Fiscal Anexada"),  # 2
    _p(M, 2, "Laser Y", "Banco A", "pre aprovado"),  # 3
    # João: mesa com Não efetivado e Negado; 20 dias depois outra leva negada (dúvida: espaçada)
    _p(J, 0, "Mesa Z", "Banco A", "Não efetivado"),  # 4
    _p(J, 1, "Mesa Z", "Banco B", " negado "),  # 5
    _p(J, 20, "Mesa Z", "Banco A", "NEGADO"),  # 6
    # Ana: autoclave efetivada, mais uma Encerrada, um texto desconhecido, um vazio e uma Em Análise
    _p(A, 5, "Autoclave W", "Banco A", "EFETIVADO"),  # 7
    _p(A, 5, "Autoclave W", "Banco B", "Encerrada"),  # 8
    _p(A, 5, "Autoclave W", "Banco C", "Reprovado"),  # 9
    _p(A, 6, "Autoclave W", "Banco D", ""),  # 10
    _p(A, 6, "Autoclave W", "Banco E", "EM ANALISE"),  # 11
    _p(A, 40, "Mesa Q", "Banco A", "Aprovado"),  # 12 (ja oficial: nao muda)
    # Maria, ja em vendas: Garantia assinada que NAO esta fechada na venda (duvida), um Aprovado e um Efetivado fechado
    _p(M, 60, "Raio Z", "Banco A", "Garantia Assinada", "P-X1", "V-X"),  # 13
    _p(M, 60, "Raio Z", "Banco B", "Aprovado", "P-X2", "V-X"),  # 14
    _p(M, 70, "Raio W", "Banco A", "Efetivado", "P-Y1", "V-Y"),  # 15
    # João: "Assinado" (status novo) sem venda: o banco nao esta fechado (duvida)
    _p(J, 100, "Cadeira Q", "Banco A", "Assinado"),  # 16
    # Ana: Encerrada + Negado no mesmo negocio: respondida "Negado", a venda tem so negadas = Perdida
    _p(A, 70, "Mesa R", "Banco A", "Encerrada"),  # 17
    _p(A, 70, "Mesa R", "Banco B", "Negado"),  # 18
]
VENDAS_EXISTENTES = [
    {"ID_VENDA": "V-X", "CPF": M, "EQUIPAMENTOS": "Raio Z", "STATUS": v.VENDA_AGUARDANDO, "BANCO_ESCOLHIDO": "", "MOTIVO": "",
     "DATA_CRIACAO": pd.Timestamp(HOJE + timedelta(days=60)), "OBSERVAÇÕES": ""},
    {"ID_VENDA": "V-Y", "CPF": M, "EQUIPAMENTOS": "Raio W", "STATUS": v.VENDA_EFETIVADA, "BANCO_ESCOLHIDO": "P-Y1", "MOTIVO": "",
     "DATA_CRIACAO": pd.Timestamp(HOJE + timedelta(days=70)), "OBSERVAÇÕES": ""},
]
STATUS_ESPERADOS = ["Assinado", "Aprovado", "Nota fiscal enviada", "Pré-aprovado", "Aprovado", "Negado", "Negado", "Efetivado",
                    "Negado", "Negado", "Em Análise", "Em Análise", "Aprovado", "Assinado", "Aprovado", "Efetivado", "Aprovado", "Negado", "Negado"]


def sha(caminho: Path) -> str:
    return hashlib.sha256(Path(caminho).read_bytes()).hexdigest()


def nova_planilha(pasta_base: Path, nome: str) -> Path:
    """Uma planilha fictícia com todos os casos, numa subpasta nova."""
    pasta = pasta_base / nome
    pasta.mkdir()
    caminho = fx.criar(pasta)
    bd.escrever_vendas_e_propostas(caminho, propostas=pd.DataFrame(LINHAS), vendas=pd.DataFrame(VENDAS_EXISTENTES, columns=bd.VENDAS_COLUNAS))
    return caminho


def rodar_script(*args: str, pasta: Path | None = None):
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=pasta or RAIZ, capture_output=True, text=True,
                          encoding="utf-8", timeout=300, env={**os.environ, "PYTHONIOENCODING": "utf-8"})


def esperar_erro(chamada, trecho: str):
    try:
        chamada()
    except leg.ErroConversao as exc:
        assert trecho in str(exc), (trecho, str(exc))
        return exc
    raise AssertionError(f"deveria recusar ({trecho!r})")


def main() -> None:
    def _sem_rede(*_a, **_k):
        raise AssertionError("o teste tentou acessar o Google de verdade")

    rede_original = (nuvem._obter_cliente, sheets_sync._obter_cliente)
    nuvem._obter_cliente = sheets_sync._obter_cliente = _sem_rede
    base = Path(tempfile.mkdtemp(prefix="_smoke_converter_legado_"))
    # os modulos de negocio apontam para uma planilha ISCA: se o conversor um dia ler/gravar no caminho "padrao" dos
    # modulos em vez do arquivo recebido, a isca muda (e o teste acusa) - nunca o arquivo real
    isca = fx.criar(base)
    fx.apontar_modulos_para(isca)
    hash_isca = sha(isca)
    real = Path(config.CAMINHO_XLSX)
    meta_real = (real.stat().st_mtime_ns, real.stat().st_size) if real.exists() else None  # so metadados: nao abre o arquivo
    try:
        linha("1) A tabela de status: cada linha, sem diferenciar maiúsculas, acentos e espaços")
        tabela = {
            "Garantia Assinada": "Assinado", "  garantia   ASSINADA ": "Assinado", "Nota Fiscal Anexada": "Nota fiscal enviada",
            "NOTA FISCAL ANEXADA": "Nota fiscal enviada", "Não efetivado": "Aprovado", "NAO EFETIVADO": "Aprovado",
            "EFETIVADO": "Efetivado", "efetivado": "Efetivado", "APROVADO": "Aprovado", "aprovado": "Aprovado",
            "EM ANÁLISE": "Em Análise", "em analise": "Em Análise", "PRÉ-APROVADO": "Pré-aprovado", "pre-aprovado": "Pré-aprovado",
            "Pré aprovado": "Pré-aprovado", "NEGADO": "Negado", "negado": "Negado", "Assinado": "Assinado",
            "Nota fiscal enviada": "Nota fiscal enviada", "Efetivada": "Efetivado", "Aprovada": "Aprovado", "Negada": "Negado",
            "Pré-Aprovado": "Pré-aprovado", "  em   ANÁLISE": "Em Análise",
        }
        for antigo, novo in tabela.items():
            assert leg.converter_status(antigo) == novo, (antigo, leg.converter_status(antigo))
        for duvida in ("Encerrada", "ENCERRADA", "", "   ", None, "Reprovado", "Cancelado", "Pendente", "Banco escolhido", "xyz"):
            assert leg.converter_status(duvida) is None, duvida
        print("OK: 24 grafias convertidas para o status certo; Encerrada, vazio e qualquer outro texto não têm resposta (viram dúvida).")

        linha("2) Simular: acha as dúvidas e não altera o arquivo")
        caminho = nova_planilha(base, "simular")
        antes_bytes, hash_antes = caminho.read_bytes(), sha(caminho)
        historico_antes = len(bd.ler_historico(caminho))
        plano = leg.planejar(caminho)
        assert sha(caminho) == hash_antes and caminho.read_bytes() == antes_bytes, "planejar nunca grava"
        por_tipo = {}
        for d in plano.duvidas:
            por_tipo.setdefault(d.tipo, []).append(d)
        assert {t: len(l) for t, l in por_tipo.items()} == {
            leg.TIPO_JUNTAR_VARIOS_EQUIPAMENTOS: 1, leg.TIPO_JUNTAR_ESPACADA: 1, leg.TIPO_ENCERRADA: 2,
            leg.TIPO_STATUS_DESCONHECIDO: 2, leg.TIPO_FECHADO_SEM_FECHAR: 2}, {t: len(l) for t, l in por_tipo.items()}
        chaves = {d.chave for d in plano.duvidas}
        assert {"S8", "S9", "S10", "S17", "F13", "F16"} <= chaves, chaves
        assert not plano.problemas
        assert plano.antes["propostas"] == 19 and plano.antes["vendas"] == 2 and plano.antes["propostas_sem_venda"] == 16
        assert plano.antes["propostas_por_status"]["Garantia Assinada"] == 2 and plano.antes["propostas_por_status"]["(vazio)"] == 1
        pergunta_juntar = por_tipo[leg.TIPO_JUNTAR_VARIOS_EQUIPAMENTOS][0]
        assert pergunta_juntar.opcoes == ("juntar", "separar") and "Laser Y" in pergunta_juntar.pergunta
        assert por_tipo[leg.TIPO_ENCERRADA][0].opcoes == ("Aprovado", "Negado", "Em Análise")
        assert por_tipo[leg.TIPO_STATUS_DESCONHECIDO][0].opcoes == (
            "Em Análise", "Pré-aprovado", "Aprovado", "Negado", "Assinado", "Nota fiscal enviada", "Efetivado"), "os 7 oficiais"
        assert por_tipo[leg.TIPO_FECHADO_SEM_FECHAR][0].opcoes == ("fechar", "Aprovado")
        assert plano.depois["propostas_sem_venda"] == 0, "mesmo sem respostas a simulação mostra tudo em vendas"
        assert not backup_mod.listar_backups(caminho) and len(bd.ler_historico(caminho)) == historico_antes
        print(f"OK: {len(plano.duvidas)} dúvidas (juntar x2, Encerrada, desconhecido e vazio, banco fechado sem fechar x2); arquivo igual.")

        linha("3) O relatório e a lista de dúvidas")
        saida = base / "saida"
        relatorio, duvidas = leg.escrever_relatorios(plano, saida)
        texto = relatorio.read_text(encoding="utf-8")
        assert "SIMULAÇÃO" in texto and "| Propostas | 19 | 19 |" in texto and "Garantia Assinada" in texto
        lista = json.loads(duvidas.read_text(encoding="utf-8"))
        assert [d["chave"] for d in lista["duvidas"]] == [d.chave for d in plano.duvidas]
        assert all(d["opcoes"] and d["pergunta"] for d in lista["duvidas"]) and lista["arquivo"] == caminho.name
        assert sha(caminho) == hash_antes
        print("OK: relatorio_conversao.md com antes/depois e duvidas_conversao.json com as opções de cada dúvida.")

        linha("4) Aplicar sem decisão, com resposta inválida, de outro arquivo ou com o arquivo mudado: recusa")
        decisoes = {
            por_tipo[leg.TIPO_JUNTAR_VARIOS_EQUIPAMENTOS][0].chave: "juntar", por_tipo[leg.TIPO_JUNTAR_ESPACADA][0].chave: "separar",
            "S8": "Negado", "S9": "negado", "S10": "Em Análise", "S17": "Negado", "F13": "fechar", "F16": "Aprovado",
        }
        parcial = dict(decisoes)
        del parcial["S8"]
        esperar_erro(lambda: leg.aplicar(plano, {}), "Faltam decisões para 8")
        esperar_erro(lambda: leg.aplicar(plano, parcial), "Faltam decisões para 1 dúvida(s): S8")
        esperar_erro(lambda: leg.aplicar(plano, {**decisoes, "S8": "Efetivado"}), "Resposta inválida para a dúvida S8")
        esperar_erro(lambda: leg.aplicar(plano, {**decisoes, "S8": "Pré-aprovado"}), "Resposta inválida para a dúvida S8")
        esperar_erro(lambda: leg.aplicar(plano, {**decisoes, "F13": "Negado"}), "Resposta inválida para a dúvida F13")
        esperar_erro(lambda: leg.aplicar(plano, {**decisoes, "S99": "Negado"}), "não corresponde a nenhuma dúvida")
        assert sha(caminho) == hash_antes and not backup_mod.listar_backups(caminho), "recusar não grava nem faz backup"
        config.SINCRONIZACAO_GOOGLE_ATIVADA = True
        try:
            esperar_erro(lambda: leg.aplicar(plano, decisoes), "sincronização com o Google precisa estar desligada")
        finally:
            config.SINCRONIZACAO_GOOGLE_ATIVADA = False
        assert sha(caminho) == hash_antes and not backup_mod.listar_backups(caminho)
        plano_com_problema = leg.planejar(caminho)
        plano_com_problema.problemas = ["problema inventado"]
        esperar_erro(lambda: leg.aplicar(plano_com_problema, decisoes), "problemas que nenhuma resposta resolve")
        assert sha(caminho) == hash_antes
        print("OK: sem decisão, resposta fora das opções, decisão de outro arquivo, Google ligado e problema aberto: tudo recusado sem gravar.")

        linha("5) O arquivo do app, data/ e qualquer lugar dentro do projeto são recusados (config falsa, nunca a real)")
        configurado, raiz_configurada = config.CAMINHO_XLSX, config.DIRETORIO_BASE
        raiz_falsa = base / "projeto_falso"  # o "projeto" desta secao: nada do projeto de verdade entra aqui
        (raiz_falsa / "sub").mkdir(parents=True)
        pasta_do_app = base / "pasta_do_app"
        pasta_do_app.mkdir()
        config.DIRETORIO_BASE = raiz_falsa
        config.CAMINHO_XLSX = pasta_do_app / "controle_do_app.dat"
        try:
            # o arquivo configurado e tudo na pasta dele (mesmo existindo uma copia valida la dentro)
            copia_ali = pasta_do_app / "copia.dat"
            shutil.copy(caminho, copia_ali)
            esperar_erro(lambda: leg.planejar(config.CAMINHO_XLSX), "arquivos de dados do app")
            esperar_erro(lambda: leg.planejar(copia_ali), "arquivos de dados do app")
            # data/ do projeto (arquivo que nem existe: a recusa vem antes de abrir qualquer coisa)
            esperar_erro(lambda: leg.planejar(raiz_falsa / "data" / "qualquer.dat"), "arquivos de dados do app")
            esperar_erro(lambda: leg.planejar(raiz_falsa / "data" / "backups" / "x" / "qualquer.dat"), "arquivos de dados do app")
            # qualquer lugar do projeto, existindo ou nao
            dentro = raiz_falsa / "sub" / "copia.dat"
            shutil.copy(caminho, dentro)
            for alvo in (dentro, raiz_falsa / "sub" / "nao_existe.dat", raiz_falsa / "copia_solta.dat"):
                exc = esperar_erro(lambda alvo=alvo: leg.planejar(alvo), "dentro da pasta do projeto")
                assert "FORA do projeto" in str(exc), "a mensagem diz para usar uma pasta fora do projeto"
            # a pasta de saida dos relatorios tambem
            for saida_ruim in (raiz_falsa, raiz_falsa / "relatorios", raiz_falsa / "sub" / "a" / "b"):
                exc = esperar_erro(lambda s=saida_ruim: leg.exigir_saida_permitida(s), "dentro da pasta do projeto")
                assert "pasta de saída" in str(exc) and "FORA do projeto" in str(exc)
                esperar_erro(lambda s=saida_ruim: leg.escrever_relatorios(leg.planejar(caminho), s), "dentro da pasta do projeto")
            assert not (raiz_falsa / "relatorios").exists() and not (raiz_falsa / "sub" / "a").exists(), "nada foi criado la dentro"
            assert leg.exigir_saida_permitida(base / "relatorios_ok") == (base / "relatorios_ok").resolve()
        finally:
            config.CAMINHO_XLSX, config.DIRETORIO_BASE = configurado, raiz_configurada
        esperar_erro(lambda: leg.planejar(base / "nao_existe.dat"), "não existe")
        print("OK: o arquivo do app, a pasta dele, data/ e qualquer lugar do projeto (arquivo ou saída) são recusados antes de "
              "abrir ou criar qualquer coisa; a mensagem manda usar uma pasta fora do projeto; fora dele passa.")

        linha("6) Aplicar de verdade (com a simulação refeita depois de uma resposta parcial)")
        antes = plano.antes
        depois_parcial = leg.simular(plano, {"S8": "Negado", "S17": "Negado"})
        assert depois_parcial["propostas_por_status"].get("Encerrada", 0) == 0 and depois_parcial["propostas_por_status"]["Reprovado"] == 1
        plano = leg.planejar(caminho)
        resumo = leg.aplicar(plano, decisoes)
        backups = backup_mod.listar_backups(caminho)
        assert [b.motivo for b in backups] == [backup_mod.MOTIVO_PRE_CONVERSAO] and resumo["backup"] == backups[0].caminho
        assert sha(resumo["backup"]) == hash_antes, "o backup é o arquivo de antes"
        from desktop.screens.usuarios_screen import _ROTULO_POR_MOTIVO

        assert leg.ROTULO_DO_BACKUP == "Antes de converter os dados antigos"
        assert _ROTULO_POR_MOTIVO[backup_mod.MOTIVO_PRE_CONVERSAO] == leg.ROTULO_DO_BACKUP, "o rótulo na lista de backups"
        propostas = bd.ler_propostas(caminho)
        vendas = bd.ler_vendas(caminho).set_index("ID_VENDA")
        assert list(propostas["STATUS"]) == STATUS_ESPERADOS, list(propostas["STATUS"])
        assert set(propostas["STATUS"]) <= set(propostas_mod.STATUS_OFICIAIS)
        assert (propostas["ID_VENDA"] != "").all() and propostas["ID_VENDA"].isin(vendas.index).all(), "nenhuma proposta sem venda"
        assert (propostas["ID_PROPOSTA"] != "").all() and propostas["ID_PROPOSTA"].is_unique
        assert len(propostas) == antes["propostas"] == 19, "nenhuma proposta apagada"
        assert round(float(propostas["VALOR (R$)"].sum()), 2) == antes["soma_valores"], "a soma dos valores não muda"
        assert len(vendas) == 9 and len(bd.ler_clientes(caminho)) == antes["clientes"]
        assert resumo["conversoes"] == 15 and resumo["vendas_novas"] == 7
        print("OK: backup 'pre-conversao' idêntico ao arquivo de antes; 17 propostas e a soma dos valores iguais; todas em vendas e com status oficial.")

        def venda_de(i):
            return vendas.loc[propostas.at[i, "ID_VENDA"]]

        maria = venda_de(0)
        assert propostas.loc[0:3, "ID_VENDA"].nunique() == 1 and maria["STATUS"] == v.VENDA_EM_ANDAMENTO
        assert set(v.fechadas_da_venda(maria["BANCO_ESCOLHIDO"])) == {propostas.at[0, "ID_PROPOSTA"], propostas.at[2, "ID_PROPOSTA"]}
        assert maria["EQUIPAMENTOS"] == "Cadeira X + Laser Y"
        assert venda_de(4)["STATUS"] == v.VENDA_NAO_EFETIVADA and propostas.at[4, "ID_VENDA"] == propostas.at[5, "ID_VENDA"]
        assert venda_de(6)["STATUS"] == v.VENDA_PERDIDA and propostas.at[6, "ID_VENDA"] != propostas.at[4, "ID_VENDA"]
        assert propostas.loc[7:11, "ID_VENDA"].nunique() == 1
        ana = venda_de(7)
        assert ana["STATUS"] == v.VENDA_EFETIVADA and v.fechadas_da_venda(ana["BANCO_ESCOLHIDO"]) == [propostas.at[7, "ID_PROPOSTA"]]
        assert venda_de(12)["STATUS"] == v.VENDA_AGUARDANDO and venda_de(16)["STATUS"] == v.VENDA_AGUARDANDO
        assert propostas.at[17, "ID_VENDA"] == propostas.at[18, "ID_VENDA"]
        assert venda_de(17)["STATUS"] == v.VENDA_PERDIDA and venda_de(17)["MOTIVO"] == "Todos os bancos negaram", \
            "a Encerrada respondida 'Negado' conta como negada na venda"
        assert propostas.at[13, "ID_VENDA"] == "V-X" and venda_de(13)["STATUS"] == v.VENDA_EM_ANDAMENTO, "fechar o banco recalcula a venda"
        assert v.fechadas_da_venda(venda_de(13)["BANCO_ESCOLHIDO"]) == ["P-X1"]
        assert venda_de(15)["STATUS"] == v.VENDA_EFETIVADA and v.fechadas_da_venda(venda_de(15)["BANCO_ESCOLHIDO"]) == ["P-Y1"]
        print("OK: Maria Em andamento com 2 bancos fechados; Não efetivado vira venda Não efetivada; só negadas = Perdida; Ana Efetivada; "
              "Garantia assinada fora da venda fechada na resposta 'fechar'; 'Assinado' sem fechar volta a Aprovado na resposta.")

        hist = bd.ler_historico(caminho)
        novos = hist.iloc[historico_antes:]
        motivo = f"conversão dos dados antigos em {date.today():%d/%m/%Y}"
        assert leg.motivo_do_historico() == motivo
        com_motivo = novos[novos["MOTIVO"] == motivo]
        convertidas = com_motivo[com_motivo["ID"].str.startswith("P") & (com_motivo["TIPO"] != v.TIPO_FECHAMENTO)]
        assert (novos["TIPO"] == v.TIPO_PROPOSTA).sum() == 0, "a conversao nao usa o TIPO das trocas de status do dia a dia"
        assert set(convertidas["TIPO"]) == {v.TIPO_CONVERSAO}
        assert len(convertidas) == 15, "uma linha por proposta convertida"
        assert not set(convertidas["ID"]) & {propostas.at[i, "ID_PROPOSTA"] for i in (12, 14, 15)}, "as que já eram oficiais não ganham linha"
        de_para = dict(zip(convertidas["ID"], zip(convertidas["DE"], convertidas["PARA"])))
        assert de_para[propostas.at[0, "ID_PROPOSTA"]] == ("Garantia Assinada", "Assinado")
        assert de_para[propostas.at[8, "ID_PROPOSTA"]] == ("Encerrada", "Negado")
        assert de_para[propostas.at[10, "ID_PROPOSTA"]] == ("", "Em Análise")
        assert de_para[propostas.at[16, "ID_PROPOSTA"]] == ("Assinado", "Aprovado")
        # o relogio: sem historico antes, a linha e datada da DATA da proposta (nunca de "agora")
        datas = dict(zip(propostas["ID_PROPOSTA"], propostas["DATA"]))
        assert all(pd.Timestamp(q) == pd.Timestamp(datas[i]) for i, q in zip(convertidas["ID"], convertidas["QUANDO"]))
        fechamentos = novos[novos["TIPO"] == v.TIPO_FECHAMENTO]
        assert list(fechamentos["ID"]) == ["P-X1"] and (novos["TIPO"] == v.TIPO_VENDA).sum() == 7
        mudanca_de_venda = novos[(novos["TIPO"] == v.TIPO_CONVERSAO) & (novos["ID"] == "V-X")]
        assert list(zip(mudanca_de_venda["DE"], mudanca_de_venda["PARA"])) == [(v.VENDA_AGUARDANDO, v.VENDA_EM_ANDAMENTO)]
        assert pd.Timestamp(fechamentos["QUANDO"].iloc[0]) == pd.Timestamp(datas["P-X1"]), "o fechamento: o relogio da proposta"
        assert pd.Timestamp(mudanca_de_venda["QUANDO"].iloc[0]) == pd.Timestamp(HOJE + timedelta(days=60)), "a venda: a criacao dela"
        assert len(novos) == 15 + 1 + 1 + 7, len(novos)
        # as vendas novas: o QUANDO e a DATA_CRIACAO dela
        criacao = dict(zip(vendas.index, vendas["DATA_CRIACAO"]))
        das_vendas = novos[(novos["TIPO"] == v.TIPO_VENDA)]
        assert all(pd.Timestamp(q) == pd.Timestamp(criacao[i]) for i, q in zip(das_vendas["ID"], das_vendas["QUANDO"]))
        print("OK: histórico: TIPO 'conversao' (uma linha por proposta convertida, com a data de hoje no motivo), datado de onde o relógio já contava.")

        relatorio_final, _ = leg.escrever_relatorios(plano, saida, resumo["depois"], resumo)
        assert "CONVERSÃO APLICADA" in relatorio_final.read_text(encoding="utf-8")
        assert resumo["depois"]["propostas_sem_venda"] == 0

        linha("7) Rodar de novo não acha mais nada")
        de_novo = leg.planejar(caminho)
        assert not de_novo.duvidas and de_novo.conversoes == 0 and de_novo.vendas_novas == 0 and not de_novo.problemas
        depois_hist = len(bd.ler_historico(caminho))
        leg.aplicar(de_novo, {})
        assert len(bd.ler_historico(caminho)) == depois_hist and list(bd.ler_propostas(caminho)["STATUS"]) == STATUS_ESPERADOS
        print("OK: sem dúvidas, sem conversões e sem vendas novas; aplicar de novo não muda o histórico.")

        linha("8) Se a conferência depois de gravar não bater, restaura o backup (cada tipo de erro)")
        gravar_original = bd.escrever_vendas_e_propostas

        def trocar(valor, outro):
            return outro if valor != outro else "Em Análise"

        def perde_proposta(p, v_, h):
            return p.iloc[:-1], v_, h

        def altera_valor(p, v_, h):
            p = p.copy()
            p.loc[p.index[0], "VALOR (R$)"] = float(p.loc[p.index[0], "VALOR (R$)"]) + 1
            return p, v_, h

        def troca_status_de_proposta(p, v_, h):
            p = p.copy()
            p.loc[p.index[0], "STATUS"] = trocar(p.loc[p.index[0], "STATUS"], "Negado")
            return p, v_, h

        def troca_status_de_venda(p, v_, h):
            v_ = v_.copy()
            v_.loc[v_.index[-1], "STATUS"] = trocar(v_.loc[v_.index[-1], "STATUS"], v.VENDA_PERDIDA)
            return p, v_, h

        def perde_historico(p, v_, h):
            return p, v_, h[:-1]

        corrupcoes = [("perde uma proposta", perde_proposta), ("altera um valor", altera_valor),
                      ("troca o status de uma proposta", troca_status_de_proposta),
                      ("troca o status de uma venda", troca_status_de_venda), ("perde uma linha do histórico", perde_historico)]
        for nome_do_erro, corromper in corrupcoes:
            caminho2 = nova_planilha(base, "conferencia")
            hash2 = sha(caminho2)
            plano2 = leg.planejar(caminho2)

            def gravar_errado(caminho_, *, propostas=None, vendas=None, historico_novo=None, clientes=None, _c=corromper):
                p_, v2, h_ = _c(propostas, vendas, historico_novo)
                gravar_original(caminho_, propostas=p_, vendas=v2, historico_novo=h_)

            bd.escrever_vendas_e_propostas = gravar_errado
            try:
                esperar_erro(lambda: leg.aplicar(plano2, decisoes), "A restauração deu certo")
            finally:
                bd.escrever_vendas_e_propostas = gravar_original
            assert sha(caminho2) == hash2, f"{nome_do_erro}: restaurado, igual ao de antes"
            assert backup_mod.MOTIVO_PRE_CONVERSAO in [b_.motivo for b_ in backup_mod.listar_backups(caminho2)]
            shutil.rmtree(caminho2.parent, ignore_errors=True)
        print("OK: gravou com uma proposta a menos / um valor, um status ou uma linha de histórico diferente: a "
              "conferência pegou, o arquivo voltou idêntico ao de antes e o erro explica.")

        linha("9) Se o arquivo mudou depois da simulação, recusa")
        caminho3 = nova_planilha(base, "mudou")
        plano3 = leg.planejar(caminho3)
        propostas3 = bd.ler_propostas(caminho3)[bd.PROPOSTAS_COLUNAS_EDITAVEIS].copy()
        propostas3.at[3, "OBSERVAÇÕES"] = "mexi"
        bd.escrever_propostas(caminho3, propostas3)
        hash3 = sha(caminho3)
        esperar_erro(lambda: leg.aplicar(plano3, decisoes), "O arquivo mudou desde a simulação")
        assert sha(caminho3) == hash3 and not backup_mod.listar_backups(caminho3)
        print("OK: arquivo diferente do da simulação: recusa sem gravar.")

        linha("10) O script: sem caminho recusa; o arquivo do app é recusado; simula sem gravar; aplica só com decisões")
        r = rodar_script()
        assert r.returncode == 2 and "the following arguments are required: arquivo" in r.stderr, (r.returncode, r.stderr[-300:])
        # dentro do projeto (arquivo que nem existe) e recusado; --saida dentro do projeto tambem, sem criar nada
        r = rodar_script(str(Path(config.DIRETORIO_BASE) / "qualquer_coisa.dat"))
        assert r.returncode == 1 and "dentro da pasta do projeto" in r.stderr, (r.returncode, r.stdout[-200:], r.stderr[-300:])
        saida_no_projeto = Path(config.DIRETORIO_BASE) / "_saida_que_nao_pode_existir"
        r = rodar_script(str(caminho), "--saida", str(saida_no_projeto))
        assert r.returncode == 1 and "dentro da pasta do projeto" in r.stderr and "pasta de saída" in r.stderr, (r.stderr[-300:])
        assert not saida_no_projeto.exists(), "nada foi criado dentro do projeto"
        caminho4 = nova_planilha(base, "script")
        hash4, saida4 = sha(caminho4), base / "saida_script"
        r = rodar_script(str(caminho4), "--saida", str(saida4))
        assert r.returncode == 0 and "SIMULAÇÃO" in r.stdout, (r.stdout[-300:], r.stderr[-300:])
        assert (saida4 / leg.ARQUIVO_RELATORIO).exists() and (saida4 / leg.ARQUIVO_DUVIDAS).exists()
        assert sha(caminho4) == hash4 and not backup_mod.listar_backups(caminho4), "simular não altera o arquivo"
        r = rodar_script(str(caminho4), "--aplicar", "--saida", str(saida4))
        assert r.returncode == 1 and "Faltam decisões" in r.stderr, (r.stdout[-200:], r.stderr[-300:])
        assert sha(caminho4) == hash4 and not backup_mod.listar_backups(caminho4), "--aplicar sem decisão não grava"
        arquivo_decisoes = base / "decisoes.json"
        arquivo_decisoes.write_text(json.dumps(decisoes), encoding="utf-8")
        r = rodar_script(str(caminho4), "--aplicar", "--decisoes", str(arquivo_decisoes), "--saida", str(saida4))
        assert r.returncode == 0 and "Convertido e conferido" in r.stdout, (r.stdout[-300:], r.stderr[-300:])
        assert list(bd.ler_propostas(caminho4)["STATUS"]) == STATUS_ESPERADOS
        assert [b.motivo for b in backup_mod.listar_backups(caminho4)] == [backup_mod.MOTIVO_PRE_CONVERSAO]
        assert "CONVERSÃO APLICADA" in (saida4 / leg.ARQUIVO_RELATORIO).read_text(encoding="utf-8")
        print("OK: sem caminho recusa; data/ e o arquivo do app recusados; simular não grava; --aplicar exige as decisões e então converte.")

        # o script desliga o Google ao ser carregado (antes de qualquer outra coisa), seja qual for a configuracao local
        config.SINCRONIZACAO_GOOGLE_ATIVADA = True
        try:
            especificacao = importlib.util.spec_from_file_location("_converter_legado_do_teste", SCRIPT)
            modulo = importlib.util.module_from_spec(especificacao)
            especificacao.loader.exec_module(modulo)
            assert config.SINCRONIZACAO_GOOGLE_ATIVADA is False, "o script tem que desligar a sincronização com o Google"
        finally:
            config.SINCRONIZACAO_GOOGLE_ATIVADA = False
        print("OK: carregar o script desliga a sincronização com o Google.")

        linha("11) Os dados reais e a isca não foram tocados")
        assert sha(isca) == hash_isca, "algo gravou no caminho padrão dos módulos em vez do arquivo recebido"
        assert not backup_mod.listar_backups(isca)
        if meta_real is not None:
            assert (real.stat().st_mtime_ns, real.stat().st_size) == meta_real, "o arquivo real mudou"
        print("OK: a planilha isca e o arquivo real (data/ ou o configurado) ficaram como estavam.")
        linha("TUDO OK")
    finally:
        nuvem._obter_cliente, sheets_sync._obter_cliente = rede_original
        fx.restaurar_modulos()
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    main()
