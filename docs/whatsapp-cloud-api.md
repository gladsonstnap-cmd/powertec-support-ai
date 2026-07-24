# WhatsApp Cloud API - Sprint 4A

Esta etapa adiciona a base organizada para WhatsApp Cloud API sem ativar chamadas reais automaticamente e sem remover o provider `mock`.

## Providers

O provider ativo é selecionado por:

```env
WHATSAPP_PROVIDER=mock
```

Valores previstos:

- `mock`: registra envios localmente e nao faz chamadas externas.
- `meta`: usa cliente HTTP isolado para a Graph API da Meta.

Variaveis usadas pelo provider `meta`:

- `WHATSAPP_ACCESS_TOKEN`
- `WHATSAPP_API_VERSION`
- `WHATSAPP_PHONE_NUMBER_ID`
- `WHATSAPP_VERIFY_TOKEN`
- `WHATSAPP_APP_SECRET`
- `WHATSAPP_REQUEST_TIMEOUT_SECONDS`

## Webhook

Endpoint de verificacao:

```http
GET /api/v1/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=TOKEN&hub.challenge=CHALLENGE
```

Quando `hub.verify_token` bate com `WHATSAPP_VERIFY_TOKEN`, o backend retorna o challenge em texto puro. Caso contrario, retorna `403`.

Endpoint de recebimento:

```http
POST /api/v1/whatsapp/webhook
```

Suporte inicial:

- mensagens de texto;
- telefone do remetente;
- nome do contato quando enviado pela Meta;
- ID externo da mensagem;
- timestamp;
- numero de destino;
- payloads sem mensagens;
- tipos nao suportados sem derrubar a aplicacao.

## Idempotencia

A tabela `messaging_messages` ja possui unicidade por:

```text
tenant_id, provider, external_message_id
```

O processamento consulta esse ID antes de criar contato, conversa, mensagem ou ticket. Reenvios da Meta sao contabilizados como duplicados.

## Conversa e Ticket

Ao receber texto novo:

1. localiza ou cria contato;
2. localiza ou cria conversa aberta;
3. cria ticket quando a conversa nao possui ticket ativo adequado;
4. registra a mensagem recebida;
5. preserva historico existente.

Nesta Sprint, webhooks usam o primeiro tenant ativo como tenant padrao. Antes de producao, a resolucao de tenant deve considerar `phone_number_id`, conta WhatsApp Business ou configuracao explicita por tenant.

## Seguranca

Nao registrar tokens ou segredos nos erros. O provider `meta` retorna erros genericos como `HTTP 401` sem ecoar credenciais.

A validacao de assinatura `X-Hub-Signature-256` foi preparada e ativada quando `WHATSAPP_APP_SECRET` estiver configurado com valor diferente de `change-me`. Em desenvolvimento, sem secret real, o POST permanece testavel localmente.

## Validacao Local

```powershell
docker compose config
docker compose run --rm migrate
docker compose exec backend pytest
docker compose exec frontend pnpm test -- --run
docker compose exec frontend pnpm exec tsc --noEmit
docker compose exec frontend pnpm build
docker compose ps
```

## Pendencias Antes de Producao

- Mapear tenant pelo `phone_number_id`.
- Configurar `WHATSAPP_APP_SECRET` real e exigir assinatura em todos os ambientes produtivos.
- Rotacionar e armazenar `WHATSAPP_ACCESS_TOKEN` em secret manager.
- Configurar webhook na Meta com HTTPS publico.
- Adicionar observabilidade sem expor conteudo sensivel.
- Definir politica de retencao de payloads brutos.
