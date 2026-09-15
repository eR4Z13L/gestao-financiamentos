# Gestão de Financiamentos

Aplicativo desktop (Windows) para controlar propostas de financiamento de
equipamentos junto a bancos/financeiras parceiros — cadastro de clientes,
lançamento e acompanhamento de propostas (Em Análise, Aprovado, Negado,
Pré-aprovado, Nota Fiscal Anexada, Garantia Assinada), e um dashboard com
taxas de aprovação e desempenho por vendedor.

## Stack

- **Python 3 + [PySide6](https://doc.qt.io/qtforpython-6/)** — interface desktop nativa
- **[openpyxl](https://openpyxl.readthedocs.io/)** — o banco de dados é um arquivo `.xlsx` local (3 abas: `CLIENTES`, `EQUIPAMENTOS`, `PROPOSTAS`), que também pode ser aberto direto no Excel
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
   estrutura esperada (mesmas 3 abas, mesmas colunas) se for começar do
   zero, ou copie sua planilha real com esse nome para dentro de `data/`.

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
```

## Empacotar como .exe (opcional)

A estrutura já está pronta para isso (o caminho do `.xlsx` é resolvido
corretamente tanto rodando com `python` quanto já empacotado):

```bash
venv\Scripts\pyinstaller --name "GestaoFinanciamentos" --windowed desktop/main.py
```

Depois de gerar, copie a pasta `data/` (com sua planilha real) para dentro
de `dist/GestaoFinanciamentos/` — ela não fica embutida no `.exe`.
