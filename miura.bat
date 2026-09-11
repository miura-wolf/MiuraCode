@echo off
setlocal
title miura - chat
cd /d "%~dp0"

REM Comprueba que el proxy Atomic AI este vivo (puerto 8120)
curl -s -o nul -m 3 http://127.0.0.1:8120/v1/models
if errorlevel 1 (
    echo [miura] Proxy caido. Levantandolo en otra ventana...
    start "atomic-ai proxy" cmd /k "services\atomic-ai\run.bat"
    echo [miura] Esperando 8 segundos a que arranque...
    timeout /t 8 /nobreak >nul
)

REM Abre la TUI (o pasa subcomandos: miura.bat models / sessions / config)
node "apps\miura\dist\index.js" %*
if errorlevel 1 pause
endlocal
