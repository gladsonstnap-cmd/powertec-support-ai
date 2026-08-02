# Roadmap

Este roadmap não define datas. Ele separa entregas confirmadas de integrações e capacidades futuras.

| Status | Entrega | Observação |
| --- | --- | --- |
| CONCLUÍDO | Fundação do Diagnostic Engine | Modelos, normalização e classificadores determinísticos. |
| CONCLUÍDO | Knowledge Base | Incidentes locais validados e carregados de JSON. |
| CONCLUÍDO | Hypothesis Engine | Geração, pontuação e ordenação determinística. |
| CONCLUÍDO | Evidence Engine | Extração e aplicação idempotente de evidências. |
| CONCLUÍDO | Decision Engine | Próximo passo seguro, confirmação, conclusão ou escalada. |
| CONCLUÍDO | Workflow Engine | Orquestração do pipeline e captura de falhas. |
| CONCLUÍDO | Session Engine | Estado em memória entre mensagens, sem estado global. |
| CONCLUÍDO | Conversation Engine | Adaptação de mensagens e comandos ao Session Engine. |
| PRÓXIMO | Memory Engine | Definir memória durável, escopo, retenção e privacidade. |
| PLANEJADO | Diagnostic Planner | Planejar verificações seguras sem executar comandos. |
| PLANEJADO | Action Planner | Propor ações sujeitas a risco, confirmação e auditoria. |
| PLANEJADO | Integração com WhatsApp | Ligar o Conversation Engine ao canal já existente. |
| PLANEJADO | Persistência de sessões | Armazenar snapshots com isolamento por tenant. |
| FUTURO | Integração com Remote Agent seguro | Conectar o diagnóstico à base de agente existente após revisão das políticas. |
| FUTURO | Painel técnico | Expor estado, evidências, decisão e auditoria aos técnicos. |
| FUTURO | Métricas e auditoria | Medir qualidade, segurança, escaladas e resultados. |

## Critérios permanentes

- não iniciar uma etapa sem autorização explícita;
- validar segurança antes de qualquer execução real;
- manter diagnóstico e canal desacoplados;
- não apresentar capacidade planejada como implementada.
