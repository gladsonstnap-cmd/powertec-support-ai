# Validacao de Infraestrutura da Etapa 1

Data: 2026-07-11

## Objetivo

Parar o desenvolvimento de novas funcionalidades e provar que a infraestrutura da Etapa 1 funciona antes de iniciar WhatsApp, IA ou qualquer nova camada.

## Resultado geral

Status: seed corrigido e validado.

O problema original do seed foi corrigido com:

- validacao explicita do limite de 72 bytes do bcrypt antes de gerar hash;
- erro claro quando `DEMO_ADMIN_PASSWORD` excede o limite suportado;
- senha padrao de desenvolvimento compativel com bcrypt;
- pin de `bcrypt==4.0.1` junto com `passlib==1.7.4` para remover a incompatibilidade observada com bcrypt mais novo.

## Testes executados

| Teste | Resultado | Observacao |
| --- | --- | --- |
| Reinstalar dependencias Python locais | Passou | `bcrypt 5.0.0` foi substituido por `bcrypt 4.0.1`. |
| Testes automatizados backend | Passou | `.venv\Scripts\python.exe -m pytest -q`: `5 passed`. |
| Build das imagens Python | Passou | `backend`, `migrate`, `seed`, `celery-worker` e `celery-beat` reconstruidos com `bcrypt==4.0.1`. |
| `docker compose up -d` | Passou | Servicos principais iniciados. |
| PostgreSQL | Passou apos recovery | Reinicio controlado deixou o container `healthy`. |
| Redis | Passou | Container `healthy`. |
| Migracoes Alembic | Passou | `docker compose run --rm migrate` finalizou com codigo 0. |
| Seed manual | Passou | `docker compose run --rm seed` finalizou com codigo 0. |
| Seed via servico Compose | Passou | `docker compose up --force-recreate seed` finalizou com `seed-1 exited with code 0`. |
| Logs do seed | Passou | `Development seed completed for tenant 'powertec' and user 'admin@powertec.local'.` |
| Login demo | Passou | Login retornou `token_type=bearer`, access token e refresh token. |

## Comandos executados

```powershell
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
.venv\Scripts\python.exe -m pytest -q
$env:DOCKER_CONFIG=(Resolve-Path .docker).Path; docker compose build backend migrate seed celery-worker celery-beat
$env:DOCKER_CONFIG=(Resolve-Path .docker).Path; docker compose up -d
$env:DOCKER_CONFIG=(Resolve-Path .docker).Path; docker compose restart postgres
$env:DOCKER_CONFIG=(Resolve-Path .docker).Path; docker compose run --rm migrate
$env:DOCKER_CONFIG=(Resolve-Path .docker).Path; docker compose run --rm seed
$env:DOCKER_CONFIG=(Resolve-Path .docker).Path; docker compose up --force-recreate seed
$env:DOCKER_CONFIG=(Resolve-Path .docker).Path; docker compose ps
$env:DOCKER_CONFIG=(Resolve-Path .docker).Path; docker compose logs seed
```

## Observacoes importantes

- Foi necessario usar `DOCKER_CONFIG` apontando para `.docker/` dentro do projeto porque o Docker nao tinha permissao para acessar `C:\Users\55949\.docker\config.json`.
- O PostgreSQL entrou em recovery durante a validacao inicial e bloqueou `migrate`/`seed`; apos restart controlado, voltou para `healthy`.
- A verificacao bcrypt dentro do Docker ficou lenta neste ambiente, mas foi mantido o custo padrao de seguranca. O teste de login foi executado com timeout maior e retornou token corretamente.
- O acesso HTTP pelo host via `Invoke-RestMethod` fechou conexao inesperadamente em alguns momentos; a API respondeu corretamente dentro do container e o login foi validado contra o backend em execucao.

## Usuario demonstrativo validado

- Tenant: `powertec`
- E-mail: `admin@powertec.local`
- Senha: `change-this-demo-password`

O teste de login confirmou access token e refresh token para esse usuario.
