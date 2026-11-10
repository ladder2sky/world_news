"""
AI分析主逻辑模块
"""
import re
import unicodedata
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger

import settings
from ai.ollama_client import OllamaClient
from ai.prompts import PromptManager


def _chinese_char_ratio(text: str) -> float:
    """文本中汉字（CJK Unified Ideographs）占全部可打印字符的比例。"""
    if not text:
        return 0.0
    cps = [ch for ch in text if not unicodedata.category(ch).startswith('Z') and ch not in '\r\n\t']
    if not cps:
        return 0.0
    han = sum(1 for ch in cps if '\u4e00' <= ch <= '\u9fff')
    return han / len(cps)


class NewsAnalyzer:
    """新闻AI分析器"""

    def __init__(self):
        """初始化分析器"""
        self.client = OllamaClient()
        self.prompt_manager = PromptManager()
        self.model_main = settings.AI_MODEL_MAIN
        self.model_light = settings.AI_MODEL_LIGHT
        self.summary_constraints = self.prompt_manager.get_summary_constraints()

    def check_service(self) -> bool:
        return self.client.is_available()

    # ---------------------------------------------------------------- classify
    def classify_news(self, news: Dict[str, Any]) -> Dict[str, Any]:
        prompt = self.prompt_manager.get_classification_prompt(
            title=news.get('title', ''),
            summary=news.get('summary', ''),
            source=news.get('source', '')
        )
        response = self.client.generate(self.model_main, prompt)
        result = self.client.parse_json_response(response)
        if result:
            category = result.get('category', 'Other')
            countries = result.get('countries', ['Global'])
            valid_categories = self.prompt_manager.get_categories()
            if category not in valid_categories:
                category = 'Other'
            if not isinstance(countries, list):
                if isinstance(countries, str):
                    countries = [c.strip() for c in countries.split(',') if c.strip()] or ['Global']
                else:
                    countries = ['Global']
            return {'category': category, 'countries': countries}
        logger.warning(
            f"Classification failed for: {str(news.get('title', ''))[:50]} | "
            f"LLM raw response ({len(response or '')} chars): {(response or '')[:500]!r}"
        )
        return {'category': 'Other', 'countries': ['Global']}

    # ---------------------------------------------------------------- score
    def score_news(self, news: Dict[str, Any], category: str) -> Dict[str, Any]:
        prompt = self.prompt_manager.get_scoring_prompt(
            title=news.get('title', ''),
            summary=news.get('summary', ''),
            category=category
        )
        response = self.client.generate(self.model_main, prompt)
        result = self.client.parse_json_response(response)
        if result and ('score' in result or 'Score' in result):
            score_val = result.get('score', result.get('Score', 0))
            reasoning_val = result.get('reasoning', result.get('Reasoning', ''))
            try:
                score = int(score_val)
            except Exception:
                score = 0
            score = max(0, min(100, score))
            return {'score': score, 'reasoning': str(reasoning_val)}
        logger.warning(
            f"Scoring failed for: {str(news.get('title', ''))[:50]} | "
            f"LLM raw response ({len(response or '')} chars): {(response or '')[:500]!r}"
        )
        return {'score': 0, 'reasoning': 'Analysis failed'}

    # ---------------------------------------------------------------- summary
    def generate_summary(self, news: Dict[str, Any]) -> str:
        """
        生成中文摘要（带质量门 + 自动重试）：
        - 太短 (< min_chars)：追加要求补信息再试一次
        - 英文占比过高：追加要求改中文再试一次
        - 真失败：不再直接把原始英文 RSS summary 塞回去，改为本地拼装的中文兜底
        """
        constraints = self.summary_constraints
        min_chars = int(constraints.get('min_chars', 80))
        max_chars = int(constraints.get('max_chars', 240))
        target_chars = int(constraints.get('target_chars', 120))

        base_prompt = self.prompt_manager.get_summary_prompt(
            title=news.get('title', ''),
            summary=news.get('summary', '')
        )
        raw = self.client.generate(self.model_light, base_prompt)
        summary = (raw or '').strip()

        # --- 质量门 1：过短 ---
        if summary and len(summary) < min_chars:
            retry_prompt = self.prompt_manager.get_summary_retry_prompt(
                'short',
                actual_chars=len(summary),
                target_chars=target_chars,
                min_chars=min_chars,
                max_chars=max_chars,
            )
            logger.debug(f"Summary too short ({len(summary)}<{min_chars}), retry: {str(news.get('title',''))[:40]}")
            raw2 = self.client.generate(self.model_light, base_prompt + "\n\n" + retry_prompt)
            if raw2 and len(raw2.strip()) >= len(summary):
                summary = raw2.strip()

        # --- 质量门 2：英文/非中文占比过高 ---
        if summary and _chinese_char_ratio(summary) < 0.45:
            retry_zh = self.prompt_manager.get_summary_retry_prompt('english')
            logger.debug(f"Summary too much English, retry in Chinese: {str(news.get('title',''))[:40]}")
            raw3 = self.client.generate(
                self.model_light,
                base_prompt + "\n\n" + retry_zh
            )
            cand = (raw3 or '').strip()
            if cand and _chinese_char_ratio(cand) >= _chinese_char_ratio(summary):
                summary = cand

        # --- 最终清洗：去 markdown 代码块、长度上限按句末软截断 + 括号双保险 ---
        if summary:
            # 方案A落地双保险：复用 ollama_client 层的 _sanitize_llm_text（去编号、The N chars、Role/Task 前缀）
            from ai.ollama_client import _sanitize_llm_text
            summary = _sanitize_llm_text(summary)

            summary = re.sub(r'^[\s　]*【?(摘要|总结|概要)】?\s*[::]\s*', '', summary, flags=re.I)
            if len(summary) > max_chars:
                splits = re.split(r'(?<=[。！？!?；;])', summary)
                rebuilt = ''
                for seg in splits:
                    if len(rebuilt) + len(seg) <= max_chars:
                        rebuilt += seg
                    else:
                        break
                summary = (rebuilt or summary[:max_chars]).rstrip()
                if summary and summary[-1] not in '。！？!?':
                    summary += '。'
            return summary.rstrip()

        # --- 真·中文兜底（绝不把原始英文 RSS summary / 长英文标题 直接塞进 ai_summary） ---
        logger.warning(f"Summary LLM empty, local Chinese fallback: {str(news.get('title',''))[:50]}")
        raw_title = (news.get('title', '') or '').strip()
        src = (news.get('source', '') or '外电').strip()
        parts: List[str] = []

        zh_ratio = _chinese_char_ratio(raw_title)
        if raw_title and zh_ratio >= 0.45:
            # 中文标题可以直接保留作为开头
            parts.append(f"据{src}报道，{raw_title.rstrip('。！？!?')}。")
        elif raw_title:
            # 外文标题：只保留前 22 个字符做极小提示，其余用中文叙述，避免一整句英文漏进摘要
            snippet = raw_title[:22].strip()
            parts.append(f"据{src}发布的一条外文消息，标题涉及：{snippet}…")
        else:
            parts.append(f"据{src}的一条快讯。")

        parts.append("本条 AI 中文摘要未生成，可点击原文链接查看完整报道内容。")
        return ''.join(parts)[:max_chars]

    # ---------------------------------------------------------------- event id
    def generate_event_id(self, category: str, countries: list, title: str) -> str:
        today = datetime.now().strftime('%Y%m%d')
        country_str = countries[0] if countries else 'Global'
        keywords = re.sub(r'[^\w\s]', '', title)[:20].replace(' ', '_')
        return f"{category}_{country_str}_{today}_{uuid.uuid4().hex[:6]}"

    # ---------------------------------------------------------------- batch
    def batch_analyze(self, news_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        analyzed_news = []
        for i, news in enumerate(news_list):
            title_t = news.get('title', '') or ''
            logger.info(f"Analyzing news {i + 1}/{len(news_list)}: {str(title_t)[:50]}")
            try:
                classification = self.classify_news(news)
                category = classification['category']
                countries = classification['countries']
                scoring = self.score_news(news, category)
                ai_summary = self.generate_summary(news)
                event_id = self.generate_event_id(category, countries, str(title_t))
                news['category'] = category
                news['countries'] = countries
                news['score'] = scoring['score']
                news['ai_summary'] = ai_summary
                news['event_id'] = event_id
                analyzed_news.append(news)
            except Exception as e:
                logger.error(f"Error analyzing news: {e}")
                news['category'] = news.get('category') or 'Other'
                news['countries'] = news.get('countries') or ['Global']
                news['score'] = news.get('score') or 0
                news['ai_summary'] = self.generate_summary(news)
                news['event_id'] = news.get('event_id') or ''
                analyzed_news.append(news)
        logger.info(f"Batch analysis complete: {len(analyzed_news)} news items")
        return analyzed_news

    # -------------------------------------------------------------- resummarize
    def resummarize_batch(self, news_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """只重跑摘要（不改分类/打分/event_id），给 --resummarize 用，省 token。"""
        updated = []
        for i, news in enumerate(news_list):
            title_t = news.get('title', '') or ''
            logger.info(f"Resummarizing {i + 1}/{len(news_list)}: {str(title_t)[:50]}")
            try:
                news['ai_summary'] = self.generate_summary(news)
            except Exception as e:
                logger.error(f"Error resummarizing: {e}")
            updated.append(news)
        return updated
