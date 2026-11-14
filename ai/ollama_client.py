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


# ------------------------------------------------------------------ sanitizer
# 常见缩写：这些词如果出现在「XXX(缩写)」或「(缩写)」里，一般是模型过度解释，统一去除括号、
# 若只剩缩写本身则直接保留去掉括号的干净形式。
_COMMON_ABBREVS = {
    'fed', 'ecb', 'opec', 'opec+', 'nato', 'un', 'rba', 'boj', 's&p 500',
    's&p500', 's&p', 'vix', 'cpi', 'pce', 'gdp', 'imf', 'who', 'wto',
    'reuters', 'ap', 'bbc', 'cnn', 'fomc', 'ec', 'pboc', 'boj', 'boe',
    'sec', 'fdic', 'eia', 'iea', 'idf', 'eu', 'asean', 'hkma', 'mas',
    'us', 'usa', 'uk', 'jp', 'kr', 'cn', 'apec', 'g7', 'g20', 'brent', 'wti',
}

# 「中文前缀(缩写)」里，前缀本身是对应缩写的标准中文译名的，直接删缩写括号：
#   美联储(Fed) → 美联储 ;  欧洲央行(ECB) → 欧洲央行
_TRANSLATION_MAP = {
    '美联储': 'fed', '美国联邦储备委员会': 'fed', '美国联邦储备理事会': 'fed',
    '欧洲央行': 'ecb', '欧洲中央银行': 'ecb',
    '石油输出国组织': 'opec', '欧佩克': 'opec',
    '北约': 'nato', '北大西洋公约组织': 'nato',
    '联合国': 'un',
    '澳大利亚储备银行': 'rba', '澳联储': 'rba',
    '日本央行': 'boj', '日本银行': 'boj',
    '国际货币基金组织': 'imf', '基金组织': 'imf',
    '世界卫生组织': 'who', '世卫组织': 'who', '世卫': 'who',
    '世界贸易组织': 'wto', '世贸组织': 'wto', '世贸': 'wto',
    '中国人民银行': 'pboc', '央行': 'pboc',
    '英国央行': 'boe', '英格兰银行': 'boe',
    '消费者物价指数': 'cpi', '居民消费价格指数': 'cpi',
    '个人消费支出': 'pce', '国内生产总值': 'gdp',
    '美国证券交易委员会': 'sec', '证券交易委员会': 'sec',
    '联邦存款保险公司': 'fdic',
    '欧盟': 'eu', '欧洲联盟': 'eu',
    '东盟': 'asean', '东南亚国家联盟': 'asean',
    '国际能源署': 'iea', '美国能源信息署': 'eia',
    '以色列国防军': 'idf',
    '亚太经济合作组织': 'apec', '亚太经合组织': 'apec',
}


