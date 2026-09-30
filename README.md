# World News · 每日全球新闻智能采集与分析系统

一套**端到端的本地自动化新闻工作流**：从 21 家主流英文媒体 RSS 抓取新闻 → 去重入库 → 用**本地 LLM**（Ollama / LM Studio / 任意 OpenAI 兼容服务）做分类·打分·中文摘要 → 生成 CSV 日报、Markdown 摘要和 TTS 播报脚本。全程**不把新闻发给任何云端**。

```
[RSS 采集 (21 家)] → [SQLite 去重入库] → [本地 LLM 分类/打分/中文摘要] → [CSV / TXT / TTS 脚本]
```

## 功能一览

- **21 家主流媒体 RSS**：BBC、Guardian、NYT、NPR、Al Jazeera、France 24、DW、CNBC、MarketWatch、Yahoo Finance、CNA、SCMP、The Japan Times、Korea Herald、India Today、The Verge、Ars Technica、TechCrunch、Wired、MIT Tech Review、Hacker News Best（国际·财经·科技全覆盖，可在 `config/rss_sources.json` 增删、`enabled:false` 可临时屏蔽）。
- **本地私有 LLM**：走 OpenAI 兼容协议 (`/v1/chat/completions`)，支持 Ollama（本地）、LM Studio（GUI 本地）、OpenRouter、vLLM 等，默认开箱即用 LM Studio。
- **智能中文摘要 + 质量门**：每条要求 3–5 句话、约 120 汉字；支持「英文占比过高」「字数不足」自动重试；对 reasoning-capable 模型（Gemma 4 / DeepSeek R1 / Qwen-R 等）会自动从 `reasoning_content` 里抽取正式答案，避免 LM Studio 的 `content` 为空导致全是兜底文案。
- **重要性评分 + 分类**：每条都有分类（国际/财经/科技/政治/军事/经济/社会/科学/文化/体育/健康/环境/法律/商业/教育/娱乐/天气/讣告/其他）、涉及国家、0–100 重要性分数、事件去重 ID。
- **多种报告输出**：
  - `output_data/daily_news_YYYYMMDD.csv`（Excel 直接打开，utf-8-sig，含排名/评分/分类/国家/中文摘要/原文链接）
  - `output_data/daily_summary_YYYYMMDD.txt`（人读文本摘要，按分数降序）
  - `output_data/daily_script_YYYYMMDD.txt`（TTS 播报脚本，供 edge-tts 朗读）
- **安全增量运行**：RSS 按 GUID/链接去重，AI 分析按 `is_processed` 翻牌子，重复运行不会重复入库、不会重复烧 token。

## 目录结构

```
world_news/
├── main.py                   # CLI 入口
├── settings.py               # 全局配置（环境变量覆盖）
├── requirements.txt
├── .env.example              # 环境变量模板
├── collector/
│   └── rss_reader.py         # RSS 抓取
├── database/
│   ├── database.py           # SQLite 访问层 + 数据库迁移
│   └── news.db               # 数据库文件（首次运行自动创建）
├── ai/
│   ├── analyzer.py           # 分类/打分/摘要 三阶段 + 质量门
│   ├── ollama_client.py      # OpenAI 兼容协议封装（支持 content / reasoning_content 双路径抽取）
│   └── prompts.py            # 从 JSON 加载分类/打分/摘要/去重 4 套 Prompt
├── tts/
│   ├── script_generator.py   # 生成播报脚本
│   └── voice_generator.py    # edge-tts 语音合成（需要联网）
├── output/
│   ├── report_builder.py     # 文本摘要
│   └── csv_generator.py      # CSV 日报（utf-8-sig）
├── scripts/
│   ├── migrate.py            # 数据库 schema 迁移
│   ├── backup_db.py          # 数据库备份到 backups/
│   └── test_rss_sources.py   # 测试 RSS 连通性
├── config/
│   ├── rss_sources.json      # RSS 源清单（增删改 + enabled 开关）
│   └── ai_prompts.json       # 4 套 Prompt + 摘要字数约束
├── logs/                     # 运行日志
├── output_data/              # 报告 / CSV / TTS 音频 最终产物
└── backups/                  # 数据库备份
```

## 安装

> 要求：Python **3.10+**。

### 1. 克隆并创建虚拟环境

