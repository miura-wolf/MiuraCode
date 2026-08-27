@echo off
cd /d "%~dp0"

set "VENV_PYTHON=.venv\Scripts\python.exe"
if exist "%VENV_PYTHON%" (
    echo [run.bat] Usando entorno virtual .venv...
    "%VENV_PYTHON%" run.py
) else (
    echo [run.bat] .venv no encontrado, usando Python del sistema...
    python run.py
)

echo.
echo [run.bat] Servidor detenido.
pause
