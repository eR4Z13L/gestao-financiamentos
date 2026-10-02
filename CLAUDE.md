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
