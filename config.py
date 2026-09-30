import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # Rodando como .exe empacotado (PyInstaller): usa a pasta onde o
    # executavel esta, nunca a pasta temporaria de extracao (sys._MEIPASS) -
    # senao o app perderia/recriaria a planilha a cada execucao.
    DIRETORIO_BASE = Path(sys.executable).resolve().parent
else:
    DIRETORIO_BASE = Path(__file__).resolve().parent

DIRETORIO_DADOS = DIRETORIO_BASE / "data"

# Versao mostrada no rodape da barra lateral - o unico lugar a mudar a cada versao nova.
VERSAO_APP = "1.0.0"

# Arquivo que funciona como banco de dados local - por dentro e um .xlsx de
# verdade, mas o nome termina em .dat de proposito: um clique duplo no
# Explorer nao abre mais sozinho no Excel mostrando todos os dados - so quem
# sabe (Abrir com... > Excel) consegue. O openpyxl grava normalmente nesse
# caminho (wb.save() nao liga pra extensao), mas recusaria LER um caminho
# .dat direto - core.data_store contorna isso abrindo o arquivo e passando o
# handle (a checagem de extensao so roda pra string/Path). O nome da
# variavel ficou historico (CAMINHO_XLSX), mesmo a extensao real sendo .dat.
CAMINHO_XLSX = DIRETORIO_DADOS / "controle_financiamentos.dat"

# Bancos/financeiras parceiros conhecidos (apenas para preencher a lista de
# sugestoes no formulario de proposta - o campo continua sendo texto livre).
BANCOS_CONHECIDOS = [
    "Santander",
    "Portobank",
    "Hubcred BV",
    "Smart",
    "Medicalsan",
    "Gloriabank",
    "Mova HTM",
    "Todos",
]

# Sincronizacao com Google Sheets (login com dois niveis de acesso - Fase 1).
# So o ADMIN escreve (a partir do .xlsx local, apos cada escrita bem
# sucedida); a credencial e a chave da conta de servico do Google Cloud, que
# fica FORA do repositorio (pasta credentials/, no .gitignore).
CAMINHO_CREDENCIAIS_GOOGLE = DIRETORIO_BASE / "credentials" / "service_account_admin.json"
GOOGLE_SHEETS_ID = "1-Iedzv3gw0QcurzpoFIzri4J68-OGjfsKihcqes0ACc"

# Senha do ADMIN (login com dois niveis de acesso - Fase 2) - fica 100%
# local, nunca sincroniza pro Google Sheets (ao contrario da senha dos
# vendedores, que precisa estar la pra logar de outro computador).
CAMINHO_CREDENCIAIS_ADMIN = DIRETORIO_BASE / "credentials" / "admin_senha.json"

# Liga/desliga a sincronizacao - usado pelos smoke tests pra nunca mandar
# dado de teste pra planilha real na nuvem (veja scripts/smoke_test_*.py).
SINCRONIZACAO_GOOGLE_ATIVADA = True

# Config local opcional de DESENVOLVIMENTO/TESTE - nunca commitada (.gitignore).
# Se config_local.py existir, ele roda AGORA e redefine so as variaveis que quiser
# (normalmente CAMINHO_XLSX/DIRETORIO_DADOS, GOOGLE_SHEETS_ID e
# CAMINHO_CREDENCIAIS_GOOGLE) - assim da pra testar/desenvolver numa planilha e
# num Google Sheets separados, sem risco de mexer nos dados reais por engano.
# Sem esse arquivo, nada muda (usa sempre a config real de cima). Copie
# config_local.exemplo.py pra config_local.py e ajuste os caminhos/IDs.
# GESTAO_IGNORAR_CONFIG_LOCAL=1 (variavel de ambiente) pula o arquivo: e o que os poucos testes
# que usam uma COPIA da planilha real como base ligam, pra nao pegarem a de teste por engano.
# GESTAO_CONFIG_LOCAL=<modulo> escolhe OUTRO arquivo de config local no lugar de config_local.py
# (ex.: config_local_oficial, pra desenvolver contra o Google Sheets oficial) - pedido de proposito,
# entao se esse arquivo nao existir o app para com erro em vez de cair na config real calado.
# Opcional nesse arquivo: NOME_DO_COMPUTADOR, o nome com que este app se identifica na nuvem.
if not os.environ.get("GESTAO_IGNORAR_CONFIG_LOCAL"):
    _perfil_local = os.environ.get("GESTAO_CONFIG_LOCAL", "").strip()
    try:
        _modulo_local = __import__(_perfil_local or "config_local")
    except ImportError as _erro:
        if _perfil_local:
            if getattr(_erro, "name", None) == _perfil_local:
                raise ImportError(
                    f"GESTAO_CONFIG_LOCAL={_perfil_local}, mas o arquivo {_perfil_local}.py não foi encontrado."
                ) from None
            raise  # o arquivo existe mas tem um erro dentro: mostra o erro de verdade
    else:
        # o mesmo que "from config_local import *": so os nomes publicos do arquivo
        globals().update({nome: valor for nome, valor in vars(_modulo_local).items() if not nome.startswith("_")})
