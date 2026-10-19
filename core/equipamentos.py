"""Regras de negocio para EQUIPAMENTOS."""

from __future__ import annotations

import pandas as pd

from config import CAMINHO_XLSX
from core import backup as backup_mod
from core import data_store as bd
from core import sessao as sessao_mod
from core.vendedores import esta_ativo


class ErroEquipamento(Exception):
    pass


_CAMPOS_NUMERICOS = [
    ("PARCELAS", "Parcelas"),
    ("VALOR PARCELA (R$)", "Valor da parcela"),
    ("VALOR LÍQUIDO/REFERÊNCIA (R$)", "Valor líquido/referência"),
]


def _validar_numericos(campos: dict) -> dict:
    """Cada campo numerico e opcional, mas se vier preenchido precisa ser um
    numero positivo - PARCELAS/VALOR negativo ou zerado nao faz sentido de
    negocio e passaria batido silenciosamente (viraria NaN na leitura, sem
    avisar ninguem)."""
    campos = dict(campos)
    for coluna, rotulo in _CAMPOS_NUMERICOS:
        if coluna not in campos:
            continue
        valor = campos[coluna]
        if valor is None or valor == "" or (isinstance(valor, float) and pd.isna(valor)):
            campos[coluna] = ""
            continue
        try:
            numero = float(valor)
        except (TypeError, ValueError):
            raise ErroEquipamento(f"{rotulo} deve ser um número.")
        if numero <= 0:
            raise ErroEquipamento(f"{rotulo} deve ser maior que zero.")
        campos[coluna] = numero
    return campos


def listar_equipamentos() -> pd.DataFrame:
    df = bd.ler_equipamentos(CAMINHO_XLSX)
    return df.sort_values(["FORNECEDOR", "EQUIPAMENTO"], key=lambda s: s.str.upper()).reset_index(drop=True)


def adicionar_equipamento(campos: dict) -> None:
    sessao_mod.exigir_admin()
    campos = dict(campos)
    nome = (campos.get("EQUIPAMENTO") or "").strip()
    if not nome:
        raise ErroEquipamento("Nome do equipamento é obrigatório.")
    campos["EQUIPAMENTO"] = nome
    campos["FORNECEDOR"] = (campos.get("FORNECEDOR") or "").strip()
    campos = _validar_numericos(campos)

    df = bd.ler_equipamentos(CAMINHO_XLSX)
    nova_linha = {col: campos.get(col, "") for col in bd.EQUIPAMENTOS_COLUNAS}
    df = pd.concat([df, pd.DataFrame([nova_linha])], ignore_index=True)
    bd.escrever_equipamentos(CAMINHO_XLSX, df)


# -- o cadastro (Cadastros > Equipamentos): a lista fechada do campo Equipamento ----------------------------------
# Decidido com o usuario em 03/10/2026: equipamento sempre escolhido da lista (novo, so pelo cadastro). Uma proposta
# ou venda guarda os nomes separados por " + " (ex.: "Cadeira X + Laser Y"); renomear aqui muda os dois.

SEPARADOR = " + "
# um nome antigo com isto dentro pode ser DOIS equipamentos digitados juntos ("Laser X e Cadeira Y"): o app nao
# decide sozinho - vai para o usuario (trazer_para_o_cadastro)
_JUNTADORES = (" E ", "/", ",", " & ")


def _chave(nome) -> str:
    return " ".join(str(nome or "").split()).upper()


def nomes_do_texto(texto) -> list[str]:
    """Os equipamentos de um campo EQUIPAMENTO(S) ("Cadeira X + Laser Y" -> ["Cadeira X", "Laser Y"]), sem repetir."""
    vistos, nomes = set(), []
    for parte in str(texto or "").split("+"):
        nome = " ".join(parte.split())
        if nome and _chave(nome) not in vistos:
            vistos.add(_chave(nome))
            nomes.append(nome)
    return nomes


def _textos_em_uso() -> list[str]:
    """Todo texto de equipamento gravado: o de cada proposta e o de cada venda."""
    propostas = bd.ler_propostas(CAMINHO_XLSX)["EQUIPAMENTO"].tolist()
    vendas = bd.ler_vendas(CAMINHO_XLSX)["EQUIPAMENTOS"].tolist()
    return [t for t in propostas + vendas if str(t or "").strip()]


def _uso_nas_propostas() -> dict[str, int]:
    """Quantas propostas citam cada equipamento (chave sem diferenciar maiusculas/espacos)."""
    uso: dict[str, int] = {}
    for texto in bd.ler_propostas(CAMINHO_XLSX)["EQUIPAMENTO"]:
        for nome in nomes_do_texto(texto):
            uso[_chave(nome)] = uso.get(_chave(nome), 0) + 1
    return uso


