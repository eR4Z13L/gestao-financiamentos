"""Resumo para colar no WhatsApp (plano 1.5-A): o resumo de um vendedor num periodo e o resumo de uma venda.

So LE (core/vendas.py, core/data_store.py): nada e gravado. A tela (1.5-B) so mostra e copia o texto daqui.

Regras do resumo por vendedor (rascunho da especificacao 1.5, ainda nao aprovado - se o formato mudar, muda so o
formatador `texto_whatsapp`):
- entra a venda CRIADA no periodo ou com MOVIMENTO nele (qualquer linha do HISTORICO da venda ou das propostas dela,
  menos as do TIPO "conversao": a conversao dos dados antigos nao e trabalho do vendedor);
- o vendedor e o do cliente da venda;
- cada venda cai em UM bloco, o do banco mais adiantado: Efetivadas, Aprovadas, Em análise, Negadas, Perdidas e não
  efetivadas. A Pendencias so aponta de volta para vendas que ja estao num bloco (aprovadas sem assinar, pendentes de
  entrega - que tambem ficam em Efetivadas - e as com observacoes).
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
TIPOS_DE_PERIODO = [SEMANA, QUINZENA, MES]
ATUAL, ANTERIOR = "atual", "anterior"
QUAIS_PERIODOS = [ATUAL, ANTERIOR]

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
        return _DO_PERIODO[(self.tipo, self.qual)]

    @property
    def no_periodo(self) -> str:
        return _NO_PERIODO[(self.tipo, self.qual)]

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
    itens: tuple[str, ...]  # um por banco ("Banco X R$ 30.000: Aprovado"), ou um so texto ("Perdida: Desistiu")


@dataclass(frozen=True)
class ResumoDoVendedor:
    periodo: Periodo
    vendedor: str | None  # None: todos
    total: int
    efetivadas: tuple[LinhaDaVenda, ...]
    aprovadas: tuple[LinhaDaVenda, ...]
    em_analise: tuple[LinhaDaVenda, ...]
    negadas: tuple[LinhaDaVenda, ...]
    perdidas: tuple[LinhaDaVenda, ...]  # Perdida e Não efetivada
    aprovadas_sem_assinar: tuple[tuple[str, int], ...] = ()  # (cliente, dias parada)
    pendentes_de_entrega: tuple[tuple[str, str], ...] = ()  # (cliente, motivo)
    observacoes: tuple[tuple[str, str], ...] = ()  # (cliente, o que falta)

    @property
    def vazio(self) -> bool:
        return self.total == 0

    @property
    def tem_pendencias(self) -> bool:
        return bool(self.aprovadas_sem_assinar or self.pendentes_de_entrega or self.observacoes)


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


_ETAPAS_APROVADAS = {propostas_mod.ETAPA_APROVADO, propostas_mod.ETAPA_NF_ANEXADA,
                     propostas_mod.ETAPA_GARANTIA_ASSINADA, propostas_mod.ETAPA_EFETIVADO}


def _etapa(p: vendas_mod.PropostaNaVenda) -> str:
    return propostas_mod.etapa_status(p.status)


def _eh_aprovado(p: vendas_mod.PropostaNaVenda) -> bool:
    return (p.status or "").strip().casefold() == propostas_mod.STATUS_APROVADO.casefold()


def _com_motivo(status: str, motivo: str) -> str:
    return f"{status}: {motivo}" if motivo else status


def _classificar(venda: vendas_mod.ResumoDaVenda, ultimas: dict, hoje: pd.Timestamp):
    """(bloco, itens, parada_das_aprovadas): o bloco do banco mais adiantado da venda."""
    fechadas = [p for p in venda.propostas if p.fechada]
    if venda.status in (vendas_mod.VENDA_EFETIVADA, vendas_mod.VENDA_PENDENTE_ENTREGA):
        return "efetivadas", tuple(_banco_e_valor(p) for p in fechadas), ()  # todos os fechados ja efetivaram
    if venda.status in vendas_mod.DESFECHOS_DA_VENDA:
        return "perdidas", (_com_motivo(venda.status, venda.motivo),), ()
    aprovadas = fechadas or [p for p in venda.propostas if _etapa(p) in _ETAPAS_APROVADAS]
    if aprovadas:
        paradas = [d for p in aprovadas if _eh_aprovado(p) and (d := _dias_parada(p, ultimas, hoje)) is not None]
        itens = tuple(f"{_banco_e_valor(p)}: {p.status}" for p in aprovadas)
        return "aprovadas", itens, tuple(paradas)
    negadas = [p for p in venda.propostas if _etapa(p) == propostas_mod.ETAPA_NEGADO]
    if venda.propostas and len(negadas) == len(venda.propostas):
        nomes = list(dict.fromkeys((p.banco or "").strip() or _SEM_BANCO for p in negadas))
        return "negadas", (f"{_lista_com_e(nomes)} {'negou' if len(nomes) == 1 else 'negaram'}",), ()
    if not venda.propostas:
        return "em_analise", ("ainda sem pedido a nenhum banco",), ()
    esperando = [p for p in venda.propostas if _etapa(p) != propostas_mod.ETAPA_NEGADO]
    return "em_analise", tuple(", ".join(t for t in (_banco_e_valor(p), _ha(p.dias_esperando)) if t) for p in esperando), ()


def _uma_linha(texto: str) -> str:
    return " ".join(str(texto or "").split())


def montar_resumo(per: Periodo, vendedor: str | None = None, hoje: date | None = None) -> ResumoDoVendedor:
    """O resumo do `vendedor` (None: todos) no periodo `per`, estruturado; `texto_whatsapp` o transforma em texto."""
    hoje = hoje or date.today()
    historico = _ler_historico()
    vendas = _escolher_vendas(vendas_mod.listar_vendas(hoje), historico, per.inicio, per.fim, vendedor)
    celulares = _celulares()
    ultimas = _ultimas_por_id(historico)
    agora = pd.Timestamp(hoje)

    blocos: dict[str, list[LinhaDaVenda]] = {nome: [] for nome in
                                              ("efetivadas", "aprovadas", "em_analise", "negadas", "perdidas")}
    sem_assinar, pendentes, observacoes = [], [], []
    for venda in sorted(vendas, key=lambda v: ((v.cliente or "").casefold(), v.id)):
        nome = venda.cliente or _SEM_CLIENTE
        bloco, itens, paradas = _classificar(venda, ultimas, agora)
        telefone = _telefone(celulares.get(apenas_digitos(venda.cpf)))
        blocos[bloco].append(LinhaDaVenda(venda.id, nome, telefone, venda.equipamentos, itens))
        if paradas:
            sem_assinar.append((nome, max(paradas)))
        if venda.status == vendas_mod.VENDA_PENDENTE_ENTREGA:
            pendentes.append((nome, venda.motivo))
        if _uma_linha(venda.observacoes):
            observacoes.append((nome, _uma_linha(venda.observacoes)))
    return ResumoDoVendedor(
        per, vendedor, len(vendas), *(tuple(blocos[n]) for n in ("efetivadas", "aprovadas", "em_analise", "negadas",
                                                                  "perdidas")),
        tuple(sem_assinar), tuple(pendentes), tuple(observacoes),
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
        else:
            if linha.equipamentos:
                saida.append(f"  {linha.equipamentos}")
            saida.append("  " + " · ".join(itens))
    saida.append("")
    return saida


def texto_whatsapp(resumo: ResumoDoVendedor) -> str:
    """O resumo no formato do WhatsApp (*negrito* so nos titulos). Sem vendas no periodo, so um aviso (veja `vazio`)."""
    per = resumo.periodo
    if resumo.vazio:
        de = f" de {resumo.vendedor}" if resumo.vendedor else ""
        return f"Nenhuma venda{de} {per.no_periodo}"
    quem = resumo.vendedor or "Todos os vendedores"
    saida = [f"*Resumo {per.do_periodo} — {quem}*", f"{per.datas} · {_vendas(resumo.total)}", ""]
    saida += _bloco_em_texto("✅ Efetivadas", resumo.efetivadas)
    saida += _bloco_em_texto("🟢 Aprovadas", resumo.aprovadas)
    saida += _bloco_em_texto("⏳ Em análise", resumo.em_analise)
    saida += _bloco_em_texto("❌ Negadas", resumo.negadas)
    saida += _bloco_em_texto("🚫 Perdidas e não efetivadas", resumo.perdidas)
    if resumo.tem_pendencias:
        saida.append("*⚠️ Pendências*")
        if resumo.aprovadas_sem_assinar:
            saida.append("Aprovadas que ainda não assinaram:")
            saida += [f"• {nome}, parada {_ha(dias)}" for nome, dias in resumo.aprovadas_sem_assinar]
        if resumo.pendentes_de_entrega:
            saida.append("Pendentes de entrega:")
            saida += [f"• {nome}: {motivo}" if motivo else f"• {nome}" for nome, motivo in resumo.pendentes_de_entrega]
        if resumo.observacoes:
            saida.append("Observações (o que falta):")
            saida += [f"• {nome}: {texto}" for nome, texto in resumo.observacoes]
    while saida and saida[-1] == "":
        saida.pop()
    return "\n".join(saida)


# -- o resumo de uma venda ---------------------------------------------------------------------------

def _data_da_efetivacao(historico: pd.DataFrame, id_proposta: str) -> pd.Timestamp | None:
    if historico.empty or not id_proposta:
        return None
    h = historico.dropna(subset=["QUANDO"])
    h = h[(h["ID"] == id_proposta) & (h["TIPO"] == vendas_mod.TIPO_PROPOSTA)
          & (h["PARA"].str.strip().str.casefold() == vendas_mod.PROPOSTA_EFETIVADA.casefold())]
    return h["QUANDO"].max() if len(h) else None


def _banco_da_venda(p: vendas_mod.PropostaNaVenda, historico: pd.DataFrame, ultimas: dict, hoje: pd.Timestamp) -> str:
    meses = f" ({p.meses}x)" if p.meses else ""
    base = f"• {_banco_e_valor(p)}{meses}: "
    parada = _dias_parada(p, ultimas, hoje)
    if p.fechada:
        texto = "Aprovado, seguiu com este"
        if p.status == vendas_mod.PROPOSTA_EFETIVADA:
            quando = _data_da_efetivacao(historico, p.id)
            return base + texto + " · Efetivado" + (f" em {quando:%d/%m}" if quando is not None else "")
        etapa = "" if _eh_aprovado(p) else p.status
        parou = f"parada há {parada} dias" if parada is not None and parada >= propostas_mod.DIAS_PROPOSTA_PARADA else ""
        extra = ", ".join(t for t in (etapa, parou) if t)
        return base + texto + (f" · {extra}" if extra else "")
    etapa = _etapa(p)
    if etapa == propostas_mod.ETAPA_NEGADO:
        return base + "Negado"
    if p.dias_esperando is not None:
        return base + f"{p.status} {_ha(p.dias_esperando)}".strip()
    return base + (p.status or "sem status")


def texto_da_venda(id_venda: str, hoje: date | None = None) -> str:
    """O resumo de uma venda para o WhatsApp: os bancos tentados, o resultado de cada um, com qual a venda seguiu e as
    observacoes."""
    hoje = hoje or date.today()
    venda = next((v for v in vendas_mod.listar_vendas(hoje) if v.id == id_venda), None)
    if venda is None:
        raise ErroResumo("Venda não encontrada (a lista pode ter mudado). Recarregue e tente de novo.")
    historico = _ler_historico()
    ultimas = _ultimas_por_id(historico)
    agora = pd.Timestamp(hoje)
    telefone = _telefone(_celulares().get(apenas_digitos(venda.cpf)))
    cabecalho = f"*Venda de {venda.cliente or _SEM_CLIENTE}* · {telefone}"
    quem = " · ".join(p for p in (venda.equipamentos, venda.vendedor) if p)
    desde = f"Desde {venda.data_criacao:%d/%m/%Y} · " if venda.data_criacao is not None else ""
    saida = [cabecalho]
    if quem:
        saida.append(quem)
    saida += [desde + _com_motivo(venda.status, venda.motivo), "", "Bancos tentados:"]
    if venda.propostas:
        saida += [_banco_da_venda(p, historico, ultimas, agora) for p in venda.propostas]
    else:
        saida.append("Nenhum banco ainda.")
    if _uma_linha(venda.observacoes):
        saida += ["", f"Obs.: {_uma_linha(venda.observacoes)}"]
    return "\n".join(saida)
