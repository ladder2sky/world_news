"""
本地LLM客户端（统一使用 OpenAI 兼容协议 /v1）

同时兼容：
- Ollama（v0.1.38+）  : base_url 形如 http://localhost:11434/v1
- LM Studio            : base_url 形如 http://127.0.0.1:1234/v1  (默认直接写 http://127.0.0.1:1234 也会自动补 /v1)
- 任何 OpenAI 兼容端点

如果 settings.OLLAMA_BASE_URL 结尾没有显式带 /v1，本类会自动补上以兼容常见配置。
"""
import json
import re
import requests
from typing import Optional, Dict, Any
from urllib.parse import urlparse

from loguru import logger

import settings

def _normalize_base_url(raw: str) -> str:
    """把用户给的 base_url 规整到 OpenAI 兼容的 <host>/v1 形式。

    例：
      http://127.0.0.1:1234      -> http://127.0.0.1:1234/v1
      http://localhost:11434/v1  -> http://localhost:11434/v1
    """
    raw = (raw or '').rstrip('/')
    if not raw:
        return raw
    parsed = urlparse(raw)
    path = parsed.path or ''
    if not path.endswith('/v1'):
        raw += '/v1'
    return raw


class OllamaClient:
    """本地 LLM 客户端（OpenAI 兼容协议）"""

    def __init__(self, base_url: str = None, api_key: str = None):
        self.base_url = _normalize_base_url(base_url or settings.OLLAMA_BASE_URL)
        self.session = requests.Session()
        headers = {'Content-Type': 'application/json'}
        if api_key:
            headers['Authorization'] = f"Bearer {api_key}"
        self.session.headers.update(headers)

    # ------------------------------------------------------------------ health
    def is_available(self) -> bool:
        """
        检查本地 LLM 服务是否可用。

        优先用 OpenAI 标准的 GET /v1/models 做探测；
        若 /v1/models 不通（LM Studio 个别版本），再回退到 GET /v1/health (Ollama)。
        """
        urls_to_try = [f"{self.base_url}/models"]
        base_host = self.base_url[:-3] if self.base_url.endswith('/v1') else self.base_url
        urls_to_try.append(f"{base_host.rstrip('/')}/health")

        for url in urls_to_try:
            try:
                resp = self.session.get(url, timeout=5)
                if resp.status_code == 200:
                    return True
            except Exception:
                continue
        logger.warning(f"LLM service unavailable (tried: {urls_to_try})")
        return False

    # ------------------------------------------------------------------ generate
    def generate(self, model: str, prompt: str,
                 stream: bool = False) -> Optional[str]:
        """把 prompt 包成单条 user message 调 chat completion。

        这样 generate() 签名对外保持不变，NewsAnalyzer 无需改动。
        """
        messages = [{'role': 'user', 'content': prompt}]
        return self.chat(model, messages)

    # ------------------------------------------------------------------ chat
    def chat(self, model: str, messages: list,
             temperature: float = 0.1,
             max_tokens: int = 2048) -> Optional[str]:
        """OpenAI chat_completions 风格调用。"""
        try:
            payload = {
                'model': model,
                'messages': messages,
                'temperature': temperature,
                'max_tokens': max_tokens,
                'stream': False,
            }
            url = f"{self.base_url}/chat/completions"
            response = self.session.post(url, json=payload, timeout=300)
            response.raise_for_status()

            data = response.json()
            choices = data.get('choices', [])
            if not choices:
                logger.warning(f"Empty choices from model {model}")
                return ''
            msg = choices[0].get('message', {}) or {}

            # ----- 1) 优先读标准 message.content -----
            content = msg.get('content', '') or ''
            if isinstance(content, list):
                # 某些推理服务返回 content=[{type:text,text:...}]
                parts = [c.get('text', '') if isinstance(c, dict) else str(c) for c in content]
                content = ''.join(parts)
            content = (content or '').strip()
            if content:
                return content

            # ----- 2) content 为空，回退到 reasoning_content（LM Studio / Ollama 的 DeepSeek R1、Gemma 4、Qwen-R 等 extended-thinking 模型）
            reasoning = msg.get('reasoning_content') or msg.get('reasoning') or data.get('reasoning_content') or ''
            if isinstance(reasoning, list):
                reasoning = ''.join(c.get('text', '') if isinstance(c, dict) else str(c) for c in reasoning)
            reasoning = (reasoning or '').strip()
            if not reasoning:
                logger.warning(f"Model {model} returned empty content AND empty reasoning_content.")
                return ''

            extracted = self._extract_final_answer_from_reasoning(reasoning)
            if extracted:
                cleaned = self._extract_final_answer_from_reasoning(extracted) or extracted
                if len(cleaned) >= 20:
                    logger.debug(f"content empty, answer recovered from reasoning_content ({len(extracted)} chars; cleaned={len(cleaned)} chars)")
                    return cleaned
                logger.debug(f"content empty, raw extracted too short ({len(extracted)} chars)")
                return extracted

            # ----- 3) 推理里也没抽出答案：至少把非乱码的后半截（中文为主）塞回去，不要直接放超长 CoT 到 CSV
            trimmed = self._trim_reasoning_noise(reasoning)
            logger.warning(
                f"Model {model} had no clean answer; fallback trimmed reasoning ({len(reasoning)} -> {len(trimmed)} chars)."
            )
            return trimmed

        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error to LLM ({self.base_url}): {e}")
            return None
        except requests.exceptions.Timeout:
            logger.error(f"Timeout calling model {model}")
            return None
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else '?'
            body_snippet = ''
            try:
                body_snippet = (e.response.text or '')[:200] if e.response is not None else ''
            except Exception:
                pass
            logger.error(f"HTTP {status} calling {model} @ {self.base_url}: {body_snippet}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error calling LLM: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error from LLM response: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error calling LLM: {e}")
            return None

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _extract_final_answer_from_reasoning(reasoning: str) -> str:
        """
        Gemma 4 / DeepSeek R1 这类 extended-thinking 模型经常把「正式答案」放在 reasoning 最后几段，
        前面全是 * Role / Task / Requirement 的 bullet points。
        策略：
          1) 先把 reasoning 里最干净的「正文块」挑出来：
             - 排除全部是英文 bullet + 要求列表的部分（例如 "* Role: Chinese News Editor..." 这一大段）
             - 也排除 "Let's check character count again carefully." 这种中间调试句
          2) 在正文块里：
             - 先找最终答案的显式分隔符：“最终回答/因此/综上/中文摘要/简而言之” 之类
             - 没分隔符就抓最后一大段中文句号结尾的自然段落，长度 >= 20
        """
        if not reasoning:
            return ''

        # --- 步骤 1：把 reasoning 切成段落，挑出「高概率真正答案段」的部分 ---
        paragraphs = [p.strip() for p in re.split(r'\n\s*\n', reasoning) if p.strip()]
        body_paragraphs = []
        for p in paragraphs:
            # 丢掉纯项目符号式的要求段（特征：整段有 3+ 行以 "* " / "- " / "  * " / "   1." 开头）
            lines = p.splitlines()
            bullet_lines = sum(
                1 for ln in lines
                if re.match(r'^\s*(?:\*+|\-+|•|\d+[.)\]])\s+', ln)
                or ln.strip().startswith('Sentence ')
                or re.match(r'(?i)^\s*(role|task|target\s*length|structure\s*requirements|language\s*requirements|constraint|who/what|context|impact)\s*[:：]', ln)
            )
            if len(lines) >= 3 and bullet_lines >= len(lines) * 0.6:
                continue

            # 丢掉纯 "Let's check character count" / "Character count summary" 之类中间过程句
            if re.search(r'(?i)check\s+character\s+count|character\s+count\s+summary|字符计数|字数统计|字符统计', p):
                # 这类段通常只包含数字列表，里面混着中文正文的每字计数，不适合直接放摘要
                # 但是它会带一份 "The 62 characters: 澳大利亚储备银行（R..." 的答案原文；
                # 用下面的兜底正则抓。
                m = re.search(r'(?i)The\s*\d+\s*characters\s*[:：]\s*([\s\S]+)$', p)
                if m:
                    body_paragraphs.append(m.group(1).strip())
                continue

            body_paragraphs.append(p)

        # 如果整段正文块看起来太散，合并成一个大文本再抽
        haystack = '\n\n'.join(body_paragraphs) if body_paragraphs else reasoning
        if not haystack:
            haystack = reasoning

        # --- 步骤 2：在 haystack 里找最终回答 ---
        # 显式分隔符（中英文混合）
        sentinel_patterns = [
            r'(?m)^[\s　]*【?(最终回答|最终答案|中文摘要|简要回答|总结|综上所述|综上|因此|简而言之|简言之)】?\s*[:：]\s*',
            r'(?m)(最终回答|最终答案|中文摘要|简要回答)\s*[:：]\s*',
            r'(?im)^\s*Final\s*(answer|summary)\s*[:：]',
            r'(?m)^\s*```(?:json|text)?\s*$([\s\S]+?)^\s*```\s*$',
        ]
        for pat in sentinel_patterns:
            m = re.search(pat, haystack)
            if m:
                tail = haystack[m.end():].strip()
                # 只取到下一条 CoT 的项目符号前（如果还有），并剥掉 ``` 包裹
                tail = re.split(r'(?m)^\s*\*+\s+Role:|^\s*\*+\s*Task:|^\s*Sentence\s*\d+\s*\(', tail, maxsplit=1)[0].strip()
                tail = re.sub(r'^```(?:json|text)?\s*', '', tail)
                tail = re.sub(r'\s*```\s*$', '', tail).strip()
                if len(tail) >= 20:
                    return tail

        # 没分隔符就抓最后一大段不以项目符号开头 + 含中文句号的
        if body_paragraphs:
            good_paragraphs = [
                p for p in body_paragraphs
                if not re.match(r'^[\s\*\-•\d\.]+\s', p) and len(p) >= 30
            ]
        else:
            # 没切出任何正文（比如整个 reasoning 被错误过滤了），就对整个原始 reasoning 切段再找
            good_paragraphs = [
                p for p in paragraphs
                if not re.match(r'^[\s\*\-•\d\.]+\s', p) and len(p) >= 30
            ]
        for p in reversed(good_paragraphs):
            if re.search(r'[。！？!?]', p):
                cut = max(p.rfind('。'), p.rfind('！'), p.rfind('？'), p.rfind('!'), p.rfind('?'))
                if cut > 0:
                    return p[:cut + 1].strip()
                return p.strip()
        return ''

    @staticmethod
    def _trim_reasoning_noise(reasoning: str, cap: int = 260) -> str:
        """万一万一抽不到正式答案，也不要把 10000 字的 CoT 直接塞到摘要列里：只取后半段并截断。"""
        if not reasoning:
            return ''
        if len(reasoning) <= cap:
            return reasoning
        tail = reasoning[len(reasoning) - cap * 2:]
        # 粗暴按第一个出现的中文句号/冒号做起点
        for sentinel in ('因此', '综上', '最终', '简而言之', '答案', '摘要：'):
            idx = tail.find(sentinel)
            if idx != -1 and idx < cap:
                return tail[idx:idx + cap].strip()
        return tail[-cap:].strip()

    # ------------------------------------------------------------------ utils
    def parse_json_response(self, text: str) -> Optional[Dict[str, Any]]:
        """从模型响应里尽力解析 JSON（容忍 Markdown 代码块/中文说明）。"""
        if not text:
            return None

        text_clean = text.strip()

        try:
            return json.loads(text_clean)
        except json.JSONDecodeError:
            pass

        json_patterns = [
            r'```json\s*([\s\S]*?)\s*```',
            r'```\s*([\s\S]*?)\s*```',
            r'(\{[\s\S]*?\})',          # 最外一层花括号，贪婪少匹配
        ]

        for pattern in json_patterns:
            for match in re.findall(pattern, text_clean):
                candidate = match.strip() if isinstance(match, str) else str(match).strip()
                if not candidate:
                    continue
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue

        logger.warning(f"Could not parse JSON from response: {text[:100]}...")
        return None
