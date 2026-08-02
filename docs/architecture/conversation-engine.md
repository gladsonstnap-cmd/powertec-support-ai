# Conversation Engine

## Responsabilidade

`DiagnosticConversationEngine` é a camada de conversa sobre o Session Engine. Ela reconhece comandos, delega mudanças de estado e transforma `SessionTurnResult` em `ConversationResponse`.

## Entradas e saídas

- `ConversationInput`: mensagem, sessão opcional e contexto opcional.
- `ConversationResponse`: texto, sessão, workflow, decisão, status, flags, metadados e erros.
- `ConversationCommand`: `NORMAL`, `STATUS`, `RESTART`, `CANCEL`, `ESCALATE` ou `HELP`.

## Fluxo

Sem sessão, uma mensagem normal chama `start_session()`. Com sessão, chama `continue_session()`. HELP e STATUS são respondidos sem novo workflow. CANCEL e ESCALATE são delegados ao Session Engine. RESTART cria nova sessão e preserva somente metadados.

## Comandos

São reconhecidos após normalização de caixa e acentos: `status`, `cancelar`, `encerrar`, `reiniciar`, `começar novamente`, `humano`, `atendente`, `ajuda` e `help`.

## Tratamento de erros

A fronteira captura exceções do Session Engine e retorna mensagem objetiva com erro estruturado, preservando a sessão recebida quando houver.

## Limites e segurança

- não inventa diagnóstico;
- não executa ações ou comandos;
- não afirma que uma recomendação foi executada;
- não conhece detalhes de WhatsApp;
- flags de espera e término são derivadas do status da sessão.

## Testes

`test_conversation_engine.py` cobre início, continuação, comandos, respostas, delegação, erros, imutabilidade, determinismo e BOM.

## O que não faz

Não envia mensagens, não acessa WhatsApp, não persiste conversas, não autentica usuários e não executa decisões diagnósticas.
