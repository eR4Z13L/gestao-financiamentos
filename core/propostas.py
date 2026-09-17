"""Regras de negocio para PROPOSTAS: cadastro, atualizacao de status e
classificacao para o dashboard.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from config import CAMINHO_XLSX
from core import clientes as clientes_mod
from core import data_store as bd
from core.validators import apenas_digitos

STATUS_EM_ANALISE = "Em Análise"
STATUS_PRE_APROVADO = "Pré-aprovado"
STATUS_APROVADO = "Aprovado"
STATUS_NF_ANEXADA = "Nota Fiscal Anexada"
STATUS_GARANTIA_ASSINADA = "Garantia Assinada"
STATUS_NEGADO = "Negado"

# Ordem sugerida nos formularios/dropdowns (funil aproximado da proposta).
STATUS_OPCOES = [
    STATUS_EM_ANALISE,
    STATUS_PRE_APROVADO,
    STATUS_APROVADO,
    STATUS_NF_ANEXADA,
    STATUS_GARANTIA_ASSINADA,
    STATUS_NEGADO,
]

# Reaproveita a mesma lista de "palavras de negado" usada pro calculo de
# TEMPO em data_store.py, pra nunca ficar dessincronizada dali.
_PALAVRAS_NEGADO = bd.PALAVRAS_STATUS_NEGADO
_PALAVRAS_EM_ANALISE = {"EM ANÁLISE", "EM ANALISE", "ANÁLISE", "ANALISE", "PENDENTE"}
# Etapas conhecidas do funil depois da aprovacao inicial - so estas contam
# como "Aprovado" nas taxas gerais. Um status desconhecido/mal digitado (que
# nao e nenhuma das etapas oficiais, nem negado, nem em analise) NAO vira
# "Aprovado" por omissao - isso inflaria a taxa de aprovacao e o valor
# aprovado do dashboard com dado ruim. Ele cai em "Não identificado".
_PALAVRAS_APROVADO = {
    "APROVADO", "APROVADA",
    "PRÉ-APROVADO", "PRE-APROVADO", "PRÉ APROVADO", "PRE APROVADO",
    "NOTA FISCAL ANEXADA", "GARANTIA ASSINADA",
}


class ErroProposta(Exception):
    pass


def categoria_status(status: str) -> str:
    """Classifica um status (mesmo um customizado/novo, desde que seja uma
    das etapas oficiais do funil) em 'Negado', 'Em Análise' ou 'Aprovado' -
    as 3 categorias usadas nas taxas do dashboard. Um status vazio devolve ""
    (sem status); um status preenchido mas desconhecido devolve
    'Não identificado' - nenhum dos dois conta como aprovacao.
    """
    s = (status or "").strip().upper()
    if not s:
        return ""
    if s in _PALAVRAS_NEGADO:
        return "Negado"
    if s in _PALAVRAS_EM_ANALISE:
        return "Em Análise"
    if s in _PALAVRAS_APROVADO:
        return "Aprovado"
    return "Não identificado"


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


def listar_propostas() -> pd.DataFrame:
    """O indice do DataFrame retornado corresponde a posicao real da proposta
    no arquivo (a mesma que atualizar_proposta espera) - por isso NAO e
    resetado depois do sort. Nao reordene esse DataFrame antes de usar o
    indice para editar uma linha.
    """
    df = bd.ler_propostas(CAMINHO_XLSX)
    return _ordenar_por_data_desc(df)


def historico_por_cpf(cpf: str) -> pd.DataFrame:
    """Mesma observacao de listar_propostas: o indice reflete a posicao real
    no arquivo, necessaria para atualizar_proposta().
    """
    df = bd.ler_propostas(CAMINHO_XLSX)
    alvo = apenas_digitos(cpf)
    filtrado = df[df["CPF"].map(apenas_digitos) == alvo]
    return _ordenar_por_data_desc(filtrado)


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


def adicionar_proposta(campos: dict) -> None:
    """`campos` deve conter DATA, CPF, VALOR (R$), MESES, EQUIPAMENTO, BANCO,
    STATUS, OBSERVAÇÕES. DATA e STATUS tem valor padrao se nao informados."""
    campos = dict(campos)
    campos.setdefault("DATA", pd.Timestamp(date.today()))
    campos.setdefault("STATUS", STATUS_EM_ANALISE)
    campos["CPF"] = (campos.get("CPF") or "").strip()

    _validar_campos(campos)

    df = bd.ler_propostas(CAMINHO_XLSX)[bd.PROPOSTAS_COLUNAS_EDITAVEIS]
    nova_linha = {col: campos.get(col, "") for col in bd.PROPOSTAS_COLUNAS_EDITAVEIS}
    df = pd.concat([df, pd.DataFrame([nova_linha])], ignore_index=True)
    bd.escrever_propostas(CAMINHO_XLSX, df)


def atualizar_proposta(indice: int, campos: dict) -> None:
    """`indice` e a posicao (0-based) da proposta na tabela retornada por
    listar_propostas()/historico_por_cpf() no momento em que a edicao foi
    aberta. Como o app sempre reescreve a aba inteira na mesma ordem, essa
    posicao continua valida entre a leitura e a escrita, desde que nada mais
    tenha mexido no arquivo nesse meio-tempo (uso individual e local).
    """
    df = bd.ler_propostas(CAMINHO_XLSX)[bd.PROPOSTAS_COLUNAS_EDITAVEIS]
    if indice not in df.index:
        raise ErroProposta("Proposta não encontrada (a lista pode ter mudado). Recarregue e tente de novo.")

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


def remover_proposta(indice: int) -> None:
    """`indice` e a posicao real da proposta no arquivo (mesmo valor que
    atualizar_proposta espera - ver o aviso na docstring dela)."""
    df = bd.ler_propostas(CAMINHO_XLSX)[bd.PROPOSTAS_COLUNAS_EDITAVEIS]
    if indice not in df.index:
        raise ErroProposta("Proposta não encontrada (a lista pode ter mudado). Recarregue e tente de novo.")
    bd.escrever_propostas(CAMINHO_XLSX, df.drop(index=indice).reset_index(drop=True))
