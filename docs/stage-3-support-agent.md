# Etapa 3 - Triagem inteligente e base de conhecimento

## Escopo

A Etapa 3 mantem `WHATSAPP_PROVIDER=mock` e `AI_PROVIDER=mock` por padrao.

Nao ha integracao com Meta, acesso remoto, execucao de comandos em clientes, deploy em producao ou correcao automatica por IA.

## Arquitetura

Principais blocos:

- `backend/app/agents/support`: agente de suporte, regras, extracao, safety, prompts e montagem de resposta.
- `backend/app/integrations/ai`: abstracao de provedor de IA, mock previsivel e provider OpenAI preparado com fallback.
- `backend/app/services/knowledge`: validacao, sanitizacao, chunking, indexacao e busca hibrida.
- `backend/app/api/v1/endpoints/knowledge.py`: API da base de conhecimento.
- `frontend/app/knowledge`: tela protegida da base de conhecimento.
- `frontend/app/tickets`: exibe analise tecnica quando existente.

## Entidades

Migração `0003_support_agent_knowledge` adiciona:

- `knowledge_documents`
- `knowledge_document_versions`
- `knowledge_chunks`
- `knowledge_tags`
- `knowledge_products`
- `knowledge_approvals`
- `knowledge_search_logs`
- `ticket_analyses`
- `support_audit_logs`

## Endpoints

- `GET /api/v1/knowledge/documents`
- `POST /api/v1/knowledge/documents`
- `GET /api/v1/knowledge/documents/{document_id}/chunks`
- `POST /api/v1/knowledge/documents/{document_id}/approval`
- `POST /api/v1/knowledge/documents/{document_id}/deactivate`
- `POST /api/v1/knowledge/search`
- `GET /api/v1/tickets/{ticket_id}/analysis`

Todos exigem autenticacao.

## Regras de prioridade

Deterministicas, com precedencia sobre IA:

- P1: todos os caixas parados, loja sem vender, servidor principal indisponivel, risco de perda de dados, emissao fiscal completamente parada.
- P2: NFC-e rejeitada/nao emite, TEF indisponivel, fechamento de caixa com erro, impressora critica, lentidao geral.
- P3: terminal unico, impressao parcial, relatorio nao gera, lentidao localizada.
- P4: duvida, configuracao, treinamento, melhoria, informacao.

As regras acionadas sao persistidas em `ticket_analyses.triggered_rules` e `support_audit_logs.triggered_rules`.

## Segurança

- Conteudo de cliente e documentos e tratado como dado nao confiavel.
- Filtros bloqueiam prompt injection conhecido.
- Segredos sao mascarados antes do contexto de IA.
- Acoes de risco sao removidas das recomendacoes e marcam `requires_authorization`.
- Arquivos executaveis, MIME invalido e path traversal sao recusados.
- Busca usa somente documentos do mesmo tenant, aprovados e validos.

## Dados de demonstracao

O seed cria documentos ficticios aprovados:

1. PDV nao abre
2. Todos os caixas sem conexao
3. Impressora termica nao imprime
4. NFC-e rejeitada
5. TEF indisponivel
6. Servico do banco parado
7. Erro de conexao com servidor
8. Certificado digital nao encontrado

## Validação executada

Comandos locais executados:

```powershell
.venv\Scripts\python.exe -m compileall backend
.venv\Scripts\python.exe -m pytest -q
pnpm --dir frontend test
pnpm --dir frontend exec tsc --noEmit
pnpm --dir frontend build
python -m alembic heads
python -m alembic history --verbose
```

Resultados:

- Backend tests: `29 passed`.
- Frontend tests: `9 passed`.
- Frontend TypeScript: sucesso.
- Frontend build: sucesso.
- Alembic head: `0003_support_agent_knowledge`.

## Limitações

- A busca semantica usa embedding deterministico local simples em JSON, adequado para mock/testes; pgvector real pode substituir depois.
- `openai_provider.py` esta preparado, mas usa fallback mock ate a chamada Responses API ser habilitada com chave e politicas finais.
- Upload usa payload base64 no MVP; upload multipart pode ser adicionado depois.
- MinIO esta representado por `storage_key`; persistencia fisica do arquivo pode ser ligada na proxima etapa.
- Docker nao foi validado nesta rodada por instabilidade previa de DNS/proxy do Docker local.

## Teste manual esperado

No simulador, com `+5594999990001`:

- Mensagem: `Todos os caixas estao parados e nao consigo vender.`
- Esperado: P1, `store_stopped=true`, `requires_human=true`, pergunta sobre impacto/erro/servidor e analise visivel em `/tickets`.

Segundo teste:

- Mensagem: `A impressora do caixa 2 nao imprime.`
- Esperado: P3 ou P2 conforme impacto, equipamento `CAIXA-02`, perguntas seguras e nenhuma acao automatica.