def listar_cadastro() -> pd.DataFrame:
    """O cadastro com ATIVO (True/False) e PROPOSTAS (quantas citam o equipamento), em ordem alfabetica."""
    df = bd.ler_equipamentos(CAMINHO_XLSX)
    df = df[df["EQUIPAMENTO"] != ""].copy()
    uso = _uso_nas_propostas()
    df["ATIVO"] = df["ATIVO"].map(esta_ativo)
    df["PROPOSTAS"] = df["EQUIPAMENTO"].map(lambda nome: uso.get(_chave(nome), 0)).astype(int)
    return df.sort_values("EQUIPAMENTO", key=lambda s: s.str.upper()).reset_index(drop=True)


def nomes_ativos() -> list[str]:
    """Os equipamentos que aparecem nas listas da venda e da proposta."""
    df = listar_cadastro()
    return df.loc[df["ATIVO"], "EQUIPAMENTO"].tolist()


def _linha(df: pd.DataFrame, nome: str) -> int:
    alvo = df.index[df["EQUIPAMENTO"].map(_chave) == _chave(nome)]
    if len(alvo) == 0:
        raise ErroEquipamento(f'O equipamento "{nome}" não está no cadastro.')
    return alvo[0]


def _nome_valido(nome) -> str:
    nome = " ".join(str(nome or "").split())
    if not nome:
        raise ErroEquipamento("Nome do equipamento é obrigatório.")
    if "+" in nome:
        raise ErroEquipamento('O nome não pode ter "+" (ele separa os equipamentos de uma venda). Cadastre um de cada vez.')
    return nome


def cadastrar(campos: dict) -> str:
    """Cadastra um equipamento novo (ja ativo). Devolve o nome como foi gravado."""
    sessao_mod.exigir_admin()
    nome = _nome_valido(campos.get("EQUIPAMENTO"))
    df = bd.ler_equipamentos(CAMINHO_XLSX)
    if (df["EQUIPAMENTO"].map(_chave) == _chave(nome)).any():
        raise ErroEquipamento(f'O equipamento "{nome}" já está no cadastro.')
    campos = _validar_numericos({**campos, "EQUIPAMENTO": nome})
    linha = {col: campos.get(col, "") for col in bd.EQUIPAMENTOS_COLUNAS}
    linha["FORNECEDOR"] = (campos.get("FORNECEDOR") or "").strip()
    linha["OBSERVAÇÕES"] = (campos.get("OBSERVAÇÕES") or "").strip()
    linha["ATIVO"] = "Sim"
    bd.escrever_equipamentos(CAMINHO_XLSX, pd.concat([df, pd.DataFrame([linha])], ignore_index=True))
    return nome


def _trocar_nas_vendas_e_propostas(trocas: dict[str, list[str]]) -> int:
    """Troca nomes nos campos de equipamento das propostas e das vendas (chave antiga -> nomes novos; um nome pode
    virar dois). Grava numa vez so. Devolve quantas propostas mudaram."""
    def _novo_texto(texto: str) -> str:
        nomes = []
        for nome in nomes_do_texto(texto):
            for trocado in trocas.get(_chave(nome), [nome]):
                if _chave(trocado) not in {_chave(n) for n in nomes}:
                    nomes.append(trocado)
        return SEPARADOR.join(nomes)

    propostas = bd.ler_propostas(CAMINHO_XLSX)[bd.PROPOSTAS_COLUNAS_EDITAVEIS].copy()
    vendas = bd.ler_vendas(CAMINHO_XLSX)
    antes_p, antes_v = propostas["EQUIPAMENTO"].copy(), vendas["EQUIPAMENTOS"].copy()
    tem_texto = propostas["EQUIPAMENTO"].map(lambda t: bool(str(t or "").strip()))
    propostas.loc[tem_texto, "EQUIPAMENTO"] = propostas.loc[tem_texto, "EQUIPAMENTO"].map(_novo_texto)
    vendas["EQUIPAMENTOS"] = vendas["EQUIPAMENTOS"].map(_novo_texto)
    mudaram_p = int((propostas["EQUIPAMENTO"] != antes_p).sum())
    mudaram_v = bool((vendas["EQUIPAMENTOS"] != antes_v).any())
    if mudaram_p or mudaram_v:
        bd.escrever_vendas_e_propostas(CAMINHO_XLSX, propostas=propostas if mudaram_p else None,
                                       vendas=vendas if mudaram_v else None)
    return mudaram_p


def salvar(nome_atual: str, campos: dict) -> int:
    """Grava a edicao do equipamento. Trocar o nome muda tambem as propostas e vendas que o citam (so mudar
    maiusculas tambem vale). Devolve quantas propostas mudaram."""
    sessao_mod.exigir_admin()
    df = bd.ler_equipamentos(CAMINHO_XLSX)
    linha = _linha(df, nome_atual)
    nome_novo = _nome_valido(campos.get("EQUIPAMENTO", df.at[linha, "EQUIPAMENTO"]))
    if (df.drop(index=linha)["EQUIPAMENTO"].map(_chave) == _chave(nome_novo)).any():
        raise ErroEquipamento(f'Já existe outro equipamento chamado "{nome_novo}" no cadastro.')
    campos = _validar_numericos({**campos, "EQUIPAMENTO": nome_novo})
    antigo = df.at[linha, "EQUIPAMENTO"]
    # propostas e vendas primeiro: se o cadastro falhar depois, o nome antigo continua nele e da pra repetir
    mudaram = _trocar_nas_vendas_e_propostas({_chave(antigo): [nome_novo]}) if antigo != nome_novo else 0
    for coluna in ("FORNECEDOR", "EQUIPAMENTO", "PARCELAS", "VALOR PARCELA (R$)", "VALOR LÍQUIDO/REFERÊNCIA (R$)", "OBSERVAÇÕES"):
        if coluna in campos:
            valor = campos[coluna]
            df.at[linha, coluna] = (valor.strip() if isinstance(valor, str) else valor)
    bd.escrever_equipamentos(CAMINHO_XLSX, df)
    return mudaram


