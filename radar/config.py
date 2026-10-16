"""配置：config.json 存可改的设置（频道、关键词、时间表），.env 存密钥。"""

from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path

ROOT = Path(os.environ.get("RADAR_HOME", Path(__file__).resolve().parent.parent))
CONFIG_PATH = Path(os.environ.get("RADAR_CONFIG", ROOT / "config.json"))
EXAMPLE_PATH = ROOT / "config.example.json"
DATA_DIR = Path(os.environ.get("RADAR_DATA", ROOT / "data"))

DEFAULTS: dict = {
    "lang": "zh",
    "telegram_channels": [],
    "news_queries": [],
    "news_lang": "en-US",
    "focus": "",
    "model": {
        "base_url": "https://api.x.ai/v1",
        "name": "grok-4-1-fast-non-reasoning",
        "batch_size": 20,
        "max_items_per_run": 300,
    },
    "schedule": {
        "timezone": "Asia/Shanghai",
        "collect_every_hours": 4,
        "brief_time": "08:30",
        "enabled": True,
    },
    "brief": {
        "max_leads": 10,
        "max_per_section": 5,
        "min_score": 0.5,
    },
    "telegram": {"max_pages": 3},
}

_lock = threading.Lock()


def load_env(path: Path | None = None) -> None:
    """读取 .env（KEY=VALUE），不覆盖已存在的环境变量。"""
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    with _lock:
        if not CONFIG_PATH.exists():
            if EXAMPLE_PATH.exists():
                CONFIG_PATH.write_text(EXAMPLE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
            else:
                CONFIG_PATH.write_text(json.dumps(DEFAULTS, ensure_ascii=False, indent=2), encoding="utf-8")
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return _merge(DEFAULTS, raw)


def save(cfg: dict) -> None:
    with _lock:
        tmp = CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(CONFIG_PATH)


def normalize_channel(name: str) -> str:
    """接受 @name、t.me/name、https://t.me/s/name，统一成 name。"""
    name = name.strip()
    for prefix in ("https://", "http://"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    for prefix in ("t.me/s/", "t.me/", "telegram.me/"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    name = name.lstrip("@").split("/")[0].split("?")[0]
    return name
