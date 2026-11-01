@echo off
chcp 932 > nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
title 初回セットアップ - 動画自動投稿ツール
echo ============================================================
echo   動画自動投稿ツール 初回セットアップ
echo   必要なライブラリを自動でインストールします（数分かかります）
echo ============================================================
echo.

rem ---- Python を探す ----
set "PY="
py -3 --version > nul 2>&1 && set "PY=py -3"
if not defined PY (
  python --version > nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo [エラー] Python が見つかりません。
  echo.
  echo  1. https://www.python.org/downloads/ を開いて Python をダウンロード
  echo  2. インストール画面の一番下「Add python.exe to PATH」に必ずチェック
  echo  3. 「Install Now」を押してインストール
  echo  4. インストールが終わったら、この .bat をもう一度ダブルクリック
  echo.
  echo 詳しくは README.md を見てください。
  goto :end_error
)

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
  echo [エラー] Python が古すぎます。3.10 以上をインストールしてください。
  %PY% --version
  goto :end_error
)
echo Python が見つかりました:
%PY% --version
echo.

rem ---- このツール専用の Python 環境（.venv）を作る ----
if not exist ".venv\Scripts\python.exe" (
  echo このツール専用の環境を作っています…
  %PY% -m venv .venv
  if errorlevel 1 (
    echo [エラー] 環境を作れませんでした。
    goto :end_error
  )
)

echo ライブラリをインストールしています…
".venv\Scripts\python.exe" -m pip install --upgrade pip --disable-pip-version-check -q
".venv\Scripts\python.exe" -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 (
  echo.
  echo [エラー] ライブラリのインストールに失敗しました。
  echo インターネットにつながっているか確認して、もう一度実行してください。
  goto :end_error
)
echo.

rem ---- 設定ファイル（.env）を用意する ----
if not exist ".env" (
  copy ".env.example" ".env" > nul
  echo 設定ファイル「.env」を作りました。メモ帳で開いて、APIキーなどを書いてください。
) else (
  echo 設定ファイル「.env」はすでにあるので、そのまま使います。
)
echo.

".venv\Scripts\python.exe" run.py check
echo.
echo ============================================================
echo   セットアップが完了しました！
echo   次は SETUP.md を見ながら、各SNSのキーを .env に書いてください。
echo ============================================================
echo.
pause
exit /b 0

:end_error
echo.
pause
exit /b 1
