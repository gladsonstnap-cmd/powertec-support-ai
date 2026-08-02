# Workflow Engine

## Responsabilidade

`DiagnosticWorkflowEngine` coordena uma execução diagnóstica em ordem fixa:

```text
Intent → Incident → Knowledge → Hypothesis → Evidence → Decision → Complete
```

## Entrada

`run()` recebe mensagem, contexto e histórico opcionais. Para continuidade, também aceita hipóteses, evidências, decisões, perguntas e informações conhecidas anteriores.

## Saída

`WorkflowResult` contém todos os resultados intermediários, tempo de processamento medido com `time.monotonic()`, etapas executadas, sucesso, erros e metadados.

## Fluxo e modelos

`WorkflowStep` registra as etapas. O workflow classifica a mensagem, consulta conhecimento, gera ou reutiliza hipóteses, aplica evidência e entrega `DecisionInput` ao Decision Engine.

## Tratamento de erros

Qualquer exceção de componente é capturada. A etapa fica em `metadata["failed_step"]`, a mensagem entra em `errors`, `success` permanece falso e a exceção não é relançada.

## Limites e segurança

- ordem imutável e comportamento local;
- histórico copiado antes de ser entregue aos componentes;
- nenhuma chamada externa;
- nenhuma execução de teste ou ação recomendada.

## Testes

`test_workflow_engine.py` cobre fluxo completo, falha em cada etapa, tempo, ordem, determinismo, histórico, confirmação, injeção e construtor padrão.

## O que não faz

Não guarda sessões entre chamadas, não formata conversa para o usuário, não persiste resultados e não executa decisões.
