# Gestão de Financiamentos — mapa

App de dados de clientes e financiamentos de uma empresa; repositório GitHub PÚBLICO. Responder em português, notícias curtas durante o trabalho; avisar antes de algo demorado (suíte, build). Chamar o usuário de Raziel (nunca "sócio"). Toda resposta ao Raziel começa com resumo de 3 linhas.

## Regras fixas
- Mudança estrutural: explicar em poucas linhas antes; depois pausar para o Raziel testar. Ideia não aprovada fica só na conversa; "não altere nada" = só ler e recomendar.
- Ao confirmar tarefa/decisão nova: registrar em `docs/tarefas.js` (local, fora do git).
- Git: commit e push ao GitHub autorizados de forma permanente pelo Raziel (19/10; push automático reafirmado em 31/10 para todos os projetos), sempre DEPOIS da varredura de privacidade (Vera = LIMPO, linha a linha); a suíte do Tito NÃO é mais obrigatória para o push (Raziel, 31/10); um commit por etapa ou bloco, mensagem só com dados fictícios. Chat na nuvem envia só o PRÓPRIO ramo `claude/...`, nunca `master`. Continua proibido reconstruir .exe/instalador sem pedido.
- Nunca reconstruir .exe/instalador sem pedido. Nunca vão ao git: `data/`, `data_dev_oficial/`, `credentials/`, `config_local*.py`, `docs/`. Nunca ler esses diretórios sem necessidade.
- Antes de commit: varrer linha a linha atrás de nome, CPF/CNPJ, telefone, e-mail, endereço da planilha real e de segredos; testes, exemplos e mensagens só com dados fictícios.
- Dados: nenhum teste toca a planilha real nem o Sheets oficial (app abre na planilha de teste `data_teste/`). Backup conferido antes de migrar; migração simula e só grava com `--aplicar`. Nunca chutar dado ambíguo nem "consertar"/restaurar a planilha real sozinho.
- Código: `core/` regras sem interface; `desktop/` interface; nomes em português; erros sempre explícitos.
- Nunca encerrar todos os pythons. Sem referência extremista ("Hail" etc.). Não repetir senhas/tokens.
- Sobe ao Raziel: plano novo/mudança de escopo, apagar, publicar, config do Claude Code, gastar/instalar, dados reais.
- Contexto > ~150 mil tokens: passagem de bastão. Recado a outra conversa: 1ª linha `[urgente]`.

## Onde está o detalhe
- Testes, subagentes, equipe (Pedro/Tito/Rita/Vera/ajudante), grafo, recados: `regras-detalhe.md`.
- Índice de notas: `MEMORY.md`. Plano vigente: `docs/planos/fechamento.md` + nota `projeto-plano-de-fechamento`.
- Painel de tarefas: `docs/tarefas.js` (ler antes de editar).
