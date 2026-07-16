# PowerTec Support AI

Plataforma profissional para suporte tecnico automatizado de clientes de PDV, varejo, ERP, emissao fiscal, estoque, caixa e equipamentos relacionados.

Este repositorio esta na Etapa 1 auditada do plano: estrutura inicial, Docker, banco, autenticacao com access/refresh token, usuarios, permissoes, clientes, estabelecimentos, produtos, equipamentos de demonstracao e chamados.

## Arquitetura da Etapa 1

- `backend`: API FastAPI, SQLAlchemy, Alembic, JWT com refresh token persistido e seed de desenvolvimento.
- `frontend`: Next.js com TypeScript, Tailwind CSS e componentes reutilizaveis.
- `postgres`: banco principal com imagem pgvector preparada para a base de conhecimento das proximas etapas.
- `redis`: broker para Celery.
- `minio`: armazenamento local compativel com S3.
- `client-agent`: reservado para a Etapa 5, sem comandos remotos nesta etapa.

## Execucao local

1. Copie `.env.example` para `.env` e ajuste segredos locais.
2. Defina uma senha local para `DEMO_ADMIN_PASSWORD`.
3. Suba a infraestrutura:

```bash
docker compose up --build
```

4. Em outro terminal, se necessario, rode migracao e seed:

```bash
docker compose run --rm migrate
docker compose run --rm seed
```

5. Acesse:

- Frontend: `http://localhost:3000`
- Backend: `http://localhost:8000`
- Documentacao da API: `http://localhost:8000/docs`
- MinIO: `http://localhost:9001`

## Usuario de demonstracao

- Tenant: `powertec`
- E-mail: `admin@powertec.local`
- Senha: valor definido em `DEMO_ADMIN_PASSWORD`

O seed so executa quando `APP_ENV=development` e `SEED_DEMO_DATA=true`.

## Testes

Backend:

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
.venv\Scripts\python.exe -m pytest -q
```

Frontend:

```bash
cd frontend
npm install
npm test
```

## Auditoria manual essencial

Com Docker disponivel na maquina:

```bash
docker compose up --build
docker compose run --rm migrate
docker compose run --rm seed
```

Depois valide:

- `GET http://localhost:8000/api/v1/health`
- `POST http://localhost:8000/api/v1/auth/login`
- `POST http://localhost:8000/api/v1/auth/refresh`
- rotas protegidas de clientes, estabelecimentos, produtos e chamados usando `Authorization: Bearer <access_token>`

Rotas de cadastro ignoram `tenant_id` enviado pelo cliente e usam o tenant do usuario autenticado.

## Limites desta etapa

- Nenhum comando remoto destrutivo foi implementado.
- Integracoes de WhatsApp, OpenAI, GitHub e agente Windows ficam para etapas posteriores.
- Os dados do frontend sao demonstrativos e ficticios.
- A Etapa 2 nao deve comecar enquanto a subida via Docker Compose nao for validada em um ambiente com Docker disponivel.
