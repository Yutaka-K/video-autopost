@echo off
chcp 932 > nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
title SNSにログイン - 動画自動投稿ツール
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo まだセットアップが終わっていません。
  echo 先に「初回セットアップ.bat」をダブルクリックしてください。
  echo.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" run.py login
echo.
".venv\Scripts\python.exe" run.py check
echo.
pause
