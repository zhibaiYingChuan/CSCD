@echo off
chcp 65001 >nul
REM ============================================================
REM  C-S-C-D 一键启动（Windows 双击运行）
REM  作用：检查 Python -> 装依赖 -> 检测端点(与AI工具共用，已配则跳过)
REM       -> 后台自运行 WebUI(8000) + REST API(8001) -> 打开部署向导 /deploy
REM  特点：
REM    1. 服务用 pythonw 后台运行，不弹窗口、不占用终端
REM    2. 模型端点自动检测（AI 工具已配置则无需再配）
REM    3. 启动前检查端口占用（避免"拒绝连接"）
REM    4. 服务日志写入 .cscd/logs/（失败时有据可查）
REM  停止服务：双击 stop.bat
REM ============================================================
setlocal

echo.
echo  ============================================
echo   C-S-C-D 一键启动向导
echo  ============================================
echo.

REM ---- 1. 检查 Python ----
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python。请先安装 Python 3.10+ 并勾选 "Add to PATH"。
    pause
    exit /b 1
)
echo [OK] Python: 
python --version

REM ---- 进入项目目录 ----
cd /d "%~dp0"

REM ---- 1.5 检查端口占用（避免服务绑定失败导致"拒绝连接"）----
echo.
echo [0/3] 检查端口...
for %%P in (8000 8001) do (
    netstat -aon | findstr ":%P " | findstr "LISTENING" >nul 2>nul
    if not errorlevel 1 (
        echo [错误] 端口 %P 已被占用。
        echo        Please double-click stop.bat to stop the old service,
        echo        or close the program occupying the port and try again.
        echo.
        exit /b 1
    )
)

REM ---- 2. 检查依赖 ----
echo.
echo [1/3] 检查依赖...
python -c "import fastapi, uvicorn, openai, pydantic" 2>nul
if errorlevel 1 (
    echo       安装依赖中...
    python -m pip install --disable-pip-version-check -q fastapi "uvicorn[standard]" openai pydantic
    if errorlevel 1 (
        echo [错误] 依赖安装失败。请检查网络或手动执行:
        echo       python -m pip install fastapi uvicorn openai pydantic
        pause
        exit /b 1
    )
) else (
    echo       [OK] 依赖已就绪
)

REM ---- 3. 检测端点（AI 工具已配置则跳过引导） ----
echo.
echo [2/3] 检测模型端点...
if defined LLM_API_URL if defined LLM_API_KEY if defined LLM_MODEL goto :endpoint_ok
if defined OPENAI_BASE_URL if defined OPENAI_API_KEY if defined OPENAI_MODEL goto :endpoint_ok

echo       未检测到完整端点配置（AI 工具未配置时需手动填写）。
echo       你也可以先启动服务，在部署向导 /deploy 页面中填写，效果相同。
echo.
set /p "LLM_API_URL=  请输入模型 API 地址 (如 https://api.deepseek.com): "
set /p "LLM_API_KEY=  请输入你的 API Key: "
set /p "LLM_MODEL=    请输入模型名 (如 gpt-4o/deepseek-chat): "
setx LLM_API_URL "%LLM_API_URL%" >nul
setx LLM_API_KEY "%LLM_API_KEY%" >nul
setx LLM_MODEL "%LLM_MODEL%" >nul
echo       [OK] 端点已保存

:endpoint_ok
echo       [OK] 模型端点已就绪

REM ---- 4. 后台自运行服务（pythonw 无窗口 + 日志落盘） ----
echo.
echo [3/3] 启动服务（后台自运行，关闭本窗口不影响）...
if not exist ".cscd\logs" mkdir ".cscd\logs"

where pythonw >nul 2>nul
set "PYW=python"
if not errorlevel 1 set "PYW=pythonw"

echo       启动 WebUI (http://127.0.0.1:8000)
start "" %PYW% -m uvicorn main:app --host 127.0.0.1 --port 8000 --app-dir webui\backend >> .cscd\logs\webui.log 2>&1
timeout /t 4 >nul
echo       启动 REST API (http://127.0.0.1:8001)
start "" %PYW% -m uvicorn api_server:app --host 127.0.0.1 --port 8001 --app-dir . >> .cscd\logs\api.log 2>&1
timeout /t 4 >nul

REM ---- 4.5 验证服务是否真的启动成功 ----
echo       验证服务状态...
netstat -aon | findstr ":8000 " | findstr "LISTENING" >nul 2>nul
if errorlevel 1 (
    echo [错误] WebUI 启动失败！请查看日志: .cscd\logs\webui.log
    echo       常见原因：端口被占用 / 依赖缺失 / Python 版本不符。
    type ".cscd\logs\webui.log" 2>nul | findstr /i "error exception" 
    echo.
    echo 请按任意键查看错误详情后关闭本窗口。
    pause
    exit /b 1
)
echo       [OK] WebUI 已就绪

REM ---- 5. 打开部署向导（第一入口） ----
echo.
echo  ============================================
echo   部署完成！正在打开部署向导...
echo   部署向导 : http://127.0.0.1:8000/deploy
echo   WebUI    : http://127.0.0.1:8000
echo   REST API : http://127.0.0.1:8001/health
echo  ============================================
start http://127.0.0.1:8000/deploy
echo.
echo 服务已后台自运行，本窗口可以关闭。
echo 停止服务请双击 stop.bat，或执行 taskkill /IM pythonw.exe /F
echo.
pause
