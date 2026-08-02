# Fluxo de desenvolvimento

## Processo padrão

1. Confirmar o diretório do checkout.
2. Confirmar a branch e o escopo autorizado.
3. Confirmar que o working tree está limpo.
4. Criar ou usar uma branch de feature.
5. Inspecionar código, testes, documentação e histórico relevantes.
6. Implementar apenas o escopo autorizado.
7. Executar `compileall`.
8. Executar os testes específicos.
9. Executar os testes do pacote afetado.
10. Executar a suíte completa.
11. Verificar `git diff --check`.
12. Verificar UTF-8 sem BOM.
13. Revisar `git diff` e `git status`.
14. Fazer commit somente após autorização e revisão.
15. Fazer push somente após autorização.
16. Criar tag apenas para um marco aprovado.

## PowerShell

Na raiz do projeto:

```powershell
Get-Location
git branch --show-current
git status --porcelain=v1

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt

python -m compileall backend\app -q
python -m pytest -q

git diff --check
git diff --stat
git status --short
```

Testes direcionados podem ser executados a partir de `backend`:

```powershell
python -m pytest -q tests\services\diagnostic_engine
```

Frontend:

```powershell
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend test
```

Docker, quando necessário e disponível:

```powershell
docker compose up -d
docker compose ps
```

Não use comandos destrutivos para “limpar” mudanças do usuário. Não registre resultados de testes que não foram efetivamente executados.
