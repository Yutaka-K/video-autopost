@echo off
chcp 932 > nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
title 投稿実行 - 動画自動投稿ツール
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo まだセットアップが終わっていません。
  echo 先に「初回セットアップ.bat」をダブルクリックしてください。
  echo.
  pause
  exit /b 1
)
echo 「投稿待ち」フォルダの中で、投稿日時になったものを投稿します。
echo （動画のアップロードには時間がかかることがあります。このまま待ってください）
echo.
".venv\Scripts\python.exe" run.py run
set RC=%errorlevel%
echo.
if not "%RC%"=="0" (
  echo うまくいかなかった投稿があります。上のメッセージを確認してください。
  echo 失敗したSNSは、次回の実行で自動的に再挑戦します。
) else (
  echo 終わりました。
)
echo.
pause
exit /b %RC%
