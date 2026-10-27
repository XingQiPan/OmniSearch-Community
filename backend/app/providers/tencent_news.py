"""腾讯新闻检索渠道（免登录）。

news.qq.com 的 PC 搜索接口 `/gw/pc_search/result` 免签名可用（从站点前端
JS 包提取的端点）；返回体为 GBK 编码 JSON，结果挂在 secList[].newsList 下。
抓取时间只写 metadata，绝不冒充发布时间。
"""
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.providers.adapters import USER_AGENT, SEARCH_ADAPTER_REGISTRY, make_async_client
from app.schemas import UnifiedSearchItem

SEARCH_API = "https://i.news.qq.com/gw/pc_search/result"
# 前端 JS 包内置的版本号，接口用它做流量分流，保持与站点一致降低风控概率。
_APPVER = "15.5_qqnews_7.1.80"
# 官方自推广卡（无正文、无外链），混在结果首位需要剔除。
_PROMO_TITLES = ("腾讯新闻用户最关注的热点",)


def _clean_html(raw: str) -> str:
    if not raw:
        return ""
    # 分隔符用空串，避免 <em>AI</em>治理 这类高亮标记被拆成 "AI 治理"
    return " ".join(BeautifulSoup(raw, "html.parser").get_text("", strip=True).split())


def _decode_payload(raw: bytes) -> Optional[Dict[str, Any]]:
    """接口返回 GBK 编码 JSON，且不总是声明 charset，需手动兜底转码。"""
    for encoding in ("utf-8", "gbk"):
        try:
            data = json.loads(raw.decode(encoding))
            if isinstance(data, dict):
                return data
            return None
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return None


def _format_publish_time(entry: Dict[str, Any]) -> Optional[str]:
    for field in ("pubtime", "timestamp", "pub_time"):
        value = entry.get(field)
        try:
            ts = int(value)
        except (TypeError, ValueError):
            continue
        # 部分字段是毫秒时间戳
        if ts > 10**12:
            ts //= 1000
        if ts <= 0:
            continue
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        except (OSError, OverflowError, ValueError):
            return None
    return None


def parse_tencent_search(raw: bytes, max_results: int) -> List[UnifiedSearchItem]:
    data = _decode_payload(raw)
    if not data or data.get("ret") != 0:
        return []
    items: List[UnifiedSearchItem] = []
    seen_urls = set()
    for section in data.get("secList") or []:
        for entry in section.get("newsList") or []:
            title = _clean_html(entry.get("title") or entry.get("longtitle") or "")
            url = (entry.get("url") or entry.get("shareUrl") or entry.get("surl") or "").strip()
            if not title or not url.startswith("http"):
                continue
            if any(promo in title for promo in _PROMO_TITLES):
                continue
            host = (urlparse(url).hostname or "").lower()
            if not host.endswith("qq.com"):
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)
            abstract = _clean_html(entry.get("abstract") or entry.get("nlpAbstract") or "")
            media = _clean_html(
                entry.get("chlname") or entry.get("media_name") or entry.get("source") or ""
            )
            items.append(
                UnifiedSearchItem(
                    title=title,
                    url=url,
                    snippet=f"[腾讯新闻] {abstract[:300]}" if abstract else "[腾讯新闻] " + title,
                    published_at=_format_publish_time(entry),
                    source_engine="tencent_news",
                    raw_score=round(1.0 / (len(items) + 1), 4),
                    category="web",
                    metadata={
                        "platform": "tencent_news",
                        "media": media,
                        "article_type": _clean_html(str(entry.get("articletype") or "")),
                        "time_label": _clean_html(str(entry.get("time") or "")) or None,
                    },
                )
            )
            if len(items) >= max_results:
                return items
    return items


async def search_tencent_news(
    query: str, max_results: int, proxy: Optional[str], timeout_sec: float, **kwargs
) -> List[UnifiedSearchItem]:
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://news.qq.com/",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    async with make_async_client(proxy, timeout_sec) as client:
        # 先拿 pac_uid 会话 cookie（失败不影响，接口对匿名请求同样放行）
        try:
            await client.get("https://i.news.qq.com/web_backend/getWebPacUid", headers=headers)
        except Exception:  # noqa: BLE001
            pass
        resp = await client.get(
            SEARCH_API,
            params={
                "page": "0",
                "query": query,
                "is_pc": "1",
                "search_type": "all",
                "search_count_limit": str(min(max(max_results, 10) * 2, 30)),
                "appver": _APPVER,
            },
            headers=headers,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Tencent News HTTP {resp.status_code}: {resp.text[:160]}")
        return parse_tencent_search(resp.content, max_results)


SEARCH_ADAPTER_REGISTRY["tencent_news"] = search_tencent_news
