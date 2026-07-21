param(
  [string]$InstallDir = "$env:ProgramData\PowerTecRemoteAgent",
  [string]$BackendUrl = "http://localhost:8000/api/v1",
  [ValidateSet("simulation", "local_safe")]
  [string]$Mode = "simulation",
  [switch]$ConsoleMode
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
  Write-Host "[PowerTec Agent] $Message"
}

Write-Step "Verificando Python"
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
  throw "Python nao encontrado. Instale Python 3.11+ antes de continuar."
}

Write-Step "Criando diretorio de instalacao"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

Write-Step "Criando ambiente virtual"
python -m venv "$InstallDir\.venv"

Write-Step "Instalando dependencias locais"
& "$InstallDir\.venv\Scripts\python.exe" -m pip install --upgrade pip
& "$InstallDir\.venv\Scripts\python.exe" -m pip install -r "$PSScriptRoot\requirements.txt"

Write-Step "Gravando configuracao"
@"
POWERTEC_AGENT_BACKEND_URL=$BackendUrl
POWERTEC_AGENT_MODE=$Mode
"@ | Set-Content -Encoding UTF8 -Path "$InstallDir\.env"

if ($ConsoleMode) {
  Write-Step "Modo console solicitado. Execute agent/main.py pelo ambiente virtual para desenvolvimento."
} else {
  Write-Step "Instalacao concluida. Registro como servico Windows deve ser habilitado manualmente apos validacao."
}
