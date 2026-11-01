"""SNS投稿の共通部分。新しいSNSを追加するときは Platform を継承して作ります。"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import Config, PLATFORM_NAMES
from ..post_parser import Post


class PlatformError(Exception):
    """投稿に失敗したときのエラー（日本語メッセージ入り）。"""

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class PostResult:
    post_id: str = ""
    url: str = ""
    note: str = ""


class Platform:
    key = ""  # youtube / tiktok / x / threads

    def __init__(self, config: Config, sleep=time.sleep):
        self.config = config
        self.sleep = sleep  # テストで待ち時間をなくすため差し替えられるようにしている

    @property
    def display_name(self) -> str:
        return PLATFORM_NAMES[self.key]

    # ---- 子クラスで作るもの ----
    def missing_settings(self) -> list[str]:
        """足りない設定の説明リスト。空なら投稿可能。"""
        raise NotImplementedError

    def preview(self, post: Post) -> dict[str, Any]:
        """お試しモードで表示する内容。"""
        raise NotImplementedError

    def publish(self, post: Post) -> PostResult:
        raise NotImplementedError

    # ---- 共通の便利機能 ----
    def is_configured(self) -> bool:
        return not self.missing_settings()

    def token_path(self) -> Path:
        return self.config.token_dir / f"{self.key}_token.json"

    def load_token(self) -> dict[str, Any] | None:
        path = self.token_path()
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def save_token(self, data: dict[str, Any]) -> None:
        path = self.token_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def check_response(resp, service: str) -> dict[str, Any]:
    """requests のレスポンスを確認し、エラーなら分かりやすいメッセージで PlatformError を出す。"""
    try:
        data = resp.json() if resp.content else {}
    except ValueError:
        data = {"raw": resp.text[:500]}
    if resp.status_code >= 400:
        hint = {
            400: "送った内容に問題があります",
            401: "ログイン情報（トークン/キー）が無効か期限切れです。SETUP.md を見て設定し直してください",
            402: "料金（クレジット）が不足しています",
            403: "権限がありません（アプリの権限設定や審査状況を確認してください）",
            404: "見つかりません",
            413: "ファイルが大きすぎます",
            429: "短時間に送りすぎました。時間をおくと成功します",
        }.get(resp.status_code, "サーバーでエラーが起きました")
        retryable = resp.status_code in (408, 429) or resp.status_code >= 500
        detail = json.dumps(data, ensure_ascii=False)[:500]
        raise PlatformError(f"{service}: {hint}（HTTP {resp.status_code}） 詳細: {detail}", retryable=retryable)
    return data
