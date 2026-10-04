@echo off
chcp 936 >nul
title 国内期货数据终端 - 打包 EXE
cd /d "%~dp0"

echo ==============================================================
echo   国内期货全量数据终端 - 将启动器打包为单文件 exe
echo   （需要已安装 Python 3.9+ 与 PyInstaller：pip install pyinstaller）
echo ==============================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [!] 未找到 python 命令，请先安装 Python 并勾选 Add to PATH。
  pause
  exit /b 1
)

python -m PyInstaller --noconfirm --onefile --windowed ^
  --name "国内期货数据终端" ^
  --icon "assets\logo.ico" ^
  --add-data "期货数据终端.html;." ^
  --add-data "assets\logo.png;assets" ^
  --add-data "assets\logo.ico;assets" ^
  --version-file version.txt ^
  "启动器.py"

if errorlevel 1 (
  echo [!] 打包失败，请检查上方错误信息。
  pause
  exit /b 1
)

copy /y "dist\国内期货数据终端.exe" "国内期货数据终端.exe" >nul
echo.
echo [OK] 已生成：国内期货数据终端.exe（双击即可启动数据终端）
pause
