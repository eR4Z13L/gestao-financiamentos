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

# Arquivo .xlsx que funciona como banco de dados local.
# Pode ser aberto no Excel a qualquer momento para conferencia manual.
CAMINHO_XLSX = DIRETORIO_DADOS / "controle_financiamentos.xlsx"

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

# Liga/desliga a sincronizacao - usado pelos smoke tests pra nunca mandar
# dado de teste pra planilha real na nuvem (veja scripts/smoke_test_*.py).
SINCRONIZACAO_GOOGLE_ATIVADA = True
