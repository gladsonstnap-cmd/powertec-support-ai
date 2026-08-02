# Session Engine

## Responsabilidade

`DiagnosticSessionEngine` mantém continuidade entre mensagens por snapshots de `DiagnosticSession`. O engine não guarda estado global: cada chamada recebe uma sessão e retorna uma nova.

## Entradas e saídas

- `start_session(message, session_id, context)` inicia o diagnóstico.
- `continue_session(session, message, context, user_confirmation)` continua o histórico.
- `cancel_session()` e `restart_session()` controlam o ciclo de vida.
- Todas retornam `SessionTurnResult`.

## Modelos e política

`DiagnosticSession` preserva intenção, incidente, conhecimento, hipóteses, evidências, decisões, perguntas, respostas, informações conhecidas, status e contadores. Coleções históricas usam tuplas e cópias defensivas. `DiagnosticSessionPolicy` define limites de interações, perguntas, testes e repetições.

## Fluxo

Uma sessão nova passa por `NEW` somente antes do primeiro workflow. As decisões mapeiam para espera do usuário, confirmação, teste, ação, escalada ou conclusão. Uma continuação encaminha o histórico ao Workflow Engine e cria outro snapshot.

## Tratamento de erros

Falha do workflow produz sessão `FAILED`. Sessões canceladas ou falhas não continuam. Sessões concluídas e escaladas respeitam regras terminais e política de reinício.

## Limites e segurança

- limite de interações;
- prevenção de pergunta repetida;
- deduplicação de evidência;
- histórico não removido;
- ações não são executadas;
- timestamps usam `time.monotonic()`.

## Testes

`test_session_engine.py` cobre ciclo de vida, estados, comandos, histórico, imutabilidade, limites, erros, confirmação e UTF-8.

## O que não faz

Não persiste em banco, Redis ou disco; não gerencia autenticação, tickets, filas ou canal de mensagens.
