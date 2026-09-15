"""Camada de leitura/escrita do arquivo .xlsx que funciona como banco de dados.

Esta e a UNICA camada que sabe que os dados estao num .xlsx. As camadas de
regra de negocio (core/clientes.py, core/equipamentos.py, core/propostas.py)
so enxergam DataFrames - se um dia o banco virar SQLite/Postgres, so este
arquivo precisa mudar.

Regras importantes:
- O arquivo pode ser aberto manualmente no Excel a qualquer momento.
- Toda escrita rele o arquivo do zero antes de aplicar a mudanca, para nao
  sobrescrever uma edicao feita direto no Excel entre uma tela e outra.
- Toda escrita e feita em arquivo temporario + substituicao atomica, para
  nunca deixar o .xlsx pela metade se algo falhar no meio do caminho.
- Se o Excel estiver com o arquivo aberto, a escrita falha com
  ErroArquivoBloqueado em vez de travar o app - quem chamou decide como
  avisar o usuario (nunca deixamos o erro passar em silencio).
"""

from __future__ import annotations

import os
import tempfile
from datetime import date, datetime
from pathlib import Path

import openpyxl
import pandas as pd

ABA_CLIENTES = "CLIENTES"
ABA_EQUIPAMENTOS = "EQUIPAMENTOS"
ABA_PROPOSTAS = "PROPOSTAS"

CLIENTES_COLUNAS = [
    "DATA CADASTRO",
    "CPF/CNPJ",
    "VENDEDOR",
    "TIPO",
    "CLIENTE",
    "NASCIMENTO",
    "CELULAR",
    "ENDEREÇO",
    "VINCULADO",
    "REDE SOCIAL",
    "EMAIL",
]

EQUIPAMENTOS_COLUNAS = [
    "FORNECEDOR",
    "EQUIPAMENTO",
    "PARCELAS",
    "VALOR PARCELA (R$)",
    "VALOR LÍQUIDO/REFERÊNCIA (R$)",
    "OBSERVAÇÕES",
]

# Colunas realmente digitadas/gravadas na aba PROPOSTAS.
PROPOSTAS_COLUNAS_EDITAVEIS = [
    "DATA",
    "CPF",
    "VALOR (R$)",
    "MESES",
    "EQUIPAMENTO",
    "BANCO",
    "STATUS",
    "OBSERVAÇÕES",
]

# Ordem completa da aba, incluindo as colunas calculadas (VENDEDOR, CLIENTE,
# TEMPO) que nunca sao digitadas - sao sempre derivadas do CPF e da data.
# O vendedor de uma proposta e sempre o mesmo vendedor do cliente (cadastrado
# uma vez em CLIENTES); repetir esse campo por proposta so criaria risco de
# ficar desatualizado se o cliente trocar de vendedor.
PROPOSTAS_COLUNAS = [
    "DATA",
    "VENDEDOR",
    "CPF",
    "CLIENTE",
    "VALOR (R$)",
    "MESES",
    "EQUIPAMENTO",
    "BANCO",
    "TEMPO",
    "STATUS",
    "OBSERVAÇÕES",
]

STATUS_ENCERRADO = {"APROVADO", "NEGADO"}

_COLUNAS_DE_DATA = {
    ABA_CLIENTES: {"DATA CADASTRO", "NASCIMENTO"},
    ABA_PROPOSTAS: {"DATA"},
}
_COLUNAS_DE_MOEDA = {
    ABA_EQUIPAMENTOS: {"VALOR PARCELA (R$)", "VALOR LÍQUIDO/REFERÊNCIA (R$)"},
    ABA_PROPOSTAS: {"VALOR (R$)"},
}

