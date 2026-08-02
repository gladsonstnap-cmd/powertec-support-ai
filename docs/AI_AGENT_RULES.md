# Regras para agentes de desenvolvimento

Estas regras se aplicam a Codex e a outros agentes que trabalhem neste projeto.

## Antes de trabalhar

- confirmar o repositório, o diretório atual e a branch;
- não trabalhar fora do checkout correto;
- confirmar o working tree antes de editar;
- ler as implementações e testes relacionados;
- não avançar para outra sprint sem autorização.

Exemplo de caminho local, sem constituir dependência do código:

```text
C:\Users\Powertec\Documents\Codex\2026-07-10\cole-o-prompt-na-raiz-de\powertec-support-ai
```

## Durante a mudança

- preservar todos os testes existentes;
- não alterar módulos fora do escopo;
- não executar ações destrutivas;
- não incluir credenciais, tokens ou dados reais;
- manter arquivos em UTF-8 sem BOM;
- não usar GPT/OpenAI em módulos determinísticos sem autorização;
- não integrar Remote Agent antes da aprovação das políticas de segurança;
- tratar ações HIGH e CRITICAL como dependentes de aprovação humana;
- distinguir sempre implementado, planejado e fora do escopo;
- não fazer commit ou push automaticamente.

## Validação e entrega

- executar somente os testes relevantes e a suíte solicitada;
- nunca afirmar que um teste foi executado sem evidência;
- verificar compilação, diff, whitespace, BOM e status;
- preservar mudanças preexistentes do usuário;
- apresentar relatório final com arquivos, arquitetura, testes, limitações e estado Git;
- aguardar autorização explícita para commit, push, tag ou próxima sprint.
