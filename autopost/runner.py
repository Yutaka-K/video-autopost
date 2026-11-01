"""投稿の全体の流れ（フォルダを調べる → 時間が来たものを投稿 → 結果を記録 → 移動）。"""
from __future__ import annotations

import csv
import json
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import PLATFORM_NAMES, Config
from .platforms import Platform, PlatformError, create_platforms
from .post_parser import Post, PostFileError, parse_post_folder

RESULT_FILE = "投稿結果.json"
HISTORY_FILE = "投稿履歴.csv"
LOCK_FILE = "実行中.lock"
LOCK_MAX_AGE = 3 * 3600

log = logging.getLogger("autopost")


# ---------------------------------------------------------------------
#  ログの準備
# ---------------------------------------------------------------------
def setup_logging(config: Config, quiet: bool = False) -> Path:
    config.log_dir.mkdir(parents=True, exist_ok=True)
    log_path = config.log_dir / f"ログ_{datetime.now():%Y-%m}.txt"
    log.handlers.clear()
    log.setLevel(logging.INFO)
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
    log.addHandler(fh)
    if not quiet:
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(message)s"))
        log.addHandler(sh)
    log.propagate = False
    return log_path


# ---------------------------------------------------------------------
#  投稿結果ファイル（各投稿フォルダの 投稿結果.json）
# ---------------------------------------------------------------------
def load_state(folder: Path) -> dict[str, Any]:
    path = folder / RESULT_FILE
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {"attempts": 0, "platforms": {}}


def save_state(folder: Path, state: dict[str, Any]) -> None:
    (folder / RESULT_FILE).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def append_history(config: Config, post_name: str, platform: str, status: str, detail: str) -> None:
    path = config.log_dir / HISTORY_FILE
    new = not path.exists()
    # utf-8-sig にすると Excel で開いても文字化けしない
    with open(path, "a", encoding="utf-8-sig" if new else "utf-8", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["日時", "投稿フォルダ", "SNS", "結果", "詳細"])
        w.writerow([f"{datetime.now():%Y-%m-%d %H:%M:%S}", post_name, PLATFORM_NAMES.get(platform, platform), status, detail])


def move_folder(src: Path, dest_root: Path) -> Path:
    dest_root.mkdir(parents=True, exist_ok=True)
    dest = dest_root / f"{datetime.now():%Y%m%d_%H%M}_{src.name}"
    n = 2
    while dest.exists():
        dest = dest_root / f"{datetime.now():%Y%m%d_%H%M}_{src.name}_{n}"
        n += 1
    shutil.move(str(src), str(dest))
    return dest


# ---------------------------------------------------------------------
#  二重起動の防止
# ---------------------------------------------------------------------
class RunLock:
    def __init__(self, config: Config):
        self.path = config.log_dir / LOCK_FILE
        self.acquired = False

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and time.time() - self.path.stat().st_mtime < LOCK_MAX_AGE:
            return self
        self.path.write_text(str(os.getpid()), encoding="utf-8")
        self.acquired = True
        return self

    def __exit__(self, *exc):
        if self.acquired:
            try:
                self.path.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------
#  メインの処理
# ---------------------------------------------------------------------
@dataclass
class RunSummary:
    posted: list[str] = field(default_factory=list)
    waiting: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    gave_up: list[str] = field(default_factory=list)


def list_post_folders(config: Config) -> list[Path]:
    if not config.pending_dir.exists():
        return []
    # 「_」で始まるフォルダ（_テンプレート など）は対象外
    return sorted(p for p in config.pending_dir.iterdir() if p.is_dir() and not p.name.startswith(("_", ".")))


def platform_status(platform: Platform, config: Config) -> tuple[bool, str]:
    """(使えるか, 使えない理由)"""
    if not config.is_enabled(platform.key):
        return False, "設定でオフになっています"
    missing = platform.missing_settings()
    if missing:
        return False, " / ".join(missing)
    return True, ""


def run(config: Config, dry_run: bool = False, platforms: dict[str, Platform] | None = None,
        now: datetime | None = None) -> RunSummary:
    config.ensure_dirs()
    platforms = platforms or create_platforms(config)
    summary = RunSummary()
    now = now or datetime.now()

    mode = "【お試しモード】実際には投稿しません" if dry_run else "投稿を開始します"
    log.info("=" * 60)
    log.info(f"{mode}（{now:%Y-%m-%d %H:%M}）")

    # SNSの準備状況
    available: dict[str, tuple[bool, str]] = {}
    for key, p in platforms.items():
        available[key] = platform_status(p, config)
        ok, reason = available[key]
        log.info(f"  {p.display_name:8}: {'使えます' if ok else 'スキップ（' + reason + '）'}")

    folders = list_post_folders(config)
    if not folders:
        log.info("「投稿待ち」フォルダに投稿がありません。")
        return summary

    for folder in folders:
        log.info("-" * 60)
        log.info(f"■ {folder.name}")
        try:
            post = parse_post_folder(folder)
        except PostFileError as e:
            log.error(f"  投稿内容に問題があります: {e}")
            summary.errors.append(folder.name)
            continue

        if not post.is_due(now):
            log.info(f"  投稿予定: {post.schedule:%Y-%m-%d %H:%M}（まだ時間前なので待ちます）")
            summary.waiting.append(folder.name)
            if not dry_run:
                continue
            log.info("  ↓ 時間になったら、次の内容で投稿されます")

        if dry_run:
            _preview(post, platforms, available)
            continue

        _process(post, config, platforms, available, summary)

    log.info("=" * 60)
    if not dry_run:
        log.info(
            f"完了: 投稿済み {len(summary.posted)}件 / 再挑戦待ち {len(summary.failed)}件 / "
            f"時間待ち {len(summary.waiting)}件 / 内容エラー {len(summary.errors)}件 / あきらめ {len(summary.gave_up)}件"
        )
    return summary


