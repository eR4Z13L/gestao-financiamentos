"""Testa o login com dois niveis de acesso (Fase 2):
1. core.auth - hash/verificacao de senha (arquivo de credencial em copia
   temporaria, nunca a senha real do ADMIN).
2. core.sessao - guard de escrita (exigir_admin) e filtro por vendedor
   logado, testados de forma isolada (sem tocar em nenhum arquivo).
3. core.data_store_sheets - leitura do Google Sheets SIMULADO: uma planilha
   100% ficticia (scripts/fixture_ficticia.py) e enviada a um Google falso em
   memoria pelo mesmo caminho do app (sheets_sync._escrever_aba) e lida de
   volta - confere que o formato bate com core.data_store (mesmas colunas,
   contagem de linhas, tipos) e o login de vendedor (senha certa aceita; senha
   ERRADA ou usuario inexistente recusados). Nenhum byte vai pro Google de
   verdade: o acesso real derruba o teste.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_fase2.py
"""

from __future__ import annotations

import atexit
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gspread
import pandas as pd

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
import fixture_ficticia as fx
from core import auth
from core import data_store as bd
from core import data_store_sheets as bd_sheets
from core import sessao as sessao_mod
from core import sheets_sync
from core import vendedores as vendedores_mod

# as copias que o teste grava ficam numa pasta temporaria, nunca ao lado da planilha (testes em paralelo
# esbarrariam nelas, e a conferencia da pasta de dados acusaria arquivo a mais)
PASTA_TEMPORARIA = Path(tempfile.mkdtemp(prefix="smoke_test_"))
atexit.register(shutil.rmtree, PASTA_TEMPORARIA, True)


class _AbaFalsa:
    """Uma aba do Google falso: guarda os valores como a API guardaria (so o que passa por JSON)."""

    def __init__(self):
        self.valores: list[list] = []

    def clear(self) -> None:
        self.valores = []

    def update(self, valores, range_name=None, raw=True, **_kw) -> None:
        assert range_name == "A1" and raw is True, "o envio sobrescreve a aba inteira em modo RAW"
        self.valores = json.loads(json.dumps(valores))  # a API de verdade so aceita JSON

    def get_all_values(self, value_render_option=None, **_kw):
        assert value_render_option == "UNFORMATTED_VALUE", "a leitura pede os valores sem formatacao"
        return [list(linha_) for linha_ in self.valores]


class _GoogleFalso:
    """O cliente gspread e a planilha aberta, em memoria."""

    def __init__(self):
        self.abas: dict[str, _AbaFalsa] = {}

    def open_by_key(self, _chave):
        return self

    def worksheet(self, nome: str) -> _AbaFalsa:
        if nome not in self.abas:
            raise gspread.WorksheetNotFound(nome)
        return self.abas[nome]

    def add_worksheet(self, title, rows, cols) -> _AbaFalsa:
        self.abas[title] = _AbaFalsa()
        return self.abas[title]


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def testar_hash_senha() -> None:
    linha("1) core.auth - hash/verificação de senha")

    hash1, salt1 = auth.hash_senha("MinhaSenh@123")
    assert auth.senha_confere("MinhaSenh@123", hash1, salt1)
    assert not auth.senha_confere("senha errada", hash1, salt1)
    print("OK: senha correta confere, senha errada não confere.")

    hash2, salt2 = auth.hash_senha("MinhaSenh@123")
    assert salt1 != salt2, "cada hash deveria usar um salt novo"
    assert hash1 != hash2, "a mesma senha com salts diferentes deveria gerar hashes diferentes"
    print("OK: salts (e hashes) diferentes a cada chamada, mesmo com a mesma senha.")

    senha_gerada = auth.gerar_senha_aleatoria()
    assert len(senha_gerada) == 8
    assert not any(c in senha_gerada for c in "0O1lI"), "não deveria conter caracteres ambíguos"
    print(f"OK: senha aleatória gerada sem caracteres ambíguos -> {senha_gerada!r}")


