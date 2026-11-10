"""
报告层新闻去重（方案B）：把「同一事件的不同报道」聚成一簇，只保留评分最高的一条，
并记录该簇内其它报道的条数（related_count），供报告标注「另有 N 篇相关报道」。

判据（满足任一即认为两条属同一簇）：
1. 标题字符 3-gram Jaccard >= jac3_th（近似「近乎相同的标题」）
2. 0.75 * IDF 加权余弦 + 0.25 * 3-gram Jaccard >= mix_th（整体相似）
3. 两条标题共享 >= min_shared_entities 个「稀有专有名词」
   （稀有 = 该实体在全库标题里出现的次数 <= rare_df）

合并使用并查集（单链聚类），每簇保留 importance_score 最高者。

注意：判据 3 只统计「专有名词」（首字母大写/全大写，排除句首常见词），
并且用「实体在全库中的文档频率」判定稀有，避免 us / ai / eu 这类高频缩写被误当作主实体。
"""
import math
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Sequence

# 句首常见词：出现在标题第一个词时不算专有名词
_SENT_START = set('''here there this that these those it he she they we you what how why when
where which who whom the a an and or but if of to in on at for with from by as is are was were
be been more most than then all any some one two three new news top live latest update updates
breaking exclusive opinion analysis video photos watch world international amid ahead'''.split())

# 通用词 / 机构缩写：永不作为「主实体」参与合并判定（df 修正后大多也会自然变常见，这里再兜底）
_COMMON_ENTITIES = set('''us usa uk eu un ai g ii iii one two five new top amid asia europe world
financial times business news reuters bloomberg cnbc cnn bbc nyt npr scmp ap here there'''.split())

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*")
_LAT_RE = re.compile(r"[a-z0-9][a-z0-9'\-]*")


def _stem(word: str) -> str:
    """极简英文词干化：去掉所有格 's 和常见后缀，用于英文词/实体归并。"""
    word = re.sub(r"['\u2019]s$", '', word)
    for suffix in ('ing', 'ed', 'es', 's'):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[:-len(suffix)]
    return word


def _norm_title(title: str) -> str:
    """去掉标题里 " - 来源" / " | 来源" 这类尾巴，统一弯引号。"""
    t = (title or '').replace('\u2019', "'")
    return re.split(r'\s+[-|\u2013\u2014]\s+', t)[0].strip()


def _title_tokens(title: str) -> set:
    """标题可比较词元集合：英文小写词干（len>=3，去停用词）+ 中文 2-gram。"""
    tl = _norm_title(title).lower()
    lat = {_stem(w) for w in _LAT_RE.findall(tl) if len(w) >= 3 and w not in _SENT_START}
    cjk = []
    for run in re.findall(r'[\u4e00-\u9fff]+', tl):
        cjk += [run[i:i + 2] for i in range(len(run) - 1)] or [run]
    return lat | set(cjk)


def _title_entities(title: str) -> List[str]:
    """标题里的专有名词候选（小写词干，按出现顺序去重），用于判据 3。"""
    words = _WORD_RE.findall(_norm_title(title))
    out: List[str] = []
    for idx, w in enumerate(words):
        lw = _stem(w.lower())
        if idx == 0 and lw in _SENT_START:
            continue
        if ((w.isupper() and len(w) >= 2) or w[0].isupper()) and lw not in out:
            out.append(lw)
    return out


def _char_trigrams(text: str) -> set:
    t = re.sub(r'\s+', ' ', _norm_title(text).lower())
    return {t[i:i + 3] for i in range(max(0, len(t) - 2))}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class NewsDeduplicator:
    """基于标题的新闻去重器（详见模块 docstring）。"""

    def __init__(self, rare_df: int = 80, jac3_th: float = 0.50,
                 mix_th: float = 0.42, min_shared_entities: int = 2):
        self.rare_df = int(rare_df)
        self.jac3_th = float(jac3_th)
        self.mix_th = float(mix_th)
        self.min_shared_entities = int(min_shared_entities)

    def dedupe(self, news_list: Sequence[Dict[str, Any]],
               corpus_titles: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        """
        对 news_list 去重。

        Args:
            news_list: 待去重的新闻（dict 列表）
            corpus_titles: 用于统计实体文档频率的背景标题（通常是全库标题）；
                           不传时退化为只用 news_list 自身，效果会偏激进，建议传入。

        Returns:
            去重后的列表，每条 dict 额外带 ``related_count`` 字段（被合并掉的同簇报道数）。
        """
        items = [dict(x) for x in news_list]
        if len(items) < 2:
            for it in items:
                it.setdefault('related_count', 0)
            return items

        corpus = [t for t in (corpus_titles or []) if t]
        if not corpus:
            corpus = [it.get('title', '') for it in items]

        n_docs = max(len(corpus), 1)
        df_word = Counter()
        df_entity = Counter()
        for t in corpus:
            df_word.update(_title_tokens(t))
            df_entity.update(_title_entities(t))
        idf = {w: math.log(n_docs / (1 + c)) for w, c in df_word.items()}
        idf_default = math.log(n_docs / 1)

        toks = [_title_tokens(it.get('title', '')) for it in items]
        ents = [_title_entities(it.get('title', '')) for it in items]
        trigrams = [_char_trigrams(it.get('title', '')) for it in items]

        def _cos(a: set, b: set) -> float:
            shared = a & b
            if not shared:
                return 0.0
            norm = lambda s: math.sqrt(sum(idf.get(w, idf_default) ** 2 for w in s)) or 1e-9
            return sum(idf.get(w, idf_default) ** 2 for w in shared) / (norm(a) * norm(b))

        def _rare(i: int) -> List[str]:
            return [w for w in ents[i]
                    if df_entity.get(w, 0) <= self.rare_df and w not in _COMMON_ENTITIES]

        parent = list(range(len(items)))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                jac = _jaccard(trigrams[i], trigrams[j])
                hit = jac >= self.jac3_th or \
                    (0.75 * _cos(toks[i], toks[j]) + 0.25 * jac) >= self.mix_th
                if not hit:
                    ri, rj = _rare(i), _rare(j)
                    if ri and rj:
                        shared = len(set(ri) & set(rj))
                        hit = shared >= self.min_shared_entities
                if hit:
                    a, b = find(i), find(j)
                    if a != b:
                        parent[max(a, b)] = min(a, b)

        groups: Dict[int, List[int]] = {}
        for i in range(len(items)):
            groups.setdefault(find(i), []).append(i)

        kept: List[Dict[str, Any]] = []
        for idxs in groups.values():
            idxs.sort(key=lambda k: (items[k].get('importance_score') or 0), reverse=True)
            rep = items[idxs[0]]
            rep['related_count'] = len(idxs) - 1
            kept.append(rep)

        kept.sort(key=lambda x: (x.get('importance_score') or 0), reverse=True)
        return kept


def dedupe_news(news_list: Sequence[Dict[str, Any]],
                corpus_titles: Optional[Sequence[str]] = None,
                rare_df: int = 80) -> List[Dict[str, Any]]:
    """便捷函数：用默认参数（方案B）对 news_list 去重。"""
    return NewsDeduplicator(rare_df=rare_df).dedupe(news_list, corpus_titles)
