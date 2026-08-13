---
name: todoist
description: Integração com a API Todoist v1 e Sync para consultar e modificar tarefas, projetos, seções, etiquetas, comentários, lembretes, arquivos, atividades, backups e demais recursos documentados. Usa perfis INI e obtém tokens exclusivamente através de um provedor KeePassVault configurado, sem expor segredos ao contexto, argumentos ou logs.
---

# Todoist

Use `scripts/todoist.py` como interface JSON segura para a API Todoist.

## Execução

Sempre informe explicitamente `--config` com o perfil desejado. Envie uma requisição JSON com `version: 1` pelo stdin.

- Para operações REST, use `operation` pertencente ao registro documentado em `references/api-contracts.md`.
- Para operações Sync, use `operation: "sync"`, `commands` e, quando necessário, `sync_token`.
- Nunca coloque tokens, senhas ou respostas secretas em prompts, argumentos, arquivos temporários ou logs.
- Use `body` para JSON, `query` para parâmetros de consulta e `params` para identificadores de caminho.
- Confirme operações destrutivas antes de executá-las.

## Perfis

Os perfis ficam em `configs/`, são ignorados pelo Git e devem ser nomeados `todoist.ini` ou `todoist_<perfil>.ini`. Consulte `configs/todoist.example.ini` para o formato.

O perfil aponta para o comando da skill KeePassVault. O token é transferido somente pelo pipe entre processos, lido em memória e nunca reproduzido na saída.

## Limitações de autenticação

A implementação inicial usa token pessoal. OAuth, refresh tokens e ativação de webhooks exigem um fluxo de aplicação OAuth e não fazem parte deste contrato.

Consulte `references/api-contracts.md` quando precisar escolher uma operação, seus parâmetros ou seus efeitos.
