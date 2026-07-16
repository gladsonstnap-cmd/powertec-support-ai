# Docker troubleshooting

Este documento cobre falhas observadas durante validacoes longas do PowerTec Support AI em Docker Desktop no Windows.

## Sintomas observados

- `docker compose ps` fica pendurado sem retornar.
- `docker image inspect` nao responde apos build longo.
- Build falha ao resolver `node:22-alpine` ou `python:3.12-slim`.
- Erro de DNS/proxy parecido com:

```text
lookup http.docker.internal on 192.168.65.7:53: i/o timeout
```

- Perda do engine `dockerDesktopLinuxEngine`.
- Backend/frontend param de responder mesmo com containers aparentemente ativos.
- Pipe do daemon ausente:

```text
failed to connect to the docker API at npipe:////./pipe/docker_engine
The system cannot find the file specified.
```

## Verificacoes rapidas

No PowerShell:

```powershell
docker version
docker context ls
docker compose ps
wsl -l -v
Get-Service com.docker.service
```

Se qualquer comando Docker ficar pendurado por mais de 30 segundos, interrompa a validacao e reinicie o Docker Desktop antes de repetir.

## Script de validacao

Use:

```powershell
.\scripts\validate-environment.ps1
```

O script executa:

```powershell
docker compose ps
docker compose run --rm migrate
docker compose run --rm seed
docker compose exec backend python -m pytest -q
docker compose exec frontend pnpm test
docker compose exec frontend pnpm exec tsc --noEmit
```

Antes de cada etapa, e durante comandos longos, ele verifica se o daemon ainda responde. Se o daemon ficar indisponivel, o script encerra a etapa atual e mostra uma mensagem clara.

## Docker Desktop reiniciando

Possiveis causas:

- Uso alto de memoria durante `docker compose build`.
- BuildKit desempacotando imagens grandes.
- WSL sem memoria suficiente.
- Proxy/DNS instavel durante pull de imagens.
- Antivirus inspecionando arquivos de imagem/volumes.

Acoes:

1. Feche builds pendurados.
2. Reinicie Docker Desktop.
3. Rode:

```powershell
wsl --shutdown
```

4. Abra Docker Desktop novamente.
5. Valide:

```powershell
docker version
docker compose ps
```

## Perda do dockerDesktopLinuxEngine

Sintomas:

- `docker version` nao mostra Server.
- `docker compose ps` fica pendurado.
- Docker Desktop mostra engine parado.
- `npipe:////./pipe/docker_engine` nao existe.

Acoes:

```powershell
wsl -l -v
wsl --shutdown
```

Depois reinicie Docker Desktop. Se persistir, use a opcao "Restart Docker Desktop" na interface.

## Timeout DNS

Sintoma comum:

```text
failed to resolve source metadata for docker.io/library/node:22-alpine
lookup http.docker.internal ... i/o timeout
```

Acoes:

1. Verifique conexao:

```powershell
docker pull hello-world
```

2. Reinicie Docker Desktop.
3. Se usar VPN/proxy, teste sem VPN.
4. Em Docker Desktop > Settings > Resources > Network, redefina DNS/proxy conforme a rede local.
5. Tente novamente:

```powershell
docker compose build frontend
```

## Proxy

Se a rede exige proxy:

- Configure Docker Desktop > Settings > Proxies.
- Evite proxy parcial apenas no Windows se o engine Linux nao conseguir resolver `http.docker.internal`.
- Valide:

```powershell
docker run --rm alpine nslookup registry-1.docker.io
```

Se este comando travar, o problema esta abaixo do projeto.

## WSL

Verifique distros e estado:

```powershell
wsl -l -v
```

Recuperacao leve:

```powershell
wsl --shutdown
```

Depois abra Docker Desktop e aguarde o engine iniciar.

Se houver uso excessivo de memoria, configure `.wslconfig` no perfil do usuario Windows, por exemplo:

```ini
[wsl2]
memory=6GB
processors=4
swap=2GB
```

Reinicie WSL depois:

```powershell
wsl --shutdown
```

## Docker Hub

Falhas de pull podem ser externas ou de rate limit.

Diagnostico:

```powershell
docker pull node:22-alpine
docker pull python:3.12-slim
docker pull redis:7-alpine
docker pull pgvector/pgvector:pg16
```

Se falhar antes de baixar camadas, e provavelmente DNS/proxy/auth. Se falhar no meio, pode ser instabilidade de rede.

## Build interrompido

Depois de build interrompido, o BuildKit pode manter estado parcial.

Verifique:

```powershell
docker buildx ls
docker builder prune
```

Use `docker builder prune` com cuidado: ele remove cache de build e deixa builds futuros mais lentos, mas nao apaga volumes do banco.

Para limpar containers parados do projeto:

```powershell
docker compose ps -a
docker compose rm
```

Nao use `docker compose down -v` a menos que queira apagar os volumes `postgres_data` e `minio_data`.

## Compose do projeto

Decisoes atuais:

- `migrate` e `seed` usam `profiles: ["jobs"]` e `restart: "no"`.
- `migrate` e `seed` devem ser executados manualmente com `docker compose run --rm ...`.
- `postgres`, `redis`, `backend` e `frontend` possuem healthchecks.
- `frontend` usa `restart: "no"` para evitar reinicio desnecessario em desenvolvimento.
- `celery-worker` e `celery-beat` aguardam `backend`, `postgres` e `redis` saudaveis.
- `celery-worker` e `celery-beat` usam `restart: on-failure:3`.

## Validacao recomendada

```powershell
docker version
docker compose ps
.\scripts\validate-environment.ps1
docker compose logs backend --tail=200
docker compose logs celery-worker --tail=200
```

Se o primeiro ou segundo comando travar, nao continue. Corrija Docker Desktop/WSL/rede primeiro.
