# Remote Agent Architecture

O Remote Agent Seguro fica em `remote-agent/` e roda separado do backend.

Fluxo:

1. O agente cria identidade local persistente com UUID, hostname, sistema operacional, versao e chave local.
2. O agente registra no backend e recebe um token exibido somente uma vez.
3. O backend salva apenas o hash do token.
4. O operador cria comandos escolhendo ferramentas cadastradas na allowlist.
5. O servidor valida ferramenta, argumentos e risco.
6. O agente valida novamente a ferramenta e executa apenas implementacoes internas.
7. O resultado estruturado retorna ao backend.
8. Cada etapa grava auditoria.

Modos:

- `simulation`: nao coleta dados reais alem da identidade basica e usa respostas simuladas.
- `local_safe`: permite coletores locais seguros e somente leitura.

Nao ha controle remoto de tela, comandos livres, RAT, keylogger, webcam, microfone ou captura de senha.
