"""Threads への投稿（Threads API）。

Threads の API は「動画ファイルを直接受け取らない」仕組みです。
インターネット上の公開URLに置いた動画を、Meta のサーバーが取りに来ます。
そのため、次のどちらかの方法で動画を公開URLに置きます（.env の THREADS_VIDEO_HOSTING）:
  s3     … Cloudflare R2 / Amazon S3 に自動アップロードし、期限付きURLを渡す。投稿後に自動削除。
  manual … 自分でアップロードし、投稿内容.txt の【動画URL】に書く。

トークンは60日で切れますが、ツールが実行のたびに自動で延長します。
"""
from __future__ import annotations

import time
from typing import Any

import requests

from .. import text_fit
from ..post_parser import Post
from ..video_hosting import S3Hosting, hosting_missing_settings
from .base import Platform, PlatformError, PostResult, check_response

GRAPH = "https://graph.threads.net"
API = GRAPH + "/v1.0"
REFRESH_INTERVAL = 7 * 24 * 3600  # 1週間ごとに延長


class Threads(Platform):
    key = "threads"

    def __init__(self, config, sleep=time.sleep, session: requests.Session | None = None, hosting=None):
        super().__init__(config, sleep)
        self.http = session or requests.Session()
        self._hosting = hosting

    @property
    def hosting_mode(self) -> str:
        return "manual" if self.config.get("THREADS_VIDEO_HOSTING", "s3").lower() == "manual" else "s3"

    def missing_settings(self) -> list[str]:
        missing = []
        if not self.config.get("THREADS_ACCESS_TOKEN") and not self.load_token():
            missing.append("THREADS_ACCESS_TOKEN が .env に書かれていません")
        if self.hosting_mode == "s3":
            missing += hosting_missing_settings(self.config)
        return missing

    def preview(self, post: Post) -> dict[str, Any]:
        text = text_fit.social_text(post, "threads")
        info = {"投稿文": text, "文字数": f"{len(text)} / {text_fit.LIMITS['threads']}"}
        if self.hosting_mode == "manual":
            info["動画URL"] = post.video_url or "（未記入！ 投稿内容.txt の【動画URL】に書いてください）"
        else:
            info["動画"] = f"{post.video.name}（クラウドに一時アップロードして使います）"
        return info

    # ---------------- トークン ----------------
    def access_token(self) -> str:
        saved = self.load_token() or {}
        env_token = self.config.get("THREADS_ACCESS_TOKEN")
        # .env のトークンが書き換えられたら、そちらを優先する
        if env_token and saved.get("source_token") != env_token:
            saved = {"access_token": env_token, "source_token": env_token, "refreshed_at": 0}
            self.save_token(saved)
        token = saved.get("access_token", "")
        if not token:
            raise PlatformError("Threads のトークンがありません。SETUP.md を見て .env に書いてください。")
        if time.time() - saved.get("refreshed_at", 0) > REFRESH_INTERVAL:
            resp = self.http.get(
                GRAPH + "/refresh_access_token",
                params={"grant_type": "th_refresh_token", "access_token": token},
                timeout=60,
            )
            if resp.status_code < 400 and "access_token" in (resp.json() or {}):
                token = resp.json()["access_token"]
                saved.update({"access_token": token, "refreshed_at": int(time.time())})
                self.save_token(saved)
            elif saved.get("refreshed_at", 0) == 0:
                # 作ったばかり（24時間以内）のトークンは延長できないので、そのまま使う
                pass
            else:
                print("    ※ Threads のトークン延長に失敗しました。60日で切れるので、切れたら作り直してください。")
        return token

    # ---------------- 投稿 ----------------
    def hosting(self):
        if self._hosting is None:
            self._hosting = S3Hosting(self.config)
        return self._hosting

    def publish(self, post: Post) -> PostResult:
        token = self.access_token()
        uploaded_key = None
        if self.hosting_mode == "manual":
            video_url = post.video_url
            if not video_url:
                raise PlatformError("Threads: 投稿内容.txt の【動画URL】が空です（THREADS_VIDEO_HOSTING=manual のとき必要）")
        else:
            print("    Threads 用に動画をクラウドへ一時アップロード中…")
            uploaded_key, video_url = self.hosting().upload(post.video)
        try:
            return self._publish_with_url(token, post, video_url)
        finally:
            if uploaded_key:
                try:
                    self.hosting().delete(uploaded_key)
                except Exception as e:  # noqa: BLE001
                    print(f"    ※ 一時アップロードした動画の削除に失敗しました（手動で削除してください）: {e}")

    def _publish_with_url(self, token: str, post: Post, video_url: str) -> PostResult:
        # 1) 入れ物（コンテナ）を作る
        resp = self.http.post(API + "/me/threads", data={
            "media_type": "VIDEO",
            "video_url": video_url,
            "text": text_fit.social_text(post, "threads"),
            "access_token": token,
        }, timeout=60)
        container_id = check_response(resp, "Threads（準備）").get("id", "")
        if not container_id:
            raise PlatformError("Threads: 投稿の準備に失敗しました（IDが返ってきません）")

        # 2) Meta 側で動画の処理が終わるのを待つ
        waited = 0
        while True:
            resp = self.http.get(API + f"/{container_id}", params={
                "fields": "status,error_message", "access_token": token}, timeout=60)
            data = check_response(resp, "Threads（処理確認）")
            status = data.get("status", "")
            if status == "FINISHED":
                break
            if status in ("ERROR", "EXPIRED"):
                raise PlatformError(
                    f"Threads: 動画の処理に失敗しました（{data.get('error_message', status)}）。"
                    "動画は MP4/MOV・5分以内・1GB以内である必要があります。"
                )
            if waited > 600:
                raise PlatformError("Threads: 動画の処理に時間がかかりすぎています。次回に再挑戦します。")
            self.sleep(10)
            waited += 10

        # 3) 公開する
        resp = self.http.post(API + "/me/threads_publish", data={
            "creation_id": container_id, "access_token": token}, timeout=60)
        thread_id = check_response(resp, "Threads（公開）").get("id", "")
        if not thread_id:
            raise PlatformError("Threads: 公開に失敗しました（IDが返ってきません）")
        permalink = ""
        try:
            resp = self.http.get(API + f"/{thread_id}", params={"fields": "permalink", "access_token": token}, timeout=30)
            permalink = (resp.json() or {}).get("permalink", "") if resp.status_code < 400 else ""
        except Exception:  # noqa: BLE001
            pass
        return PostResult(post_id=thread_id, url=permalink)
