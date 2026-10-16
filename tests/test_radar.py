import json
from datetime import datetime, timezone

from conftest import FIX

from radar import classify, config, pipeline, report, scheduler, store
from radar.sources import news, telegram


def test_parse_telegram_page():
    msgs = telegram.parse_page((FIX / "tg_page.html").read_text(), "testcargo")
    ids = [m["ext_id"] for m in msgs]
    assert ids == ["101", "102", "104"]  # 103 只有图片，跳过
    assert "09121234567" in msgs[0]["text"]
    assert msgs[1]["posted_at"] == "2026-10-15T08:00:00+00:00"
    assert msgs[1]["url"] == "https://t.me/testcargo/102"


def test_parse_news_feed():
    items = news.parse_feed((FIX / "news.xml").read_text(), "Irkeshtam border")
    assert len(items) == 1
    assert items[0]["text"].startswith("Irkeshtam checkpoint to close")
    assert "AKIpress" in items[0]["text"]
    assert items[0]["posted_at"].startswith("2026-10-15")


def test_normalize_channel():
    for raw in ("@amadgaran", "amadgaran", "https://t.me/amadgaran", "t.me/s/amadgaran", "https://t.me/amadgaran/55"):
        assert config.normalize_channel(raw) == "amadgaran"


def test_parse_results_tolerates_wrapping():
    out = classify.parse_results('好的：\n{"results": [{"id": 1, "category": "lead", "score": 0.9}]}')
    assert out[0]["id"] == 1
    cat, score, fields = classify.clean({"category": "SPAM", "score": "7"})
    assert cat == "noise" and score == 1.0 and fields["contact"] == ""


def fake_llm(model_cfg, system, user):
    items = json.loads(user)
    res = []
    for it in items:
        t = it["内容"]
        if "Машхад" in t or "تهران" in t:
            res.append({"id": it["id"], "category": "lead", "score": 0.9, "summary_zh": "求车",
                        "origin": "霍尔果斯" if "Хоргос" in t else "义乌", "destination": "伊朗",
                        "contact": "@buyer_ir" if "@buyer_ir" in t else "09121234567",
                        "fit": "霍尔果斯线", "action_zh": "私信报价"})
        elif "Irkeshtam" in t:
            res.append({"id": it["id"], "category": "policy", "score": 0.8, "summary_zh": "伊尔克什坦口岸 10/20–22 关闭"})
        else:
            res.append({"id": it["id"], "category": "noise", "score": 0})
    return json.dumps({"results": res}, ensure_ascii=False)


def _patch_sources(monkeypatch):
    page = (FIX / "tg_page.html").read_text()
    feed = (FIX / "news.xml").read_text()
    monkeypatch.setattr(telegram, "http_get", lambda url: page)
    monkeypatch.setattr(news, "http_get", lambda url: feed)
    monkeypatch.setattr(classify, "_chat", fake_llm)
    monkeypatch.setenv("XAI_API_KEY", "test")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)


def test_end_to_end(radar_env, monkeypatch):
    _patch_sources(monkeypatch)
    r = pipeline.collect()
    assert r["added"] == 4 and r["classified"] == 4 and not r["errors"]
    # 第二次运行不重复入库
    assert pipeline.collect()["added"] == 0

    leads = store.query_items(category="lead")
    assert len(leads) == 2
    assert {l["fields"]["contact"] for l in leads} == {"@buyer_ir", "09121234567"}

    b = pipeline.brief(push=True, collect_first=False)
    md = b["markdown"]
    assert "询价线索（2）" in md and "口岸与政策（1）" in md
    assert "Happy Friday" not in md
    # 发过的不会第二天再出现
    assert pipeline.brief(push=False, collect_first=False)["items"] == 0
    assert (radar_env.DATA_DIR / "briefs").exists()

    lead_id = leads[0]["id"]
    assert store.update_status(lead_id, "won", "报了 4200 美金")
    stats = store.source_stats()
    tg = next(s for s in stats if s["channel"] == "testcargo")
    assert tg["leads"] == 2 and tg["won"] == 1 and tg["noise"] == 1


def test_classify_failure_keeps_items_for_retry(radar_env, monkeypatch):
    _patch_sources(monkeypatch)

    def boom(*a, **k):
        raise TimeoutError("timeout")

    monkeypatch.setattr(classify, "_chat", boom)
    r = pipeline.collect()
    assert r["classified"] == 0 and r["errors"]
    assert len(store.unclassified(100)) == 4
    monkeypatch.setattr(classify, "_chat", fake_llm)
    assert pipeline.collect()["classified"] == 4


def test_telegram_pagination_stops_at_seen(monkeypatch):
    pages = []

    def get(url):
        pages.append(url)
        return (FIX / "tg_page.html").read_text()

    monkeypatch.setattr(telegram, "http_get", get)
    msgs = telegram.fetch_channel("testcargo", since_id="101", max_pages=3, pause=0)
    assert [m["ext_id"] for m in msgs] == ["102", "104"]
    assert len(pages) == 1


def test_report_telegram_chunks():
    chunks = report.render_telegram("# 标题\n" + ("一行内容\n" * 2000))
    assert all(len(c) <= 3600 for c in chunks) and len(chunks) > 1


def test_schedule_first_start_does_not_backfill(radar_env):
    cfg = config.load()
    store.set_meta("last_brief", "2026-10-16T05:00:00+00:00")  # 13:00 上海，部署时刻
    now = datetime(2026, 10, 16, 6, 0, tzinfo=timezone.utc)  # 14:00 上海
    nt = scheduler.next_times(cfg, now)
    assert nt["brief"].strftime("%Y-%m-%d %H:%M") == "2026-10-17 08:30"
    # 第二天 08:31 应该触发
    later = datetime(2026, 10, 17, 0, 31, tzinfo=timezone.utc)
    assert scheduler.next_times(cfg, later)["brief"] <= later
