"""生成中文简报：Markdown（给 Grok Bot 和存档）和 Telegram 用的纯文本分段。"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from . import store

SECTIONS = [
    ("lead", "🔥 询价线索"),
    ("rate", "📊 运价情报"),
    ("policy", "⚠️ 口岸与政策"),
    ("competitor", "👀 竞品动态"),
]


def _src(it: dict) -> str:
    if it["source"] == "telegram":
        return f'@{it["channel"]}'
    return "新闻"


def collect_sections(cfg: dict) -> dict[str, list[dict]]:
    b = cfg["brief"]
    out = {}
    for cat, _ in SECTIONS:
        limit = b["max_leads"] if cat == "lead" else b["max_per_section"]
        out[cat] = store.query_items(
            category=cat, days=3, min_score=b["min_score"], limit=limit, unreported_only=True
        )
    return out


def render_markdown(sections: dict[str, list[dict]], tz: str) -> str:
    today = datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d")
    lines = [f"# 📦 货代情报 {today}", ""]
    total = sum(len(v) for v in sections.values())
    if total == 0:
        lines.append("今天没有新的可行动线索。")
        return "\n".join(lines)
    for cat, title in SECTIONS:
        items = sections.get(cat) or []
        if not items:
            continue
        lines.append(f"## {title}（{len(items)}）")
        lines.append("")
        for it in items:
            f = it["fields"]
            head = f"**#{it['id']}** {f.get('summary_zh') or it['text'][:60]}"
            lines.append(f"- {head}")
            route = " → ".join(x for x in (f.get("origin"), f.get("destination")) if x)
            meta = [
                p
                for p in (
                    f"线路：{route}" if route else "",
                    f"货物：{f['cargo']}" if f.get("cargo") else "",
                    f"货量：{f['volume']}" if f.get("volume") else "",
                    f"价格：{f['price']}" if f.get("price") else "",
                    f"适配：{f['fit']}" if f.get("fit") and f["fit"] not in ("未知",) else "",
                    f"联系：{f['contact']}" if f.get("contact") else "",
                    f"评分 {it['score']:.2f}",
                )
                if p
            ]
            lines.append("  " + " ｜ ".join(meta))
            if f.get("action_zh"):
                lines.append(f"  👉 {f['action_zh']}")
            lines.append(f"  来源：{_src(it)} {it.get('url') or ''}".rstrip())
        lines.append("")
    lines.append("回复 Grok Bot「#编号 已联系 / 已报价 / 成交 / 丢单 / 忽略」更新跟进状态。")
    return "\n".join(lines)


def render_telegram(markdown: str) -> list[str]:
    """Telegram 单条上限 4096 字，按段切开；用纯文本发，避免 Markdown 解析出错。"""
    text = markdown.replace("**", "").replace("## ", "").replace("# ", "")
    chunks, cur = [], ""
    for para in text.split("\n"):
        if len(cur) + len(para) + 1 > 3500:
            chunks.append(cur)
            cur = ""
        cur += para + "\n"
    if cur.strip():
        chunks.append(cur)
    return chunks
