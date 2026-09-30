# 每日全球头条新闻智能采集系统

## Technical Design Document (V2.0)

---

# 1. 项目概述

## 1.1 项目名称

每日全球新闻智能采集与分析系统
(Global Daily News Intelligence System)

---

## 1.2 项目目标

建立一个个人使用的自动化新闻情报系统，每天自动：

1. 从全球主流媒体 RSS 获取新闻
2. 保存新闻原始数据
3. 使用本地 AI 模型进行分析
4. 自动完成：

   * 新闻分类
   * 新闻去重
   * 重要性评分
   * 摘要生成
5. 输出每日全球新闻简报 CSV 文件
6. 为未来 TTS 语音播报提供数据接口

---

## 1.3 系统定位

目标不是简单新闻阅读器，而是：

> 一个长期积累全球事件数据，并利用 AI 提炼世界趋势的个人新闻数据库。

---

## 1.4 版权合规说明

> **重要提醒**：本系统仅用于个人学习与研究目的。
> RSS 新闻标题 + 短摘要属于合理使用范围，但全文存储可能有版权风险。
> 系统数据仅限本地使用，不对外分发或公开。

---

# 2. 系统总体架构

```
                  RSS 新闻源

 Reuters / AP / BBC
 Guardian / Al Jazeera
 CNBC / MarketWatch
 CNA / Nikkei Asia
 The Verge / Ars Technica
     |
     |
     ↓

 RSS Collector
 (Python + feedparser)
     |
     |
     ↓

 SQLite Database
 (news.db)
     |
     |
     ↓

 Local AI Engine
 (Ollama + Qwen/DeepSeek)
     |
     |
     ↓

 News Analysis

 - 分类
 - 去重
 - 摘要
 - 评分

     |
     |
     ↓

 CSV Report

     |
     |
     ↓

 TTS Module

     |
     |
     ↓

 Daily Audio Briefing
```

---

# 3. 技术选型

## 3.1 开发语言

Python 3.10+

选择原因：

* RSS处理成熟
* AI接口丰富
* 数据分析能力强
* 适合自动化任务

---

## 3.2 数据采集

技术：

RSS Feed

Python库：

```
feedparser      # RSS解析
requests        # HTTP请求
tenacity        # 重试机制
```

功能：

* 获取新闻标题
* 获取摘要
* 获取发布时间
* 获取链接
* 获取来源

---

## 3.3 数据库

第一阶段：

SQLite 3

文件：

```
news.db
```

选择原因：

* 无需安装数据库服务器
* 单机性能足够
* 易备份
* 易迁移

---

## 3.4 AI模型

采用本地运行方案：

推荐：

* Ollama（推理引擎）
* Qwen2.5-7B（主模型，分类+摘要+评分）
* Qwen2.5-3B（轻量模型，初筛过滤）
* DeepSeek-R1（可选，复杂推理场景）

运行模式：

```
Python
 |
 |
 Ollama API (localhost:11434)
 |
 |
 Local LLM
```

**两阶段处理策略**：

| 阶段 | 模型 | 任务 | 处理量 |
|------|------|------|--------|
| 初筛 | Qwen2.5-3B | 快速过滤低价值新闻 | 500+条 |
| 深度分析 | Qwen2.5-7B | 分类+摘要+评分+去重 | Top 50条 |

---

## 3.5 输出格式

主要格式：

CSV

原因：

* 通用
* 可Excel打开
* 可导入数据库
* 方便后续分析

---

# 4. 新闻来源设计

## 4.1 第一阶段新闻源

目标：

20~30个 RSS。

---

## 4.2 国际新闻

