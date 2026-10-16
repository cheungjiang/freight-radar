"""通过 Telegram Bot 把简报推给你。"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request


def telegram_configured() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def send_telegram(chunks: list[str]) -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_ids = [c.strip() for c in os.environ.get("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]
    if not token or not chat_ids:
        return 0
    sent = 0
    for chat_id in chat_ids:
        for chunk in chunks:
            data = urllib.parse.urlencode(
                {"chat_id": chat_id, "text": chunk, "disable_web_page_preview": "true"}
            ).encode()
            req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
            with urllib.request.urlopen(req, timeout=30) as resp:
                if json.loads(resp.read()).get("ok"):
                    sent += 1
    return sent
