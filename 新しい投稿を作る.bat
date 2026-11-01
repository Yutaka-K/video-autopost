@echo off
chcp 932 > nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
title 新しい投稿を作る - 動画自動投稿ツール
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo まだセットアップが終わっていません。
  echo 先に「初回セットアップ.bat」をダブルクリックしてください。
  echo.
  pause
  exit /b 1
)
set /p NAME=投稿の名前を入力して Enter（例: 京都旅行。空のままなら日時の名前になります）: 
if "%NAME%"=="" (
  ".venv\Scripts\python.exe" run.py new
) else (
  ".venv\Scripts\python.exe" run.py new "%NAME%"
)
if not errorlevel 1 start "" "%~dp0投稿待ち"
echo.
pause
