"""命令行：
    python -m radar serve            # MCP 服务 + 定时器（部署时用这个）
    python -m radar collect          # 抓一次并分类
    python -m radar brief [--no-push]  # 抓一次并生成简报
    python -m radar test-push        # 测试 Telegram 推送
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from . import config


def main(argv: list[str] | None = None) -> int:
    config.load_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="radar", description="货代情报雷达")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--host", default=os.environ.get("RADAR_HOST", "0.0.0.0"))
    s.add_argument("--port", type=int, default=int(os.environ.get("RADAR_PORT", "8787")))
    s.add_argument("--no-scheduler", action="store_true")
    sub.add_parser("collect")
    b = sub.add_parser("brief")
    b.add_argument("--no-push", action="store_true")
    sub.add_parser("test-push")
    args = p.parse_args(argv)

    if args.cmd == "serve":
        from .server import serve

        serve(args.host, args.port, with_scheduler=not args.no_scheduler)
    elif args.cmd == "collect":
        from .pipeline import collect

        r = collect()
        print(r["summary"])
        for e in r["errors"]:
            print("  ! " + e)
    elif args.cmd == "brief":
        from .pipeline import brief

        r = brief(push=not args.no_push)
        print(r["markdown"])
        for e in r["collect"]["errors"]:
            print("  ! " + e, file=sys.stderr)
        if r["push_error"]:
            print("推送失败：" + r["push_error"], file=sys.stderr)
    elif args.cmd == "test-push":
        from .notify import send_telegram, telegram_configured

        if not telegram_configured():
            print("没设置 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")
            return 1
        print(f"发出 {send_telegram(['✅ 货代情报雷达：推送测试成功'])} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