| 来源 | RSS URL | 作用 | 免费可用性 |
|------|---------|------|-----------|
| Reuters | `https://feeds.reuters.com/reuters/topNews` | 全球事实新闻 | ✅ 完全免费 |
| Associated Press | `https://rss.ap.org/ap/feed/default/feed/Top%20Stories.xml` | 美国头条 | ✅ 完全免费 |
| BBC World | `https://feeds.bbci.co.uk/news/world/rss.xml` | 国际报道 | ✅ 完全免费 |
| Guardian World | `https://www.theguardian.com/world/rss` | 欧洲/英国视角 | ✅ 完全免费 |
| Al Jazeera | `https://www.aljazeera.com/xml/rss/all.xml` | 中东/全球南方视角 | ✅ 完全免费 |
| France 24 | `https://www.france24.com/en/feed` | 法国/非洲视角 | ✅ 完全免费 |
| DW (Deutsche Welle) | `https://www.dw.com/rss/dw/chinese/10000009` | 德国/欧洲视角 | ✅ 完全免费 |

---

## 4.3 财经新闻

| 来源 | RSS URL | 作用 | 免费可用性 |
|------|---------|------|-----------|
| CNBC | `https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114` | 商业/金融市场 | ✅ 完全免费 |
| MarketWatch | `https://www.marketwatch.com/feed/headlines/top` | 美股/宏观经济 | ✅ 完全免费 |
| Investing.com | `https://feeds.investing.com/news/all` | 全球市场 | ✅ 完全免费 |
| Yahoo Finance | `https://feeds.finance.yahoo.com/rss/2.0/headline?s=.INX&region=US&lang=en-US` | 美股指数 | ✅ 完全免费 |
| Financial Times | `https://www.ft.com/rss/home` | 全球经济深度 | ⚠️ 部分免费 |
| Bloomberg | `https://feeds.bloomberg.com/markets/news.xml` | 金融市场 | ⚠️ 部分免费 |

> **注意**：FT 和 Bloomberg 的 RSS 可能需要订阅才能获取完整内容，建议先用测试脚本验证可用性，如不可用则以 CNBC + MarketWatch + Yahoo Finance 替代。

---

## 4.4 亚洲新闻

| 来源 | RSS URL | 作用 | 免费可用性 |
|------|---------|------|-----------|
| CNA | `https://www.channelnewsasia.com/rss/sitemap0.xml` | 东南亚/新加坡 | ✅ 完全免费 |
| Nikkei Asia | `https://asia.nikkei.com/rss/free` | 亚洲经济 | ✅ 免费内容可用 |
| SCMP | `https://www.scmp.com/rss` | 中国/香港 | ⚠️ 部分免费 |
| The Japan Times | `https://www.japantimes.co.jp/feed/` | 日本视角 | ✅ 完全免费 |
| Korea Herald | `https://www.koreaherald.com/rss/economy.xml` | 韩国视角 | ✅ 完全免费 |
| India Today | `https://www.indiatoday.in/rss` | 印度视角 | ✅ 完全免费 |

---

## 4.5 科技新闻

| 来源 | RSS URL | 作用 | 免费可用性 |
|------|---------|------|-----------|
| The Verge | `https://www.theverge.com/rss/index.xml` | 科技产业 | ✅ 完全免费 |
| Ars Technica | `https://feeds.arstechnica.com/arstechnica/latest` | 技术深度 | ✅ 完全免费 |
| TechCrunch | `https://techcrunch.com/feed/` | 创业/科技 | ✅ 完全免费 |
| Wired | `https://www.wired.com/feed/rss` | 科技文化 | ✅ 完全免费 |
| MIT Tech Review | `https://www.technologyreview.com/feed/` | 前沿科技 | ✅ 完全免费 |
| Hacker News (Best) | `https://hnrss.org/best` | 开发者社区 | ✅ 完全免费 |

---

## 4.6 RSS源测试策略

编写测试脚本 `scripts/test_rss_sources.py`，用于：

1. 验证每个 RSS 源是否可访问
2. 检查返回状态码
3. 验证 XML/JSON 格式正确性
4. 统计每个源返回的文章数量
5. 输出可用源清单

```python
# 测试指标
- HTTP 状态码 (200 = OK)
- 响应时间 (< 5秒)
- 文章数量 (> 0)
- 解析成功率
```

