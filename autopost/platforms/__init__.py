"""SNSごとの投稿処理。新しいSNSを追加するときは、ファイルを作ってここに登録します。"""
from __future__ import annotations

from ..config import Config
from .base import Platform, PlatformError, PostResult
from .threads import Threads
from .tiktok import TikTok
from .x import X
from .youtube import YouTube

# 投稿する順番（まず YouTube）
PLATFORM_CLASSES: dict[str, type[Platform]] = {
    "youtube": YouTube,
    "tiktok": TikTok,
    "x": X,
    "threads": Threads,
}


def create_platforms(config: Config) -> dict[str, Platform]:
    return {key: cls(config) for key, cls in PLATFORM_CLASSES.items()}


__all__ = ["Platform", "PlatformError", "PostResult", "PLATFORM_CLASSES", "create_platforms"]
