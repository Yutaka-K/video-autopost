from datetime import datetime
from pathlib import Path

import pytest

from autopost.post_parser import PostFileError, parse_datetime, parse_post_folder, parse_tags, parse_targets

ROOT = Path(__file__).resolve().parent.parent


def test_template_is_valid(tmp_path):
    folder = tmp_path / "p"
    folder.mkdir()
    (folder / "投稿内容.txt").write_bytes((ROOT / "投稿待ち" / "_テンプレート" / "投稿内容.txt").read_bytes())
    (folder / "a.mp4").write_bytes(b"x")
    # テンプレートのままだと投稿されない（うっかり投稿の防止）
    with pytest.raises(PostFileError, match="テンプレートのまま"):
        parse_post_folder(folder)
    text = (folder / "投稿内容.txt").read_text(encoding="utf-8").replace("ここにタイトルを書きます", "本番タイトル")
    (folder / "投稿内容.txt").write_text(text, encoding="utf-8")
    post = parse_post_folder(folder)
    assert post.title == "本番タイトル"
    assert post.targets == ["youtube", "tiktok", "x", "threads"]
    assert post.tags == ["タグ1", "タグ2", "タグ3"]
    assert post.schedule == datetime(2026, 12, 1, 18, 0)
    assert "何行でも" in post.description
    assert post.custom_texts == {}


def test_parse_basic(make_post):
    folder = make_post(schedule="2026-11-05 18:00", x="しない")
    post = parse_post_folder(folder)
    assert post.targets == ["youtube", "tiktok", "threads"]
    assert post.video.name == "video.mp4"
    assert not post.is_due(datetime(2026, 11, 5, 17, 59))
    assert post.is_due(datetime(2026, 11, 5, 18, 0))


def test_shift_jis_file(make_post):
    post = parse_post_folder(make_post(title="日本語タイトル", encoding="cp932"))
    assert post.title == "日本語タイトル"


def test_bom_file(make_post):
    post = parse_post_folder(make_post(title="BOM付き", encoding="utf-8-sig"))
    assert post.title == "BOM付き"


@pytest.mark.parametrize("text", ["2026-11-05 18:00", "2026/11/05 18:00", "２０２６／１１／０５　１８：００",
                                  "2026年11月05日 18:00", "2026年11月5日 18時00分"])
def test_datetime_formats(text):
    assert parse_datetime(text) == datetime(2026, 11, 5, 18, 0)


def test_bad_datetime():
    with pytest.raises(PostFileError, match="読み取れません"):
        parse_datetime("来週の月曜")


def test_targets_aliases():
    assert parse_targets("youtube：○\nTwitter: はい\nスレッズ=×\nTikTok: しない") == ["youtube", "x"]


def test_unknown_target():
    with pytest.raises(PostFileError, match="知らないSNS"):
        parse_targets("Instagram: する")


def test_tags():
    assert parse_tags("#京都 #旅行、vlog,京都") == ["京都", "旅行", "vlog"]


def test_missing_video(make_post):
    folder = make_post()
    (folder / "video.mp4").unlink()
    with pytest.raises(PostFileError, match="動画ファイル"):
        parse_post_folder(folder)


def test_no_targets(make_post):
    with pytest.raises(PostFileError, match="投稿先"):
        parse_post_folder(make_post(youtube="しない", tiktok="しない", x="しない", threads="しない"))


def test_custom_text(make_post):
    folder = make_post()
    with open(folder / "投稿内容.txt", "a", encoding="utf-8") as f:
        f.write("【Xの投稿文】\nX専用の文 #タグ\n")
    post = parse_post_folder(folder)
    assert post.custom_texts == {"x": "X専用の文 #タグ"}
