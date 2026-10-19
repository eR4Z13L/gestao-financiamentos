"""Testa o login com dois niveis de acesso (Fase 2):
1. core.auth - hash/verificacao de senha (arquivo de credencial em copia
   temporaria, nunca a senha real do ADMIN).
2. core.sessao - guard de escrita (exigir_admin) e filtro por vendedor
   logado, testados de forma isolada (sem tocar em nenhum arquivo).
3. core.data_store_sheets - leitura do Google Sheets contra um DUPLO (uma planilha de
   mentira montada da fixture ficticia, scripts/fixture_ficticia.py; nenhum acesso a
   rede nem a credencial) - confere que o formato bate com core.data_store (mesmas
   colunas, tipos, contagem de linhas), que aba ausente levanta WorksheetNotFound e que
   o login de vendedor funciona com a senha certa e e recusado com senha ERRADA ou
   usuario inexistente.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_fase2.py
"""

from __future__ import annotations

import atexit
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from contextlib import contextmanager

import gspread
import pandas as pd

import config

config.SINCRONIZACAO_GOOGLE_ATIVADA = False  # nunca manda dado de teste pra planilha real na nuvem
import fixture_ficticia
from core import auth
from core import data_store as bd
from core import data_store_sheets as bd_sheets
from core import sessao as sessao_mod
from core import vendedores as vendedores_mod

# as copias que o teste grava ficam numa pasta temporaria, nunca ao lado da planilha (testes em paralelo
# esbarrariam nelas, e a conferencia da pasta de dados acusaria arquivo a mais)
PASTA_TEMPORARIA = Path(tempfile.mkdtemp(prefix="smoke_test_"))
atexit.register(shutil.rmtree, PASTA_TEMPORARIA, True)


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

    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_VENDEDOR, nome_usuario="JOANA TESTE"))
    assert sessao_mod.eh_vendedor() and not sessao_mod.eh_admin()
    try:
        sessao_mod.exigir_admin()
        raise SystemExit("deveria ter bloqueado uma sessão de vendedor")
    except sessao_mod.PermissaoNegada:
        print("OK: exigir_admin() bloqueia uma sessão de VENDEDOR.")

    df = pd.DataFrame({"VENDEDOR": ["Joana Teste", "CARLOS TESTE", "joana teste ", ""], "X": [1, 2, 3, 4]})
    filtrado = sessao_mod.filtrar_por_vendedor_logado(df)
    assert list(filtrado["X"]) == [1, 3], "deveria pegar só as linhas da JOANA TESTE, sem diferenciar maiúsculas/espaço"
    print("OK: filtrar_por_vendedor_logado() pega só as linhas do vendedor logado (case/espaço-insensível).")

    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
    assert sessao_mod.eh_admin()
    sessao_mod.exigir_admin()  # nao pode levantar
    filtrado_admin = sessao_mod.filtrar_por_vendedor_logado(df)
    assert len(filtrado_admin) == len(df), "ADMIN vê tudo, sem filtro"
    print("OK: sessão ADMIN passa por exigir_admin() e não filtra nada.")

    sessao_mod.encerrar()


SENHA_DO_VENDEDOR_DE_TESTE = "senha-de-teste-do-duplo"


class _AbaDeMentira:
    def __init__(self, valores: list[list]):
        self._valores = valores

    def get_all_values(self, **_kwargs) -> list[list]:
        return [list(linha) for linha in self._valores]


class _PlanilhaDeMentira:
    def __init__(self, abas: dict[str, list[list]]):
        self._abas = abas

    def worksheet(self, nome: str) -> _AbaDeMentira:
        if nome not in self._abas:
            raise gspread.WorksheetNotFound(nome)
        return _AbaDeMentira(self._abas[nome])