---

# 5. 数据库设计

数据库：

```
news.db
```

---

## 5.1 新闻主表

Table: `news`

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 主键 |
| title | TEXT | NOT NULL | 新闻标题 |
| summary | TEXT | | 原始摘要 |
| source | TEXT | NOT NULL | 新闻来源名称 |
| url | TEXT | UNIQUE NOT NULL | 原文链接（唯一约束防重复） |
| url_hash | TEXT | | URL的MD5哈希（快速去重） |
| published_time | DATETIME | | 发布时间 |
| fetched_time | DATETIME | DEFAULT CURRENT_TIMESTAMP | 抓取时间 |
| category | TEXT | | AI分类结果 |
| country | TEXT | | 涉及国家/地区 |
| ai_summary | TEXT | | AI生成的摘要 |
| importance_score | INTEGER | DEFAULT 0 | 重要性评分 (0-100) |
| event_id | TEXT | | 事件编号（关联events表） |
| is_processed | INTEGER | DEFAULT 0 | 是否已完成AI分析 |
| raw_content | TEXT | | 原始RSS内容备份（可选） |

**索引设计**：

```sql
CREATE INDEX idx_published_time ON news(published_time DESC);
CREATE INDEX idx_importance_score ON news(importance_score DESC);
CREATE INDEX idx_category_country ON news(category, country);
CREATE INDEX idx_is_processed ON news(is_processed);
CREATE INDEX idx_event_id ON news(event_id);
CREATE INDEX idx_fetched_time ON news(fetched_time DESC);
```

---

## 5.2 新闻来源配置表

Table: `sources`

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 主键 |
| name | TEXT | UNIQUE NOT NULL | 来源名称 |
| url | TEXT | UNIQUE NOT NULL | RSS Feed URL |
| category | TEXT | | 来源类别(国际/财经/亚洲/科技) |
| enabled | INTEGER | DEFAULT 1 | 是否启用 |
| last_fetched | DATETIME | | 最后抓取时间 |
| fetch_status | TEXT | DEFAULT 'unknown' | 抓取状态(ok/error) |
| error_message | TEXT | | 最后错误信息 |
| created_time | DATETIME | DEFAULT CURRENT_TIMESTAMP | 添加时间 |

> 支持动态增删RSS源，无需修改配置文件。

---

## 5.3 事件追踪表

Table: `events`

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| event_id | TEXT | PRIMARY KEY | 事件唯一标识 |
| event_name | TEXT | NOT NULL | 事件名称 |
| first_seen | DATETIME | | 首次出现时间 |
| last_seen | DATETIME | | 最后出现时间 |
| news_count | INTEGER | DEFAULT 1 | 相关新闻数量 |
| category | TEXT | | 事件类别 |
| countries | TEXT | | 涉及国家（逗号分隔） |
| status | TEXT | DEFAULT 'active' | 状态(active/resolved/archived) |
| summary | TEXT | | 事件概述 |

> 用于后续的事件时间线分析和趋势追踪。

---

## 5.4 运行日志表

Table: `run_history`

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 主键 |
| run_time | DATETIME | DEFAULT CURRENT_TIMESTAMP | 运行时间 |
| run_type | TEXT | | 运行类型(full/incremental/manual) |
| sources_count | INTEGER | | 处理的源数量 |
| news_fetched | INTEGER | | 抓取的新闻数 |
| news_new | INTEGER | | 新增新闻数 |
| news_duplicated | INTEGER | | 去重丢弃数 |
| ai_processed | INTEGER | | AI处理的新闻数 |
| error_count | INTEGER | DEFAULT 0 | 错误数量 |
| duration_seconds | REAL | | 耗时(秒) |
| status | TEXT | | 运行状态(success/partial/failed) |
| error_details | TEXT | | 错误详情 |

---

## 5.5 新闻分类枚举

category 取值：