```powershell
# Windows (PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. 配置环境变量（可选，默认值对本地 LM Studio 用户已开箱）

```powershell
Copy-Item .env.example .env
# 然后用编辑器打开 .env，按需修改。绝大多数情况可以跳过这步直接跑。
```

关键变量（完整列表见 `.env.example`）：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://127.0.0.1:1234` | **OpenAI 兼容服务基础 URL**。Ollama 默认用 `http://localhost:11434`，LM Studio 默认 `http://127.0.0.1:1234`。是否以 `/v1` 结尾都行，程序会自动规整。 |
| `AI_MODEL_LIGHT` | `unsloth/gemma-4-26b-a4b-it` | 初筛/摘要模型名。 |
| `AI_MODEL_MAIN` | `unsloth/gemma-4-26b-a4b-it` | 分类/打分模型名。想省显存可和 LIGHT 共用同一个。 |
| `AI_TOP_N` | `20` | CSV / 摘要 / 脚本里最多放多少条重要新闻。 |
| `AI_SCREEN_N` | `50` | 单次 `--analyze-only` 最多处理多少条未分析新闻。26B 推理慢时建议 20–50。 |
| `NEWS_AGE_HOURS` | `24` | 只入库 24 小时内发布的新闻（防止 RSS 历史积压把库里塞满）。 |
| `MAX_RETRIES` | `3` | RSS / LLM 请求失败的最大重试次数（指数退避）。 |
| `SCORE_THRESHOLD_TOP` | `70` | Top 报告最低分数门槛（< 70 不进 CSV 排名）。 |
| `TTS_VOICE` | `zh-CN-XiaoxiaoNeural` | edge-tts 朗读音色。 |
| `LOG_LEVEL` | `INFO` | 日志等级：`DEBUG` / `INFO` / `WARNING` / `ERROR`。 |

### 3. 启动本地大模型后端

**任选一个**：

#### A. LM Studio（新手推荐，有 GUI，当前默认配置对它开箱）
1. 安装 <https://lmstudio.ai>
2. 搜索并下载 `unsloth/gemma-4-26b-a4b-it`（或任意喜欢的模型）
3. 左侧切到 **Local Server (🔌)** → 顶部 Model 下拉选刚下的模型 → 点 **Load**
4. 右侧 **Start Server** 面板 → 端口默认 1234 → 点 **▶ Start Server**  
   （看到 `[SERVER READY] Endpoint: http://127.0.0.1:1234/v1` 就 OK）

> **TIP**：Gemma 4、DeepSeek R1、Qwen-R 这种 extended-thinking 模型默认会把答案塞到 `reasoning_content` 字段而让 `content` 空。本项目的 `OllamaClient` 已经内置两条路径的抽取器，不用关 Reasoning。但若嫌推理慢，可在 Server Settings 里关 **Enable Extended Thinking** 提速 2–5 倍。

#### B. Ollama（命令行党）
```powershell
# 1. 下载：https://ollama.com/download
ollama serve                           # 另开一个窗口常驻
ollama pull qwen2.5:7b                 # 随便哪个模型都行
```
然后把 `.env` 改成：
```
OLLAMA_BASE_URL=http://localhost:11434
AI_MODEL_LIGHT=qwen2.5:3b
AI_MODEL_MAIN=qwen2.5:7b
```

## 运行方式

所有命令都在项目根目录执行，统一前缀：
```powershell
.\.venv\scripts\python.exe main.py
```

### 0. 先自检：RSS 源健康检查

```powershell
.\.venv\scripts\python.exe main.py --test-sources
```
会打印 `[OK] BBC World: 34 entries`、`[WARN]`、`[FAIL]` 三种状态。FAIL 说明该源 URL 失效，编辑 `config/rss_sources.json` 改好再跑即可。

### 1. 标准跑法：完整流水线

```powershell
.\.venv\scripts\python.exe main.py --type full
# --type full / incremental / manual 三选一：
#   full        (默认) 抓 RSS + 做 AI 分析 + 出报告，AI_SCREEN_N=50 条一批
#   incremental 同上，给调度器用（和 full 目前语义等价，留作将来区分）
#   manual      留作手动触发的占位
```

### 2. 只做 AI 分析（不抓 RSS）

```powershell
.\.venv\scripts\python.exe main.py --analyze-only
```
最常用。它会从 DB 里取 `is_processed=0` 的**最新 50 条**（= `AI_SCREEN_N`）做分类/打分/摘要，然后**自动生成当天 3 份报告**（CSV / summary / script）。

> 因为有 `LIMIT 50`，所以想把 DB 里积压的 274 条新闻一次性分析完，这个命令连续跑 6 次即可，不会重复做。

### 3. 只重新出报告（不抓、不分析）

```powershell
.\.venv\scripts\python.exe main.py --reports-only
```
**最快**。只要 DB 里已经有 `is_processed=1` 的分析结果，想改完 `AI_TOP_N` 重排 CSV、或者把昨天的报告按今天日期重命名一份，就用这个。完全不烧 token。

### 4. 只重算中文摘要（不动分类/打分，省 2/3 token）

```powershell
# A. 只挑「不合格」的摘要重跑（字数 < 100 或 汉字占比 < 45% 的那些）
.\.venv\scripts\python.exe main.py --resummarize

# B. 对「全部已分析」的新闻强制重算摘要（比如刚改完 ai_prompts.json 想把历史全换新）
.\.venv\scripts\python.exe main.py --resummarize-all
```

跑 `--resummarize*` 的最后也会自动生成当天报告，不用再补 `--reports-only`。

### 5. 数据库备份 & 迁移

```powershell
# 备份到 backups/news.db.YYYYMMDD_HHMMSS
.\.venv\scripts\python.exe scripts/backup_db.py

# 首次/升级 schema（main.py 会自动调用这个，一般不用手动）
.\.venv\scripts\python.exe scripts/migrate.py
```

## 输出文件说明

