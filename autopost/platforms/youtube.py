"""YouTube への投稿（YouTube Data API v3 / videos.insert）。

必要なもの:
  - Google Cloud の「OAuth クライアント ID（デスクトップアプリ）」のファイル（client_secret.json）
  - 初回だけブラウザでログイン（「SNSにログイン.bat」→ YouTube）

注意:
  - Google の監査（Audit）を通っていないプロジェクトからアップロードした動画は、
    公開設定に関係なく「非公開」に固定されます。公開するには監査の申請が必要です。
  - OAuth 同意画面が「テスト」のままだと、ログインが7日で切れます。「本番環境」にしてください。
"""
from __future__ import annotations

from typing import Any

from .. import text_fit
from ..post_parser import Post
from .base import Platform, PlatformError, PostResult

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CHUNK_SIZE = 8 * 1024 * 1024  # 8MB ずつ送る（途中で切れても続きから再送できる）


class YouTube(Platform):
    key = "youtube"

    # ---------------- 設定チェック ----------------
    @property
    def client_secret_path(self):
        name = self.config.get("YOUTUBE_CLIENT_SECRET_FILE", "client_secret.json")
        path = self.config.base_dir / name
        return path

    def missing_settings(self) -> list[str]:
        missing = []
        if not self.client_secret_path.exists():
            missing.append(f"{self.client_secret_path.name} がありません")
        if not self.token_path().exists():
            missing.append("未ログイン（「SNSにログイン.bat」でログインしてください）")
        return missing

    def privacy(self) -> str:
        value = self.config.get("YOUTUBE_PRIVACY", "public").lower()
        return value if value in ("public", "unlisted", "private") else "private"

    # ---------------- 投稿内容 ----------------
    def build_body(self, post: Post) -> dict[str, Any]:
        return {
            "snippet": {
                "title": text_fit.youtube_title(post),
                "description": text_fit.youtube_description(post),
                "tags": text_fit.youtube_tags(post),
                "categoryId": self.config.get("YOUTUBE_CATEGORY_ID", "22"),
            },
            "status": {
                "privacyStatus": self.privacy(),
                "selfDeclaredMadeForKids": self.config.get_bool("YOUTUBE_MADE_FOR_KIDS", False),
            },
        }

    def preview(self, post: Post) -> dict[str, Any]:
        body = self.build_body(post)
        return {
            "タイトル": body["snippet"]["title"],
            "説明文": body["snippet"]["description"],
            "タグ": ", ".join(body["snippet"]["tags"]) or "（なし）",
            "公開設定": body["status"]["privacyStatus"],
            "動画": post.video.name if post.video else "",
        }

    # ---------------- ログイン ----------------
    def load_credentials(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        token = self.token_path()
        if not token.exists():
            raise PlatformError("YouTube にログインしていません。「SNSにログイン.bat」でログインしてください。")
        creds = Credentials.from_authorized_user_file(str(token), SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception as e:  # noqa: BLE001
                    raise PlatformError(
                        "YouTube のログインが切れました。「SNSにログイン.bat」でログインし直してください。"
                        f"（OAuth同意画面が「テスト」だと7日で切れます） 詳細: {e}"
                    ) from e
                token.write_text(creds.to_json(), encoding="utf-8")
            else:
                raise PlatformError("YouTube のログイン情報が無効です。ログインし直してください。")
        return creds

    def login(self) -> None:
        from google_auth_oauthlib.flow import InstalledAppFlow

        if not self.client_secret_path.exists():
            raise PlatformError(
                f"{self.client_secret_path.name} が見つかりません。SETUP.md の手順でダウンロードし、"
                "このツールのフォルダに置いてください。"
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(self.client_secret_path), SCOPES)
        print("ブラウザが開きます。投稿したい YouTube チャンネルの Google アカウントでログインしてください。")
        print("「このアプリは Google で確認されていません」と出たら「詳細」→「（安全ではないページ）に移動」で進めます。")
        creds = flow.run_local_server(port=0, prompt="consent", open_browser=True)
        self.token_path().parent.mkdir(parents=True, exist_ok=True)
        self.token_path().write_text(creds.to_json(), encoding="utf-8")

    # ---------------- 投稿 ----------------
    def build_service(self):
        from googleapiclient.discovery import build

        return build("youtube", "v3", credentials=self.load_credentials(), cache_discovery=False)

    def publish(self, post: Post) -> PostResult:
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload

        service = self.build_service()
        media = MediaFileUpload(str(post.video), chunksize=CHUNK_SIZE, resumable=True)
        request = service.videos().insert(part="snippet,status", body=self.build_body(post), media_body=media)
        response = None
        retries = 0
        while response is None:
            try:
                status, response = request.next_chunk()
                if status:
                    print(f"    YouTube アップロード中… {int(status.progress() * 100)}%")
            except HttpError as e:
                code = getattr(e.resp, "status", 0)
                reason = _http_error_reason(e)
                if code in (500, 502, 503, 504) and retries < 5:
                    retries += 1
                    self.sleep(2 ** retries)
                    continue
                raise PlatformError(_youtube_error_message(code, reason, e)) from e
        video_id = response.get("id", "")
        note = ""
        if response.get("status", {}).get("privacyStatus") == "private" and self.privacy() != "private":
            note = "※ 非公開で登録されました（Google の監査前のプロジェクトは非公開に固定されます）"
        return PostResult(post_id=video_id, url=f"https://www.youtube.com/watch?v={video_id}", note=note)


def _http_error_reason(e) -> str:
    try:
        import json

        data = json.loads(e.content.decode("utf-8"))
        return data["error"]["errors"][0].get("reason", "")
    except Exception:  # noqa: BLE001
        return ""


def _youtube_error_message(code: int, reason: str, e: Exception) -> str:
    messages = {
        "quotaExceeded": "今日の YouTube API の利用上限に達しました。明日（日本時間の夕方以降）に自動で再挑戦します",
        "uploadLimitExceeded": "YouTube チャンネルの1日のアップロード上限に達しました",
        "forbidden": "このチャンネルへのアップロード権限がありません",
        "invalidTitle": "タイトルが不正です",
        "invalidDescription": "説明文が不正です",
        "invalidTags": "タグが不正です",
        "youtubeSignupRequired": "このGoogleアカウントにはYouTubeチャンネルがありません。先にチャンネルを作ってください",
    }
    msg = messages.get(reason, "YouTube への投稿に失敗しました")
    return f"YouTube: {msg}（HTTP {code} {reason}） 詳細: {e}"
