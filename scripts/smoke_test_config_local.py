"""Testa a escolha da config local (config.py): GESTAO_CONFIG_LOCAL escolhe outro arquivo de perfil, um
perfil pedido que nao existe para com erro claro (nunca cai calado na config REAL), um erro DENTRO do
perfil aparece como ele e, GESTAO_IGNORAR_CONFIG_LOCAL continua mandando, e NOME_DO_COMPUTADOR muda o
nome com que o app aparece na nuvem. Cada caso roda num processo Python novo (a config e lida ao
importar); os perfis sao arquivos temporarios - nada le ou grava dado real.

Rodar com: venv/Scripts/python.exe scripts/smoke_test_config_local.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PY = sys.executable
CONSULTA = (
    "import config; from core import sheets_sync; "
    "print(config.CAMINHO_XLSX.name); print(sheets_sync.nome_desta_maquina()); print(hasattr(config, '_PRIVADO'))"
)


def linha(titulo: str) -> None:
    print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")


def rodar(pasta_perfis: Path, **variaveis: str) -> subprocess.CompletedProcess:
    ambiente = {k: v for k, v in os.environ.items() if k not in ("GESTAO_CONFIG_LOCAL", "GESTAO_IGNORAR_CONFIG_LOCAL")}
    ambiente.update(variaveis)
    ambiente["PYTHONPATH"] = str(pasta_perfis)
    ambiente["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run([PY, "-c", CONSULTA], cwd=RAIZ, env=ambiente, capture_output=True, text=True,
                          encoding="utf-8", timeout=60)


def main() -> None:
    pasta = Path(tempfile.mkdtemp(prefix="_smoke_config_local_"))
    try:
        (pasta / "perfil_de_teste_x.py").write_text(
            "from pathlib import Path\n"
            "CAMINHO_XLSX = Path('perfil_x.dat')\n"
            "NOME_DO_COMPUTADOR = 'PC-DO-PERFIL-X'\n"
            "_PRIVADO = 1\n",
            encoding="utf-8",
        )
        (pasta / "perfil_com_erro.py").write_text("import modulo_que_nao_existe_de_jeito_nenhum\n", encoding="utf-8")

        linha("1) GESTAO_CONFIG_LOCAL escolhe o perfil (e so os nomes publicos entram)")
        r = rodar(pasta, GESTAO_CONFIG_LOCAL="perfil_de_teste_x")
        assert r.returncode == 0, r.stderr
        caminho, nome, privado = r.stdout.split()
        assert (caminho, nome, privado) == ("perfil_x.dat", "PC-DO-PERFIL-X", "False"), r.stdout
        print("OK: o perfil pedido vale (planilha e nome na nuvem dele); nome com _ nao vaza pra config.")

        linha("2) Perfil pedido que nao existe: erro claro, nunca a config real calada")
        r = rodar(pasta, GESTAO_CONFIG_LOCAL="perfil_que_nao_existe")
        assert r.returncode != 0 and "perfil_que_nao_existe.py não foi encontrado" in r.stderr, r.stderr
        print("OK: sem o arquivo do perfil, o app para dizendo qual arquivo falta.")

        linha("3) Erro DENTRO do perfil aparece como ele e (nao como 'arquivo nao encontrado')")
        r = rodar(pasta, GESTAO_CONFIG_LOCAL="perfil_com_erro")
        assert r.returncode != 0 and "modulo_que_nao_existe_de_jeito_nenhum" in r.stderr and "não foi encontrado" not in r.stderr, r.stderr
        print("OK: o erro de verdade (o import quebrado dentro do perfil) e o que aparece.")

        linha("4) GESTAO_IGNORAR_CONFIG_LOCAL continua mandando (os testes que usam a planilha real)")
        r = rodar(pasta, GESTAO_CONFIG_LOCAL="perfil_de_teste_x", GESTAO_IGNORAR_CONFIG_LOCAL="1")
        assert r.returncode == 0, r.stderr
        caminho, nome, _ = r.stdout.split(maxsplit=2)
        assert caminho == "controle_financiamentos.dat" and nome != "PC-DO-PERFIL-X", r.stdout
        print("OK: com IGNORAR ligado, vale a config real mesmo com um perfil pedido.")

        linha("TUDO OK")
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


if __name__ == "__main__":
    main()
