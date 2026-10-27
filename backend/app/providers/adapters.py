import html
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup

from app.schemas import UnifiedSearchItem
from app.gateway.freshness import DAYS, utc_now
from datetime import timedelta

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


TIME_FILTER_ENGINES = {"duckduckgo", "bocha", "tavily", "serper", "exa", "brave", "hackernews", "reddit"}


def time_filter_params(engine: str, window: Optional[str]) -> Dict[str, Any]:
    if window not in DAYS:
        return {}
    code = {"day": "d", "week": "w", "month": "m", "year": "y"}[window]
    if engine == "duckduckgo": return {"df": code}
    if engine == "bocha": return {"freshness": f"one{window.title()}"}
    if engine == "tavily": return {"time_range": window}
    if engine == "serper": return {"tbs": f"qdr:{code}"}
    if engine == "exa": return {"startPublishedDate": (utc_now() - timedelta(days=DAYS[window])).isoformat()}
    if engine == "brave": return {"freshness": f"p{code}"}
    if engine == "hackernews": return {"numericFilters": f"created_at_i>{int((utc_now() - timedelta(days=DAYS[window])).timestamp())}"}
    if engine == "reddit": return {"t": window, "sort": "new"}
    return {}


def make_async_client(proxy: Optional[str], timeout_sec: float = 8.0) -> httpx.AsyncClient:
    kwargs: Dict[str, Any] = {
        "timeout": httpx.Timeout(timeout_sec, connect=min(5.0, timeout_sec)),
        "follow_redirects": True,
        "headers": {"User-Agent": USER_AGENT},
        "verify": False,
    }
    if proxy:
        kwargs["proxy"] = proxy
    else:
        kwargs["trust_env"] = False
    return httpx.AsyncClient(**kwargs)


