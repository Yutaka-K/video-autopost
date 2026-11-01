"""コマンドの入口。普段は .bat ファイルから呼び出されます。

  python run.py run            … 投稿を実行
  python run.py run --dry-run  … お試し（実際には投稿しない）
  python run.py login          … SNSにログイン（メニューが出ます）
  python run.py check          … 設定の確認
  python run.py new            … 新しい投稿フォルダを作る
  python run.py register-task  … タスクスケジューラに登録
  python run.py unregister-task… 登録を解除
"""
from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime

from .config import PLATFORM_NAMES, load_config
from .platforms import PlatformError, create_platforms
from .runner import RunLock, list_post_folders, platform_status, run, setup_logging

TEMPLATE_DIR_NAME = "_テンプレート"


def cmd_run(args) -> int:
    config = load_config()
    config.ensure_dirs()
    log_path = setup_logging(config, quiet=args.auto)
    with RunLock(config) as lock:
        if not lock.acquired:
            print("別の場所でツールが実行中のため、今回は何もせずに終了します。")
            return 0
        summary = run(config, dry_run=args.dry_run)
    if not args.auto:
        print()
        print(f"ログ: {log_path}")
    return 1 if (summary.failed or summary.errors or summary.gave_up) else 0


def cmd_check(args) -> int:
    config = load_config()
    config.ensure_dirs()
    if not config.env_file.exists():
        print("★ .env ファイルがありません。「初回セットアップ.bat」を実行してください。")
    print("SNSの準備状況:")
    for key, p in create_platforms(config).items():
        ok, reason = platform_status(p, config)
        print(f"  {p.display_name:8}: {'OK（投稿できます）' if ok else 'スキップ → ' + reason}")
    print()
    folders = list_post_folders(config)
    print(f"「投稿待ち」の投稿: {len(folders)}件")
    return 0


def cmd_login(args) -> int:
    config = load_config()
    config.ensure_dirs()
    platforms = create_platforms(config)
    target = args.platform
    if not target:
        print("どのSNSにログインしますか？")
        print("  1: YouTube（ブラウザでGoogleにログイン）")
        print("  2: TikTok （ブラウザでTikTokにログイン）")
        print("  ※ X と Threads は .env にキーを書くだけなのでログイン不要です（SETUP.md参照）")
        choice = input("番号を入力して Enter: ").strip().translate(str.maketrans("１２", "12"))
        target = {"1": "youtube", "2": "tiktok"}.get(choice)
        if not target:
            print("1 か 2 を入力してください。")
            return 1
    platform = platforms.get(target)
    if platform is None or not hasattr(platform, "login"):
        print(f"{target} はログイン不要です。")
        return 1
    try:
        platform.login()
    except (PlatformError, RuntimeError) as e:
        print(f"ログインできませんでした: {e}")
        return 1
    print(f"{PLATFORM_NAMES[target]} のログインが完了しました！")
    return 0


def cmd_new(args) -> int:
    config = load_config()
    config.ensure_dirs()
    template = config.pending_dir / TEMPLATE_DIR_NAME
    name = args.name or datetime.now().strftime("投稿_%Y%m%d_%H%M%S")
    dest = config.pending_dir / name
    if dest.exists():
        print(f"「{name}」はすでにあります。")
        return 1
    dest.mkdir(parents=True)
    src = template / "投稿内容.txt"
    if src.exists():
        shutil.copy(src, dest / "投稿内容.txt")
    print(f"新しい投稿フォルダを作りました: {dest}")
    print("この中に動画ファイルを入れて、「投稿内容.txt」を書き換えてください。")
    return 0


def cmd_register(args) -> int:
    from . import scheduler

    config = load_config()
    mode, at = "hourly", "09:00"
    if args.daily:
        mode, at = "daily", args.daily
    elif not args.hourly:
        print("どのくらいの間隔で自動実行しますか？")
        print("  1: 1時間ごと（おすすめ。投稿日時から最大1時間以内に投稿されます）")
        print("  2: 1日1回（決まった時刻に実行）")
        choice = input("番号を入力して Enter: ").strip().translate(str.maketrans("１２", "12"))
        if choice == "2":
            at = input("何時に実行しますか？（例 09:00）: ").strip().translate(
                str.maketrans("０１２３４５６７８９：", "0123456789:")) or "09:00"
            try:
                datetime.strptime(at, "%H:%M")
            except ValueError:
                print("「09:00」のような形で入力してください。")
                return 1
            mode = "daily"
        elif choice != "1":
            print("1 か 2 を入力してください。")
            return 1
    return 0 if scheduler.register(config.base_dir, mode, at) else 1


def cmd_unregister(args) -> int:
    from . import scheduler

    return 0 if scheduler.unregister() else 1


def main(argv: list[str] | None = None) -> int:
    # Windows のコンソールでも日本語が化けないようにする
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass

    parser = argparse.ArgumentParser(prog="run.py", description="動画自動投稿ツール")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("run", help="投稿を実行する")
    p.add_argument("--dry-run", action="store_true", help="お試しモード（実際には投稿しない）")
    p.add_argument("--auto", action="store_true", help="タスクスケジューラから実行するとき用")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("check", help="設定を確認する")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("login", help="SNSにログインする")
    p.add_argument("platform", nargs="?", choices=["youtube", "tiktok"])
    p.set_defaults(func=cmd_login)

    p = sub.add_parser("new", help="新しい投稿フォルダを作る")
    p.add_argument("name", nargs="?")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("register-task", help="タスクスケジューラに登録する")
    p.add_argument("--hourly", action="store_true")
    p.add_argument("--daily", metavar="HH:MM")
    p.set_defaults(func=cmd_register)

    p = sub.add_parser("unregister-task", help="タスクスケジューラから解除する")
    p.set_defaults(func=cmd_unregister)

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n中断しました。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
