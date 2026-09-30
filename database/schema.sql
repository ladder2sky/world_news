-- 新闻主表
CREATE TABLE IF NOT EXISTS news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    summary TEXT,
    source TEXT NOT NULL,
    url TEXT UNIQUE NOT NULL,
    url_hash TEXT,
    published_time DATETIME,
    fetched_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    category TEXT,
    country TEXT,
    ai_summary TEXT,
    importance_score INTEGER DEFAULT 0,
    event_id TEXT,
    is_processed INTEGER DEFAULT 0,
    raw_content TEXT
);

-- 新闻来源配置表
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    url TEXT UNIQUE NOT NULL,
    category TEXT,
    enabled INTEGER DEFAULT 1,
    last_fetched DATETIME,
    fetch_status TEXT DEFAULT 'unknown',
    error_message TEXT,
    created_time DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 事件追踪表
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    event_name TEXT NOT NULL,
    first_seen DATETIME,
    last_seen DATETIME,
    news_count INTEGER DEFAULT 1,
    category TEXT,
    countries TEXT,
    status TEXT DEFAULT 'active',
    summary TEXT
);

-- 运行日志表
CREATE TABLE IF NOT EXISTS run_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    run_type TEXT,
    sources_count INTEGER,
    news_fetched INTEGER,
    news_new INTEGER,
    news_duplicated INTEGER,
    ai_processed INTEGER,
    error_count INTEGER DEFAULT 0,
    duration_seconds REAL,
    status TEXT,
    error_details TEXT
);

-- 索引设计
CREATE INDEX IF NOT EXISTS idx_published_time ON news(published_time DESC);
CREATE INDEX IF NOT EXISTS idx_importance_score ON news(importance_score DESC);
CREATE INDEX IF NOT EXISTS idx_category_country ON news(category, country);
CREATE INDEX IF NOT EXISTS idx_is_processed ON news(is_processed);
CREATE INDEX IF NOT EXISTS idx_event_id ON news(event_id);
CREATE INDEX IF NOT EXISTS idx_fetched_time ON news(fetched_time DESC);
