param(
    [int]$DaemonTimeoutSeconds = 20,
    [int]$CommandTimeoutSeconds = 900,
    [int]$ServiceStartupTimeoutSeconds = 240
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)

    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Failure {
    param(
        [string]$Title,
        [string]$Detail
    )

    Write-Host ""
    Write-Host $Title -ForegroundColor Red

    if (-not [string]::IsNullOrWhiteSpace($Detail)) {
        Write-Host $Detail -ForegroundColor Red
    }
}

function Test-DockerDaemonQuick {
    try {
        $serverVersion = & docker version --format '{{.Server.Version}}' 2>$null
        $serverVersionText = ($serverVersion | Out-String).Trim()

        return (
            $LASTEXITCODE -eq 0 -and
            -not [string]::IsNullOrWhiteSpace($serverVersionText)
        )
    }
    catch {
        return $false
    }
}

function Assert-DockerDaemon {
    try {
        $serverVersion = & docker version --format '{{.Server.Version}}' 2>&1
        $serverVersionText = ($serverVersion | Out-String).Trim()

        if ($LASTEXITCODE -ne 0) {
            throw $serverVersionText
        }

        if ([string]::IsNullOrWhiteSpace($serverVersionText)) {
            throw "Docker did not return the server version."
        }

        Write-Host "Docker daemon available. Server: $serverVersionText" -ForegroundColor Green
    }
    catch {
        Write-Failure `
            "Docker daemon unavailable or not responding." `
            "$($_.Exception.Message)"

        Write-Host ""
        Write-Host "Check Docker Desktop, WSL, Docker context, DNS and proxy settings."
        exit 2
    }
}

function Invoke-NativeCommand {
    param(
        [string]$FileName,
        [string[]]$Arguments,
        [int]$TimeoutSeconds,
        [switch]$MonitorDockerDaemon,
        [switch]$Quiet
    )

    $argumentLine = $Arguments -join " "

    $processInfo = New-Object System.Diagnostics.ProcessStartInfo
    $processInfo.FileName = $FileName
    $processInfo.Arguments = $argumentLine
    $processInfo.UseShellExecute = $false
    $processInfo.CreateNoWindow = $true
    $processInfo.RedirectStandardOutput = $true
    $processInfo.RedirectStandardError = $true

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $processInfo

    try {
        if (-not $process.Start()) {
            throw "Could not start command: $FileName $argumentLine"
        }

        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()

        $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)

        while (-not $process.HasExited) {
            Start-Sleep -Milliseconds 500

            if ([DateTime]::UtcNow -gt $deadline) {
                try {
                    $process.Kill()
                }
                catch {
                }

                throw "Command timed out after ${TimeoutSeconds}s: $FileName $argumentLine"
            }

            if ($MonitorDockerDaemon -and -not (Test-DockerDaemonQuick)) {
                try {
                    $process.Kill()
                }
                catch {
                }

                throw "Docker daemon became unavailable while running: $FileName $argumentLine"
            }
        }

        $process.WaitForExit()

        $stdout = $stdoutTask.Result
        $stderr = $stderrTask.Result
        $exitCode = $process.ExitCode

        if (-not $Quiet) {
            if (-not [string]::IsNullOrWhiteSpace($stdout)) {
                Write-Host $stdout.TrimEnd()
            }

            if (-not [string]::IsNullOrWhiteSpace($stderr)) {
                Write-Host $stderr.TrimEnd() -ForegroundColor Yellow
            }
        }

        if ($exitCode -ne 0) {
            $detail = ""

            if (-not [string]::IsNullOrWhiteSpace($stderr)) {
                $detail = $stderr.Trim()
            }
            elseif (-not [string]::IsNullOrWhiteSpace($stdout)) {
                $detail = $stdout.Trim()
            }

            throw "Command failed with exit code ${exitCode}: $FileName $argumentLine`n$detail"
        }

        return $stdout
    }
    finally {
        $process.Dispose()
    }
}

function Invoke-DockerCompose {
    param(
        [string]$Description,
        [string[]]$Arguments
    )

    Assert-DockerDaemon
    Write-Step $Description

    try {
        Invoke-NativeCommand `
            -FileName "docker" `
            -Arguments (@("compose") + $Arguments) `
            -TimeoutSeconds $CommandTimeoutSeconds `
            -MonitorDockerDaemon | Out-Null
    }
    catch {
        Write-Failure `
            "Failure during '$Description'." `
            "$($_.Exception.Message)"

        exit 3
    }
}

