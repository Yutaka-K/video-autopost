"""各SNSの投稿処理を、偽のAPI応答（モック）で確認するテスト。"""
from __future__ import annotations

import json
import time

import pytest
import responses
from responses import matchers

from autopost.config import load_config
from autopost.platforms.base import PlatformError
from autopost.platforms.threads import Threads
from autopost.platforms.tiktok import TikTok, chunk_plan
from autopost.platforms.x import X
from autopost.platforms.youtube import YouTube
from autopost.post_parser import parse_post_folder

no_sleep = lambda s: None  # noqa: E731


# ---------------------------------------------------------------- YouTube
class FakeYouTube(YouTube):
    """Google のサーバーの代わりに、決められた応答を返す。"""

    def __init__(self, config, sequence):
        super().__init__(config, sleep=no_sleep)
        self.sequence = sequence

    def build_service(self):
        from googleapiclient.discovery import build
        from googleapiclient.http import HttpMockSequence

        class Recording(HttpMockSequence):
            def request(inner, uri, method="GET", body=None, headers=None, *a, **kw):  # noqa: N805
                inner.calls.append((method, uri, body))
                return super().request(uri, method, body, headers, *a, **kw)

        self.http = Recording(self.sequence)
        self.http.calls = []
        return build("youtube", "v3", http=self.http, static_discovery=True, cache_discovery=False)


def test_youtube_missing_settings(config):
    missing = YouTube(config).missing_settings()
    assert any("client_secret.json" in m for m in missing)
    assert any("ログイン" in m for m in missing)


def test_youtube_publish(base, make_post):
    config = load_config(base, extra={"YOUTUBE_PRIVACY": "public"})
    post = parse_post_folder(make_post(title="京都の動画", tags="京都, 旅行"))
    yt = FakeYouTube(config, [
        ({"status": "200", "location": "https://upload.example/session1"}, ""),
        ({"status": "200"}, json.dumps({"id": "VID123", "status": {"privacyStatus": "public"}})),
    ])
    result = yt.publish(post)
    assert result.post_id == "VID123"
    assert result.url == "https://www.youtube.com/watch?v=VID123"
    assert result.note == ""
    # 1回目のリクエストに、タイトル・タグ・公開設定が入っていること
    method, uri, body = yt.http.calls[0]
    assert method == "POST" and "uploadType=resumable" in uri
    sent = json.loads(body)
    assert sent["snippet"]["title"] == "京都の動画"
    assert sent["snippet"]["tags"] == ["京都", "旅行"]
    assert sent["status"]["privacyStatus"] == "public"


def test_youtube_locked_private_note(base, make_post):
    config = load_config(base, extra={"YOUTUBE_PRIVACY": "public"})
    post = parse_post_folder(make_post())
    yt = FakeYouTube(config, [
        ({"status": "200", "location": "https://upload.example/s"}, ""),
        ({"status": "200"}, json.dumps({"id": "V", "status": {"privacyStatus": "private"}})),
    ])
    assert "非公開" in yt.publish(post).note


def test_youtube_quota_error(base, make_post):
    config = load_config(base)
    post = parse_post_folder(make_post())
    err = json.dumps({"error": {"code": 403, "errors": [{"reason": "quotaExceeded"}], "message": "quota"}})
    yt = FakeYouTube(config, [({"status": "403"}, err)])
    with pytest.raises(PlatformError, match="利用上限"):
        yt.publish(post)


def test_youtube_body(base, make_post):
    config = load_config(base, extra={"YOUTUBE_PRIVACY": "unlisted", "YOUTUBE_CATEGORY_ID": "24"})
    post = parse_post_folder(make_post(title="タイトル", tags="a, b"))
    body = YouTube(config).build_body(post)
    assert body["snippet"]["tags"] == ["a", "b"]
    assert body["snippet"]["categoryId"] == "24"
    assert body["status"]["privacyStatus"] == "unlisted"


# ---------------------------------------------------------------- TikTok
def tiktok_config(base, **extra):
    values = {"TIKTOK_CLIENT_KEY": "ck", "TIKTOK_CLIENT_SECRET": "cs"}
    values.update(extra)
    config = load_config(base, extra=values)
    (config.token_dir / "tiktok_token.json").write_text(json.dumps({
        "access_token": "act", "refresh_token": "rft",
        "expires_at": time.time() + 3600, "refresh_expires_at": time.time() + 100000,
    }), encoding="utf-8")
    return config


def test_tiktok_chunk_plan():
    MB = 1024 * 1024
    assert chunk_plan(3 * MB) == (3 * MB, 1)
    assert chunk_plan(9 * MB) == (9 * MB, 1)
    size = 50_000_123
    chunk, count = chunk_plan(size)
    assert chunk == 10 * MB and count == size // chunk
    assert size - chunk * (count - 1) <= 128 * MB  # 最後のチャンクは128MBまで