def _valor_da_celula(valor):
    """Como o Sheets devolve (UNFORMATTED_VALUE): data como texto dd/mm/aaaa (o que o app envia),
    numero como numero, vazio como ''."""
    if valor is None or valor is pd.NaT or (isinstance(valor, float) and valor != valor):
        return ""
    if isinstance(valor, pd.Timestamp):
        return valor.strftime("%d/%m/%Y")
    if hasattr(valor, "item"):  # numpy -> python
        return valor.item()
    return valor


def _valores_da_aba(df: pd.DataFrame) -> list[list]:
    return [list(df.columns)] + [[_valor_da_celula(v) for v in linha] for linha in df.itertuples(index=False)]


@contextmanager
def _google_de_mentira(caminho_xlsx: Path):
    """Troca o ponto unico de rede de core.data_store_sheets por uma planilha de mentira montada da
    fixture (so as abas CLIENTES/EQUIPAMENTOS/PROPOSTAS/VENDEDORES: as outras NAO existem, como numa
    nuvem antiga). Qualquer tentativa de abrir o cliente real do Google derruba o teste."""
    clientes = bd.ler_clientes(caminho_xlsx)
    vendedores = bd.ler_vendedores(caminho_xlsx)
    hash_hex, salt_hex = auth.hash_senha(SENHA_DO_VENDEDOR_DE_TESTE)
    vendedores.loc[0, ["SENHA_HASH", "SALT"]] = [hash_hex, salt_hex]
    abas = {
        bd.ABA_CLIENTES: _valores_da_aba(clientes),
        bd.ABA_EQUIPAMENTOS: _valores_da_aba(bd.ler_equipamentos(caminho_xlsx)),
        bd.ABA_PROPOSTAS: _valores_da_aba(bd.ler_propostas(caminho_xlsx, df_clientes=clientes)),
        bd.ABA_VENDEDORES: _valores_da_aba(vendedores),
    }
    # um cliente com a data de cadastro como numero serial (planilha enviada por versao antiga do app)
    serial = (clientes.loc[0, "DATA CADASTRO"] - pd.Timestamp(1899, 12, 30)).days
    abas[bd.ABA_CLIENTES][1][bd.CLIENTES_COLUNAS.index("DATA CADASTRO")] = serial

    def _cliente_proibido():
        raise AssertionError("o teste tentou abrir o cliente REAL do Google")

    originais = (bd_sheets._obter_planilha, bd_sheets._obter_cliente)
    bd_sheets._obter_planilha = lambda: _PlanilhaDeMentira(abas)
    bd_sheets._obter_cliente = _cliente_proibido
    try:
        yield abas
    finally:
        bd_sheets._obter_planilha, bd_sheets._obter_cliente = originais


