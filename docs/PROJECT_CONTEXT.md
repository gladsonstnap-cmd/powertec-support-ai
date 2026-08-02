# Contexto do projeto

## Produto e objetivo

O **PowerTec Support AI** é uma plataforma de suporte técnico para clientes que operam PDV, ERP, emissão fiscal, estoque, caixa e outros sistemas comerciais.

Seu objetivo central é receber chamados via chat, diagnosticar problemas de software em sistemas de venda/PDV, resolver automaticamente quando isso for seguro e encaminhar o caso para atendimento humano quando necessário.

O público-alvo inclui equipes de suporte, técnicos e operadores de empresas de varejo que precisam investigar indisponibilidade, lentidão, impressão, comunicação, pagamentos, banco de dados e integrações comerciais.

Fluxo desejado:

```text
chamado → diagnóstico → tentativa automatizada segura → atendimento humano
```

Uma tentativa automatizada futura nunca elimina as políticas de risco, aprovação e auditoria.

## Estado confirmado

Na branch `feature/diagnostic-engine`, o marco identificado pela tag `sprint4c8` contém:

- fundação determinística do Diagnostic Engine;
- classificadores de intenção e incidente;
- Knowledge Base local em JSON;
- Hypothesis, Evidence e Decision Engines;
- Workflow Engine;
- Session Engine em memória;
- Conversation Engine independente do canal;
- testes automatizados dessas camadas;
- WhatsApp Cloud API e controller de conversa presentes em módulos anteriores;
- AI Orchestrator separado, determinístico e com ferramentas simuladas;
- base separada de Remote Agent com allowlist e modos seguros documentados.

O novo `diagnostic_engine` opera localmente e não chama WhatsApp, banco, API HTTP, OpenAI, Docker ou Remote Agent.

## Princípios

- regras determinísticas, reproduzíveis e testáveis;
- menor privilégio e ausência de comandos arbitrários;
- ações de risco alto ou crítico exigem aprovação humana;
- diagnóstico não significa execução de ação;
- dados e segredos não devem aparecer em código, logs ou documentação;
- histórico de sessão preservado por snapshots e cópias defensivas;
- separação entre domínio diagnóstico, canal de conversa e execução remota;
- falhas viram resultados estruturados nas fronteiras dos engines.

## Planejado

- Memory Engine para contexto durável e governado;
- Diagnostic Planner e Action Planner;
- integração explícita do Conversation Engine com o canal WhatsApp existente;
- persistência das novas sessões diagnósticas;
- integração do diagnóstico com um Remote Agent sujeito às políticas de segurança;
- painel técnico para o novo fluxo;
- métricas, auditoria e observabilidade do diagnóstico.

## Fora do escopo atual

- execução automática de comandos pelo Diagnostic Engine;
- persistência do `DiagnosticSession`;
- uso de GPT/OpenAI/LLM no pipeline determinístico;
- acoplamento direto do Conversation Engine a WhatsApp;
- início do Memory Engine.

## Papel futuro de Codex e Remote Agent

Codex pode apoiar desenvolvimento, revisão e geração de mudanças dentro de um checkout confirmado, mas não é dependência de execução do produto. O Remote Agent existente é um subsistema separado; sua integração futura ao diagnóstico deverá usar ferramentas cadastradas, validação local e no servidor, auditoria e aprovação humana conforme o risco.

## Marcos recentes

- Sprint 4A: base da WhatsApp Cloud API.
- Sprint 4C: fundação e engines determinísticos de diagnóstico.
- Sprint 4C.6: Workflow Engine.
- Sprint 4C.7: Session Engine.
- Sprint 4C.8: Conversation Engine.
- Tag de consolidação confirmada: `sprint4c8`.
