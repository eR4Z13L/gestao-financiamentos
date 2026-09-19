"""Testa o login com dois niveis de acesso (Fase 2):
1. core.auth - hash/verificacao de senha (arquivo de credencial em copia
   temporaria, nunca a senha real do ADMIN).
2. core.sessao - guard de escrita (exigir_admin) e filtro por vendedor
   logado, testados de forma isolada (sem tocar em nenhum arquivo).
3. core.data_store_sheets - leitura real do Google Sheets (SO LEITURA,
   nunca escreve) - confere que o formato bate com core.data_store (mesmas
   colunas, contagem de linhas) e que login de vendedor com senha ERRADA ou
   usuario inexistente e recusado (o caso de senha CORRETA foi validado
   manualmente, pra nao expor uma senha real de vendedor neste arquivo).

Rodar com: venv/Scripts/python.exe scripts/smoke_test_fase2.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from config import CAMINHO_XLSX
from core import auth
from core import data_store as bd
from core import data_store_sheets as bd_sheets
from core import sessao as sessao_mod
from core import vendedores as vendedores_mod


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

    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_VENDEDOR, nome_usuario="ARIANE"))
    assert sessao_mod.eh_vendedor() and not sessao_mod.eh_admin()
    try:
        sessao_mod.exigir_admin()
        raise SystemExit("deveria ter bloqueado uma sessão de vendedor")
    except sessao_mod.PermissaoNegada:
        print("OK: exigir_admin() bloqueia uma sessão de VENDEDOR.")

    df = pd.DataFrame({"VENDEDOR": ["Ariane", "BRUNO", "ariane ", ""], "X": [1, 2, 3, 4]})
    filtrado = sessao_mod.filtrar_por_vendedor_logado(df)
    assert list(filtrado["X"]) == [1, 3], "deveria pegar só as linhas da ARIANE, sem diferenciar maiúsculas/espaço"
    print("OK: filtrar_por_vendedor_logado() pega só as linhas do vendedor logado (case/espaço-insensível).")

    sessao_mod.iniciar(sessao_mod.Sessao(papel=sessao_mod.PAPEL_ADMIN, nome_usuario="Administrador"))
    assert sessao_mod.eh_admin()
    sessao_mod.exigir_admin()  # nao pode levantar
    filtrado_admin = sessao_mod.filtrar_por_vendedor_logado(df)
    assert len(filtrado_admin) == len(df), "ADMIN vê tudo, sem filtro"
    print("OK: sessão ADMIN passa por exigir_admin() e não filtra nada.")

    sessao_mod.encerrar()


def testar_leitura_sheets_bate_com_local() -> None:
    linha("4) core.data_store_sheets - leitura real do Google Sheets (só leitura)")

    clientes_local = bd.ler_clientes(CAMINHO_XLSX)
    clientes_sheets = bd_sheets.ler_clientes()
    assert list(clientes_sheets.columns) == list(bd.CLIENTES_COLUNAS)
    assert len(clientes_sheets) == len(clientes_local), (
        f"Sheets tem {len(clientes_sheets)} clientes, local tem {len(clientes_local)} - "
        "rode a sincronização inicial se a planilha estiver desatualizada"
    )
    print(f"OK: CLIENTES no Sheets bate com o local ({len(clientes_sheets)} linhas, mesmas colunas).")

    propostas_local = bd.ler_propostas(CAMINHO_XLSX)
    propostas_sheets = bd_sheets.ler_propostas()
    assert list(propostas_sheets.columns) == list(bd.PROPOSTAS_COLUNAS)
    assert len(propostas_sheets) == len(propostas_local)
    assert propostas_sheets["VALOR (R$)"].dtype.kind == "f", "VALOR (R$) deveria vir como numero, nao texto"
    assert pd.api.types.is_datetime64_any_dtype(propostas_sheets["DATA"]), "DATA deveria vir como data, nao texto"
    print(f"OK: PROPOSTAS no Sheets bate com o local ({len(propostas_sheets)} linhas, tipos corretos).")

    vendedores_sheets = bd_sheets.ler_vendedores()
    assert set(vendedores_sheets.columns) == {"NOME", "SENHA_HASH", "SALT"}
    assert (vendedores_sheets["SENHA_HASH"] != "").all(), "todo vendedor deveria ter senha definida"
    print(f"OK: VENDEDORES no Sheets tem {len(vendedores_sheets)} linha(s), todas com senha definida.")


def testar_login_vendedor_recusa_casos_invalidos() -> None:
    linha("5) core.vendedores.verificar_login - casos inválidos (login correto já testado manualmente)")

    assert vendedores_mod.verificar_login("Vendedor Que Nao Existe", "qualquer-coisa") is None
    print("OK: usuário inexistente é recusado.")

    algum_vendedor = vendedores_mod.listar_vendedores()[0]
    assert vendedores_mod.verificar_login(algum_vendedor, "com certeza senha errada") is None
    print(f"OK: senha errada para um usuário real ('{algum_vendedor}') é recusada.")


def main() -> None:
    testar_hash_senha()
    testar_credencial_admin_em_copia_temporaria(CAMINHO_XLSX.parent / "_smoke_test_admin_senha.json")
    testar_sessao_e_guard_de_escrita()
    testar_leitura_sheets_bate_com_local()
    testar_login_vendedor_recusa_casos_invalidos()
    linha("TUDO OK")


if __name__ == "__main__":
    main()