_CLIENTES_COLUNAS_TEXTO = [
    "CPF/CNPJ", "VENDEDOR", "TIPO", "CLIENTE", "ENDEREÇO", "VINCULADO", "REDE SOCIAL", "EMAIL",
]
_EQUIPAMENTOS_COLUNAS_TEXTO = ["FORNECEDOR", "EQUIPAMENTO", "OBSERVAÇÕES"]
_EQUIPAMENTOS_COLUNAS_NUMERICAS = ["PARCELAS", "VALOR PARCELA (R$)", "VALOR LÍQUIDO/REFERÊNCIA (R$)"]
_PROPOSTAS_COLUNAS_TEXTO = ["CPF", "EQUIPAMENTO", "BANCO", "STATUS", "OBSERVAÇÕES"]
_PROPOSTAS_COLUNAS_NUMERICAS = ["VALOR (R$)", "MESES"]


class ErroArquivoBloqueado(Exception):
    """O .xlsx esta aberto no Excel (ou outro programa) e nao pode ser salvo agora."""


# ---------------------------------------------------------------------------
# Deteccao de bloqueio / leitura basica
# ---------------------------------------------------------------------------

def _caminho_arquivo_bloqueio(caminho_xlsx: Path) -> Path:
    return caminho_xlsx.with_name(f"~${caminho_xlsx.name}")


def arquivo_esta_bloqueado(caminho_xlsx: Path) -> bool:
    """True se tudo indica que o Excel esta com o arquivo aberto agora."""
    return _caminho_arquivo_bloqueio(caminho_xlsx).exists()


def _carregar_planilha(caminho_xlsx: Path):
    return openpyxl.load_workbook(caminho_xlsx, data_only=False)


def _esta_vazio(valor) -> bool:
    """None, "" ou NaN (celula vazia as vezes vira float('nan') em vez de None,
    dependendo de como o pandas infere o tipo da coluna)."""
    if valor is None or valor == "":
        return True
    if isinstance(valor, float):
        return pd.isna(valor)
    return False


def _normalizar_texto(valor) -> str:
    if _esta_vazio(valor):
        return ""
    return str(valor).strip()


def _normalizar_celular(valor) -> str:
    if _esta_vazio(valor):
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor).strip()


def _linhas_da_aba(ws, n_colunas: int):
    for linha in ws.iter_rows(min_row=2, max_col=n_colunas, values_only=True):
        if all(v is None or v == "" for v in linha):
            continue
        yield linha


def ler_aba(caminho_xlsx: Path, nome_aba: str, colunas: list[str]) -> pd.DataFrame:
    wb = _carregar_planilha(caminho_xlsx)
    try:
        ws = wb[nome_aba]
        linhas = list(_linhas_da_aba(ws, len(colunas)))
    finally:
        wb.close()
    return pd.DataFrame(linhas, columns=colunas)


# ---------------------------------------------------------------------------
# Leitura tipada por entidade
# ---------------------------------------------------------------------------

def ler_clientes(caminho_xlsx: Path) -> pd.DataFrame:
    df = ler_aba(caminho_xlsx, ABA_CLIENTES, CLIENTES_COLUNAS)
    for col in _CLIENTES_COLUNAS_TEXTO:
        df[col] = df[col].map(_normalizar_texto)
    df["CELULAR"] = df["CELULAR"].map(_normalizar_celular)
    return df


def ler_equipamentos(caminho_xlsx: Path) -> pd.DataFrame:
    df = ler_aba(caminho_xlsx, ABA_EQUIPAMENTOS, EQUIPAMENTOS_COLUNAS)
    for col in _EQUIPAMENTOS_COLUNAS_TEXTO:
        df[col] = df[col].map(_normalizar_texto)
    for col in _EQUIPAMENTOS_COLUNAS_NUMERICAS:
        # celula vazia deve virar NaN "de verdade" (tipo numerico), nao um
        # None solto num objeto - senao a tela exibe o texto literal "None".
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _calcular_tempo(valor_data, valor_status) -> str:
    if not isinstance(valor_data, (datetime, date)) or pd.isna(valor_data):
        return ""
    status = _normalizar_texto(valor_status).upper()
    if status in STATUS_ENCERRADO:
        return "Encerrado"
    dia = valor_data.date() if isinstance(valor_data, datetime) else valor_data
    dias = (date.today() - dia).days
    return f"{dias} dias"


