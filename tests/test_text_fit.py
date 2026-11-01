from pathlib import Path

from autopost import text_fit
from autopost.post_parser import Post


def make(title="タイトル", description="", tags=None, custom=None):
    return Post(folder=Path("."), video=None, title=title, description=description,
                tags=tags or [], custom_texts=custom or {})


def test_count_x():
    assert text_fit.count_x("abc") == 3
    assert text_fit.count_x("あいう") == 6
    assert text_fit.count_x("見て https://example.com/" + "a" * 100) == 4 + 1 + 23


def test_x_long_text_is_trimmed_but_keeps_tags():
    post = make(description="あ" * 1000, tags=["京都", "旅行"])
    text = text_fit.social_text(post, "x")
    assert text_fit.count_x(text) <= 280
    assert text.endswith("#京都 #旅行")
    assert "…" in text


def test_short_text_unchanged():
    post = make(description="短い", tags=["a"])
    assert text_fit.social_text(post, "threads") == "タイトル\n\n短い\n\n#a"


def test_threads_only_one_tag():
    post = make(tags=["a", "b", "c"])
    assert text_fit.social_text(post, "threads").endswith("#a")


def test_threads_limit():
    post = make(description="い" * 2000, tags=["a"])
    assert len(text_fit.social_text(post, "threads")) <= 500


def test_tiktok_limit_utf16_emoji():
    post = make(description="😀" * 3000)
    assert text_fit.count_utf16(text_fit.social_text(post, "tiktok")) <= 2200


def test_custom_text_is_used():
    post = make(description="本文", custom={"x": "専用"})
    assert text_fit.social_text(post, "x") == "専用"


def test_youtube_title_and_description():
    post = make(title="<タイトル>" + "あ" * 200, description="う" * 3000)
    assert len(text_fit.youtube_title(post)) <= 100
    assert "<" not in text_fit.youtube_title(post)
    assert len(text_fit.youtube_description(post).encode("utf-8")) <= 5000


def test_youtube_tags_total():
    post = make(tags=[f"タグ{i:03d}" * 3 for i in range(100)])
    tags = text_fit.youtube_tags(post)
    assert sum(len(t) for t in tags) + len(tags) - 1 <= 500
    assert 0 < len(tags) < 100


def test_very_long_title_for_x():
    post = make(title="長" * 500, tags=["a"])
    assert text_fit.count_x(text_fit.social_text(post, "x")) <= 280
