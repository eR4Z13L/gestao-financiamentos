"""Planilha 100% ficticia pros testes e renders de tela: parte da copia de exemplo
versionada (exemplo/controle_financiamentos_exemplo.xlsx) e acrescenta vendedores e
propostas com datas antigas e status variados - o bastante pra exercitar selo de
"propostas paradas", dashboard e cards. Nada aqui vem da planilha real, e tudo fica
numa pasta temporaria do sistema (nunca em data/).

Uso:
    pasta = Path(tempfile.mkdtemp())
    caminho = fixture_ficticia.criar(pasta)
    fixture_ficticia.apontar_modulos_para(caminho)
"""

from __future__ import annotations

import logging
import shutil
import sys
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from core import clientes as clientes_mod
from core import equipamentos as equipamentos_mod
from core import propostas as propostas_mod
from core import sessao as sessao_mod
from core import vendedores as vendedores_mod

EXEMPLO = Path(__file__).resolve().parent.parent / "exemplo" / "controle_financiamentos_exemplo.xlsx"
CPF_MARIA = "529.982.247-25"
CPF_JOAO = "111.444.777-35"
CPF_ANA = "390.533.447-05"

# (cpf, dias atras, status, banco, equipamento, valor) - nomes e valores inventados
_PROPOSTAS_EXTRAS = [
    (CPF_MARIA, 12, propostas_mod.STATUS_EM_ANALISE, "Banco Exemplo", "Equipamento Modelo X", 52000),
    (CPF_MARIA, 20, propostas_mod.STATUS_APROVADO, "Outro Banco Exemplo", "Equipamento Modelo Y", 31000),
    (CPF_JOAO, 3, propostas_mod.STATUS_PRE_APROVADO, "Banco Exemplo", "Equipamento Modelo X", 47000),
    (CPF_JOAO, 30, propostas_mod.STATUS_EFETIVADO, "Banco Exemplo", "Equipamento Modelo Y", 28000),
    (CPF_ANA, 9, propostas_mod.STATUS_NEGADO, "Outro Banco Exemplo", "Equipamento Modelo X", 60000),
    (CPF_ANA, 0, propostas_mod.STATUS_EM_ANALISE, "Banco Exemplo", "Equipamento Modelo Y", 33000),
]


def criar(diretorio: Path) -> Path:
    """Copia o exemplo pra `diretorio` e acrescenta as propostas/vendedores extras. Recusa
    rodar com a sincronizacao do Google ligada: cada cadastro abaixo mandaria dado de
    teste pra planilha REAL na nuvem."""
    if config.SINCRONIZACAO_GOOGLE_ATIVADA:
        raise RuntimeError("Desligue config.SINCRONIZACAO_GOOGLE_ATIVADA antes de criar a fixture.")
    destino = Path(diretorio) / "controle_financiamentos_teste.xlsx"
    shutil.copy(EXEMPLO, destino)

    sessao_anterior = sessao_mod.atual()
    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
    caminhos_anteriores = _guardar_caminhos()
    try:
        apontar_modulos_para(destino)
        vendedores_mod.adicionar_vendedor("Vendedora Teste Dois")
        hoje = date.today()
        # as 3 propostas do exemplo foram datadas no dia em que o exemplo foi gerado e ficam
        # "velhas" com o tempo: re-datar aqui deixa a fixture igual em qualquer dia de execucao
        for posicao in range(len(propostas_mod.listar_propostas())):
            propostas_mod.atualizar_proposta(posicao, {"DATA": pd.Timestamp(hoje - timedelta(days=1 + posicao))})
        for cpf, dias, status, banco, equipamento, valor in _PROPOSTAS_EXTRAS:
            propostas_mod.adicionar_proposta(
                {
                    "CPF": cpf,
                    "DATA": pd.Timestamp(hoje - timedelta(days=dias)),
                    "STATUS": status,
                    "BANCO": banco,
                    "EQUIPAMENTO": equipamento,
                    "VALOR (R$)": valor,
                    "MESES": 36,
                }
            )
    finally:
        _restaurar_caminhos(caminhos_anteriores)
        if sessao_anterior is None:
            sessao_mod.encerrar()
        else:
            sessao_mod.iniciar(sessao_anterior)
    return destino


def montar_propostas(*linhas: dict) -> pd.DataFrame:
    """Propostas SINTETICAS no formato de listar_propostas (pra testar regras e telas sem arquivo): cada dict
    sobrescreve os padroes. O indice de cada linha e a sua posicao ("posicao real no arquivo") e TEMPO e
    calculado como o app calcula. Nomes e valores inventados."""
    from core import data_store as bd

    padrao = dict(
        DATA=pd.Timestamp(date.today() - timedelta(days=1)), VENDEDOR="VENDEDOR A", CPF="11111111111", CLIENTE="CLIENTE UM",
        MESES=36.0, EQUIPAMENTO="EQUIPAMENTO X", BANCO="Santander", STATUS="Em Análise", **{"VALOR (R$)": 1000.0},
    )
    registros = []
    for linha in linhas:
        registro = {**padrao, **linha}
        registro["TEMPO"] = bd._calcular_tempo(registro["DATA"], registro["STATUS"])
        registro["OBSERVAÇÕES"] = ""
        registros.append(registro)
    df = pd.DataFrame(registros, columns=bd.PROPOSTAS_COLUNAS)
    df["DATA"] = pd.to_datetime(df["DATA"])
    return df