def definir_ativo(nome: str, ativo: bool) -> None:
    """Desativado, o equipamento sai das listas da venda e da proposta; o que ja foi lancado com ele fica como esta."""
    sessao_mod.exigir_admin()
    df = bd.ler_equipamentos(CAMINHO_XLSX)
    df.at[_linha(df, nome), "ATIVO"] = "Sim" if ativo else "Não"
    bd.escrever_equipamentos(CAMINHO_XLSX, df)


def excluir(nome: str) -> None:
    """Apaga do cadastro um equipamento que nenhuma proposta cita (se alguma cita, recusa: desative em vez disso)."""
    sessao_mod.exigir_admin()
    df = bd.ler_equipamentos(CAMINHO_XLSX)
    linha = _linha(df, nome)
    usadas = _uso_nas_propostas().get(_chave(nome), 0)
    if usadas:
        raise ErroEquipamento(
            f'"{df.at[linha, "EQUIPAMENTO"]}" está em {usadas} proposta(s) e não pode ser excluído. Desative-o: ele '
            "sai das listas, e as propostas antigas continuam como estão."
        )
    bd.escrever_equipamentos(CAMINHO_XLSX, df.drop(index=linha).reset_index(drop=True))


def nomes_fora_do_cadastro() -> tuple[list[str], list[str]]:
    """Os nomes ja usados em propostas e vendas que o cadastro ainda nao tem: (simples, juntos). "Juntos" sao os que
    podem ser dois equipamentos digitados num nome so ("Laser X e Cadeira Y") - o usuario decide."""
    no_cadastro = {_chave(n) for n in bd.ler_equipamentos(CAMINHO_XLSX)["EQUIPAMENTO"]}
    simples, juntos, vistos = [], [], set()
    for texto in _textos_em_uso():
        for nome in nomes_do_texto(texto):
            if _chave(nome) in no_cadastro or _chave(nome) in vistos:
                continue
            vistos.add(_chave(nome))
            (juntos if any(j in f" {_chave(nome)} " for j in _JUNTADORES) else simples).append(nome)
    return sorted(simples, key=_chave), sorted(juntos, key=_chave)


def trazer_para_o_cadastro(simples: list[str], juntos: dict[str, list[str]]) -> dict:
    """Poe no cadastro os nomes ja usados (nomes_fora_do_cadastro). `juntos`: para cada nome "junto", como o usuario
    decidiu - [o proprio nome] (e um equipamento so) ou as partes (sao dois ou mais; as propostas e vendas que o citam
    passam a citar as partes). Faz backup antes. Devolve um resumo."""
    sessao_mod.exigir_admin()
    faltando_simples, faltando_juntos = nomes_fora_do_cadastro()
    sem_resposta = [n for n in faltando_juntos if n not in juntos]
    if sem_resposta:
        raise ErroEquipamento(f"Decida antes os nomes que podem ser dois equipamentos ({len(sem_resposta)} sem resposta).")
    novos, trocas = [], {}
    for nome in simples:
        if nome in faltando_simples:
            novos.append(nome)
    for nome, partes in juntos.items():
        partes = [_nome_valido(p) for p in partes]
        if not partes:
            raise ErroEquipamento(f'Informe como fica "{nome}".')
        novos.extend(partes)
        if [_chave(p) for p in partes] != [_chave(nome)]:
            trocas[_chave(nome)] = partes
    backup = backup_mod.fazer_backup(backup_mod.MOTIVO_PRE_EQUIPAMENTOS, CAMINHO_XLSX)
    mudaram = _trocar_nas_vendas_e_propostas(trocas) if trocas else 0
    df = bd.ler_equipamentos(CAMINHO_XLSX)
    ja = {_chave(n) for n in df["EQUIPAMENTO"]}
    linhas = []
    for nome in novos:
        if _chave(nome) not in ja:
            ja.add(_chave(nome))
            linhas.append({**{c: "" for c in bd.EQUIPAMENTOS_COLUNAS}, "EQUIPAMENTO": nome, "ATIVO": "Sim"})
    if linhas:
        bd.escrever_equipamentos(CAMINHO_XLSX, pd.concat([df, pd.DataFrame(linhas)], ignore_index=True))
    return {"cadastrados": len(linhas), "propostas_alteradas": mudaram, "backup": backup}