def _sanitize_llm_text(text: str) -> str:
    """
    LLM 输出文本的统一清洗（reasoning_content 恢复出来的正文 & content 正文都会走这里）：
      1. 剥 ``` 代码块 / "摘要：" / "总结：" / 数字编号前缀
      2. 删除 (1)(2)(3)… 乃至 （100）（101）… 的多位数编号括号 & "The N characters:" / "Count:" 行
      3. 删行首 CoT 元话术前缀（Role/Task/Final Polish/Impact/Status/Total characters…）
      4. 丢掉整行不含汉字的 CoT 残渣行（前提：整段至少有一行含汉字）
      5. 对常见缩写的过度括号做压缩：
         - 「美联储(Fed)」 / 「美联储 (Fed)」  →  「美联储」
         - 「标普 500(S&P 500)」这种括号里外是一回事 → 保留前面的中文名或缩写之一
         - 括号内容是纯常见缩写 + 长度 <= 10，且出现>=3对括号时，全部剥除到只剩<2对
      6. 剥连续的 Source: News - XXX 前缀（等下由 report_builder 里正经 Source 字段接管）
      7. 中文标点规范化："()" -> "（）" 但本函数里方向：英文括号->中文括号，只有需要保留的括号才规范；
         我们尽量直接去掉多余括号，能不保留就不保留。
    """
    if not text:
        return ''

    s = text.replace('\r\n', '\n').replace('\r', '\n').strip()

    # 1) 剥代码块
    s = re.sub(r'^```(?:json|text)?\s*', '', s, flags=re.MULTILINE)
    s = re.sub(r'\s*```\s*$', '', s, flags=re.MULTILINE)

    # 1.5) 结构化 JSON 响应（分类/打分）直接原样返回，不做面向自然语言的逐行清洗。
    #      否则下面「丢弃整行不含汉字」会把 {\n "score": 62,\n "reasoning": "…",\n} 里的
    #      结构行全部删掉（这些行本来就不含汉字），只剩 "reasoning": "…" 一行，
    #      导致 parse_json_response 解析失败、打分/分类降级。
    if s.lstrip()[:1] in ('{', '['):
        return s.strip()

    # 2) 剥 "The N characters:" 这种逐字计数整行
    s = re.sub(r'(?im)^\s*The\s+\d+\s+characters?\s*[:：]\s*', '', s)
    s = re.sub(r'(?im)^\s*Character\s+count\s*[:：].*$', '', s)
    s = re.sub(r'(?im)^\s*Let\'?s\s+check\s+character\s+count.*$', '', s)
    # 同段内嵌的 The 62 characters: (1)x(2)y ... 这种也剥（不是整行的情况）
    s = re.sub(r'(?i)The\s+\d+\s+characters?\s*[:：]\s*', '', s)

    # 3) 剥 (1)(2)(3)... / （1）（2）（3）... 数字编号括号（中文括号也去掉）
    #    注意要覆盖多位数字：模型数汉字时会输出 （100）（101）… 这种三位数逐字计数
    s = re.sub(r'\(\s*\d{1,4}\s*\)', '', s)
    s = re.sub(r'（\s*\d{1,4}\s*）', '', s)
    # 1. 2. 3. / 1) 2) 3) 这种一行内编号（不是列表，正文里的）
    s = re.sub(r'(?<!\d)\b\d{1,2}\s*[.)、]\s*(?=[\u4e00-\u9fa5A-Z])', '', s)

    # 4) 剥 Role: / Task: / Final Polish: / Count: / Impact/Status: 类行首 CoT 元话术前缀
    s = re.sub(
        r"(?im)^[\s\*\-•]*("
        r"Role|Task|Target length|Structure requirements|Language requirements|"
        r"Constraint|Who/When/What|Context|Impact\s*/\s*Status|Impact|Status|"
        r"Final\s+(?:Text|Polish|Answer|Draft)(?:\s+Construction)?|Final|"
        r"Count|Text|Total\s+characters?|Character\s+count(?:\s+check)?|"
        r"Let'?s\s+[^\n。！？]{0,60}|Wait[^\n。！？]{0,60}|"
        r"Refine[d]?|Re-?verify[^\n。！？]{0,60}|Numbering|Meta-?talk"
        r")\s*[:：]?\s*",
        '', s,
    )

    # 5) 剥 "Summary:" / "摘要：" / "总结：" / "最终回答：" 前缀
    s = re.sub(
        r'(?im)^\s*(Summary|最终回答|最终答案|中文摘要|简要回答|总结|综上所述|综上|因此|简而言之|简言之)\s*[:：]\s*',
        '', s,
    )

    # 6) 先强制对 _TRANSLATION_MAP 的标准译名做「整词整句」剥除
    #    （避免括号压缩器因为前缀过短而没抓到）
    s = _strip_known_translation_parens(s)

    # 7) 连续 3+ 对括号压缩 + 常见缩写去括号
    s = _collapse_brackets(s)

    # 8) Source: News - XXX 这类脏前缀（如果被误混进正文里的话）
    s = re.sub(r'(?im)^\s*Source\s*[:：]\s*News\s*-\s*', 'Source: ', s)

    # 9) 去掉句首「孤立引号」（CoT 残渣）：仅当整段没有与之配对的闭引号时才剥，避免误伤正文引号
    for open_q, close_q in (('"', '"'), ('\u201c', '\u201d')):
        if s.startswith(open_q) and close_q not in s[1:]:
            s = s[1:].lstrip()

    # 10) 丢掉「整行不含任何汉字」的 CoT 元话术行（如裸的 "Final Polish:"、"No numbering? Yes."）。
    #    前提是整段至少有一行含汉字——若整段都没汉字（模型整段跑英文），保留原样交给质量门重试。
    if any('\u4e00' <= ch <= '\u9fff' for ch in s):
        s = '\n'.join(
            ln for ln in s.split('\n')
            if (not ln.strip()) or any('\u4e00' <= ch <= '\u9fff' for ch in ln)
        )

    # 11) 合并多余空白
    s = re.sub(r'[ \t\u3000]+', ' ', s)
    s = re.sub(r'\n{3,}', '\n\n', s)
    return s.strip()


