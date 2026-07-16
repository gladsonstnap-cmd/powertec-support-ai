# Politica de Seguranca

## Segredos

Nao exponha chaves, tokens ou credenciais no frontend. Use variaveis de ambiente e mantenha `.env` fora do controle de versao.

A senha do usuario demonstrativo deve ser definida em `DEMO_ADMIN_PASSWORD`; nao ha senha fixa no codigo.

## Autorizacoes

A Etapa 1 nao executa diagnosticos remotos nem comandos de alteracao em maquinas de clientes.

## Dados sensiveis

Use somente dados ficticios em desenvolvimento. Antes das etapas de IA e WhatsApp, adicionar sanitizacao automatica de CPF, CNPJ, e-mail, telefone, tokens, senhas e strings de conexao.

## Isolamento por tenant

As rotas protegidas usam o tenant do token JWT. O backend nao confia em `tenant_id` enviado pelo frontend para criar registros.
