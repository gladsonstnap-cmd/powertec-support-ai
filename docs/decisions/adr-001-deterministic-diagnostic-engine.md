# ADR-001: Motor de diagnóstico determinístico

- Status: Accepted

## Contexto

O suporte a PDV e ERP exige decisões reproduzíveis, auditáveis e seguras. Chamadas externas ou geração probabilística tornariam testes, limites e explicações menos previsíveis nesta fase.

## Decisão

Implementar o pacote `diagnostic_engine` com regras locais, pipeline fixo, modelos estruturados e sem GPT/OpenAI, HTTP, banco ou comandos remotos.

## Consequências positivas

- resultados reproduzíveis;
- testes unitários rápidos;
- explicação clara das regras;
- superfície de segurança menor;
- funcionamento offline.

## Consequências negativas

- cobertura limitada ao vocabulário e conhecimento cadastrados;
- evolução exige manutenção explícita de regras e JSON;
- menor flexibilidade para mensagens inesperadas.

## Alternativas consideradas

- LLM como decisor principal: rejeitado nesta fase por imprevisibilidade e dependência externa.
- Regras dentro do controller de canal: rejeitado por acoplamento.
- Reutilizar diretamente o AI Orchestrator persistido: rejeitado porque possui ciclo e responsabilidades diferentes.
