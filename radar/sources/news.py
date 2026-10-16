"""Google News RSS：按查询词抓新闻标题，用来盯口岸、海关、过境政策。"""

from __future__ import annotations

import html
import re
import urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from . import http_get

LANGS = {
    "en-US": ("en-US", "US", "US:en"),
    "ru": ("ru", "RU", "RU:ru"),
    "fa": ("fa", "IR", "IR:fa"),
    "zh-CN": ("zh-CN", "CN", "CN:zh-Hans"),
}


def feed_url(query: str, lang: str = "en-US") -> str:
    hl, gl, ceid = LANGS.get(lang, LANGS["en-US"])
    q = urllib.parse.quote(f"{query} when:7d")
    return f"https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={ceid}"


def _strip(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(s or ""))).strip()


def parse_feed(xml_text: str, query: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    out = []
    for item in root.iter("item"):
        title = _strip(item.findtext("title", ""))
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        source = _strip(item.findtext("source", ""))
        desc = _strip(item.findtext("description", ""))
        posted = item.findtext("pubDate")
        try:
            posted_at = parsedate_to_datetime(posted).isoformat() if posted else None
        except (TypeError, ValueError):
            posted_at = None
        text = title if not desc or desc.startswith(title) else f"{title}\n{desc}"
        if source:
            text += f"\n（来源：{source}）"
        out.append(
            {
                "source": "news",
                "channel": query,
                "ext_id": link,
                "url": link,
                "text": text[:1500],
                "posted_at": posted_at,
            }
        )
    return out


def fetch_query(query: str, lang: str = "en-US") -> list[dict]:
    return parse_feed(http_get(feed_url(query, lang)), query)
