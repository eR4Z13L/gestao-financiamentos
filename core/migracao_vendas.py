"""Juntar as propostas antigas (de antes das vendas, sem ID_VENDA) em vendas - feito UMA vez, num computador so.

planejar() so propoe, sem gravar nada:
- mesmo cliente + mesmo equipamento, com no maximo DIAS_MESMA_VENDA entre uma proposta e a seguinte: a mesma venda;
- o que o app NAO decide sozinho vira uma Duvida, que o usuario responde (juntar ou deixar separado):
  * o mesmo cliente com equipamentos DIFERENTES mandados com ate DIAS_VARIOS_EQUIPAMENTOS de diferenca (uma venda
    com os dois, ou opcoes que o cliente estava considerando?);
  * o mesmo cliente + equipamento com propostas mais espacadas que DIAS_MESMA_VENDA (a mesma venda reenviada, ou
    uma compra nova?).
aplicar() grava, com backup antes e numa gravacao so. O status de cada venda sai das propostas, sem chute: as que
passaram da aprovacao (Efetivado, Nota fiscal anexada, Garantia assinada) sao os bancos FECHADOS da venda, e o status
e o calculado por eles (Efetivada se todos efetivaram, senao Em andamento); sem nenhum fechado, Não efetivada se o
cliente desistiu, Perdida ("Todos os bancos negaram") se todos negaram, senao Aguardando bancos. O status das
propostas nao muda (so ganham o ID e a venda).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd

from config import CAMINHO_XLSX
from core import backup as backup_mod
from core import data_store as bd
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import vendas as vendas_mod
from core.validators import apenas_digitos

DIAS_MESMA_VENDA = 2  # decidido com o usuario em 02/10/2026
DIAS_VARIOS_EQUIPAMENTOS = 7

DUVIDA_VARIOS_EQUIPAMENTOS = "varios_equipamentos"
DUVIDA_ESPACADA = "espacada"


@dataclass
class Grupo:
    chave: str
    cpf: str
    equipamento: str
    indices: list[int]  # posicao de cada proposta na aba PROPOSTAS
    primeira: pd.Timestamp
    ultima: pd.Timestamp


@dataclass(frozen=True)
class Duvida:
    chave: str
    tipo: str
    cpf: str
    cliente: str
    grupos: tuple[str, ...]  # as chaves dos grupos que "juntar" une
    pergunta: str
    juntar: str  # o texto do botao de cada resposta
    separar: str


@dataclass
class Plano:
    grupos: list[Grupo]
    duvidas: list[Duvida]
    indices_sem_venda: list[int]
    resumo: dict = field(default_factory=dict)


def _data_curta(momento) -> str:
    return pd.Timestamp(momento).strftime("%d/%m/%Y") if pd.notna(momento) else "sem data"


def planejar(caminho: Path | None = None, propostas: pd.DataFrame | None = None) -> Plano:
    """`caminho`: o arquivo a ler (padrao: o do app); o conversor dos dados antigos passa o dele. `propostas`: ja lidas
    (como bd.ler_propostas devolve), se quem chama quer decidir quais entram (o conversor tira o ID_VENDA das orfas)."""
    if propostas is None:
        propostas = bd.ler_propostas(caminho or CAMINHO_XLSX)
    sem_venda = propostas[propostas["ID_VENDA"] == ""].copy()
    sem_venda["_cpf"] = sem_venda["CPF"].map(apenas_digitos)
    sem_venda["_equip"] = sem_venda["EQUIPAMENTO"].fillna("").str.strip()
    sem_venda["_chave_equip"] = sem_venda["_equip"].str.upper()
    sem_venda["_data"] = pd.to_datetime(sem_venda["DATA"], errors="coerce")
    nomes = dict(zip(sem_venda["_cpf"], sem_venda["CLIENTE"]))

    grupos: list[Grupo] = []
    duvidas: list[Duvida] = []
    for (cpf, _chave), sub in sem_venda.sort_values("_data", kind="stable").groupby(["_cpf", "_chave_equip"], sort=True):
        partes: list[list[int]] = []
        anterior = None
        for indice, data in zip(sub.index, sub["_data"]):
            espacada = anterior is not None and pd.notna(data) and pd.notna(anterior) and (data - anterior).days > DIAS_MESMA_VENDA
            if not partes or espacada:
                partes.append([])
            partes[-1].append(int(indice))
            anterior = data if pd.notna(data) else anterior
        chaves = []
        for parte in partes:
            datas = sem_venda.loc[parte, "_data"]
            grupos.append(Grupo(f"G{len(grupos) + 1}", cpf, sub["_equip"].iloc[0], parte, datas.min(), datas.max()))
            chaves.append(grupos[-1].chave)
        if len(chaves) > 1:
            datas = " · ".join(f"{_data_curta(g.primeira)}" for g in grupos[-len(chaves):])
            equip = sub["_equip"].iloc[0] or "sem equipamento"
            duvidas.append(Duvida(
                f"D{len(duvidas) + 1}", DUVIDA_ESPACADA, cpf, nomes.get(cpf, ""), tuple(chaves),
                f"{equip}: propostas em datas afastadas ({datas}). É a mesma venda reenviada, ou compras diferentes?",
                "A mesma venda", "Vendas separadas",
            ))

    # equipamentos diferentes do mesmo cliente, mandados perto: componentes ligados (A perto de B, B perto de C)
    por_cliente: dict[str, list[Grupo]] = {}
    for grupo in grupos:
        por_cliente.setdefault(grupo.cpf, []).append(grupo)
    for cpf, do_cliente in por_cliente.items():
        vizinhos = {g.chave: set() for g in do_cliente}
        for i, a in enumerate(do_cliente):
            for b in do_cliente[i + 1:]:
                if a.equipamento.upper() == b.equipamento.upper():
                    continue
                distancia = min(abs((x - y).days) for x in (a.primeira, a.ultima) for y in (b.primeira, b.ultima)
                                if pd.notna(x) and pd.notna(y)) if all(pd.notna(d) for d in (a.primeira, b.primeira)) else None
                if distancia is not None and distancia <= DIAS_VARIOS_EQUIPAMENTOS:
                    vizinhos[a.chave].add(b.chave)
                    vizinhos[b.chave].add(a.chave)
        vistos: set[str] = set()
        for chave in vizinhos:
            if chave in vistos or not vizinhos[chave]:
                continue
            componente, pilha = set(), [chave]
            while pilha:
                atual = pilha.pop()
                if atual not in componente:
                    componente.add(atual)
                    pilha.extend(vizinhos[atual] - componente)
            vistos |= componente
            envolvidos = [g for g in do_cliente if g.chave in componente]
            equipamentos = sorted({g.equipamento or "sem equipamento" for g in envolvidos}, key=str.upper)
            datas = sorted({_data_curta(g.primeira) for g in envolvidos})
            duvidas.append(Duvida(
                f"D{len(duvidas) + 1}", DUVIDA_VARIOS_EQUIPAMENTOS, cpf, nomes.get(cpf, ""),
                tuple(g.chave for g in envolvidos),
                f"{' e '.join(equipamentos)} mandados em {', '.join(datas)}. É uma venda só com todos, ou vendas separadas "
                "(opções que o cliente estava considerando)?",
                "Uma venda só", "Vendas separadas",
            ))
    plano = Plano(grupos, duvidas, [int(i) for i in sem_venda.index])
    plano.resumo = {"propostas": len(sem_venda), "grupos": len(grupos), "duvidas": len(duvidas)}
    return plano


def _juntar(plano: Plano, decisoes: dict[str, bool]) -> list[list[Grupo]]:
    """Os grupos finais: cada duvida respondida com "juntar" une os grupos dela (pode encadear varias)."""
    pai = {g.chave: g.chave for g in plano.grupos}

    def raiz(chave: str) -> str:
        while pai[chave] != chave:
            pai[chave] = pai[pai[chave]]
            chave = pai[chave]
        return chave

    for duvida in plano.duvidas:
        if decisoes.get(duvida.chave):
            primeiro = raiz(duvida.grupos[0])
            for outro in duvida.grupos[1:]:
                pai[raiz(outro)] = primeiro
    finais: dict[str, list[Grupo]] = {}
    for grupo in plano.grupos:
        finais.setdefault(raiz(grupo.chave), []).append(grupo)
    return list(finais.values())


def montar(plano: Plano, decisoes: dict[str, bool], propostas: pd.DataFrame, vendas: pd.DataFrame,
           quando: Callable[[pd.Timestamp], datetime] | None = None) -> dict:
    """Monta, SEM gravar, o resultado de juntar: `propostas` (so as colunas editaveis) ganham ID_PROPOSTA/ID_VENDA e
    as vendas novas saem prontas, com o historico de cada uma. `propostas` e alterada no lugar (passe uma copia).
    `quando`: o QUANDO do historico de cada venda nova, a partir da DATA_CRIACAO dela (padrao: agora).
    Devolve {"propostas", "vendas", "historico", "por_status", "vendas_novas"}."""
    novas, historico, contagem = [], [], {}
    agora = datetime.now().replace(microsecond=0)
    for grupos in _juntar(plano, decisoes):
        indices = sorted(i for g in grupos for i in g.indices)
        if not indices:  # grupo esvaziado (o conversor tira propostas de um grupo): nao ha venda para ele
            continue
        id_venda = vendas_mod.novo_id("V")
        for i in indices:
            if not propostas.at[i, "ID_PROPOSTA"]:
                propostas.at[i, "ID_PROPOSTA"] = vendas_mod.novo_id("P")
            propostas.at[i, "ID_VENDA"] = id_venda
        etapas = propostas.loc[indices, "STATUS"].map(propostas_mod.etapa_status)
        fechou = etapas.isin({propostas_mod.ETAPA_EFETIVADO, propostas_mod.ETAPA_GARANTIA_ASSINADA, propostas_mod.ETAPA_NF_ANEXADA})
        fechadas = [propostas.at[i, "ID_PROPOSTA"] for i in etapas.index[fechou]]
        escolhido, motivo = ";".join(fechadas), ""
        if fechadas:
            status = vendas_mod.status_calculado(
                [vendas_mod.PROPOSTA_EFETIVADA if e == propostas_mod.ETAPA_EFETIVADO else e for e in etapas[fechou]])
        elif (etapas == propostas_mod.ETAPA_NAO_EFETIVADO).any():
            status = vendas_mod.VENDA_NAO_EFETIVADA
        elif len(etapas) and (etapas == propostas_mod.ETAPA_NEGADO).all():
            status, motivo = vendas_mod.VENDA_PERDIDA, "Todos os bancos negaram"
        else:
            status = vendas_mod.VENDA_AGUARDANDO
        equipamentos = []
        for grupo in sorted(grupos, key=lambda g: (g.primeira, g.equipamento)):
            if grupo.equipamento and grupo.equipamento.upper() not in {e.upper() for e in equipamentos}:
                equipamentos.append(grupo.equipamento)
        datas = pd.to_datetime(propostas.loc[indices, "DATA"], errors="coerce")
        novas.append({"ID_VENDA": id_venda, "CPF": propostas.at[indices[0], "CPF"], "EQUIPAMENTOS": " + ".join(equipamentos),
                      "STATUS": status, "BANCO_ESCOLHIDO": escolhido, "MOTIVO": motivo,
                      "DATA_CRIACAO": datas.min(), "OBSERVAÇÕES": ""})
        momento = quando(datas.min()) if quando is not None else agora
        historico.append({"QUANDO": momento, "TIPO": vendas_mod.TIPO_VENDA, "ID": id_venda, "DE": "", "PARA": status,
                          "MOTIVO": motivo, "COMPUTADOR": vendas_mod.sheets_sync.nome_desta_maquina()})
        contagem[status] = contagem.get(status, 0) + 1
    return {"propostas": propostas, "historico": historico, "por_status": contagem, "vendas_novas": len(novas),
            "vendas": pd.concat([vendas, pd.DataFrame(novas, columns=bd.VENDAS_COLUNAS)], ignore_index=True)}


def aplicar(plano: Plano, decisoes: dict[str, bool]) -> dict:
    """Grava as vendas do plano. `decisoes`: chave da duvida -> True (juntar) / False (separar); duvida sem resposta
    fica separada. Recusa se as propostas mudaram desde o plano. Devolve um resumo do que foi feito."""
    sessao_mod.exigir_admin()
    faltando = [d.chave for d in plano.duvidas if d.chave not in decisoes]
    if faltando:
        raise vendas_mod.ErroVenda(f"Responda todas as dúvidas antes ({len(faltando)} sem resposta).")
    propostas = bd.ler_propostas(CAMINHO_XLSX)[bd.PROPOSTAS_COLUNAS_EDITAVEIS].copy()
    if [int(i) for i in propostas.index[propostas["ID_VENDA"] == ""]] != plano.indices_sem_venda:
        raise vendas_mod.ErroVenda("As propostas mudaram desde que o plano foi feito. Abra de novo para refazer o plano.")
    vendas = bd.ler_vendas(CAMINHO_XLSX)
    backup = backup_mod.fazer_backup(backup_mod.MOTIVO_PRE_VENDAS, CAMINHO_XLSX)
    montado = montar(plano, decisoes, propostas, vendas)
    bd.escrever_vendas_e_propostas(
        CAMINHO_XLSX, propostas=montado["propostas"], vendas=montado["vendas"], historico_novo=montado["historico"],
    )
    return {"vendas": montado["vendas_novas"], "propostas": len(plano.indices_sem_venda),
            "por_status": montado["por_status"], "backup": backup}
