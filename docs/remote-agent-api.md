# Remote Agent API

Base path:

`/api/v1/agents`

Endpoints:

- `POST /register`: registra ou atualiza agente e retorna token completo uma unica vez.
- `POST /heartbeat`: atualiza `last_seen_at` usando `Authorization: Bearer <agent_token>`.
- `GET /`: lista agentes do tenant autenticado.
- `GET /{agent_id}`: detalhes do agente.
- `GET /tools`: lista ferramentas cadastradas e schemas.
- `POST /{agent_id}/commands`: cria comando idempotente por `request_uuid`.
- `GET /{agent_id}/commands`: lista comandos do agente.
- `GET /commands/{command_id}`: consulta comando.
- `POST /commands/{command_id}/approve`: aprova comando pendente.
- `POST /commands/{command_id}/result`: recebe resultado do agente correspondente.
- `GET /{agent_id}/audit`: lista auditoria.

Exemplo de comando:

```json
{
  "request_uuid": "uuid",
  "tool_name": "service_status",
  "arguments_json": {
    "service_name": "Spooler"
  }
}
```

Exemplo de resultado:

```json
{
  "request_uuid": "uuid",
  "status": "success",
  "duration_ms": 10,
  "result_json": {
    "service_name": "Spooler",
    "status": "running"
  }
}
```