def testar_leitura_sheets_bate_com_local(caminho_xlsx: Path) -> None:
    linha("4) core.data_store_sheets - leitura do Google (duplo montado da fixture, sem rede)")

    with _google_de_mentira(caminho_xlsx):
        clientes_local = bd.ler_clientes(caminho_xlsx)
        clientes_sheets = bd_sheets.ler_clientes()
        assert list(clientes_sheets.columns) == list(bd.CLIENTES_COLUNAS)
        assert len(clientes_sheets) == len(clientes_local) > 0
        assert clientes_sheets["CPF/CNPJ"].tolist() == clientes_local["CPF/CNPJ"].tolist()
        assert clientes_sheets["DATA CADASTRO"].equals(clientes_local["DATA CADASTRO"]), (
            "a data de cadastro (texto dd/mm/aaaa ou numero serial) deveria voltar igual ao local"
        )
        print(f"OK: CLIENTES no Sheets bate com o local ({len(clientes_sheets)} linhas, mesmas colunas, datas lidas).")

        propostas_local = bd.ler_propostas(caminho_xlsx)
        propostas_sheets = bd_sheets.ler_propostas()
        assert list(propostas_sheets.columns) == list(bd.PROPOSTAS_COLUNAS)
        assert len(propostas_sheets) == len(propostas_local) > 0
        # numero (inteiro ou decimal), nunca texto
        assert propostas_sheets["VALOR (R$)"].dtype.kind in "fi", "VALOR (R$) deveria vir como numero, nao texto"
        assert propostas_sheets["VALOR (R$)"].tolist() == propostas_local["VALOR (R$)"].tolist()
        assert pd.api.types.is_datetime64_any_dtype(propostas_sheets["DATA"]), "DATA deveria vir como data, nao texto"
        assert propostas_sheets["DATA"].tolist() == propostas_local["DATA"].tolist()
        print(f"OK: PROPOSTAS no Sheets bate com o local ({len(propostas_sheets)} linhas, tipos corretos).")

        equipamentos_sheets = bd_sheets.ler_equipamentos()
        assert len(equipamentos_sheets) == len(bd.ler_equipamentos(caminho_xlsx)) > 0
        print(f"OK: EQUIPAMENTOS no Sheets tem {len(equipamentos_sheets)} linhas.")

        vendedores_sheets = bd_sheets.ler_vendedores()
        assert set(vendedores_sheets.columns) == {"NOME", "SENHA_HASH", "SALT", "ATIVO"}
        assert len(vendedores_sheets) == len(bd.ler_vendedores(caminho_xlsx)) > 0
        # nao exige TODOS com senha definida: um vendedor recem-importado/cadastrado fica
        # "Pendente" ate o admin gerar a senha inicial pela tela (core.vendedores.
        # gerar_senhas_iniciais_pendentes) - um estado valido, nao um erro de sincronizacao.
        pendentes = int((vendedores_sheets["SENHA_HASH"] == "").sum())
        assert pendentes == len(vendedores_sheets) - 1, "so o vendedor do duplo tem senha definida"
        print(f"OK: VENDEDORES no Sheets tem {len(vendedores_sheets)} linha(s) ({pendentes} com senha pendente).")

        # abas que a nuvem ainda nao tem: o erro explicito do gspread, nunca um DataFrame vazio calado
        for leitor in (bd_sheets.ler_bancos, bd_sheets.ler_vendas, bd_sheets.ler_historico):
            try:
                leitor()
                raise SystemExit(f"{leitor.__name__} deveria levantar WorksheetNotFound com a aba ausente")
            except gspread.WorksheetNotFound:
                pass
        print("OK: aba ausente (BANCOS/VENDAS/HISTÓRICO) levanta gspread.WorksheetNotFound.")


def testar_login_vendedor_recusa_casos_invalidos(caminho_xlsx: Path) -> None:
    linha("5) core.vendedores.verificar_login - senha certa entra; casos inválidos são recusados (duplo do Google)")

    with _google_de_mentira(caminho_xlsx):
        assert vendedores_mod.verificar_login("Vendedor Que Nao Existe", "qualquer-coisa") is None
        print("OK: usuário inexistente é recusado.")

        vendedor_do_duplo = bd.ler_vendedores(caminho_xlsx).loc[0, "NOME"]  # o da fixture, com senha no duplo
        assert vendedores_mod.verificar_login(vendedor_do_duplo, "com certeza senha errada") is None
        print(f"OK: senha errada para um usuário existente ('{vendedor_do_duplo}') é recusada.")

        assert vendedores_mod.verificar_login(vendedor_do_duplo.lower(), SENHA_DO_VENDEDOR_DE_TESTE) == vendedor_do_duplo
        print("OK: senha certa entra e devolve o nome com a grafia oficial.")


def main() -> None:
    testar_hash_senha()
    testar_credencial_admin_em_copia_temporaria(PASTA_TEMPORARIA / "_smoke_test_admin_senha.json")
    testar_sessao_e_guard_de_escrita()
    caminho_xlsx = fixture_ficticia.criar(PASTA_TEMPORARIA)
    testar_leitura_sheets_bate_com_local(caminho_xlsx)
    testar_login_vendedor_recusa_casos_invalidos(caminho_xlsx)
    linha("TUDO OK")


if __name__ == "__main__":
    main()