```
Politics      # 政治
Economy       # 经济
Technology    # 科技
Science       # 科学
Military      # 军事
Energy        # 能源
Finance       # 金融
Society       # 社会
Climate       # 气候/环境
Health        # 健康
Culture       # 文化
Other         # 其他
```

---

# 6. 软件目录设计

项目：

```
world_news/

│
├── main.py                      # 主入口
├── config.py                    # 全局配置
├── requirements.txt             # Python依赖
├── .env.example                 # 环境变量模板
│
├── config/
│   ├── rss_sources.json         # RSS源配置（初始用）
│   └── ai_prompts.json          # AI Prompt模板配置
│
├── database/
│   ├── __init__.py
│   ├── news.db                  # SQLite数据库（运行后生成）
│   ├── database.py              # 数据库连接与操作
│   └── schema.sql               # 数据库建表脚本
│
├── collector/
│   ├── __init__.py
│   ├── rss_reader.py            # RSS抓取核心逻辑
│   └── retry_handler.py         # 重试与错误处理
│
├── ai/
│   ├── __init__.py
│   ├── analyzer.py              # AI分析主逻辑
│   ├── prompts.py               # Prompt管理
│   └── ollama_client.py         # Ollama API客户端
│
├── output/
│   ├── __init__.py
│   ├── csv_generator.py         # CSV日报生成
│   └── report_builder.py        # 报告组装
│
├── tts/
│   ├── __init__.py
│   ├── script_generator.py      # 播报脚本生成
│   └── voice_generator.py       # TTS转换
│
├── scripts/
│   ├── test_rss_sources.py      # RSS源测试脚本
│   ├── backup_db.py             # 数据库备份脚本
│   └── migrate.py               # 数据库迁移工具
│
├── logs/
│   ├── system.log               # 系统运行日志
│   └── errors.log               # 错误日志
│
└── output_data/
    ├── daily_news_YYYYMMDD.csv   # 每日CSV日报
    └── daily_summary_YYYYMMDD.txt # 每日摘要文本
```

---

# 7. 核心业务流程

## 7.1 每日运行流程

时间：

每天 06:00（可配置）

流程：

```
启动程序 main.py
    │
    ├─ 1. 加载配置
    │     └─ 读取启用的RSS源列表
    │
    ├─ 2. 记录运行开始
    │     └─ 写入 run_history
    │
    ├─ 3. RSS抓取循环
    │     ├─ 对每个源发起请求
    │     ├─ 网络失败 → 重试3次（指数退避: 1s, 2s, 4s）
    │     ├─ 单源失败 → 记录错误，跳过，继续下一源
    │     └─ 解析新闻条目
    │
    ├─ 4. 数据清洗
    │     ├─ 过滤空标题/空内容
    │     ├─ 过滤超过24小时的旧新闻
    │     └─ URL去重（检查已入库记录）
    │
    ├─ 5. 保存SQLite
    │     ├─ 新增新闻写入 news 表
    │     └─ 更新 sources 表的 last_fetched
    │
    ├─ 6. AI分析（两阶段）
    │     ├─ 阶段1: 轻量模型快速初筛（500→50条）
    │     ├─ 阶段2: 大模型深度分析（Top 50条）
    │     │     ├─ 分类
    │     │     ├─ 重要性评分
    │     │     ├─ 摘要生成
    │     │     └─ 事件去重与event_id分配
    │     └─ 更新 is_processed = 1
    │
    ├─ 7. 生成日报
    │     ├─ 按 importance_score 排序
    │     ├─ 选取 Top 20
    │     └─ 生成 CSV + 摘要文本
    │
    ├─ 8. TTS播报（可选）
    │     ├─ 生成播报脚本
    │     └─ 转换为音频
    │
    └─ 9. 记录运行结束
          └─ 更新 run_history 统计信息
```

---

## 7.2 错误处理策略

