# ADR-004: Conversation Engine independente do WhatsApp

- Status: Accepted

## Contexto

O repositório já possui integração WhatsApp, mas a lógica diagnóstica deve poder operar e ser testada sem rede, credenciais, payloads da Meta ou dependência de canal.

## Decisão

Manter `DiagnosticConversationEngine` no domínio diagnóstico. Ele recebe modelos próprios, reconhece comandos e delega ao Session Engine, sem importar ou chamar módulos WhatsApp.

## Consequências positivas

- testes locais e determinísticos;
- reutilização futura em outros canais;
- menor exposição de credenciais e rede;
- regras diagnósticas independentes do formato do webhook.

## Consequências negativas

- será necessária uma camada adaptadora para integração real;
- estado do canal e estado diagnóstico precisam de correlação explícita;
- respostas e erros terão de ser convertidos para cada provider.

## Alternativas consideradas

- chamar o diagnóstico diretamente no webhook: rejeitado por forte acoplamento.
- colocar comandos no controller WhatsApp: rejeitado porque impediria reutilização.
- substituir o controller existente: rejeitado por estar fora do escopo e arriscar regressões.