def propostas_vazias() -> pd.DataFrame:
    from core import data_store as bd

    return pd.DataFrame(columns=bd.PROPOSTAS_COLUNAS)


def cpf_ficticio(n: int) -> str:
    """Um CPF VALIDO (digitos verificadores certos) derivado de `n` - pra cadastrar clientes de teste."""
    from core.validators import _digito_verificador_cpf

    base = f"{n % 10 ** 9:09d}"
    if len(set(base)) == 1:  # 111111111... e invalido de proposito
        base = f"{(n + 12345) % 10 ** 9:09d}"
    return base + _digito_verificador_cpf(base)


_BANCOS_DO_VOLUME = ["Santander", "Portobank", "Hubcred BV", "HUBCRED BV", "Medicalsan", "Mova HTM", "Gloriabank", "Todos", ""]
_PESOS_DE_STATUS = [
    (propostas_mod.STATUS_EM_ANALISE, 30), (propostas_mod.STATUS_NEGADO, 34), (propostas_mod.STATUS_APROVADO, 14),
    (propostas_mod.STATUS_PRE_APROVADO, 6), (propostas_mod.STATUS_NF_ANEXADA, 4), (propostas_mod.STATUS_GARANTIA_ASSINADA, 3),
    (propostas_mod.STATUS_EFETIVADO, 5),
]


def criar_volumoso(diretorio: Path, n_clientes: int = 26, semente: int = 7) -> Path:
    """Uma planilha fictícia maior (dezenas de propostas: varios bancos e status, datas de hoje a ~45 dias atras,
    algumas sem valor/meses, uma com data absurda, duplicatas, clientes que so tiveram negativas e clientes
    sem nenhuma proposta) - o bastante pro Dashboard parecer com o uso de verdade. Deterministica (`semente`)."""
    import random

    if config.SINCRONIZACAO_GOOGLE_ATIVADA:
        raise RuntimeError("Desligue config.SINCRONIZACAO_GOOGLE_ATIVADA antes de criar a fixture.")
    destino = Path(diretorio) / "controle_financiamentos_volumoso.xlsx"
    shutil.copy(EXEMPLO, destino)
    sorteio = random.Random(semente)
    status_e_pesos = [s for s, _ in _PESOS_DE_STATUS], [p for _, p in _PESOS_DE_STATUS]

    sessao_anterior = sessao_mod.atual()
    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
    caminhos_anteriores = _guardar_caminhos()
    try:
        apontar_modulos_para(destino)
        vendedores_mod.adicionar_vendedor("Vendedora Teste Dois")
        vendedores = ["Vendedor Exemplo", "Vendedora Teste Dois"]
        hoje = date.today()
        for posicao in range(len(propostas_mod.listar_propostas())):  # as do exemplo: datas fixas, como em criar()
            propostas_mod.atualizar_proposta(posicao, {"DATA": pd.Timestamp(hoje - timedelta(days=1 + posicao))})
        for i in range(n_clientes):
            cpf = cpf_ficticio(300_000_000 + i * 7919)
            clientes_mod.adicionar_cliente(
                {"CPF/CNPJ": cpf, "CLIENTE": f"Cliente Fictício {i + 1:02d}", "TIPO": "Cliente", "VENDEDOR": vendedores[i % 2]}
            )
            if i % 6 == 1:
                continue  # sem nenhuma proposta
            if i % 6 in (0, 5):  # so negativas, em bancos diferentes: candidato a "para reenviar" (9 clientes com 26)
                planos = [(propostas_mod.STATUS_NEGADO, banco) for banco in sorteio.sample(["Santander", "Portobank", "Medicalsan", "Mova HTM"], 2)]
            else:
                planos = [(sorteio.choices(*status_e_pesos)[0], sorteio.choice(_BANCOS_DO_VOLUME)) for _ in range(sorteio.randint(1, 3))]
            for status, banco in planos:
                dias = sorteio.randint(0, 45)
                campos = {
                    "CPF": cpf, "DATA": pd.Timestamp(hoje - timedelta(days=dias)), "STATUS": status, "BANCO": banco,
                    "EQUIPAMENTO": sorteio.choice(["Equipamento Modelo X", "Equipamento Modelo Y", "Equipamento Modelo Z"]),
                    "VALOR (R$)": sorteio.choice([25000, 35000, 48000, 60000, 75000, 90000, 120000]),
                }
                if sorteio.random() < 0.3:
                    campos["MESES"] = 36
                indice = propostas_mod.adicionar_proposta(campos)
                if sorteio.random() < 0.3:  # sem valor: so editando (cadastrar exige valor)
                    propostas_mod.atualizar_proposta(indice, {"VALOR (R$)": ""})
        # uma data absurda e uma duplicata (mesmo cliente, equipamento, banco e dia)
        cpf_um = cpf_ficticio(300_000_000)
        propostas_mod.adicionar_proposta({"CPF": cpf_um, "DATA": pd.Timestamp(2000, 8, 9), "STATUS": propostas_mod.STATUS_NEGADO, "BANCO": "Santander", "EQUIPAMENTO": "Equipamento Modelo X", "VALOR (R$)": 1000})
        for _ in range(2):
            propostas_mod.adicionar_proposta({"CPF": cpf_um, "DATA": pd.Timestamp(hoje - timedelta(days=4)), "STATUS": propostas_mod.STATUS_EM_ANALISE, "BANCO": "Portobank", "EQUIPAMENTO": "Equipamento Modelo Y", "VALOR (R$)": 55000})
    finally:
        _restaurar_caminhos(caminhos_anteriores)
        if sessao_anterior is None:
            sessao_mod.encerrar()
        else:
            sessao_mod.iniciar(sessao_anterior)
    return destino


