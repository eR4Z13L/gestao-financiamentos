# Gestão de Financiamentos

Aplicativo desktop (Windows) para controlar propostas de financiamento de
equipamentos junto a bancos/financeiras parceiros — cadastro de clientes,
lançamento e acompanhamento de propostas (Em Análise, Aprovado, Negado,
Pré-aprovado, Nota Fiscal Anexada, Garantia Assinada), e um dashboard com
taxas de aprovação e desempenho por vendedor.

## Stack

- **Python 3 + [PySide6](https://doc.qt.io/qtforpython-6/)** — interface desktop nativa
- **[openpyxl](https://openpyxl.readthedocs.io/)** — o banco de dados do ADMIN é um arquivo `.xlsx` local (4 abas: `CLIENTES`, `EQUIPAMENTOS`, `PROPOSTAS`, `VENDEDORES`), que também pode ser aberto direto no Excel
- **pandas** — cálculos do dashboard e filtros
- **[gspread](https://docs.gspread.org/) + google-auth** — sincronização automática (background, best-effort) do `.xlsx` local para uma planilha no Google Sheets, e leitura (só-leitura) de lá quando quem loga é um VENDEDOR

### Login com dois níveis de acesso

- **Administrador**: acesso total, 100% local (não depende de internet). A senha fica só no computador do admin (`credentials/admin_senha.json`, nunca sincroniza).
- **Vendedor**: só-leitura, vendo somente os próprios clientes/propostas/desempenho. Pode logar de qualquer computador com internet — os dados (e a própria senha, com hash) vêm do Google Sheets, nunca do `.xlsx` local. Por decisão de produto, o vendedor nunca escreve em nada (nem na própria senha); pra trocar, pede pro admin (`core.vendedores.redefinir_senha`).
- O bloqueio de escrita do VENDEDOR é reforçado na camada de regras de negócio (`core.sessao.exigir_admin()`), não só escondendo botão na tela.

⚠️ **Antes de distribuir o `.exe` pra máquina de um vendedor de verdade**, troque a credencial usada em `core/data_store_sheets.py` (hoje reaproveita a mesma do admin, só pra testar de ponta a ponta) por uma conta de serviço do Google Cloud com escopo **só de leitura** na planilha — assim, mesmo que o arquivo de credencial vaze, não dá pra escrever na planilha compartilhada por fora do app.

## Estrutura do projeto

```
core/       # leitura/escrita do .xlsx + regras de negócio (sem nada de interface)
desktop/    # interface PySide6 (janela principal, telas, diálogos, tema)
scripts/    # testes automatizados e utilitários (gerar planilha de exemplo, etc.)
exemplo/    # planilha de exemplo com dados fictícios (estrutura de referência)
data/       # onde o .xlsx REAL fica (não versionado - ver abaixo)
```

## Como rodar localmente

1. Clone o repositório e entre na pasta:
   ```bash
   git clone <url-do-repositorio>
   cd gestao-financiamentos
   ```

2. Crie o ambiente virtual e instale as dependências:
   ```bash
   python -m venv venv
   venv\Scripts\pip install -r requirements.txt
   ```

3. **Coloque sua planilha de dados em `data/controle_financiamentos.xlsx`.**
   Esse arquivo **não vem no repositório** (contém dados reais de clientes:
   CPF, telefone, endereço, valores — está no `.gitignore` de propósito).
   Use `exemplo/controle_financiamentos_exemplo.xlsx` como referência da
   estrutura esperada (mesmas abas, mesmas colunas) se for começar do
   zero, ou copie sua planilha real com esse nome para dentro de `data/` — se
   ela ainda não tiver a aba `VENDEDORES`, o app cria e popula essa aba
   sozinho na primeira leitura.

   **Estrutura da aba `CLIENTES`** (21 colunas): `DATA CADASTRO`, `CPF/CNPJ`,
   `VENDEDOR`, `TIPO`, `CLIENTE` (A–E, não mudam de lugar: as fórmulas de
   `PROPOSTAS` fazem `VLOOKUP` nelas), `NASCIMENTO`, `CELULAR`, `CEP`,
   `LOGRADOURO`, `NÚMERO`, `COMPLEMENTO`, `BAIRRO`, `CIDADE`, `UF`,
   `ENDEREÇO (REVISAR)`, `VINCULADO`, `REDE SOCIAL`, `EMAIL`, `NOME DO PAI`,
   `NOME DA MÃE`, `PROFISSÃO`.

   **Planilha em formato antigo** (uma única coluna `ENDEREÇO`, ou o endereço
   já separado mas sem `COMPLEMENTO`/`UF`): o app recusa abrir, com uma
   mensagem clara, em vez de ler colunas trocadas. Migre com o script abaixo
   — por padrão ele só **simula** (mostra o que faria e os endereços que não
   conseguiu separar com segurança, sem gravar nada); com `--aplicar` ele faz
   um backup conferido do arquivo, grava num arquivo temporário, verifica que
   nada mais mudou e só então troca o original:
   ```bash
   venv\Scripts\python.exe scripts\migrar_endereco_clientes.py
   venv\Scripts\python.exe scripts\migrar_endereco_clientes.py --aplicar
   ```
   Endereço que não segue um padrão claro **não é adivinhado**: o texto
   original inteiro vai pra coluna `ENDEREÇO (REVISAR)` (aparece na ficha e no
   diálogo de edição do cliente); preencha `CEP`/`LOGRADOURO`/… e apague esse
   texto quando terminar de revisar. Essa coluna existe só como apoio da
   migração: pode ser removida (junto do código que a usa) depois que os
   dados definitivos estiverem carregados.

4. **Configure a sincronização com o Google Sheets** (necessária mesmo pro ADMIN sozinho, já que a leitura de VENDEDOR depende dela):
   - Crie um projeto no [Google Cloud Console](https://console.cloud.google.com/), ative a API do Google Sheets (e a do Drive)
   - Crie uma Conta de Serviço, gere uma chave JSON e salve em `credentials/service_account_admin.json` (pasta já no `.gitignore`)
   - Crie uma planilha no Google Sheets e compartilhe com o e-mail da conta de serviço (campo `client_email` do JSON) como **Editor**
   - Anote o ID da planilha (o trecho da URL entre `/d/` e `/edit`) em `GOOGLE_SHEETS_ID`, no `config.py`

5. Rode o app:
   ```bash
   venv\Scripts\python.exe -m desktop.main
   ```
   Ou, no Windows, dê duplo clique em `Abrir Gestao de Financiamentos.bat`.

   Na primeira execução, a tela de login pede pra você definir a senha do
   Administrador (fica salva em `credentials/admin_senha.json`, local).
   Pra cadastrar vendedores com acesso próprio, use o botão "+ Novo Vendedor"
   (cadastro de cliente) ou "+ Novo Vendedor" na ficha — uma senha inicial é
   gerada e mostrada na hora (anote, não dá pra recuperar depois).

## Testes

Os testes rodam contra cópias temporárias dos dados (nunca contra
`data/controle_financiamentos.xlsx`):

```bash
venv\Scripts\python.exe scripts\smoke_test_data_store.py
venv\Scripts\python.exe scripts\smoke_test_business.py
venv\Scripts\python.exe scripts\smoke_test_desktop.py
venv\Scripts\python.exe scripts\smoke_test_dialogs.py
venv\Scripts\python.exe scripts\smoke_test_formatters.py
venv\Scripts\python.exe scripts\smoke_test_propostas_screen.py
venv\Scripts\python.exe scripts\smoke_test_proposta_leitura.py
venv\Scripts\python.exe scripts\smoke_test_vendedores.py
venv\Scripts\python.exe scripts\smoke_test_usuarios_screen.py
venv\Scripts\python.exe scripts\smoke_test_migracao_endereco.py
venv\Scripts\python.exe scripts\smoke_test_ficha_cliente.py
venv\Scripts\python.exe scripts\smoke_test_fase2.py
```

`smoke_test_fase2.py` é o único que fala com o Google Sheets de verdade — e
mesmo assim só faz leitura (nunca escreve lá). Os outros desligam a
sincronização (`config.SINCRONIZACAO_GOOGLE_ATIVADA = False`) pra nunca
mandar dado de teste pra planilha real.

## Gerar o .exe

Executável único (`--onefile`), sem console, com ícone próprio. A receita
fica versionada em `GestaoFinanciamentos.spec` — pra reconstruir depois de
mudar o código, basta:

```bash
venv\Scripts\pyinstaller GestaoFinanciamentos.spec --noconfirm
```

(A primeira vez que o `.spec` foi gerado usou `pyinstaller --name
GestaoFinanciamentos --onefile --windowed --icon desktop/assets/icone_app.ico
--paths . desktop/main.py` — se precisar recriar o `.spec` do zero, é esse o
comando.)

O `.exe` sai em `dist/GestaoFinanciamentos.exe` (~100 MB, já inclui Python,
Qt, pandas e tudo mais — não precisa de Python instalado na máquina de
destino). Ele **não** embute nenhum dado: continua lendo/escrevendo
`data/controle_financiamentos.xlsx` numa pasta `data/` ao lado de onde o
`.exe` estiver, exatamente como a versão rodando com `python`. Pra distribuir
o app, copie `dist/GestaoFinanciamentos.exe` + a pasta `data/` (com a
planilha real) juntos para o destino final.

O primeiro lançamento de uma sessão do Windows costuma demorar alguns
segundos a mais (o `--onefile` extrai tudo pra uma pasta temporária antes de
abrir); execuções seguintes ficam mais rápidas.

O ícone (`desktop/assets/icone_app.ico`) é provisório - gerado por
`scripts/gerar_icone.py` (precisa do Pillow: `venv\Scripts\pip install
pillow`, só pra essa ferramenta de build). Troque o `.ico` por um definitivo
quando tiver um, sem precisar mudar nada no `.spec`.