function Wait-ForRequiredServices {
    param(
        [string[]]$Services,
        [int]$TimeoutSeconds
    )

    Write-Step "Waiting for required services"

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)

    while ($true) {
        Assert-DockerDaemon

        $runningOutput = & docker compose ps --status running --services 2>$null

        if ($LASTEXITCODE -ne 0) {
            Write-Failure `
                "Could not read running Docker Compose services." `
                (($runningOutput | Out-String).Trim())

            exit 4
        }

        $runningServices = @(
            $runningOutput |
            ForEach-Object { $_.Trim() } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
        )

        $missingServices = @(
            $Services |
            Where-Object { $runningServices -notcontains $_ }
        )

        if ($missingServices.Count -eq 0) {
            Write-Host "Required services are running." -ForegroundColor Green
            return
        }

        if ([DateTime]::UtcNow -gt $deadline) {
            Write-Failure `
                "Required services did not start within ${TimeoutSeconds}s." `
                "Missing services: $($missingServices -join ', ')"

            Write-Host ""
            Write-Host "Current container status:" -ForegroundColor Yellow
            & docker compose ps -a

            Write-Host ""
            Write-Host "Recent logs:" -ForegroundColor Yellow
            & docker compose logs --tail=100 backend frontend postgres redis

            exit 4
        }

        Write-Host "Waiting for: $($missingServices -join ', ')" -ForegroundColor DarkYellow
        Start-Sleep -Seconds 5
    }
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $repoRoot

# Remove conflicting Docker environment variables.
Remove-Item Env:DOCKER_CONFIG -ErrorAction SilentlyContinue
Remove-Item Env:DOCKER_HOST -ErrorAction SilentlyContinue
Remove-Item Env:DOCKER_CONTEXT -ErrorAction SilentlyContinue

# Use Docker Desktop Linux engine.
$env:DOCKER_CONTEXT = "desktop-linux"

Write-Host ""
Write-Host "PowerTec Support AI - Docker validation" -ForegroundColor Green
Write-Host "Repository: $repoRoot"
Write-Host "Docker context: $env:DOCKER_CONTEXT" -ForegroundColor DarkGray

Assert-DockerDaemon

Invoke-DockerCompose `
    "Checking Docker Compose configuration" `
    @("--profile", "jobs", "config", "--quiet")

Invoke-DockerCompose `
    "Listing all containers before startup" `
    @("ps", "-a")

Invoke-DockerCompose `
    "Starting required services" `
    @(
        "up",
        "-d",
        "postgres",
        "redis",
        "minio",
        "backend",
        "frontend",
        "celery-worker",
        "celery-beat"
    )

Wait-ForRequiredServices `
    -Services @(
        "postgres",
        "redis",
        "backend",
        "frontend"
    ) `
    -TimeoutSeconds $ServiceStartupTimeoutSeconds

Invoke-DockerCompose `
    "Listing running containers" `
    @("ps")

Invoke-DockerCompose `
    "Running migrations once" `
    @(
        "--profile",
        "jobs",
        "run",
        "--rm",
        "migrate"
    )

Invoke-DockerCompose `
    "Running development seed once" `
    @(
        "--profile",
        "jobs",
        "run",
        "--rm",
        "seed"
    )

Invoke-DockerCompose `
    "Running backend tests" `
    @(
        "exec",
        "-T",
        "backend",
        "python",
        "-m",
        "pytest",
        "-q"
    )

Invoke-DockerCompose `
    "Running frontend tests" `
    @(
        "exec",
        "-T",
        "frontend",
        "pnpm",
        "test"
    )

Invoke-DockerCompose `
    "Running frontend TypeScript validation" `
    @(
        "exec",
        "-T",
        "frontend",
        "pnpm",
        "exec",
        "tsc",
        "--noEmit"
    )

Invoke-DockerCompose `
    "Showing final container status" `
    @("ps", "-a")

Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host "VALIDATION COMPLETED SUCCESSFULLY" -ForegroundColor Green
Write-Host "=========================================" -ForegroundColor Green