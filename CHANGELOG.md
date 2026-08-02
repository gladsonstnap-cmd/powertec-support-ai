# Changelog

Todas as mudanças relevantes deste projeto serão documentadas neste arquivo. O formato é inspirado em [Keep a Changelog](https://keepachangelog.com/), sem atribuir números de versão não confirmados.

## [Unreleased]

### Added

- documentação consolidada de contexto, arquitetura, roadmap, desenvolvimento e regras para agentes;
- ADRs do motor determinístico, Knowledge Base JSON, sessões imutáveis e desacoplamento do canal.

### Marcos confirmados

- WhatsApp Cloud API com provider configurável, webhook, normalização e idempotência;
- automação inicial do webhook e continuidade de conversa;
- controller avançado de conversação no WhatsApp;
- fundação determinística do Diagnostic Engine;
- Knowledge Base em JSON;
- Hypothesis Engine;
- Evidence Engine;
- Decision Engine;
- Workflow Engine;
- Session Engine em memória;
- Conversation Engine desacoplado do WhatsApp.

### Notas

- os marcos foram confirmados pelo código, documentação e histórico Git;
- o Diagnostic Engine não executa comandos e não está integrado automaticamente a WhatsApp ou Remote Agent;
- nenhuma versão adicional é inferida neste changelog.
