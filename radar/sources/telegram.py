"""读 Telegram 公开频道的网页版（https://t.me/s/频道名），不需要 Telegram API。

只能读公开频道。私有群、需要加入才能看的群读不到。
"""

from __future__ import annotations

import time

from bs4 import BeautifulSoup

from . import http_get


def parse_page(html: str, channel: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for msg in soup.select("div.tgme_widget_message[data-post]"):
        post = msg.get("data-post", "")
        if "/" not in post:
            continue
        post_id = post.rsplit("/", 1)[1]
        if not post_id.isdigit():
            continue
        text_el = msg.select_one("div.tgme_widget_message_text")
        text = text_el.get_text("\n", strip=True) if text_el else ""
        # 转发消息、只有图片的消息也可能带说明文字，没有文字就跳过
        if not text:
            continue
        time_el = msg.select_one("a.tgme_widget_message_date time")
        posted_at = time_el.get("datetime") if time_el else None
        link_el = msg.select_one("a.tgme_widget_message_date")
        url = link_el.get("href") if link_el else f"https://t.me/{post}"
        out.append(
            {
                "source": "telegram",
                "channel": channel,
                "ext_id": post_id,
                "url": url,
                "text": text[:4000],
                "posted_at": posted_at,
            }
        )
    return out


def fetch_channel(channel: str, since_id: str | None, max_pages: int = 3, pause: float = 1.5) -> list[dict]:
    """取比 since_id 新的消息。第一次（since_id 为空）只取最新一页。"""
    collected: dict[str, dict] = {}
    url = f"https://t.me/s/{channel}"
    since = int(since_id) if since_id and since_id.isdigit() else None
    pages = max_pages if since else 1
    for _ in range(pages):
        msgs = parse_page(http_get(url), channel)
        if not msgs:
            break
        for m in msgs:
            if since is None or int(m["ext_id"]) > since:
                collected[m["ext_id"]] = m
        oldest = min(int(m["ext_id"]) for m in msgs)
        if since is None or oldest <= since:
            break
        url = f"https://t.me/s/{channel}?before={oldest}"
        time.sleep(pause)
    return sorted(collected.values(), key=lambda m: int(m["ext_id"]))
