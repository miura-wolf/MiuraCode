# ============================================================================
# MiuraCode - script de arranque del stack de servicios locales
# ============================================================================
# Bootea (o detiene / verifica) los dos servicios Python que acompanan a la
# extension MiuraCode. Uso:
#
#   .\scripts\stack.ps1 up        # arranca gigaxity (:8090) y atomic-ai (:8120)
#   .\scripts\stack.ps1 down      # detiene ambos servicios
#   .\scripts\stack.ps1 status    # health de cada servicio
#
# Requisitos previos (solo la primera vez, ver services/README.md):
#   - services/atomic-ai/.venv y services/gigaxity/.venv creados
#   - services/atomic-ai/.env y services/gigaxity/.env configurados
#
# NOTA: este script NO arranca llama.cpp (8080/8081) ni las APIs de busqueda.
# Para el stack completo ver services/README.md (mapa de puertos).
# ============================================================================

param(
    [Parameter(Position = 0)]
    [ValidateSet("up", "down", "status")]
    [string]$Action = "status"
)

$ErrorActionPreference = "Stop"

# Rutas absolutas (independientes del cwd del llamador)
$RepoRoot = $PSScriptRoot | Split-Path -Parent
$AtomicAi = Join-Path $RepoRoot "services\atomic-ai"
$Gigaxity = Join-Path $RepoRoot "services\gigaxity"

$Services = @(
    @{
        Name    = "gigaxity"
        Dir     = $Gigaxity
        Python  = Join-Path $Gigaxity ".venv\Scripts\python.exe"
        # python -m src.main arranca uvicorn leyendo RESEARCH_HOST/RESEARCH_PORT
        # del .env (single source of truth del puerto)
        Args    = @("-m", "src.main")
        Health  = "http://127.0.0.1:8090/api/v1/health"
        Title   = "Gigaxity Deep Research (web research)"
    },
    @{
        Name    = "atomic-ai"
        Dir     = $AtomicAi
        Python  = Join-Path $AtomicAi ".venv\Scripts\python.exe"
        Args    = @("run.py")
        Health  = "http://127.0.0.1:8120/healthz"
        Title   = "Atomic AI (orquestador proxy :8120)"
    }
)

function Test-ServiceHealth([string]$Url) {
    try {
        $null = Invoke-WebRequest -Uri $Url -TimeoutSec 3 -UseBasicParsing
        return $true
    }
    catch { return $false }
}

function Wait-ServiceHealthy([string]$Url, [string]$Name, [int]$TimeoutSec = 30) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-ServiceHealth $Url) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

switch ($Action) {

    "up" {
        $failed = @()
        foreach ($svc in $Services) {
            if (-not (Test-Path $svc.Python)) {
                Write-Host ("[SKIP] {0}: no existe {1} - crea el venv (services/README.md)" -f $svc.Name, $svc.Python) -ForegroundColor Yellow
                $failed += $svc.Name
                continue
            }
            if (Test-ServiceHealth $svc.Health) {
                Write-Host ("[OK]   {0} ya esta corriendo" -f $svc.Name) -ForegroundColor Green
                continue
            }
            Write-Host ("[UP]   {0} - arrancando..." -f $svc.Name) -ForegroundColor Cyan
            $p = Start-Process -FilePath $svc.Python -ArgumentList $svc.Args -WorkingDirectory $svc.Dir `
                -WindowStyle Hidden -RedirectStandardOutput (Join-Path $svc.Dir "server.out.log") `
                -RedirectStandardError (Join-Path $svc.Dir "server.err.log") -PassThru
            if (Wait-ServiceHealthy $svc.Health $svc.Name) {
                Write-Host ("[OK]   {0} saludable (pid {1})" -f $svc.Name, $p.Id) -ForegroundColor Green
            }
            else {
                Write-Host ("[FAIL] {0} no respondio en 30s - mira {1}" -f $svc.Name, (Join-Path $svc.Dir "server.err.log")) -ForegroundColor Red
                $failed += $svc.Name
            }
        }
        if ($failed.Count -gt 0) {
            Write-Host ("`nServicios con problemas: {0}" -f ($failed -join ", ")) -ForegroundColor Red
            exit 1
        }
        Write-Host "`nStack listo: MiuraCode -> atomic-ai :8120 -> {RAG local, gigaxity :8090} -> upstream" -ForegroundColor Green
    }

    "down" {
        foreach ($svc in $Services) {
            if (-not (Test-ServiceHealth $svc.Health)) {
                Write-Host ("[DOWN] {0} no esta corriendo" -f $svc.Name) -ForegroundColor DarkGray
                continue
            }
            # Mata el proceso que escucha el puerto del servicio
            $port = if ($svc.Name -eq "gigaxity") { 8090 } else { 8120 }
            $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
            $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
            foreach ($procId in $pids) {
                try {
                    Stop-Process -Id $procId -Force -ErrorAction Stop
                    Write-Host ("[DOWN] {0} detenido (pid {1})" -f $svc.Name, $procId) -ForegroundColor Green
                }
                catch {
                    Write-Host ("[DOWN] {0}: no se pudo detener pid {1} ({2})" -f $svc.Name, $procId, $_.Exception.Message) -ForegroundColor Red
                }
            }
        }
    }

    "status" {
        foreach ($svc in $Services) {
            $ok = Test-ServiceHealth $svc.Health
            $color = if ($ok) { "Green" } else { "Red" }
            $state = if ($ok) { "SALUDABLE" } else { "CAIDO" }
            Write-Host ("[{0}] {1}: {2} - {3}" -f $state, $svc.Name, $svc.Health, $svc.Title) -ForegroundColor $color
        }
    }
}