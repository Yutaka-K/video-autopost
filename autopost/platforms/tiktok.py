"""TikTok への投稿（TikTok Content Posting API）。

2つの投稿方法があります（.env の TIKTOK_MODE で選択）:
  direct … 直接投稿。TikTok の審査（Audit）前は「自分のみ」（非公開）でしか投稿できず、
           さらに TikTok アカウント自体を「非公開アカウント」にしておく必要があります。
  inbox  … 下書きとして TikTok アプリに送ります。アプリの通知から開いて、自分で「投稿」を押します。

ログインのトークンは24時間で切れますが、ツールが自動で更新します（更新用トークンは約1年有効）。
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import requests

from .. import text_fit
from ..post_parser import Post
from .base import Platform, PlatformError, PostResult

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
API_BASE = "https://open.tiktokapis.com"
TOKEN_URL = API_BASE + "/v2/oauth/token/"
SCOPES = "user.info.basic,video.publish,video.upload"

MIN_CHUNK = 5 * 1024 * 1024
CHUNK = 10 * 1024 * 1024  # 5MB〜64MB の範囲で指定する決まり
PRIVACY_CHOICES = ("SELF_ONLY", "MUTUAL_FOLLOW_FRIENDS", "FOLLOWER_OF_CREATOR", "PUBLIC_TO_EVERYONE")

ERROR_HINTS = {
    "unaudited_client_can_only_post_to_private_accounts":
        "審査前のアプリは「非公開アカウント」にしか投稿できません。TikTokアプリの設定でアカウントを非公開にするか、審査を申請してください",
    "privacy_level_option_mismatch": "公開範囲（TIKTOK_PRIVACY）がこのアカウントでは使えません",
    "spam_risk_too_many_posts": "1日の投稿数の上限に達しました",
    "spam_risk_user_banned_from_posting": "このアカウントは現在投稿が制限されています",
    "access_token_invalid": "ログインが切れています。「SNSにログイン.bat」で TikTok にログインし直してください",
    "scope_not_authorized": "権限（video.publish / video.upload）が許可されていません。ログインし直してください",
    "rate_limit_exceeded": "短時間に送りすぎました。次回に再挑戦します",
}


def chunk_plan(size: int) -> tuple[int, int]:
    """(chunk_size, total_chunk_count) を返す。最後のチャンクには余りをまとめる。"""
    if size <= 0:
        raise PlatformError("動画ファイルが空です")
    if size < MIN_CHUNK or size <= CHUNK:
        return size, 1
    return CHUNK, size // CHUNK


class TikTok(Platform):
    key = "tiktok"

    def __init__(self, config, sleep=time.sleep, session: requests.Session | None = None):
        super().__init__(config, sleep)
        self.http = session or requests.Session()

    # ---------------- 設定 ----------------
    def missing_settings(self) -> list[str]:
        missing = []
        keys = [k for k in ("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET") if not self.config.get(k)]
        if keys:
            missing.append(f".env に {', '.join(keys)} が書かれていません")
        if not self.load_token():
            missing.append("未ログイン（「SNSにログイン.bat」でログインしてください）")
        return missing

    @property
    def mode(self) -> str:
        return "inbox" if self.config.get("TIKTOK_MODE", "direct").lower() == "inbox" else "direct"

    @property
    def privacy(self) -> str:
        value = self.config.get("TIKTOK_PRIVACY", "SELF_ONLY").upper()
        return value if value in PRIVACY_CHOICES else "SELF_ONLY"

    def preview(self, post: Post) -> dict[str, Any]:
        info = {
            "投稿方法": "直接投稿" if self.mode == "direct" else "下書きとしてアプリに送る",
            "動画": post.video.name if post.video else "",
        }
        if self.mode == "direct":
            info["投稿文"] = text_fit.social_text(post, "tiktok")
            info["公開範囲"] = self.privacy
        else:
            info["メモ"] = "下書きモードでは投稿文はアプリで入力します（API では送れません）"
        return info

    # ---------------- ログイン ----------------
    def login(self) -> None:
        from ..oauth_helper import get_authorization_code

        client_key = self.config.get("TIKTOK_CLIENT_KEY")
        redirect_uri = self.config.get("TIKTOK_REDIRECT_URI", "http://localhost:8765/callback/")
        if not client_key or not self.config.get("TIKTOK_CLIENT_SECRET"):
            raise PlatformError("先に .env に TIKTOK_CLIENT_KEY と TIKTOK_CLIENT_SECRET を書いてください。")
        verifier = base64.urlsafe_b64encode(os.urandom(48)).decode().rstrip("=")
        challenge = hashlib.sha256(verifier.encode()).hexdigest()  # TikTok は16進数の形式
        state = secrets.token_urlsafe(16)
        url = AUTH_URL + "?" + urlencode({
            "client_key": client_key,
            "scope": SCOPES,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })
        code, got_state = get_authorization_code(url, redirect_uri)
        if got_state and got_state != state:
            raise PlatformError("ログインの確認コード（state）が一致しません。もう一度やり直してください。")
        data = self._token_request({
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
        })
        self._save_token_response(data)

    def _token_request(self, fields: dict[str, str]) -> dict[str, Any]:
        body = {
            "client_key": self.config.get("TIKTOK_CLIENT_KEY"),
            "client_secret": self.config.get("TIKTOK_CLIENT_SECRET"),
            **fields,
        }
        resp = self.http.post(TOKEN_URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=60)
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.status_code >= 400 or "access_token" not in data:
            raise PlatformError(
                f"TikTok: ログイン情報の取得に失敗しました。「SNSにログイン.bat」でログインし直してください。 詳細: {data or resp.text[:300]}"
            )
        return data

    def _save_token_response(self, data: dict[str, Any]) -> None:
        now = int(time.time())
        self.save_token({
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token", ""),
            "open_id": data.get("open_id", ""),
            "scope": data.get("scope", ""),
            "expires_at": now + int(data.get("expires_in", 86400)),
            "refresh_expires_at": now + int(data.get("refresh_expires_in", 31536000)),
        })

    def access_token(self) -> str:
        token = self.load_token()
        if not token:
            raise PlatformError("TikTok にログインしていません。「SNSにログイン.bat」でログインしてください。")
        if token.get("expires_at", 0) - 300 > time.time():
            return token["access_token"]
        if token.get("refresh_expires_at", 0) < time.time() or not token.get("refresh_token"):
            raise PlatformError("TikTok のログイン期限（約1年）が切れました。「SNSにログイン.bat」でログインし直してください。")
        data = self._token_request({"grant_type": "refresh_token", "refresh_token": token["refresh_token"]})
        self._save_token_response(data)
        return data["access_token"]

    # ---------------- API 呼び出し ----------------
    def _api(self, path: str, token: str, body: dict[str, Any]) -> dict[str, Any]:
        resp = self.http.post(
            API_BASE + path,
            json=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
            timeout=60,
        )
        try:
            data = resp.json()
        except ValueError:
            data = {}
        err = data.get("error", {}) or {}
        code = err.get("code", "")
        if resp.status_code >= 400 or (code and code != "ok"):
            hint = ERROR_HINTS.get(code, "TikTok への投稿に失敗しました")
            raise PlatformError(f"TikTok: {hint}（HTTP {resp.status_code} {code}） 詳細: {err.get('message', '') or resp.text[:300]}")
        return data.get("data", {}) or {}

    def publish(self, post: Post) -> PostResult:
        token = self.access_token()
        size = post.video.stat().st_size
        chunk_size, count = chunk_plan(size)
        source_info = {
            "source": "FILE_UPLOAD",
            "video_size": size,
            "chunk_size": chunk_size,
            "total_chunk_count": count,
        }

        privacy = self.privacy
        if self.mode == "direct":
            creator = self._api("/v2/post/publish/creator_info/query/", token, {})
            options = creator.get("privacy_level_options") or []
            if options and privacy not in options:
                print(f"    ※ 公開範囲 {privacy} は使えないため SELF_ONLY（自分のみ）で投稿します")
                privacy = "SELF_ONLY"
            init = self._api("/v2/post/publish/video/init/", token, {
                "post_info": {
                    "title": text_fit.social_text(post, "tiktok"),
                    "privacy_level": privacy,
                    "disable_duet": False,
                    "disable_comment": False,
                    "disable_stitch": False,
                },
                "source_info": source_info,
            })
        else:
            init = self._api("/v2/post/publish/inbox/video/init/", token, {"source_info": source_info})

        publish_id = init.get("publish_id", "")
        upload_url = init.get("upload_url", "")
        if not upload_url:
            raise PlatformError(f"TikTok: アップロード先URLが返ってきませんでした（{init}）")
        self._upload(upload_url, post, size, chunk_size, count)
        status = self._wait(token, publish_id)

        if self.mode == "inbox":
            note = "TikTokアプリの通知（受信トレイ）から開いて、投稿を完了してください"
        elif privacy == "SELF_ONLY":
            note = "公開範囲は「自分のみ」です（審査前のアプリはこの設定のみ使えます）"
        else:
            note = ""
        if status.get("status") == "TIMEOUT":
            note = "動画は送信済みですが処理に時間がかかっています。TikTokアプリで確認してください。" + note
        # 公開された投稿のID（項目名はTikTok側のつづりのまま）
        post_ids = status.get("publicaly_available_post_id") or []
        post_id = str(post_ids[0]) if post_ids else publish_id
        return PostResult(post_id=post_id, note=note)

    def _upload(self, upload_url: str, post: Post, size: int, chunk_size: int, count: int) -> None:
        mime = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}.get(
            post.video.suffix.lower(), "video/mp4")
        with open(post.video, "rb") as f:
            for i in range(count):
                start = i * chunk_size
                end = size - 1 if i == count - 1 else start + chunk_size - 1
                f.seek(start)
                data = f.read(end - start + 1)
                resp = self.http.put(upload_url, data=data, headers={
                    "Content-Type": mime,
                    "Content-Length": str(len(data)),
                    "Content-Range": f"bytes {start}-{end}/{size}",
                }, timeout=600)
                if resp.status_code not in (200, 201, 206):
                    raise PlatformError(f"TikTok: 動画のアップロードに失敗しました（HTTP {resp.status_code}） {resp.text[:300]}")
                print(f"    TikTok アップロード中… {int((i + 1) / count * 100)}%")

    def _wait(self, token: str, publish_id: str, max_wait: int = 600) -> dict[str, Any]:
        waited = 0
        while waited <= max_wait:
            data = self._api("/v2/post/publish/status/fetch/", token, {"publish_id": publish_id})
            status = data.get("status", "")
            if status in ("PUBLISH_COMPLETE", "SEND_TO_USER_INBOX"):
                return data
            if status == "FAILED":
                raise PlatformError(f"TikTok: 投稿の処理に失敗しました（理由: {data.get('fail_reason', '不明')}）")
            self.sleep(5)
            waited += 5
        # 動画は送信済みなので、二重投稿を防ぐため「失敗」にはしない
        return {"status": "TIMEOUT"}