_MODULOS = (clientes_mod, propostas_mod, vendedores_mod, equipamentos_mod)


class ColetorDeLog(logging.Handler):
    """Guarda o que um modulo registra no log em vez de imprimir na tela. Testes que provocam uma
    falha DE PROPOSITO usam isto: um "Traceback" impresso confundiria a varredura por erros de
    verdade - e o coletor ainda deixa provar que a falha FOI registrada (nunca em silencio)."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.registros: list[logging.LogRecord] = []

    def emit(self, registro: logging.LogRecord) -> None:
        self.registros.append(registro)

    def avisos_com_traceback(self) -> list[str]:
        return [r.getMessage() for r in self.registros if r.levelno >= logging.WARNING and r.exc_info]


@contextmanager
def capturar_log(nome_do_registrador: str):
    """`with capturar_log("desktop.main_window") as log:` - o que esse registrador emitir vai
    pra `log` (nao pra tela) dentro do bloco."""
    registrador = logging.getLogger(nome_do_registrador)
    coletor = ColetorDeLog()
    propagava = registrador.propagate
    registrador.addHandler(coletor)
    registrador.propagate = False
    try:
        yield coletor
    finally:
        registrador.removeHandler(coletor)
        registrador.propagate = propagava


def _guardar_caminhos() -> list[Path]:
    return [modulo.CAMINHO_XLSX for modulo in _MODULOS]


def _restaurar_caminhos(caminhos: list[Path]) -> None:
    for modulo, caminho in zip(_MODULOS, caminhos):
        modulo.CAMINHO_XLSX = caminho


def apontar_modulos_para(caminho: Path) -> None:
    """Faz as camadas de negocio lerem/escreverem em `caminho` (e nao na planilha real)."""
    for modulo in _MODULOS:
        modulo.CAMINHO_XLSX = caminho


def restaurar_modulos() -> None:
    for modulo in _MODULOS:
        modulo.CAMINHO_XLSX = config.CAMINHO_XLSX


def isolar_preferencias(diretorio: Path) -> None:
    """Manda as preferencias do app (QSettings: tema, ultima tela, geometria...) pra um
    .ini dentro de `diretorio`, em vez do registro do Windows do usuario - assim o teste
    nunca le nem grava as preferencias reais. Chamar antes de criar qualquer QSettings.
    Confere que o isolamento VALEU (o arquivo de preferencias esta mesmo dentro de
    `diretorio`) e recusa seguir se nao: um teste que grava no registro real muda o app do
    usuario sem ninguem ver."""
    from PySide6.QtCore import QSettings

    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(diretorio))

    from desktop import settings as settings_mod

    arquivo = Path(settings_mod._settings().fileName()).resolve()
    if Path(diretorio).resolve() not in arquivo.parents:
        raise RuntimeError(f"Isolamento das preferencias falhou: elas iriam pra {arquivo}, fora de {diretorio}.")


def instantaneo_do_registro() -> dict[str, object]:
    """As preferencias REAIS do app no registro do Windows (nome -> valor), so leitura. Pra o
    teste comparar antes e depois e provar que nao mexeu nelas. Fora do Windows, {}."""
    try:
        import winreg
    except ImportError:
        return {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\GestaoFinanciamentos\Desktop") as chave:
            valores = {}
            indice = 0
            while True:
                try:
                    nome, valor, _tipo = winreg.EnumValue(chave, indice)
                except OSError:
                    return valores
                valores[nome] = valor
                indice += 1
    except FileNotFoundError:
        return {}
