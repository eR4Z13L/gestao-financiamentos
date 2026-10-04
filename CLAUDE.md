## Regras de trabalho (valem para toda conversa neste projeto)

O app guarda dados de clientes e financiamentos de uma empresa, e o repositório no GitHub é PÚBLICO. Estas regras
foram definidas pelo usuário e valem sempre.

**Antes e durante uma mudança**
- Mudança estrutural: explicar em poucas linhas o que vai mudar antes de fazer; depois, pausar para o usuário testar no app.
- Ideia ou sugestão que o usuário ainda não aprovou fica só na conversa, sem código. Se ele disse "não altere nada", só ler e recomendar.
- Responder em português, dar notícias curtas enquanto trabalha e avisar antes de algo demorado (suíte de testes, build).
- Quando o usuário confirmar uma tarefa ou decisão nova, registrar no painel de tarefas (`docs/tarefas.js`, local, fora do git).

**Git**
- Commit e push SÓ quando o usuário pedir com todas as letras ("pode commitar", "envia pro GitHub"). "Commitar" não autoriza push.
- Nunca reconstruir o .exe nem o instalador sem pedido.
- Nunca entram no git: `data/` (planilha real e backups), `data_dev_oficial/`, `credentials/`, `config_local*.py`, `docs/`.
- Antes de cada commit: conferir, nos arquivos que vão entrar, que não há nome, CPF/CNPJ, telefone, e-mail ou endereço lidos da planilha real (comparar linha a linha) nem segredo (chave privada, conta de serviço do Google, segredo do login Google — os arquivos de `credentials/`). Em testes, exemplos e mensagens de commit, só dados claramente fictícios.

**Dados**
- Nenhum teste toca a planilha real nem a planilha oficial do Google. O `Abrir Gestao de Financiamentos.bat` abre o app na planilha de teste (`config_local.py` → `data_teste/`); o perfil "dev com Sheets oficial" é só do usuário.
- Backup conferido antes de qualquer migração; script de migração simula por padrão e só grava com `--aplicar`.
- Nunca chutar dado ambíguo: o caso duvidoso vai para o usuário decidir. Nunca "consertar" nem restaurar a planilha real por conta própria.

**Código**
- `core/` = dados e regras de negócio (sem interface); `desktop/` = interface. Nomes em português. Comentário só para lógica não óbvia.
- Erros sempre explícitos (mensagem ao usuário ou exceção com texto); nunca falhar em silêncio.

**Testes**
- Rodar `venv\Scripts\python.exe scripts\smoke_test_<nome>.py` com `QT_QPA_FONTDIR=C:\Windows\Fonts` e `PYTHONIOENCODING=utf-8`, e procurar `Traceback` na saída inteira (um erro dentro de um sinal do Qt só é impresso; o processo sai com código 0).
- Os testes usam planilha fictícia em pasta temporária (`scripts/fixture_ficticia.py`), isolam as preferências do Windows (`isolar_preferencias`) e bloqueiam o acesso ao Google.
- Depois da suíte, conferir que o hash de `data/controle_financiamentos.dat`, a listagem de `data/` e `credentials/` não mudaram. Se mudou com o app do usuário aberto, pode ter sido ele: investigar e perguntar, nunca restaurar.
- Lógica nova se prova com mutação: estragar o código de propósito, ver o teste falhar, restaurar e conferir que o arquivo voltou idêntico. Enquanto uma mutação roda, um arquivo do projeto fica alterado por instantes.
- Nunca encerrar todos os processos python (o app do usuário pode estar aberto).

## Uso de subagentes

Use subagentes de forma estratégica neste projeto — quando isso economiza tokens da conversa principal, não como padrão para toda tarefa.

QUANDO USAR SUBAGENTES:
1. Buscas ou explorações grandes no código (ex: "onde está toda a lógica que trata Status?", "quais arquivos mexem no .xlsx?") — delegue para um subagente de busca em vez de vasculhar arquivo por arquivo consumindo o próprio contexto
2. Tarefas que podem rodar em paralelo e são independentes entre si (ex: revisar 3 telas diferentes procurando o mesmo tipo de bug) — disparar vários subagentes ao mesmo tempo, um por tarefa
3. Verificação independente de um trabalho recém-feito (ex: revisar se uma refatoração grande não quebrou nada), quando o usuário pedir uma segunda opinião que não deve "compartilhar" o raciocínio do trabalho original

QUANDO NÃO USAR SUBAGENTES:
1. Tarefas pequenas e diretas (corrigir um bug pontual, ajustar um estilo, mudar um texto) — fazer direto
2. Quando a tarefa depende do contexto da conversa atual e não compensaria reexplicar tudo para um subagente do zero
3. Não criar subagentes "só para ajudar" sem uma tarefa clara e delimitada

ECONOMIA DE TOKENS AO USAR SUBAGENTES:
1. Ao instruir um subagente, ser específico sobre o que ele deve devolver — pedir um resumo objetivo (ex: "liste os arquivos e linhas, não devolva o conteúdo inteiro")
2. Preferir o subagente de exploração mais leve disponível para buscas simples de arquivo/código, reservando o mais robusto só para tarefas que exigem julgamento
3. Antes de disparar um subagente, confirmar que a tarefa realmente precisa de investigação separada
