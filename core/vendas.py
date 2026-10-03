"""Vendas: o negocio (um cliente + um ou mais equipamentos) e as propostas dele, uma por banco.

Dois niveis de status (decididos com o usuario em 02/10/2026):
- PROPOSTA (a resposta do banco): Em Análise -> Pré-aprovado -> Aprovado / Negado.
- VENDA (o andamento do negocio): Aguardando bancos -> Banco escolhido -> Nota fiscal -> Garantia -> Efetivada,
  ou os desfechos Não efetivada (o cliente desistiu) / Perdida (todos os bancos negaram).

Regras:
- Por padrao um pedido por banco cobre a venda inteira; tambem da pra mandar pedidos separados na mesma venda
  (cada proposta diz no EQUIPAMENTO o que cobre).
- "Banco escolhido" so com uma proposta APROVADA da propria venda; "Efetivada" so depois de escolher o banco.
  Nota fiscal e Garantia nao tem ordem fixa entre si (o usuario nao sabe se vem sempre depois do banco).
- Toda troca de status (de venda ou de proposta) vira uma linha no HISTÓRICO: e dele que saem o tempo de cada
  etapa e os alertas de parada.
- Gravar e sempre tudo-ou-nada (bd.escrever_vendas_e_propostas): venda, propostas e historico juntos.

So o ADMIN escreve (sessao.exigir_admin()).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

from core import data_store as bd
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import sheets_sync
from core.validators import apenas_digitos

VENDA_AGUARDANDO = "Aguardando bancos"
VENDA_BANCO_ESCOLHIDO = "Banco escolhido"
VENDA_NOTA_FISCAL = "Nota fiscal"
VENDA_GARANTIA = "Garantia"
VENDA_EFETIVADA = "Efetivada"
VENDA_NAO_EFETIVADA = "Não efetivada"
VENDA_PERDIDA = "Perdida"

ETAPAS_DA_VENDA = [VENDA_AGUARDANDO, VENDA_BANCO_ESCOLHIDO, VENDA_NOTA_FISCAL, VENDA_GARANTIA, VENDA_EFETIVADA]
DESFECHOS_DA_VENDA = [VENDA_NAO_EFETIVADA, VENDA_PERDIDA]
STATUS_DA_VENDA = ETAPAS_DA_VENDA + DESFECHOS_DA_VENDA
VENDA_FINALIZADA = {VENDA_EFETIVADA, *DESFECHOS_DA_VENDA}

STATUS_DA_PROPOSTA = [
    propostas_mod.STATUS_EM_ANALISE,
    propostas_mod.STATUS_PRE_APROVADO,
    propostas_mod.STATUS_APROVADO,
    propostas_mod.STATUS_NEGADO,
]

MOTIVOS_DE_PERDA = ["Desistiu", "Comprou à vista", "Foi com outro correspondente", "Todos os bancos negaram", "Outro"]

DIAS_PARA_ALERTA = 7  # proposta em analise sem resposta / venda parada na mesma etapa

TIPO_VENDA = "venda"
TIPO_PROPOSTA = "proposta"


def _caminho():
    # o MESMO arquivo das propostas, lido na hora: vendas e propostas moram juntas, e quem aponta as propostas
    # para outro arquivo (os testes, para a copia ficticia) leva as vendas junto - nunca grava a venda no
    # arquivo real enquanto as propostas estao na copia
    return propostas_mod.CAMINHO_XLSX


class ErroVenda(Exception):
    """A regra recusou (a mensagem diz o que fazer) - nada foi gravado."""


def novo_id(prefixo: str) -> str:
    # aleatorio, e nao sequencial: dois computadores criando ao mesmo tempo nunca geram o mesmo numero
    return f"{prefixo}-{uuid.uuid4().hex[:10]}"


def _registro_historico(tipo: str, id_: str, de: str, para: str, motivo: str = "") -> dict:
    return {"QUANDO": datetime.now().replace(microsecond=0), "TIPO": tipo, "ID": id_, "DE": de, "PARA": para,
            "MOTIVO": motivo, "COMPUTADOR": sheets_sync.nome_desta_maquina()}


def _ler() -> tuple[pd.DataFrame, pd.DataFrame]:
    propostas = bd.ler_propostas(_caminho())[bd.PROPOSTAS_COLUNAS_EDITAVEIS].copy()
    vendas = bd.ler_vendas(_caminho())
    return propostas, vendas


def _linha_da_venda(vendas: pd.DataFrame, id_venda: str) -> int:
    alvo = vendas.index[vendas["ID_VENDA"] == id_venda]
    if len(alvo) == 0:
        raise ErroVenda("Venda não encontrada (a lista pode ter mudado). Recarregue e tente de novo.")
    return alvo[0]


def _linha_da_proposta(propostas: pd.DataFrame, id_proposta: str) -> int:
    alvo = propostas.index[propostas["ID_PROPOSTA"] == id_proposta]
    if len(alvo) == 0:
        raise ErroVenda("Proposta não encontrada (a lista pode ter mudado). Recarregue e tente de novo.")
    return alvo[0]


def _normalizar_equipamentos(equipamentos: list[str]) -> list[str]:
    vistos, nomes = set(), []
    for nome in equipamentos:
        nome = " ".join(str(nome or "").split())
        if nome and nome.upper() not in vistos:
            vistos.add(nome.upper())
            nomes.append(nome)
    if not nomes:
        raise ErroVenda("Informe pelo menos um equipamento da venda.")
    return nomes


def _nova_proposta(campos: dict, id_venda: str) -> dict:
    campos = dict(campos)
    campos.setdefault("DATA", pd.Timestamp(date.today()))
    campos.setdefault("STATUS", propostas_mod.STATUS_EM_ANALISE)
    campos["CPF"] = (campos.get("CPF") or "").strip()
    if not str(campos.get("BANCO") or "").strip():
        raise ErroVenda("Informe o banco do pedido.")  # cada proposta da venda e o pedido a UM banco
    if campos["STATUS"] not in STATUS_DA_PROPOSTA:
        raise ErroVenda(f"Status de proposta inválido: {campos['STATUS']!r}.")
    propostas_mod._validar_campos(campos)  # as mesmas regras de sempre (CPF cadastrado, banco, equipamento, valor)
    linha = {col: campos.get(col, "") for col in bd.PROPOSTAS_COLUNAS_EDITAVEIS}
    linha["ID_PROPOSTA"] = novo_id("P")
    linha["ID_VENDA"] = id_venda
    return linha


def criar_venda(cpf: str, equipamentos: list[str], proposta: dict, observacoes: str = "") -> tuple[str, str]:
    """Cria a venda e a primeira proposta dela (o pedido a um banco). Sem EQUIPAMENTO na proposta, ela cobre a
    venda inteira. Devolve (ID_VENDA, ID_PROPOSTA)."""
    sessao_mod.exigir_admin()
    nomes = _normalizar_equipamentos(equipamentos)
    propostas, vendas = _ler()
    id_venda = novo_id("V")
    linha = _nova_proposta({**proposta, "CPF": cpf, "EQUIPAMENTO": proposta.get("EQUIPAMENTO") or " + ".join(nomes)}, id_venda)
    venda = {"ID_VENDA": id_venda, "CPF": linha["CPF"], "EQUIPAMENTOS": " + ".join(nomes), "STATUS": VENDA_AGUARDANDO,
             "BANCO_ESCOLHIDO": "", "MOTIVO": "", "DATA_CRIACAO": pd.Timestamp(linha["DATA"]), "OBSERVAÇÕES": observacoes}
    bd.escrever_vendas_e_propostas(
        _caminho(),
        propostas=pd.concat([propostas, pd.DataFrame([linha])], ignore_index=True),
        vendas=pd.concat([vendas, pd.DataFrame([venda])], ignore_index=True),
        historico_novo=[_registro_historico(TIPO_VENDA, id_venda, "", VENDA_AGUARDANDO),
                        _registro_historico(TIPO_PROPOSTA, linha["ID_PROPOSTA"], "", linha["STATUS"])],
    )
    return id_venda, linha["ID_PROPOSTA"]


def mandar_a_outro_banco(id_venda: str, proposta: dict) -> str:
    """Mais uma proposta na mesma venda (o antigo "Duplicar"). Devolve o ID_PROPOSTA."""
    sessao_mod.exigir_admin()
    propostas, vendas = _ler()
    venda = vendas.loc[_linha_da_venda(vendas, id_venda)]
    if venda["STATUS"] in VENDA_FINALIZADA:
        raise ErroVenda(f"A venda já está \"{venda['STATUS']}\": não dá para mandar a outro banco.")
    linha = _nova_proposta({**proposta, "CPF": venda["CPF"], "EQUIPAMENTO": proposta.get("EQUIPAMENTO") or venda["EQUIPAMENTOS"]},
                           id_venda)
    bd.escrever_vendas_e_propostas(
        _caminho(),
        propostas=pd.concat([propostas, pd.DataFrame([linha])], ignore_index=True),
        historico_novo=[_registro_historico(TIPO_PROPOSTA, linha["ID_PROPOSTA"], "", linha["STATUS"])],
    )
    return linha["ID_PROPOSTA"]


def mudar_status_proposta(id_proposta: str, novo: str) -> bool:
    """Troca a resposta do banco. Devolve True quando, com isso, TODAS as propostas da venda estao negadas e a venda
    ainda aguarda os bancos - quem chamou oferece marcar a venda como Perdida (o app nunca decide sozinho)."""
    sessao_mod.exigir_admin()
    if novo not in STATUS_DA_PROPOSTA:
        raise ErroVenda(f"Status de proposta inválido: {novo!r}.")
    propostas, vendas = _ler()
    linha = _linha_da_proposta(propostas, id_proposta)
    antigo = propostas.at[linha, "STATUS"]
    if antigo == novo:
        return False
    id_venda = propostas.at[linha, "ID_VENDA"]
    if id_venda and id_venda in set(vendas["ID_VENDA"]):
        venda = vendas.loc[_linha_da_venda(vendas, id_venda)]
        if venda["BANCO_ESCOLHIDO"] == id_proposta and novo != propostas_mod.STATUS_APROVADO:
            raise ErroVenda("Esta é a proposta do banco escolhido na venda. Troque o banco escolhido antes.")
    propostas.at[linha, "STATUS"] = novo
    bd.escrever_vendas_e_propostas(
        _caminho(), propostas=propostas,
        historico_novo=[_registro_historico(TIPO_PROPOSTA, id_proposta, antigo, novo)],
    )
    if not id_venda:
        return False
    da_venda = propostas[propostas["ID_VENDA"] == id_venda]["STATUS"].map(propostas_mod.etapa_status)
    venda_aguardando = id_venda in set(vendas["ID_VENDA"]) and \
        vendas.loc[_linha_da_venda(vendas, id_venda), "STATUS"] == VENDA_AGUARDANDO
    return bool(venda_aguardando and len(da_venda) > 0 and (da_venda == propostas_mod.ETAPA_NEGADO).all())


def mudar_status_venda(id_venda: str, novo: str, *, proposta_escolhida: str | None = None, motivo: str = "") -> None:
    """Troca a etapa da venda. "Banco escolhido" pede a proposta aprovada escolhida; "Efetivada" exige que o banco ja
    tenha sido escolhido; o motivo (opcional) so vale para Não efetivada e Perdida. Voltar uma etapa tambem e
    permitido (desfazer) e fica no historico como qualquer troca."""
    sessao_mod.exigir_admin()
    if novo not in STATUS_DA_VENDA:
        raise ErroVenda(f"Status de venda inválido: {novo!r}.")
    if motivo and motivo not in MOTIVOS_DE_PERDA:
        raise ErroVenda(f"Motivo inválido: {motivo!r}.")
    if motivo and novo not in DESFECHOS_DA_VENDA:
        raise ErroVenda("O motivo só vale para Não efetivada e Perdida.")
    propostas, vendas = _ler()
    linha = _linha_da_venda(vendas, id_venda)
    antigo = vendas.at[linha, "STATUS"]
    if novo == VENDA_BANCO_ESCOLHIDO:
        if not proposta_escolhida:
            raise ErroVenda("Escolha qual banco (uma proposta aprovada da venda).")
        p = _linha_da_proposta(propostas, proposta_escolhida)
        if propostas.at[p, "ID_VENDA"] != id_venda:
            raise ErroVenda("Essa proposta é de outra venda.")
        if propostas_mod.etapa_status(propostas.at[p, "STATUS"]) != propostas_mod.ETAPA_APROVADO:
            raise ErroVenda("Só dá para escolher um banco que aprovou a proposta.")
        vendas.at[linha, "BANCO_ESCOLHIDO"] = proposta_escolhida
    elif novo == VENDA_AGUARDANDO:
        vendas.at[linha, "BANCO_ESCOLHIDO"] = ""  # voltou atras: nenhum banco escolhido
    elif novo == VENDA_EFETIVADA and not vendas.at[linha, "BANCO_ESCOLHIDO"]:
        raise ErroVenda("Escolha o banco antes de marcar a venda como efetivada.")
    vendas.at[linha, "MOTIVO"] = motivo if novo in DESFECHOS_DA_VENDA else ""
    if antigo == novo and novo != VENDA_BANCO_ESCOLHIDO:
        return
    vendas.at[linha, "STATUS"] = novo
    bd.escrever_vendas_e_propostas(
        _caminho(), vendas=vendas,
        historico_novo=[_registro_historico(TIPO_VENDA, id_venda, antigo, novo, motivo)],
    )


def _pilhas_de_anteriores(historico: pd.DataFrame) -> dict[str, list[str]]:
    """Para cada ID, os status de onde ele veio, o mais recente no fim - relendo o historico na ordem em que foi
    gravado: cada troca empilha o status de onde saiu; uma troca que volta ao status do topo e uma volta e
    desempilha. Assim o "voltar" recua um passo por vez (B -> A, depois A -> o de antes), e nunca fica indo e
    voltando entre os dois ultimos."""
    pilhas: dict[str, list[str]] = {}
    for id_, de, para in zip(historico["ID"], historico["DE"], historico["PARA"]):
        pilha = pilhas.setdefault(id_, [])
        if de == para:
            continue  # trocar o banco escolhido: o status da venda nao mudou
        if pilha and para == pilha[-1]:
            pilha.pop()
        elif de:
            pilha.append(de)
    return pilhas


def _anterior(id_: str) -> str | None:
    pilha = _pilhas_de_anteriores(bd.ler_historico(_caminho())).get(id_, [])
    return pilha[-1] if pilha else None


def voltar_venda(id_venda: str) -> str:
    """Volta a venda ao status de antes da ultima troca (o "↩" do card). Devolve o status para onde voltou."""
    anterior = _anterior(id_venda)
    if anterior is None or anterior not in STATUS_DA_VENDA:
        raise ErroVenda("Não há um status anterior para onde voltar.")
    _, vendas = _ler()
    escolhida = vendas.at[_linha_da_venda(vendas, id_venda), "BANCO_ESCOLHIDO"] or None
    if anterior == VENDA_BANCO_ESCOLHIDO and escolhida is None:
        raise ErroVenda("Escolha de novo o banco (o anel ao lado do banco aprovado).")
    motivo = ""
    if anterior in DESFECHOS_DA_VENDA:  # volta com o mesmo motivo que tinha
        historico = bd.ler_historico(_caminho())
        entradas = historico[(historico["ID"] == id_venda) & (historico["PARA"] == anterior)]
        motivo = entradas["MOTIVO"].iloc[-1] if len(entradas) else ""
        motivo = motivo if motivo in MOTIVOS_DE_PERDA else ""
    mudar_status_venda(id_venda, anterior, proposta_escolhida=escolhida, motivo=motivo)
    return anterior


def voltar_proposta(id_proposta: str) -> bool:
    """Volta a proposta a resposta de antes da ultima troca. Devolve o mesmo que mudar_status_proposta."""
    anterior = _anterior(id_proposta)
    if anterior is None or anterior not in STATUS_DA_PROPOSTA:
        raise ErroVenda("Não há um status anterior para onde voltar.")
    return mudar_status_proposta(id_proposta, anterior)


def proxima_etapa(status: str) -> str | None:
    """A etapa seguinte da venda (a que o "Avançar para…" oferece); None no fim ou num desfecho."""
    if status not in ETAPAS_DA_VENDA:
        return None
    posicao = ETAPAS_DA_VENDA.index(status)
    return ETAPAS_DA_VENDA[posicao + 1] if posicao + 1 < len(ETAPAS_DA_VENDA) else None


# -- leitura ---------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Alerta:
    tipo: str  # TIPO_VENDA ou TIPO_PROPOSTA
    id: str
    dias: int
    texto: str


def _ultimas_mudancas(historico: pd.DataFrame) -> dict[str, pd.Timestamp]:
    if historico.empty:
        return {}
    return historico.dropna(subset=["QUANDO"]).groupby("ID")["QUANDO"].max().to_dict()


def alertas(hoje: date | None = None) -> list[Alerta]:
    """Proposta Em Análise ou Pré-aprovado sem resposta, e venda ainda andando parada na mesma etapa, ha
    DIAS_PARA_ALERTA dias ou mais (desde a ultima troca no historico; sem historico, desde o envio/criacao)."""
    hoje = pd.Timestamp(hoje or date.today())
    propostas = bd.ler_propostas(_caminho())
    vendas = bd.ler_vendas(_caminho())
    ultimas = _ultimas_mudancas(bd.ler_historico(_caminho()))
    resultado = []
    esperando = {propostas_mod.ETAPA_EM_ANALISE, propostas_mod.ETAPA_PRE_APROVADO}
    for _, p in propostas.iterrows():
        if propostas_mod.etapa_status(p["STATUS"]) not in esperando or not p["ID_PROPOSTA"]:
            continue
        desde = ultimas.get(p["ID_PROPOSTA"], p["DATA"])
        dias = (hoje - pd.Timestamp(desde).normalize()).days if pd.notna(desde) else 0
        if dias >= DIAS_PARA_ALERTA:
            resultado.append(Alerta(TIPO_PROPOSTA, p["ID_PROPOSTA"], dias, f"{p['BANCO']}: sem resposta há {dias} dias"))
    for _, v in vendas.iterrows():
        if v["STATUS"] in VENDA_FINALIZADA:
            continue
        desde = ultimas.get(v["ID_VENDA"], v["DATA_CRIACAO"])
        dias = (hoje - pd.Timestamp(desde).normalize()).days if pd.notna(desde) else 0
        if dias >= DIAS_PARA_ALERTA:
            resultado.append(Alerta(TIPO_VENDA, v["ID_VENDA"], dias, f"parada em \"{v['STATUS']}\" há {dias} dias"))
    return resultado


@dataclass(frozen=True)
class PropostaNaVenda:
    id: str
    indice: int  # posicao real na aba PROPOSTAS (a que a Ficha e Todas as Propostas usam)
    banco: str
    status: str
    valor: float | None
    meses: int | None
    data: pd.Timestamp | None
    equipamento: str
    escolhida: bool
    dias_esperando: int | None  # so Em Análise / Pré-aprovado: dias desde o envio (ou a ultima troca de status)
    anterior: str | None = None  # para onde o "voltar" leva (None: nao ha para onde voltar)
    carencia: int | None = None  # dias ate a 1a parcela
    parcela: float | None = None


@dataclass(frozen=True)
class ResumoDaVenda:
    id: str
    cpf: str
    cliente: str
    vendedor: str
    equipamentos: str
    status: str
    motivo: str
    banco_escolhido: str  # o ID_PROPOSTA escolhido ("" = nenhum)
    data_criacao: pd.Timestamp | None
    dias_na_etapa: int | None  # desde a ultima troca de status da venda (sem historico: desde a criacao)
    observacoes: str
    propostas: tuple[PropostaNaVenda, ...]
    anterior: str | None = None  # para onde o "voltar" leva (None: nao ha para onde voltar)

    @property
    def finalizada(self) -> bool:
        return self.status in VENDA_FINALIZADA

    @property
    def parada(self) -> bool:
        return not self.finalizada and (self.dias_na_etapa or 0) >= DIAS_PARA_ALERTA

    def aprovadas(self) -> list[PropostaNaVenda]:
        return [p for p in self.propostas if propostas_mod.etapa_status(p.status) == propostas_mod.ETAPA_APROVADO]


def _dias_desde(momento, hoje: pd.Timestamp) -> int | None:
    return (hoje - pd.Timestamp(momento).normalize()).days if pd.notna(momento) else None


def _numero_ou_none(valor):
    return None if valor is None or valor == "" or pd.isna(valor) else valor


def listar_vendas(hoje: date | None = None) -> list[ResumoDaVenda]:
    """Todas as vendas, prontas pra tela (a mais recente primeiro), cada uma com as suas propostas."""
    hoje = pd.Timestamp(hoje or date.today())
    propostas = bd.ler_propostas(_caminho())
    vendas = bd.ler_vendas(_caminho())
    clientes = bd.ler_clientes(_caminho())
    historico = bd.ler_historico(_caminho())
    ultimas = _ultimas_mudancas(historico)
    pilhas = _pilhas_de_anteriores(historico)
    por_cpf = {apenas_digitos(c): (nome, vendedor) for c, nome, vendedor
               in zip(clientes["CPF/CNPJ"], clientes["CLIENTE"], clientes["VENDEDOR"])}
    esperando = {propostas_mod.ETAPA_EM_ANALISE, propostas_mod.ETAPA_PRE_APROVADO}

    resultado = []
    for _, v in vendas.iterrows():
        da_venda = propostas[propostas["ID_VENDA"] == v["ID_VENDA"]].sort_values("DATA", kind="stable")
        itens = []
        for indice, p in da_venda.iterrows():
            dias = None
            if propostas_mod.etapa_status(p["STATUS"]) in esperando:
                dias = _dias_desde(ultimas.get(p["ID_PROPOSTA"], p["DATA"]), hoje)
            meses = _numero_ou_none(p["MESES"])
            anterior = (pilhas.get(p["ID_PROPOSTA"]) or [None])[-1]
            carencia = _numero_ou_none(p["CARÊNCIA (DIAS)"])
            itens.append(PropostaNaVenda(
                p["ID_PROPOSTA"], int(indice), p["BANCO"], p["STATUS"], _numero_ou_none(p["VALOR (R$)"]),
                int(meses) if meses is not None else None, p["DATA"] if pd.notna(p["DATA"]) else None,
                p["EQUIPAMENTO"], bool(p["ID_PROPOSTA"]) and p["ID_PROPOSTA"] == v["BANCO_ESCOLHIDO"], dias,
                anterior if anterior in STATUS_DA_PROPOSTA else None,  # status de antes das vendas nao volta
                int(carencia) if carencia is not None else None, _numero_ou_none(p["PARCELA (R$)"]),
            ))
        nome, vendedor = por_cpf.get(apenas_digitos(v["CPF"]), ("", ""))
        criacao = v["DATA_CRIACAO"] if pd.notna(v["DATA_CRIACAO"]) else None
        anterior = (pilhas.get(v["ID_VENDA"]) or [None])[-1]
        if anterior == VENDA_BANCO_ESCOLHIDO and not v["BANCO_ESCOLHIDO"]:
            anterior = None  # a escolha foi desfeita: o banco se escolhe de novo pelo anel
        resultado.append(ResumoDaVenda(
            v["ID_VENDA"], v["CPF"], nome, vendedor, v["EQUIPAMENTOS"], v["STATUS"], v["MOTIVO"],
            v["BANCO_ESCOLHIDO"], criacao, _dias_desde(ultimas.get(v["ID_VENDA"], criacao), hoje),
            v["OBSERVAÇÕES"], tuple(itens), anterior if anterior in STATUS_DA_VENDA else None,
        ))
    resultado.sort(key=lambda r: r.data_criacao if r.data_criacao is not None else pd.Timestamp.min, reverse=True)
    return resultado


def contar_propostas_sem_venda() -> int:
    """Propostas que nao estao em nenhuma venda (as de antes das vendas, ainda nao juntadas)."""
    propostas = bd.ler_propostas(_caminho())
    existentes = set(bd.ler_vendas(_caminho())["ID_VENDA"])
    return int((~propostas["ID_VENDA"].isin(existentes)).sum())


def indice_da_proposta(id_proposta: str) -> int:
    """A posicao real da proposta na aba PROPOSTAS (a que a Ficha e Todas as Propostas usam)."""
    return int(_linha_da_proposta(bd.ler_propostas(_caminho()), id_proposta))


def propostas_da_venda(id_venda: str) -> pd.DataFrame:
    propostas = bd.ler_propostas(_caminho())
    return propostas[propostas["ID_VENDA"] == id_venda].copy()


def vendas_do_cliente(cpf: str) -> pd.DataFrame:
    vendas = bd.ler_vendas(_caminho())
    return vendas[vendas["CPF"].map(apenas_digitos) == apenas_digitos(cpf)].copy()
