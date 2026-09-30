"""Modelo de config local pra DESENVOLVIMENTO/TESTE - copie este arquivo pra
"config_local.py" (esse nome exato) e preencha com a sua planilha e o seu
Sheets de teste. "config_local.py" nunca é commitado (.gitignore) - cada
pessoa que desenvolve tem o seu, com os próprios dados fictícios.

Defina só o que quiser sobrescrever - o que não estiver aqui continua vindo
de config.py normalmente (a config REAL). Pra rodar 100% isolado dos dados
reais, normalmente isso quer dizer os três abaixo.

Outros perfis: um arquivo "config_local_<nome>.py" (também fora do git) é usado
no lugar deste quando o app abre com a variável de ambiente
GESTAO_CONFIG_LOCAL=config_local_<nome> (num .bat: "set GESTAO_CONFIG_LOCAL=...").
Ex.: um perfil que desenvolve contra o Google Sheets OFICIAL, com a própria
pasta de dados - nele, tudo o que for gravado vai para a planilha real. Se o
perfil pedido não existir, o app para com erro (nunca cai calado na config real).

NOME_DO_COMPUTADOR (opcional): o nome com que este app aparece na nuvem ("outro
computador ativo", último a gravar). Use um nome diferente do app instalado no
mesmo computador (ex.: "MEU-PC (dev)") para um enxergar o outro.
"""

from pathlib import Path

_AQUI = Path(__file__).resolve().parent

# Planilha de teste (dados fictícios) - fica numa pasta separada da "data/" real,
# pra nunca confundir as duas. Gere uma planilha fictícia com:
#   venv\Scripts\python.exe -c "import sys; sys.path.insert(0, 'scripts'); import fixture_ficticia as fx; from pathlib import Path; print(fx.criar_volumoso(Path('data_teste')))"
DIRETORIO_DADOS = _AQUI / "data_teste"
CAMINHO_XLSX = DIRETORIO_DADOS / "controle_financiamentos_teste.dat"

# Planilha de TESTE no Google Sheets (NUNCA a real) + a conta de serviço dela.
# Veja o passo a passo no README ("Configure a sincronização com o Google Sheets")
# - repita os mesmos passos, só que criando uma planilha e uma conta de serviço
# novas, exclusivas pra teste.
GOOGLE_SHEETS_ID = "COLE_AQUI_O_ID_DA_PLANILHA_DE_TESTE"
CAMINHO_CREDENCIAIS_GOOGLE = _AQUI / "credentials_teste" / "service_account_teste.json"

# Senha do Administrador separada da real, pra nunca compartilhar arquivo com
# credentials/ de produção.
CAMINHO_CREDENCIAIS_ADMIN = _AQUI / "credentials_teste" / "admin_senha_teste.json"
