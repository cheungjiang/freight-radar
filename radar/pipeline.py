"""一次完整运行：抓取 → 入库 → 分类；简报：取未报过的高分条目 → 渲染 → 推送。"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from . import classify, config, notify, report, store
from .sources import news, telegram

log = logging.getLogger(__name__)
_run_lock = threading.Lock()


class Busy(RuntimeError):
    pass


def _news_queries(cfg: dict) -> list[tuple[str, str]]:
    out = []
    for q in cfg.get("news_queries", []):
        if isinstance(q, str):
            out.append((q, cfg.get("news_lang", "en-US")))
        elif isinstance(q, dict) and q.get("q"):
            out.append((q["q"], q.get("lang", cfg.get("news_lang", "en-US"))))
    return out


def _fetch(cfg: dict) -> tuple[int, list[str]]:
    added, errors = 0, []
    max_pages = cfg["telegram"].get("max_pages", 3)
    for ch in cfg.get("telegram_channels", []):
        name = config.normalize_channel(ch if isinstance(ch, str) else ch.get("name", ""))
        if not name:
            continue
        try:
            msgs = telegram.fetch_channel(name, store.last_ext_id("telegram", name), max_pages=max_pages)
            added += store.insert_items(msgs)
        except Exception as e:  # noqa: BLE001 —— 一个源坏了不影响其他源
            errors.append(f"@{name}: {e}")
        time.sleep(1)
    for q, lang in _news_queries(cfg):
        try:
            added += store.insert_items(news.fetch_query(q, lang))
        except Exception as e:  # noqa: BLE001
            errors.append(f"新闻「{q}」: {e}")
    return added, errors


def _classify(cfg: dict) -> tuple[int, list[str]]:
    m = cfg["model"]
    pending = store.unclassified(limit=m["max_items_per_run"] + 1000)
    todo, overflow = pending[: m["max_items_per_run"]], pending[m["max_items_per_run"] :]
    store.mark_skipped([it["id"] for it in overflow])
    done, errors = 0, []
    size = max(1, int(m.get("batch_size", 20)))
    for i in range(0, len(todo), size):
        batch = todo[i : i + size]
        try:
            results = classify.classify_batch(batch, m, cfg.get("focus", ""))
        except Exception as e:  # noqa: BLE001
            errors.append(f"分类失败（{len(batch)} 条，下次重试）: {e}")
            if isinstance(e, classify.ClassifyError) and "XAI_API_KEY" in str(e):
                break
            continue
        for item_id, (cat, score, fields) in results.items():
            store.save_classification(item_id, cat, score, fields)
            done += 1
    return done, errors


def collect() -> dict:
    if not _run_lock.acquire(blocking=False):
        raise Busy("雷达正在运行，稍后再试")
    run_id = store.start_run("collect")
    try:
        cfg = config.load()
        added, fetch_errors = _fetch(cfg)
        classified, cls_errors = _classify(cfg)
        errors = fetch_errors + cls_errors
        summary = f"新抓 {added} 条，分类 {classified} 条" + (f"，{len(errors)} 个错误" if errors else "")
        store.finish_run(run_id, not errors, summary + ("\n" + "\n".join(errors) if errors else ""))
        store.set_meta("last_collect", store.now_iso())
        return {"added": added, "classified": classified, "errors": errors, "summary": summary}
    except Exception as e:
        store.finish_run(run_id, False, f"运行失败: {e}")
        raise
    finally:
        _run_lock.release()


def brief(push: bool = True, collect_first: bool = True) -> dict:
    result: dict = {}
    if collect_first:
        result["collect"] = collect()
    run_id = store.start_run("brief")
    cfg = config.load()
    tz = cfg["schedule"]["timezone"]
    sections = report.collect_sections(cfg)
    md = report.render_markdown(sections, tz)
    day = datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d")
    out_dir = config.DATA_DIR / "briefs"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{day}.md").write_text(md, encoding="utf-8")
    ids = [it["id"] for items in sections.values() for it in items]
    sent = 0
    push_error = None
    if push:
        try:
            sent = notify.send_telegram(report.render_telegram(md))
        except Exception as e:  # noqa: BLE001
            push_error = str(e)
    if not push or sent or not notify.telegram_configured():
        # 推送成功（或者本来就不推）才算"已报过"，推送失败下次还会出现
        if push_error is None:
            store.mark_reported(ids)
    store.set_meta("last_brief", store.now_iso())
    summary = f"简报 {len(ids)} 条，Telegram 发出 {sent} 段" + (f"，推送失败：{push_error}" if push_error else "")
    store.finish_run(run_id, push_error is None, summary)
    result.update({"markdown": md, "items": len(ids), "telegram_messages": sent, "push_error": push_error})
    return result
