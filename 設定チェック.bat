@echo off
chcp 932 > nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
title 設定チェック - 動画自動投稿ツール
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo まだセットアップが終わっていません。
  echo 先に「初回セットアップ.bat」をダブルクリックしてください。
  echo.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" run.py check
echo.
pause
