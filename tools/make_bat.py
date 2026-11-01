"""(開発者用) .bat ファイルを Shift_JIS(CP932) + CRLF で書き出すスクリプト。

.bat に日本語を書くと、UTF-8 のままでは Windows のコマンドプロンプトで文字化け・誤動作することがあるため、
このスクリプトでまとめて作っています。内容を変えたいときはここを編集して
    python tools/make_bat.py
を実行してください。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HEADER = r"""@echo off
chcp 932 > nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
"""

CHECK_VENV = r"""if not exist ".venv\Scripts\python.exe" (
  echo.
  echo まだセットアップが終わっていません。
  echo 先に「初回セットアップ.bat」をダブルクリックしてください。
  echo.
  pause
  exit /b 1
)
"""

BATS = {}

BATS["初回セットアップ.bat"] = HEADER + r"""title 初回セットアップ - 動画自動投稿ツール
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
"""

BATS["投稿実行.bat"] = HEADER + r"""title 投稿実行 - 動画自動投稿ツール
""" + CHECK_VENV + r"""echo 「投稿待ち」フォルダの中で、投稿日時になったものを投稿します。
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
"""

BATS["お試し実行.bat"] = HEADER + r"""title お試し実行 - 動画自動投稿ツール
""" + CHECK_VENV + r"""echo 【お試しモード】実際には投稿せず、何が投稿されるかだけを表示します。
echo （投稿日時がまだ先のものも表示します。フォルダの移動もしません）
echo.
".venv\Scripts\python.exe" run.py run --dry-run
echo.
echo お試し実行が終わりました。内容がよければ「投稿実行.bat」で本番投稿できます。
echo.
pause
"""

BATS["自動実行に登録.bat"] = HEADER + r"""title 自動実行に登録 - 動画自動投稿ツール
""" + CHECK_VENV + r"""echo Windows のタスクスケジューラに、このツールを自動で動かす設定を登録します。
echo （パソコンが起動していてログインしているときに実行されます）
echo.
".venv\Scripts\python.exe" run.py register-task
echo.
pause
"""

BATS["自動実行を解除.bat"] = HEADER + r"""title 自動実行を解除 - 動画自動投稿ツール
""" + CHECK_VENV + r"""".venv\Scripts\python.exe" run.py unregister-task
echo.
pause
"""

BATS["SNSにログイン.bat"] = HEADER + r"""title SNSにログイン - 動画自動投稿ツール
""" + CHECK_VENV + r"""".venv\Scripts\python.exe" run.py login
echo.
".venv\Scripts\python.exe" run.py check
echo.
pause
"""

BATS["新しい投稿を作る.bat"] = HEADER + r"""title 新しい投稿を作る - 動画自動投稿ツール
""" + CHECK_VENV + r"""set /p NAME=投稿の名前を入力して Enter（例: 京都旅行。空のままなら日時の名前になります）: 
if "%NAME%"=="" (
  ".venv\Scripts\python.exe" run.py new
) else (
  ".venv\Scripts\python.exe" run.py new "%NAME%"
)
if not errorlevel 1 start "" "%~dp0投稿待ち"
echo.
pause
"""

BATS["設定チェック.bat"] = HEADER + r"""title 設定チェック - 動画自動投稿ツール
""" + CHECK_VENV + r"""".venv\Scripts\python.exe" run.py check
echo.
pause
"""


def main():
    for name, text in BATS.items():
        data = text.replace("\r\n", "\n").replace("\n", "\r\n").encode("cp932")
        (ROOT / name).write_bytes(data)
        print("作成:", name)


if __name__ == "__main__":
    main()
