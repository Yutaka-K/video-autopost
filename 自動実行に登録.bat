@echo off
chcp 932 > nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
title 自動実行に登録 - 動画自動投稿ツール
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo まだセットアップが終わっていません。
  echo 先に「初回セットアップ.bat」をダブルクリックしてください。
  echo.
  pause
  exit /b 1
)
echo Windows のタスクスケジューラに、このツールを自動で動かす設定を登録します。
echo （パソコンが起動していてログインしているときに実行されます）
echo.
".venv\Scripts\python.exe" run.py register-task
echo.
pause