| 场景 | 处理策略 |
|------|---------|
| 网络超时 | 重试3次，指数退避（1s → 2s → 4s） |
| 单源解析失败 | 记录错误日志，跳过该源，继续处理 |
| 全部源失败 | 标记运行状态为failed，发送告警 |
| AI服务不可用 | 使用默认分类/评分，标记待后续分析 |
| 数据库锁冲突 | 等待重试，最多5次 |
| 磁盘空间不足 | 停止运行，记录严重错误 |

---

# 8. AI分析模块设计

## 8.1 新闻分类

### 输入 Prompt 模板

```
你是一个新闻分类专家。请分析以下新闻，返回JSON格式结果。

新闻标题：{title}
新闻摘要：{summary}
来源：{source}

请从以下类别中选择最匹配的一个：
Politics, Economy, Technology, Science, Military, Energy, Finance, Society, Climate, Health, Culture, Other

请判断主要涉及的国家/地区（可多选）：
USA, China, UK, EU, Russia, Japan, Korea, India, ASEAN, MiddleEast, Africa, LatinAmerica, Global

返回格式（仅返回JSON，不要其他内容）：
{
  "category": "类别",
  "countries": ["国家1", "国家2"]
}
```

### 输出示例

```json
{
  "category": "Economy",
  "countries": ["USA", "Global"]
}
```

---

## 8.2 重要性评分

### 评分 Prompt 模板

```
你是一个新闻价值评估专家。请为以下新闻打分（0-100分）。

评分维度：
1. 全球影响力 (0-30分) - 影响多少国家和人群
2. 经济/金融影响 (0-25分) - 对市场、经济的影响程度
3. 政治/政策影响 (0-25分) - 对国际关系、政策的影响
4. 持续追踪价值 (0-20分) - 是否值得关注后续发展

评分参考标准：
- 90-100: 改变全球格局的重大事件（战争爆发、重大条约、全球性危机）
- 75-89:  重要政策/经济数据/地缘事件（央行决策、大选、贸易协议）
- 60-74:  区域性重要事件（区域冲突、重要立法、大型企业动向）
- 40-59:  一般新闻（常规政策调整、行业报告、学术发布）
- 0-39:   低优先级（地方新闻、娱乐八卦、日常事件）

新闻标题：{title}
新闻摘要：{summary}
分类：{category}

返回格式（仅返回JSON）：
{
  "score": 分数,
  "reasoning": "打分理由（一句话）",
  "breakdown": {
    "global_impact": 分数,
    "economic_impact": 分数,
    "political_impact": 分数,
    "follow_value": 分数
  }
}
```

### 评分示例

| 新闻类型 | 典型评分 | 说明 |
|---------|---------|------|
| 战争升级/停战协议 | 95 | 全球影响极大 |
| 央行政策变化 | 90 | 全球经济影响 |
| 重大贸易协议 | 85 | 多边经济影响 |
| 国家大选结果 | 80 | 政治格局变化 |
| 大型企业财报 | 65 | 行业影响 |
| 科技产品发布 | 55 | 有限影响 |
| 地方性事件 | 25 | 低优先级 |

---

## 8.3 摘要生成

### 摘要 Prompt 模板

```
请用一句话概括以下新闻的核心内容（30字以内，中文）。

新闻标题：{title}
新闻摘要：{summary}

只返回摘要文本，不要其他内容。
```

---

## 8.4 新闻去重

### 去重 Prompt 模板

```
判断以下两条新闻是否报道同一事件。

新闻1标题：{title1}
新闻1摘要：{summary1}
新闻1来源：{source1}

新闻2标题：{title2}
新闻2摘要：{summary2}
新闻2来源：{source2}

如果是同一事件，返回：
{
  "same_event": true,
  "event_name": "事件简短名称"
}

如果不是，返回：
{
  "same_event": false
}
```

### event_id 命名规则

```
{主题}_{日期}
示例: US_TARIFF_POLICY_20260726
      UK_ELECTION_RESULT_20260726
      AI_REGULATION_EU_20260726
```

---

# 9. CSV输出设计

文件命名：

```
daily_news_YYYYMMDD.csv
```

### 字段定义