@responses.activate
def test_tiktok_direct_post(base, make_post):
    config = tiktok_config(base, TIKTOK_PRIVACY="PUBLIC_TO_EVERYONE")
    post = parse_post_folder(make_post(video_size=2048))
    api = "https://open.tiktokapis.com/v2/post/publish"
    ok = {"error": {"code": "ok", "message": ""}}
    responses.post(api + "/creator_info/query/", json={"data": {"privacy_level_options": ["SELF_ONLY"]}, **ok},
                   match=[matchers.header_matcher({"Authorization": "Bearer act"})])
    responses.post(api + "/video/init/", json={"data": {"publish_id": "p1", "upload_url": "https://up.tiktok/x"}, **ok})
    responses.put("https://up.tiktok/x", status=201,
                  match=[matchers.header_matcher({"Content-Range": "bytes 0-2047/2048"})])
    responses.post(api + "/status/fetch/", json={"data": {"status": "PROCESSING_UPLOAD"}, **ok})
    responses.post(api + "/status/fetch/", json={"data": {"status": "PUBLISH_COMPLETE",
                                                          "publicaly_available_post_id": [777]}, **ok})
    result = TikTok(config, sleep=no_sleep).publish(post)
    assert result.post_id == "777"
    init_body = json.loads(responses.calls[1].request.body)
    # 審査前で PUBLIC が使えないので SELF_ONLY に自動で切り替わる
    assert init_body["post_info"]["privacy_level"] == "SELF_ONLY"
    assert init_body["source_info"] == {"source": "FILE_UPLOAD", "video_size": 2048,
                                        "chunk_size": 2048, "total_chunk_count": 1}
    assert "自分のみ" in result.note


@responses.activate
def test_tiktok_inbox_mode(base, make_post):
    config = tiktok_config(base, TIKTOK_MODE="inbox")
    post = parse_post_folder(make_post())
    api = "https://open.tiktokapis.com/v2/post/publish"
    ok = {"error": {"code": "ok"}}
    responses.post(api + "/inbox/video/init/", json={"data": {"publish_id": "p2", "upload_url": "https://up/y"}, **ok})
    responses.put("https://up/y", status=201)
    responses.post(api + "/status/fetch/", json={"data": {"status": "SEND_TO_USER_INBOX"}, **ok})
    result = TikTok(config, sleep=no_sleep).publish(post)
    assert "受信トレイ" in result.note


@responses.activate
def test_tiktok_unaudited_error(base, make_post):
    config = tiktok_config(base)
    post = parse_post_folder(make_post())
    api = "https://open.tiktokapis.com/v2/post/publish"
    responses.post(api + "/creator_info/query/", json={"data": {}, "error": {"code": "ok"}})
    responses.post(api + "/video/init/", status=403, json={
        "error": {"code": "unaudited_client_can_only_post_to_private_accounts", "message": "x"}})
    with pytest.raises(PlatformError, match="非公開アカウント"):
        TikTok(config, sleep=no_sleep).publish(post)


@responses.activate
def test_tiktok_token_refresh(base):
    config = tiktok_config(base)
    tok = json.loads((config.token_dir / "tiktok_token.json").read_text())
    tok["expires_at"] = 0
    (config.token_dir / "tiktok_token.json").write_text(json.dumps(tok))
    responses.post("https://open.tiktokapis.com/v2/oauth/token/", json={
        "access_token": "new", "refresh_token": "rft2", "expires_in": 86400, "refresh_expires_in": 31536000})
    assert TikTok(config).access_token() == "new"
    assert "grant_type=refresh_token" in responses.calls[0].request.body
    assert json.loads((config.token_dir / "tiktok_token.json").read_text())["refresh_token"] == "rft2"


# ---------------------------------------------------------------- X
def x_config(base):
    return load_config(base, extra={"X_API_KEY": "k", "X_API_SECRET": "s",
                                    "X_ACCESS_TOKEN": "t", "X_ACCESS_TOKEN_SECRET": "ts"})


def test_x_missing(config):
    assert "X_ACCESS_TOKEN_SECRET" in X(config).missing_settings()[0]