def ler_propostas(caminho_xlsx: Path, df_clientes: pd.DataFrame | None = None) -> pd.DataFrame:
    """Le a aba PROPOSTAS e recalcula VENDEDOR/CLIENTE/TEMPO a partir do CPF.

    Os valores calculados NUNCA vem do que esta gravado na planilha (que pode
    estar desatualizado se o arquivo nao foi reaberto no Excel) - sao sempre
    recalculados aqui, do mesmo jeito que as formulas de Excel fariam. Isso
    garante que o dashboard e a ficha do cliente sempre mostrem o vendedor e
    o nome corretos mesmo que o cliente tenha sido editado depois da proposta.
    """
    # A aba tem 11 colunas na ordem de PROPOSTAS_COLUNAS (com VENDEDOR/CLIENTE/
    # TEMPO intercalados como formulas). Le tudo nessa ordem e depois descarta
    # essas 3 colunas calculadas - o texto da formula, se sobrar algo, nunca e
    # usado.
    completo = ler_aba(caminho_xlsx, ABA_PROPOSTAS, PROPOSTAS_COLUNAS)
    df = completo[PROPOSTAS_COLUNAS_EDITAVEIS].copy()
    for col in _PROPOSTAS_COLUNAS_TEXTO:
        df[col] = df[col].map(_normalizar_texto)
    for col in _PROPOSTAS_COLUNAS_NUMERICAS:
        # celula vazia deve virar NaN "de verdade" (tipo numerico), nao um
        # None solto num objeto - senao a tela exibe o texto literal "None".
        df[col] = pd.to_numeric(df[col], errors="coerce")

    if df_clientes is None:
        df_clientes = ler_clientes(caminho_xlsx)
    referencia = df_clientes.drop_duplicates("CPF/CNPJ").set_index("CPF/CNPJ")

    df["VENDEDOR"] = df["CPF"].map(referencia["VENDEDOR"]).fillna("")
    df["CLIENTE"] = df["CPF"].map(referencia["CLIENTE"]).fillna("")
    df["TEMPO"] = [_calcular_tempo(d, s) for d, s in zip(df["DATA"], df["STATUS"])]
    return df[PROPOSTAS_COLUNAS]


# ---------------------------------------------------------------------------
# Escrita segura (bloqueio + salvamento atomico)
# ---------------------------------------------------------------------------

def _salvar_planilha(wb, caminho_xlsx: Path) -> None:
    if arquivo_esta_bloqueado(caminho_xlsx):
        raise ErroArquivoBloqueado(
            f"O arquivo '{caminho_xlsx.name}' esta aberto no Excel. "
            "Feche-o e tente salvar novamente."
        )
    tmp_fd, tmp_nome = tempfile.mkstemp(suffix=".xlsx", dir=str(caminho_xlsx.parent))
    os.close(tmp_fd)
    caminho_temporario = Path(tmp_nome)
    try:
        wb.save(caminho_temporario)
        os.replace(caminho_temporario, caminho_xlsx)
    except PermissionError as exc:
        caminho_temporario.unlink(missing_ok=True)
        raise ErroArquivoBloqueado(
            f"Nao foi possivel salvar '{caminho_xlsx.name}'. "
            "Verifique se ele nao esta aberto no Excel e tente novamente."
        ) from exc


def _aplicar_formato(cell, nome_aba: str, nome_coluna: str) -> None:
    if nome_coluna in _COLUNAS_DE_DATA.get(nome_aba, ()):
        cell.number_format = "dd/mm/yyyy"
    elif nome_coluna in _COLUNAS_DE_MOEDA.get(nome_aba, ()):
        cell.number_format = '"R$ "#,##0.00'


def _limpar_valor(valor):
    """None/""/NaN viram None (celula vazia de verdade); o resto passa direto."""
    return None if _esta_vazio(valor) else valor