| 字段 | 说明 | 示例 |
|------|------|------|
| date | 日期 | 2026-07-26 |
| rank | 排名 | 1 |
| title | 标题 | Fed signals rate cut |
| source | 来源 | Reuters |
| category | 类别 | Economy |
| country | 涉及国家 | USA,Global |
| ai_summary | AI摘要 | 美联储释放降息信号，可能影响全球市场 |
| impact | 影响说明 | 全球金融市场可能波动 |
| score | 评分 | 90 |
| event_id | 事件编号 | US_FED_RATE_CUT_20260726 |
| url | 原文链接 | https://... |

### 示例数据

```csv
date,rank,title,source,category,country,ai_summary,impact,score,event_id,url
2026-07-26,1,Fed signals rate cut,Reuters,Economy,"USA,Global",美联储释放降息信号,全球金融市场可能波动,90,US_FED_RATE_CUT_20260726,https://...
2026-07-26,2,EU passes AI regulation,Guardian,Technology,"EU,Global",欧盟通过AI监管法案,科技行业合规成本上升,85,EU_AI_REGULATION_20260726,https://...
```

---

# 10. TTS扩展设计

## 10.1 播报脚本生成

### 输入

CSV日报文件：`daily_news.csv`

### 输出

播报脚本：`daily_script_YYYYMMDD.txt`

### 脚本模板

```
早上好，现在是全球新闻简报，日期：{date}。

今天全球最重要的新闻共有 {count} 条。

【第一条，评分 {score}】
{ai_summary}
来源：{source}，类别：{category}。

【第二条，评分 {score}】
...

以上是今天的全球新闻简报。
```

---

## 10.2 TTS引擎选型

### 推荐方案：Edge TTS

优势：

* 完全免费（使用微软 Azure 的 edge-api）
* 支持多种语言和语音
* 音质自然
* 无需本地安装额外模型

推荐中文语音：

```
zh-CN-XiaoxiaoNeural    # 女声，自然
zh-CN-YunxiNeural       # 男声，清晰
```

### 备选方案：Piper TTS

* 完全本地运行
* 离线可用
* 速度较快
* 音质略逊于Edge TTS

---

## 10.3 TTS流程

```
CSV日报
    ↓
筛选 Top 10 新闻
    ↓
生成播报脚本
    ↓
Edge TTS 转换
    ↓
输出 MP3 文件
    ↓
手机/音箱播放
```

---

# 11. 自动运行设计

## 11.1 Windows

使用：任务计划程序 (Task Scheduler)

配置：

```
触发器: 每天 06:00
操作: python main.py
日志: logs/system.log
```

---

## 11.2 Linux / macOS

使用：cron

配置：

```bash
# 每天早上6点运行
0 6 * * * cd /path/to/world_news && python3 main.py >> logs/system.log 2>&1
```

---

## 11.3 运行模式

| 模式 | 说明 | 触发方式 |
|------|------|---------|
| full | 全量抓取所有源 | 每日定时 |
| incremental | 增量抓取（仅过去6小时） | 每6小时 |
| manual | 手动触发 | 命令行参数 |

---

# 12. 配置管理

## 12.1 全局配置 (config.py)

```python
# 数据库
DB_PATH = "database/news.db"

# AI配置
OLLAMA_BASE_URL = "http://localhost:11434"
AI_MODEL_LIGHT = "qwen2.5:3b"      # 初筛模型
AI_MODEL_MAIN = "qwen2.5:7b"       # 深度分析模型
AI_TOP_N = 20                      # 日报选取数量
AI_SCREEN_N = 50                   # 深度分析数量

# 抓取配置
NEWS_AGE_HOURS = 24                # 只抓取24小时内新闻
REQUEST_TIMEOUT = 10               # 请求超时(秒)
MAX_RETRIES = 3                    # 最大重试次数
RETRY_DELAY = 1                    # 初始重试延迟(秒)

# 评分阈值
SCORE_THRESHOLD_TOP = 70           # Top新闻最低分数

# TTS配置
TTS_VOICE = "zh-CN-XiaoxiaoNeural"
TTS_OUTPUT_DIR = "output_data/audio"
```

