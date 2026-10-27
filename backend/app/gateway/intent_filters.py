"""查询意图噪声过滤与语言偏置。

目标（用户明确要求）：
- A：非学术意图时过滤 doi.org / Crossref 等论文站点，避免"提示词"这类查询混进论文；
- B：英文/中英混合查询时对中文内容农场做有界降权（乘性、可解释、不改 URL 去重与 RRF 语义）。

全部为纯函数，便于离线回归。
"""
import re
from typing import Any, Iterable, List
from urllib.parse import urlparse

# 论文/出版站点：仅当查询不是学术意图时才过滤
ACADEMIC_DOMAINS = {
    "doi.org", "dx.doi.org", "crossref.org", "api.crossref.org",
    "link.springer.com", "springer.com", "sciencedirect.com", "ieeexplore.ieee.org",
    "nature.com", "science.org", "pubmed.ncbi.nlm.nih.gov", "researchgate.net",
    "semanticscholar.org", "openalex.org", "arxiv.org", "mdpi.com", "frontiersin.org",
    "tandfonline.com", "onlinelibrary.wiley.com", "sagepub.com", "jstor.org",
    "ssrn.com", "cnki.net", "wanfangdata.com.cn", "plos.org", "biorxiv.org",
}

# 中文内容农场/聚合站：英文或中英混合查询时降权（不是删除）
CN_CONTENT_DOMAINS = {
    "bilibili.com", "csdn.net", "blog.csdn.net", "aicoding.csdn.net",
    "mp.weixin.qq.com", "zhihu.com", "zhuanlan.zhihu.com", "baike.baidu.com",
    "so.com", "ai.so.com", "cnblogs.com", "juejin.cn", "segmentfault.com",
    "51cto.com", "jianshu.com", "douban.com", "xiaohongshu.com", "toutiao.com",
}

ACADEMIC_KEYWORDS = (
    "论文", "文献", "学术", "期刊", "综述", "引用", "预印本", "研究进展", "实验",
    "paper", "papers", "literature", "survey", "arxiv", "doi", "citation",
    "preprint", "journal", "peer-reviewed", "benchmark",
)

CN_CONTENT_PENALTY = 0.6

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_LATIN_RE = re.compile(r"[A-Za-z]{2,}")


def detect_lang(query: str) -> str:
    """纯本地语言判定：zh / en / mixed / other。"""
    text = query or ""
    has_cjk = bool(_CJK_RE.search(text))
    has_latin = bool(_LATIN_RE.search(text))
    if has_cjk and has_latin:
        return "mixed"
    if has_cjk:
        return "zh"
    if has_latin:
        return "en"
    return "other"


def is_academic_intent(query: str, resolved_route: str = "") -> bool:
    if (resolved_route or "").lower() == "academic":
        return True
    q = (query or "").lower()
    return any(word in q for word in ACADEMIC_KEYWORDS)


def _host(url: str) -> str:
    try:
        return (urlparse(url or "").hostname or "").lower()
    except ValueError:
        return ""


def _matches(host: str, domains: Iterable[str]) -> bool:
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in domains)


def is_academic_domain(url: str) -> bool:
    return _matches(_host(url), ACADEMIC_DOMAINS)


def is_cn_content_domain(url: str) -> bool:
    return _matches(_host(url), CN_CONTENT_DOMAINS)


def filter_academic_noise(items: List[Any], query: str, resolved_route: str = "") -> List[Any]:
    """非学术意图时剔除论文站点结果；学术意图原样返回。"""
    if is_academic_intent(query, resolved_route):
        return items
    return [item for item in items if not is_academic_domain(getattr(item, "url", ""))]


def is_language_biased(query: str) -> bool:
    """只有英文或中英混合查询才降权中文内容站，纯中文查询保持原排序。"""
    return detect_lang(query) in ("en", "mixed")


_LATIN_TOKEN_RE = re.compile(r"[A-Za-z]{3,}")
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
MIN_KEEP_RATIO = 0.2


def _bigrams(text: str) -> set:
    grams = set()
    for run in _CJK_RUN_RE.findall(text or ""):
        for idx in range(len(run) - 1):
            grams.add(run[idx:idx + 2])
    return grams


def filter_low_overlap_zh(items: List[Any], query: str) -> List[Any]:
    """中文查询的词面覆盖过滤：丢掉只命中单字（如"全"→汉语字典）的无关页。

    仅中文查询生效；若过滤后剩余不足 40%，判定为规则不可靠并回退原列表。
    """
    if detect_lang(query) not in ("zh", "mixed") or len(items) < 4:
        return items
    grams = _bigrams(query)
    latin = {token.lower() for token in _LATIN_TOKEN_RE.findall(query or "")}
    latin_compact = [re.sub(r"[^a-z0-9]", "", token) for token in latin]
    if not grams and not latin:
        return items
    kept: List[Any] = []
    for item in items:
        text = f"{getattr(item, 'title', '')} {getattr(item, 'snippet', '') or ''}"
        low = text.lower()
        compact = re.sub(r"[^a-z0-9]", "", low)
        # 英文词按"去连字符/空格"后的紧凑形式匹配，避免 vibe-coding 漏掉 vibecoding
        if (grams & _bigrams(text)) or any(token and token in compact for token in latin_compact):
            kept.append(item)
    if not kept:
        # 带英文关键词却一条都不命中，几乎必然是搜索引擎把中文查询截断了（如"全网vibecoding"→"全"）
        return [] if latin else items
    if len(kept) < max(2, int(len(items) * MIN_KEEP_RATIO)):
        return items
    return kept


def apply_language_bias(items: List[Any], query: str, penalty: float = CN_CONTENT_PENALTY) -> int:
    """对中文内容站做有界乘法降权，返回被调整的条数；不改删除、不改其他字段。"""
    if not items or not is_language_biased(query):
        return 0
    adjusted = 0
    for item in items:
        if is_cn_content_domain(getattr(item, "url", "")):
            item.final_score = round(float(item.final_score) * penalty, 5)
            item.metadata["language_bias"] = f"cn_content_x{penalty}"
            adjusted += 1
    return adjusted
