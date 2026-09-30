"""
Prompt管理模块
"""
import json
from pathlib import Path
from typing import Dict, Any, Optional

from loguru import logger

import settings

DEFAULT_SUMMARY_CFG: Dict[str, Any] = {
    "prompt": (
        "你是一名中文新闻编辑。请用中文撰写一段 3~5 句话的新闻摘要，"
        "总长度以 120 汉字为目标（允许 100~160 字）。"
        "\n写作要求：\n"
        "1. 第一句交代“谁（国家/机构/人物）在什么时间做了什么决定或发生了什么事”。\n"
        "2. 第二句说明事件发生的直接背景或导火索。\n"
        "3. 第三句说明对市场、政策、普通人群或地缘局势的影响。\n"
        "4. 必要时用第四、五句补充后续进展或各方反应。\n"
        "5. 全文必须是简体中文；如果原文标题或摘要是英文，请先翻译为中文再总结。\n"
        "6. 不要以“摘要：”“总结：”开头，直接输出正文即可。\n\n"
        "新闻标题：{title}\n新闻摘要：{summary}\n\n只输出正文。"
    ),
    "min_chars": 100,
    "target_chars": 120,
    "max_chars": 220,
    "retry_short_prompt": (
        "你上一次的摘要太短（仅 {actual_chars} 字），请补充更多背景、影响或后续信息，"
        "使全文达到 {target_chars} 字左右，仍然只输出中文正文，不要其他说明。"
    ),
    "retry_english_prompt": (
        "你上一次的摘要包含过多英文。请全部改写为简体中文，"
        "英文术语必须配中文译名，然后按 100~160 字重写完整摘要，仅输出正文。"
    ),
}


class PromptManager:
    """Prompt管理器"""
    
    def __init__(self, prompts_file: Path = None):
        """
        初始化Prompt管理器
        
        Args:
            prompts_file: Prompt配置文件路径
        """
        self.prompts_file = prompts_file or settings.AI_PROMPTS_FILE
        self.prompts: Dict[str, Any] = {}
        self._load_prompts()
    
    def _load_prompts(self):
        """加载Prompt配置"""
        try:
            with open(self.prompts_file, 'r', encoding='utf-8') as f:
                self.prompts = json.load(f)
            logger.info(f"Loaded prompts from {self.prompts_file}")
        except FileNotFoundError:
            logger.warning(f"Prompts file not found: {self.prompts_file}, using defaults")
            self.prompts = self._get_default_prompts()
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in prompts file: {e}")
            self.prompts = self._get_default_prompts()

    def _get_default_prompts(self) -> Dict[str, Any]:
        """获取默认Prompt配置"""
        return {
            "classification": {
                "prompt": (
                    "你是一个新闻分类专家。请分析以下新闻，返回JSON格式结果。\n\n"
                    "新闻标题：{title}\n新闻摘要：{summary}\n来源：{source}\n\n"
                    "请从以下类别中选择最匹配的一个：\n"
                    "Politics, Economy, Technology, Science, Military, Energy, Finance, Society, Climate, Health, Culture, Other\n\n"
                    "请判断主要涉及的国家/地区（可多选）：\n"
                    "USA, China, UK, EU, Russia, Japan, Korea, India, ASEAN, MiddleEast, Africa, LatinAmerica, Global\n\n"
                    "返回格式（仅返回JSON）：\n"
                    "{\"category\": \"类别\", \"countries\": [\"国家1\"]}"
                )
            },
            "scoring": {
                "prompt": (
                    "为以下新闻打分（0-100分）。\n\n新闻标题：{title}\n新闻摘要：{summary}\n分类：{category}\n\n"
                    "返回格式（仅返回JSON）：\n"
                    "{\"score\": 分数, \"reasoning\": \"理由\"}"
                )
            },
            "summary": dict(DEFAULT_SUMMARY_CFG),
            "deduplication": {
                "prompt": (
                    "判断以下两条新闻是否报道同一事件。\n\n新闻1：{title1}\n新闻2：{title2}\n\n"
                    "如果是同一事件返回 {\"same_event\": true}，否则返回 {\"same_event\": false}"
                )
            }
        }

    # ---------------------------------------------------------------------------- classification
    def get_classification_prompt(self, title: str, summary: str, source: str) -> str:
        prompt_template = self.prompts.get('classification', {}).get('prompt', '')
        return prompt_template.format(title=title, summary=summary, source=source)

    # ---------------------------------------------------------------------------- scoring
    def get_scoring_prompt(self, title: str, summary: str, category: str) -> str:
        prompt_template = self.prompts.get('scoring', {}).get('prompt', '')
        return prompt_template.format(title=title, summary=summary, category=category)

    # ---------------------------------------------------------------------------- summary
    def _summary_cfg(self) -> Dict[str, Any]:
        """summary 块的配置，缺失字段用默认补齐。"""
        cfg = dict(DEFAULT_SUMMARY_CFG)
        file_cfg = self.prompts.get('summary', {}) or {}
        cfg.update({k: v for k, v in file_cfg.items() if v is not None})
        for int_key in ('min_chars', 'target_chars', 'max_chars'):
            try:
                cfg[int_key] = int(cfg[int_key])
            except Exception:
                pass
        return cfg

    def get_summary_prompt(self, title: str, summary: str) -> str:
        prompt_template = self._summary_cfg().get('prompt', '')
        return prompt_template.format(title=title, summary=summary)

    def get_summary_constraints(self) -> Dict[str, Any]:
        """字数等硬约束，给 analyzer 做质量门使用。"""
        cfg = self._summary_cfg()
        return {
            'min_chars': int(cfg.get('min_chars', 80)),
            'target_chars': int(cfg.get('target_chars', 120)),
            'max_chars': int(cfg.get('max_chars', 240)),
            'retry_short_prompt': cfg.get('retry_short_prompt', ''),
            'retry_english_prompt': cfg.get('retry_english_prompt', ''),
        }

    def get_summary_retry_prompt(self, kind: str, **kwargs) -> str:
        """kind ∈ {'short','english'}，返回二次追问用的 prompt。"""
        cfg = self._summary_cfg()
        tmpl = cfg.get('retry_short_prompt' if kind == 'short' else 'retry_english_prompt', '')
        try:
            return tmpl.format(**kwargs)
        except Exception:
            return tmpl

    # ---------------------------------------------------------------------------- dedup
    def get_deduplication_prompt(self, title1: str, summary1: str, source1: str,
                                 title2: str, summary2: str, source2: str) -> str:
        prompt_template = self.prompts.get('deduplication', {}).get('prompt', '')
        return prompt_template.format(
            title1=title1, summary1=summary1, source1=source1,
            title2=title2, summary2=summary2, source2=source2
        )

    # ---------------------------------------------------------------------------- lists
    def get_categories(self) -> list:
        return self.prompts.get('classification', {}).get(
            'categories',
            ['Politics', 'Economy', 'Technology', 'Science', 'Military', 
             'Energy', 'Finance', 'Society', 'Climate', 'Health', 'Culture', 'Other']
        )
    
    def get_countries(self) -> list:
        return self.prompts.get('classification', {}).get(
            'countries',
            ['USA', 'China', 'UK', 'EU', 'Russia', 'Japan', 'Korea', 
             'India', 'ASEAN', 'MiddleEast', 'Africa', 'LatinAmerica', 'Global']
        )