def _escrever_linhas_simples(ws, nome_aba: str, colunas: list[str], registros: list[dict]) -> None:
    if ws.max_row >= 2:
        ws.delete_rows(2, ws.max_row - 1)
    for i, registro in enumerate(registros, start=2):
        for j, nome_coluna in enumerate(colunas, start=1):
            cell = ws.cell(row=i, column=j, value=_limpar_valor(registro.get(nome_coluna)))
            _aplicar_formato(cell, nome_aba, nome_coluna)


def _escrever_linhas_propostas(ws, registros: list[dict]) -> None:
    """Regrava a aba PROPOSTAS, incluindo as formulas de VENDEDOR/CLIENTE/TEMPO
    (identicas as que ja existiam na planilha original), para que o arquivo
    continue funcionando normalmente se for aberto e editado direto no Excel.
    """
    if ws.max_row >= 2:
        ws.delete_rows(2, ws.max_row - 1)
    for i, registro in enumerate(registros, start=2):
        cell_data = ws.cell(row=i, column=1, value=_limpar_valor(registro.get("DATA")))
        cell_data.number_format = "dd/mm/yyyy"
        # VENDEDOR e CLIENTE sao sempre formulas (VLOOKUP pelo CPF na aba
        # CLIENTES) - nunca gravamos um valor fixo aqui, senao a planilha
        # ficaria desatualizada se o cliente mudasse de vendedor ou de nome.
        ws.cell(row=i, column=2, value=f'=IFERROR(VLOOKUP(C{i},CLIENTES!$B:$C,2,FALSE()),"")')
        ws.cell(row=i, column=3, value=registro.get("CPF"))
        ws.cell(row=i, column=4, value=f'=IFERROR(VLOOKUP(C{i},CLIENTES!$B:$E,4,FALSE()),"")')
        cell_valor = ws.cell(row=i, column=5, value=_limpar_valor(registro.get("VALOR (R$)")))
        cell_valor.number_format = '"R$ "#,##0.00'
        ws.cell(row=i, column=6, value=_limpar_valor(registro.get("MESES")))
        ws.cell(row=i, column=7, value=registro.get("EQUIPAMENTO"))
        ws.cell(row=i, column=8, value=registro.get("BANCO"))
        # TEMPO: enquanto nao for Aprovado/Negado, mostra "N dias" desde o
        # envio; depois disso mostra "Encerrado" (a proposta parou de "correr").
        ws.cell(
            row=i,
            column=9,
            value=(
                f'=IF(A{i}="","",IF(OR(UPPER(J{i})="APROVADO",UPPER(J{i})="NEGADO"),'
                f'"Encerrado",TODAY()-A{i}&" dias"))'
            ),
        )
        ws.cell(row=i, column=10, value=registro.get("STATUS"))
        ws.cell(row=i, column=11, value=registro.get("OBSERVAÇÕES"))


def escrever_clientes(caminho_xlsx: Path, df: pd.DataFrame) -> None:
    wb = _carregar_planilha(caminho_xlsx)
    try:
        _escrever_linhas_simples(wb[ABA_CLIENTES], ABA_CLIENTES, CLIENTES_COLUNAS, df.to_dict("records"))
        _salvar_planilha(wb, caminho_xlsx)
    finally:
        wb.close()


def escrever_equipamentos(caminho_xlsx: Path, df: pd.DataFrame) -> None:
    wb = _carregar_planilha(caminho_xlsx)
    try:
        _escrever_linhas_simples(wb[ABA_EQUIPAMENTOS], ABA_EQUIPAMENTOS, EQUIPAMENTOS_COLUNAS, df.to_dict("records"))
        _salvar_planilha(wb, caminho_xlsx)
    finally:
        wb.close()


def escrever_propostas(caminho_xlsx: Path, df: pd.DataFrame) -> None:
    """`df` deve conter apenas as colunas editaveis (PROPOSTAS_COLUNAS_EDITAVEIS)."""
    wb = _carregar_planilha(caminho_xlsx)
    try:
        _escrever_linhas_propostas(wb[ABA_PROPOSTAS], df.to_dict("records"))
        _salvar_planilha(wb, caminho_xlsx)
    finally:
        wb.close()