def testar_credencial_admin_em_copia_temporaria(tmp_path: Path) -> None:
    linha("2) core.auth - credencial do ADMIN (arquivo local, copia temporária)")

    original = auth.CAMINHO_CREDENCIAIS_ADMIN
    auth.CAMINHO_CREDENCIAIS_ADMIN = tmp_path
    try:
        assert not auth.admin_configurado(), "não deveria existir credencial ainda"
        print("OK: admin_configurado() == False antes de definir qualquer senha.")

        auth.definir_senha_admin("SenhaDeTeste1")
        assert auth.admin_configurado()
        assert auth.verificar_senha_admin("SenhaDeTeste1")
        assert not auth.verificar_senha_admin("senha errada")
        print("OK: senha do admin definida e verificada corretamente (arquivo local).")
    finally:
        auth.CAMINHO_CREDENCIAIS_ADMIN = original
        tmp_path.unlink(missing_ok=True)


def testar_sessao_e_guard_de_escrita() -> None:
    linha("3) core.sessao - exigir_admin() e filtrar_por_vendedor_logado()")

    sessao_mod.encerrar()
    assert not sessao_mod.eh_admin() and not sessao_mod.eh_vendedor()
    try:
        sessao_mod.exigir_admin()
        raise SystemExit("deveria ter bloqueado sem nenhuma sessão ativa")
    except sessao_mod.PermissaoNegada:
        print("OK: exigir_admin() bloqueia quando ninguém está logado.")

    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_VENDEDOR, nome_usuario="VENDEDORA TESTE"))
    assert sessao_mod.eh_vendedor() and not sessao_mod.eh_admin()
    try:
        sessao_mod.exigir_admin()
        raise SystemExit("deveria ter bloqueado uma sessão de vendedor")
    except sessao_mod.PermissaoNegada:
        print("OK: exigir_admin() bloqueia uma sessão de VENDEDOR.")

    df = pd.DataFrame({"VENDEDOR": ["Vendedora Teste", "OUTRO TESTE", "vendedora teste ", ""], "X": [1, 2, 3, 4]})
    filtrado = sessao_mod.filtrar_por_vendedor_logado(df)
    assert list(filtrado["X"]) == [1, 3], "deveria pegar só as linhas da VENDEDORA TESTE, sem diferenciar maiúsculas/espaço"
    print("OK: filtrar_por_vendedor_logado() pega só as linhas do vendedor logado (case/espaço-insensível).")

    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
    assert sessao_mod.eh_admin()
    sessao_mod.exigir_admin()  # nao pode levantar
    filtrado_admin = sessao_mod.filtrar_por_vendedor_logado(df)
    assert len(filtrado_admin) == len(df), "ADMIN vê tudo, sem filtro"
    print("OK: sessão ADMIN passa por exigir_admin() e não filtra nada.")

    sessao_mod.encerrar()


def montar_google_falso(caminho: Path) -> dict[str, str]:
    """Gera as senhas iniciais dos vendedores da planilha ficticia, manda as abas pro Google falso pelo
    mesmo caminho do app e liga a leitura do vendedor nele. Devolve {vendedor: senha} pro teste de login."""
    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
    senhas = vendedores_mod.gerar_senhas_iniciais_pendentes()
    sessao_mod.encerrar()
    google = _GoogleFalso()
    for aba, leitor in ((bd.ABA_CLIENTES, bd.ler_clientes), (bd.ABA_PROPOSTAS, bd.ler_propostas),
                        (bd.ABA_VENDEDORES, bd.ler_vendedores)):
        sheets_sync._escrever_aba(google, aba, leitor(caminho))
    bd_sheets._obter_cliente = lambda: google
    bd_sheets.esquecer_conexao()
    return senhas


