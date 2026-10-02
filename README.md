# Gestão de Financiamentos

Aplicativo desktop (Windows) para controlar propostas de financiamento de
equipamentos junto a bancos/financeiras parceiros — cadastro de clientes,
lançamento e acompanhamento de propostas (Em Análise, Aprovado, Negado,
Pré-aprovado, Nota Fiscal Anexada, Garantia Assinada), e um dashboard com
taxas de aprovação e desempenho por vendedor.

## Stack

- **Python 3 + [PySide6](https://doc.qt.io/qtforpython-6/)** — interface desktop nativa
- **[openpyxl](https://openpyxl.readthedocs.io/)** — o banco de dados do ADMIN é um arquivo `.xlsx` de verdade por dentro (4 abas: `CLIENTES`, `EQUIPAMENTOS`, `PROPOSTAS`, `VENDEDORES`), só que salvo com a extensão `.dat` (`data/controle_financiamentos.dat`) de propósito — um clique duplo não abre mais sozinho no Excel; pra conferir manualmente, "Abrir com..." e escolher o Excel continua funcionando normalmente
- **pandas** — cálculos do dashboard e filtros
- **[gspread](https://docs.gspread.org/) + google-auth + google-auth-oauthlib** — login com a conta Google e sincronização automática (background, best-effort) do `.xlsx` local para uma planilha no Google Sheets, e leitura (só-leitura) de lá quando quem loga é um VENDEDOR

### Login com dois níveis de acesso

- **Administrador**: acesso total. Entra com a **conta Google** (a primeira vez em cada computador, pelo navegador) e cria um **PIN de 6 números** daquele computador; nas próximas vezes, só o PIN, sem internet (`core/acesso.py`). A conta precisa ter acesso de Editor à planilha do Google Sheets — o app confere na hora. "Esqueci o PIN" = entrar com Google de novo; 5 erros seguidos apagam o PIN. A autorização do Google (`credentials/conta_google.dat`) e o PIN (`credentials/acesso_pin.dat`) ficam só naquele computador, criptografados pelo Windows (DPAPI). Quem ainda tinha a senha antiga do Administrador (`credentials/admin_senha.json`) entra com ela uma última vez e cria o PIN, que aposenta a senha.
- **Vendedor**: só-leitura, vendo somente os próprios clientes/propostas/desempenho. Pode logar de qualquer computador com internet — os dados (e a própria senha, com hash) vêm do Google Sheets, nunca do `.xlsx` local. Por decisão de produto, o vendedor nunca escreve em nada (nem na própria senha); pra trocar, pede pro admin (`core.vendedores.redefinir_senha`).
- O bloqueio de escrita do VENDEDOR é reforçado na camada de regras de negócio (`core.sessao.exigir_admin()`), não só escondendo botão na tela.

⚠️ **Antes de distribuir o `.exe` pra máquina de um vendedor de verdade**, troque a credencial usada em `core/data_store_sheets.py` (hoje reaproveita a mesma do admin, só pra testar de ponta a ponta) por uma conta de serviço do Google Cloud com escopo **só de leitura** na planilha — assim, mesmo que o arquivo de credencial vaze, não dá pra escrever na planilha compartilhada por fora do app.

## Estrutura do projeto

```
core/       # leitura/escrita do .xlsx + regras de negócio (sem nada de interface)
desktop/    # interface PySide6 (janela principal, telas, diálogos, tema)
scripts/    # testes automatizados e utilitários (gerar planilha de exemplo, etc.)
exemplo/    # planilha de exemplo com dados fictícios (estrutura de referência)
data/       # onde o .dat (.xlsx por dentro) REAL fica (não versionado - ver abaixo)
installer/  # receita do instalador (Inno Setup) - ver "Gerar o instalador" abaixo
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

3. **Coloque sua planilha de dados em `data/controle_financiamentos.dat`.**
   Esse arquivo **não vem no repositório** (contém dados reais de clientes:
   CPF, telefone, endereço, valores — está no `.gitignore` de propósito). É
   um `.xlsx` normal por dentro, só com a extensão trocada (ver "Stack" acima)
   — se você já tem uma planilha `.xlsx` pronta, basta renomear a extensão
   dela para `.dat` e copiar para dentro de `data/`. Use
   `exemplo/controle_financiamentos_exemplo.xlsx` como referência da
   estrutura esperada (mesmas abas, mesmas colunas) se for começar do
   zero — se ela ainda não tiver a aba `VENDEDORES`, o app cria e popula essa
   aba sozinho na primeira leitura.

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

   **Status de proposta e a coluna `TEMPO`:** o fluxo é Em Análise →
   Pré-aprovado → Aprovado → Nota Fiscal Anexada → Garantia Assinada →
   **Efetivado** (aprovada *e* compra concluída), ou Negado. `TEMPO` mostra
   "Encerrado" só para Efetivado e Negado/Reprovado/Cancelado — "Aprovado"
   continua contando dias até virar Efetivado. No Dashboard, Efetivado conta
   como aprovado na taxa de aprovação, e o card "Aprovados não efetivados"
   mostra quantas propostas ainda estão em "Aprovado". O app só regrava as
   fórmulas do Excel quando alguém grava uma proposta; numa planilha gravada
   com a regra antiga (Aprovado = Encerrado), atualize a coluna `TEMPO` de uma
   vez — o script simula por padrão e, com `--aplicar`, faz backup e mexe só
   nessa coluna:
   ```bash
   venv\Scripts\python.exe scripts\atualizar_formulas_tempo.py
   venv\Scripts\python.exe scripts\atualizar_formulas_tempo.py --aplicar
   ```

4. **Configure a sincronização com o Google Sheets** (necessária mesmo pro ADMIN sozinho, já que a leitura de VENDEDOR depende dela):
   - Crie um projeto no [Google Cloud Console](https://console.cloud.google.com/), ative a API do Google Sheets (e a do Drive)
   - Crie uma Conta de Serviço, gere uma chave JSON e salve em `credentials/service_account_admin.json` (pasta já no `.gitignore`)
   - Crie uma planilha no Google Sheets e compartilhe com o e-mail da conta de serviço (campo `client_email` do JSON) como **Editor**
   - Anote o ID da planilha (o trecho da URL entre `/d/` e `/edit`) em `GOOGLE_SHEETS_ID`, no `config.py`

   **Usando o app em dois computadores (revezando).** Cada computador tem o próprio arquivo de
   dados, e cada gravação envia a aba inteira para o Google Sheets - então, sem cuidado, quem
   salvou por último apagaria o que o outro lançou. Por isso a nuvem tem uma aba `META` com um
   **número de versão**, e cada computador guarda (em `data/estado_sincronizacao.json`) a versão
   que conhece e quais abas ainda não foram enviadas:
   - **Trava de versão:** antes de enviar, o app confere se a nuvem está na versão que ele
     conhece. Se outro computador gravou no meio, o envio é **recusado** (nada é sobrescrito), o
     indicador da barra lateral fica vermelho ("Conflito com a nuvem - clique") e as
     alterações continuam salvas aqui, marcadas como pendentes.
   - **Ao abrir o app** (como Administrador) ele compara este computador com a nuvem: se a nuvem
     tem dados mais novos, oferece **baixar**; se os dois lados mudaram, pergunta qual vence
     (baixar da nuvem ou manter o que está aqui); se há alterações que ficaram sem enviar (por
     exemplo, sem internet), reenvia sozinho. Sem internet, o app abre normalmente.
   - **Baixar da nuvem** (também em Administração > Sincronização e backup) troca os dados
     deste computador pelos da nuvem, tudo ou nada, com backup do arquivo de antes
     ("Antes de baixar da nuvem"). "Manter o meu" guarda antes uma cópia do que a nuvem tinha
     ("Cópia da nuvem"). Esses backups nunca são apagados sozinhos.
   - **Aviso de outro computador ativo:** com o app aberto, cada computador dá um sinal na nuvem
     a cada minuto. Ao abrir, se outro computador deu sinal nos últimos 5 minutos, o app avisa
     (é só um aviso: o sinal expira sozinho se o outro fechou ou travou). A trava de versão é a
     proteção de verdade, mesmo que você escolha continuar.
   - **Nuvem sem controle ainda:** uma planilha na nuvem sem a aba `META` (de antes desta
     versão) faz o app perguntar qual lado tem os dados certos: **"Baixar da nuvem para este
     computador"** (fica com os dados de lá e liga o controle, sem reenviar nada) ou **"Enviar
     os dados deste computador"** (a nuvem fica com os daqui). Até decidir, nada é enviado (as
     alterações ficam salvas aqui).
   - **Sem planilha neste computador** (instalação nova): antes de abrir a janela, o app
     consulta a nuvem. Se ela tem dados, oferece baixar; se está vazia, não há chave do Google
     ou não há internet, oferece começar com uma planilha vazia (as 4 abas, só com os
     cabeçalhos) - ou fechar, para copiar o arquivo de outro computador. Começar vazio não
     apaga nada na nuvem: a trava de versão impede, e com internet o app oferece baixar.
   - O Google limita a 60 leituras por minuto para a conta de serviço (dividido entre os
     computadores); o uso normal fica bem abaixo disso, e um envio que esbarrar no limite
     é repetido sozinho.

5. Rode o app:
   ```bash
   venv\Scripts\python.exe -m desktop.main
   ```
   Ou, no Windows, dê duplo clique em `Abrir Gestao de Financiamentos.bat`.

   Na primeira execução, a tela de login pede "Entrar com Google" (precisa de
   `credentials/oauth_cliente_google.json`, o cliente OAuth "App para
   computador" do projeto no Google Cloud) e depois um PIN de 6 números.
   Pra cadastrar vendedores com acesso próprio, use o botão "+ Novo Vendedor"
   (cadastro de cliente) ou "+ Novo Vendedor" na ficha — uma senha inicial é
   gerada e mostrada na hora (anote, não dá pra recuperar depois).

## Testes

Os testes rodam contra cópias temporárias dos dados (nunca contra
`data/controle_financiamentos.dat`):

```bash
venv\Scripts\python.exe scripts\smoke_test_data_store.py
venv\Scripts\python.exe scripts\smoke_test_business.py
venv\Scripts\python.exe scripts\smoke_test_desktop.py
venv\Scripts\python.exe scripts\smoke_test_formulario_proposta.py
venv\Scripts\python.exe scripts\smoke_test_formatters.py
venv\Scripts\python.exe scripts\smoke_test_propostas_screen.py
venv\Scripts\python.exe scripts\smoke_test_proposta_leitura.py
venv\Scripts\python.exe scripts\smoke_test_cartao_expansivel.py
venv\Scripts\python.exe scripts\smoke_test_vendedores.py
venv\Scripts\python.exe scripts\smoke_test_usuarios_screen.py
venv\Scripts\python.exe scripts\smoke_test_migracao_endereco.py
venv\Scripts\python.exe scripts\smoke_test_ficha_cliente.py
venv\Scripts\python.exe scripts\smoke_test_ficha_cards.py
venv\Scripts\python.exe scripts\smoke_test_filtros_clientes.py
venv\Scripts\python.exe scripts\smoke_test_status_efetivado.py
venv\Scripts\python.exe scripts\smoke_test_cards_propostas.py
venv\Scripts\python.exe scripts\smoke_test_cards_melhorias.py
venv\Scripts\python.exe scripts\smoke_test_filtros_propostas.py
venv\Scripts\python.exe scripts\smoke_test_barra_lateral_regras.py
venv\Scripts\python.exe scripts\smoke_test_sincronizacao_estado.py
venv\Scripts\python.exe scripts\smoke_test_sincronizacao_versao.py
venv\Scripts\python.exe scripts\smoke_test_sincronizacao_janela.py
venv\Scripts\python.exe scripts\smoke_test_barra_lateral.py
venv\Scripts\python.exe scripts\smoke_test_dashboard_core.py
venv\Scripts\python.exe scripts\smoke_test_dashboard_screen.py
venv\Scripts\python.exe scripts\smoke_test_fase2.py
```

`smoke_test_fase2.py` é o único que fala com o Google Sheets de verdade — e
mesmo assim só faz leitura (nunca escreve lá). Os outros desligam a
sincronização (`config.SINCRONIZACAO_GOOGLE_ATIVADA = False`) pra nunca
mandar dado de teste pra planilha real.

Os testes da barra lateral (`*_barra_lateral*.py` e
`smoke_test_sincronizacao_estado.py`) e do Dashboard (`smoke_test_dashboard_*.py`)
vão além: usam uma planilha 100% fictícia (`scripts/fixture_ficticia.py`,
montada a partir de `exemplo/`; o Dashboard usa a versão volumosa) e mandam as
preferências do app (tema, última tela, tamanho da janela) pra um `.ini`
temporário, então não leem nem gravam nada do registro do Windows — o teste
confere isso no fim. As caixas de mensagem falsas, o isolamento e o bloqueio
da rede ficam em `scripts/ambiente_de_teste.py`. Vale a regra de sempre: depois de rodar os
testes, procure `Traceback` na saída inteira, não só o código de saída (uma
exceção dentro de um slot do Qt só é impressa, e o processo sai com código 0).

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
`data/controle_financiamentos.dat` numa pasta `data/` ao lado de onde o
`.exe` estiver, exatamente como a versão rodando com `python`.

Pra instalar/distribuir em outro PC, copie estas DUAS pastas junto do `.exe`
(sem elas, o app não tem a planilha nem o login Google):

```
GestaoFinanciamentos.exe
data/                       # a planilha real (controle_financiamentos.dat) + backups/
credentials/                # oauth_cliente_google.json (+ service_account_admin.json, enquanto existir)
```

`credentials/` não é mencionado em nenhum lugar do processo de build (o
`.spec` não empacota nada de fora - `datas=[]`) - é sempre uma cópia manual,
igual `data/`. Trate o PC de destino com o mesmo cuidado que o seu: essas
duas pastas são os dados reais e a chave de acesso à nuvem.

O primeiro lançamento de uma sessão do Windows costuma demorar alguns
segundos a mais (o `--onefile` extrai tudo pra uma pasta temporária antes de
abrir); execuções seguintes ficam mais rápidas.

O ícone (`desktop/assets/icone_app.ico`) é provisório - gerado por
`scripts/gerar_icone.py` (precisa do Pillow: `venv\Scripts\pip install
pillow`, só pra essa ferramenta de build). Troque o `.ico` por um definitivo
quando tiver um, sem precisar mudar nada no `.spec`.

## Gerar o instalador

Em vez de mandar o `.exe` + as duas pastas soltos, dá pra gerar um instalador
único (assistente com "Avançar/Concluir", atalho no Menu Iniciar e na Área de
Trabalho, e entrada em "Adicionar ou remover programas"). A receita fica em
`installer/GestaoFinanciamentos.iss`, pro [Inno Setup](https://jrsoftware.org/isinfo.php)
(grátis).

1. Gere o `.exe` normal primeiro (passo acima) - o instalador espera achar
   `dist/GestaoFinanciamentos.exe`.
2. Instale o Inno Setup (só uma vez, na máquina de quem gera o instalador -
   não precisa no PC de destino):
   ```bash
   winget install JRSoftware.InnoSetup
   ```
3. Compile o instalador:
   ```bash
   iscc installer\GestaoFinanciamentos.iss
   ```
   O instalador pronto sai em `installer/saida/GestaoFinanciamentos-Setup.exe`.

**Onde ele instala e por quê**: em `%LocalAppData%\Programs\GestaoFinanciamentos`
(pasta do próprio usuário do Windows), não em `C:\Program Files\`. Program
Files é protegido contra escrita pra quem não é administrador - e este app
grava a planilha na própria pasta onde está instalado a cada proposta salva,
então instalar lá exigiria pedir permissão de administrador toda vez que
abrisse. Instalando na pasta do usuário, ninguém precisa disso.

**O instalador NÃO embute** a planilha real nem as credenciais do Google
dentro do próprio `.exe` de instalação - de propósito, pra essas duas coisas
sensíveis nunca ficarem fixas num arquivo que pode ser copiado ou enviado por
engano. Em vez disso, o assistente **pergunta** (uma tela, logo depois de
escolher a pasta de instalação) por três arquivos, cada um no seu campo com o
próprio "Procurar..." - dá pra juntar os três numa pasta qualquer e escolher
um por um; todos são opcionais, e cada um é conferido pelo conteúdo (para não
trocar um pelo outro):

- a planilha (`.dat` ou `.xlsx`) - vai pra `data/`, já com o nome
  `controle_financiamentos.dat`;
- a senha do Administrador (`admin_senha.json`) - vai pra `credentials/`;
- a chave do Google (`service_account_admin.json`) - vai pra `credentials/`.

O cliente OAuth do login Google (`credentials/oauth_cliente_google.json`, deste
PC) vai embutido no instalador: ele só identifica o app, não dá acesso a nada
sozinho. Campo em branco não é problema: sem planilha, o app oferece baixar da nuvem ou
começar com uma vazia na primeira abertura; sem senha, entra com Google e cria o PIN;
sem a chave, funciona só neste computador. O
`installer/LEIA-ME-primeira-instalacao.txt` (aberto automaticamente no fim)
explica o que ainda falta copiar à mão.

Ao lançar uma versão nova do app, atualize `MyAppVersion` no topo do `.iss`
para o mesmo valor de `config.VERSAO_APP` (são dois lugares porque o Inno
Setup não lê arquivo `.py`).
