"""「投稿内容.txt」を読み取る処理。

書き方の例（テンプレートは 投稿待ち/_テンプレート/投稿内容.txt にあります）:

    【タイトル】
    夏の京都を歩いてみた
    【説明文】
    今日は京都の…（複数行OK）
    【タグ】
    京都, 旅行, vlog
    【投稿日時】
    2026-11-05 18:00
    【投稿先】
    YouTube: する
    TikTok: する
    X: しない
    Threads: する
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

POST_FILE_NAME = "投稿内容.txt"
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}

# 見出しの名前 → 内部の名前
SECTION_ALIASES = {
    "タイトル": "title",
    "説明文": "description",
    "説明": "description",
    "タグ": "tags",
    "ハッシュタグ": "tags",
    "投稿日時": "schedule",
    "日時": "schedule",
    "投稿先": "targets",
    "投稿先sns": "targets",
    "動画url": "video_url",
    "youtubeの説明文": "text_youtube",
    "tiktokの投稿文": "text_tiktok",
    "xの投稿文": "text_x",
    "threadsの投稿文": "text_threads",
}

PLATFORM_ALIASES = {
    "youtube": "youtube",
    "ユーチューブ": "youtube",
    "tiktok": "tiktok",
    "ティックトック": "tiktok",
    "x": "x",
    "twitter": "x",
    "ツイッター": "x",
    "エックス": "x",
    "threads": "threads",
    "スレッズ": "threads",
}

YES_WORDS = {"する", "はい", "yes", "y", "on", "true", "1", "○", "〇", "◯", "o", "出す", "投稿する"}
NO_WORDS = {"しない", "いいえ", "no", "n", "off", "false", "0", "×", "x", "✕", "出さない", "投稿しない", ""}

DATE_FORMATS = [
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y年%m月%d日 %H:%M",
    "%Y年%m月%d日 %H時%M分",
    "%Y-%m-%d",
    "%Y/%m/%d",
]

_HEADER_RE = re.compile(r"^\s*[【\[]\s*(.+?)\s*[】\]]\s*$")


class PostFileError(Exception):
    """投稿内容.txt の書き方に問題があるときのエラー。"""


@dataclass
class Post:
    folder: Path
    video: Path | None
    title: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    schedule: datetime | None = None
    targets: list[str] = field(default_factory=list)
    video_url: str = ""
    custom_texts: dict[str, str] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.folder.name

    def is_due(self, now: datetime | None = None) -> bool:
        if self.schedule is None:
            return True
        return (now or datetime.now()) >= self.schedule


def read_text_file(path: Path) -> str:
    """メモ帳で保存した文字コード（UTF-8 / BOM付き / Shift_JIS）どれでも読めるようにする。"""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp932", "utf-16"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise PostFileError(f"{path.name} の文字コードが読み取れません。メモ帳で「UTF-8」を選んで保存し直してください。")


def parse_datetime(text: str) -> datetime:
    t = text.strip()
    # 全角数字・全角記号を半角に
    t = t.translate(str.maketrans("０１２３４５６７８９／：－　", "0123456789/:- "))
    t = re.sub(r"\s+", " ", t)
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(t, fmt)
        except ValueError:
            continue
    raise PostFileError(
        f"投稿日時「{text.strip()}」が読み取れません。「2026-11-05 18:00」のように書いてください。"
    )


def parse_targets(text: str) -> list[str]:
    targets: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(.+?)\s*[:：=＝]\s*(.*)$", line)
        if not m:
            raise PostFileError(f"【投稿先】の「{line}」が読み取れません。「YouTube: する」のように書いてください。")
        name = m.group(1).strip().lower()
        answer = m.group(2).strip().lower()
        platform = PLATFORM_ALIASES.get(name)
        if platform is None:
            raise PostFileError(
                f"【投稿先】の「{m.group(1).strip()}」は知らないSNSです。YouTube / TikTok / X / Threads のどれかを書いてください。"
            )
        if answer in YES_WORDS:
            if platform not in targets:
                targets.append(platform)
        elif answer in NO_WORDS:
            continue
        else:
            raise PostFileError(f"【投稿先】の「{line}」は「する」か「しない」で書いてください。")
    return targets


def parse_tags(text: str) -> list[str]:
    text = re.sub(r"[#＃]", ",", text)
    parts = re.split(r"[,、，\n]+", text)
    tags = []
    for p in parts:
        p = p.strip()
        if p and p not in tags:
            tags.append(p)
    return tags


def split_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        m = _HEADER_RE.match(line)
        if m:
            key = SECTION_ALIASES.get(m.group(1).strip().lower().replace(" ", ""))
            if key is None:
                raise PostFileError(f"見出し【{m.group(1)}】は使えません。テンプレートの見出しを使ってください。")
            current = key
            sections[current] = []
            continue
        if current is None:
            continue  # 最初の見出しより前の行（説明メモなど）は無視
        if line.lstrip().startswith("#") and current not in ("description", "tags") and not current.startswith("text_"):
            continue  # メモ行
        sections[current].append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def find_video(folder: Path) -> Path | None:
    videos = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS)
    if len(videos) > 1:
        raise PostFileError(
            f"動画ファイルが{len(videos)}個あります。1つのフォルダには動画を1つだけ入れてください: "
            + ", ".join(v.name for v in videos)
        )
    return videos[0] if videos else None


def parse_post_folder(folder: Path) -> Post:
    post_file = folder / POST_FILE_NAME
    if not post_file.exists():
        raise PostFileError(f"「{POST_FILE_NAME}」がありません。テンプレートをコピーして入れてください。")
    sections = split_sections(read_text_file(post_file))

    title = sections.get("title", "").replace("\n", " ").strip()
    if not title:
        raise PostFileError("【タイトル】が空です。タイトルを書いてください。")

    if title == "ここにタイトルを書きます":
        raise PostFileError("タイトルがテンプレートのままです。投稿内容.txt を書き換えてください。")

    targets = parse_targets(sections.get("targets", ""))
    if not targets:
        raise PostFileError("【投稿先】で「する」になっているSNSがありません。")

    schedule_text = sections.get("schedule", "").strip()
    schedule = parse_datetime(schedule_text) if schedule_text else None

    video_url = sections.get("video_url", "").strip()
    video = find_video(folder)
    if video is None:
        raise PostFileError("動画ファイル（.mp4 など）がフォルダに入っていません。")

    custom = {}
    for key, value in sections.items():
        if key.startswith("text_") and value:
            custom[key[5:]] = value

    return Post(
        folder=folder,
        video=video,
        title=title,
        description=sections.get("description", ""),
        tags=parse_tags(sections.get("tags", "")),
        schedule=schedule,
        targets=targets,
        video_url=video_url,
        custom_texts=custom,
    )
