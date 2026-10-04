@echo off
cd /d "%~dp0"

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY ( where py >nul 2>nul && set "PY=py" )
if not defined PY ( if exist "\Python314\python.exe" set "PY=\Python314\python.exe" )
if not defined PY ( if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe" )
if not defined PY ( if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe" )
if not defined PY ( if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe" )
if not defined PY (
  echo.
  echo [错误] 未检测到 Python，请先安装 Python 3.9 及以上版本，
  echo        安装时务必勾选 "Add Python to PATH"。
  echo        下载地址：https://www.python.org/downloads/
  echo.
  pause
  exit /b 1
)

echo.
echo ==========================================================
echo   国内期货全量数据终端 - 本地服务
echo   默认地址：http://127.0.0.1:8907/期货数据终端.html
echo   （浏览器会自动打开；关闭本窗口即停止服务）
echo ==========================================================
echo.
%PY% start_server.py
pause
