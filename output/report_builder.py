"""
报告组装模块
"""
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from loguru import logger

import settings

class ReportBuilder:
    """报告生成器"""
    
    def __init__(self, output_dir: Path = None):
        """
        初始化报告生成器
        
        Args:
            output_dir: 输出目录
        """
        self.output_dir = output_dir or settings.OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def build_summary_text(self, news_list: List[Dict[str, Any]],
                          date_str: str = None) -> Path:
        """
        生成每日摘要文本报告
        
        Args:
            news_list: 新闻列表
            date_str: 日期字符串 (YYYY-MM-DD)
            
        Returns:
            生成的文本文件路径
        """
        if date_str is None:
            date_str = datetime.now().strftime('%Y-%m-%d')
        
        filename = f"daily_summary_{date_str.replace('-', '')}.txt"
        output_path = self.output_dir / filename
        
        try:
            # 按评分排序
            sorted_news = sorted(
                news_list,
                key=lambda x: x.get('importance_score', 0) or 0,
                reverse=True
            )
            
            lines = []
            lines.append("=" * 60)
            lines.append(f"Daily News Summary - {date_str}")
            lines.append(f"Total: {len(sorted_news)} items")
            lines.append("=" * 60)
            lines.append("")
            
            for rank, news in enumerate(sorted_news, 1):
                score = news.get('importance_score', 0) or 0
                category = news.get('category', 'Other')
                country = news.get('country', 'Global')
                title = news.get('title', '')
                ai_summary = news.get('ai_summary', '')
                source = news.get('source', '')
                
                lines.append(f"[{rank}] Score: {score} | {category} | {country}")
                lines.append(f"    Title: {title}")
                if ai_summary:
                    lines.append(f"    Summary: {ai_summary}")
                lines.append(f"    Source: {source}")
                lines.append("")
            
            lines.append("=" * 60)
            lines.append("End of Report")
            lines.append("=" * 60)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            
            logger.info(f"Summary report generated: {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"Failed to generate summary report: {e}")
            raise
