"""
数据库连接与操作模块
"""
import sqlite3
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

import settings

class DatabaseManager:
    """数据库管理器"""
    
    def __init__(self, db_path: Optional[Path] = None):
        """初始化数据库管理器"""
        self.db_path = db_path or settings.DB_PATH
        self._ensure_db_directory()
        self.connection = None
    
    def _ensure_db_directory(self):
        """确保数据库目录存在"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
    
    def connect(self):
        """建立数据库连接"""
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        # 启用外键支持
        self.connection.execute("PRAGMA foreign_keys = ON")
        return self.connection
    
    def close(self):
        """关闭数据库连接"""
        if self.connection:
            self.connection.close()
            self.connection = None
    
    def __enter__(self):
        """上下文管理器入口"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        if exc_type is None:
            self.connection.commit()
        else:
            self.connection.rollback()
        self.close()
    
    def initialize_schema(self):
        """初始化数据库schema"""
        schema_path = Path(__file__).parent / "schema.sql"
        with open(schema_path, 'r', encoding='utf-8') as f:
            schema_sql = f.read()
        self.connection.executescript(schema_sql)
    
    def get_url_hash(self, url: str) -> str:
        """计算URL的MD5哈希"""
        return hashlib.md5(url.encode('utf-8')).hexdigest()
    
    # ==================== 新闻操作 ====================
    
    def insert_news(self, news_data: Dict[str, Any]) -> Optional[int]:
        """
        插入单条新闻
        
        Args:
            news_data: 新闻数据字典
            
        Returns:
            新插入记录的ID，如果已存在则返回None
        """
        url_hash = self.get_url_hash(news_data['url'])
        
        try:
            cursor = self.connection.execute(
                """INSERT INTO news 
                   (title, summary, source, url, url_hash, published_time, raw_content)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    news_data['title'],
                    news_data.get('summary', ''),
                    news_data['source'],
                    news_data['url'],
                    url_hash,
                    news_data.get('published_time'),
                    news_data.get('raw_content', '')
                )
            )
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            # URL已存在，返回None
            return None
    
    def bulk_insert_news(self, news_list: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        批量插入新闻
        
        Args:
            news_list: 新闻数据列表
            
        Returns:
            统计信息字典 {'new': int, 'duplicated': int}
        """
        stats = {'new': 0, 'duplicated': 0}
        
        for news_data in news_list:
            result = self.insert_news(news_data)
            if result:
                stats['new'] += 1
            else:
                stats['duplicated'] += 1
        
        return stats
    
    def get_unprocessed_news(self, limit: int = 100) -> List[sqlite3.Row]:
        """
        获取未处理的新闻
        """
        cursor = self.connection.execute(
            """SELECT * FROM news 
               WHERE is_processed = 0 
               ORDER BY published_time DESC 
               LIMIT ?""",
            (limit,)
        )
        return cursor.fetchall()

    def get_news_needing_resummary(self, min_chars: int = 100,
                                   min_chinese_ratio: float = 0.45,
                                   limit: int = 500) -> List[sqlite3.Row]:
        """
        挑出 AI 摘要不合格、需要重跑的新闻（只在已 is_processed=1 的记录里找）。

        不合格判定（满足任一）：
        1. ai_summary 为空
        2. 长度 < min_chars
        3. 汉字占比 < min_chinese_ratio（判断为英文/中英夹杂严重）
        4. ai_summary 出现明显英文兜底特征词（"The firm also issued"、"In its prospectus"... 等整句英文）

        为避免每条 SQL 做 Unicode 正则（SQLite 不自带），这里先按长度 / 中文常见字 regexp 粗筛，
        返回给 Python 后再用 _chinese_char_ratio 精筛，或者调用方直接批量接受。
        """
        # 用最廉价的条件先筛掉明显合格的：长度不足/空/完全不含中文常用字范围
        # 这里 LIKE '%[一-龥]%' 在 SQLite 是 LIKE 带通配符，不够精所以改成只在长度空+<min 上卡，
        # 汉字比例判断交由 Python。因为 SQLite 中文 LIKE 对 UTF-8 不稳定。
        cursor = self.connection.execute(
            """SELECT * FROM news
               WHERE is_processed = 1
                 AND (ai_summary IS NULL
                      OR length(trim(ai_summary)) = 0
                      OR length(ai_summary) < ?)
               ORDER BY importance_score DESC, published_time DESC
               LIMIT ?""",
            (int(min_chars), int(limit))
        )
        return cursor.fetchall()

    def update_news_summary_only(self, news_id: int, ai_summary: str):
        """只更新 ai_summary 字段，不扰动分类/打分/is_processed（给 --resummarize 用）。"""
        self.connection.execute(
            """UPDATE news SET ai_summary = ? WHERE id = ?""",
            (ai_summary, int(news_id))
        )
    
    def get_recent_news(self, hours: int = 24, limit: int = 100) -> List[sqlite3.Row]:
        """
        获取最近一段时间的新闻网
        
        Args:
            hours: 时间范围（小时）
            limit: 最大返回数量
            
        Returns:
            新闻列表
        """
        since_time = (datetime.now() - timedelta(hours=hours)).isoformat()
        cursor = self.connection.execute(
            """SELECT * FROM news 
               WHERE published_time >= ? 
               ORDER BY importance_score DESC, published_time DESC 
               LIMIT ?""",
            (since_time, limit)
        )
        return cursor.fetchall()
    
    def update_news_analysis(self, news_id: int, category: str, country: str, 
                            ai_summary: str, importance_score: int, event_id: str):
        """
        更新新闻AI分析结果
        
        Args:
            news_id: 新闻ID
            category: 分类
            country: 涉及国家
            ai_summary: AI摘要
            importance_score: 重要性评分
            event_id: 事件ID
        """
        self.connection.execute(
            """UPDATE news 
               SET category = ?, country = ?, ai_summary = ?, 
                   importance_score = ?, event_id = ?, is_processed = 1
               WHERE id = ?""",
            (category, country, ai_summary, importance_score, event_id, news_id)
        )
    
    def get_top_news(self, count: int = 20, min_score: int = 0,
                     since: Optional[str] = None) -> List[sqlite3.Row]:
        """
        获取评分最高的新闻
        
        Args:
            count: 返回数量
            min_score: 最低评分阈值
            since: 时间窗起点（如 '2026-11-07'）；只返回该时间之后发布/抓取的新闻，
                   传 None 表示不限（全库历史总榜）
            
        Returns:
            新闻列表
        """
        sql = """SELECT * FROM news
                 WHERE is_processed = 1 AND importance_score >= ?"""
        params: List[Any] = [min_score]
        if since:
            sql += " AND COALESCE(published_time, fetched_time) >= ?"
            params.append(since)
        sql += " ORDER BY importance_score DESC, published_time DESC LIMIT ?"
        params.append(count)
        cursor = self.connection.execute(sql, tuple(params))
        return cursor.fetchall()

    def get_title_corpus(self, limit: int = 5000) -> List[str]:
        """取全库新闻标题，用作去重时统计实体文档频率（df）的背景语料。"""
        cursor = self.connection.execute(
            "SELECT title FROM news ORDER BY id DESC LIMIT ?", (int(limit),)
        )
        return [r['title'] for r in cursor.fetchall() if r['title']]
    
    # ==================== 来源操作 ====================
    
    def upsert_source(self, name: str, url: str, category: str, enabled: bool = True) -> bool:
        """
        插入或更新新闻来源
        
        Args:
            name: 来源名称
            url: RSS URL
            category: 类别
            enabled: 是否启用
            
        Returns:
            是否成功
        """
        try:
            self.connection.execute(
                """INSERT INTO sources (name, url, category, enabled) 
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET url = excluded.url, category = excluded.category, enabled = excluded.enabled""",
                (name, url, category, 1 if enabled else 0)
            )
            return True
        except sqlite3.IntegrityError:
            return False
    
    def disable_sources_not_in(self, keep_names) -> int:
        """
        把不在指定名单里的来源全部置为 disabled（JSON 作为唯一真源时使用）
        
        Args:
            keep_names: 可迭代的 name 集合
            
        Returns:
            被 disable 的条数
        """
        names = list(keep_names)
        if not names:
            return 0
        placeholders = ','.join('?' * len(names))
        cur = self.connection.execute(
            f"""UPDATE sources SET enabled = 0
                WHERE enabled = 1 AND name NOT IN ({placeholders})""",
            names
        )
        return cur.rowcount or 0
    
    def update_source_fetch_status(self, name: str, status: str, error_message: Optional[str] = None):
        """
        更新来源抓取状态
        
        Args:
            name: 来源名称
            status: 抓取状态(ok/error)
            error_message: 错误信息
        """
        self.connection.execute(
            """UPDATE sources 
               SET last_fetched = ?, fetch_status = ?, error_message = ?
               WHERE name = ?""",
            (datetime.now().isoformat(), status, error_message, name)
        )
    
    def get_enabled_sources(self) -> List[sqlite3.Row]:
        """
        获取所有启用的来源
        
        Returns:
            来源列表
        """
        cursor = self.connection.execute(
            """SELECT * FROM sources WHERE enabled = 1"""
        )
        return cursor.fetchall()
    
    # ==================== 事件操作 ====================
    
    def upsert_event(self, event_id: str, event_name: str, category: str, 
                    countries: str, summary: str):
        """
        插入或更新事件
        
        Args:
            event_id: 事件ID
            event_name: 事件名称
            category: 类别
            countries: 涉及国家
            summary: 事件概述
        """
        now = datetime.now().isoformat()
        self.connection.execute(
            """INSERT INTO events (event_id, event_name, first_seen, last_seen, 
                                   news_count, category, countries, summary, status)
               VALUES (?, ?, ?, ?, 1, ?, ?, ?, 'active')
               ON CONFLICT(event_id) DO UPDATE SET
                   last_seen = excluded.last_seen,
                   news_count = news_count + 1,
                   summary = excluded.summary""",
            (event_id, event_name, now, now, category, countries, summary)
        )
    
    def get_active_events(self, limit: int = 50) -> List[sqlite3.Row]:
        """
        获取活跃事件
        
        Args:
            limit: 最大返回数量
            
        Returns:
            事件列表
        """
        cursor = self.connection.execute(
            """SELECT * FROM events 
               WHERE status = 'active'
               ORDER BY news_count DESC, last_seen DESC 
               LIMIT ?""",
            (limit,)
        )
        return cursor.fetchall()
    
    # ==================== 运行历史操作 ====================
    
    def create_run_record(self, run_type: str, sources_count: int) -> int:
        """
        创建运行记录
        
        Args:
            run_type: 运行类型 (full/incremental/manual)
            sources_count: 源数量
            
        Returns:
            记录ID
        """
        cursor = self.connection.execute(
            """INSERT INTO run_history 
               (run_type, sources_count, news_fetched, news_new, news_duplicated, 
                ai_processed, error_count, status)
               VALUES (?, ?, 0, 0, 0, 0, 0, 'running')""",
            (run_type, sources_count)
        )
        return cursor.lastrowid
    
    def update_run_record(self, run_id: int, **kwargs):
        """
        更新运行记录
        
        Args:
            run_id: 运行记录ID
            **kwargs: 要更新的字段
        """
        set_clauses = []
        values = []
        for key, value in kwargs.items():
            set_clauses.append(f"{key} = ?")
            values.append(value)
        
        if set_clauses:
            values.append(run_id)
            self.connection.execute(
                f"""UPDATE run_history 
                    SET {', '.join(set_clauses)}
                    WHERE id = ?""",
                values
            )
    
    def complete_run_record(self, run_id: int, duration: float, status: str, 
                           error_details: Optional[str] = None):
        """
        完成运行记录
        
        Args:
            run_id: 运行记录ID
            duration: 运行耗时（秒）
            status: 运行状态(success/partial/failed)
            error_details: 错误详情
        """
        self.update_run_record(run_id, duration_seconds=duration, status=status, 
                              error_details=error_details)
