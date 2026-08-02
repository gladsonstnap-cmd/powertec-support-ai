# Diagnostic Engine

## Responsabilidade

O pacote `backend/app/services/diagnostic_engine` reúne os modelos, regras e engines determinísticos do diagnóstico. Ele transforma mensagens e contexto em hipóteses, evidências e decisões seguras.

## Entradas e saídas

- Entradas: mensagem, `DiagnosticContext`, histórico e confirmação opcional.
- Saídas: classificações, resultados da Knowledge Base, hipóteses, evidência, decisão, sessão ou resposta de conversa, conforme a camada usada.

## Principais modelos

- `IntentClassification`, `IncidentClassification` e `DiagnosticContext`;
- `KnowledgeIncident` e `KnowledgeSearchResult`;
- `Hypothesis`, `Evidence`, `EvidenceResult` e `Decision`;
- `WorkflowResult`, `DiagnosticSession` e `ConversationResponse`.

## Fluxo

O uso de mais alto nível começa no Conversation Engine. Ele delega ao Session Engine, que chama o Workflow Engine. O workflow usa classificadores, conhecimento, hipóteses, evidências e decisão em ordem fixa.

## Erros e limites

Os engines de workflow e conversa convertem falhas de componentes em resultados estruturados. Políticas limitam perguntas, testes, interações e respostas repetidas. Confianças são limitadas ao intervalo `0.0–1.0`.

## Segurança

- sem `random` na lógica diagnóstica;
- sem HTTP, banco, WhatsApp, Docker ou execução de comandos;
- testes recomendados precisam ser seguros e somente leitura;
- ações sensíveis ou de risco são bloqueadas, confirmadas ou escaladas;
- uma recomendação nunca é apresentada como ação executada.

## Testes

Os testes em `backend/tests/services/diagnostic_engine` cobrem classificadores, conhecimento, hipóteses, evidências, decisão, workflow, sessão e conversa.

## O que não faz

O pacote não persiste estado, não controla máquinas, não chama provedores de IA e não substitui autenticação, tickets, mensageria ou auditoria do restante da plataforma.
