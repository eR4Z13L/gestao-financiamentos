"""Regras de negocio para PROPOSTAS: cadastro, atualizacao de status e
classificacao para o dashboard.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from datetime import date
from typing import Mapping

import pandas as pd

from config import CAMINHO_XLSX
from core import clientes as clientes_mod
from core import data_store as bd
from core import sessao as sessao_mod
from core.formatting import dias_do_tempo
from core.validators import apenas_digitos

STATUS_EM_ANALISE = "Em Análise"
STATUS_PRE_APROVADO = "Pré-aprovado"
STATUS_APROVADO = "Aprovado"
STATUS_NF_ANEXADA = "Nota Fiscal Anexada"
STATUS_GARANTIA_ASSINADA = "Garantia Assinada"
STATUS_EFETIVADO = "Efetivado"
# "Não efetivado": o banco aprovou mas o cliente NAO seguiu com a compra - desfecho
# FINAL, so alcancavel a partir de "Aprovado" (adicionar_proposta/atualizar_proposta
# travam qualquer outra origem). Nao confundir com a metrica antiga
# "aprovadas_nao_efetivadas" de core/dashboard.py, que conta quem ainda esta
# "Aprovado" (pendente, podendo virar venda) - este status aqui e o oposto: o
# processo JA acabou sem virar venda.
STATUS_NAO_EFETIVADO = "Não efetivado"
# "Encerrada": a proposta parou de fazer sentido porque OUTRA proposta do mesmo
# cliente + equipamento (a mesma venda, em outro banco) ja foi efetivada. Normalmente
# gravada pelo fluxo de "perguntar_e_encerrar" (desktop/widgets/encerrar_propostas_da_venda.py),
# mas pode ser escolhida a mao tambem (ex.: o admin sabe de outro motivo pra fechar).
STATUS_PROPOSTA_ENCERRADA = "Encerrada"
STATUS_NEGADO = "Negado"

# Ordem sugerida nos formularios/dropdowns (funil aproximado da proposta).
# "Efetivado" (compra concluida) e a ultima etapa do lado positivo: vem depois
# de "Aprovado" (e das etapas de nota fiscal/garantia); "Não efetivado" e
# "Encerrada" sao os outros dois jeitos de uma proposta aprovada nao virar
# venda, e ficam antes do "Negado" (que nunca foi aprovado).
STATUS_OPCOES = [
    STATUS_EM_ANALISE,
    STATUS_PRE_APROVADO,
    STATUS_APROVADO,
    STATUS_NF_ANEXADA,
    STATUS_GARANTIA_ASSINADA,
    STATUS_EFETIVADO,
    STATUS_NAO_EFETIVADO,
    STATUS_PROPOSTA_ENCERRADA,
    STATUS_NEGADO,
]

# Reaproveita as mesmas listas de "palavras" usadas pro calculo de TEMPO em
# data_store.py, pra nunca ficar dessincronizada dali.
_PALAVRAS_NEGADO = bd.PALAVRAS_STATUS_NEGADO
_PALAVRAS_EFETIVADO = bd.PALAVRAS_STATUS_EFETIVADO
_PALAVRAS_NAO_EFETIVADO = bd.PALAVRAS_STATUS_NAO_EFETIVADO
_PALAVRAS_ENCERRADA = bd.PALAVRAS_STATUS_ENCERRADA
_PALAVRAS_APROVADO_NAO_EFETIVADO = {"APROVADO", "APROVADA"}
_PALAVRAS_EM_ANALISE = {"EM ANÁLISE", "EM ANALISE", "ANÁLISE", "ANALISE", "PENDENTE"}
# Etapas conhecidas do funil depois da aprovacao inicial - so estas contam
# como "Aprovado" nas taxas gerais. Um status desconhecido/mal digitado (que
# nao e nenhuma das etapas oficiais, nem negado, nem em analise) NAO vira
# "Aprovado" por omissao - isso inflaria a taxa de aprovacao e o valor
# aprovado do dashboard com dado ruim. Ele cai em "Não identificado".
# "Efetivado" e "Não efetivado" contam como aprovado: o banco aprovou os dois -
# separar essas etapas nao pode derrubar a taxa de aprovacao. "Encerrada" fica
# de FORA (ver categoria_status): pode ter sido fechada sem nunca ter sido
# decidida por aquele banco.
_PALAVRAS_PRE_APROVADO = {"PRÉ-APROVADO", "PRE-APROVADO", "PRÉ APROVADO", "PRE APROVADO"}
_PALAVRAS_NF_ANEXADA = {"NOTA FISCAL ANEXADA"}
_PALAVRAS_GARANTIA_ASSINADA = {"GARANTIA ASSINADA"}
_PALAVRAS_APROVADO = (
    _PALAVRAS_APROVADO_NAO_EFETIVADO
    | _PALAVRAS_EFETIVADO
    | _PALAVRAS_NAO_EFETIVADO
    | _PALAVRAS_PRE_APROVADO
    | _PALAVRAS_NF_ANEXADA
    | _PALAVRAS_GARANTIA_ASSINADA
)

# Etapas "finas" do funil (uma por status oficial), pra quem precisa distinguir
# alem das 3 categorias do dashboard - ex.: a cor do status nos cards.
ETAPA_SEM_STATUS = ""
ETAPA_EM_ANALISE = "em_analise"
ETAPA_PRE_APROVADO = "pre_aprovado"
ETAPA_APROVADO = "aprovado"
ETAPA_NF_ANEXADA = "nota_fiscal"
ETAPA_GARANTIA_ASSINADA = "garantia"
ETAPA_EFETIVADO = "efetivado"
ETAPA_NAO_EFETIVADO = "nao_efetivado"
ETAPA_PROPOSTA_ENCERRADA = "encerrada"
ETAPA_NEGADO = "negado"
ETAPA_DESCONHECIDA = "desconhecida"

# Ordem do funil (do inicio ao fim, depois os desfechos "fora do funil" - Nao
# efetivado, Encerrada e Negado -, e por ultimo o que nao da pra classificar) -
# usada na contagem por status do topo de Todas as Propostas.
ETAPAS_EM_ORDEM = [
    ETAPA_EM_ANALISE,
    ETAPA_PRE_APROVADO,
    ETAPA_APROVADO,
    ETAPA_NF_ANEXADA,
    ETAPA_GARANTIA_ASSINADA,
    ETAPA_EFETIVADO,
    ETAPA_NAO_EFETIVADO,
    ETAPA_PROPOSTA_ENCERRADA,
    ETAPA_NEGADO,
    ETAPA_DESCONHECIDA,
    ETAPA_SEM_STATUS,
]


class ErroProposta(Exception):
    pass


def categoria_status(status: str) -> str:
    """Classifica um status (mesmo um customizado/novo, desde que seja uma
    das etapas oficiais do funil) em 'Negado', 'Em Análise', 'Aprovado' ou
    'Encerrada' - as categorias usadas nas taxas do dashboard. Um status vazio
    devolve "" (sem status); um status preenchido mas desconhecido devolve
    'Não identificado' - nenhum destes conta como aprovacao. 'Encerrada' fica
    de FORA de 'Aprovado' de proposito: a proposta pode ter sido fechada sem
    nunca ter sido decidida por aquele banco (ver STATUS_PROPOSTA_ENCERRADA) -
    contá-la como aprovada ou negada inflaria a taxa errada.
    """
    s = (status or "").strip().upper()
    if not s:
        return ""
    if s in _PALAVRAS_NEGADO:
        return "Negado"
    if s in _PALAVRAS_ENCERRADA:
        return "Encerrada"
    if s in _PALAVRAS_EM_ANALISE:
        return "Em Análise"
    if s in _PALAVRAS_APROVADO:
        return "Aprovado"
    return "Não identificado"


def etapa_status(status: str) -> str:
    """Etapa do funil a que o status pertence (uma das constantes ETAPA_*),
    sem diferenciar maiusculas/acentos das grafias legadas ("APROVADO",
    "EM ANALISE"...). Status vazio -> ETAPA_SEM_STATUS; preenchido mas
    desconhecido -> ETAPA_DESCONHECIDA (nunca chuta uma etapa)."""
    s = (status or "").strip().upper()
    if not s:
        return ETAPA_SEM_STATUS
    for etapa, palavras in (
        (ETAPA_NEGADO, _PALAVRAS_NEGADO),
        (ETAPA_PROPOSTA_ENCERRADA, _PALAVRAS_ENCERRADA),
        (ETAPA_NAO_EFETIVADO, _PALAVRAS_NAO_EFETIVADO),
        (ETAPA_EFETIVADO, _PALAVRAS_EFETIVADO),
        (ETAPA_APROVADO, _PALAVRAS_APROVADO_NAO_EFETIVADO),
        (ETAPA_PRE_APROVADO, _PALAVRAS_PRE_APROVADO),
        (ETAPA_NF_ANEXADA, _PALAVRAS_NF_ANEXADA),
        (ETAPA_GARANTIA_ASSINADA, _PALAVRAS_GARANTIA_ASSINADA),
        (ETAPA_EM_ANALISE, _PALAVRAS_EM_ANALISE),
    ):
        if s in palavras:
            return etapa
    return ETAPA_DESCONHECIDA


def eh_efetivado(status: str) -> bool:
    """Compra concluida (status "Efetivado"), sem diferenciar maiusculas."""
    return (status or "").strip().upper() in _PALAVRAS_EFETIVADO


def eh_nao_efetivado(status: str) -> bool:
    """Status "Não efetivado": o banco aprovou mas o cliente NAO seguiu com a
    compra (desfecho final, diferente de so "ainda nao efetivou" - ver
    eh_aprovado_nao_efetivado, que e o status "Aprovado" ainda em aberto)."""
    return (status or "").strip().upper() in _PALAVRAS_NAO_EFETIVADO


def eh_proposta_encerrada(status: str) -> bool:
    """Status "Encerrada": fechada porque outra proposta do MESMO cliente +
    equipamento ja foi efetivada em outro banco."""
    return (status or "").strip().upper() in _PALAVRAS_ENCERRADA


def eh_aprovado_nao_efetivado(status: str) -> bool:
    """Status exatamente "Aprovado" - aprovada pelo banco mas AINDA em aberto,
    podendo virar compra a qualquer momento. As etapas Pre-aprovado / Nota
    Fiscal Anexada / Garantia Assinada NAO entram aqui: sao outras etapas do
    funil, com nome proprio. NAO CONFUNDIR com eh_nao_efetivado: aquele e o
    status "Não efetivado", um desfecho FINAL (o cliente ja desistiu) - este
    aqui e so "pendente" (o nome antigo desta funcao/metrica e antes do status
    "Não efetivado" ter sido criado)."""
    return (status or "").strip().upper() in _PALAVRAS_APROVADO_NAO_EFETIVADO


def esta_em_aberto(status: str) -> bool:
    """Proposta ainda NAO encerrada: tudo que nao e um desfecho final (Efetivado
    ou Negado/Reprovado/Cancelado). "Aprovado" segue em aberto (continua contando
    dias ate virar Efetivado, como na coluna TEMPO) e a sem status tambem: nao
    esta encerrada."""
    texto = status if isinstance(status, str) else ""
    return texto.strip().upper() not in bd.STATUS_ENCERRADO


# Uma proposta em aberto ha MAIS que isto (em dias) conta como "parada": e o limite do selo
# na barra lateral e, depois, da lista "Precisa de atencao" do dashboard - um numero so, pros
# dois nunca discordarem.
DIAS_PROPOSTA_PARADA = 7


def contar_paradas(propostas: pd.DataFrame, dias: int | None = None) -> int:
    """Quantas das `propostas` (como listar_propostas devolve, com STATUS e TEMPO) estao em
    aberto ha mais de `dias` dias (padrao: DIAS_PROPOSTA_PARADA, lido na hora da chamada).
    Sem dias calculaveis na coluna TEMPO (vazia, "Encerrado", texto desconhecido) ou com a
    data no futuro, a proposta nao conta: nunca se chuta."""
    if dias is None:
        dias = DIAS_PROPOSTA_PARADA
    if propostas.empty:
        return 0
    em_aberto = propostas["STATUS"].map(esta_em_aberto).astype(bool)
    dias_parada = pd.to_numeric(propostas["TEMPO"].map(dias_do_tempo), errors="coerce")
    return int((em_aberto & (dias_parada > dias)).sum())


def cpfs_com_proposta_em_aberto() -> set[str]:
    """CPF/CNPJ (so os digitos) de quem tem ao menos UMA proposta em aberto -
    pra marcar, na lista de clientes, quem esta com processo ativo. Usa a mesma
    fonte e o mesmo filtro de vendedor de listar_propostas (o VENDEDOR so ve os
    proprios)."""
    df = _ler_da_fonte_ativa()
    # astype(bool): sem nenhuma proposta o map() devolve uma serie vazia SEM tipo
    # booleano, e o pandas a trataria como selecao de COLUNAS (sumindo com o CPF)
    em_aberto = df["STATUS"].map(esta_em_aberto).astype(bool)
    return {digitos for digitos in df.loc[em_aberto, "CPF"].map(apenas_digitos) if digitos}


def _ordenar_por_data_desc(df: pd.DataFrame) -> pd.DataFrame:
    """Ordena por DATA (mais recente primeiro) sem quebrar se a coluna tiver
    uma mistura de datas de verdade e texto (dado legado digitado errado na
    planilha) - comparar datetime com str diretamente faria sort_values
    estourar TypeError. Datas invalidas/texto vao pro final, como se fossem
    as mais antigas. Usa uma coluna auxiliar soh pra ordenar - a coluna DATA
    devolvida continua com os valores originais (formatar_data ja sabe
    mostrar "—" pro que nao for uma data de verdade).
    """
    chave = pd.to_datetime(df["DATA"], errors="coerce")
    return (
        df.assign(_CHAVE_ORDENACAO=chave)
        .sort_values("_CHAVE_ORDENACAO", ascending=False, na_position="last")
        .drop(columns="_CHAVE_ORDENACAO")
    )


def _ler_da_fonte_ativa() -> pd.DataFrame:
    """ADMIN sempre le do .xlsx local (funciona offline); VENDEDOR le do
    Google Sheets (pode estar em outro computador, sem acesso ao arquivo
    local do ADMIN) - ver core/data_store_sheets.py. Nos dois casos, so
    devolve as propostas do vendedor logado (sessao_mod.eh_vendedor())."""
    if sessao_mod.eh_vendedor():
        from core import data_store_sheets as bd_sheets

        df = bd_sheets.ler_propostas()
    else:
        df = bd.ler_propostas(CAMINHO_XLSX)
    return sessao_mod.filtrar_por_vendedor_logado(df)


def listar_propostas() -> pd.DataFrame:
    """O indice do DataFrame retornado corresponde a posicao real da proposta
    no arquivo (a mesma que atualizar_proposta espera) - por isso NAO e
    resetado depois do sort. Nao reordene esse DataFrame antes de usar o
    indice para editar uma linha. Atencao: com VENDEDOR logado, o indice
    ainda e a posicao real no arquivo/planilha completa - so a LISTAGEM e
    filtrada, e como VENDEDOR nunca escreve (core.sessao.exigir_admin() nas
    funcoes de escrita), esse indice nunca chega a ser usado pra editar.
    """
    df = _ler_da_fonte_ativa()
    return _ordenar_por_data_desc(df)


def historico_por_cpf(cpf: str) -> pd.DataFrame:
    """Mesma observacao de listar_propostas: o indice reflete a posicao real
    no arquivo, necessaria para atualizar_proposta().
    """
    df = _ler_da_fonte_ativa()
    alvo = apenas_digitos(cpf)
    filtrado = df[df["CPF"].map(apenas_digitos) == alvo]
    return _ordenar_por_data_desc(filtrado)


ORDENACAO_DATA_RECENTE = "data_recente"
ORDENACAO_DATA_ANTIGA = "data_antiga"
ORDENACAO_VALOR_MAIOR = "valor_maior"
ORDENACAO_VALOR_MENOR = "valor_menor"
ORDENACAO_TEMPO_PARADO = "tempo_parado"
# (chave, rotulo) na ordem em que a tela deve listar
ORDENACAO_OPCOES = [
    (ORDENACAO_DATA_RECENTE, "Data (mais recente primeiro)"),
    (ORDENACAO_DATA_ANTIGA, "Data (mais antiga primeiro)"),
    (ORDENACAO_VALOR_MAIOR, "Valor (maior primeiro)"),
    (ORDENACAO_VALOR_MENOR, "Valor (menor primeiro)"),
    (ORDENACAO_TEMPO_PARADO, "Tempo parado (mais dias em aberto primeiro)"),
]


def ordenar(df: pd.DataFrame, ordenacao: str = ORDENACAO_DATA_RECENTE) -> pd.DataFrame:
    """Reordena `df` SEM mexer no indice (que e a posicao real da proposta no
    arquivo - ver listar_propostas). Em qualquer ordenacao, o que nao tem o dado
    (sem data, sem valor, sem TEMPO) vai pro fim, e o empate desempata pela
    data mais recente (e, na mesma data, pela proposta cadastrada por ultimo)."""
    if ordenacao not in {chave for chave, _ in ORDENACAO_OPCOES}:
        raise ValueError(f"Ordenação desconhecida: {ordenacao!r}")

    # colunas auxiliares so pra ordenar; as devolvidas continuam com os valores originais
    auxiliar = df.assign(_DATA=pd.to_datetime(df["DATA"], errors="coerce"), _POSICAO=df.index)

    if ordenacao in (ORDENACAO_DATA_RECENTE, ORDENACAO_DATA_ANTIGA):
        recente = ordenacao == ORDENACAO_DATA_RECENTE
        colunas, crescente = ["_DATA", "_POSICAO"], [not recente, not recente]
    elif ordenacao in (ORDENACAO_VALOR_MAIOR, ORDENACAO_VALOR_MENOR):
        colunas, crescente = ["VALOR (R$)", "_DATA", "_POSICAO"], [ordenacao == ORDENACAO_VALOR_MENOR, False, False]
    else:
        # tempo parado: primeiro quem tem dias em aberto (mais dias antes), depois
        # os "Encerrado", por ultimo os sem TEMPO
        dias = pd.to_numeric(df["TEMPO"].map(dias_do_tempo), errors="coerce")
        sem_dias = dias.isna()
        encerrado = df["TEMPO"].map(lambda t: isinstance(t, str) and t.strip().upper() == "ENCERRADO")
        grupo = sem_dias.astype(int) + (sem_dias & ~encerrado).astype(int)  # 0 = com dias, 1 = Encerrado, 2 = sem TEMPO
        auxiliar = auxiliar.assign(_DIAS=dias, _GRUPO=grupo)
        colunas, crescente = ["_GRUPO", "_DIAS", "_DATA", "_POSICAO"], [True, False, False, False]

    auxiliar = auxiliar.sort_values(colunas, ascending=crescente, na_position="last")
    return df.loc[auxiliar.index]


def _mesmo_texto(serie: pd.Series, valor: str) -> pd.Series:
    """Igualdade sem diferenciar maiusculas nem espacos nas pontas (a planilha
    tem o mesmo banco escrito "Hubcred BV" e "HUBCRED BV")."""
    return serie.str.strip().str.upper() == valor.strip().upper()


def filtrar_propostas(
    df: pd.DataFrame,
    termo: str = "",
    *,
    status: str | None = None,
    vendedor: str | None = None,
    banco: str | None = None,
    equipamento: str | None = None,
    data_de: date | pd.Timestamp | None = None,
    data_ate: date | pd.Timestamp | None = None,
    ordenacao: str = ORDENACAO_DATA_RECENTE,
) -> pd.DataFrame:
    """Aplica em `df` (as propostas ja lidas) a busca livre + os filtros que
    vierem preenchidos, TODOS combinados (E), e devolve o resultado na
    `ordenacao` pedida:
    - termo: cliente, banco ou equipamento (contem, sem diferenciar maiusculas)
      ou CPF/CNPJ (so os digitos);
    - status: igualdade exata;
    - vendedor / banco / equipamento: igualdade, sem diferenciar maiusculas;
    - data_de / data_ate: periodo da DATA da proposta, com as duas pontas
      INCLUIDAS; proposta sem data nunca entra num periodo.
    Filtro None (ou "") = sem filtro. O indice do resultado continua sendo a
    posicao real da proposta no arquivo."""
    mascara = pd.Series(True, index=df.index)

    termo = (termo or "").strip()
    if termo:
        # regex=False: o que a pessoa digita e texto, nao expressao regular
        # ("(" ou "C++" estourariam um erro de regex)
        termo_upper = termo.upper()
        digitos = apenas_digitos(termo)
        achou = (
            df["CLIENTE"].str.upper().str.contains(termo_upper, na=False, regex=False)
            | df["BANCO"].str.upper().str.contains(termo_upper, na=False, regex=False)
            | df["EQUIPAMENTO"].str.upper().str.contains(termo_upper, na=False, regex=False)
        )
        if digitos:
            achou = achou | df["CPF"].map(apenas_digitos).str.contains(digitos, na=False, regex=False)
        mascara &= achou

    if status:
        mascara &= df["STATUS"] == status
    if vendedor:
        mascara &= _mesmo_texto(df["VENDEDOR"], vendedor)
    if banco:
        mascara &= _mesmo_texto(df["BANCO"], banco)
    if equipamento:
        mascara &= _mesmo_texto(df["EQUIPAMENTO"], equipamento)

    if data_de is not None or data_ate is not None:
        datas = pd.to_datetime(df["DATA"], errors="coerce").dt.normalize()
        if data_de is not None:
            mascara &= datas >= pd.Timestamp(data_de).normalize()
        if data_ate is not None:
            mascara &= datas <= pd.Timestamp(data_ate).normalize()

    return ordenar(df[mascara], ordenacao)


def _chave_alfabetica(texto: str) -> str:
    """Maiusculas e SEM acento, pra listar como um dicionario ("ÁGUIA" junto
    do "A", nao depois do "Z")."""
    return "".join(c for c in unicodedata.normalize("NFD", texto.upper()) if unicodedata.category(c) != "Mn")


def valores_distintos(df: pd.DataFrame, coluna: str) -> list[str]:
    """Valores usados em `coluna` (ex.: "BANCO"), em ordem alfabetica e sem os
    vazios, pra alimentar um filtro. Grafias que so diferem em maiusculas ou
    espacos ("Hubcred BV" e "HUBCRED BV") viram UMA opcao - a mais usada (no
    empate, a primeira em ordem alfabetica, que costuma ser a em maiusculas)."""
    grafias: dict[str, Counter] = {}
    for bruto in df[coluna]:
        if not isinstance(bruto, str):
            continue
        texto = bruto.strip()
        if texto:
            grafias.setdefault(texto.upper(), Counter())[texto] += 1
    escolhidas = [min(contagem, key=lambda t: (-contagem[t], t)) for contagem in grafias.values()]
    return sorted(escolhidas, key=_chave_alfabetica)


def _converter_valor(valor):
    """Aceita um numero ja pronto (vindo do QDoubleSpinBox) ou texto no
    formato brasileiro ("1.500,00") ou americano ("1500.00"). Devolve None se
    nao for um numero valido em nenhum dos dois formatos - quem chama decide
    a mensagem de erro, em vez de deixar o ValueError do float() estourar sem
    tratamento (e sem mensagem clara) la na tela.
    """
    if valor is None or valor == "" or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip()
    if not texto:
        return None
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return None


def _validar_campos(campos: dict, *, valor_obrigatorio: bool = True) -> None:
    cpf = (campos.get("CPF") or "").strip()
    equipamento = (campos.get("EQUIPAMENTO") or "").strip()

    if not cpf:
        raise ErroProposta("CPF do cliente é obrigatório.")
    if clientes_mod.buscar_por_cpf(cpf) is None:
        raise ErroProposta(f"Não existe cliente cadastrado com o CPF {cpf}. Cadastre o cliente primeiro.")

    valor_bruto = campos.get("VALOR (R$)")
    valor_ausente = valor_bruto is None or valor_bruto == "" or (isinstance(valor_bruto, float) and pd.isna(valor_bruto))
    if valor_ausente:
        # proposta antiga sem VALOR preenchido - so bloqueia se for um
        # cadastro novo (valor_obrigatorio=True); editar uma proposta que ja
        # nao tinha valor (ex: soh pra mudar o status) nao pode ficar travada
        # exigindo preencher o valor primeiro.
        if valor_obrigatorio:
            raise ErroProposta("Valor solicitado deve ser maior que zero.")
    else:
        valor = _converter_valor(valor_bruto)
        if valor is None:
            raise ErroProposta("Valor solicitado inválido - use um número (ex: 1500 ou 1.500,00).")
        if valor <= 0:
            raise ErroProposta("Valor solicitado deve ser maior que zero.")
        campos["VALOR (R$)"] = valor

    if not equipamento:
        raise ErroProposta("Equipamento é obrigatório.")


def dados_para_duplicar(proposta: Mapping, hoje: date | None = None) -> dict:
    """Ponto de partida de uma proposta NOVA a partir de uma existente - o caso
    comum e reenviar a mesma proposta a outro banco depois de uma negativa.
    Leva cliente, equipamento, valor, meses e observacoes; a data e a de hoje, o
    banco fica em branco (quem duplica escolhe o novo) e o status volta a "Em
    Analise" (nunca herda Negado/Aprovado). Leva tambem a venda (ID_VENDA): gravar a copia manda o mesmo
    negocio a outro banco (core/vendas.py). Nao grava nada, e a original continua como estava."""

    def _texto(valor) -> str:
        return valor if isinstance(valor, str) else ""

    def _numero(valor):
        return None if valor is None or pd.isna(valor) else valor

    return {
        "DATA": pd.Timestamp(hoje or date.today()),
        "CPF": _texto(proposta.get("CPF")),
        "VALOR (R$)": _numero(proposta.get("VALOR (R$)")),
        "MESES": _numero(proposta.get("MESES")),
        "EQUIPAMENTO": _texto(proposta.get("EQUIPAMENTO")),
        "BANCO": "",
        "STATUS": STATUS_EM_ANALISE,
        "OBSERVAÇÕES": _texto(proposta.get("OBSERVAÇÕES")),
        "ID_VENDA": _texto(proposta.get("ID_VENDA")),
    }


def _normalizar_para_comparar(valor):
    """Vazio (None, NaN, NaT, "" ou so espacos) vira None; texto perde os espacos das
    pontas; numero vira float. Assim a mesma celula lida em momentos diferentes (ou
    vinda de um DataFrame e de outro) compara igual."""
    if valor is None:
        return None
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(valor, str):
        return valor.strip() or None
    if isinstance(valor, (int, float)):
        return float(valor)
    return valor


def linha_confere(atual: Mapping, esperado: Mapping) -> bool:
    """A proposta gravada no arquivo ainda e a que a tela mostrava? Compara os campos
    editaveis (o resto e calculado). Serve pra nao gravar/excluir por cima de OUTRA
    proposta quando a posicao (indice) ficou velha - ex.: a tela ficou aberta com um
    card em edicao enquanto outra tela excluiu uma proposta e as posicoes andaram."""
    return all(
        _normalizar_para_comparar(atual.get(coluna)) == _normalizar_para_comparar(esperado.get(coluna))
        for coluna in bd.PROPOSTAS_COLUNAS_EDITAVEIS
    )


_MENSAGEM_PROPOSTA_MUDOU = (
    "Esta proposta foi alterada ou excluída desde que foi aberta (por outra tela?). "
    "Recarregue a lista e abra a proposta de novo antes de continuar."
)


def adicionar_proposta(campos: dict) -> int:
    """`campos` deve conter DATA, CPF, VALOR (R$), MESES, EQUIPAMENTO, BANCO,
    STATUS, OBSERVAÇÕES. DATA e STATUS tem valor padrao se nao informados.
    Devolve a posicao real da proposta nova no arquivo (a que editar/excluir usam)."""
    sessao_mod.exigir_admin()
    campos = dict(campos)
    campos.setdefault("DATA", pd.Timestamp(date.today()))
    campos.setdefault("STATUS", STATUS_EM_ANALISE)
    campos["CPF"] = (campos.get("CPF") or "").strip()

    if eh_nao_efetivado(campos.get("STATUS")):
        # uma proposta nova nunca passou por "Aprovado" - "Não efetivado" so
        # faz sentido como uma MUDANCA de uma proposta que ja foi aprovada
        raise ErroProposta('O status "Não efetivado" só pode vir de uma proposta que já estava "Aprovado".')

    _validar_campos(campos)

    df = bd.ler_propostas(CAMINHO_XLSX)[bd.PROPOSTAS_COLUNAS_EDITAVEIS]
    nova_linha = {col: campos.get(col, "") for col in bd.PROPOSTAS_COLUNAS_EDITAVEIS}
    df = pd.concat([df, pd.DataFrame([nova_linha])], ignore_index=True)
    bd.escrever_propostas(CAMINHO_XLSX, df)
    return len(df) - 1


def atualizar_proposta(indice: int, campos: dict, esperado: Mapping | None = None) -> None:
    """`indice` e a posicao (0-based) da proposta na tabela retornada por
    listar_propostas()/historico_por_cpf() no momento em que a edicao foi
    aberta. Como o app sempre reescreve a aba inteira na mesma ordem, essa
    posicao continua valida entre a leitura e a escrita, desde que nada mais
    tenha mexido no arquivo nesse meio-tempo (uso individual e local).

    `esperado`: a proposta como a tela a mostrava (ver `linha_confere`) - se a linha
    gravada nesse indice for outra, recusa em vez de sobrescrever a errada.
    """
    sessao_mod.exigir_admin()
    df = bd.ler_propostas(CAMINHO_XLSX)[bd.PROPOSTAS_COLUNAS_EDITAVEIS]
    if indice not in df.index:
        raise ErroProposta("Proposta não encontrada (a lista pode ter mudado). Recarregue e tente de novo.")
    if esperado is not None and not linha_confere(df.loc[indice].to_dict(), esperado):
        raise ErroProposta(_MENSAGEM_PROPOSTA_MUDOU)

    if "STATUS" in campos and eh_nao_efetivado(campos["STATUS"]) and not eh_aprovado_nao_efetivado(df.loc[indice, "STATUS"]):
        # so pode virar "Não efetivado" quem estava exatamente "Aprovado" - nunca a
        # partir de Em analise/Negado/Efetivado/etc (o cliente so "desiste" do que
        # tinha sido aprovado)
        raise ErroProposta('O status "Não efetivado" só pode vir de uma proposta que já estava "Aprovado".')

    # `campos` pode vir parcial (so os campos que mudaram) - valida sempre o
    # estado FINAL da linha (valores atuais + alteracoes), nunca so o que foi
    # passado, senao uma edicao parcial poderia escapar da validacao normal
    # (ex: zerar o valor por engano numa linha que ja tinha valor valido).
    estado_final = df.loc[indice].to_dict()
    estado_final.update(campos)
    # numa edicao, VALOR (R$) nao e obrigatorio - uma proposta antiga que ja
    # estava sem valor pode ser editada (ex: so pra mudar o status) sem
    # precisar preencher o valor primeiro. Se um valor FOR informado, ele
    # ainda precisa ser um numero valido e maior que zero (validado abaixo).
    _validar_campos(estado_final, valor_obrigatorio=False)
    if "VALOR (R$)" in campos:
        # usa o valor ja convertido por _validar_campos (aceita formato
        # brasileiro "1.500,00") em vez do texto/numero original recebido.
        campos["VALOR (R$)"] = estado_final["VALOR (R$)"]

    for col, valor in campos.items():
        if col in bd.PROPOSTAS_COLUNAS_EDITAVEIS:
            # "" nao pode ser atribuido direto numa coluna ja tipada como
            # numerica (MESES/VALOR viram float64 na leitura) - o pandas
            # recusa ("Invalid value '' for dtype 'float64'"). None e aceito
            # em qualquer coluna (numerica vira NaN, texto vira None mesmo).
            df.loc[indice, col] = None if valor == "" else valor
    bd.escrever_propostas(CAMINHO_XLSX, df)


def remover_proposta(indice: int, esperado: Mapping | None = None) -> None:
    """`indice` e a posicao real da proposta no arquivo (mesmo valor que
    atualizar_proposta espera - ver o aviso na docstring dela). `esperado`: ver
    atualizar_proposta."""
    sessao_mod.exigir_admin()
    df = bd.ler_propostas(CAMINHO_XLSX)[bd.PROPOSTAS_COLUNAS_EDITAVEIS]
    if indice not in df.index:
        raise ErroProposta("Proposta não encontrada (a lista pode ter mudado). Recarregue e tente de novo.")
    if esperado is not None and not linha_confere(df.loc[indice].to_dict(), esperado):
        raise ErroProposta(_MENSAGEM_PROPOSTA_MUDOU)
    id_proposta = df.loc[indice, "ID_PROPOSTA"]
    if id_proposta and id_proposta in set(bd.ler_vendas(CAMINHO_XLSX)["BANCO_ESCOLHIDO"]):
        # a venda ficaria apontando para um banco que nao existe mais
        raise ErroProposta("Esta é a proposta do banco escolhido numa venda. Troque o banco escolhido antes de excluí-la.")
    bd.escrever_propostas(CAMINHO_XLSX, df.drop(index=indice).reset_index(drop=True))


# -- mesma venda em bancos diferentes ----------------------------------------------------
# E comum lancar a MESMA venda (mesmo cliente + mesmo equipamento) em varios bancos ao
# mesmo tempo. Quando uma delas efetiva, as outras que ainda estavam em aberto (em
# analise, ou ate ja aprovadas por outro banco) deixam de fazer sentido - mas o app NUNCA
# decide isso sozinho: so pergunta (ver desktop/widgets/encerrar_propostas_da_venda.py).


def propostas_da_mesma_venda(cpf: str, equipamento: str, ignorar_indice: int | None = None) -> pd.DataFrame:
    """Outras propostas do MESMO cliente (CPF, so os digitos) e do MESMO equipamento
    (sem diferenciar maiusculas/espacos) - candidatas a serem a mesma venda em bancos
    diferentes. Sempre le a planilha local inteira (so ADMIN grava, e e quem chama isto).
    `ignorar_indice`: nunca inclui essa posicao (normalmente a proposta que acabou de ser
    efetivada)."""
    df = bd.ler_propostas(CAMINHO_XLSX)
    alvo = apenas_digitos(cpf)
    mesmo_cliente = df["CPF"].map(apenas_digitos) == alvo
    mesmo_equipamento = _mesmo_texto(df["EQUIPAMENTO"], equipamento) if equipamento else pd.Series(False, index=df.index)
    resultado = df[mesmo_cliente & mesmo_equipamento]
    if ignorar_indice is not None:
        resultado = resultado[resultado.index != ignorar_indice]
    return resultado


def propostas_em_aberto_da_mesma_venda(cpf: str, equipamento: str, ignorar_indice: int | None = None) -> pd.DataFrame:
    """Como propostas_da_mesma_venda, so as que AINDA estao em aberto (esta_em_aberto) -
    as candidatas reais a virar "Encerrada" quando uma delas acabou de ser efetivada. Uma
    proposta ja Negada/Efetivada/Não efetivado/Encerrada nunca entra aqui."""
    outras = propostas_da_mesma_venda(cpf, equipamento, ignorar_indice)
    if outras.empty:
        return outras
    return outras[outras["STATUS"].map(esta_em_aberto)]


def encerrar_propostas(indices: list[int]) -> int:
    """Marca cada proposta de `indices` como STATUS_PROPOSTA_ENCERRADA, numa unica escrita.
    So usada depois de perguntar (nunca automatico) - ver propostas_em_aberto_da_mesma_venda.
    Pula (sem erro) indices que sumiram ou que ja nao estao mais em aberto nesse meio-tempo -
    nunca sobrescreve um desfecho que outra tela ja deu a proposta. Devolve quantas mudaram."""
    sessao_mod.exigir_admin()
    if not indices:
        return 0
    df = bd.ler_propostas(CAMINHO_XLSX)[bd.PROPOSTAS_COLUNAS_EDITAVEIS]
    alteradas = 0
    for indice in indices:
        if indice not in df.index or not esta_em_aberto(df.loc[indice, "STATUS"]):
            continue
        df.loc[indice, "STATUS"] = STATUS_PROPOSTA_ENCERRADA
        alteradas += 1
    if alteradas:
        bd.escrever_propostas(CAMINHO_XLSX, df)
    return alteradas
