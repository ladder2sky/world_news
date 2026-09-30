"""
播报脚本生成模块
"""
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

from loguru import logger

import settings

class ScriptGenerator:
    """TTS播报脚本生成器"""
    
    def __init__(self, output_dir: Path = None):
        """
        初始化脚本生成器
        
        Args:
            output_dir: 输出目录
        """
        self.output_dir = output_dir or settings.OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_script(self, news_list: List[Dict[str, Any]],
                       max_count: int = 10, date_str: str = None) -> Path:
        """
        生成TTS播报脚本
        
        Args:
            news_list: 新闻列表
            max_count: 最大新闻数量
            date_str: 日期字符串 (YYYY-MM-DD)
            
        Returns:
            生成的脚本文件路径
        """
        if date_str is None:
            date_str = datetime.now().strftime('%Y-%m-%d')
        
        filename = f"daily_script_{date_str.replace('-', '')}.txt"
        output_path = self.output_dir / filename
        
        try:
            # 按评分排序，取前N条
            sorted_news = sorted(
                news_list,
                key=lambda x: x.get('importance_score', 0) or 0,
                reverse=True
            )[:max_count]
            
            lines = []
            lines.append(f"Good morning, this is your daily news briefing for {date_str}.")
            lines.append(f"Today's top stories: {len(sorted_news)} items.")
            lines.append("")
            
            for rank, news in enumerate(sorted_news, 1):
                score = news.get('importance_score', 0) or 0
                category = news.get('category', 'Other')
                ai_summary = news.get('ai_summary', '')
                title = news.get('title', '')
                source = news.get('source', '')
                
                lines.append(f"Story {rank}, score {score}.")
                if ai_summary:
                    lines.append(f"{ai_summary}")
                else:
                    lines.append(f"{title}")
                lines.append(f"Source: {source}, Category: {category}.")
                lines.append("")
            
            lines.append("That's all for today's news briefing.")
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            
            logger.info(f"TTS script generated: {output_path}")
            return output_path
            
        except Exception as e:
            logger.error(f"Failed to generate TTS script: {e}")
            raise
