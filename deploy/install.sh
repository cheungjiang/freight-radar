#!/usr/bin/env bash
# 在 instabox（Debian 13）上安装货代情报雷达。重复运行是安全的：不会覆盖已有的 .env、config.json 和数据。
#   bash deploy/install.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$APP_DIR"
PORT="${RADAR_PORT:-8787}"

SUDO=""
if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then SUDO="sudo"; fi

echo "==> 1/5 检查 Python"
if ! python3 -c 'import sys; assert sys.version_info >= (3, 10)' 2>/dev/null; then
  echo "需要 Python 3.10+"; exit 1
fi
if ! python3 -m venv --help >/dev/null 2>&1 || ! python3 -c 'import ensurepip' 2>/dev/null; then
  $SUDO apt-get update -qq && $SUDO apt-get install -y -qq python3-venv
fi

echo "==> 2/5 安装依赖"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

echo "==> 3/5 准备配置"
[ -f config.json ] || cp config.example.json config.json
if [ ! -f .env ]; then
  cp .env.example .env
fi
if ! grep -qE '^RADAR_MCP_TOKEN=.{24,}' .env; then
  TOKEN="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"
  sed -i "s|^RADAR_MCP_TOKEN=.*|RADAR_MCP_TOKEN=${TOKEN}|" .env
fi
chmod 600 .env
mkdir -p data
PORT="${RADAR_PORT:-$(grep -E '^RADAR_PORT=[0-9]+' .env | cut -d= -f2)}"
PORT="${PORT:-8787}"

echo "==> 4/5 自检"
.venv/bin/python -m pytest -q tests >/dev/null 2>&1 || .venv/bin/pip install -q pytest
.venv/bin/python -m pytest -q tests

echo "==> 5/5 启动服务"
if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
  sed -e "s|__APP_DIR__|$APP_DIR|g" -e "s|__USER__|$(id -un)|g" deploy/freight-radar.service \
    | $SUDO tee /etc/systemd/system/freight-radar.service >/dev/null
  $SUDO systemctl daemon-reload
  $SUDO systemctl enable --now freight-radar
  $SUDO systemctl restart freight-radar
  echo "已用 systemd 启动（开机自启）。看日志：sudo journalctl -u freight-radar -f"
else
  bash deploy/start.sh
  echo "这台机器没有 systemd，已用后台进程启动。重启机器后要再运行：bash deploy/start.sh"
fi

for i in $(seq 1 20); do
  if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null && echo "服务正常：http://127.0.0.1:${PORT}/mcp"

TOKEN="$(grep '^RADAR_MCP_TOKEN=' .env | cut -d= -f2-)"
cat <<EOF

──────────────────────────────────────────────
接下来：
1. 编辑 .env，填 XAI_API_KEY、TELEGRAM_BOT_TOKEN、TELEGRAM_CHAT_ID，然后重新运行本脚本
2. 在 instabox 面板里把端口 ${PORT} 开成公网地址（Public URL）
3. 在 Grok Bot 里发：
   Add a custom MCP server called freight-radar at https://<公网地址>/mcp
   with header Authorization: Bearer ${TOKEN}
──────────────────────────────────────────────
EOF