---

## 12.2 环境变量 (.env)

```
# Ollama配置
OLLAMA_HOST=localhost
OLLAMA_PORT=11434

# 日志级别
LOG_LEVEL=INFO

# 运行模式
RUN_MODE=full
```

---

# 13. 数据备份策略

## 13.1 自动备份

```
触发条件: 每次成功运行后
备份内容: news.db
备份路径: backups/news_YYYYMMDD.db
保留策略: 最近30天
```

## 13.2 手动备份

```
脚本: scripts/backup_db.py
用法: python scripts/backup_db.py --full
```

---

# 14. 第一阶段开发计划

## Phase 1：基础采集（预计1-2周）

目标：

RSS → SQLite

完成：

* [ ] 数据库 schema 创建
* [ ] RSS源配置
* [ ] 新闻抓取核心逻辑
* [ ] 重试与错误处理
* [ ] 数据去重与保存
* [ ] RSS源测试脚本
* [ ] 运行日志记录

---

## Phase 2：数据输出（预计3-5天）

完成：

* [ ] SQLite查询
* [ ] CSV日报生成
* [ ] 摘要文本生成
* [ ] 按评分排序

---

## Phase 3：AI分析（预计1-2周）

完成：

* [ ] Ollama环境搭建
* [ ] AI分类模块
* [ ] AI评分模块
* [ ] AI摘要模块
* [ ] 新闻去重模块
* [ ] 两阶段处理流程
* [ ] event_id分配

---

## Phase 4：语音系统（预计3-5天）

完成：

* [ ] 播报脚本生成
* [ ] Edge TTS集成
* [ ] 音频文件输出
* [ ] 自动播放测试

---

# 15. 后续升级方向

## 15.1 新闻搜索

加入向量数据库：

* ChromaDB
* FAISS

支持自然语言查询：

```
"过去一年能源危机发展如何？"
"俄乌冲突的关键节点有哪些？"
```

---

## 15.2 事件追踪

建立事件时间线：

```
事件: Ukraine War

2026-01  停火谈判启动
2026-02  援助协议签署
2026-03  局势缓和
...
```

---

## 15.3 趋势分析

自动生成周报/月报：

```
本周全球关注热点：

1. AI监管 (25条相关, 平均评分78)
2. 全球利率 (18条相关, 平均评分82)
3. 能源市场 (15条相关, 平均评分71)
```

---

## 15.4 可视化仪表板

Web界面：

* 新闻时间线
* 热点地图
* 趋势图表
* 事件追踪面板

技术选型：

* Streamlit（快速原型）
* 或 Dash（更灵活）

---

# 16. V1成功标准

系统每天能够自动完成：

| 指标 | 目标值 | 说明 |
|------|-------|------|
| 新闻采集量 | 500+ 条 | 来自20+个RSS源 |
| 数据库保存 | 100% | 无数据丢失 |
| AI筛选 | Top 20 | 按重要性排序 |
| CSV日报 | 1 份/天 | 格式规范 |
| TTS文本 | 1 份/天 | 可读性强 |
| 运行成功率 | > 95% | 30天统计 |
| 单次运行时间 | < 30分钟 | 含AI分析 |

---

# 17. 最终愿景

经过长期运行，该系统将形成：

**个人全球新闻数据库。**

不仅回答：

> "今天发生了什么？"

还能回答：

> "过去一年发生了什么？"
> "哪些事件正在形成趋势？"
> "哪些变化可能影响未来？"

最终成为**个人化的全球信息分析平台**。

---

## 版本历史

| 版本 | 日期 | 变更内容 |
|------|------|---------|
| V1.0 | 2026-07-26 | 初始设计文档 |
| V2.0 | 2026-07-26 | 补充数据库设计、AI评分标准、错误处理、RSS备选源、配置管理、备份策略 |

---

*文档结束*
