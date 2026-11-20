@echo off
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 未检测到 Python，请先安装 Python 3.9 及以上版本，安装时勾选 "Add python.exe to PATH"。
  pause
  exit /b 1
)

python -c "import flask, requests, bs4, Crypto, cryptography" >nul 2>nul
if errorlevel 1 (
  echo 首次运行，正在安装依赖，请稍候...
  python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
)

python server.py
pause