@responses.activate
def test_x_publish(base, make_post, monkeypatch):
    import autopost.platforms.x as xmod

    monkeypatch.setattr(xmod, "SEGMENT", 1000)  # 3回に分けて送られるように
    config = x_config(base)
    post = parse_post_folder(make_post(video_size=2500, description="あ" * 500))
    responses.post("https://api.x.com/2/media/upload/initialize", json={"data": {"id": "M1"}})
    responses.post("https://api.x.com/2/media/upload/M1/append", status=200, body="")
    responses.post("https://api.x.com/2/media/upload/M1/finalize", json={
        "data": {"id": "M1", "processing_info": {"state": "pending", "check_after_secs": 1}}})
    responses.get("https://api.x.com/2/media/upload", json={
        "data": {"id": "M1", "processing_info": {"state": "succeeded"}}})
    responses.post("https://api.x.com/2/tweets", json={"data": {"id": "T1", "text": "..."}})

    result = X(config, sleep=no_sleep).publish(post)
    assert result.url == "https://x.com/i/status/T1"
    calls = [c.request.url.split("?")[0] for c in responses.calls]
    assert calls.count("https://api.x.com/2/media/upload/M1/append") == 3
    init = json.loads(responses.calls[0].request.body)
    assert init == {"media_type": "video/mp4", "total_bytes": 2500, "media_category": "amplify_video"}
    tweet = json.loads(responses.calls[-1].request.body)
    assert tweet["media"] == {"media_ids": ["M1"]}
    from autopost.text_fit import count_x
    assert count_x(tweet["text"]) <= 280
    assert responses.calls[0].request.headers["Authorization"].startswith(b"OAuth ")


@responses.activate
def test_x_payment_required(base, make_post):
    config = x_config(base)
    post = parse_post_folder(make_post())
    responses.post("https://api.x.com/2/media/upload/initialize", status=402, json={"title": "CreditsDepleted"})
    with pytest.raises(PlatformError, match="クレジット"):
        X(config, sleep=no_sleep).publish(post)


# ---------------------------------------------------------------- Threads
class FakeHosting:
    def __init__(self):
        self.deleted = []

    def upload(self, video):
        return "key1", "https://bucket.example/key1?sig=abc"

    def delete(self, key):
        self.deleted.append(key)


def threads_config(base, **extra):
    values = {"THREADS_ACCESS_TOKEN": "th", "S3_ENDPOINT_URL": "https://r2", "S3_ACCESS_KEY_ID": "a",
              "S3_SECRET_ACCESS_KEY": "b", "S3_BUCKET": "c"}
    values.update(extra)
    return load_config(base, extra=values)


def test_threads_missing_s3(base):
    config = load_config(base, extra={"THREADS_ACCESS_TOKEN": "th"})
    assert any("S3_BUCKET" in m for m in Threads(config).missing_settings())
    config = load_config(base, extra={"THREADS_ACCESS_TOKEN": "th", "THREADS_VIDEO_HOSTING": "manual"})
    assert Threads(config).missing_settings() == []


@responses.activate
def test_threads_publish_with_s3(base, make_post):
    config = threads_config(base)
    post = parse_post_folder(make_post(tags="京都, 旅行"))
    g = "https://graph.threads.net"
    responses.get(g + "/refresh_access_token", json={"access_token": "th2", "expires_in": 5184000})
    responses.post(g + "/v1.0/me/threads", json={"id": "C1"})
    responses.get(g + "/v1.0/C1", json={"status": "IN_PROGRESS"})
    responses.get(g + "/v1.0/C1", json={"status": "FINISHED"})
    responses.post(g + "/v1.0/me/threads_publish", json={"id": "TH1"})
    responses.get(g + "/v1.0/TH1", json={"permalink": "https://www.threads.com/@me/post/abc"})
    hosting = FakeHosting()
    result = Threads(config, sleep=no_sleep, hosting=hosting).publish(post)
    assert result.post_id == "TH1"
    assert result.url.endswith("/abc")
    assert hosting.deleted == ["key1"]  # 一時ファイルは削除される
    create = responses.calls[1].request.body
    assert "video_url=https%3A%2F%2Fbucket.example%2Fkey1" in create
    assert "media_type=VIDEO" in create
    assert "access_token=th2" in create  # 延長後のトークンを使う


@responses.activate
def test_threads_video_error_still_deletes(base, make_post):
    config = threads_config(base)
    post = parse_post_folder(make_post())
    g = "https://graph.threads.net"
    responses.get(g + "/refresh_access_token", status=400, json={"error": {}})
    responses.post(g + "/v1.0/me/threads", json={"id": "C1"})
    responses.get(g + "/v1.0/C1", json={"status": "ERROR", "error_message": "bad video"})
    hosting = FakeHosting()
    with pytest.raises(PlatformError, match="bad video"):
        Threads(config, sleep=no_sleep, hosting=hosting).publish(post)
    assert hosting.deleted == ["key1"]


def test_threads_manual_requires_url(base, make_post):
    config = threads_config(base, THREADS_VIDEO_HOSTING="manual")
    post = parse_post_folder(make_post())
    th = Threads(config, sleep=no_sleep)
    th.access_token = lambda: "th"
    with pytest.raises(PlatformError, match="動画URL"):
        th.publish(post)
