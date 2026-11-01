"""SNSごとの文字数制限に合わせて、投稿文を自動で短くする処理。"""
from __future__ import annotations

import re
from typing import Callable

from .post_parser import Post

Counter = Callable[[str], int]
ELLIPSIS = "…"

# 各SNSの上限（2026年11月時点の公式ドキュメント／公開情報より）
LIMITS = {
    "youtube_title": 100,        # 文字
    "youtube_description": 5000,  # バイト（UTF-8）
    "youtube_tags_total": 500,    # 文字（タグ全体）
    "tiktok": 2200,              # 文字（UTF-16単位）
    "x": 280,                    # 重み付き文字数（日本語は1文字=2として数える）
    "threads": 500,              # 文字
}

_URL_RE = re.compile(r"https?://\S+")


def count_chars(text: str) -> int:
    return len(text)


def count_utf8_bytes(text: str) -> int:
    return len(text.encode("utf-8"))


def count_utf16(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _x_char_weight(ch: str) -> int:
    cp = ord(ch)
    # twitter-text v3 の設定: これらの範囲は1、それ以外（日本語・絵文字など）は2
    if (0 <= cp <= 4351) or (8192 <= cp <= 8205) or (8208 <= cp <= 8223) or (8242 <= cp <= 8247):
        return 1
    return 2


def count_x(text: str) -> int:
    """X の数え方。URL はどんな長さでも23文字、日本語・絵文字は2文字として数える。"""
    total = 0
    pos = 0
    for m in _URL_RE.finditer(text):
        total += sum(_x_char_weight(c) for c in text[pos:m.start()])
        total += 23
        pos = m.end()
    total += sum(_x_char_weight(c) for c in text[pos:])
    return total


def truncate(text: str, limit: int, counter: Counter, ellipsis: str = ELLIPSIS) -> str:
    """text を limit 以内に切り詰める（切ったときは末尾に … を付ける）。"""
    if counter(text) <= limit:
        return text
    if counter(ellipsis) > limit:
        return ""
    lo, hi = 0, len(text)
    while lo < hi:  # 入る最大の長さを二分探索
        mid = (lo + hi + 1) // 2
        if counter(text[:mid].rstrip() + ellipsis) <= limit:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + ellipsis


def fit_parts(head: str, body: str, tail: str, limit: int, counter: Counter) -> str:
    """「見出し」「本文」「末尾（ハッシュタグ）」を組み合わせて limit 以内にする。

    はみ出したら、まず本文を短くする → それでもダメならハッシュタグを減らす → 最後に見出しを切る。
    """
    def join(*parts: str) -> str:
        return "\n\n".join(p for p in parts if p)

    full = join(head, body, tail)
    if counter(full) <= limit:
        return full

    # 1) 本文を短くする
    if body:
        fixed = counter(join(head, "X", tail)) - counter("X")
        room = limit - fixed
        if room >= 10:
            return join(head, truncate(body, room, counter), tail)

    # 2) ハッシュタグを後ろから減らす
    tags = tail.split()
    while tags:
        tags.pop()
        candidate = join(head, " ".join(tags))
        if counter(candidate) <= limit:
            return candidate

    # 3) 見出しだけを切り詰める
    return truncate(head, limit, counter)


def hashtags(tags: list[str], max_count: int | None = None) -> str:
    items = ["#" + re.sub(r"\s+", "", t) for t in tags if t.strip()]
    if max_count is not None:
        items = items[:max_count]
    return " ".join(items)


# ---------------------------------------------------------------------
#  SNSごとの投稿文を作る
# ---------------------------------------------------------------------
def youtube_title(post: Post) -> str:
    title = post.title.replace("<", "＜").replace(">", "＞")  # YouTube は < > が使えない
    return truncate(title, LIMITS["youtube_title"], count_chars)


def youtube_description(post: Post) -> str:
    text = post.custom_texts.get("youtube", post.description)
    text = text.replace("<", "＜").replace(">", "＞")
    return truncate(text, LIMITS["youtube_description"], count_utf8_bytes)


def youtube_tags(post: Post) -> list[str]:
    """YouTube のタグは合計500文字まで（スペースを含むタグは "" の2文字分も数える）。"""
    result: list[str] = []
    total = 0
    for tag in post.tags:
        tag = tag.replace("<", "").replace(">", "").strip()
        if not tag:
            continue
        size = len(tag) + (2 if " " in tag else 0)
        extra = 1 if result else 0  # 区切りのカンマ
        if total + size + extra > LIMITS["youtube_tags_total"]:
            break
        result.append(tag)
        total += size + extra
    return result


def social_text(post: Post, platform: str) -> str:
    """TikTok / X / Threads 用の投稿文を作る。"""
    limits = {
        "tiktok": (LIMITS["tiktok"], count_utf16, None),
        "x": (LIMITS["x"], count_x, None),
        "threads": (LIMITS["threads"], count_chars, 1),  # Threads はトピックタグが1投稿1つまで
    }
    limit, counter, max_tags = limits[platform]
    custom = post.custom_texts.get(platform)
    if custom:
        return truncate(custom, limit, counter)
    return fit_parts(post.title, post.description, hashtags(post.tags, max_tags), limit, counter)
