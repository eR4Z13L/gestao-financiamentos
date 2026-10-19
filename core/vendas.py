"""Vendas: o negocio (um cliente + um ou mais equipamentos) e as propostas dele, uma por banco.

O modelo (decidido com o usuario em 02 e 03/10/2026):
- PROPOSTA (cada pedido a um banco): Em Análise -> Pré-aprovado -> Aprovado / Negado - a resposta do banco. Um banco
  APROVADO pode ser marcado como FECHADO (o cliente fechou com ele) e, fechado, segue sozinho ate Efetivado. Uma venda
  pode fechar em VARIOS bancos (ex.: o equipamento X por um banco e o Y por outro), e cada financiamento anda no seu
  tempo - por isso as etapas depois do fechamento sao de cada proposta, nao da venda.
- VENDA: nao tem etapas proprias - o status sai dos bancos: Aguardando bancos (nenhum fechado), Em andamento (algum
  fechado) ou Efetivada (todos os fechados efetivados). Os desfechos sao manuais: Não efetivada (o cliente desistiu) e
  Perdida (ex.: todos os bancos negaram); reabrir volta ao status calculado.
  (Contrato assinado e Nota fiscal ficaram FORA por enquanto - o usuario vai ver como funcionam; quando voltarem,
  entram como etapas de cada proposta fechada, antes de Efetivado.)

Regras:
- Por padrao um pedido por banco cobre a venda inteira; tambem da pra mandar pedidos separados na mesma venda
  (cada proposta diz no EQUIPAMENTO o que cobre). Dois bancos fechados nunca cobrem o mesmo equipamento.
- Os fechados ficam em VENDAS.BANCO_ESCOLHIDO, como uma lista de ID_PROPOSTA (sem coluna nova na planilha).
- Toda troca de status (de venda ou de proposta) e todo fechamento viram uma linha no HISTÓRICO: e dele que saem o
  tempo de cada etapa, os alertas de parada e o "voltar".
- Gravar e sempre tudo-ou-nada (bd.escrever_vendas_e_propostas): venda, propostas e historico juntos.

So o ADMIN escreve (sessao.exigir_admin()).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

from core import clientes as clientes_mod
from core import data_store as bd
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import sheets_sync
from core.validators import apenas_digitos

VENDA_AGUARDANDO = "Aguardando bancos"
VENDA_EM_ANDAMENTO = "Em andamento"
VENDA_EFETIVADA = "Efetivada"
VENDA_NAO_EFETIVADA = "Não efetivada"
VENDA_PERDIDA = "Perdida"

ETAPAS_DA_VENDA = [VENDA_AGUARDANDO, VENDA_EM_ANDAMENTO, VENDA_EFETIVADA]  # calculadas pelos bancos
DESFECHOS_DA_VENDA = [VENDA_NAO_EFETIVADA, VENDA_PERDIDA]  # manuais
STATUS_DA_VENDA = ETAPAS_DA_VENDA + DESFECHOS_DA_VENDA
VENDA_FINALIZADA = {VENDA_EFETIVADA, *DESFECHOS_DA_VENDA}

# a resposta do banco (o que a lista e as bolinhas oferecem para qualquer proposta)
STATUS_DA_PROPOSTA = [
    propostas_mod.STATUS_EM_ANALISE,
    propostas_mod.STATUS_PRE_APROVADO,
    propostas_mod.STATUS_APROVADO,
    propostas_mod.STATUS_NEGADO,
]
PROPOSTA_EFETIVADA = propostas_mod.STATUS_EFETIVADO  # so para um banco fechado
STATUS_DE_FECHADA = [propostas_mod.STATUS_APROVADO, PROPOSTA_EFETIVADA]  # onde um banco fechado pode estar

MOTIVOS_DE_PERDA = ["Desistiu", "Comprou à vista", "Foi com outro correspondente", "Todos os bancos negaram", "Outro"]

DIAS_PARA_ALERTA = 7  # proposta em analise sem resposta / venda parada no mesmo status

TIPO_VENDA = "venda"
TIPO_PROPOSTA = "proposta"
TIPO_FECHAMENTO = "fechamento"  # marcar/desmarcar um banco como fechado (nao e troca de status)
FECHADA = "Fechada"
_SEPARADOR_DE_FECHADAS = ";"
_SEPARADOR_DE_EQUIPAMENTOS = "+"


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


def fechadas_da_venda(texto) -> list[str]:
    """Os ID_PROPOSTA fechados de uma venda (a coluna BANCO_ESCOLHIDO, "P-1;P-2")."""
    return [i.strip() for i in str(texto or "").split(_SEPARADOR_DE_FECHADAS) if i.strip()]


def equipamentos_cobertos(texto) -> set[str]:
    """Os equipamentos que um pedido cobre ("Laser X + Cadeira Y"), sem diferenciar maiusculas/espacos."""
    return {" ".join(e.split()).upper() for e in str(texto or "").split(_SEPARADOR_DE_EQUIPAMENTOS) if e.strip()}


def status_calculado(fechadas_e_status: list[str]) -> str:
    """O status da venda (fora os desfechos) a partir dos status dos bancos fechados."""
    if not fechadas_e_status:
        return VENDA_AGUARDANDO
    if all(s == PROPOSTA_EFETIVADA for s in fechadas_e_status):
        return VENDA_EFETIVADA
    return VENDA_EM_ANDAMENTO


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


def _recalcular_venda(vendas: pd.DataFrame, propostas: pd.DataFrame, linha_venda: int, historico: list[dict]) -> None:
    """Acerta a venda depois de mudar um banco: tira da lista de fechados o que sumiu e recalcula o status (um
    desfecho manual fica como esta). A troca de status vai pro `historico`."""
    id_venda = vendas.at[linha_venda, "ID_VENDA"]
    da_venda = propostas[propostas["ID_VENDA"] == id_venda].set_index("ID_PROPOSTA")["STATUS"]
    fechadas = [i for i in fechadas_da_venda(vendas.at[linha_venda, "BANCO_ESCOLHIDO"]) if i in da_venda.index]
    vendas.at[linha_venda, "BANCO_ESCOLHIDO"] = _SEPARADOR_DE_FECHADAS.join(fechadas)
    antigo = vendas.at[linha_venda, "STATUS"]
    if antigo in DESFECHOS_DA_VENDA:
        return
    novo = status_calculado([da_venda[i] for i in fechadas])
    if novo != antigo:
        vendas.at[linha_venda, "STATUS"] = novo
        historico.append(_registro_historico(TIPO_VENDA, id_venda, antigo, novo))


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


def criar_venda(cpf: str, equipamentos: list[str], proposta: dict | None = None,
                observacoes: str = "") -> tuple[str, str | None]:
    """Cria a venda - so ela (as propostas entram depois, uma por banco) ou ja com a primeira proposta. Sem
    EQUIPAMENTO na proposta, ela cobre a venda inteira. Devolve (ID_VENDA, ID_PROPOSTA ou None)."""
    sessao_mod.exigir_admin()
    nomes = _normalizar_equipamentos(equipamentos)
    propostas, vendas = _ler()
    id_venda = novo_id("V")
    historico = [_registro_historico(TIPO_VENDA, id_venda, "", VENDA_AGUARDANDO)]
    if proposta is None:
        cpf = (cpf or "").strip()
        if not cpf or clientes_mod.buscar_por_cpf(cpf) is None:
            raise ErroVenda("Escolha um cliente cadastrado para a venda.")
        linha, criacao = None, pd.Timestamp(date.today())
    else:
        linha = _nova_proposta({**proposta, "CPF": cpf, "EQUIPAMENTO": proposta.get("EQUIPAMENTO") or " + ".join(nomes)},
                               id_venda)
        cpf, criacao = linha["CPF"], pd.Timestamp(linha["DATA"])
        propostas = pd.concat([propostas, pd.DataFrame([linha])], ignore_index=True)
        historico.append(_registro_historico(TIPO_PROPOSTA, linha["ID_PROPOSTA"], "", linha["STATUS"]))
    venda = {"ID_VENDA": id_venda, "CPF": cpf, "EQUIPAMENTOS": " + ".join(nomes), "STATUS": VENDA_AGUARDANDO,
             "BANCO_ESCOLHIDO": "", "MOTIVO": "", "DATA_CRIACAO": criacao, "OBSERVAÇÕES": observacoes}
    bd.escrever_vendas_e_propostas(
        _caminho(),
        propostas=propostas if linha is not None else None,
        vendas=pd.concat([vendas, pd.DataFrame([venda])], ignore_index=True),
        historico_novo=historico,
    )
    return id_venda, (linha["ID_PROPOSTA"] if linha is not None else None)


def editar_venda(id_venda: str, equipamentos: list[str], observacoes: str) -> None:
    """Troca os equipamentos e as observacoes da venda (o "Editar a venda" do card aberto). O status nao muda aqui."""
    sessao_mod.exigir_admin()
    nomes = _normalizar_equipamentos(equipamentos)
    _, vendas = _ler()
    linha = _linha_da_venda(vendas, id_venda)
    vendas.at[linha, "EQUIPAMENTOS"] = " + ".join(nomes)
    vendas.at[linha, "OBSERVAÇÕES"] = (observacoes or "").strip()
    bd.escrever_vendas_e_propostas(_caminho(), vendas=vendas)


def mandar_a_outro_banco(id_venda: str, proposta: dict) -> str:
    """Mais uma proposta na mesma venda (o antigo "Duplicar"). Devolve o ID_PROPOSTA. Uma venda Efetivada ainda aceita
    pedidos (ex.: um equipamento que ficou de fora); uma desistida/perdida, nao."""
    sessao_mod.exigir_admin()
    propostas, vendas = _ler()
    venda = vendas.loc[_linha_da_venda(vendas, id_venda)]
    if venda["STATUS"] in DESFECHOS_DA_VENDA:
        raise ErroVenda(f"A venda está \"{venda['STATUS']}\": reabra a venda antes de mandar a outro banco.")
    linha = _nova_proposta({**proposta, "CPF": venda["CPF"], "EQUIPAMENTO": proposta.get("EQUIPAMENTO") or venda["EQUIPAMENTOS"]},
                           id_venda)
    bd.escrever_vendas_e_propostas(
        _caminho(),
        propostas=pd.concat([propostas, pd.DataFrame([linha])], ignore_index=True),
        historico_novo=[_registro_historico(TIPO_PROPOSTA, linha["ID_PROPOSTA"], "", linha["STATUS"])],
    )
    return linha["ID_PROPOSTA"]


def editar_proposta(id_proposta: str, campos: dict, esperado: dict | None = None) -> bool:
    """Grava a edicao de uma proposta (o formulario, em qualquer tela) numa gravacao so. `campos`: so os que mudam.
    Troca de STATUS: as respostas do banco; Efetivado so num banco fechado, e um banco fechado so fica entre Aprovado
    e Efetivado (pra mudar a resposta, desmarque antes). Fica no historico e recalcula a venda; um status de antes das
    vendas que nao mudou e aceito como esta. `esperado`: a proposta como o formulario a abriu - se outra tela a mudou
    nesse meio-tempo, recusa em vez de gravar por cima. Devolve True quando, com isso, TODAS as propostas da venda
    estao negadas e a venda ainda aguarda os bancos - quem chamou oferece marcar a venda como Perdida."""
    sessao_mod.exigir_admin()
    propostas, vendas = _ler()
    linha = _linha_da_proposta(propostas, id_proposta)
    if esperado is not None and not propostas_mod.linha_confere(propostas.loc[linha].to_dict(), esperado):
        raise propostas_mod.ErroProposta(propostas_mod._MENSAGEM_PROPOSTA_MUDOU)
    antigo = propostas.at[linha, "STATUS"]
    novo = campos.get("STATUS", antigo)
    id_venda = propostas.at[linha, "ID_VENDA"]
    linha_venda = _linha_da_venda(vendas, id_venda) if id_venda and id_venda in set(vendas["ID_VENDA"]) else None
    fechada = linha_venda is not None and id_proposta in fechadas_da_venda(vendas.at[linha_venda, "BANCO_ESCOLHIDO"])
    historico = []
    if novo != antigo:
        if novo not in STATUS_DA_PROPOSTA and not (novo == PROPOSTA_EFETIVADA and fechada):
            if novo == PROPOSTA_EFETIVADA:
                raise ErroVenda("Só um banco marcado como fechado pode ser efetivado (o anel ao lado do banco aprovado).")
            raise ErroVenda(f"Status de proposta inválido: {novo!r}.")
        if fechada and novo not in STATUS_DE_FECHADA:
            raise ErroVenda("Este banco está marcado como fechado na venda. Desmarque o anel antes de mudar a resposta.")
        historico.append(_registro_historico(TIPO_PROPOSTA, id_proposta, antigo, novo))
    estado_final = {**propostas.loc[linha].to_dict(), **campos}
    propostas_mod._validar_campos(estado_final, valor_obrigatorio=False)  # as mesmas regras do formulario de sempre
    igual = propostas_mod._normalizar_para_comparar
    if not historico and all(igual(propostas.at[linha, c]) == igual(estado_final[c]) for c in campos if c in propostas.columns):
        return False  # nada mudou: nao grava (nem sincroniza) a toa
    for coluna in campos:
        if coluna in bd.PROPOSTAS_COLUNAS_EDITAVEIS and coluna not in ("ID_PROPOSTA", "ID_VENDA", "CPF"):
            valor = estado_final[coluna]
            propostas.at[linha, coluna] = None if valor == "" else valor
    if linha_venda is not None:
        _recalcular_venda(vendas, propostas, linha_venda, historico)
    bd.escrever_vendas_e_propostas(_caminho(), propostas=propostas, vendas=vendas if linha_venda is not None else None,
                                   historico_novo=historico or None)
    if novo == antigo or linha_venda is None:
        return False
    da_venda = propostas[propostas["ID_VENDA"] == id_venda]["STATUS"].map(propostas_mod.etapa_status)
    venda_aguardando = vendas.at[linha_venda, "STATUS"] == VENDA_AGUARDANDO
    return bool(venda_aguardando and len(da_venda) > 0 and (da_venda == propostas_mod.ETAPA_NEGADO).all())


def mudar_status_proposta(id_proposta: str, novo: str) -> bool:
    """Troca a resposta do banco (ou leva um banco fechado a Efetivado). Devolve o mesmo que editar_proposta."""
    if novo not in STATUS_DA_PROPOSTA and novo != PROPOSTA_EFETIVADA:
        raise ErroVenda(f"Status de proposta inválido: {novo!r}.")
    return editar_proposta(id_proposta, {"STATUS": novo})


def efetivar_proposta(id_proposta: str) -> str:
    """O financiamento deste banco saiu. So para um banco fechado. Devolve o status da venda depois disso (Efetivada
    quando era o ultimo banco fechado a efetivar)."""
    editar_proposta(id_proposta, {"STATUS": PROPOSTA_EFETIVADA})
    propostas, vendas = _ler()
    return vendas.at[_linha_da_venda(vendas, propostas.at[_linha_da_proposta(propostas, id_proposta), "ID_VENDA"]), "STATUS"]


def _marcar_fechamento(id_proposta: str, fechar: bool) -> None:
    sessao_mod.exigir_admin()
    propostas, vendas = _ler()
    linha = _linha_da_proposta(propostas, id_proposta)
    id_venda = propostas.at[linha, "ID_VENDA"]
    linha_venda = _linha_da_venda(vendas, id_venda)
    if vendas.at[linha_venda, "STATUS"] in DESFECHOS_DA_VENDA:
        raise ErroVenda(f"A venda está \"{vendas.at[linha_venda, 'STATUS']}\": reabra a venda antes.")
    fechadas = fechadas_da_venda(vendas.at[linha_venda, "BANCO_ESCOLHIDO"])
    if fechar == (id_proposta in fechadas):
        return
    if fechar:
        if propostas_mod.etapa_status(propostas.at[linha, "STATUS"]) != propostas_mod.ETAPA_APROVADO:
            raise ErroVenda("Só um banco que aprovou pode ser marcado como fechado.")
        meus = equipamentos_cobertos(propostas.at[linha, "EQUIPAMENTO"])
        for outra in fechadas:
            alvo = propostas.index[propostas["ID_PROPOSTA"] == outra]
            if len(alvo) and meus & equipamentos_cobertos(propostas.at[alvo[0], "EQUIPAMENTO"]):
                repetidos = sorted(meus & equipamentos_cobertos(propostas.at[alvo[0], "EQUIPAMENTO"]))
                raise ErroVenda(f"{' e '.join(e.title() for e in repetidos)} já está coberto pelo "
                                f"{propostas.at[alvo[0], 'BANCO']}, que está marcado como fechado.")
        fechadas.append(id_proposta)
    else:
        if propostas.at[linha, "STATUS"] == PROPOSTA_EFETIVADA:
            raise ErroVenda("Este banco já está Efetivado: volte o status dele antes (a setinha ↩).")
        fechadas.remove(id_proposta)
    vendas.at[linha_venda, "BANCO_ESCOLHIDO"] = _SEPARADOR_DE_FECHADAS.join(fechadas)
    historico = [_registro_historico(TIPO_FECHAMENTO, id_proposta, "" if fechar else FECHADA, FECHADA if fechar else "")]
    _recalcular_venda(vendas, propostas, linha_venda, historico)
    bd.escrever_vendas_e_propostas(_caminho(), vendas=vendas, historico_novo=historico)


def fechar_proposta(id_proposta: str) -> None:
    """Marca um banco APROVADO como fechado (o cliente fechou com ele); pode haver varios na venda, mas dois fechados
    nunca cobrem o mesmo equipamento."""
    _marcar_fechamento(id_proposta, True)


def desfazer_fechamento(id_proposta: str) -> None:
    """Desmarca o banco (nao fechou, afinal). Um banco ja Efetivado volta antes pelo "voltar"."""
    _marcar_fechamento(id_proposta, False)


def excluir_proposta(id_proposta: str) -> None:
    """Tira a proposta (um pedido lancado por engano). Um banco fechado nao sai: desmarque antes (a recusa e de
    propostas.remover_proposta)."""
    propostas_mod.remover_proposta(indice_da_proposta(id_proposta))


def mudar_status_venda(id_venda: str, novo: str, *, motivo: str = "") -> None:
    """Os desfechos manuais da venda: Não efetivada / Perdida, com o motivo (opcional) da lista curta. Os outros
    status da venda sao calculados pelos bancos (ver reabrir_venda)."""
    sessao_mod.exigir_admin()
    if novo not in DESFECHOS_DA_VENDA:
        raise ErroVenda(f"O status \"{novo}\" da venda vem dos bancos (o anel e o Efetivado de cada um).")
    if motivo and motivo not in MOTIVOS_DE_PERDA:
        raise ErroVenda(f"Motivo inválido: {motivo!r}.")
    _, vendas = _ler()
    linha = _linha_da_venda(vendas, id_venda)
    antigo = vendas.at[linha, "STATUS"]
    if antigo == novo and vendas.at[linha, "MOTIVO"] == motivo:
        return
    vendas.at[linha, "STATUS"] = novo
    vendas.at[linha, "MOTIVO"] = motivo
    bd.escrever_vendas_e_propostas(
        _caminho(), vendas=vendas, historico_novo=[_registro_historico(TIPO_VENDA, id_venda, antigo, novo, motivo)],
    )


def reabrir_venda(id_venda: str) -> str:
    """Desfaz um desfecho (Não efetivada / Perdida): a venda volta ao status calculado pelos bancos. Devolve qual."""
    sessao_mod.exigir_admin()
    propostas, vendas = _ler()
    linha = _linha_da_venda(vendas, id_venda)
    antigo = vendas.at[linha, "STATUS"]
    if antigo not in DESFECHOS_DA_VENDA:
        raise ErroVenda("A venda não está desistida nem perdida: não há o que reabrir.")
    vendas.at[linha, "STATUS"] = VENDA_AGUARDANDO  # so pra sair do desfecho: o recalculo abaixo da o certo
    vendas.at[linha, "MOTIVO"] = ""
    historico: list[dict] = []
    _recalcular_venda(vendas, propostas, linha, historico)
    novo = vendas.at[linha, "STATUS"]
    bd.escrever_vendas_e_propostas(
        _caminho(), vendas=vendas, historico_novo=[_registro_historico(TIPO_VENDA, id_venda, antigo, novo)],
    )
    return novo


def _pilhas_de_anteriores(historico: pd.DataFrame) -> dict[str, list[str]]:
    """Para cada proposta, os status de onde ela veio, o mais recente no fim - relendo o historico na ordem em que foi
    gravado: cada troca empilha o status de onde saiu; uma troca que volta ao status do topo e uma volta e
    desempilha. Assim o "voltar" recua um passo por vez (B -> A, depois A -> o de antes), e nunca fica indo e
    voltando entre os dois ultimos. Marcar/desmarcar um banco (fechamento) nao e troca de status: fica de fora."""
    pilhas: dict[str, list[str]] = {}
    for tipo, id_, de, para in zip(historico["TIPO"], historico["ID"], historico["DE"], historico["PARA"]):
        if tipo != TIPO_PROPOSTA or de == para:
            continue
        pilha = pilhas.setdefault(id_, [])
        if pilha and para == pilha[-1]:
            pilha.pop()
        elif de:
            pilha.append(de)
    return pilhas


def _anterior(id_: str) -> str | None:
    pilha = _pilhas_de_anteriores(bd.ler_historico(_caminho())).get(id_, [])
    return pilha[-1] if pilha else None


def voltar_venda(id_venda: str) -> str:
    """O "↩" da venda: so existe num desfecho, e reabre (os outros status vem dos bancos). Devolve para onde voltou."""
    return reabrir_venda(id_venda)


def voltar_proposta(id_proposta: str) -> bool:
    """Volta a proposta ao status de antes da ultima troca. Devolve o mesmo que mudar_status_proposta."""
    anterior = _anterior(id_proposta)
    if anterior is None or anterior not in [*STATUS_DA_PROPOSTA, PROPOSTA_EFETIVADA]:
        raise ErroVenda("Não há um status anterior para onde voltar.")
    return mudar_status_proposta(id_proposta, anterior)


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
    fechada: bool  # o cliente fechou com este banco (o anel)
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
    fechadas: tuple[str, ...]  # os ID_PROPOSTA dos bancos fechados
    data_criacao: pd.Timestamp | None
    dias_na_etapa: int | None  # desde a ultima mudanca de status da venda (sem historico: desde a criacao)
    observacoes: str
    propostas: tuple[PropostaNaVenda, ...]
    anterior: str | None = None  # num desfecho: o status para onde reabrir (None: nao ha "voltar")

    @property
    def finalizada(self) -> bool:
        return self.status in VENDA_FINALIZADA

    @property
    def parada(self) -> bool:
        return not self.finalizada and (self.dias_na_etapa or 0) >= DIAS_PARA_ALERTA

    def aprovadas(self) -> list[PropostaNaVenda]:
        return [p for p in self.propostas if propostas_mod.etapa_status(p.status) == propostas_mod.ETAPA_APROVADO]

    def bancos_fechados(self) -> list[PropostaNaVenda]:
        return [p for p in self.propostas if p.fechada]

    def efetivados(self) -> list[PropostaNaVenda]:
        return [p for p in self.bancos_fechados() if p.status == PROPOSTA_EFETIVADA]


def _dias_desde(momento, hoje: pd.Timestamp) -> int | None:
    return (hoje - pd.Timestamp(momento).normalize()).days if pd.notna(momento) else None


def _numero_ou_none(valor):
    return None if valor is None or valor == "" or pd.isna(valor) else valor


_ESPERANDO_RESPOSTA = {propostas_mod.ETAPA_EM_ANALISE, propostas_mod.ETAPA_PRE_APROVADO}


def _proposta_da_linha(indice, p: pd.Series, ultimas: dict, pilhas: dict, fechadas: list[str],
                       hoje: pd.Timestamp) -> PropostaNaVenda:
    """Uma linha da aba PROPOSTAS pronta pra tela. Os dias esperando resposta contam da ultima troca de status no
    HISTÓRICO e, sem ela (ou sem ID_PROPOSTA, nas de antes das vendas), da DATA da proposta."""
    id_proposta = p.get("ID_PROPOSTA") or ""
    dias = None
    if propostas_mod.etapa_status(p["STATUS"]) in _ESPERANDO_RESPOSTA:
        dias = _dias_desde(ultimas.get(id_proposta, p["DATA"]) if id_proposta else p["DATA"], hoje)
    meses = _numero_ou_none(p["MESES"])
    anterior = (pilhas.get(id_proposta) or [None])[-1] if id_proposta else None
    carencia = _numero_ou_none(p.get("CARÊNCIA (DIAS)"))
    return PropostaNaVenda(
        id_proposta, int(indice), p["BANCO"], p["STATUS"], _numero_ou_none(p["VALOR (R$)"]),
        int(meses) if meses is not None else None, p["DATA"] if pd.notna(p["DATA"]) else None,
        p["EQUIPAMENTO"], bool(id_proposta) and id_proposta in fechadas, dias,
        # status de antes das vendas nao volta
        anterior if anterior in [*STATUS_DA_PROPOSTA, PROPOSTA_EFETIVADA] else None,
        int(carencia) if carencia is not None else None, _numero_ou_none(p.get("PARCELA (R$)")),
    )


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

    resultado = []
    for _, v in vendas.iterrows():
        da_venda = propostas[propostas["ID_VENDA"] == v["ID_VENDA"]].sort_values("DATA", kind="stable")
        fechadas = [i for i in fechadas_da_venda(v["BANCO_ESCOLHIDO"]) if i in set(da_venda["ID_PROPOSTA"])]
        itens = [_proposta_da_linha(indice, p, ultimas, pilhas, fechadas, hoje) for indice, p in da_venda.iterrows()]
        nome, vendedor = por_cpf.get(apenas_digitos(v["CPF"]), ("", ""))
        criacao = v["DATA_CRIACAO"] if pd.notna(v["DATA_CRIACAO"]) else None
        # o status vem dos bancos (uma venda gravada com etapas de antes - "Banco escolhido", "Nota fiscal" - le certo)
        calculado = status_calculado([p.status for p in itens if p.fechada])
        status = v["STATUS"] if v["STATUS"] in DESFECHOS_DA_VENDA else calculado
        resultado.append(ResumoDaVenda(
            v["ID_VENDA"], v["CPF"], nome, vendedor, v["EQUIPAMENTOS"], status, v["MOTIVO"],
            tuple(fechadas), criacao, _dias_desde(ultimas.get(v["ID_VENDA"], criacao), hoje),
            v["OBSERVAÇÕES"], tuple(itens), calculado if status in DESFECHOS_DA_VENDA else None,
        ))
    resultado.sort(key=lambda r: r.data_criacao if r.data_criacao is not None else pd.Timestamp.min, reverse=True)
    return resultado


@dataclass(frozen=True)
class PropostaNaLista:
    """Uma proposta como Todas as Propostas (e a Ficha, nas de antes das vendas) a mostra: um card por pedido a um
    banco, com a venda dele para as acoes do card (as mesmas do card da venda)."""
    proposta: PropostaNaVenda
    venda: ResumoDaVenda | None  # None: de antes das vendas (ou a leitura do VENDEDOR, que ainda nao tem as vendas)
    cpf: str
    cliente: str
    vendedor: str


def propostas_na_lista(propostas: pd.DataFrame, vendas=(), historico: pd.DataFrame | None = None,
                       hoje: date | None = None) -> dict[int, PropostaNaLista]:
    """Para cada proposta de `propostas` (as ja lidas, pelo indice = posicao real no arquivo), o que o card dela
    mostra. `vendas` (listar_vendas) da a venda de cada uma e o resto do que o card da venda mostra (anel, voltar,
    dias esperando); as que nao estao em nenhuma delas saem da propria linha, com os dias esperando pelo `historico`
    (sem ele, ou sem ID_PROPOSTA, contados da DATA)."""
    hoje = pd.Timestamp(hoje or date.today())
    na_venda = {p.indice: (p, v) for v in vendas for p in v.propostas}
    ultimas = _ultimas_mudancas(historico) if historico is not None else {}
    resultado = {}
    for indice, linha in propostas.iterrows():
        proposta, venda = na_venda.get(int(indice), (None, None))
        if proposta is None or not proposta.id or proposta.id != (linha.get("ID_PROPOSTA") or ""):  # outra leitura
            proposta, venda = _proposta_da_linha(indice, linha, ultimas, {}, [], hoje), None
        cliente = venda.cliente if venda is not None else (linha.get("CLIENTE") or "")
        vendedor = venda.vendedor if venda is not None else (linha.get("VENDEDOR") or "")
        resultado[int(indice)] = PropostaNaLista(proposta, venda, linha["CPF"], cliente, vendedor)
    return resultado


def propostas_na_lista_do_arquivo(propostas: pd.DataFrame, hoje: date | None = None) -> dict[int, PropostaNaLista]:
    """propostas_na_lista com as vendas e o HISTÓRICO do arquivo (o ADMIN, em Todas as Propostas)."""
    return propostas_na_lista(propostas, listar_vendas(hoje), bd.ler_historico(_caminho()), hoje)


def vendas_do_cliente(cpf: str, hoje: date | None = None) -> list[ResumoDaVenda]:
    """As vendas de um cliente (a mais recente primeiro): a Ficha de Cliente."""
    alvo = apenas_digitos(cpf)
    return [v for v in listar_vendas(hoje) if apenas_digitos(v.cpf) == alvo]


VENDA_EM_ABERTO = {VENDA_AGUARDANDO, VENDA_EM_ANDAMENTO}


def vendas_em_aberto_do_cliente(cpf: str, hoje: date | None = None) -> list[ResumoDaVenda]:
    """As vendas do cliente que ainda aceitam mais um pedido a um banco (Aguardando bancos e Em andamento), a mais
    recente primeiro: as que o "+ Nova proposta" oferece. Efetivada, Não efetivada e Perdida ficam de fora."""
    em_aberto = [v for v in vendas_do_cliente(cpf, hoje) if v.status in VENDA_EM_ABERTO]
    # a data de criacao nao tem hora: no mesmo dia, a criada por ultimo (mais embaixo no arquivo) vem primeiro - e a
    # que o "+ Nova proposta" marca sozinho
    return sorted(reversed(em_aberto), key=lambda v: v.data_criacao if v.data_criacao is not None else pd.Timestamp.min,
                  reverse=True)


def rotulo_da_venda(venda: ResumoDaVenda) -> str:
    """"Venda de 02/10 · Cadeira X + Laser Y · Em andamento · 2 bancos": a venda na escolha do "+ Nova proposta"."""
    quando = f"Venda de {venda.data_criacao:%d/%m}" if venda.data_criacao is not None else "Venda sem data"
    bancos = len(venda.propostas)
    quantos = "nenhum banco" if not bancos else f"{bancos} banco{'s' if bancos > 1 else ''}"
    return " · ".join(p for p in (quando, venda.equipamentos, venda.status, quantos) if p)


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
