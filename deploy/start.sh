#!/usr/bin/env bash
# 没有 systemd 时用：后台启动，日志写到 data/server.log
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data
if [ -f data/server.pid ] && kill -0 "$(cat data/server.pid)" 2>/dev/null; then
  kill "$(cat data/server.pid)" && sleep 1
fi
nohup .venv/bin/python -m radar serve >> data/server.log 2>&1 &
echo $! > data/server.pid
echo "已启动，PID $(cat data/server.pid)，日志：tail -f data/server.log"
