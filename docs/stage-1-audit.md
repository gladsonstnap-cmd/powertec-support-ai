# Auditoria da Etapa 1

## Funcionalidades encontradas

- Estrutura backend FastAPI, frontend Next.js e Docker Compose.
- Modelos iniciais de tenant, usuario, permissao, cliente, estabelecimento, produto, equipamento e chamado.
- Alembic com migracao inicial.
- Autenticacao JWT com access token e refresh token persistido.
- Seed idempotente de desenvolvimento.

## Erros identificados e corrigidos

- Login retornava `501`; foi implementado.
- Rotas CRUD confiavam em `tenant_id` externo; agora usam o tenant do token.
- Nao havia refresh token persistido; foi criada tabela e fluxo de renovacao.
- Nao havia seed seguro; foi criado seed condicionado a ambiente de desenvolvimento.
- Testes nao encontravam pacote `app`; foi adicionado `pytest.ini`.
- Migracao nao refletia todos os campos dos modelos; schema inicial foi alinhado.

## Bloqueios de ambiente

- Docker nao esta disponivel no PATH deste ambiente, entao Compose, PostgreSQL, Redis, migracoes em container e comunicacao frontend-backend nao puderam ser validados aqui.
- A Etapa 2 deve aguardar validacao real do Docker Compose.