def _strip_known_translation_parens(s: str) -> str:
    """
    对 _TRANSLATION_MAP 里收录的标准译名执行硬剥除：
      美联储(Fed) / 美联储 （Fed） / 美联储（Fed）、  -> 美联储
    大小写不敏感，允许中/英文括号、前后 0~2 个空格。
    """
    if not s:
        return s
    for zh_cn, abbr in _TRANSLATION_MAP.items():
        # 允许：(abbr) （abbr） [空格 0~2]
        pat = re.compile(
            r'%s\s{0,2}[\(（]\s*%s\s*[\)）]\s{0,2}' % (re.escape(zh_cn), re.escape(abbr)),
            re.IGNORECASE,
        )
        s = pat.sub(zh_cn, s)
    return s


def _collapse_brackets(s: str) -> str:
    """
    针对括号过多的核心压缩策略：
      A. 先把所有英文括号 () 都先替换成中文（），然后统一处理中文括号；
         这样不用区分半角/全角。
      B. 对每一对「前缀 + (内容)」分类处理：
         1. 前缀是标准中文译名，括号内容是对应常见缩写（_TRANSLATION_MAP）：直接删括号和缩写，保留中文译名。
         2. 括号内容是纯常见缩写，且长度 <= 10：可删除标记记 1。
         3. 括号内容和前缀重复（标普500(S&P500) / S&P500(标普500)）：删括号和内容。
      C. 最后，如果可删除标记的括号 >= 3 对，就把这些可删的全部删掉；否则保留前 1~2 对，其它冗余的删掉（保证<=2对）。
    """
    if not s:
        return s

    # A) 统一括号成中文括号，方便后续处理
    s = s.replace('(', '（').replace(')', '）')

    # 匹配：<前缀1~20字>（<内容>）
    #   前缀是非括号非空白的字符，尽量短；内容不含中文括号
    pattern = re.compile(r'(?P<prefix>[\u4e00-\u9fa5A-Za-z0-9&+\-\.\s]{1,20}?)（(?P<inner>[^（）]{0,40})）')

    removable_ranges = []   # 候选可删除括号的 (start,end)
    for m in pattern.finditer(s):
        prefix = (m.group('prefix') or '').strip().lower()
        inner  = (m.group('inner')  or '').strip()
        inner_low = inner.lower().replace(' ', '')

        # 情况 1：前缀(无括号尾部的词)是标准中文译名，inner是对应缩写
        tail_word = re.sub(r'[\s\-]+$', '', (m.group('prefix') or '')).strip()
        tail_low  = tail_word.lower()
        if tail_word in _TRANSLATION_MAP and _TRANSLATION_MAP[tail_word] == inner_low:
            removable_ranges.append((m.start('prefix') + len(tail_word), m.end()))
            continue
        # 兼容：前缀里最后一个词 = 译名
        last_match = re.search(r'[\u4e00-\u9fa5A-Za-z]+$', tail_word or '')
        if last_match:
            last_word = last_match.group(0)
            if last_word in _TRANSLATION_MAP and _TRANSLATION_MAP[last_word] == inner_low:
                removable_ranges.append((m.start('prefix') + last_match.start(), m.end()))
                continue

        # 情况 2：inner 是纯常见缩写（不依赖前缀）
        if inner_low in _COMMON_ABBREVS and len(inner) <= 10:
            # 如果前缀本身已经提到了这个意思（例如"原油WTI（WTI）"或"WTI（西德克萨斯中质原油）"重复），整括号可删
            pref_clean = re.sub(r'[\s\(\)（）\-]+', '', prefix or '')
            inner_clean_nospace = inner_low.replace('&', '').replace('+', '')
            if inner_clean_nospace in pref_clean or pref_clean.endswith(inner_clean_nospace[:-1]):
                removable_ranges.append(m.span())
                continue
            # 其它情况：先标记为"可优先移除的冗余候选"
            removable_ranges.append((m.start('inner') - 1, m.end()))  # 把括号一起删除（-1 包含开括号）

        # 情况 3：前后重复：prefix 末尾 == inner（不区分大小写/空白）
        pref_tail_clean = re.sub(r'[\s&+\.\-]+', '', prefix or '')
        inner_no_space     = re.sub(r'[\s&+\.\-]+', '', inner_low)
        if inner_no_space and (pref_tail_clean.endswith(inner_no_space) or inner_no_space.endswith(pref_tail_clean)):
            removable_ranges.append((m.start('prefix') + max(0, len(prefix) - len(inner)), m.end()))

    # C) 真正删除：保证整条摘要最后 <= 2 对括号。从后往前删除，避免索引漂移。
    # 先数当前总括号对
    total_pairs = s.count('（')
    to_remove = []
    if total_pairs > 2:
        # 先把 removable_ranges 里标记的都尽量删；如果还是>2对，再把最前面的冗余也剥掉
        removable_ranges_sorted = sorted(set(removable_ranges), key=lambda x: x[0], reverse=True)
        for (a, b) in removable_ranges_sorted:
            if total_pairs <= 2:
                break
            seg = s[a:b]
            removed_pairs = seg.count('（')
            if removed_pairs <= 0:
                continue
            s = s[:a] + s[b:]
            total_pairs -= removed_pairs
            to_remove.append((a, b))

        # 如果还是 >2 对（说明没标到那么多），就直接把最靠前的那些括号里 inner 是纯常见缩写的硬删
        if total_pairs > 2:
            def _brute_force_remove(text):
                pairs_left = text.count('（')
                out = []
                i = 0
                while i < len(text):
                    if text[i] == '（' and pairs_left > 2:
                        j = text.find('）', i + 1)
                        if j != -1:
                            inner = text[i + 1:j]
                            if inner.lower().strip() in _COMMON_ABBREVS:
                                i = j + 1
                                pairs_left -= 1
                                continue
                    out.append(text[i])
                    i += 1
                return ''.join(out)
            s = _brute_force_remove(s)

    # 最后清理可能留下的空括号和脏空格
    s = s.replace('（）', '')
    # 如果留下了孤立的半角括号（极少数没被替换干净的），清理
    s = re.sub(r'[()]+', '', s)
    # 中文字符之间的多余空格可能被上面生成，再次合并
    s = re.sub(r'(?<=[\u4e00-\u9fa5，。！？；：])\s+(?=[\u4e00-\u9fa5A-Za-z0-9])', '', s)
    return s


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
                return _sanitize_llm_text(content)

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
                cleaned_raw = self._extract_final_answer_from_reasoning(extracted) or extracted
                cleaned_final = _sanitize_llm_text(cleaned_raw)
                if len(cleaned_final) >= 20:
                    logger.debug(
                        f"content empty, answer recovered from reasoning_content "
                        f"({len(extracted)} -> {len(cleaned_raw)} -> {len(cleaned_final)} chars)"
                    )
                    return cleaned_final
                logger.debug(f"content empty, raw extracted too short ({len(extracted)} chars)")
                return _sanitize_llm_text(extracted)

            # ----- 3) 推理里也没抽出答案：至少把非乱码的后半截（中文为主）塞回去，不要直接放超长 CoT 到 CSV
            trimmed = _sanitize_llm_text(self._trim_reasoning_noise(reasoning))
            logger.warning(
                f"Model {model} had no clean answer; fallback trimmed reasoning "
                f"({len(reasoning)} -> {len(trimmed)} chars)."
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
