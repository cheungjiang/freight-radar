# 货代情报雷达（freight-radar）

定时读 Telegram 公开频道和口岸新闻，用模型分成四类：

| 类别 | 含义 |
|---|---|
| 🔥 询价线索 lead | 有人从中国（或经中亚）往伊朗/中亚/海湾运货，在找车、找货代、求报价 |
| 📊 运价 rate | 具体车价、涨跌、车源松紧 |
| ⚠️ 口岸政策 policy | 口岸关闭/拥堵、海关新规、过境规则 |
| 👀 竞品 competitor | 同行在推什么线路、怎么报价 |

每天固定时间推一份中文简报到你的 Telegram，同时开一个 MCP 接口，让 Grok Bot 查线索、改频道、记跟进状态、做复盘。

```
instabox 云机（常开）
 ├─ 定时器：每 4 小时抓一次，每天 08:30 发简报
 ├─ SQLite：所有消息、分类、跟进状态
 └─ MCP 服务 :8787/mcp（令牌鉴权）
        ▲
        │ 远程 MCP（https 公网地址 + Bearer 令牌）
     Grok Bot
```

## 部署到 instabox

instabox 的机器是 Debian 13，自带 Python 3.13。

```bash
# 1. 把代码放上去（二选一）
git clone <你的仓库地址> freight-radar      # 推到自己的 GitHub 后
# 或者把压缩包上传后：tar xzf freight-radar.tar.gz

cd freight-radar
bash deploy/install.sh          # 装依赖、跑自检、生成令牌、启动服务
nano .env                       # 填 XAI_API_KEY、TELEGRAM_BOT_TOKEN、TELEGRAM_CHAT_ID
bash deploy/install.sh          # 再跑一次，带上新的 key 重启
```

然后在 instabox 里把 **8787 端口** 开成公网地址（instabox 支持给本地端口生成 Public URL）。

### 三个 key 怎么拿

- **XAI_API_KEY**：console.x.ai 申请。分类用 grok 的快速非推理模型，每天几百条消息，每月几美元
- **TELEGRAM_BOT_TOKEN**：在 Telegram 找 @BotFather，`/newbot`，拿到 token。然后先给这个新 bot 发一句话，它才能给你推送
- **TELEGRAM_CHAT_ID**：给 @userinfobot 发消息，它回你的数字 ID。想推到群里，就把 bot 拉进群，填群的 ID（负数）

填好后可以测试推送：`.venv/bin/python -m radar test-push`

## 接入 Grok Bot

在 Grok Bot 的对话里发（替换成你的地址和令牌，令牌在 `.env` 的 `RADAR_MCP_TOKEN`）：

```
Add a custom MCP server called freight-radar at https://<你的公网地址>/mcp
Use header Authorization with value: Bearer <RADAR_MCP_TOKEN>
```

Grok Bot 会复述名字和地址，确认后点 **Add it**，它会报告工具数量（应该是 13 个）。服务是账号级的，你所有 bot 都能用，建议挂在 Pipeline 或 Sales 那个 bot 上。给 bot 的说明见 `GROK_BOT.md`。

## Grok Bot 能做什么

| 你说 | 它调用 |
|---|---|
| 今天的情报 | `get_brief` |
| 最近有哪些去马什哈德的询价 | `list_items(category="lead", search="Mashhad")` |
| #123 已报价，报了 4200 美金 | `update_lead(123, "quoted", "4200 美金")` |
| 加一个频道 @xxx | `add_telegram_channel` |
| 盯一下"Сарахс граница"的俄语新闻 | `add_news_query(lang="ru")` |
| 重点关注轮胎和汽配买家 | `set_focus` |
| 简报改到早上 9 点 | `set_schedule(brief_time="09:00")` |
| 这个月哪个频道最有用 | `source_stats` |
| 现在就跑一次 | `run_now`，几分钟后 `radar_status` |

## 命令行

```bash
.venv/bin/python -m radar collect          # 抓一次并分类
.venv/bin/python -m radar brief --no-push  # 生成简报但不推送
.venv/bin/python -m radar serve            # MCP 服务 + 定时器（install.sh 已经替你跑起来了）
```

有 systemd 时日志看 `sudo journalctl -u freight-radar -f`；没有时看 `data/server.log`，机器重启后要再跑 `bash deploy/start.sh`。

## 需要知道的限制

- **只能读公开频道**。用 `t.me/s/频道名` 网页版读，私有群、要加入才能看的群读不到。一个频道打开 `https://t.me/s/频道名` 能看到消息，就能加
- 频道太活跃时（4 小时内超过约 60 条），每次最多往回翻 3 页，可能漏掉一部分。改 `config.json` 的 `telegram.max_pages`
- 第一次抓一个频道只取最新一页，不翻历史
- 每次最多分类 300 条，多出来的旧消息直接标成噪音
- 模型偶尔会判错。前两周请多看 `list_items(category="noise")` 抽查有没有漏掉的线索，再用 `set_focus` 调
- 联系人是从公开帖子里抽出来的，雷达不会替你发消息；Grok Bot 也被说明不要擅自联系

## 文件

| 文件 | 内容 |
|---|---|
| `config.json` | 频道、新闻词、模型、时间表（Grok Bot 改的就是它） |
| `.env` | 密钥，权限 600，不进 git |
| `data/radar.db` | 全部数据 |
| `data/briefs/日期.md` | 每天的简报存档 |

## 换模型

改 `config.json` 里 `model.base_url` 和 `model.name`，key 放 `RADAR_LLM_API_KEY`。任何 OpenAI 兼容接口都行（DeepSeek、OpenAI、本地 Ollama 等）。

## 开发

```bash
.venv/bin/python -m pytest -q tests   # 不联网，用样例数据测
```
