"""テスト共通の準備。実際のSNSには一切アクセスしません。"""
from __future__ import annotations

from pathlib import Path

import pytest

from autopost.config import load_config

POST_TEXT = """【タイトル】
{title}
【説明文】
{description}
【タグ】
{tags}
【投稿日時】
{schedule}
【投稿先】
YouTube: {youtube}
TikTok: {tiktok}
X: {x}
Threads: {threads}
【動画URL】
{video_url}
"""


@pytest.fixture
def base(tmp_path: Path) -> Path:
    for d in ("投稿待ち", "投稿済み", "投稿失敗", "ログ", "tokens"):
        (tmp_path / d).mkdir()
    return tmp_path


@pytest.fixture
def config(base):
    return load_config(base, extra={})


@pytest.fixture
def make_post(base):
    def _make(name="テスト投稿", title="テスト動画", description="説明文です", tags="旅行, vlog",
              schedule="", youtube="する", tiktok="する", x="する", threads="する", video_url="",
              video_size=1024, encoding="utf-8"):
        folder = base / "投稿待ち" / name
        folder.mkdir(parents=True)
        (folder / "video.mp4").write_bytes(b"\0" * video_size)
        text = POST_TEXT.format(title=title, description=description, tags=tags, schedule=schedule,
                                youtube=youtube, tiktok=tiktok, x=x, threads=threads, video_url=video_url)
        (folder / "投稿内容.txt").write_bytes(text.encode(encoding))
        return folder
    return _make
