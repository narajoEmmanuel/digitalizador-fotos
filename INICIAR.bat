@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py -3"
) else (
    where python >nul 2>nul
    if %errorlevel% neq 0 (
        echo Necesitas instalar Python 3.10 o superior desde https://www.python.org/downloads/
        echo Marca la casilla "Add python.exe to PATH" durante la instalacion.
        pause
        exit /b 1
    )
    set "PY=python"
)
if not exist ".venv\Scripts\python.exe" (
    echo Preparando el programa por primera vez...
    %PY% -m venv .venv
    if errorlevel 1 goto error
)
if not exist ".venv\instalado_v13.ok" (
    echo Instalando componentes necesarios. Solo ocurre la primera vez...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto error
    echo ok>".venv\instalado_v13.ok"
)
".venv\Scripts\python.exe" digitalizador.py
if errorlevel 1 goto error
exit /b 0
:error
echo.
echo No se pudo iniciar. Revisa la conexion a Internet durante la primera instalacion.
pause
exit /b 1
