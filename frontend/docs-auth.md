# Autenticacao do frontend

O MVP de desenvolvimento usa as chaves abaixo no `localStorage`:

- `powertec_access_token`
- `powertec_refresh_token`
- `powertec_user`

O access token tambem e espelhado em cookie `SameSite=Lax` para permitir redirecionamento antecipado via middleware do Next.js nas rotas protegidas. Em producao, a abordagem recomendada e mover a sessao para cookies `HttpOnly`, `Secure` e `SameSite`, emitidos pelo backend, evitando exposicao do token ao JavaScript do navegador.
