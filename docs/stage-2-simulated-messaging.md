# Etapa 2 - Mensageria simulada

## Escopo implementado

A Etapa 2 adiciona somente mensageria simulada, com `WHATSAPP_PROVIDER=mock`.

Nao ha integracao real com WhatsApp, Meta, IA, OpenAI, LangChain, filas externas ou envio para numeros reais. Os arquivos em `backend/app/integrations/messaging/whatsapp` existem apenas como stubs seguros para impedir uso acidental.

## Configuracao

Variaveis relevantes em `.env.example`:

```env
WHATSAPP_PROVIDER=mock
MESSAGING_SIMULATOR_ENABLED=true
WHATSAPP_MAX_MEDIA_SIZE_MB=20
```

Os endpoints de desenvolvimento retornam `404` fora de `APP_ENV=development` ou quando `MESSAGING_SIMULATOR_ENABLED=false`.

## Modelo de dados

A migracao `backend/alembic/versions/0002_mock_messaging.py` cria:

- `contacts`
- `temporary_customers`
- `conversation_sessions`
- `conversation_state_transitions`
- `messaging_messages`
- `message_attachments`
- `messaging_events`
- `ticket_messages`
- `protocol_counters`

As mensagens possuem idempotencia por `(tenant_id, provider, external_message_id)`.

## Fluxos simulados

Estados principais:

- `new_contact`
- `confirming_customer`
- `requesting_contact_name`
- `requesting_company`
- `requesting_city`
- `requesting_system`
- `selecting_device`
- `collecting_problem`
- `ticket_created`
- `waiting_attendant`
- `closed`

Regras deterministicamente simuladas:

- P1: termos como "parou tudo", "nao abre", "sem internet", "urgente".
- P2: termos como "impressora", "lento", "erro".
- P4: demais casos.

Protocolos seguem o formato `PWT-YYYY-000001`.

## Endpoints

Todos exigem autenticacao:

- `POST /api/v1/dev/messaging/simulate`
- `GET /api/v1/dev/messaging/conversations`
- `GET /api/v1/dev/messaging/conversations/{conversation_id}`
- `POST /api/v1/dev/messaging/conversations/{conversation_id}/reset`
- `POST /api/v1/dev/messaging/conversations/{conversation_id}/send`
- `POST /api/v1/dev/messaging/conversations/{conversation_id}/attach`
- `GET /api/v1/conversations`
- `GET /api/v1/conversations/{conversation_id}`

## Frontend

Telas adicionadas:

- `/dev/message-simulator`
- `/conversations`

O simulador aceita um token JWT gerado pelo login e permite enviar mensagens mock, resetar conversa e anexar um arquivo demonstrativo seguro.

## Validacao executada

Comandos executados com sucesso no ambiente local:

```powershell
.venv\Scripts\python.exe -m compileall backend
.venv\Scripts\python.exe -m pytest -q
C:\Users\55949\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback\pnpm.cmd --dir frontend test
```

Resultados:

- Backend compile: sucesso.
- Backend tests: `12 passed`.
- Frontend tests: `1 passed`.

## Validacao Docker

Foi iniciado `docker compose build backend`.

O build concluiu a instalacao das dependencias Python, incluindo `passlib==1.7.4` e `bcrypt==4.0.1`, copiou o codigo e exportou as camadas. Durante a etapa final de `unpacking to docker.io/library/powertec-support-ai-backend:latest`, o Docker local ficou sem resposta. Apos isso, chamadas para `docker image inspect`, backend HTTP e frontend HTTP tambem ficaram indisponiveis ou expiraram.

Antes do travamento do Docker local, `docker compose ps` indicava:

- PostgreSQL: `Up` e `healthy`.
- Redis: `Up` e `healthy`.
- Backend: `Up`.
- Frontend: `Up`.
- Celery Worker: `Up`.
- Celery Beat: `Up`.
- MinIO: `Up`.
- Seed: `Exited (0)`.
- Migrate: `Exited (0)`.

Como o daemon Docker ficou instavel durante a exportacao da nova imagem, a validacao Docker final da Etapa 2 precisa ser repetida em uma sessao Docker limpa:

```powershell
$env:DOCKER_CONFIG=(Resolve-Path .docker).Path
docker compose up -d --build
docker compose ps
docker compose run --rm migrate
docker compose run --rm seed
docker compose exec backend pytest -q
docker compose exec frontend pnpm test
docker compose logs backend --tail=200
docker compose logs frontend --tail=200
```

## Como testar manualmente

1. Suba a stack:

```powershell
$env:DOCKER_CONFIG=(Resolve-Path .docker).Path
docker compose up -d --build
```

2. Acesse:

- Backend: `http://localhost:8000/docs`
- Frontend: `http://localhost:3000`
- Simulador: `http://localhost:3000/dev/message-simulator`
- Conversas: `http://localhost:3000/conversations`

3. Login de desenvolvimento:

- Email: `admin@powertec.local`
- Senha: `change-this-demo-password`

4. No simulador, use um telefone conhecido ou desconhecido:

- Conhecido: `+5594999990001`
- Desconhecido: `+5594999990002`

5. Envie mensagens como:

- `Nao consigo abrir o sistema`
- `A impressora esta com erro`
- `Preciso tirar uma duvida`

6. Confirme que a conversa muda de estado, cria protocolo e registra mensagens sem chamar provedores externos.
