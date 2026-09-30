"""
RSS抓取核心逻辑模块
"""
import feedparser
import requests
import re
import html
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from loguru import logger

from collector.retry_handler import retry_with_backoff
import settings

class RSSReader:
    """RSS阅读器"""
    
    def __init__(self, timeout: int = None, max_retries: int = None):
        """
        初始化RSS阅读器
        
        Args:
            timeout: 请求超时时间（秒）
            max_retries: 最大重试次数
        """
        self.timeout = timeout or settings.REQUEST_TIMEOUT
        self.max_retries = max_retries or settings.MAX_RETRIES
    
    @retry_with_backoff(max_retries=3, initial_delay=1)
    def fetch_feed(self, url: str) -> Optional[Any]:
        """
        获取单个RSS源
        
        Args:
            url: RSS源URL
            
        Returns:
            解析后的Feed对象，失败返回None
        """
        try:
            logger.debug(f"Fetching RSS feed: {url}")
            
            # 设置请求头
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                             'AppleWebKit/537.36 (KHTML, like Gecko) '
                             'Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/xml, text/xml, */*',
                'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8',
            }
            
            # 获取RSS内容
            response = requests.get(url, headers=headers, timeout=self.timeout)
            response.raise_for_status()
            
            # 解析RSS
            feed = feedparser.parse(response.content)
            
            if feed.bozo and not feed.entries:
                logger.warning(f"Feed parse warning for {url}: {feed.bozo_exception}")
                return None
            
            logger.info(f"Successfully fetched {len(feed.entries)} entries from {url}")
            return feed
            
        except requests.exceptions.Timeout:
            logger.error(f"Timeout fetching {url}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error fetching {url}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error fetching {url}: {e}")
            raise
    
    def parse_entries(self, feed, max_age_hours: int = None) -> List[Dict[str, Any]]:
        """
        解析Feed条目
        
        Args:
            feed: Feed对象
            max_age_hours: 最大新闻年龄（小时）
            
        Returns:
            新闻条目列表
        """
        max_age_hours = max_age_hours or settings.NEWS_AGE_HOURS
        cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
        
        entries = []
        for entry in feed.entries:
            # 解析发布时间
            published_time = self._parse_published_time(entry)
            
            # 过滤旧新闻
            if published_time and published_time < cutoff_time:
                continue
            
            # 提取新闻数据
            news_data = {
                'title': self._get_entry_title(entry),
                'summary': self._get_entry_summary(entry),
                'source': feed.feed.get('title', 'Unknown'),
                'url': self._get_entry_link(entry),
                'published_time': published_time.isoformat() if published_time else None,
            }
            
            # 过滤无效数据
            if not news_data['title'] or not news_data['url']:
                continue
            
            entries.append(news_data)
        
        logger.info(f"Parsed {len(entries)} valid entries (filtered by age {max_age_hours}h)")
        return entries
    
    def _parse_published_time(self, entry) -> Optional[datetime]:
        """
        解析发布时间
        
        Args:
            entry: Feed条目
            
        Returns:
            发布时间，解析失败返回None
        """
        # 尝试不同的时间字段
        time_fields = [
            'published_parsed',
            'updated_parsed',
            'created_parsed',
        ]
        
        for field in time_fields:
            if hasattr(entry, field) and getattr(entry, field):
                try:
                    time_tuple = getattr(entry, field)
                    return datetime(*time_tuple[:6])
                except (ValueError, TypeError):
                    continue
        
        # 尝试从字符串解析
        string_fields = ['published', 'updated', 'created']
        date_formats = [
            '%a, %d %b %Y %H:%M:%S %z',
            '%Y-%m-%dT%H:%M:%S%z',
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d',
        ]
        
        for field in string_fields:
            date_str = getattr(entry, field, None)
            if date_str:
                for fmt in date_formats:
                    try:
                        return datetime.strptime(date_str, fmt)
                    except (ValueError, TypeError):
                        continue
        
        return None
    
    def _get_entry_title(self, entry) -> str:
        """获取条目标题"""
        return getattr(entry, 'title', '').strip()
    
    def _get_entry_summary(self, entry) -> str:
        """
        获取条目摘要
        
        优先使用 summary，其次 description，最后 content
        """
        summary = ''
        
        # 尝试 summary
        if hasattr(entry, 'summary'):
            summary = entry.summary
        
        # 尝试 description
        if not summary and hasattr(entry, 'description'):
            summary = entry.description
        
        # 尝试 content
        if not summary and hasattr(entry, 'content'):
            content = entry.content
            if isinstance(content, list) and len(content) > 0:
                summary = content[0].get('value', '')
        
        # 清理HTML标签（简单处理）
        if summary:
            summary = html.unescape(summary)
            # 移除HTML标签
            summary = re.sub(r'<[^>]+>', '', summary)
            # 限制长度
            if len(summary) > 1000:
                summary = summary[:1000] + '...'
        
        return summary.strip()
    
    def _get_entry_link(self, entry) -> str:
        """获取条目链接"""
        return getattr(entry, 'link', '').strip()
    
    def fetch_all_feeds(self, sources: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        获取所有RSS源的新闻
        
        Args:
            sources: 源配置列表 [{'name': str, 'url': str, 'category': str}, ...]
            
        Returns:
            结果字典 {
                'news': List[Dict],
                'stats': {'total': int, 'success': int, 'failed': int},
                'errors': List[str]
            }
        """
        all_news = []
        stats = {'total': len(sources), 'success': 0, 'failed': 0}
        errors = []
        
        for source in sources:
            name = source['name']
            url = source['url']
            
            try:
                feed = self.fetch_feed(url)
                if feed:
                    entries = self.parse_entries(feed)
                    # 添加来源分类信息
                    for entry in entries:
                        entry['source_category'] = source.get('category', '')
                    all_news.extend(entries)
                    stats['success'] += 1
                    logger.info(f"[{name}] Fetched {len(entries) if feed else 0} news")
                else:
                    stats['failed'] += 1
                    errors.append(f"[{name}] No entries returned")
            except Exception as e:
                stats['failed'] += 1
                error_msg = f"[{name}] {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)
        
        return {
            'news': all_news,
            'stats': stats,
            'errors': errors
        }
