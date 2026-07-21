# Remote Agent Installation

Instalacao em Windows:

```powershell
cd remote-agent
.\install-agent.ps1 -BackendUrl "http://localhost:8000/api/v1" -Mode simulation -ConsoleMode
```

O instalador:

- verifica Python;
- cria ambiente virtual;
- instala dependencias locais;
- cria pasta de dados;
- grava configuracao;
- permite modo console para desenvolvimento.

Ele nao baixa executaveis desconhecidos, nao desabilita antivirus, nao altera politicas de seguranca e nao executa scripts remotos.

Rotacao de token:

1. Registre novamente o agente pelo endpoint `/api/v1/agents/register`.
2. Guarde o token retornado no arquivo de configuracao local.
3. O backend substitui o hash anterior.

Desinstalacao:

1. Pare qualquer processo local do agente.
2. Remova a pasta configurada em `$InstallDir`.
3. Revogue/remova o agente no backend quando a tela administrativa oferecer essa acao.
