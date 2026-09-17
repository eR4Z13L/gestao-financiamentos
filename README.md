# Gestão de Financiamentos

Aplicativo desktop (Windows) para controlar propostas de financiamento de
equipamentos junto a bancos/financeiras parceiros — cadastro de clientes,
lançamento e acompanhamento de propostas (Em Análise, Aprovado, Negado,
Pré-aprovado, Nota Fiscal Anexada, Garantia Assinada), e um dashboard com
taxas de aprovação e desempenho por vendedor.

## Stack

- **Python 3 + [PySide6](https://doc.qt.io/qtforpython-6/)** — interface desktop nativa
- **[openpyxl](https://openpyxl.readthedocs.io/)** — o banco de dados é um arquivo `.xlsx` local (4 abas: `CLIENTES`, `EQUIPAMENTOS`, `PROPOSTAS`, `VENDEDORES`), que também pode ser aberto direto no Excel
- **pandas** — cálculos do dashboard e filtros

Sincronização com Google Sheets está planejada, mas ainda não implementada.

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

4. Rode o app:
   ```bash
   venv\Scripts\python.exe -m desktop.main
   ```
   Ou, no Windows, dê duplo clique em `Abrir Gestao de Financiamentos.bat`.

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
venv\Scripts\python.exe scripts\smoke_test_vendedores.py
```

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
