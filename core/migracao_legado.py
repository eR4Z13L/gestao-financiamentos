"""Converter os dados antigos para o jeito novo - feito UMA vez, numa COPIA dos dados, com backup e simulando antes
(plano 1.3). Sem interface: scripts/converter_legado.py e a linha de comando.

Dois passos, numa gravacao so:
1. juntar as propostas sem venda em vendas (core/migracao_vendas.py: as duvidas de la - varios equipamentos,
   propostas espacadas - entram aqui, e a resposta e "juntar" ou "separar");
2. converter o status de cada proposta para um dos oficiais (propostas.STATUS_OFICIAIS): Garantia assinada vira
   Assinado, Nota fiscal anexada vira NF enviada, Não efetivado vira Aprovado, e as grafias diferentes dos
   oficiais so sao normalizadas. "Encerrada" e qualquer texto desconhecido (ou vazio) viram DUVIDA, que o usuario
   responde com o status certo: nunca se chuta.

Alem disso, a conversao pergunta (nunca chuta): a proposta Encerrada ou de status desconhecido (resposta: um status
oficial; Assinado / NF enviada / Efetivado ja marcam o banco como fechado da venda), a proposta orfa (ID_VENDA
de venda que nao existe: juntar como proposta sem venda ou criar venda so para ela), "Não efetivado" numa venda que nao
esta Não efetivada, banco em Assinado / NF enviada / Efetivado que nao esta fechado na venda, e venda com
status de antes sem banco fechado (com banco fechado, o status se recalcula por eles).

Depois da conversao: nenhuma proposta fica sem venda, nenhum status fica fora dos oficiais, nenhum banco nao fechado
fica em Assinado / NF enviada / Efetivado e o total de propostas e a soma dos valores continuam iguais.
Nenhuma proposta ou venda e apagada. O HISTORICO ganha uma linha por conversao (TIPO "conversao", que o "voltar"
ignora) datada de onde o relogio de cada proposta ja contava, para nunca zerar "esperando ha N dias".

Nunca roda sobre os dados do app nem dentro da pasta do projeto (o repositorio e publico): o arquivo e a pasta de
saida sao sempre passados de forma explicita e este modulo recusa os dois se estiverem em config.DIRETORIO_BASE.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

import pandas as pd

import config
from core import backup as backup_mod
from core import data_store as bd
from core import migracao_vendas as migracao_vendas_mod
from core import propostas as propostas_mod
from core import vendas as vendas_mod
from core.validators import apenas_digitos

MOTIVO_NO_HISTORICO = "conversão dos dados antigos"
ROTULO_DO_BACKUP = "Antes de converter os dados antigos"

ARQUIVO_RELATORIO = "relatorio_conversao.md"
ARQUIVO_DUVIDAS = "duvidas_conversao.json"

TIPO_JUNTAR_VARIOS_EQUIPAMENTOS = migracao_vendas_mod.DUVIDA_VARIOS_EQUIPAMENTOS
TIPO_JUNTAR_ESPACADA = migracao_vendas_mod.DUVIDA_ESPACADA
TIPO_ENCERRADA = "encerrada"
TIPO_STATUS_DESCONHECIDO = "status_desconhecido"
TIPO_FECHADO_SEM_FECHAR = "fechado_sem_fechar"
TIPO_ORFA = "proposta_orfa"
TIPO_VENDA_STATUS_ANTIGO = "venda_status_antigo"
TIPO_NAO_EFETIVADO_EM_VENDA = "nao_efetivado_em_venda"

RESPOSTA_JUNTAR = "juntar"
RESPOSTA_SEPARAR = "separar"
RESPOSTA_FECHAR = "fechar"
RESPOSTA_ORFA_JUNTAR = "juntar como proposta sem venda"
RESPOSTA_ORFA_SOZINHA = "criar venda só para ela"
RESPOSTA_VENDA_NAO_EFETIVADA = "venda Não efetivada"
RESPOSTA_SO_APROVADO = "só Aprovado"

# o status desconhecido aceita qualquer um dos oficiais; uma resposta de banco fechado (Assinado, NF enviada,
# Efetivado) ja marca o banco como fechado da venda (nunca fica sem saida)
_RESPOSTAS_DE_STATUS = tuple(propostas_mod.STATUS_OFICIAIS)
_RESPOSTAS_DE_VENDA_SEM_BANCO = (vendas_mod.VENDA_AGUARDANDO, vendas_mod.VENDA_PERDIDA, vendas_mod.VENDA_NAO_EFETIVADA)
_RESPOSTAS_DE_ENCERRADA = (propostas_mod.STATUS_APROVADO, propostas_mod.STATUS_NEGADO, propostas_mod.STATUS_EM_ANALISE)

# status depois do fechamento do banco: so um banco FECHADO pode estar neles
_STATUS_DE_BANCO_FECHADO = {propostas_mod.STATUS_ASSINADO, propostas_mod.STATUS_NOTA_ENVIADA, propostas_mod.STATUS_EFETIVADO}

# (texto normalizado) -> (status novo, grafia antiga canonica). A grafia antiga e a que o resto do app reconhece como
# etapa: e ela que a juncao em vendas le para saber quais bancos estao FECHADOS (Garantia assinada, Nota fiscal
# anexada, Efetivado). Assinado / NF enviada (novos) NAO fecham banco: se aparecerem sem venda viram duvida.
_TABELA = {
    "garantia assinada": (propostas_mod.STATUS_ASSINADO, propostas_mod.STATUS_GARANTIA_ASSINADA),
    "nota fiscal anexada": (propostas_mod.STATUS_NOTA_ENVIADA, propostas_mod.STATUS_NF_ANEXADA),
    "nao efetivado": (propostas_mod.STATUS_APROVADO, propostas_mod.STATUS_NAO_EFETIVADO),
    "efetivado": (propostas_mod.STATUS_EFETIVADO, propostas_mod.STATUS_EFETIVADO),
    "efetivada": (propostas_mod.STATUS_EFETIVADO, propostas_mod.STATUS_EFETIVADO),
    "aprovado": (propostas_mod.STATUS_APROVADO, propostas_mod.STATUS_APROVADO),
    "aprovada": (propostas_mod.STATUS_APROVADO, propostas_mod.STATUS_APROVADO),
    "em analise": (propostas_mod.STATUS_EM_ANALISE, propostas_mod.STATUS_EM_ANALISE),
    "pre-aprovado": (propostas_mod.STATUS_PRE_APROVADO, propostas_mod.STATUS_PRE_APROVADO),
    "pre aprovado": (propostas_mod.STATUS_PRE_APROVADO, propostas_mod.STATUS_PRE_APROVADO),
    "negado": (propostas_mod.STATUS_NEGADO, propostas_mod.STATUS_NEGADO),
    "negada": (propostas_mod.STATUS_NEGADO, propostas_mod.STATUS_NEGADO),
    "assinado": (propostas_mod.STATUS_ASSINADO, propostas_mod.STATUS_ASSINADO),
    "nf enviada": (propostas_mod.STATUS_NOTA_ENVIADA, propostas_mod.STATUS_NOTA_ENVIADA),
    "nota fiscal enviada": (propostas_mod.STATUS_NOTA_ENVIADA, propostas_mod.STATUS_NOTA_ENVIADA),  # o nome de antes (20/10)
}
_TEXTO_DE_ENCERRADA = "encerrada"


class ErroConversao(Exception):
    """A conversao recusou (a mensagem diz o que fazer) - nada foi gravado, ou o arquivo foi restaurado."""


def _normalizar(texto) -> str:
    sem_acento = "".join(c for c in unicodedata.normalize("NFD", str(texto or "")) if unicodedata.category(c) != "Mn")
    return " ".join(sem_acento.casefold().split())


def converter_status(status) -> str | None:
    """O status oficial para um status antigo (sem diferenciar maiusculas, acentos e espacos) ou None se a tabela
    nao cobre (Encerrada, texto desconhecido, vazio)."""
    achado = _TABELA.get(_normalizar(status))
    return achado[0] if achado else None


@dataclass(frozen=True)
class Duvida:
    chave: str
    tipo: str
    cliente: str
    pergunta: str
    opcoes: tuple[str, ...]  # as respostas aceitas
    detalhe: str = ""  # a(s) proposta(s) a que ela se refere, para quem responde


@dataclass
class PlanoConversao:
    caminho: Path
    impressao: str  # sha256 do arquivo no momento do plano: aplicar recusa se o arquivo mudou
    plano_vendas: migracao_vendas_mod.Plano
    duvidas: list[Duvida]
    problemas: list[str]  # o que nenhuma resposta resolve (impede --aplicar)
    antes: dict
    depois: dict  # a simulacao (duvida sem resposta: venda separada, status como esta)
    conversoes: int  # propostas que mudam de status (simulacao)
    vendas_novas: int


@dataclass
class Resultado:
    propostas: pd.DataFrame
    vendas: pd.DataFrame
    historico: list[dict]
    conversoes: int
    vendas_novas: int
    pendentes: list[Duvida] = field(default_factory=list)  # duvidas (banco fechado sem fechar, venda sem banco) sem resposta
    duvidas_fixas: list[Duvida] = field(default_factory=list)  # status, orfas e Nao efetivado em venda: nao dependem das respostas


@dataclass(frozen=True)
class DadosAntigos:
    """O que a planilha ainda tem do jeito antigo (a guarda do app ao abrir)."""
    sem_venda: int  # propostas que nao estao em nenhuma venda
    status_fora_da_lista: int  # propostas com status que nao e um dos oficiais (inclui o vazio)

    def __bool__(self) -> bool:
        return bool(self.sem_venda or self.status_fora_da_lista)

    def texto(self) -> str:
        partes = []
        if self.sem_venda:
            partes.append(f"{self.sem_venda} proposta(s) que não estão em nenhuma venda")
        if self.status_fora_da_lista:
            partes.append(f"{self.status_fora_da_lista} proposta(s) com status fora da lista do app")
        return (
            "Esta planilha ainda tem dados de uma versão antiga: " + " e ".join(partes) + ".\n\n"
            "É preciso rodar a conversão dos dados antigos (scripts/converter_legado.py) antes de usar o app "
            "normalmente. O app abre assim mesmo, e essas propostas aparecem em Todas as Propostas com o status "
            "como está, mas as vendas e os totais não as contam direito até a conversão."
        )


def contar_dados_antigos(caminho: Path) -> DadosAntigos:
    """Quantas propostas de `caminho` ainda estao do jeito antigo. So le."""
    _, propostas, vendas = _ler(Path(caminho))
    sem_venda = int((~propostas["ID_VENDA"].isin(set(vendas["ID_VENDA"]))).sum())
    fora = int((~propostas["STATUS"].isin(propostas_mod.STATUS_OFICIAIS)).sum())
    return DadosAntigos(sem_venda, fora)


def _impressao(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def _dentro_de(pasta: Path, resolvido: Path) -> bool:
    return pasta == resolvido or pasta in resolvido.parents


def exigir_fora_do_projeto(caminho: Path, o_que: str) -> Path:
    """Recusa qualquer lugar dentro da pasta do projeto (config.DIRETORIO_BASE): o repositorio e PUBLICO, e dado de
    cliente (a copia, o relatorio, as duvidas) nunca pode ficar perto do codigo. Nao precisa existir. Devolve o
    caminho resolvido."""
    resolvido = Path(caminho).resolve()
    base = Path(config.DIRETORIO_BASE).resolve()
    if _dentro_de(base, resolvido):
        raise ErroConversao(
            f"Recusado: {o_que} '{resolvido}' fica dentro da pasta do projeto ({base}). O repositório do projeto é "
            "público: use uma pasta FORA do projeto (por exemplo, em Documentos), para que nenhum dado de cliente "
            "fique perto do código."
        )
    return resolvido


def exigir_arquivo_permitido(caminho: Path) -> Path:
    """Recusa o arquivo do app (config.CAMINHO_XLSX), a pasta dele, data/, data_dev_oficial/ e tudo dentro da pasta do
    projeto: o conversor so roda sobre uma COPIA fora do projeto. Nao abre o arquivo. Devolve o caminho resolvido."""
    resolvido = Path(caminho).resolve()
    proibidos = [Path(config.CAMINHO_XLSX).resolve()]
    pastas = [Path(config.CAMINHO_XLSX).resolve().parent, Path(config.DIRETORIO_DADOS).resolve(),
              (Path(config.DIRETORIO_BASE) / "data").resolve(), (Path(config.DIRETORIO_BASE) / "data_dev_oficial").resolve()]
    if resolvido in proibidos or any(_dentro_de(pasta, resolvido) for pasta in pastas):
        raise ErroConversao(
            f"Recusado: '{resolvido.name}' é um dos arquivos de dados do app. Rode o conversor numa CÓPIA, "
            "em outra pasta, fora do projeto."
        )
    exigir_fora_do_projeto(resolvido, "o arquivo")
    if not resolvido.is_file():
        raise ErroConversao(f"O arquivo '{resolvido}' não existe.")
    return resolvido


def exigir_saida_permitida(pasta: Path) -> Path:
    """A pasta dos relatorios (nomes de clientes, dados de propostas): fora do projeto, como o arquivo."""
    return exigir_fora_do_projeto(pasta, "a pasta de saída")


def motivo_do_historico(hoje: datetime | None = None) -> str:
    return f"{MOTIVO_NO_HISTORICO} em {(hoje or datetime.now()):%d/%m/%Y}"


def _contagem(clientes: pd.DataFrame, propostas: pd.DataFrame, vendas: pd.DataFrame) -> dict:
    ids_vendas = set(vendas["ID_VENDA"])
    por_status = propostas["STATUS"].map(lambda s: s or "(vazio)").value_counts().to_dict()
    return {
        "clientes": len(clientes),
        "propostas": len(propostas),
        "soma_valores": round(float(pd.to_numeric(propostas["VALOR (R$)"], errors="coerce").sum()), 2),
        "vendas": len(vendas),
        "propostas_sem_venda": int((~propostas["ID_VENDA"].isin(ids_vendas)).sum()),
        "propostas_por_status": dict(sorted(por_status.items())),
        "vendas_por_status": dict(sorted(vendas["STATUS"].map(lambda s: s or "(vazio)").value_counts().to_dict().items())),
    }


def _ler(caminho: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    clientes = bd.ler_clientes(caminho)
    propostas = bd.ler_propostas(caminho, clientes)
    return clientes, propostas, bd.ler_vendas(caminho)


def _descrever(linha: pd.Series) -> str:
    data = pd.Timestamp(linha["DATA"]).strftime("%d/%m/%Y") if pd.notna(linha["DATA"]) else "sem data"
    valor = linha["VALOR (R$)"]
    valor = f"R$ {valor:,.2f}" if pd.notna(valor) else "sem valor"
    return f"{linha['BANCO'] or 'sem banco'} · {linha['EQUIPAMENTO'] or 'sem equipamento'} · {data} · {valor}"


def _duvidas_de_status(propostas: pd.DataFrame) -> dict[int, Duvida]:
    """Uma duvida por proposta cujo status a tabela nao cobre (Encerrada, desconhecido ou vazio), pela posicao."""
    duvidas = {}
    for indice, linha in propostas.iterrows():
        bruto = linha["STATUS"]
        if converter_status(bruto) is not None:
            continue
        encerrada = _normalizar(bruto) == _TEXTO_DE_ENCERRADA
        tipo = TIPO_ENCERRADA if encerrada else TIPO_STATUS_DESCONHECIDO
        if encerrada:
            pergunta = "Esta proposta estava Encerrada (outra do mesmo negócio foi efetivada). Qual foi a resposta deste banco?"
        else:
            pergunta = (f"O status {bruto!r} não é de nenhum que o app conhece. Qual é o status certo?" if bruto
                        else "Esta proposta está sem status. Qual é o status certo?")
        duvidas[int(indice)] = Duvida(
            f"S{int(indice)}", tipo, linha["CLIENTE"], pergunta,
            _RESPOSTAS_DE_ENCERRADA if encerrada else _RESPOSTAS_DE_STATUS, _descrever(linha),
        )
    return duvidas


def _orfas(propostas: pd.DataFrame, vendas: pd.DataFrame) -> list[int]:
    """As propostas com ID_VENDA de uma venda que nao existe."""
    ids = set(vendas["ID_VENDA"])
    return [int(i) for i in propostas.index[(propostas["ID_VENDA"] != "") & ~propostas["ID_VENDA"].isin(ids)]]


def _duvidas_de_orfas(propostas: pd.DataFrame, orfas: list[int]) -> dict[int, Duvida]:
    return {
        i: Duvida(
            f"O{i}", TIPO_ORFA, propostas.at[i, "CLIENTE"],
            f"Esta proposta aponta para a venda {propostas.at[i, 'ID_VENDA']!r}, que não existe. Juntar com as outras propostas "
            "sem venda do cliente (a conversão decide as vendas), ou criar uma venda só para ela?",
            (RESPOSTA_ORFA_JUNTAR, RESPOSTA_ORFA_SOZINHA), _descrever(propostas.loc[i]),
        )
        for i in orfas
    }


def _duvidas_de_nao_efetivado_em_venda(propostas: pd.DataFrame, vendas: pd.DataFrame) -> dict[int, Duvida]:
    """Proposta "Não efetivado" que JA esta numa venda que nao esta Não efetivada: o status antigo dizia que o cliente
    desistiu, a venda nao. O app nao decide: a venda vira Não efetivada, ou a proposta fica so Aprovado."""
    status_da_venda = dict(zip(vendas["ID_VENDA"], vendas["STATUS"]))
    duvidas = {}
    for indice, linha in propostas.iterrows():
        id_venda = linha["ID_VENDA"]
        if id_venda not in status_da_venda or _normalizar(linha["STATUS"]) != "nao efetivado":
            continue
        if status_da_venda[id_venda] == vendas_mod.VENDA_NAO_EFETIVADA:
            continue
        duvidas[int(indice)] = Duvida(
            f"N{int(indice)}", TIPO_NAO_EFETIVADO_EM_VENDA, linha["CLIENTE"],
            f"Esta proposta estava Não efetivado, mas a venda dela está {status_da_venda[id_venda]}. "
            "A venda deve virar Não efetivada, ou a proposta fica só Aprovado?",
            (RESPOSTA_VENDA_NAO_EFETIVADA, RESPOSTA_SO_APROVADO), _descrever(linha),
        )
    return duvidas


def _escolher(opcoes: tuple[str, ...], resposta) -> str | None:
    """A opcao a que `resposta` se refere (sem diferenciar maiusculas, acentos e espacos) ou None."""
    for opcao in opcoes:
        if _normalizar(opcao) == _normalizar(resposta):
            return opcao
    return None


def _validar_decisoes(duvidas: list[Duvida], decisoes: dict[str, str], completo: bool) -> dict[str, str]:
    """As decisoes com cada resposta no texto canonico. Chave desconhecida ou resposta fora das opcoes e erro (uma
    decisao velha, de outro arquivo, nunca passa em silencio); com `completo`, falta de resposta tambem."""
    por_chave = {d.chave: d for d in duvidas}
    certas = {}
    for chave, resposta in decisoes.items():
        if chave not in por_chave:
            raise ErroConversao(f"A decisão '{chave}' não corresponde a nenhuma dúvida deste arquivo (decisões de outro arquivo?).")
        escolhida = _escolher(por_chave[chave].opcoes, resposta)
        if escolhida is None:
            raise ErroConversao(f"Resposta inválida para a dúvida {chave}: {resposta!r}. Use uma de: {', '.join(por_chave[chave].opcoes)}.")
        certas[chave] = escolhida
    faltando = [d.chave for d in duvidas if d.chave not in certas]
    if completo and faltando:
        raise ErroConversao(f"Faltam decisões para {len(faltando)} dúvida(s): {', '.join(faltando)}. Nada foi gravado.")
    return certas


def _duvidas_de_vendas(plano: migracao_vendas_mod.Plano) -> list[Duvida]:
    return [
        Duvida(d.chave, d.tipo, d.cliente, d.pergunta, (RESPOSTA_JUNTAR, RESPOSTA_SEPARAR),
               f"CPF/CNPJ {d.cpf} · {d.juntar} = '{RESPOSTA_JUNTAR}', {d.separar} = '{RESPOSTA_SEPARAR}'")
        for d in plano.duvidas
    ]


def _plano_de_vendas(caminho: Path) -> migracao_vendas_mod.Plano:
    """O plano de juntar em vendas: as sem venda E as orfas (ID_VENDA de venda que nao existe), que entram no mesmo
    plano como se nao tivessem venda."""
    _, completo, vendas = _ler(caminho)
    entram = completo.copy()
    entram.loc[_orfas(completo, vendas), "ID_VENDA"] = ""
    return migracao_vendas_mod.planejar(caminho, propostas=entram)


def _py(momento) -> datetime:
    return pd.Timestamp(momento).to_pydatetime()


def _construir(caminho: Path, plano_vendas: migracao_vendas_mod.Plano, decisoes: dict[str, str]) -> Resultado:
    """Faz as conversoes em memoria, sem gravar. Duvida sem decisao: venda separada / status como esta / orfa junto
    com as outras."""
    clientes, completo, vendas = _ler(caminho)
    ultimas = vendas_mod._ultimas_mudancas(bd.ler_historico(caminho))
    propostas = completo[bd.PROPOSTAS_COLUNAS_EDITAVEIS].copy()
    originais = propostas["STATUS"].copy()
    orfas = _orfas(completo, vendas)
    sem_venda = [int(i) for i in propostas.index[propostas["ID_VENDA"] == ""]]
    if sorted(sem_venda + orfas) != sorted(plano_vendas.indices_sem_venda):
        raise ErroConversao("As propostas mudaram desde que o plano foi feito. Simule de novo.")
    duvidas_status = _duvidas_de_status(completo)
    duvidas_orfas = _duvidas_de_orfas(completo, orfas)
    duvidas_nao_efetivado = _duvidas_de_nao_efetivado_em_venda(completo, vendas)
    fixas = [*duvidas_status.values(), *duvidas_orfas.values(), *duvidas_nao_efetivado.values()]

    # 1) o status final de cada proposta. Para juntar em vendas, o banco FECHADO se reconhece pela grafia antiga; uma
    # resposta Assinado / NF enviada / Efetivado a uma duvida ja marca o banco como fechado (no passo 3).
    finais, para_agrupar, fechar_de_vez = {}, propostas.copy(), set()
    for indice in propostas.index:
        bruto = originais[indice]
        achado = _TABELA.get(_normalizar(bruto))
        if achado:
            finais[indice] = achado[0]
            para_agrupar.at[indice, "STATUS"] = achado[1]
            continue
        resposta = decisoes.get(duvidas_status[int(indice)].chave)
        finais[indice] = resposta or bruto
        para_agrupar.at[indice, "STATUS"] = resposta or bruto
        if resposta in _STATUS_DE_BANCO_FECHADO:
            fechar_de_vez.add(indice)

    # 2) as vendas novas (orfa "so para ela": sai do grupo e ganha o seu)
    sozinhas = {i for i in orfas if decisoes.get(duvidas_orfas[i].chave) == RESPOSTA_ORFA_SOZINHA}
    plano = plano_vendas
    if sozinhas:
        grupos = [replace(g, indices=[i for i in g.indices if i not in sozinhas]) for g in plano_vendas.grupos]
        for i in sorted(sozinhas):
            data = pd.to_datetime(completo.at[i, "DATA"], errors="coerce")
            grupos.append(migracao_vendas_mod.Grupo(
                f"O{i}", apenas_digitos(completo.at[i, "CPF"]), str(completo.at[i, "EQUIPAMENTO"] or "").strip(), [i], data, data))
        plano = replace(plano_vendas, grupos=grupos)
    agora = datetime.now().replace(microsecond=0)
    motivo = motivo_do_historico(agora)
    maquina = vendas_mod.sheets_sync.nome_desta_maquina()
    juncao = {d.chave: decisoes.get(d.chave) == RESPOSTA_JUNTAR for d in plano_vendas.duvidas}
    n_vendas_antes = len(vendas)
    montado = migracao_vendas_mod.montar(
        plano, juncao, para_agrupar, vendas,
        quando=lambda criacao: _py(criacao) if pd.notna(criacao) else agora)
    propostas = montado["propostas"]
    vendas = montado["vendas"]
    historico = list(montado["historico"])

    def relogio_da_proposta(indice) -> datetime:
        # o momento de onde o relogio da proposta (dias esperando, "parado em...") ja contava: a ultima mudanca dela no
        # historico ou, sem ela, a DATA. Assim a conversao nunca zera o tempo de ninguem.
        id_original = completo.at[indice, "ID_PROPOSTA"]
        if id_original and id_original in ultimas:
            return _py(ultimas[id_original])
        data = completo.at[indice, "DATA"]
        return _py(data) if pd.notna(data) else agora

    def relogio_da_venda(linha) -> datetime:
        id_venda, criacao = vendas.at[linha, "ID_VENDA"], vendas.at[linha, "DATA_CRIACAO"]
        if id_venda in ultimas:
            return _py(ultimas[id_venda])
        return _py(criacao) if pd.notna(criacao) else agora

    def id_da_proposta(indice) -> str:
        if not propostas.at[indice, "ID_PROPOSTA"]:
            propostas.at[indice, "ID_PROPOSTA"] = vendas_mod.novo_id("P")
        return propostas.at[indice, "ID_PROPOSTA"]

    def linha_da_venda(id_venda: str) -> int:
        return int(vendas.index[vendas["ID_VENDA"] == id_venda][0])

    def registrar_venda(linha, antigo: str, novo: str) -> None:
        vendas.at[linha, "STATUS"] = novo
        historico.append({"QUANDO": relogio_da_venda(linha), "TIPO": vendas_mod.TIPO_CONVERSAO, "ID": vendas.at[linha, "ID_VENDA"],
                          "DE": antigo, "PARA": novo, "MOTIVO": motivo, "COMPUTADOR": maquina})

    for indice in propostas.index:
        propostas.at[indice, "STATUS"] = finais[indice]

    # 3) banco em Assinado / NF enviada / Efetivado que nao esta fechado na venda
    pendentes = []
    for indice in propostas.index:
        status = propostas.at[indice, "STATUS"]
        if status not in _STATUS_DE_BANCO_FECHADO:
            continue
        id_proposta = id_da_proposta(indice)
        id_venda = propostas.at[indice, "ID_VENDA"]
        if not (vendas["ID_VENDA"] == id_venda).any():
            continue
        linha = linha_da_venda(id_venda)
        if id_proposta in vendas_mod.fechadas_da_venda(vendas.at[linha, "BANCO_ESCOLHIDO"]):
            continue
        duvida = Duvida(
            f"F{int(indice)}", TIPO_FECHADO_SEM_FECHAR, completo.at[indice, "CLIENTE"],
            f"Esta proposta está {status}, mas o banco não está marcado como fechado na venda. "
            "Marcar como fechado, ou voltar para Aprovado?",
            (RESPOSTA_FECHAR, propostas_mod.STATUS_APROVADO), _descrever(completo.loc[indice]),
        )
        resposta = RESPOSTA_FECHAR if indice in fechar_de_vez else decisoes.get(duvida.chave)
        if resposta is None:
            pendentes.append(duvida)
        elif resposta == RESPOSTA_FECHAR:
            fechadas = vendas_mod.fechadas_da_venda(vendas.at[linha, "BANCO_ESCOLHIDO"]) + [id_proposta]
            vendas.at[linha, "BANCO_ESCOLHIDO"] = ";".join(fechadas)
            historico.append({"QUANDO": relogio_da_proposta(indice), "TIPO": vendas_mod.TIPO_FECHAMENTO, "ID": id_proposta,
                              "DE": "", "PARA": vendas_mod.FECHADA, "MOTIVO": motivo, "COMPUTADOR": maquina})
            antigo = vendas.at[linha, "STATUS"]
            if antigo not in vendas_mod.VENDA_MANUAL:
                da_venda = propostas[propostas["ID_VENDA"] == id_venda].set_index("ID_PROPOSTA")["STATUS"]
                novo = vendas_mod.status_calculado([da_venda[i] for i in fechadas if i in da_venda.index])
                if novo != antigo:
                    registrar_venda(linha, antigo, novo)
        else:
            propostas.at[indice, "STATUS"] = propostas_mod.STATUS_APROVADO

    # 4) "Não efetivado" numa venda que ja existia: a resposta pode virar a venda Não efetivada
    for indice, duvida in duvidas_nao_efetivado.items():
        if decisoes.get(duvida.chave) == RESPOSTA_VENDA_NAO_EFETIVADA:
            linha = linha_da_venda(propostas.at[indice, "ID_VENDA"])
            antigo = vendas.at[linha, "STATUS"]
            if antigo != vendas_mod.VENDA_NAO_EFETIVADA:
                registrar_venda(linha, antigo, vendas_mod.VENDA_NAO_EFETIVADA)

    # 5) venda com status de antes (Banco escolhido, Nota fiscal...): recalcula pelos bancos fechados (modelo B); sem
    # nenhum banco fechado, vira duvida
    nomes = dict(zip(completo["CPF"].map(apenas_digitos), completo["CLIENTE"]))
    for linha in range(n_vendas_antes):
        antigo = vendas.at[linha, "STATUS"]
        if antigo in vendas_mod.STATUS_DA_VENDA:
            continue
        id_venda = vendas.at[linha, "ID_VENDA"]
        da_venda = propostas[propostas["ID_VENDA"] == id_venda]
        por_id = dict(zip(da_venda["ID_PROPOSTA"], da_venda["STATUS"]))
        fechadas = [i for i in vendas_mod.fechadas_da_venda(vendas.at[linha, "BANCO_ESCOLHIDO"]) if i in por_id]
        if fechadas:
            novo = vendas_mod.status_calculado([por_id[i] for i in fechadas])
        else:
            duvida = Duvida(
                f"V{linha}", TIPO_VENDA_STATUS_ANTIGO, nomes.get(apenas_digitos(vendas.at[linha, "CPF"]), ""),
                f"A venda {vendas.at[linha, 'EQUIPAMENTOS'] or id_venda!r} está com o status {antigo or '(vazio)'!r}, que não existe mais, "
                "e não tem banco fechado para calcular. Qual é o status dela?",
                _RESPOSTAS_DE_VENDA_SEM_BANCO, f"Venda {id_venda}",
            )
            novo = decisoes.get(duvida.chave)
            if novo is None:
                pendentes.append(duvida)
                continue
        registrar_venda(linha, antigo, novo)

    conversoes = 0
    for indice in propostas.index:
        if propostas.at[indice, "STATUS"] != originais[indice]:
            conversoes += 1
            historico.append({"QUANDO": relogio_da_proposta(indice), "TIPO": vendas_mod.TIPO_CONVERSAO,
                              "ID": id_da_proposta(indice), "DE": originais[indice], "PARA": propostas.at[indice, "STATUS"],
                              "MOTIVO": motivo, "COMPUTADOR": maquina})
    return Resultado(propostas, vendas, historico, conversoes, montado["vendas_novas"], pendentes, fixas)


def _problemas(caminho: Path) -> list[str]:
    """O que impede a conversao e nenhuma resposta resolve: dado quebrado que alguem precisa olhar."""
    _, _, vendas = _ler(caminho)
    problemas = []
    if vendas["ID_VENDA"].duplicated().any():
        problemas.append("Há ID_VENDA repetido na aba VENDAS.")
    return problemas


def planejar(caminho: Path) -> PlanoConversao:
    """Simula a conversao do arquivo `caminho` sem gravar nada: as duvidas, o antes e o depois."""
    caminho = exigir_arquivo_permitido(caminho)
    impressao = _impressao(caminho)
    plano_vendas = _plano_de_vendas(caminho)
    resultado = _construir(caminho, plano_vendas, {})
    clientes, propostas, vendas = _ler(caminho)
    duvidas = _duvidas_de_vendas(plano_vendas) + resultado.duvidas_fixas + resultado.pendentes
    # a simulacao sem respostas deixa o status das duvidas como esta: o "depois" mostra o que ainda falta responder
    depois = _contagem(clientes, resultado.propostas, resultado.vendas)
    return PlanoConversao(caminho, impressao, plano_vendas, duvidas, _problemas(caminho),
                          _contagem(clientes, propostas, vendas), depois, resultado.conversoes, resultado.vendas_novas)


def simular(plano: PlanoConversao, decisoes: dict[str, str] | None = None) -> dict:
    """O "depois" com as `decisoes` que ja existem (as que faltam ficam como na simulacao)."""
    certas = _validar_decisoes(plano.duvidas, decisoes or {}, completo=False)
    resultado = _construir(plano.caminho, plano.plano_vendas, certas)
    return _contagem(_ler(plano.caminho)[0], resultado.propostas, resultado.vendas)


def _problemas_do_resultado(resultado: Resultado, antes: dict) -> list[str]:
    """As garantias da conversao, conferidas no resultado ANTES de gravar (e de novo no arquivo gravado)."""
    problemas = []
    ids_vendas = set(resultado.vendas["ID_VENDA"])
    sem_venda = int((~resultado.propostas["ID_VENDA"].isin(ids_vendas)).sum())
    if sem_venda:
        problemas.append(f"{sem_venda} proposta(s) ficariam sem venda")
    fora = int((~resultado.propostas["STATUS"].isin(propostas_mod.STATUS_OFICIAIS)).sum())
    if fora:
        problemas.append(f"{fora} proposta(s) ficariam com status fora da lista oficial")
    vendas_fora = int((~resultado.vendas["STATUS"].isin(vendas_mod.STATUS_DA_VENDA)).sum())
    if vendas_fora:
        problemas.append(f"{vendas_fora} venda(s) ficariam com status que não existe mais")
    fechadas = {i for texto in resultado.vendas["BANCO_ESCOLHIDO"] for i in vendas_mod.fechadas_da_venda(texto)}
    soltas = resultado.propostas[resultado.propostas["STATUS"].isin(_STATUS_DE_BANCO_FECHADO)
                                 & ~resultado.propostas["ID_PROPOSTA"].isin(fechadas)]
    if len(soltas):
        problemas.append(f"{len(soltas)} proposta(s) ficariam em Assinado, NF enviada ou Efetivado sem banco fechado")
    if len(resultado.propostas) != antes["propostas"]:
        problemas.append("o total de propostas mudaria")
    soma = round(float(pd.to_numeric(resultado.propostas["VALOR (R$)"], errors="coerce").sum()), 2)
    if soma != antes["soma_valores"]:
        problemas.append("a soma dos valores mudaria")
    if len(resultado.vendas) != antes["vendas"] + resultado.vendas_novas:
        problemas.append("o total de vendas não bate")
    return problemas


def _conferir_gravacao(caminho: Path, resultado: Resultado, antes: dict, historico_antes: int) -> list[str]:
    """Le o arquivo gravado e confere com o que era para ter sido gravado."""
    clientes, propostas, vendas = _ler(caminho)
    depois = _contagem(clientes, propostas, vendas)
    esperado = _contagem(clientes, resultado.propostas, resultado.vendas)
    divergencias = []
    if depois["clientes"] != antes["clientes"]:
        divergencias.append("o número de clientes mudou")
    for chave, texto in (("propostas", "o total de propostas"), ("soma_valores", "a soma dos valores"), ("vendas", "o total de vendas"),
                         ("propostas_por_status", "as propostas por status"), ("vendas_por_status", "as vendas por status")):
        if depois[chave] != esperado[chave]:
            divergencias.append(f"{texto} gravado não bate com o esperado")
    if depois["propostas_sem_venda"]:
        divergencias.append(f"{depois['propostas_sem_venda']} proposta(s) sem venda depois de gravar")
    if len(bd.ler_historico(caminho)) != historico_antes + len(resultado.historico):
        divergencias.append("o histórico gravado não bate com o esperado")
    return divergencias


def _restaurar_e_explicar(caminho: Path, backup: Path, erro: Exception) -> ErroConversao:
    """Qualquer erro depois do backup: tenta restaurar e devolve o erro dizendo o nome do backup e se deu certo."""
    motivo = str(erro) if isinstance(erro, ErroConversao) else f"{type(erro).__name__}: {erro}"
    try:
        backup_mod.restaurar_backup(backup, caminho)
        igual = _impressao(caminho) == hashlib.sha256(backup.read_bytes()).hexdigest()
        situacao = ("A restauração deu certo: o arquivo voltou idêntico ao backup." if igual else
                    "A restauração rodou, MAS o arquivo NÃO ficou igual ao backup: confira o arquivo.")
    except Exception as exc_restaurar:
        situacao = (f"A RESTAURAÇÃO FALHOU ({type(exc_restaurar).__name__}: {exc_restaurar}): o arquivo pode estar alterado; "
                    "restaure o backup à mão.")
    return ErroConversao(f"{motivo}\nBackup: {backup.name}. {situacao}")


def aplicar(plano: PlanoConversao, decisoes: dict[str, str]) -> dict:
    """Converte DE VERDADE o arquivo do plano: recusa sem todas as decisoes, com backup antes, numa gravacao so, e
    confere o arquivo depois de gravar. Qualquer erro depois do backup restaura o backup e levanta ErroConversao com o
    nome do backup e o resultado da restauracao. Devolve o resumo."""
    caminho = exigir_arquivo_permitido(plano.caminho)
    if config.SINCRONIZACAO_GOOGLE_ATIVADA:
        raise ErroConversao("A sincronização com o Google precisa estar desligada para converter (o conversor nunca mexe na nuvem).")
    if plano.problemas:
        raise ErroConversao("Há problemas que nenhuma resposta resolve; veja o relatório:\n  - " + "\n  - ".join(plano.problemas))
    certas = _validar_decisoes(plano.duvidas, decisoes, completo=True)
    if _impressao(caminho) != plano.impressao:
        raise ErroConversao("O arquivo mudou desde a simulação. Simule de novo.")
    resultado = _construir(caminho, plano.plano_vendas, certas)
    if resultado.pendentes:
        raise ErroConversao(f"Faltam decisões para {len(resultado.pendentes)} dúvida(s) que só aparecem com as respostas dadas "
                            f"({', '.join(d.chave for d in resultado.pendentes)}). Nada foi gravado.")
    erros = _problemas_do_resultado(resultado, plano.antes)
    if erros:
        raise ErroConversao("A conversão não passou nas garantias (" + "; ".join(erros) + "). Nada foi gravado.")

    historico_antes = len(bd.ler_historico(caminho))
    backup = backup_mod.fazer_backup(backup_mod.MOTIVO_PRE_CONVERSAO, caminho)
    try:
        bd.escrever_vendas_e_propostas(caminho, propostas=resultado.propostas, vendas=resultado.vendas,
                                       historico_novo=resultado.historico)
        divergencias = _conferir_gravacao(caminho, resultado, plano.antes, historico_antes)
        if divergencias:
            raise ErroConversao("A conferência depois de gravar falhou (" + "; ".join(divergencias) + ").")
        return {"backup": backup, "conversoes": resultado.conversoes, "vendas_novas": resultado.vendas_novas,
                "depois": _contagem(*_ler(caminho))}
    except Exception as erro:
        raise _restaurar_e_explicar(caminho, backup, erro) from erro


def carregar_decisoes(caminho: Path) -> dict[str, str]:
    try:
        bruto = json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ErroConversao(f"Não foi possível ler o arquivo de decisões '{caminho}': {exc}") from exc
    if not isinstance(bruto, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in bruto.items()):
        raise ErroConversao('O arquivo de decisões deve ser um objeto JSON {"D1": "juntar", "S3": "Aprovado", ...}.')
    return bruto


def texto_das_duvidas(plano: PlanoConversao) -> str:
    """O duvidas_conversao.json: o que o usuario precisa responder (a resposta vai em decisoes.json)."""
    return json.dumps(
        {"arquivo": plano.caminho.name,
         "como_responder": 'Copie para decisoes.json um objeto {"<chave>": "<resposta>"} com uma das "opcoes" de cada dúvida.',
         "duvidas": [{"chave": d.chave, "tipo": d.tipo, "cliente": d.cliente, "pergunta": d.pergunta,
                      "detalhe": d.detalhe, "opcoes": list(d.opcoes)} for d in plano.duvidas],
         "problemas": plano.problemas},
        ensure_ascii=False, indent=2,
    )


def _tabela(titulo: str, antes: dict, depois: dict) -> list[str]:
    nomes = sorted(set(antes) | set(depois))
    linhas = [f"### {titulo}", "", "| | Antes | Depois |", "|---|---:|---:|"]
    linhas += [f"| {n} | {antes.get(n, 0)} | {depois.get(n, 0)} |" for n in nomes]
    return linhas + [""]


def texto_do_relatorio(plano: PlanoConversao, depois: dict | None = None, aplicado: dict | None = None) -> str:
    depois = depois or plano.depois
    a = plano.antes
    linhas = [
        "# Conversão dos dados antigos", "",
        f"Arquivo: `{plano.caminho.name}`", "",
        "**CONVERSÃO APLICADA**" if aplicado else "**SIMULAÇÃO: nada foi gravado.**", "",
    ]
    if aplicado:
        linhas += [f"Backup: `{aplicado['backup'].name}` ({ROTULO_DO_BACKUP})", ""]
    linhas += [
        "## Contagens", "", "| | Antes | Depois |", "|---|---:|---:|",
        f"| Clientes | {a['clientes']} | {depois['clientes']} |",
        f"| Propostas | {a['propostas']} | {depois['propostas']} |",
        f"| Soma dos valores (R$) | {a['soma_valores']:,.2f} | {depois['soma_valores']:,.2f} |",
        f"| Vendas | {a['vendas']} | {depois['vendas']} |",
        f"| Propostas sem venda | {a['propostas_sem_venda']} | {depois['propostas_sem_venda']} |", "",
    ]
    linhas += _tabela("Propostas por status", a["propostas_por_status"], depois["propostas_por_status"])
    linhas += _tabela("Vendas por status", a["vendas_por_status"], depois["vendas_por_status"])
    linhas += [f"Propostas que mudam de status: {plano.conversoes}. Vendas novas: {plano.vendas_novas}.", ""]
    if plano.problemas:
        linhas += ["## Problemas (impedem converter)", ""] + [f"- {p}" for p in plano.problemas] + [""]
    linhas += [f"## Dúvidas ({len(plano.duvidas)})", ""]
    if not plano.duvidas:
        linhas += ["Nenhuma.", ""]
    for d in plano.duvidas:
        linhas += [f"- **{d.chave}** ({d.tipo}) {d.cliente}: {d.pergunta}  ", f"  {d.detalhe}  ",
                   f"  Respostas: {', '.join(d.opcoes)}"]
    if plano.duvidas:
        linhas += ["", "Na simulação, as dúvidas sem resposta deixam a venda separada e o status como está."]
    return "\n".join(linhas) + "\n"


def escrever_relatorios(plano: PlanoConversao, pasta: Path, depois: dict | None = None, aplicado: dict | None = None) -> tuple[Path, Path]:
    pasta = exigir_saida_permitida(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    relatorio, duvidas = pasta / ARQUIVO_RELATORIO, pasta / ARQUIVO_DUVIDAS
    relatorio.write_text(texto_do_relatorio(plano, depois, aplicado), encoding="utf-8")
    duvidas.write_text(texto_das_duvidas(plano), encoding="utf-8")
    return relatorio, duvidas
