@echo off
setlocal
cd /d "%~dp0"
title CSCD WebUI - foreground mode

echo ============================================
echo   CSCD WebUI foreground startup
echo   Stop service: press Ctrl+C in this window
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 goto no_python

python --version
echo.
echo [CHECK] WebUI dependencies...
python -c "import fastapi, uvicorn, openai, pydantic" >nul 2>nul
if errorlevel 1 goto missing_deps

echo [OK] Dependencies are ready
echo.

netstat -ano | findstr /r /c:":8000 .*LISTENING" >nul 2>nul
if not errorlevel 1 goto already_running

echo [START] http://127.0.0.1:8000
echo [INFO] Uvicorn output will stay visible in this window.
echo.
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --app-dir webui\backend
if errorlevel 1 goto webui_failed

echo.
echo [INFO] WebUI stopped.
pause
exit /b 0

:already_running
echo [INFO] WebUI is already running on http://127.0.0.1:8000
echo Open http://127.0.0.1:8000/deploy in your browser.
start "" http://127.0.0.1:8000/deploy
pause
exit /b 0

:no_python
echo [ERROR] Python was not found.
echo Install Python 3.10+ and enable Add Python to PATH.
pause
exit /b 1

:missing_deps
echo [ERROR] WebUI dependencies are missing.
echo Run this command in the project directory:
echo python -m pip install fastapi uvicorn openai pydantic
pause
exit /b 1

:webui_failed
echo.
echo [ERROR] WebUI exited with an error.
echo Copy the Uvicorn error shown above and report it.
pause
exit /b 1
