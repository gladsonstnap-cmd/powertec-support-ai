# Remote Agent Security

Modelo de confianca:

- O backend confia no agente somente quando o token Bearer bate com o hash salvo.
- O agente nao confia cegamente no backend: toda solicitacao passa por registry e policy local.
- O token completo aparece somente no registro.
- Segredos sao sanitizados antes de auditoria.

Allowlist inicial:

- `system_info`
- `disk_health`
- `network_test`
- `service_status`
- `event_logs`
- `windows_update_status`

Termos bloqueados em nomes ou argumentos:

- `powershell`
- `powershell.exe`
- `pwsh`
- `cmd`
- `cmd.exe`
- `bash`
- `sh`
- `shell`
- `script`
- `eval`
- `exec`
- `invoke-expression`
- `encodedcommand`
- `downloadstring`

Limites atuais:

- Ferramentas `high` ficam desabilitadas.
- Ferramentas desconhecidas sempre sao bloqueadas.
- Argumentos fora do schema sao bloqueados.
- Nao existe execucao arbitraria de linha de comando.
- Nao existe coleta invasiva.
