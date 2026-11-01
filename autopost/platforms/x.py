"""X（旧Twitter）への投稿（X API v2）。

- 認証は「OAuth 1.0a」（APIキー・シークレット＋アクセストークン・シークレットの4つ）を使います。
  自分のアカウントに投稿するだけならこれが一番かんたんで、トークンの期限切れもありません。
- 動画は v2 のメディアアップロード（initialize → append → finalize → 処理待ち）で送ります。
- 2026年現在、X API は「従量課金（使った分だけ支払い）」です。投稿にはクレジットの購入が必要です。
"""
from __future__ import annotations

import math
import time
from typing import Any

import requests

from .. import text_fit
from ..post_parser import Post
from .base import Platform, PlatformError, PostResult, check_response

API = "https://api.x.com"
SEGMENT = 4 * 1024 * 1024  # 4MB ずつ送る
KEYS = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET")


class X(Platform):
    key = "x"

    def __init__(self, config, sleep=time.sleep, session: requests.Session | None = None):
        super().__init__(config, sleep)
        self.http = session or requests.Session()

    def missing_settings(self) -> list[str]:
        missing = [k for k in KEYS if not self.config.get(k)]
        return [f".env に {', '.join(missing)} が書かれていません"] if missing else []

    def preview(self, post: Post) -> dict[str, Any]:
        text = text_fit.social_text(post, "x")
        info = {
            "投稿文": text,
            "文字数": f"{text_fit.count_x(text)} / {text_fit.LIMITS['x']}（日本語は1文字=2で計算）",
            "動画": post.video.name if post.video else "",
        }
        if "http://" in text or "https://" in text:
            info["注意"] = "URLが入っています。X API はURL入りの投稿の料金が高くなります（約13倍）"
        return info

    def _auth(self):
        from requests_oauthlib import OAuth1

        return OAuth1(
            self.config.get("X_API_KEY"),
            self.config.get("X_API_SECRET"),
            self.config.get("X_ACCESS_TOKEN"),
            self.config.get("X_ACCESS_TOKEN_SECRET"),
        )

    def publish(self, post: Post) -> PostResult:
        auth = self._auth()
        media_id = self._upload_video(post, auth)
        text = text_fit.social_text(post, "x")
        resp = self.http.post(
            API + "/2/tweets",
            json={"text": text, "media": {"media_ids": [media_id]}},
            auth=auth,
            timeout=60,
        )
        data = check_response(resp, "X")
        tweet_id = data.get("data", {}).get("id", "")
        if not tweet_id:
            raise PlatformError(f"X: 投稿IDが返ってきませんでした（{data}）")
        return PostResult(post_id=tweet_id, url=f"https://x.com/i/status/{tweet_id}")

    def _upload_video(self, post: Post, auth) -> str:
        size = post.video.stat().st_size
        mime = "video/quicktime" if post.video.suffix.lower() == ".mov" else "video/mp4"

        # 1) initialize
        resp = self.http.post(
            API + "/2/media/upload/initialize",
            json={"media_type": mime, "total_bytes": size, "media_category": "amplify_video"},
            auth=auth,
            timeout=60,
        )
        media_id = check_response(resp, "X（動画の準備）").get("data", {}).get("id", "")
        if not media_id:
            raise PlatformError("X: 動画アップロードの準備に失敗しました（IDが返ってきません）")

        # 2) append（分割して送る）
        total = max(1, math.ceil(size / SEGMENT))
        with open(post.video, "rb") as f:
            for index in range(total):
                chunk = f.read(SEGMENT)
                resp = self.http.post(
                    API + f"/2/media/upload/{media_id}/append",
                    data={"segment_index": str(index)},
                    files={"media": ("chunk", chunk, "application/octet-stream")},
                    auth=auth,
                    timeout=300,
                )
                check_response(resp, "X（動画の送信）")
                print(f"    X アップロード中… {int((index + 1) / total * 100)}%")

        # 3) finalize
        resp = self.http.post(API + f"/2/media/upload/{media_id}/finalize", auth=auth, timeout=60)
        info = check_response(resp, "X（動画の確定）").get("data", {}).get("processing_info")

        # 4) 処理待ち
        waited = 0
        while info and info.get("state") in ("pending", "in_progress"):
            wait = int(info.get("check_after_secs", 5) or 5)
            if waited > 900:
                raise PlatformError("X: 動画の処理に時間がかかりすぎています。次回に再挑戦します。")
            self.sleep(wait)
            waited += wait
            resp = self.http.get(
                API + "/2/media/upload",
                params={"command": "STATUS", "media_id": media_id},
                auth=auth,
                timeout=60,
            )
            info = check_response(resp, "X（動画の処理確認）").get("data", {}).get("processing_info")
        if info and info.get("state") == "failed":
            err = info.get("error", {})
            raise PlatformError(
                f"X: 動画の処理に失敗しました。動画の形式や長さ（通常は2分20秒まで）を確認してください。 詳細: {err}"
            )
        return media_id
