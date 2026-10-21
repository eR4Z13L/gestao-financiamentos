"""Resumo para colar no WhatsApp (planos 1.5-A e 1.5-B): o resumo de um vendedor num periodo e o resumo de uma venda.

So LE (core/vendas.py, core/data_store.py): nada e gravado. A tela so mostra e copia o texto daqui.

Regras do resumo por vendedor (ajustes aprovados em 20/10/2026, docs/planos/1.5B_resumo_ajustes.md):
- entra a venda CRIADA no periodo ou com MOVIMENTO nele (qualquer linha do HISTORICO da venda ou das propostas dela,
  menos as do TIPO "conversao": a conversao dos dados antigos nao e trabalho do vendedor); o periodo e a semana, a
  quinzena, o mes (atual ou anterior) ou DUAS DATAS LIVRES (periodo_das_datas);
- o vendedor e o do cliente da venda;
- cada venda cai em UM bloco, o do banco que esta sendo mostrado: Efetivadas, Aprovadas, Em análise, Negadas, Não
  efetivadas (Perdida e Não efetivada contam como uma coisa so). Se um banco FECHADO ja chegou a Assinado (ou alem),
  mostra esse(s) banco(s), cada um numa linha; senao, so o banco mais adiantado (Aprovado, Pré-aprovado, Em análise;
  Negado so quando TODAS as propostas negaram). No empate: o banco fechado e, depois, o mais parado (o mais antigo) -
  nunca a ordem da lista;
- o bloco Pendencias: TODO banco fechado ainda em Aprovado (mesmo com outro fechado ja Assinado; sem nenhum fechado,
  todo Aprovado), cada um com os seus dias parado, e, de cada venda, cada pendencia ABERTA (a lista do card, 1.2-B).
  Observacoes nao entram em resumo nenhum (ficam so no card);
- `blocos` escolhe o que entra no texto (todos, por padrao); sem emojis; negrito so nos titulos.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from core import data_store as bd
from core import propostas as propostas_mod
from core import vendas as vendas_mod
from core.formatting import formatar_reais
from core.validators import apenas_digitos

SEMANA, QUINZENA, MES = "semana", "quinzena", "mes"
LIVRE = "livre"  # duas datas escolhidas a mao (periodo_das_datas)
TIPOS_DE_PERIODO = [SEMANA, QUINZENA, MES]
ATUAL, ANTERIOR = "atual", "anterior"
QUAIS_PERIODOS = [ATUAL, ANTERIOR]

# os blocos do texto (a ordem e a do texto) - `blocos` aceita qualquer subconjunto deles
EFETIVADAS, APROVADAS, EM_ANALISE, NEGADAS, NAO_EFETIVADAS, PENDENCIAS = (
    "efetivadas", "aprovadas", "em_analise", "negadas", "nao_efetivadas", "pendencias")
BLOCOS = (EFETIVADAS, APROVADAS, EM_ANALISE, NEGADAS, NAO_EFETIVADAS, PENDENCIAS)
TITULO_DO_BLOCO = {EFETIVADAS: "Efetivadas", APROVADAS: "Aprovadas", EM_ANALISE: "Em análise", NEGADAS: "Negadas",
                   NAO_EFETIVADAS: "Não efetivadas", PENDENCIAS: "Pendências"}

SEM_TELEFONE = "sem telefone"
_SEM_CLIENTE = "Cliente sem cadastro"
_SEM_BANCO = "banco não informado"

# nome do periodo nas frases: "Resumo da semana passada", "Nenhuma venda nesta semana"
_DO_PERIODO = {(SEMANA, ATUAL): "da semana", (SEMANA, ANTERIOR): "da semana passada",
               (QUINZENA, ATUAL): "da quinzena", (QUINZENA, ANTERIOR): "da quinzena passada",
               (MES, ATUAL): "do mês", (MES, ANTERIOR): "do mês passado"}
_NO_PERIODO = {(SEMANA, ATUAL): "nesta semana", (SEMANA, ANTERIOR): "na semana passada",
               (QUINZENA, ATUAL): "nesta quinzena", (QUINZENA, ANTERIOR): "na quinzena passada",
               (MES, ATUAL): "neste mês", (MES, ANTERIOR): "no mês passado"}


class ErroResumo(Exception):
    """Pedido invalido (a mensagem diz o que fazer) - nada foi lido nem gravado."""


# -- periodo ---------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Periodo:
    tipo: str
    qual: str
    inicio: date
    fim: date  # inclusive

    @property
    def do_periodo(self) -> str:
        return "do período" if self.tipo == LIVRE else _DO_PERIODO[(self.tipo, self.qual)]

    @property
    def no_periodo(self) -> str:
        return f"no período de {self.datas}" if self.tipo == LIVRE else _NO_PERIODO[(self.tipo, self.qual)]

    @property
    def datas(self) -> str:
        """"12/10 a 18/10/2026" (o ano aparece nos dois extremos so quando eles sao de anos diferentes)."""
        if self.inicio.year == self.fim.year:
            return f"{self.inicio:%d/%m} a {self.fim:%d/%m/%Y}"
        return f"{self.inicio:%d/%m/%Y} a {self.fim:%d/%m/%Y}"


def _fim_do_mes(ano: int, mes: int) -> date:
    return date(ano, mes, calendar.monthrange(ano, mes)[1])


def periodo(tipo: str, qual: str = ATUAL, hoje: date | None = None) -> Periodo:
    """O intervalo de datas do resumo: semana (segunda a domingo), quinzena (1 a 15 / 16 ao fim do mes) ou mes do
    calendario, o ATUAL (o que contem `hoje`) ou o ANTERIOR."""
    if tipo not in TIPOS_DE_PERIODO:
        raise ErroResumo(f"Período inválido: {tipo!r} (use semana, quinzena ou mes).")
    if qual not in QUAIS_PERIODOS:
        raise ErroResumo(f"Período inválido: {qual!r} (use atual ou anterior).")
    hoje = hoje or date.today()
    if tipo == SEMANA:
        inicio = hoje - timedelta(days=hoje.weekday()) - (timedelta(days=7) if qual == ANTERIOR else timedelta(0))
        return Periodo(tipo, qual, inicio, inicio + timedelta(days=6))
    if tipo == MES:
        primeiro = hoje.replace(day=1)
        if qual == ANTERIOR:
            primeiro = (primeiro - timedelta(days=1)).replace(day=1)
        return Periodo(tipo, qual, primeiro, _fim_do_mes(primeiro.year, primeiro.month))
    primeira_metade = hoje.day <= 15
    if qual == ANTERIOR:
        if primeira_metade:  # a segunda metade do mes passado
            mes_passado = hoje.replace(day=1) - timedelta(days=1)
            return Periodo(tipo, qual, mes_passado.replace(day=16), mes_passado)
        return Periodo(tipo, qual, hoje.replace(day=1), hoje.replace(day=15))
    if primeira_metade:
        return Periodo(tipo, qual, hoje.replace(day=1), hoje.replace(day=15))
    return Periodo(tipo, qual, hoje.replace(day=16), _fim_do_mes(hoje.year, hoje.month))


def periodo_das_datas(inicio: date, fim: date, hoje: date | None = None) -> Periodo:
    """O periodo de duas datas livres (inclusive). Se elas sao exatamente a semana, a quinzena ou o mes (atual ou
    anterior) de `hoje`, e esse periodo (o texto diz "da semana"); senao, um periodo "livre"."""
    if inicio > fim:
        raise ErroResumo("O período começa depois de terminar.")
    for tipo in TIPOS_DE_PERIODO:
        for qual in QUAIS_PERIODOS:
            sugerido = periodo(tipo, qual, hoje)
            if (sugerido.inicio, sugerido.fim) == (inicio, fim):
                return sugerido
    return Periodo(LIVRE, "", inicio, fim)


# -- leitura ---------------------------------------------------------------------------------------

def _ler_historico() -> pd.DataFrame:
    return bd.ler_historico(propostas_mod.CAMINHO_XLSX)


def _ids_com_movimento(historico: pd.DataFrame, inicio: date, fim: date) -> set[str]:
    if historico.empty:
        return set()
    h = historico.dropna(subset=["QUANDO"])
    h = h[h["TIPO"] != vendas_mod.TIPO_CONVERSAO]
    dia = h["QUANDO"].dt.normalize()
    return set(h.loc[(dia >= pd.Timestamp(inicio)) & (dia <= pd.Timestamp(fim)), "ID"])


def _no_periodo(venda: vendas_mod.ResumoDaVenda, com_movimento: set[str], inicio: date, fim: date) -> bool:
    criada = venda.data_criacao is not None and inicio <= venda.data_criacao.date() <= fim
    ids = {venda.id, *(p.id for p in venda.propostas if p.id)}
    return criada or bool(ids & com_movimento)


def _do_vendedor(venda: vendas_mod.ResumoDaVenda, vendedor: str | None) -> bool:
    return vendedor is None or (venda.vendedor or "").strip().casefold() == vendedor.strip().casefold()


def _escolher_vendas(todas, historico: pd.DataFrame, inicio: date, fim: date, vendedor: str | None) -> list:
    if inicio > fim:
        raise ErroResumo("O período começa depois de terminar.")
    com_movimento = _ids_com_movimento(historico, inicio, fim)
    return [v for v in todas if _do_vendedor(v, vendedor) and _no_periodo(v, com_movimento, inicio, fim)]


def vendas_do_periodo(inicio: date, fim: date, vendedor: str | None = None,
                      hoje: date | None = None) -> list[vendas_mod.ResumoDaVenda]:
    """As vendas CRIADAS no periodo (inicio e fim inclusive) ou com MOVIMENTO nele; do vendedor do cliente da venda
    (`None`: todos)."""
    return _escolher_vendas(vendas_mod.listar_vendas(hoje), _ler_historico(), inicio, fim, vendedor)


# -- o resumo, estruturado ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LinhaDaVenda:
    id_venda: str
    cliente: str
    telefone: str  # ja formatado, ou SEM_TELEFONE
    equipamentos: str
    itens: tuple[str, ...]  # um por banco ("Banco X R$ 30.000: Aprovado"), ou um so texto ("Não efetivada: Desistiu")


@dataclass(frozen=True)
class ResumoDoVendedor:
    periodo: Periodo
    vendedor: str | None  # None: todos
    total: int  # as vendas do periodo (todas, estejam ou nao nos blocos escolhidos)
    efetivadas: tuple[LinhaDaVenda, ...]
    aprovadas: tuple[LinhaDaVenda, ...]
    em_analise: tuple[LinhaDaVenda, ...]
    negadas: tuple[LinhaDaVenda, ...]
    nao_efetivadas: tuple[LinhaDaVenda, ...]  # Perdida e Não efetivada
    aprovadas_sem_assinar: tuple[tuple[str, str, int], ...] = ()  # (cliente, banco, dias parado)
    com_pendencias: tuple[tuple[str, tuple[str, ...]], ...] = ()  # (cliente, os textos das pendencias abertas)
    blocos: tuple[str, ...] = BLOCOS  # o que entra no texto

    @property
    def vazio(self) -> bool:
        return self.total == 0

    @property
    def tem_pendencias(self) -> bool:
        return bool(self.aprovadas_sem_assinar or self.com_pendencias)


def _telefone(celular) -> str:
    """"(11) 91234-5678"; de um numero que nao tem 10 ou 11 digitos mostra o que esta na planilha (nunca adivinha)."""
    texto = str(celular or "").strip()
    digitos = apenas_digitos(texto)
    if len(digitos) == 11:
        return f"({digitos[:2]}) {digitos[2:7]}-{digitos[7:]}"
    if len(digitos) == 10:
        return f"({digitos[:2]}) {digitos[2:6]}-{digitos[6:]}"
    return texto or SEM_TELEFONE


def _celulares() -> dict[str, str]:
    clientes = bd.ler_clientes(propostas_mod.CAMINHO_XLSX)
    return {apenas_digitos(c): cel for c, cel in zip(clientes["CPF/CNPJ"], clientes["CELULAR"])}


def _reais(valor) -> str:
    return formatar_reais(valor).removesuffix(",00")


def _banco_e_valor(p: vendas_mod.PropostaNaVenda) -> str:
    banco = (p.banco or "").strip() or _SEM_BANCO
    return banco if p.valor is None else f"{banco} {_reais(p.valor)}"


def _ha(dias: int | None) -> str:
    if dias is None:
        return ""
    return "desde hoje" if dias <= 0 else "há 1 dia" if dias == 1 else f"há {dias} dias"


def _lista_com_e(nomes: list[str]) -> str:
    if len(nomes) <= 1:
        return "".join(nomes)
    return ", ".join(nomes[:-1]) + " e " + nomes[-1]


def _ultimas_por_id(historico: pd.DataFrame) -> dict[str, pd.Timestamp]:
    if historico.empty:
        return {}
    return historico.dropna(subset=["QUANDO"]).groupby("ID")["QUANDO"].max().to_dict()


def _dias_parada(p: vendas_mod.PropostaNaVenda, ultimas: dict, hoje: pd.Timestamp) -> int | None:
    """Dias desde a ultima mudanca da proposta no HISTORICO (sem ela, desde a data do pedido), como os alertas."""
    desde = ultimas.get(p.id, p.data) if p.id else p.data
    if desde is None or pd.isna(desde):
        return None
    return (hoje - pd.Timestamp(desde).normalize()).days


def _etapa(p: vendas_mod.PropostaNaVenda) -> str:
    return propostas_mod.etapa_status(p.status)


def _eh_aprovado(p: vendas_mod.PropostaNaVenda) -> bool:
    return (p.status or "").strip().casefold() == propostas_mod.STATUS_APROVADO.casefold()


def _com_motivo(status: str, motivo: str) -> str:
    return f"{status}: {motivo}" if motivo else status


# a resposta mais adiantada do banco: Aprovado (e o que veio depois dele), Pré-aprovado, Em análise, Negado
_ETAPAS_DE_APROVADO = {propostas_mod.ETAPA_APROVADO, propostas_mod.ETAPA_NF_ANEXADA, propostas_mod.ETAPA_GARANTIA_ASSINADA,
                       propostas_mod.ETAPA_EFETIVADO, propostas_mod.ETAPA_NAO_EFETIVADO}


def _posto_da_resposta(p: vendas_mod.PropostaNaVenda) -> int:
    etapa = _etapa(p)
    if etapa in _ETAPAS_DE_APROVADO:
        return 0
    if etapa == propostas_mod.ETAPA_PRE_APROVADO:
        return 1
    if etapa == propostas_mod.ETAPA_EM_ANALISE:
        return 2
    if etapa == propostas_mod.ETAPA_NEGADO:
        return 3
    return 4  # sem status ou desconhecido


def _assinado_ou_alem(p: vendas_mod.PropostaNaVenda) -> bool:
    """Banco FECHADO que ja chegou a Assinado (Assinado, NF enviada, Efetivado - e os nomes de antes: Garantia
    Assinada, Nota Fiscal Anexada)."""
    if not p.fechada:
        return False
    indice = vendas_mod.indice_da_etapa(p.status)
    return (indice is not None and indice >= 1) or _etapa(p) in {
        propostas_mod.ETAPA_NF_ANEXADA, propostas_mod.ETAPA_GARANTIA_ASSINADA, propostas_mod.ETAPA_EFETIVADO}


def _banco_mais_adiantado(propostas, ultimas: dict, hoje: pd.Timestamp) -> vendas_mod.PropostaNaVenda:
    """A melhor resposta; no empate, o banco fechado e, depois, o mais parado (o mais antigo) - nunca a ordem da lista
    (o resto do desempate, nome e id, so da um resultado sempre igual)."""
    return min(propostas, key=lambda p: (_posto_da_resposta(p), not p.fechada, -(_dias_parada(p, ultimas, hoje) or 0),
                                         (p.banco or "").casefold(), p.id))


def _aprovadas_sem_assinar(venda: vendas_mod.ResumoDaVenda, ultimas: dict, hoje: pd.Timestamp) -> list[tuple[str, int]]:
    """(banco, dias parado) de todo banco fechado ainda em Aprovado (mesmo quando outro fechado ja esta Assinado); sem
    nenhum fechado, de todo banco Aprovado. Cada banco com os dias do pedido dele. Venda ja resolvida: nenhum."""
    if venda.status == vendas_mod.VENDA_EFETIVADA or venda.status in vendas_mod.DESFECHOS_DA_VENDA:
        return []
    candidatos = [p for p in venda.propostas if p.fechada] or list(venda.propostas)
    return [((p.banco or "").strip() or _SEM_BANCO, dias) for p in candidatos
            if _eh_aprovado(p) and (dias := _dias_parada(p, ultimas, hoje)) is not None]

def _classificar(venda: vendas_mod.ResumoDaVenda, ultimas: dict, hoje: pd.Timestamp):
    """(bloco, itens): o bloco do(s) banco(s) mostrado(s) da venda."""
    fechadas = [p for p in venda.propostas if p.fechada]
    if venda.status == vendas_mod.VENDA_EFETIVADA:
        return EFETIVADAS, tuple(_banco_e_valor(p) for p in fechadas)  # todos os fechados ja efetivaram
    if venda.status in vendas_mod.DESFECHOS_DA_VENDA:  # Perdida e Não efetivada contam como uma coisa so
        return NAO_EFETIVADAS, (_com_motivo(vendas_mod.VENDA_NAO_EFETIVADA, venda.motivo),)
    if not venda.propostas:
        return EM_ANALISE, ("ainda sem pedido a nenhum banco",)
    assinados = [p for p in fechadas if _assinado_ou_alem(p)]
    # Negado so e o resultado quando TODAS negaram; status vazio ou desconhecido nao conta como negado
    sem_negados = [p for p in venda.propostas if _posto_da_resposta(p) != 3]
    if not sem_negados:
        nomes = list(dict.fromkeys((p.banco or "").strip() or _SEM_BANCO for p in venda.propostas))
        return NEGADAS, (f"{_lista_com_e(nomes)} {'negou' if len(nomes) == 1 else 'negaram'}",)
    mostrados = assinados or [_banco_mais_adiantado(sem_negados, ultimas, hoje)]
    posto = _posto_da_resposta(mostrados[0])
    if posto == 0:
        return APROVADAS, tuple(f"{_banco_e_valor(p)}: {p.status}" for p in mostrados)
    banco = mostrados[0]
    # Pré-aprovado (e um status desconhecido) diz o que e; Em análise e o proprio bloco
    resposta = f": {banco.status}" if posto in (1, 4) and banco.status else ""
    return EM_ANALISE, (", ".join(t for t in (_banco_e_valor(banco) + resposta, _ha(banco.dias_esperando)) if t),)


def _uma_linha(texto: str) -> str:
    return " ".join(str(texto or "").split())


def _blocos_validos(blocos) -> tuple[str, ...]:
    escolhidos = BLOCOS if blocos is None else tuple(b for b in BLOCOS if b in set(blocos))
    desconhecidos = set(blocos or ()) - set(BLOCOS)
    if desconhecidos:
        raise ErroResumo(f"Bloco desconhecido: {sorted(desconhecidos)[0]!r}.")
    return escolhidos


def montar_resumo(per: Periodo, vendedor: str | None = None, hoje: date | None = None,
                  blocos=None) -> ResumoDoVendedor:
    """O resumo do `vendedor` (None: todos) no periodo `per`, estruturado; `texto_whatsapp` o transforma em texto.
    `blocos`: quais blocos levar (None: todos); os outros ficam vazios."""
    escolhidos = _blocos_validos(blocos)
    hoje = hoje or date.today()
    historico = _ler_historico()
    vendas = _escolher_vendas(vendas_mod.listar_vendas(hoje), historico, per.inicio, per.fim, vendedor)
    celulares = _celulares()
    ultimas = _ultimas_por_id(historico)
    agora = pd.Timestamp(hoje)

    por_bloco: dict[str, list[LinhaDaVenda]] = {nome: [] for nome in BLOCOS if nome != PENDENCIAS}
    sem_assinar, com_pendencias = [], []
    for venda in sorted(vendas, key=lambda v: ((v.cliente or "").casefold(), v.id)):
        nome = venda.cliente or _SEM_CLIENTE
        bloco, itens = _classificar(venda, ultimas, agora)
        telefone = _telefone(celulares.get(apenas_digitos(venda.cpf)))
        por_bloco[bloco].append(LinhaDaVenda(venda.id, nome, telefone, venda.equipamentos, itens))
        sem_assinar += [(nome, nome_do_banco, dias) for nome_do_banco, dias in _aprovadas_sem_assinar(venda, ultimas, agora)]
        abertas = tuple(t for p in venda.pendencias if p.aberta and (t := _uma_linha(p.texto)))
        if abertas:
            com_pendencias.append((nome, abertas))
    de_cada = {b: (tuple(por_bloco[b]) if b in escolhidos else ()) for b in por_bloco}
    pendencias_incluidas = PENDENCIAS in escolhidos
    return ResumoDoVendedor(
        per, vendedor, len(vendas), de_cada[EFETIVADAS], de_cada[APROVADAS], de_cada[EM_ANALISE], de_cada[NEGADAS],
        de_cada[NAO_EFETIVADAS], tuple(sem_assinar) if pendencias_incluidas else (),
        tuple(com_pendencias) if pendencias_incluidas else (), escolhidos,
    )


# -- o texto -----------------------------------------------------------------------------------------

def _vendas(n: int) -> str:
    return f"{n} venda" if n == 1 else f"{n} vendas"


def _bloco_em_texto(titulo: str, linhas: tuple[LinhaDaVenda, ...]) -> list[str]:
    if not linhas:
        return []
    saida = [f"*{titulo} ({len(linhas)})*"]
    for linha in linhas:
        saida.append(f"• {linha.cliente} · {linha.telefone}")
        itens = [i for i in linha.itens if i]
        if len(itens) <= 1:  # equipamento e banco na mesma linha
            saida.append("  " + " · ".join(p for p in (linha.equipamentos, *itens) if p))
        else:  # cada banco na sua linha, um embaixo do outro
            if linha.equipamentos:
                saida.append(f"  {linha.equipamentos}")
            saida += [f"  {item}" for item in itens]
    saida.append("")
    return saida


def texto_whatsapp(resumo: ResumoDoVendedor, blocos=None) -> str:
    """O resumo no formato do WhatsApp (*negrito* so nos titulos, sem emojis). `blocos`: so esses (None: os do
    resumo). Sem vendas no periodo, so um aviso (veja `vazio`)."""
    escolhidos = resumo.blocos if blocos is None else tuple(b for b in _blocos_validos(blocos) if b in resumo.blocos)
    if not escolhidos:
        raise ErroResumo("Marque pelo menos um bloco para o resumo.")
    per = resumo.periodo
    if resumo.vazio:
        de = f" de {resumo.vendedor}" if resumo.vendedor else ""
        return f"Nenhuma venda{de} {per.no_periodo}"
    quem = resumo.vendedor or "Todos os vendedores"
    saida = [f"*Resumo {per.do_periodo} — {quem}*", f"{per.datas} · {_vendas(resumo.total)}", ""]
    for bloco in (EFETIVADAS, APROVADAS, EM_ANALISE, NEGADAS, NAO_EFETIVADAS):
        if bloco in escolhidos:
            saida += _bloco_em_texto(TITULO_DO_BLOCO[bloco], getattr(resumo, bloco))
    if PENDENCIAS in escolhidos and resumo.tem_pendencias:
        saida.append(f"*{TITULO_DO_BLOCO[PENDENCIAS]}*")
        if resumo.aprovadas_sem_assinar:
            saida.append("Aprovadas que ainda não assinaram:")
            saida += [f"• {nome}, {banco}: parada {_ha(dias)}" for nome, banco, dias in resumo.aprovadas_sem_assinar]
        if resumo.com_pendencias:
            saida.append("Pendências em aberto:")
            saida += [f"• {nome}: {texto}" for nome, textos in resumo.com_pendencias for texto in textos]
    while saida and saida[-1] == "":
        saida.pop()
    if len(saida) == 2:  # so o titulo: nenhum dos blocos escolhidos tem venda
        saida.append("")
        saida.append("Nada nos blocos escolhidos neste período.")
    return "\n".join(saida)


# -- o resumo de uma venda ---------------------------------------------------------------------------

def _banco_da_venda(p: vendas_mod.PropostaNaVenda) -> str:
    """"• Banco X R$ 52.000 (36x): NF enviada, seguiu com este": so o status (sem datas nem "parada ha N dias")."""
    meses = f" ({p.meses}x)" if p.meses else ""
    status = p.status or "sem status"
    return f"• {_banco_e_valor(p)}{meses}: {status}" + (", seguiu com este" if p.fechada else "")


def texto_da_venda(id_venda: str, hoje: date | None = None) -> str:
    """O resumo de uma venda para o WhatsApp: os bancos tentados, o resultado de cada um (so o status), com qual a
    venda seguiu e as pendencias abertas. Sem observacoes, sem datas e sem "parada ha N dias"."""
    hoje = hoje or date.today()
    venda = next((v for v in vendas_mod.listar_vendas(hoje) if v.id == id_venda), None)
    if venda is None:
        raise ErroResumo("Venda não encontrada (a lista pode ter mudado). Recarregue e tente de novo.")
    telefone = _telefone(_celulares().get(apenas_digitos(venda.cpf)))
    cabecalho = f"*Venda de {venda.cliente or _SEM_CLIENTE}* · {telefone}"
    quem = " · ".join(p for p in (venda.equipamentos, venda.vendedor) if p)
    saida = [cabecalho]
    if quem:
        saida.append(quem)
    saida += [_com_motivo(venda.status, venda.motivo), "", "Bancos tentados:"]
    if venda.propostas:
        saida += [_banco_da_venda(p) for p in venda.propostas]
    else:
        saida.append("Nenhum banco ainda.")
    abertas = [_uma_linha(p.texto) for p in venda.pendencias if p.aberta and _uma_linha(p.texto)]
    if abertas:
        saida += ["", "Pendências em aberto:"]
        saida += [f"• {texto}" for texto in abertas]
    return "\n".join(saida)
