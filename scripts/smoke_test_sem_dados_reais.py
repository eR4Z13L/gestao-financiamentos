"""Guarda dos testes: nenhum scripts/smoke_test_*.py pode tocar a planilha real, a pasta data/ ou o Google de verdade.
Le o TEXTO de cada teste (nao roda nenhum) e reprova se achar:
  1. GESTAO_IGNORAR_CONFIG_LOCAL (so smoke_test_config_local.py, que testa o proprio mecanismo, pode citar);
  2. shutil.copy*(config.CAMINHO_XLSX ...) ou copia de CAMINHO_XLSX importado de config (e a planilha real);
  3. caminho de data/ ou data_dev_oficial (string "data/...", "data_dev_oficial", config.DIRETORIO_DADOS ou
     DIRETORIO_BASE / "data");
  4. import de core.data_store_sheets sem um duplo da rede no mesmo teste (_obter_cliente/_obter_planilha/
     _ler_aba_bruta trocados, ou o Ambiente de scripts/ambiente_de_teste.py, que troca _obter_cliente): sem ele o
     teste falaria com o Google de verdade.
Listar a pasta data/ so para provar que ela nao mudou (config.DIRETORIO_DADOS.glob/exists/iterdir) e permitido.
O guarda confere as proprias regras com exemplos ruins e bons antes de varrer (uma regra quebrada nao pode
passar calada).

Rodar com: venv/Scripts/python.exe scripts/smoke_test_sem_dados_reais.py
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

PASTA_SCRIPTS = Path(__file__).resolve().parent

# Testes que ainda tocam a planilha real e serao trocados depois (nome -> o que falta). ESVAZIAR quando
# acontecer: o guarda reprova um pendente que ja esta limpo, para a lista nao ficar velha.
PENDENTES: dict[str, str] = {}

TESTE_DA_CONFIG_LOCAL = "smoke_test_config_local.py"
FUNCOES_DE_COPIA = {"copy", "copy2", "copyfile", "copyfileobj", "copytree"}
DUPLOS_DA_REDE = {"_obter_cliente", "_obter_planilha", "_ler_aba_bruta"}
SO_LEITURA_DA_PASTA = {"glob", "exists", "iterdir"}
AMBIENTE_COM_DUPLO = "ambiente_de_teste"  # scripts/ambiente_de_teste.py: o Ambiente troca _obter_cliente


def _nome_com_pontos(no: ast.AST) -> str:
    return ast.unparse(no) if isinstance(no, (ast.Name, ast.Attribute)) else ""


def _docstrings(arvore: ast.AST) -> set[int]:
    """Ids dos nos de texto que sao docstring (prosa; podem citar data/ sem tocar nela)."""
    ids = set()
    for no in ast.walk(arvore):
        if isinstance(no, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and no.body:
            primeiro = no.body[0]
            if isinstance(primeiro, ast.Expr) and isinstance(primeiro.value, ast.Constant) and isinstance(primeiro.value.value, str):
                ids.add(id(primeiro.value))
    return ids


def problemas_do_texto(nome: str, texto: str) -> list[str]:
    """Os motivos pelos quais o teste `nome` (com esse conteudo) reprova; vazio = limpo."""
    achados = []
    if "GESTAO_IGNORAR_CONFIG_LOCAL" in texto and nome != TESTE_DA_CONFIG_LOCAL:
        achados.append("usa GESTAO_IGNORAR_CONFIG_LOCAL (cai na planilha real)")
    try:
        arvore = ast.parse(texto)
    except SyntaxError as erro:
        return achados + [f"nao foi possivel ler o arquivo: {erro}"]

    importa_caminho_da_config = False
    importa_nuvem = False
    troca_a_rede = False
    docstrings = _docstrings(arvore)
    so_conferencias = {id(no.value) for no in ast.walk(arvore)
                       if isinstance(no, ast.Attribute) and no.attr in SO_LEITURA_DA_PASTA}
    for no in ast.walk(arvore):
        if isinstance(no, ast.ImportFrom):
            if no.module == AMBIENTE_COM_DUPLO:
                troca_a_rede = True
            if no.module == "config" and any(a.name == "CAMINHO_XLSX" for a in no.names):
                importa_caminho_da_config = True
            if no.module == "core.data_store_sheets" or (no.module == "core" and any(a.name == "data_store_sheets" for a in no.names)):
                importa_nuvem = True
        elif isinstance(no, ast.Import):
            importa_nuvem = importa_nuvem or any(a.name == "core.data_store_sheets" for a in no.names)
            troca_a_rede = troca_a_rede or any(a.name == AMBIENTE_COM_DUPLO for a in no.names)
        elif isinstance(no, ast.Attribute) and isinstance(no.ctx, ast.Store) and no.attr in DUPLOS_DA_REDE:
            troca_a_rede = True
        elif isinstance(no, ast.Constant) and isinstance(no.value, str):
            if no.value in DUPLOS_DA_REDE:  # setattr(modulo, "_obter_cliente", ...) / mock.patch
                troca_a_rede = True
            if id(no) in docstrings:
                continue
            if "data_dev_oficial" in no.value:
                achados.append(f"linha {no.lineno}: cita data_dev_oficial")
            elif re.match(r"^\.{0,2}[\\/]?data[\\/]", no.value):
                achados.append(f"linha {no.lineno}: caminho dentro de data/ ({no.value!r})")
        elif isinstance(no, ast.Attribute) and no.attr == "DIRETORIO_DADOS" and id(no) not in so_conferencias:
            achados.append(f"linha {no.lineno}: usa DIRETORIO_DADOS (a pasta data/ real)")
        elif isinstance(no, ast.BinOp) and isinstance(no.op, ast.Div):
            if isinstance(no.right, ast.Constant) and no.right.value == "data" and re.search(r"DIRETORIO_BASE|__file__", ast.unparse(no.left)):
                achados.append(f"linha {no.lineno}: monta o caminho da pasta data/ do projeto")

    for no in ast.walk(arvore):  # segunda passada: precisa de importa_caminho_da_config ja conhecido
        if isinstance(no, ast.Call) and _nome_com_pontos(no.func).split(".")[-1] in FUNCOES_DE_COPIA and no.args:
            origem = _nome_com_pontos(no.args[0])
            if origem == "config.CAMINHO_XLSX" or (origem == "CAMINHO_XLSX" and importa_caminho_da_config):
                achados.append(f"linha {no.lineno}: copia a planilha real ({origem})")

    if importa_nuvem and not troca_a_rede:
        achados.append("importa core.data_store_sheets sem duplo da rede (_obter_cliente/_obter_planilha/_ler_aba_bruta)")
    return achados


def _conferir_as_regras() -> None:
    """Exemplos ruins que TEM de reprovar e bons que TEM de passar - a regra nao pode estar quebrada."""
    ruins = {
        "ignorar": "import os\nos.environ['GESTAO_IGNORAR_CONFIG_LOCAL'] = '1'\n",
        "copia_config": "import shutil, config\nshutil.copy(config.CAMINHO_XLSX, 'x')\n",
        "copia_importada": "import shutil\nfrom config import CAMINHO_XLSX\nshutil.copy2(CAMINHO_XLSX, 'x')\n",
        "data_relativa": "from pathlib import Path\np = Path('data/controle.dat')\n",
        "data_dev_oficial": "p = 'data_dev_oficial/x.dat'\n",
        "diretorio_dados": "import config\np = config.DIRETORIO_DADOS\n",
        "base_barra_data": "import config\np = config.DIRETORIO_BASE / 'data' / 'x'\n",
        "nuvem_sem_duplo": "from core import data_store_sheets as nuvem\nnuvem.ler()\n",
        "nuvem_import_direto": "from core.data_store_sheets import ler\n",
        "nuvem_import_simples": "import core.data_store_sheets\n",
    }
    for rotulo, texto in ruins.items():
        assert problemas_do_texto("smoke_test_exemplo.py", texto), f"a regra deixou passar o exemplo ruim {rotulo!r}"
    bons = {
        "restaurar_so": "from core import propostas\nimport fixture_ficticia as fx\nfx.restaurar_modulos()\n",
        "doc_cita_data": '"""Nunca toca em data/ nem em data_dev_oficial."""\nx = 1\n',
        "data_do_tmp": "from pathlib import Path\np = Path('tmp') / 'data' / 'x'\nq = 'spin/data/combos'\n",
        "copia_da_fixture": "import shutil\nshutil.copy(caminho_da_fixture, 'x')\n",
        "nuvem_com_duplo": "from core import data_store_sheets as nuvem\nnuvem._obter_cliente = lambda: None\n",
        "nuvem_com_ler_aba": "from core import data_store_sheets as nuvem\nnuvem._ler_aba_bruta = lambda a: a\n",
        "nuvem_com_ambiente": "from ambiente_de_teste import Ambiente\nfrom core import data_store_sheets as nuvem\n",
        "lista_data_so_para_conferir": "import config\nx = sorted(config.DIRETORIO_DADOS.glob('*')) if config.DIRETORIO_DADOS.exists() else []\n",
        "nuvem_com_setattr": "from core import data_store_sheets as nuvem\nsetattr(nuvem, '_obter_planilha', None)\n",
    }
    for rotulo, texto in bons.items():
        achados = problemas_do_texto("smoke_test_exemplo.py", texto)
        assert not achados, f"a regra reprovou o exemplo bom {rotulo!r}: {achados}"
    assert not problemas_do_texto(TESTE_DA_CONFIG_LOCAL, ruins["ignorar"]), "o teste da config local pode citar a variavel"


def main() -> None:
    _conferir_as_regras()
    print("OK: as regras do guarda reprovam os exemplos ruins e deixam passar os bons.")

    ambiente = (PASTA_SCRIPTS / f"{AMBIENTE_COM_DUPLO}.py").read_text(encoding="utf-8")
    assert re.search(r"_obter_cliente\s*=", ambiente), f"{AMBIENTE_COM_DUPLO}.py deixou de trocar _obter_cliente: o guarda confia nele"

    testes = sorted(p for p in PASTA_SCRIPTS.glob("smoke_test_*.py") if p.name != Path(__file__).name)
    assert testes, "nenhum smoke_test_*.py encontrado"
    nomes = {p.name for p in testes}
    desconhecidos = sorted(set(PENDENTES) - nomes)
    assert not desconhecidos, f"PENDENTES cita teste que nao existe mais: {desconhecidos}"

    reprovados = {}
    pendentes_limpos = []
    for caminho in testes:
        achados = problemas_do_texto(caminho.name, caminho.read_text(encoding="utf-8"))
        if caminho.name in PENDENTES:
            if achados:
                print(f"PENDENTE (conhecido): {caminho.name} - {PENDENTES[caminho.name]}")
            else:
                pendentes_limpos.append(caminho.name)
        elif achados:
            reprovados[caminho.name] = achados

    for nome, achados in reprovados.items():
        for achado in achados:
            print(f"REPROVADO: {nome}: {achado}")
    for nome in pendentes_limpos:
        print(f"REPROVADO: {nome} ja esta limpo - tire-o da lista PENDENTES no topo de {Path(__file__).name}")
    if reprovados or pendentes_limpos:
        sys.exit(1)
    print(f"OK: {len(testes)} testes varridos, nenhum toca dado real (pendentes conhecidos: {len(PENDENTES)}).")


if __name__ == "__main__":
    main()