def _preview(post: Post, platforms: dict[str, Platform], available: dict[str, tuple[bool, str]]) -> None:
    state = load_state(post.folder)
    when = f"{post.schedule:%Y-%m-%d %H:%M}" if post.schedule else "すぐ"
    log.info(f"  投稿日時: {when}")
    for key in post.targets:
        p = platforms[key]
        log.info(f"  ▼ {p.display_name}")
        if state["platforms"].get(key, {}).get("status") == "success":
            log.info("    （投稿済みなので今回は投稿しません）")
            continue
        ok, reason = available[key]
        if not ok:
            log.info(f"    スキップされます（{reason}）")
        try:
            for label, value in p.preview(post).items():
                text = str(value)
                if "\n" in text:
                    log.info(f"    {label}:")
                    for line in text.splitlines():
                        log.info(f"      | {line}")
                else:
                    log.info(f"    {label}: {text}")
        except Exception as e:  # noqa: BLE001
            log.info(f"    （表示できませんでした: {e}）")


def _process(post: Post, config: Config, platforms: dict[str, Platform],
             available: dict[str, tuple[bool, str]], summary: RunSummary) -> None:
    state = load_state(post.folder)
    had_failure = False
    for key in post.targets:
        p = platforms[key]
        record = state["platforms"].get(key, {})
        if record.get("status") == "success":
            log.info(f"  {p.display_name}: 前回までに投稿済み")
            continue
        ok, reason = available[key]
        if not ok:
            log.warning(f"  {p.display_name}: スキップしました（{reason}）")
            state["platforms"][key] = {"status": "skipped", "reason": reason, "time": _now()}
            append_history(config, post.name, key, "スキップ", reason)
            continue
        log.info(f"  {p.display_name}: 投稿中…")
        try:
            result = p.publish(post)
        except PlatformError as e:
            had_failure = True
            log.error(f"  {p.display_name}: 失敗しました → {e}")
            state["platforms"][key] = {"status": "failed", "error": str(e), "time": _now()}
            append_history(config, post.name, key, "失敗", str(e))
        except Exception as e:  # noqa: BLE001  想定外のエラーも記録して次へ進む
            had_failure = True
            log.exception(f"  {p.display_name}: 想定外のエラーで失敗しました → {e}")
            state["platforms"][key] = {"status": "failed", "error": f"{type(e).__name__}: {e}", "time": _now()}
            append_history(config, post.name, key, "失敗", f"{type(e).__name__}: {e}")
        else:
            log.info(f"  {p.display_name}: 成功！ {result.url or result.post_id}")
            if result.note:
                log.info(f"    {result.note}")
            state["platforms"][key] = {
                "status": "success", "id": result.post_id, "url": result.url, "note": result.note, "time": _now()}
            append_history(config, post.name, key, "成功", " ".join(x for x in (result.url or result.post_id, result.note) if x))
        save_state(post.folder, state)  # 1件ごとに保存（途中で止まっても二重投稿しないように）

    if had_failure:
        state["attempts"] = state.get("attempts", 0) + 1
        save_state(post.folder, state)
        if state["attempts"] >= config.max_retry:
            dest = move_folder(post.folder, config.failed_dir)
            log.error(f"  {config.max_retry}回失敗したので「投稿失敗」フォルダへ移動しました: {dest.name}")
            log.error("  原因を直したら、フォルダを「投稿待ち」に戻し、投稿結果.json を削除すると再挑戦します。")
            summary.gave_up.append(post.name)
        else:
            log.warning(f"  失敗した分は次回また挑戦します（{state['attempts']}/{config.max_retry}回目）")
            summary.failed.append(post.name)
        return

    save_state(post.folder, state)
    if not any(r.get("status") == "success" for r in state["platforms"].values()):
        # 1つも投稿できていない（全部スキップ）ときは移動しない。設定が終わったら投稿される
        log.warning("  投稿できるSNSが1つもなかったので「投稿待ち」に残します。設定を確認してください。")
        for key in post.targets:
            state["platforms"].pop(key, None)
        save_state(post.folder, state)
        summary.waiting.append(post.name)
        return
    dest = move_folder(post.folder, config.done_dir)
    log.info(f"  「投稿済み」フォルダへ移動しました: {dest.name}")
    summary.posted.append(post.name)


def _now() -> str:
    return f"{datetime.now():%Y-%m-%d %H:%M:%S}"
