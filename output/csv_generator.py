"""
CSV日报生成模块
"""
import csv
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from loguru import logger

import settings
from output.report_builder import _normalize_source_label


class CSVGenerator:
    """CSV报告生成器"""
    
    def __init__(self, output_dir: Path = None):
        """
        初始化CSV生成器
        
        Args:
            output_dir: 输出目录
        """
        self.output_dir = output_dir or settings.OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_daily_csv(self, news_list: List[Dict[str, Any]], 
                          date_str: str = None) -> Path:
        """
        生成每日CSV报告
        
        Args:
            news_list: 新闻列表
            date_str: 日期字符串 (YYYY-MM-DD)
            
        Returns:
            生成的CSV文件路径
        """
        if date_str is None:
            date_str = datetime.now().strftime('%Y-%m-%d')
        
        filename = f"daily_news_{date_str.replace('-', '')}.csv"
        output_path = self.output_dir / filename
        
        # CSV字段定义
        fieldnames = [
            'date', 'rank', 'title', 'source', 'category', 'country',
            'ai_summary', 'score', 'related_count', 'event_id', 'url'
        ]
        
        try:
            with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                
                # 按评分排序
                sorted_news = sorted(
                    news_list, 
                    key=lambda x: x.get('importance_score', 0) or 0, 
                    reverse=True
                )
                
                for rank, news in enumerate(sorted_news, 1):
                    row = {
                        'date': date_str,
                        'rank': rank,
                        'title': news.get('title', ''),
                        'source': _normalize_source_label(news.get('source', '')),
                        'category': news.get('category', 'Other'),
                        'country': news.get('country', 'Global'),
                        'ai_summary': news.get('ai_summary', ''),
                        'score': news.get('importance_score', 0),
                        'related_count': news.get('related_count', 0) or 0,
                        'event_id': news.get('event_id', ''),
                        'url': news.get('url', ''),
                    }
                    writer.writerow(row)
            
            logger.info(f"CSV report generated: {output_path} ({len(sorted_news)} items)")
            return output_path
            
        except Exception as e:
            logger.error(f"Failed to generate CSV report: {e}")
            raise
