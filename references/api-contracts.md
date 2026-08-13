# Contrato da API Todoist

## Envelope

Toda requisição usa `version: 1`, `operation`, `params`, `query` e opcionalmente `body`.

O resultado tem `ok`, `version`, `operation` e `data`; falhas têm `ok: false` e `error.code`/`error.message`.

## Operações

O registro em `scripts/todoist.py` é a lista permitida de operações REST. Ele cobre user, tasks, projects, sections, labels, comments, collaborators, activity, reminders, uploads, backups, emails, notifications, mapeamento de IDs e revoke.

Operações destrutivas incluem delete, close, archive, revoke e remoção de uploads.

## Sync

`sync` envia comandos em lote para `/sync`, com `sync_token`, `temp_id` e `temp_id_mapping` conforme a API oficial. Não aceitar comandos arbitrários fora do fluxo documentado.

## Arquivos

Uploads usam `body.file_path` e o cliente monta o contrato multipart documentado pela API. Respostas binárias devem ser transportadas como Base64 no JSON, sem registrar conteúdo em logs.

## Segurança

O token deve vir do campo configurado no KeePassVault. Não imprimir request headers, token, senha, resposta bruta de falha ou conteúdo secreto.

Referência: https://developer.todoist.com/api/v1/