async def search_bing_web(
    query: str, max_results: int, proxy: Optional[str], timeout_sec: float, **kwargs
) -> List[UnifiedSearchItem]:
    items: List[UnifiedSearchItem] = []
    async with make_async_client(proxy, timeout_sec) as client:
        # Try Bing HTML & RSS fallback for high reliability
        resp = await client.get(
            "https://www.bing.com/search",
            params={"q": query, "count": min(max_results, 20), "format": "rss"},
            headers={"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
        )
        if resp.status_code == 200 and "<rss" in resp.text[:400]:
            root = ET.fromstring(resp.text)
            for idx, node in enumerate(root.findall(".//item")[:max_results], start=1):
                title = (node.findtext("title") or "").strip()
                link = (node.findtext("link") or "").strip()
                desc = (node.findtext("description") or "").strip()
                pub = (node.findtext("pubDate") or "").strip()
                if title and link:
                    items.append(
                        UnifiedSearchItem(
                            title=title,
                            url=link,
                            snippet=desc,
                            published_at=pub or None,
                            source_engine="bing_web",
                            raw_score=round(1.0 / idx, 4),
                            category="web",
                        )
                    )
        if items:
            return items

        # Fallback HTML parse
        resp_html = await client.get(
            "https://cn.bing.com/search",
            params={"q": query, "count": min(max_results, 15)},
            headers={"Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
        )
        soup = BeautifulSoup(resp_html.text, "html.parser")
        for idx, li in enumerate(soup.select("li.b_algo")[:max_results], start=1):
            a_tag = li.select_one("h2 a")
            if not a_tag:
                continue
            title = a_tag.get_text(" ", strip=True)
            href = a_tag.get("href", "")
            p_tag = li.select_one(".b_caption p") or li.select_one("p")
            snippet = p_tag.get_text(" ", strip=True) if p_tag else ""
            if title and href.startswith("http"):
                items.append(
                    UnifiedSearchItem(
                        title=title,
                        url=href,
                        snippet=snippet,
                        source_engine="bing_web",
                        raw_score=round(1.0 / idx, 4),
                        category="web",
                    )
                )
    return items


async def search_duckduckgo(
    query: str, max_results: int, proxy: Optional[str], timeout_sec: float, **kwargs
) -> List[UnifiedSearchItem]:
    items: List[UnifiedSearchItem] = []
    async with make_async_client(proxy, timeout_sec) as client:
        resp = await client.post(
            "https://lite.duckduckgo.com/lite/",
            data={"q": query, **time_filter_params("duckduckgo", kwargs.get("time_range"))},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        links = soup.select("a.result-link")
        snippets = soup.select("td.result-snippet")
        rank = 0
        for idx, a_tag in enumerate(links):
            title = a_tag.get_text(" ", strip=True)
            href = a_tag.get("href", "")
            if href.startswith("//"):
                href = "https:" + href
            if "uddg=" in href:
                parsed_qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                if "uddg" in parsed_qs:
                    href = parsed_qs["uddg"][0]
            if "duckduckgo.com/y.js" in href or "duckduckgo-help-pages" in href:
                continue
            snippet = snippets[idx].get_text(" ", strip=True) if idx < len(snippets) else ""
            if title and href.startswith("http"):
                rank += 1
                items.append(
                    UnifiedSearchItem(
                        title=title,
                        url=href,
                        snippet=snippet,
                        source_engine="duckduckgo",
                        raw_score=round(1.0 / rank, 4),
                        category="web",
                    )
                )
                if rank >= max_results:
                    break
    return items


async def search_wikipedia(
    query: str, max_results: int, proxy: Optional[str], timeout_sec: float, **kwargs
) -> List[UnifiedSearchItem]:
    items: List[UnifiedSearchItem] = []
    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", query))
    host = "https://zh.wikipedia.org" if has_cjk else "https://en.wikipedia.org"
    async with make_async_client(proxy, timeout_sec) as client:
        resp = await client.get(
            f"{host}/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": min(max_results, 10),
                "format": "json",
                "utf8": 1,
            },
            headers={"User-Agent": "OmniSearchGateway/2.0 (https://github.com/omnisearch; contact@omnisearch.local)"},
        )
        data = resp.json()
        search_list = data.get("query", {}).get("search", [])
        for idx, entry in enumerate(search_list, start=1):
            title = entry.get("title", "")
            raw_snippet = entry.get("snippet", "")
            clean_snippet = BeautifulSoup(raw_snippet, "html.parser").get_text(" ", strip=True)
            url = f"{host}/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
            items.append(
                UnifiedSearchItem(
                    title=f"{title} - Wikipedia",
                    url=url,
                    snippet=clean_snippet,
                    metadata={"updated_at": entry.get("timestamp")},
                    source_engine="wikipedia",
                    raw_score=round(1.0 / idx, 4),
                    category="web",
                )
            )
    return items


async def search_arxiv(
    query: str, max_results: int, proxy: Optional[str], timeout_sec: float, **kwargs
) -> List[UnifiedSearchItem]:
    items: List[UnifiedSearchItem] = []
    async with make_async_client(proxy, timeout_sec) as client:
        resp = await client.get(
            "https://export.arxiv.org/api/query",
            params={
                "search_query": f"all:{query}",
                "start": 0,
                "max_results": min(max_results, 12),
                "sortBy": "relevance",
                "sortOrder": "descending",
            },
        )
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(resp.text)
        for idx, entry in enumerate(root.findall("atom:entry", ns), start=1):
            title = " ".join((entry.findtext("atom:title", "", ns) or "").split())
            summary = " ".join((entry.findtext("atom:summary", "", ns) or "").split())
            link = (entry.findtext("atom:id", "", ns) or "").strip()
            published = (entry.findtext("atom:published", "", ns) or "")[:10]
            authors = [
                a.findtext("atom:name", "", ns)
                for a in entry.findall("atom:author", ns)
                if a.findtext("atom:name", "", ns)
            ]
            if title and link:
                items.append(
                    UnifiedSearchItem(
                        title=title,
                        url=link,
                        snippet=f"[Authors: {', '.join(authors[:4])}] {summary[:450]}",
                        published_at=published,
                        source_engine="arxiv",
                        raw_score=round(1.0 / idx, 4),
                        category="academic",
                        metadata={"authors": authors, "pdf_url": link.replace("/abs/", "/pdf/")},
                    )
                )
    return items


async def search_openalex(
    query: str, max_results: int, proxy: Optional[str], timeout_sec: float, **kwargs
) -> List[UnifiedSearchItem]:
    items: List[UnifiedSearchItem] = []
    async with make_async_client(proxy, timeout_sec) as client:
        resp = await client.get(
            "https://api.openalex.org/works",
            params={"search": query, "per-page": min(max_results, 12)},
        )
        data = resp.json()
        for idx, work in enumerate(data.get("results", []), start=1):
            title = work.get("title") or work.get("display_name") or ""
            url = work.get("doi") or work.get("primary_location", {}).get("landing_page_url") or work.get("id") or ""
            pub_date = work.get("publication_date") or str(work.get("publication_year", ""))
            cited_by = work.get("cited_by_count", 0)
            # Reconstruct inverted index abstract if available
            inv = work.get("abstract_inverted_index")
            abstract_text = ""
            if isinstance(inv, dict):
                pos_words = []
                for word, positions in inv.items():
                    for p in positions:
                        pos_words.append((p, word))
                pos_words.sort(key=lambda x: x[0])
                abstract_text = " ".join(w for _, w in pos_words)[:420]
            snippet = f"[Citations: {cited_by} | Date: {pub_date}] {abstract_text or title}"
            if title and url:
                items.append(
                    UnifiedSearchItem(
                        title=title,
                        url=url,
                        snippet=snippet,
                        published_at=pub_date,
                        source_engine="openalex",
                        raw_score=round(1.0 / idx, 4),
                        category="academic",
                        metadata={"cited_by_count": cited_by},
                    )
                )
    return items


async def search_github(
    query: str, max_results: int, proxy: Optional[str], timeout_sec: float, api_key: Optional[str] = None, **kwargs
) -> List[UnifiedSearchItem]:
    items: List[UnifiedSearchItem] = []
    headers = {"Accept": "application/vnd.github+json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    async with make_async_client(proxy, timeout_sec) as client:
        resp = await client.get(
            "https://api.github.com/search/repositories",
            params={"q": query, "sort": "stars", "order": "desc", "per_page": min(max_results, 12)},
            headers=headers,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"GitHub API HTTP {resp.status_code}: {resp.text[:160]}")
        data = resp.json()
        for idx, repo in enumerate(data.get("items", []), start=1):
            full_name = repo.get("full_name", "")
            desc = repo.get("description") or "No description"
            stars = repo.get("stargazers_count", 0)
            lang = repo.get("language") or "Unknown"
            url = repo.get("html_url", "")
            updated = (repo.get("updated_at") or "")[:10]
            items.append(
                UnifiedSearchItem(
                    title=f"{full_name} (⭐ {stars:,} | {lang})",
                    url=url,
                    snippet=f"{desc} [Topics: {', '.join(repo.get('topics', [])[:5])}]",
                    published_at=repo.get("created_at"),
                    source_engine="github",
                    raw_score=round(1.0 / idx, 4),
                    category="code",
                    metadata={"stars": stars, "language": lang, "forks": repo.get("forks_count", 0), "updated_at": repo.get("updated_at")},
                )
            )
    return items


async def search_hackernews(
    query: str, max_results: int, proxy: Optional[str], timeout_sec: float, **kwargs
) -> List[UnifiedSearchItem]:
    items: List[UnifiedSearchItem] = []
    async with make_async_client(proxy, timeout_sec) as client:
        resp = await client.get(
            "https://hn.algolia.com/api/v1/search",
            params={"query": query, "hitsPerPage": min(max_results, 12), "tags": "story", **time_filter_params("hackernews", kwargs.get("time_range"))},
        )
        data = resp.json()
        for idx, hit in enumerate(data.get("hits", []), start=1):
            title = hit.get("title") or hit.get("story_title") or ""
            object_id = hit.get("objectID", "")
            hn_url = f"https://news.ycombinator.com/item?id={object_id}"
            url = hit.get("url") or hn_url
            points = hit.get("points", 0)
            comments = hit.get("num_comments", 0)
            created = (hit.get("created_at") or "")[:10]
            items.append(
                UnifiedSearchItem(
                    title=title,
                    url=url,
                    snippet=f"[Hacker News: {points} points, {comments} comments | Discussion: {hn_url}]",
                    published_at=created,
                    source_engine="hackernews",
                    raw_score=round(1.0 / idx, 4),
                    category="social",
                    metadata={"points": points, "num_comments": comments, "hn_discussion": hn_url},
                )
            )
    return items


async def search_reddit(
    query: str, max_results: int, proxy: Optional[str], timeout_sec: float, **kwargs
) -> List[UnifiedSearchItem]:
    items: List[UnifiedSearchItem] = []
    async with make_async_client(proxy, timeout_sec) as client:
        resp = await client.get(
            "https://www.reddit.com/search.rss",
            params={"q": query, "limit": min(max_results, 12), "sort": "relevance", **time_filter_params("reddit", kwargs.get("time_range"))},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Reddit HTTP {resp.status_code}")
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(resp.text)
        for idx, entry in enumerate(root.findall("atom:entry", ns)[:max_results], start=1):
            title = (entry.findtext("atom:title", "", ns) or "").strip()
            link_el = entry.find("atom:link", ns)
            url = link_el.attrib.get("href", "") if link_el is not None else ""
            raw_content = entry.findtext("atom:content", "", ns) or ""
            clean_text = BeautifulSoup(raw_content, "html.parser").get_text(" ", strip=True)[:360]
            updated = (entry.findtext("atom:updated", "", ns) or "")[:10]
            cat_el = entry.find("atom:category", ns)
            sub_label = cat_el.attrib.get("label", "r/reddit") if cat_el is not None else "r/reddit"
            if title and url:
                items.append(
                    UnifiedSearchItem(
                        title=f"[{sub_label}] {title}",
                        url=url,
                        snippet=clean_text or title,
                        published_at=entry.findtext("atom:published", "", ns) or None,
                        source_engine="reddit",
                        raw_score=round(1.0 / idx, 4),
                        category="social",
                        metadata={"subreddit": sub_label, "updated_at": updated},
                    )
                )
    return items


async def search_bocha(
    query: str, max_results: int, proxy: Optional[str], timeout_sec: float, api_key: Optional[str] = None, base_url: Optional[str] = None, **kwargs
) -> List[UnifiedSearchItem]:
    if not api_key:
        raise RuntimeError("Bocha API key is missing")
    endpoint = base_url or "https://api.bochaai.com/v1/web-search"
    items: List[UnifiedSearchItem] = []
    async with make_async_client(proxy, timeout_sec) as client:
        resp = await client.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"query": query, "summary": True, "count": min(max_results, 15), **time_filter_params("bocha", kwargs.get("time_range"))},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Bocha HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        web_pages = data.get("data", {}).get("webPages", {}).get("value", []) or data.get("webPages", {}).get("value", [])
        for idx, page in enumerate(web_pages, start=1):
            items.append(
                UnifiedSearchItem(
                    title=page.get("name", ""),
                    url=page.get("url", ""),
                    snippet=page.get("summary") or page.get("snippet") or "",
                    content=page.get("summary"),
                    published_at=page.get("datePublished"),
                    source_engine="bocha",
                    raw_score=round(1.0 / idx, 4),
                    category="web",
                )
            )
    return items


async def search_tavily(
    query: str, max_results: int, proxy: Optional[str], timeout_sec: float, api_key: Optional[str] = None, base_url: Optional[str] = None, **kwargs
) -> List[UnifiedSearchItem]:
    if not api_key:
        raise RuntimeError("Tavily API key is missing")
    endpoint = base_url or "https://api.tavily.com/search"
    items: List[UnifiedSearchItem] = []
    async with make_async_client(proxy, timeout_sec) as client:
        resp = await client.post(
            endpoint,
            json={
                "api_key": api_key,
                "query": query,
                "max_results": min(max_results, 15),
                "search_depth": "basic",
                "include_raw_content": False,
                **time_filter_params("tavily", kwargs.get("time_range")),
            },
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Tavily HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        for idx, r in enumerate(data.get("results", []), start=1):
            items.append(
                UnifiedSearchItem(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=r.get("content", ""),
                    published_at=r.get("published_date"),
                    source_engine="tavily",
                    raw_score=float(r.get("score") or round(1.0 / idx, 4)),
                    category="web",
                )
            )
    return items


async def search_serper(
    query: str, max_results: int, proxy: Optional[str], timeout_sec: float, api_key: Optional[str] = None, base_url: Optional[str] = None, **kwargs
) -> List[UnifiedSearchItem]:
    if not api_key:
        raise RuntimeError("Serper API key is missing")
    endpoint = base_url or "https://google.serper.dev/search"
    items: List[UnifiedSearchItem] = []
    async with make_async_client(proxy, timeout_sec) as client:
        resp = await client.post(
            endpoint,
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": min(max_results, 15), **time_filter_params("serper", kwargs.get("time_range"))},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Serper HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        for idx, r in enumerate(data.get("organic", []), start=1):
            items.append(
                UnifiedSearchItem(
                    title=r.get("title", ""),
                    url=r.get("link", ""),
                    snippet=r.get("snippet", ""),
                    published_at=r.get("date"),
                    source_engine="serper",
                    raw_score=round(1.0 / idx, 4),
                    category="web",
                )
            )
    return items


async def search_exa(
    query: str, max_results: int, proxy: Optional[str], timeout_sec: float, api_key: Optional[str] = None, base_url: Optional[str] = None, **kwargs
) -> List[UnifiedSearchItem]:
    if not api_key:
        raise RuntimeError("Exa API key is missing")
    endpoint = base_url or "https://api.exa.ai/search"
    items: List[UnifiedSearchItem] = []
    async with make_async_client(proxy, timeout_sec) as client:
        resp = await client.post(
            endpoint,
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            json={"query": query, "numResults": min(max_results, 12), "contents": {"text": {"maxCharacters": 600}}, **time_filter_params("exa", kwargs.get("time_range"))},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Exa HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        for idx, r in enumerate(data.get("results", []), start=1):
            items.append(
                UnifiedSearchItem(
                    title=r.get("title") or r.get("url", ""),
                    url=r.get("url", ""),
                    snippet=(r.get("text") or r.get("summary") or "")[:450],
                    published_at=r.get("publishedDate"),
                    source_engine="exa",
                    raw_score=float(r.get("score") or round(1.0 / idx, 4)),
                    category="web",
                )
            )
    return items


async def search_brave(
    query: str, max_results: int, proxy: Optional[str], timeout_sec: float, api_key: Optional[str] = None, base_url: Optional[str] = None, **kwargs
) -> List[UnifiedSearchItem]:
    if not api_key:
        raise RuntimeError("Brave API key is missing")
    endpoint = base_url or "https://api.search.brave.com/res/v1/web/search"
    items: List[UnifiedSearchItem] = []
    async with make_async_client(proxy, timeout_sec) as client:
        resp = await client.get(
            endpoint,
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
            params={"q": query, "count": min(max_results, 15), **time_filter_params("brave", kwargs.get("time_range"))},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Brave HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        for idx, r in enumerate(data.get("web", {}).get("results", []), start=1):
            items.append(
                UnifiedSearchItem(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=r.get("description", ""),
                    published_at=r.get("age"),
                    source_engine="brave",
                    raw_score=round(1.0 / idx, 4),
                    category="web",
                )
            )
    return items


async def scrape_url_markdown(
    target_url: str, proxy: Optional[str], api_key: Optional[str] = None, timeout_sec: float = 8.0
) -> str:
    result = await read_url_evidence(target_url, proxy, api_key, timeout_sec)
    return result['text']


async def read_url_evidence(
    target_url: str, proxy: Optional[str], api_key: Optional[str] = None, timeout_sec: float = 8.0,
    min_chars: int = 200, max_chars: int = 16000,
) -> Dict[str, Any]:
    """Return bounded正文 and provenance; fetch time is never used as publication time.

    读取顺序：静态抓取 + 本地正文抽取（免外部依赖、国内站点最快）→
    Jina Reader 兜底（可渲染部分 SPA）→ meta description（仅摘要并标注 provenance）。
    """
    max_chars = max(500, int(max_chars))
    result = {"text": "", "read_status": "failed", "retrieved_at": utc_now().isoformat(),
              "content_truncated": False, "published_at": None, "updated_at": None,
              "final_url": target_url, "title": None}

    def finish(text, source):
        # Reject obvious challenge/error documents rather than counting them as read.
        if len(text.strip()) < min_chars or re.search(r"captcha|just a moment|access denied|verify you are human|验证码|安全验证", text[:600], re.I):
            return False
        result.update(text=text[:max_chars], read_status="fulltext", reader_source=source,
                      content_truncated=len(text) > max_chars)
        return True

    fetch_headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    raw_html = None
    description = ""
    description_ok = False
    try:
        async with make_async_client(proxy, timeout_sec) as client:
            resp = await client.get(target_url, headers=fetch_headers)
            if resp.status_code == 200:
                result['final_url'] = str(resp.url)
                raw_html = resp.content
    except (httpx.HTTPError, ValueError):
        if proxy:
            # 代理不可达是常态（本地无梯子），静态抓取退直连重试一次。
            try:
                async with make_async_client(None, timeout_sec) as client:
                    resp = await client.get(target_url, headers=fetch_headers)
                    if resp.status_code == 200:
                        result['final_url'] = str(resp.url)
                        raw_html = resp.content
            except (httpx.HTTPError, ValueError):
                raw_html = None

    if raw_html and (b"<" in raw_html[:2048] or b"&" in raw_html[:2048]):
        try:
            # 传 bytes 让 BeautifulSoup 自行探测编码（GBK 站点如腾讯网依赖这一点）。
            soup = BeautifulSoup(raw_html, "html.parser")
            if soup.title:
                title_text = " ".join(soup.title.get_text(" ", strip=True).split())
                result['title'] = title_text[:200] or None
            for name in ("description", "og:description", "twitter:description"):
                tag = soup.find("meta", attrs={"name": name}) or soup.find("meta", attrs={"property": name})
                if tag and tag.get("content"):
                    description = " ".join(tag["content"].split())
                    if description:
                        break
            for key, names in [('published_at', ['article:published_time', 'datePublished', 'pubdate', 'publishdate']),
                               ('updated_at', ['article:modified_time', 'dateModified'])]:
                for name in names:
                    tag = soup.find('meta', attrs={'property': name}) or soup.find('meta', attrs={'name': name})
                    if tag and tag.get('content'):
                        result[key] = tag['content']
                        break
            text = extract_main_text(soup, result['final_url'])
            if finish(text, 'direct_html'):
                return result
        except Exception:  # noqa: BLE001  解析失败时继续走 Reader 兜底
            pass

        # JS 渲染的 SPA 页面通常只把 <title>/meta description 暴露给静态抓取器。
        # 这里不再立即返回摘要，先给 Reader 一次机会；Reader 也失败时才标记 metadata_only。
        if (description and len(description) >= 30
                and not re.search(r"captcha|just a moment|access denied|verify you are human|验证码|安全验证",
                                  description[:600], re.I)):
            description_ok = True
        else:
            description_ok = False

    try:
        headers = {"Accept": "text/plain"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        async with make_async_client(proxy, timeout_sec) as client:
            resp = await client.get(f"https://r.jina.ai/{target_url}", headers=headers)
            if resp.status_code == 200:
                text = resp.text
                match = re.search(r"^Published Time:\s*(.+)$", text, re.M)
                if match:
                    result['published_at'] = match[1].strip()
                title_match = re.search(r"^Title:\s*(.+)$", text, re.M)
                if title_match:
                    result['title'] = title_match[1].strip()[:200]
                # Strip Reader transport headers so they do not masquerade as content.
                text = text.split('Markdown Content:', 1)[-1].strip()
                if finish(text, 'jina_reader'):
                    return result
    except (httpx.HTTPError, ValueError):
        pass

    if raw_html and description_ok:
        result.update(text=description[:max_chars], read_status="metadata_only",
                      reader_source="meta_description", content_truncated=False)
    return result


# ---------------------------------------------------------------------------
# 网页正文抽取（readability 风格）
#
# 旧实现直接把 article/main/整页 get_text 拼成一整行，导航、推荐、版权、侧栏
# 全部混进正文，且段落结构被空格吞掉。这里改成：
#   1. 先移除 script/style/导航/页脚以及按 class 命名识别的样板节点；
#   2. 按「段落文本量 × (1 - 链接密度)」为候选容器打分，选正文容器，
#      并对常见中文站点挂显式容器选择器；
#   3. 按文档顺序逐块取文本，保留段落换行，跳过高链接密度的小块。
# ---------------------------------------------------------------------------

_BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "pre", "figcaption", "dd", "dt"}
_MAYBE_BLOCK_TAGS = {"div", "section", "td", "details", "summary", "span", "font"}
# 命中这些 class/id 词根的节点几乎都是样板：评论区、分享条、侧栏、推荐位、广告位。
_JUNK_ATTR_RE = re.compile(
    r"(^|[-_ ])(?:sidebar|comment|share|social|related|recommend|banner|breadcrumb|crumb"
    r"|menu|nav|footer|advert|ads?|promo|login|sign ?in|sign ?up|subscribe|qrcode"
    r"|copyright|toolbar|pager|pagination|modal|dialog|mask|popup|toast|carousel"
    r"|swiper|download-?app|open-?app|guide|widget|ranking|hot-?list|live|gift|danmu)([-_ ]|$)",
    re.IGNORECASE,
)

# 高频中文站点的正文容器（域名后缀 -> 候选选择器，按优先级排列）。
_SITE_CONTAINER_HINTS: List[Tuple[str, List[str]]] = [
    ("mp.weixin.qq.com", ["#js_content", ".rich_media_content"]),
    ("zhihu.com", [".Post-RichTextContainer", ".RichContent-inner", ".QuestionAnswer-content", ".RichText"]),
    ("qq.com", [".content-article", "#ArticleContent", ".article-content", ".Cnt-Main-Article-QQ"]),
    ("toutiao.com", ["article", ".article-content"]),
    ("36kr.com", [".articleDetailContent", "article"]),
    ("sina.com.cn", ["#artibody", "#article", ".article"]),
    ("sohu.com", ["#mp-editor", "article", ".article"]),
    ("163.com", [".post_body", "#endText", ".article-content"]),
    ("csdn.net", ["#content_views", "article"]),
    ("juejin.cn", ["article"]),
    ("cnblogs.com", ["#cnblogs_post_body"]),
    ("jianshu.com", ["article"]),
    ("people.com.cn", [".show_text", ".rm_txt_con", "#rwb_zw"]),
    ("xinhuanet.com", ["#detail", "article", ".article"]),
    ("chinanews.com.cn", [".left_zw"]),
    ("thepaper.cn", ["#content", ".index_cententWrap"]),
]


def _link_density(el) -> float:
    total = len(el.get_text(" ", strip=True))
    if total <= 0:
        return 0.0
    linked = sum(len(a.get_text(" ", strip=True)) for a in el.find_all("a"))
    return min(1.0, linked / total)


def _score_container(el) -> float:
    paragraphs = el.find_all("p")
    text_len = sum(len(" ".join(p.get_text(" ", strip=True).split())) for p in paragraphs)
    if not paragraphs:
        text_len = len(el.get_text(" ", strip=True))
    strong_paras = sum(1 for p in paragraphs if len(p.get_text(strip=True)) > 80)
    return text_len * (1.0 - _link_density(el)) + 40.0 * strong_paras


def _pick_main_container(soup, final_url: str):
    host = ""
    try:
        host = (urllib.parse.urlparse(final_url).hostname or "").lower()
    except ValueError:
        pass
    for suffix, selectors in _SITE_CONTAINER_HINTS:
        if host == suffix or host.endswith("." + suffix):
            for sel in selectors:
                nodes = soup.select(sel)
                if nodes:
                    return nodes[0]

    candidates = []
    for sel in ("article", "main", '[role="main"]', "#content", ".article-content", ".article__content", "#js_content"):
        candidates.extend(soup.select(sel))
    candidates.append(soup.body or soup)

    best, best_score = None, -1.0
    seen = set()
    for el in candidates:
        key = id(el)
        if key in seen:
            continue
        seen.add(key)
        score = _score_container(el)
        if score > best_score:
            best, best_score = el, score
    return best


def _decompose_boilerplate(soup) -> None:
    for tag in soup(["script", "style", "noscript", "iframe", "svg", "form", "button", "select", "textarea", "link", "meta"]):
        tag.decompose()
    # article/main 里的 header/nav/footer/aside 可能承载标题或正文结构，予以保留。
    protected = set()
    for main_el in soup(["article", "main"]):
        for node in main_el.descendants:
            protected.add(id(node))
    for tag in soup(["header", "nav", "footer", "aside"]):
        if id(tag) not in protected:
            tag.decompose()
    for tag in list(soup.find_all(True)):
        if tag.attrs is None:
            continue  # 父节点已被 decompose，自身随之移除
        class_attr = tag.get("class") or []
        if not isinstance(class_attr, list):
            class_attr = [str(class_attr)]
        attrs = " ".join(class_attr) + " " + str(tag.get("id") or "")
        if _JUNK_ATTR_RE.search(attrs):
            tag.decompose()


def _walk_blocks(el, out: List[str]) -> None:
    """按文档顺序取块级文本；块内不再下钻，避免 li>p 之类嵌套重复。"""
    for child in el.children:
        if isinstance(child, str):  # NavigableString
            text = " ".join(child.split())
            if text:
                out.append(text)
            continue
        name = (child.name or "").lower()
        if name in _BLOCK_TAGS:
            text = " ".join(child.get_text(" ", strip=True).split())
            if text and not (_link_density(child) > 0.55 and len(text) < 160):
                out.append(text)
        elif name in _MAYBE_BLOCK_TAGS:
            if child.find(list(_BLOCK_TAGS | {"div", "section", "table", "ul", "ol"})):
                _walk_blocks(child, out)
            else:
                text = " ".join(child.get_text(" ", strip=True).split())
                if text and not (_link_density(child) > 0.55 and len(text) < 160):
                    out.append(text)
        else:
            _walk_blocks(child, out)


def extract_main_text(soup, final_url: str = "") -> str:
    """抽取正文文本：保留段落换行，剔除导航/推荐/评论等样板。"""
    _decompose_boilerplate(soup)
    container = _pick_main_container(soup, final_url)
    blocks: List[str] = []
    _walk_blocks(container, blocks)

    # 同一行被多个容器重复收录时去掉相邻重复；行数过多时收紧到有内容的行。
    cleaned: List[str] = []
    for line in blocks:
        if cleaned and cleaned[-1] == line:
            continue
        cleaned.append(line)
    text = "\n".join(cleaned).strip()
    if not text:
        # 块级结构缺失（如纯文本流页面）时退回整页文本，保证不比旧实现差；
        # 注意只兜底完全为空的场景——此时多半整页都被风控页占据，交给 finish() 判定。
        parts = []
        for node in soup.strings:
            parent_name = (node.parent.name or "").lower() if node.parent else ""
            if parent_name == "a":
                continue  # 链接锚文本不算正文
            line = " ".join(node.split())
            if line and (not parts or parts[-1] != line):
                parts.append(line)
        text = "\n".join(parts).strip()
    return text


def _parse_bluesky_posts(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """把 AT Protocol searchPosts 返回解析成统一字段，便于离线测试。"""
    parsed: List[Dict[str, Any]] = []
    for post in (payload or {}).get("posts", []) or []:
        record = post.get("record") or {}
        text = " ".join((record.get("text") or "").split())
        uri = post.get("uri") or ""
        rkey = uri.rsplit("/", 1)[-1] if uri else ""
        handle = (post.get("author") or {}).get("handle") or ""
        if not text or not rkey or not handle:
            continue
        parsed.append(
            {
                "text": text,
                "url": f"https://bsky.app/profile/{handle}/post/{rkey}",
                "handle": handle,
                "display_name": (post.get("author") or {}).get("displayName") or handle,
                "published_at": record.get("createdAt") or post.get("indexedAt"),
                "indexed_at": post.get("indexedAt"),
                "likes": post.get("likeCount") or 0,
                "reposts": post.get("repostCount") or 0,
                "replies": post.get("replyCount") or 0,
                "langs": record.get("langs") or [],
            }
        )
    return parsed


async def search_bluesky(
    query: str, max_results: int, proxy: Optional[str], timeout_sec: float, **kwargs
) -> List[UnifiedSearchItem]:
    """Bluesky 公共 AT Protocol 检索：免 Key、按最新排序，适合抓突发与外网实时舆论。"""
    items: List[UnifiedSearchItem] = []
    async with make_async_client(proxy, timeout_sec) as client:
        resp = await client.get(
            "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts",
            params={"q": query, "limit": min(max_results, 25), "sort": "latest"},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Bluesky HTTP {resp.status_code}: {resp.text[:160]}")
        for idx, post in enumerate(_parse_bluesky_posts(resp.json())[:max_results], start=1):
            items.append(
                UnifiedSearchItem(
                    title=f"@{post['handle']}: {post['text'][:90]}",
                    url=post["url"],
                    snippet=post["text"][:300],
                    published_at=(post["published_at"] or "")[:10] or None,
                    source_engine="bluesky",
                    raw_score=round(1.0 / idx, 4),
                    category="social",
                    metadata={
                        "platform": "bluesky",
                        "author": post["display_name"],
                        "handle": post["handle"],
                        "likes": post["likes"],
                        "reposts": post["reposts"],
                        "replies": post["replies"],
                        "indexed_at": post["indexed_at"],
                        "langs": post["langs"],
                    },
                )
            )
    return items


async def search_x_api(
    query: str, max_results: int, proxy: Optional[str], timeout_sec: float,
    api_key: Optional[str] = None, base_url: Optional[str] = None, **kwargs
) -> List[UnifiedSearchItem]:
    """X 官方 API v2 recent search（需 Bearer Token；免费层无读取额度，Basic 起 $200/月）。"""
    if not api_key:
        raise RuntimeError("X API Bearer Token 未配置")
    endpoint = (base_url or "https://api.x.com/2").rstrip("/") + "/tweets/search/recent"
    async with make_async_client(proxy, timeout_sec) as client:
        resp = await client.get(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}"},
            params={
                "query": f"{query} -is:retweet",
                "max_results": max(10, min(max_results, 25)),
                "tweet.fields": "created_at,public_metrics,lang,author_id",
                "expansions": "author_id",
                "user.fields": "username,name,verified",
            },
        )
        if resp.status_code != 200:
            raise RuntimeError(f"X API HTTP {resp.status_code}: {resp.text[:200]}")
        payload = resp.json()
    users = {u.get("id"): u for u in (payload.get("includes") or {}).get("users", []) or []}
    items: List[UnifiedSearchItem] = []
    for idx, tweet in enumerate((payload.get("data") or [])[:max_results], start=1):
        tid = tweet.get("id") or ""
        user = users.get(tweet.get("author_id")) or {}
        username = user.get("username") or "i"
        metrics = tweet.get("public_metrics") or {}
        text = " ".join((tweet.get("text") or "").split())
        if not tid or not text:
            continue
        items.append(
            UnifiedSearchItem(
                title=f"@{username}: {text[:90]}",
                url=f"https://x.com/{username}/status/{tid}",
                snippet=text[:300],
                published_at=(tweet.get("created_at") or "")[:10] or None,
                source_engine="x_search",
                raw_score=round(1.0 / idx, 4),
                category="social",
                metadata={
                    "platform": "x",
                    "author": user.get("name"),
                    "handle": username,
                    "verified": user.get("verified"),
                    "likes": metrics.get("like_count", 0),
                    "reposts": metrics.get("retweet_count", 0),
                    "replies": metrics.get("reply_count", 0),
                    "lang": tweet.get("lang"),
                },
            )
        )
    return items


async def search_bilibili(
    query: str, max_results: int, proxy: Optional[str], timeout_sec: float, **kwargs
) -> List[UnifiedSearchItem]:
    """B站官方视频搜索（免登录，带指纹 cookie）。"""
    from app.providers.bilibili import search_videos

    data = await search_videos(query, limit=min(max_results, 12), proxy=proxy, timeout_sec=timeout_sec)
    items: List[UnifiedSearchItem] = []
    for idx, video in enumerate(data.get("items", [])[:max_results], start=1):
        published = None
        if video.get("pubdate"):
            try:
                published = time.strftime("%Y-%m-%d", time.localtime(int(video["pubdate"])))
            except (ValueError, OSError, TypeError):
                published = None
        items.append(
            UnifiedSearchItem(
                title=video.get("title") or video.get("bvid") or "B站视频",
                url=video.get("url") or "",
                snippet=(
                    f"[B站] UP主 {video.get('author') or '未知'} · 播放 {video.get('play') or 0}"
                    f" · 弹幕 {video.get('danmaku') or 0} · 时长 {video.get('duration') or '-'}"
                ),
                published_at=published,
                source_engine="bilibili",
                raw_score=round(1.0 / idx, 4),
                category="entertainment",
                metadata={
                    "platform": "bilibili",
                    "bvid": video.get("bvid"),
                    "aid": video.get("aid"),
                    "author": video.get("author"),
                    "play": video.get("play"),
                    "danmaku": video.get("danmaku"),
                    "duration": video.get("duration"),
                    "cover": video.get("cover"),
                    "description": video.get("description"),
                },
            )
        )
    return items


SEARCH_ADAPTER_REGISTRY = {
    "bing_web": search_bing_web,
    "duckduckgo": search_duckduckgo,
    "wikipedia": search_wikipedia,
    "arxiv": search_arxiv,
    "openalex": search_openalex,
    "github": search_github,
    "hackernews": search_hackernews,
    "reddit": search_reddit,
    "bluesky": search_bluesky,
    "x_search": search_x_api,
    "bilibili": search_bilibili,
    "bocha": search_bocha,
    "tavily": search_tavily,
    "serper": search_serper,
    "exa": search_exa,
    "brave": search_brave,
}
