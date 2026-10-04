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
echo   国内期货全量数据终端 - 一键更新数据
echo ==========================================================
echo   请选择采集模式：
echo     [1] 全量：行情 + 分类 + 加权 + 资讯 + 龙虎榜 + 核心K线 + 加权日K
echo               首次使用，或需要龙虎榜 / 离线K线 / 加权日K时选此项（约 1~2 分钟）
echo     [2] 快速：仅行情 + 分类 + 加权 + 资讯（约 30 秒）
echo               已有龙虎榜 / K线快照会被保留，不会被清空
echo.
set "MODE=1"
set /p MODE=输入 1 或 2 后回车（直接回车 = 1）: 
set "ARGS="
if "%MODE%"=="2" set "ARGS=--quick"
echo.

echo [1/2] 正在采集数据 ...
%PY% 采集期货数据.py %ARGS%
if errorlevel 1 (
  echo.
  echo [错误] 数据采集失败，已中止。请检查网络后重试。
  pause
  exit /b 1
)

echo.
echo [2/2] 正在打包单文件页面 ...
%PY% 生成终端页面.py
if errorlevel 1 (
  echo.
  echo [错误] 打包失败，已中止。
  pause
  exit /b 1
)

echo.
echo ==========================================================
echo   更新完成！请到浏览器刷新终端页面（Ctrl+F5 强制刷新）。
echo ==========================================================
echo.
pause
