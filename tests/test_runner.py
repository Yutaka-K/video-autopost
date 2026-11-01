"""全体の流れ（投稿 → 記録 → 移動、失敗時の再挑戦、お試しモード）のテスト。"""
from __future__ import annotations

import json
from datetime import datetime

from autopost.config import load_config
from autopost.platforms.base import Platform, PlatformError, PostResult
from autopost.runner import RESULT_FILE, run, setup_logging


class FakePlatform(Platform):
    def __init__(self, config, key, fail_times=0, configured=True):
        super().__init__(config)
        self.key = key
        self.fail_times = fail_times
        self.configured = configured
        self.published = []

    def missing_settings(self):
        return [] if self.configured else ["キーがありません"]

    def preview(self, post):
        return {"投稿文": f"{post.title}（{self.key}）"}

    def publish(self, post):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise PlatformError(f"{self.key} で失敗")
        self.published.append(post.name)
        return PostResult(post_id=f"{self.key}-id", url=f"https://{self.key}/1")


def fakes(config, **overrides):
    result = {k: FakePlatform(config, k) for k in ("youtube", "tiktok", "x", "threads")}
    result.update(overrides)
    return result


def test_success_moves_to_done(base, config, make_post):
    setup_logging(config, quiet=True)
    make_post("投稿A")
    ps = fakes(config)
    summary = run(config, platforms=ps)
    assert summary.posted == ["投稿A"]
    assert not (base / "投稿待ち" / "投稿A").exists()
    done = list((base / "投稿済み").iterdir())
    assert len(done) == 1 and done[0].name.endswith("_投稿A")
    state = json.loads((done[0] / RESULT_FILE).read_text(encoding="utf-8"))
    assert all(v["status"] == "success" for v in state["platforms"].values())
    history = (base / "ログ" / "投稿履歴.csv").read_text(encoding="utf-8-sig")
    assert history.count("成功") == 4


def test_failed_platform_is_retried_only(base, config, make_post):
    setup_logging(config, quiet=True)
    make_post("投稿B")
    ps = fakes(config, x=FakePlatform(config, "x", fail_times=1))
    summary = run(config, platforms=ps)
    assert summary.failed == ["投稿B"]
    folder = base / "投稿待ち" / "投稿B"
    assert folder.exists()
    state = json.loads((folder / RESULT_FILE).read_text(encoding="utf-8"))
    assert state["platforms"]["x"]["status"] == "failed"
    assert state["platforms"]["youtube"]["status"] == "success"

    # 2回目: X だけ再挑戦し、成功したら移動
    summary = run(config, platforms=ps)
    assert summary.posted == ["投稿B"]
    assert ps["youtube"].published == ["投稿B"]  # YouTube は二重投稿しない
    assert ps["x"].published == ["投稿B"]


def test_give_up_after_max_retry(base, make_post):
    config = load_config(base, extra={"MAX_RETRY": "2"})
    setup_logging(config, quiet=True)
    make_post("投稿C", youtube="しない", tiktok="しない", threads="しない")
    ps = fakes(config, x=FakePlatform(config, "x", fail_times=10))
    run(config, platforms=ps)
    summary = run(config, platforms=ps)
    assert summary.gave_up == ["投稿C"]
    assert len(list((base / "投稿失敗").iterdir())) == 1


def test_skip_disabled_and_unconfigured(base, make_post):
    config = load_config(base, extra={"TIKTOK_ENABLED": "false"})
    setup_logging(config, quiet=True)
    make_post("投稿D")
    ps = fakes(config, threads=FakePlatform(config, "threads", configured=False))
    summary = run(config, platforms=ps)
    assert summary.posted == ["投稿D"]
    assert ps["tiktok"].published == [] and ps["threads"].published == []
    state = json.loads(next((base / "投稿済み").iterdir()).joinpath(RESULT_FILE).read_text(encoding="utf-8"))
    assert state["platforms"]["tiktok"]["status"] == "skipped"
    assert "オフ" in state["platforms"]["tiktok"]["reason"]
    assert state["platforms"]["threads"]["status"] == "skipped"


def test_not_due_waits(base, config, make_post):
    setup_logging(config, quiet=True)
    make_post("投稿E", schedule="2030-01-01 10:00")
    ps = fakes(config)
    summary = run(config, platforms=ps, now=datetime(2029, 12, 31, 23, 0))
    assert summary.waiting == ["投稿E"]
    assert ps["youtube"].published == []
    summary = run(config, platforms=ps, now=datetime(2030, 1, 1, 10, 0))
    assert summary.posted == ["投稿E"]


def test_dry_run_changes_nothing(base, config, make_post, capsys):
    setup_logging(config, quiet=False)
    make_post("投稿F", title="お試しタイトル", schedule="2030-01-01 10:00")
    ps = fakes(config)
    run(config, dry_run=True, platforms=ps)
    out = capsys.readouterr().err
    assert "お試しモード" in out
    assert "お試しタイトル（youtube）" in out
    assert ps["youtube"].published == []
    assert (base / "投稿待ち" / "投稿F").exists()
    assert not (base / "投稿待ち" / "投稿F" / RESULT_FILE).exists()


def test_bad_post_file_is_reported(base, config):
    setup_logging(config, quiet=True)
    folder = base / "投稿待ち" / "壊れた投稿"
    folder.mkdir()
    (folder / "投稿内容.txt").write_text("【タイトル】\n\n【投稿先】\nYouTube: する\n", encoding="utf-8")
    summary = run(config, platforms=fakes(config))
    assert summary.errors == ["壊れた投稿"]
    assert folder.exists()


def test_template_folder_is_ignored(base, config):
    setup_logging(config, quiet=True)
    (base / "投稿待ち" / "_テンプレート").mkdir()
    summary = run(config, platforms=fakes(config))
    assert summary.errors == [] and summary.posted == []


def test_real_platforms_dry_run_without_keys(base, make_post, capsys):
    """本物のSNSクラスでも、キー未設定ならスキップ表示になり、通信しないこと。"""
    config = load_config(base)
    setup_logging(config, quiet=False)
    make_post("投稿G", description="あ" * 1000)
    summary = run(config, dry_run=True)
    err = capsys.readouterr().err
    assert err.count("スキップ") >= 4
    assert "/ 280" in err
    assert summary.posted == []


def test_all_skipped_stays_pending(base, config, make_post):
    setup_logging(config, quiet=True)
    make_post("投稿H")
    ps = {k: FakePlatform(config, k, configured=False) for k in ("youtube", "tiktok", "x", "threads")}
    summary = run(config, platforms=ps)
    assert summary.waiting == ["投稿H"] and summary.posted == []
    assert (base / "投稿待ち" / "投稿H").exists()
    # 設定が終わったら投稿される
    summary = run(config, platforms=fakes(config))
    assert summary.posted == ["投稿H"]
