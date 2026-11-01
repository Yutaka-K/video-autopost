@echo off
chcp 932 > nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
title お試し実行 - 動画自動投稿ツール
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo まだセットアップが終わっていません。
  echo 先に「初回セットアップ.bat」をダブルクリックしてください。
  echo.
  pause
  exit /b 1
)
echo 【お試しモード】実際には投稿せず、何が投稿されるかだけを表示します。
echo （投稿日時がまだ先のものも表示します。フォルダの移動もしません）
echo.
".venv\Scripts\python.exe" run.py run --dry-run
echo.
echo お試し実行が終わりました。内容がよければ「投稿実行.bat」で本番投稿できます。
echo.
pause