def testar_leitura_sheets_bate_com_local(caminho: Path) -> None:
    linha("4) core.data_store_sheets - leitura do Google Sheets simulado (planilha fictícia)")

    clientes_local = bd.ler_clientes(caminho)
    clientes_sheets = bd_sheets.ler_clientes()
    assert list(clientes_sheets.columns) == list(bd.CLIENTES_COLUNAS)
    assert len(clientes_sheets) == len(clientes_local), (
        f"Sheets tem {len(clientes_sheets)} clientes, local tem {len(clientes_local)} - "
        "rode a sincronização inicial se a planilha estiver desatualizada"
    )
    print(f"OK: CLIENTES no Sheets bate com o local ({len(clientes_sheets)} linhas, mesmas colunas).")

    propostas_local = bd.ler_propostas(caminho)
    propostas_sheets = bd_sheets.ler_propostas()
    assert list(propostas_sheets.columns) == list(bd.PROPOSTAS_COLUNAS)
    assert len(propostas_sheets) == len(propostas_local)
    # numero, nao texto (na planilha ficticia so ha valores redondos: inteiro, como o local tambem le)
    assert pd.api.types.is_numeric_dtype(propostas_sheets["VALOR (R$)"]), "VALOR (R$) deveria vir como numero, nao texto"
    assert list(propostas_sheets["VALOR (R$)"]) == list(propostas_local["VALOR (R$)"]), "os valores voltam iguais"
    assert pd.api.types.is_datetime64_any_dtype(propostas_sheets["DATA"]), "DATA deveria vir como data, nao texto"
    print(f"OK: PROPOSTAS no Sheets bate com o local ({len(propostas_sheets)} linhas, tipos corretos).")

    vendedores_sheets = bd_sheets.ler_vendedores()
    assert set(vendedores_sheets.columns) == {"NOME", "SENHA_HASH", "SALT", "ATIVO"}
    # nao exige TODOS com senha definida: um vendedor recem-importado/cadastrado fica
    # "Pendente" ate o admin gerar a senha inicial pela tela (core.vendedores.
    # gerar_senhas_iniciais_pendentes) - um estado valido, nao um erro de sincronizacao.
    pendentes = int((vendedores_sheets["SENHA_HASH"] == "").sum())
    print(f"OK: VENDEDORES no Sheets tem {len(vendedores_sheets)} linha(s) ({pendentes} com senha pendente).")


def testar_login_vendedor(senhas: dict[str, str]) -> None:
    linha("5) core.vendedores.verificar_login - senha certa aceita, casos inválidos recusados")

    assert senhas, "a planilha fictícia deveria ter vendedor sem senha pra gerar"
    for nome, senha in senhas.items():
        assert vendedores_mod.verificar_login(nome, senha) == nome
        assert vendedores_mod.verificar_login(f"  {nome.lower()} ", senha) == nome, "nome sem diferenciar maiúsculas/espaço"
    print(f"OK: senha certa aceita para {len(senhas)} vendedor(es) fictício(s), devolvendo a grafia cadastrada.")

    assert vendedores_mod.verificar_login("Vendedor Que Nao Existe", "qualquer-coisa") is None
    print("OK: usuário inexistente é recusado.")

    algum_vendedor = vendedores_mod.listar_vendedores()[0]
    assert vendedores_mod.verificar_login(algum_vendedor, "com certeza senha errada") is None
    print(f"OK: senha errada para um vendedor cadastrado ('{algum_vendedor}') é recusada.")


def main() -> None:
    testar_hash_senha()
    testar_credencial_admin_em_copia_temporaria(PASTA_TEMPORARIA / "_smoke_test_admin_senha.json")
    testar_sessao_e_guard_de_escrita()
    caminho = fx.criar(PASTA_TEMPORARIA)
    fx.apontar_modulos_para(caminho)
    fx.bloquear_google()
    senhas = montar_google_falso(caminho)
    testar_leitura_sheets_bate_com_local(caminho)
    testar_login_vendedor(senhas)
    linha("TUDO OK")


if __name__ == "__main__":
    main()
