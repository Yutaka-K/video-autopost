"""設定（.env）の読み込みと、フォルダの場所の管理。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

# このツールのフォルダ（autopost フォルダの1つ上）
DEFAULT_BASE_DIR = Path(__file__).resolve().parent.parent

PLATFORM_NAMES = {
    "youtube": "YouTube",
    "tiktok": "TikTok",
    "x": "X",
    "threads": "Threads",
}

_TRUE_WORDS = {"true", "1", "yes", "on", "はい", "する", "オン"}


def to_bool(value: str | None, default: bool = False) -> bool:
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() in _TRUE_WORDS


@dataclass
class Config:
    base_dir: Path
    values: dict[str, str] = field(default_factory=dict)

    # ---- フォルダ ----
    @property
    def pending_dir(self) -> Path:
        return self.base_dir / "投稿待ち"

    @property
    def done_dir(self) -> Path:
        return self.base_dir / "投稿済み"

    @property
    def failed_dir(self) -> Path:
        return self.base_dir / "投稿失敗"

    @property
    def log_dir(self) -> Path:
        return self.base_dir / "ログ"

    @property
    def token_dir(self) -> Path:
        return self.base_dir / "tokens"

    def ensure_dirs(self) -> None:
        for d in (self.pending_dir, self.done_dir, self.failed_dir, self.log_dir, self.token_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ---- 値の取得 ----
    def get(self, key: str, default: str = "") -> str:
        value = self.values.get(key)
        if value is None:
            return default
        return str(value).strip()

    def get_bool(self, key: str, default: bool = False) -> bool:
        return to_bool(self.values.get(key), default)

    def get_int(self, key: str, default: int) -> int:
        try:
            return int(self.get(key, str(default)))
        except ValueError:
            return default

    def is_enabled(self, platform: str) -> bool:
        return self.get_bool(f"{platform.upper()}_ENABLED", default=True)

    @property
    def max_retry(self) -> int:
        return max(1, self.get_int("MAX_RETRY", 5))

    @property
    def env_file(self) -> Path:
        return self.base_dir / ".env"


def load_config(base_dir: Path | None = None, extra: dict[str, str] | None = None) -> Config:
    """.env を読み込んで Config を作る。

    base_dir を省略するとツールのフォルダを使う（環境変数 AUTOPOST_HOME で変更可）。
    extra はテスト用に値を上書きするためのもの。
    """
    if base_dir is None:
        base_dir = Path(os.environ.get("AUTOPOST_HOME", DEFAULT_BASE_DIR))
    base_dir = Path(base_dir)
    values: dict[str, str] = {}
    env_path = base_dir / ".env"
    if env_path.exists():
        # メモ帳で保存したときの BOM にも対応
        values.update({k: v for k, v in dotenv_values(env_path, encoding="utf-8-sig").items() if v is not None})
    if extra:
        values.update(extra)
    return Config(base_dir=base_dir, values=values)
