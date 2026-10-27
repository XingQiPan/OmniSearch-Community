"""知乎内容检索渠道（免登录）。

直连知乎搜索接口需要登录 + x-zse-96 签名（api.zhihu.com search_v3 返回
need_login），知乎页面还带 __zse_ck JS 挑战，静态抓取过不去。这里用搜狗
「insite=zhihu.com」站内检索（搜狗收录知乎，免登录可直连）拿到知乎原生
链接与摘要；搜狗失败时回退 Bing site: 限定检索。
"""
import re
from typing import List, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from lxml import html as lxml_html

from app.providers.adapters import (
    SEARCH_ADAPTER_REGISTRY,
    USER_AGENT,
    make_async_client,
    search_bing_web,
)
from app.schemas import UnifiedSearchItem

# 仅收录知乎主站内容（问答 / 专栏 / 想法），排除站外页面。
_ZHIHU_HOST_RE = re.compile(r"^(?:www\.|zhuanlan\.)?zhihu\.com$", re.IGNORECASE)


def _clean_html(raw: str) -> str:
    if not raw:
        return ""
    return BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)


def parse_sogou_zhihu(html_text: str, max_results: int) -> List[UnifiedSearchItem]:
    """解析搜狗站内检索结果，只保留 zhihu.com 域名条目。"""
    items: List[UnifiedSearchItem] = []
    if not html_text:
        return items
    try:
        dom = lxml_html.fromstring(html_text)
    except Exception:  # noqa: BLE001  lxml 对畸形页面可能抛 XMLSyntaxError/ValueError
        return items
    blocks = dom.xpath(
        '//div[contains(@class, "rb")] | '
        '//div[contains(@class, "vrwrap") and not(.//div[contains(@class, "special-wrap")])]'
    )
    seen_urls = set()
    for block in blocks:
        a_nodes = block.xpath('.//h3/a')
        if not a_nodes:
            continue
        title = " ".join(a_nodes[0].text_content().split())
        href = a_nodes[0].get("href", "")
        if href.startswith("/link?url="):
            # 搜狗跳转链接：真实地址挂在 data-url 属性上。
            block_str = lxml_html.tostring(block, encoding="unicode")
            m = re.search(r'data-url="([^"]+)"', block_str)
            href = m.group(1) if m else ""
        host = (urlparse(href).hostname or "") if href.startswith("http") else ""
        if not title or not _ZHIHU_HOST_RE.match(host) or href in seen_urls:
            continue
        seen_urls.add(href)
        desc_nodes = block.xpath(
            './/div[@class="ft"] | .//div[contains(@class, "attribute-centent")] '
            '| .//p[contains(@class, "star-wiki")] | .//div[contains(@class, "text-layout")]'
        )
        snippet = " ".join(desc_nodes[0].text_content().split()) if desc_nodes else title
        items.append(
            UnifiedSearchItem(
                title=title,
                url=href,
                snippet=f"[知乎] {snippet[:320]}",
                source_engine="zhihu",
                raw_score=round(1.0 / (len(items) + 1), 4),
                category="social",
                metadata={"platform": "zhihu", "via": "sogou_insite"},
            )
        )
        if len(items) >= max_results:
            break
    return items


async def search_zhihu_sogou(
    query: str, max_results: int, proxy: Optional[str], timeout_sec: float
) -> List[UnifiedSearchItem]:
    async with make_async_client(proxy, timeout_sec) as client:
        resp = await client.get(
            "https://www.sogou.com/web",
            params={"query": query, "insite": "zhihu.com"},
            headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"},
        )
        if resp.status_code != 200 or not resp.text:
            return []
        return parse_sogou_zhihu(resp.text, max_results)


async def search_zhihu(
    query: str, max_results: int, proxy: Optional[str], timeout_sec: float, **kwargs
) -> List[UnifiedSearchItem]:
    """知乎检索：搜狗站内搜优先，空结果时回退 Bing site:zhihu.com。"""
    items = await search_zhihu_sogou(query, max_results, proxy, timeout_sec)
    if items:
        return items
    try:
        bing_items = await search_bing_web(
            f"{query} site:zhihu.com", max_results, proxy, timeout_sec
        )
    except Exception:  # noqa: BLE001  Bing 兜底失败不影响主流程
        return []
    fallback: List[UnifiedSearchItem] = []
    for idx, item in enumerate(bing_items, start=1):
        host = (urlparse(item.url).hostname or "").lower()
        if not _ZHIHU_HOST_RE.match(host):
            continue
        item.source_engine = "zhihu"
        item.metadata = {"platform": "zhihu", "via": "bing_site"}
        item.snippet = f"[知乎] {item.snippet or item.title}"
        item.raw_score = round(1.0 / len(fallback), 4)
        item.category = "social"
        fallback.append(item)
        if len(fallback) >= max_results:
            break
    return fallback


SEARCH_ADAPTER_REGISTRY["zhihu"] = search_zhihu
