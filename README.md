# PowerTec Support AI

Plataforma de suporte técnico para clientes de PDV, varejo, ERP, emissão fiscal, estoque, caixa e sistemas comerciais relacionados.

O objetivo central é receber chamados via chat, diagnosticar problemas de software em sistemas de venda/PDV, resolver automaticamente quando isso for seguro e encaminhar para atendimento humano quando necessário.

## Visão geral

O repositório contém:

- backend FastAPI com SQLAlchemy, Alembic, autenticação JWT e isolamento por tenant;
- frontend Next.js com TypeScript e Tailwind CSS;
- PostgreSQL/pgvector, Redis, Celery e MinIO na composição local;
- mensageria simulada e integração WhatsApp Cloud API configurável;
- base de conhecimento e suporte orientado por regras;
- AI Orchestrator separado, determinístico e com ferramentas simuladas;
- Diagnostic Engine local e determinístico;
- base separada de Remote Agent com allowlist e políticas de segurança.

Nenhuma dessas descrições autoriza execução automática de ações em máquinas de clientes.

## Arquitetura atual do diagnóstico

```text
Conversation Engine
→ Session Engine
→ Workflow Engine
→ Intent Classifier
→ Incident Classifier
→ Knowledge Base
→ Hypothesis Engine
→ Evidence Engine
→ Decision Engine
```

O pacote `backend/app/services/diagnostic_engine` não usa banco, WhatsApp, HTTP, Docker, Remote Agent ou GPT/OpenAI. Ele produz diagnósticos e recomendações estruturadas; não executa ações.

Veja [a visão geral da arquitetura](docs/architecture/system-overview.md).

## Requisitos

- Python 3.12 compatível com o backend;
- Node.js compatível com o frontend;
- pnpm para dependências e testes do frontend;
- Docker Desktop/Engine e Docker Compose para a stack completa;
- PowerShell para os exemplos no Windows.

## Instalação local

Na raiz do repositório:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
pnpm --dir frontend install --frozen-lockfile
```

Copie `.env.example` para `.env`, configure segredos apenas no ambiente local e defina `DEMO_ADMIN_PASSWORD`. Não registre `.env` no Git.

O seed de demonstração só deve ser usado com `APP_ENV=development` e `SEED_DEMO_DATA=true`.

## Docker Compose

```powershell
docker compose up -d
docker compose run --rm migrate
docker compose run --rm seed
docker compose ps
```

Serviços expostos localmente:

- Frontend: `http://localhost:3000`
- Backend: `http://localhost:8000`
- Documentação da API: `http://localhost:8000/docs`
- MinIO: `http://localhost:9001`

Consulte [Docker troubleshooting](docs/docker-troubleshooting.md) antes de executar limpezas de containers, imagens ou volumes.

## Usuário de demonstração

- Tenant: `powertec`
- E-mail: `admin@powertec.local`
- Senha: valor local de `DEMO_ADMIN_PASSWORD`

Use apenas dados fictícios em desenvolvimento.

## Testes

Backend, com a venv ativa:

```powershell
python -m compileall backend\app -q
python -m pytest -q
```

Frontend:

```powershell
pnpm --dir frontend test
```

Testes específicos do diagnóstico:

```powershell
Set-Location backend
python -m pytest -q tests\services\diagnostic_engine
```

## Desenvolvimento

A branch de desenvolvimento do marco diagnóstico atual é `feature/diagnostic-engine`, com a tag confirmada `sprint4c8`. Confirme sempre branch e working tree antes de editar; não presuma que essa branch será permanente.

- [Contexto do projeto](docs/PROJECT_CONTEXT.md)
- [Roadmap](docs/ROADMAP.md)
- [Fluxo de desenvolvimento](docs/DEVELOPMENT_WORKFLOW.md)
- [Regras para agentes](docs/AI_AGENT_RULES.md)
- [Arquitetura](docs/architecture/system-overview.md)
- [Decisões técnicas](docs/decisions/adr-001-deterministic-diagnostic-engine.md)
- [Política de segurança](SECURITY.md)
- [Changelog](CHANGELOG.md)

## Limitações atuais

- as sessões do novo Diagnostic Session Engine existem apenas em memória;
- o Conversation Engine ainda não está integrado ao controller WhatsApp existente;
- o Diagnostic Engine não está integrado à base de Remote Agent;
- diagnóstico e recomendação não executam comandos;
- ferramentas do AI Orchestrator continuam simuladas conforme sua documentação;
- dados do frontend e seed são demonstrativos;
- integração real exige revisão de segurança, isolamento por tenant, auditoria e aprovação conforme o risco.

## Roadmap resumido

Próximos temas propostos, sem datas: Memory Engine, Diagnostic Planner, Action Planner, integração com WhatsApp, persistência de sessões, integração governada com Remote Agent, painel técnico, métricas e auditoria.

O status detalhado está em [ROADMAP.md](docs/ROADMAP.md).
