@echo off
chcp 65001 >nul
REM ============================================================
REM  C-S-C-D 停止服务（Windows 双击运行）
REM  作用：停止后台运行的 WebUI(8000) + REST API(8001)
REM  注意：本脚本会终止所有占用 8000/8001 端口的进程，请确认无其他应用使用这些端口
REM  Note: This script terminates all processes occupying ports 8000/8001.
REM  Please ensure no other applications are using these ports.
REM ============================================================
echo.
echo  正在停止 C-S-C-D 服务...
echo.

REM 停止占用 8000 / 8001 端口的进程
for %%P in (8000 8001) do (
    for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":%%P" ^| findstr "LISTENING"') do (
        taskkill /F /PID %%a >nul 2>nul
        echo  [已停止] 端口 %%P 的进程 PID %%a
    )
)

echo.
echo  C-S-C-D 服务已停止。
echo.
pause
