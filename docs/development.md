# Guia de Desenvolvimento

## Backend

- FastAPI em `backend/app/main.py`.
- Rotas em `backend/app/api/v1/endpoints`.
- Modelos SQLAlchemy em `backend/app/models`.
- Schemas Pydantic em `backend/app/schemas`.
- Seed de desenvolvimento em `backend/app/scripts/seed_dev.py`.

## Seed local

O seed cria dados ficticios somente em ambiente de desenvolvimento:

- tenant `powertec`;
- usuario `admin@powertec.local`;
- cliente `Supermercado Modelo`;
- estabelecimento `Loja Matriz`;
- equipamentos `SERVIDOR-01`, `CAIXA-01` e `CAIXA-02`;
- produtos e chamados demonstrativos.

Configure `DEMO_ADMIN_PASSWORD` antes de executar.

## Frontend

- App Router em `frontend/app`.
- Componentes compartilhados em `frontend/components`.
- Tipos em `frontend/types`.

## Proximas etapas

Avance somente apos executar os testes da Etapa 1, validar Docker Compose e revisar os arquivos criados.