### `output_data/daily_news_YYYYMMDD.csv`
一份 Excel 能直接打开的 utf-8-sig CSV，列：

| 列 | 说明 |
|---|---|
| Rank | 当日重要性排名（1 = 最高） |
| Score | 0–100 重要性分数（模型打） |
| Category | 分类（中文） |
| Countries | 涉及国家/地区，`,` 分隔 |
| Title | 原文标题（英文） |
| AI Summary | 模型生成的中文摘要（约 120 字 / 3–5 句） |
| Source | 来源媒体 |
| Published | 发布时间（UTC ISO8601） |
| URL | 原文链接 |
| Event ID | 事件去重 ID，相同代表同一条事件被多家媒体报道 |

### `output_data/daily_summary_YYYYMMDD.txt`
给人快速浏览的纯文本版本，按分数降序，每条包含标题、AI 中文摘要、来源。默认最多 `AI_TOP_N * 2 = 40` 条。

### `output_data/daily_script_YYYYMMDD.txt`
给 `edge-tts` 朗读用的英文句式脚本。用 `voice_generator.py` 可以把它转成 mp3：
```powershell
.\.venv\scripts\python.exe -c "
from tts.voice_generator import VoiceGenerator
VoiceGenerator().generate(open('output_data/daily_script_20260930.txt', encoding='utf-8').read(), 'output_data/audio/daily_20260930.mp3')
"
```

## 自定义

### 增删 RSS 源
改 `config/rss_sources.json`。加一个对象即可：
```json
{ "name": "My Source", "url": "https://example.com/rss", "category": "财经", "enabled": true }
```
改完下次跑 main.py 会被自动同步到数据库；**你在 JSON 里删掉的源、或把 `enabled` 设成 false 的源，会被 DB 自动标记为禁用，不会再抓取**。

### 改 AI Prompt 模板 / 摘要字数
改 `config/ai_prompts.json`：
- `classify_news` / `score_news` / `summary_news` / `deduplicate_events` 四个模板都能改。
- `summary_news` 下的 `"summary_cfg": { "min_chars": 100, "target_chars": 120, "max_chars": 220 }` 直接控制摘要长短。
- 改完立刻想让旧摘要也换成新 Prompt：`--resummarize-all`。

### 换模型（一个参数，不用改代码）
```powershell
# 临时覆盖：
$env:AI_MODEL_MAIN='hugging-quants/Llama-3.2-3B-Instruct-Q4_K_M.gguf'
.\.venv\scripts\python.exe main.py --analyze-only
```
或者写进 `.env` 永久生效。

## FAQ & 排错

### Q：324 条新闻，AI 分析为什么每次只有 50 条？
不是 bug。`AI_SCREEN_N=50` 是**单次 `--analyze-only` 的处理上限**（防止 Gemma 26B 一次跑 8 小时卡住）。加上 `is_processed=1` 做增量标记，所以每次只吃一口。连续跑 6 次就把 300 条吃完，或者把 `AI_SCREEN_N` 调大。

### Q：跑 2 次 `--analyze-only`，CSV 为什么不是 100 条？
因为 CSV 有**全局最高分 40 条**的上限（`AI_TOP_N * 2`）。想扩大日报容量：`$env:AI_TOP_N=50` 后跑 `--reports-only`，立刻得到 100 条 CSV。

### Q：为什么 `ai_summary` 列有些非常短？
常见 3 种情况，都有对应开关修：
1. **Prompt 字数约束太松**：改 `config/ai_prompts.json` 里 `summary_cfg` 三档，然后 `--resummarize-all`。
2. **Reasoning 模型把答案写进了 reasoning_content，老代码没读到（出现过的症状：`global flags not at the start of expression` / `summary LLM empty`）**：当前 `OllamaClient` 已经自动双路径抽取，不用再修。如果仍出现英文，大概率是模型倾向英文输出，跑一次 `--resummarize` 就会被「汉字占比 < 45%」质量门自动中文重试。
3. **AI 服务根本没启动**：日志里出现 `AI service not available`。请在 LM Studio 点 ▶ Start Server，或 `ollama serve` 先起起来。

### Q：出现分类/打分失败，怎么快速定位？
现在 `NewsAnalyzer.classify_news / score_news` 失败日志里会把「LLM 实际返回的前 500 字符」一起打出来，直接复制出来对照就行，不用猜。一般原因是 Prompt 让它输出 JSON 但它输出了解释性文字，把 `ai_prompts.json` 里的约束再写硬一点（加一句 `Your output must be a single valid JSON object with no additional commentary, no markdown fences.`）即可。

### Q：CSV 用 Excel 打开中文乱码？
请直接双击 `daily_news_*.csv`，我们输出用的是 **utf-8-sig**（带 BOM），新版 Excel 对它直接识别。如果还是乱码，那是 Excel 的「文本导入向导」里手动选了 GBK，取消 → 重新双击即可。

## 许可证 & 数据来源说明

- 代码：MIT。
- 新闻内容版权归各 RSS 源原媒体所有，本工具仅用于个人或小团队内部信息聚合，请遵守各源的 ToS。
- TTS 依赖微软 edge-tts 服务，生成音频受对应条款约束。
