"""内置定时器：每 N 小时抓一次，每天固定时间发简报。跟 MCP 服务在同一个进程里跑，不依赖 cron。"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config, pipeline, store

log = logging.getLogger(__name__)


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def next_times(cfg: dict, now: datetime | None = None) -> dict:
    sch = cfg["schedule"]
    tz = ZoneInfo(sch["timezone"])
    now = (now or datetime.now(timezone.utc)).astimezone(tz)
    hh, mm = (int(x) for x in sch["brief_time"].split(":"))
    brief_at = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    last_brief = _parse_iso(store.get_meta("last_brief"))
    # 今天的时间已过：已经发过，或者是第一次启动（不补发），都排到明天
    if brief_at <= now and (last_brief is None or last_brief.astimezone(tz) >= brief_at):
        brief_at += timedelta(days=1)
    last_collect = _parse_iso(store.get_meta("last_collect"))
    every = timedelta(hours=float(sch["collect_every_hours"]))
    collect_at = (last_collect.astimezone(tz) + every) if last_collect else now
    return {"brief": brief_at, "collect": collect_at}


def tick(now: datetime | None = None) -> str | None:
    cfg = config.load()
    if not cfg["schedule"].get("enabled", True):
        return None
    now = now or datetime.now(timezone.utc)
    nt = next_times(cfg, now)
    try:
        if nt["brief"] <= now:
            log.info("定时简报开始")
            pipeline.brief(push=True, collect_first=True)
            return "brief"
        if nt["collect"] <= now:
            log.info("定时抓取开始")
            pipeline.collect()
            return "collect"
    except pipeline.Busy:
        return None
    except Exception:  # noqa: BLE001
        log.exception("定时任务出错")
    return None


def start_background(interval: float = 60) -> threading.Event:
    stop = threading.Event()
    # 第一次部署：以现在为基线，今天已过的简报时间不补发，从下一个时间点开始
    if store.get_meta("last_brief") is None:
        store.set_meta("last_brief", store.now_iso())

    def loop():
        while not stop.wait(interval):
            tick()

    threading.Thread(target=loop, name="radar-scheduler", daemon=True).start()
    return stop
