"""
全网热榜聚合模块：抓取百度 / 微博 / 知乎 / 抖音 / B站 / GitHub /
Hacker News / 掘金 / V2EX / Reddit / 维基百科等公开榜单。

- 国内源默认直连（不走代理），海外源优先复用网关全局代理
- 带内存缓存（TTL 5 分钟，失败结果仅缓存 30 秒），避免被源站限流
"""
import datetime as dt
import json
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any, Callable, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup

from app.providers.adapters import SEARCH_ADAPTER_REGISTRY, make_async_client
from app.schemas import TrendingBoard, TrendingItem, UnifiedSearchItem
import asyncio

CACHE_TTL_SECONDS = 300
ERROR_CACHE_TTL_SECONDS = 30
_board_cache: Dict[str, Tuple[float, TrendingBoard]] = {}


def _fmt_hot(n: Any) -> str:
    """1234567 -> '123.5万'；非法值返回空串。"""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return ""
    if n >= 100_000_000:
        return f"{n / 100_000_000:.1f}亿"
    if n >= 10_000:
        return f"{n / 10_000:.1f}万"
    return str(n)


# ==================== 各榜单适配器 ====================

def _extract_baidu_entries(node: Any) -> List[Dict[str, Any]]:
    """递归提取百度接口中所有含 word 字段的条目（接口存在 cards->content->content 嵌套）。"""
    found: List[Dict[str, Any]] = []
    if isinstance(node, dict):
        if node.get("word"):
            found.append(node)
            return found
        for v in node.values():
            found.extend(_extract_baidu_entries(v))
    elif isinstance(node, list):
        for v in node:
            found.extend(_extract_baidu_entries(v))
    return found


async def fetch_baidu_hot(max_items: int, proxy: Optional[str], timeout_sec: float) -> List[TrendingItem]:
    items: List[TrendingItem] = []
    async with make_async_client(proxy, timeout_sec) as client:
        resp = await client.get(
            "https://top.baidu.com/api/board?platform=wise&tab=realtime",
            headers={"Referer": "https://top.baidu.com/board", "Accept": "application/json"},
        )
        entries = _extract_baidu_entries(resp.json().get("data", {}))
        for idx, e in enumerate(entries[:max_items], start=1):
            word = (e.get("word") or "").strip()
            if not word:
                continue
            items.append(
                TrendingItem(
                    rank=idx,
                    title=word,
                    url=e.get("url") or f"https://www.baidu.com/s?wd={urllib.parse.quote(word)}",
                    subtitle=(e.get("desc") or "")[:90] or None,
                    tag="置顶" if e.get("isTop") else None,
                )
            )
    return items


async def fetch_weibo_hot(max_items: int, proxy: Optional[str], timeout_sec: float) -> List[TrendingItem]:
    items: List[TrendingItem] = []
    async with make_async_client(proxy, timeout_sec) as client:
        resp = await client.get(
            "https://weibo.com/ajax/side/hotSearch",
            headers={"Referer": "https://weibo.com", "Accept": "application/json"},
        )
        realtime = resp.json().get("data", {}).get("realtime", []) or []
        rank = 0
        for e in realtime:
            word = (e.get("word") or "").strip()
            if not word or e.get("is_ad"):
                continue
            rank += 1
            hot = e.get("num") or 0
            items.append(
                TrendingItem(
                    rank=rank,
                    title=word,
                    url=f"https://s.weibo.com/weibo?q=%23{urllib.parse.quote(word)}%23",
                    hot_value=f"{_fmt_hot(hot)} 热度" if hot else None,
                    hot_score=hot or None,
                    subtitle=e.get("note") or None,
                    tag=e.get("label_name") or None,
                )
            )
            if rank >= max_items:
                break
    return items


async def fetch_zhihu_hot(max_items: int, proxy: Optional[str], timeout_sec: float) -> List[TrendingItem]:
    """知乎 App 端热榜接口：免登录（web 端 hot-lists/total 已要求身份验证）。"""
    items: List[TrendingItem] = []
    async with make_async_client(proxy, timeout_sec) as client:
        resp = await client.get(
            "https://api.zhihu.com/topstory/hot-list",
            params={"limit": min(max_items, 50)},
            # App UA 是该接口免登录放行的关键，浏览器 UA 会被风控拒绝
            headers={"User-Agent": "osee2unifiedRelease/22.5.0", "Accept": "application/json"},
        )
        data = resp.json().get("data", []) or []
        for e in data:
            target = e.get("target", {})
            title = (target.get("title") or "").strip()
            if not title:
                continue
            api_url = (target.get("url") or "").rstrip("/")
            qid = api_url.rsplit("/", 1)[-1] if api_url else ""
            url = f"https://www.zhihu.com/question/{qid}" if qid.isdigit() else api_url
            items.append(
                TrendingItem(
                    rank=len(items) + 1,
                    title=title,
                    url=url,
                    hot_value=e.get("detail_text") or None,  # 如 "5,687 万热度"
                    subtitle=(target.get("excerpt") or target.get("excerpt_area") or "")[:90] or None,
                    cover=target.get("thumbnail_url") or target.get("thumbnail") or None,
                )
            )
            if len(items) >= max_items:
                break
    return items


async def fetch_tencent_hot(max_items: int, proxy: Optional[str], timeout_sec: float) -> List[TrendingItem]:
    """腾讯新闻热点榜：PC 站前端接口，免登录；返回体 GBK 编码。"""
    items: List[TrendingItem] = []
    async with make_async_client(proxy, timeout_sec) as client:
        resp = await client.get(
            "https://i.news.qq.com/gw/event/pc_hot_ranking_list",
            params={
                "ids_hash": "",
                "offset": 0,
                "page_size": min(max(max_items, 10) + 2, 60),  # 头部混有官方推广卡，多取一些用于剔除
                "appver": "15.5_qqnews_7.1.60",
                "rank_id": "hot",
            },
            headers={"Referer": "https://news.qq.com/", "Accept": "application/json"},
        )
        try:
            text = resp.content.decode("utf-8")
        except UnicodeDecodeError:
            text = resp.content.decode("gbk", "replace")
        idlist = json.loads(text).get("idlist") or []
        newslist = idlist[0].get("newslist", []) if idlist else []
        for e in newslist:
            title = re.sub(r"<[^>]+>", "", e.get("title") or "").strip()
            url = (e.get("url") or e.get("shareUrl") or "").strip()
            if not title or not url.startswith("http"):
                continue
            if "腾讯新闻用户最关注" in title:  # 官方自推广卡，非真实榜单条目
                continue
            hot = None
            for field in ("hotScore", "hot_score", "readCount"):
                try:
                    hot = int(e.get(field) or 0) or None
                except (TypeError, ValueError):
                    continue
                if hot:
                    break
            tag_raw = e.get("tag")
            if isinstance(tag_raw, list):
                tag_raw = " ".join(str(t) for t in tag_raw)
            tag = re.sub(r"<[^>]+>", "", str(tag_raw or "")).strip() or None
            items.append(
                TrendingItem(
                    rank=len(items) + 1,
                    title=title,
                    url=url,
                    hot_value=f"{_fmt_hot(hot)} 热度" if hot else None,
                    hot_score=hot,
                    subtitle=re.sub(r"<[^>]+>", "", e.get("abstract") or "").strip()[:90] or None,
                    tag=tag,
                )
            )
            if len(items) >= max_items:
                break
    return items


async def fetch_douyin_hot(max_items: int, proxy: Optional[str], timeout_sec: float) -> List[TrendingItem]:
    items: List[TrendingItem] = []
    async with make_async_client(proxy, timeout_sec) as client:
        resp = await client.get(
            "https://www.douyin.com/aweme/v1/web/hot/search/list/",
            headers={"Referer": "https://www.douyin.com/hot", "Accept": "application/json"},
        )
        word_list = resp.json().get("data", {}).get("word_list", []) or []
        for idx, e in enumerate(word_list[:max_items], start=1):
            word = (e.get("word") or "").strip()
            if not word:
                continue
            items.append(
                TrendingItem(
                    rank=idx,
                    title=word,
                    url=f"https://www.douyin.com/hot/{e.get('position', idx)}",
                    hot_value=f"{_fmt_hot(e.get('hot_value'))} 热度",
                    hot_score=e.get("hot_value"),
                    subtitle=e.get("sentence") or None,
                    tag=(str(e.get("label")) if e.get("label") not in (None, "") else None),
                    # 抖音热搜为关键词榜，可通过关键词桥接出视频下载直链
                    video_platform="douyin",
                    video_id=None,
                )
            )
    return items


async def fetch_bilibili_rank(max_items: int, proxy: Optional[str], timeout_sec: float) -> List[TrendingItem]:
    items: List[TrendingItem] = []
    async with make_async_client(proxy, timeout_sec) as client:
        headers = {"Referer": "https://www.bilibili.com/", "Accept": "application/json"}
        resp = await client.get(
            "https://api.bilibili.com/x/web-interface/ranking/v2", params={"rid": 0, "type": "all"}, headers=headers
        )
        lst = (resp.json().get("data") or {}).get("list") or []
        if not lst:  # 排行榜被风控时退回热门接口
            resp = await client.get("https://api.bilibili.com/x/web-interface/popular", headers=headers)
            lst = (resp.json().get("data") or {}).get("list") or []
        for idx, v in enumerate(lst[:max_items], start=1):
            stat = v.get("stat", {}) or {}
            bvid = v.get("bvid", "")
            items.append(
                TrendingItem(
                    rank=idx,
                    title=(v.get("title") or "").strip(),
                    url=v.get("short_link_v2") or (f"https://www.bilibili.com/video/{bvid}" if bvid else ""),
                    hot_value=f"{_fmt_hot(stat.get('view'))} 播放",
                    hot_score=stat.get("view"),
                    subtitle=f"UP主: {v.get('owner', {}).get('name', '')} · {stat.get('danmaku', 0)} 弹幕",
                    cover=(v.get("pic") or "").replace("http://", "https://") or None,
                    video_platform="bilibili",
                    video_id=bvid or None,
                )
            )
    return items


async def fetch_github_trending(max_items: int, proxy: Optional[str], timeout_sec: float) -> List[TrendingItem]:
    items: List[TrendingItem] = []
    async with make_async_client(proxy, timeout_sec) as client:
        resp = await client.get("https://github.com/trending")
        soup = BeautifulSoup(resp.text, "html.parser")
        for row in soup.select("article.Box-row")[:max_items]:
            a = row.select_one("h2 a")
            if not a:
                continue
            repo_path = (a.get("href") or "").strip("/")
            if not repo_path:
                continue
            desc_el = row.select_one("p")
            lang_el = row.select_one("span[itemprop='programmingLanguage']")
            today_el = row.select_one("span.d-inline-block.float-sm-right")
            items.append(
                TrendingItem(
                    rank=len(items) + 1,
                    title=repo_path,
                    url=f"https://github.com/{repo_path}",
                    hot_value=today_el.get_text(" ", strip=True) if today_el else None,
                    subtitle=desc_el.get_text(" ", strip=True) if desc_el else None,
                    tag=lang_el.get_text(strip=True) if lang_el else None,
                )
            )
    return items


async def fetch_hackernews_top(max_items: int, proxy: Optional[str], timeout_sec: float) -> List[TrendingItem]:
    items: List[TrendingItem] = []
    async with make_async_client(proxy, timeout_sec) as client:
        resp = await client.get(
            "https://hn.algolia.com/api/v1/search",
            params={"tags": "front_page", "hitsPerPage": min(max_items, 30)},
        )
        for idx, h in enumerate(resp.json().get("hits", [])[:max_items], start=1):
            title = (h.get("title") or "").strip()
            if not title:
                continue
            oid = h.get("objectID", "")
            items.append(
                TrendingItem(
                    rank=idx,
                    title=title,
                    url=h.get("url") or f"https://news.ycombinator.com/item?id={oid}",
                    hot_value=f"{h.get('points', 0)} 赞 · {h.get('num_comments', 0)} 评",
                    hot_score=h.get("points"),
                    tag="HN",
                )
            )
    return items


async def fetch_juejin_hot(max_items: int, proxy: Optional[str], timeout_sec: float) -> List[TrendingItem]:
    items: List[TrendingItem] = []
    async with make_async_client(proxy, timeout_sec) as client:
        resp = await client.get(
            "https://api.juejin.cn/content_api/v1/content/article_rank",
            params={"category_id": 1, "type": "hot"},
            headers={"Referer": "https://juejin.cn/", "Accept": "application/json"},
        )
        data = resp.json().get("data", []) or []
        for idx, e in enumerate(data[:max_items], start=1):
            c = e.get("content", {}) or {}
            counter = e.get("content_counter", {}) or {}
            title = (c.get("title") or "").strip()
            content_id = c.get("content_id") or c.get("article_id") or ""
            if not title or not content_id:
                continue
            views = counter.get("view")
            items.append(
                TrendingItem(
                    rank=idx,
                    title=title,
                    url=f"https://juejin.cn/post/{content_id}",
                    hot_value=f"{_fmt_hot(views)} 阅读" if views else None,
                    hot_score=views,
                    subtitle=(c.get("brief") or "")[:80] or None,
                )
            )
    return items


async def fetch_v2ex_hot(max_items: int, proxy: Optional[str], timeout_sec: float) -> List[TrendingItem]:
    items: List[TrendingItem] = []
    async with make_async_client(proxy, timeout_sec) as client:
        resp = await client.get("https://www.v2ex.com/api/topics/hot.json")
        for idx, t in enumerate(resp.json()[:max_items], start=1):
            title = (t.get("title") or "").strip()
            if not title:
                continue
            items.append(
                TrendingItem(
                    rank=idx,
                    title=title,
                    url=t.get("url") or "https://www.v2ex.com/?tab=hot",
                    hot_value=f"{t.get('replies', 0)} 回复",
                    hot_score=t.get("replies"),
                    subtitle=f"{t.get('node', {}).get('title', '')} · @{t.get('member', {}).get('username', '')}",
                )
            )
    return items


async def fetch_reddit_hot(max_items: int, proxy: Optional[str], timeout_sec: float) -> List[TrendingItem]:
    items: List[TrendingItem] = []
    async with make_async_client(proxy, timeout_sec) as client:
        # Reddit 对 UA 敏感，要求可唯一识别的 UA；RSS 偶发限流返回空 body，故加 JSON 回退
        client.headers["User-Agent"] = "OmniSearchGateway/2.0 (trending aggregator; contact@omnisearch.local)"
        try:
            resp = await client.get(
                "https://www.reddit.com/r/popular/hot.rss",
                params={"limit": min(max_items * 2, 50)},
            )
            if resp.status_code == 200 and resp.text.strip().startswith("<"):
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                root = ET.fromstring(resp.text)
                for entry in root.findall("atom:entry", ns):
                    title = (entry.findtext("atom:title", "", ns) or "").strip()
                    link_el = entry.find("atom:link", ns)
                    url = link_el.attrib.get("href", "") if link_el is not None else ""
                    if not title or not url:
                        continue
                    cat_el = entry.find("atom:category", ns)
                    sub = cat_el.attrib.get("label", "") if cat_el is not None else ""
                    items.append(
                        TrendingItem(
                            rank=len(items) + 1,
                            title=title,
                            url=url,
                            tag=sub or None,  # RSS label 本身已是 r/xxx 格式
                        )
                    )
                    if len(items) >= max_items:
                        break
        except ET.ParseError:
            items = []

        if items:
            return items

        # JSON 端点回退
        resp = await client.get(
            "https://www.reddit.com/r/popular/hot.json", params={"limit": min(max_items, 30)}
        )
        children = ((resp.json().get("data") or {}).get("children")) or []
        for c in children:
            d = c.get("data", {}) or {}
            title = (d.get("title") or "").strip()
            permalink = d.get("permalink") or ""
            if not title:
                continue
            sub = d.get("subreddit") or ""
            ups = d.get("ups") or 0
            comments = d.get("num_comments") or 0
            items.append(
                TrendingItem(
                    rank=len(items) + 1,
                    title=title,
                    url=f"https://www.reddit.com{permalink}" if permalink else "https://www.reddit.com/r/popular/",
                    hot_value=f"{_fmt_hot(ups)} 赞 · {comments} 评",
                    hot_score=ups,
                    tag=f"r/{sub}" if sub else None,
                )
            )
            if len(items) >= max_items:
                break
    return items


async def fetch_wikipedia_mostread(max_items: int, proxy: Optional[str], timeout_sec: float) -> List[TrendingItem]:
    items: List[TrendingItem] = []
    yesterday = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    async with make_async_client(proxy, timeout_sec) as client:
        # 维基百科 REST API 要求带可联系 UA，否则可能返回 HTML 拦截页
        client.headers["User-Agent"] = "OmniSearchGateway/2.0 (https://github.com/omnisearch; contact@omnisearch.local)"
        resp = await client.get(
            f"https://zh.wikipedia.org/api/rest_v1/feed/featured/{yesterday:%Y/%m/%d}",
            headers={"Accept": "application/json; charset=utf-8"},
        )
        articles = (resp.json().get("mostread") or {}).get("articles") or []
        for a in articles:
            titles = a.get("titles", {}) or {}
            title = (titles.get("normalized") or titles.get("canonical") or "").strip()
            if not title or title in ("Wikipedia:首页", "Main Page", "Portal:当前事件"):
                continue
            link = a.get("link") or ""
            url = f"https://zh.wikipedia.org/{link}" if link else "https://zh.wikipedia.org/"
            items.append(
                TrendingItem(
                    rank=len(items) + 1,
                    title=title,
                    url=url,
                    hot_value=f"{_fmt_hot(a.get('views'))} 浏览",
                    hot_score=a.get("views"),
                )
            )
            if len(items) >= max_items:
                break
    return items


# ==================== 榜单注册表 ====================

BOARD_META: Dict[str, Dict[str, Any]] = {
    "baidu_hot": {
        "name": "百度热搜", "source": "baidu.com", "category": "comprehensive",
        "emoji": "🔥", "site_url": "https://top.baidu.com/board", "prefer_proxy": False,
    },
    "weibo_hot": {
        "name": "微博热搜", "source": "weibo.com", "category": "comprehensive",
        "emoji": "📢", "site_url": "https://s.weibo.com/top/summary", "prefer_proxy": False,
    },
    "zhihu_hot": {
        "name": "知乎热榜", "source": "zhihu.com", "category": "comprehensive",
        "emoji": "💡", "site_url": "https://www.zhihu.com/hot", "prefer_proxy": False,
    },
    "tencent_hot": {
        "name": "腾讯新闻热点榜", "source": "news.qq.com", "category": "news",
        "emoji": "📰", "site_url": "https://news.qq.com/", "prefer_proxy": False,
    },
    "douyin_hot": {
        "name": "抖音热点", "source": "douyin.com", "category": "comprehensive",
        "emoji": "🎵", "site_url": "https://www.douyin.com/hot", "prefer_proxy": False,
    },
    "bilibili_rank": {
        "name": "B站排行榜", "source": "bilibili.com", "category": "comprehensive",
        "emoji": "📺", "site_url": "https://www.bilibili.com/v/popular/rank/all", "prefer_proxy": False,
    },
    "github_trending": {
        "name": "GitHub Trending", "source": "github.com", "category": "tech",
        "emoji": "🐙", "site_url": "https://github.com/trending", "prefer_proxy": True,
    },
    "hackernews_top": {
        "name": "Hacker News", "source": "news.ycombinator.com", "category": "tech",
        "emoji": "🟠", "site_url": "https://news.ycombinator.com/", "prefer_proxy": True,
    },
    "juejin_hot": {
        "name": "掘金热榜", "source": "juejin.cn", "category": "tech",
        "emoji": "⛏️", "site_url": "https://juejin.cn/rank", "prefer_proxy": False,
    },
    "v2ex_hot": {
        "name": "V2EX 热帖", "source": "v2ex.com", "category": "community",
        "emoji": "💬", "site_url": "https://www.v2ex.com/?tab=hot", "prefer_proxy": True,
    },
    "reddit_hot": {
        "name": "Reddit 热帖", "source": "reddit.com", "category": "community",
        "emoji": "👽", "site_url": "https://www.reddit.com/r/popular/", "prefer_proxy": True,
    },
    "wikipedia_mostread": {
        "name": "维基百科热门", "source": "zh.wikipedia.org", "category": "knowledge",
        "emoji": "📚", "site_url": "https://zh.wikipedia.org/", "prefer_proxy": True,
    },
}

TRENDING_FETCHERS: Dict[str, Callable] = {
    "baidu_hot": fetch_baidu_hot,
    "weibo_hot": fetch_weibo_hot,
    "zhihu_hot": fetch_zhihu_hot,
    "tencent_hot": fetch_tencent_hot,
    "douyin_hot": fetch_douyin_hot,
    "bilibili_rank": fetch_bilibili_rank,
    "github_trending": fetch_github_trending,
    "hackernews_top": fetch_hackernews_top,
    "juejin_hot": fetch_juejin_hot,
    "v2ex_hot": fetch_v2ex_hot,
    "reddit_hot": fetch_reddit_hot,
    "wikipedia_mostread": fetch_wikipedia_mostread,
}


def get_trending_catalog() -> List[Dict[str, Any]]:
    return [
        {
            "board_id": bid,
            "name": meta["name"],
            "source": meta["source"],
            "category": meta["category"],
            "emoji": meta["emoji"],
            "site_url": meta["site_url"],
        }
        for bid, meta in BOARD_META.items()
    ]


async def fetch_trending_board(
    board_id: str,
    max_items: int = 20,
    force_refresh: bool = False,
    global_proxy: Optional[str] = None,
    timeout_sec: float = 12.0,
) -> TrendingBoard:
    """抓取单个榜单（带缓存）。失败结果仅短缓存，成功结果缓存 5 分钟。"""
    meta = BOARD_META[board_id]
    now = time.time()
    cached = _board_cache.get(board_id)
    if cached and not force_refresh:
        ts, board = cached
        ttl = ERROR_CACHE_TTL_SECONDS if board.status != "success" else CACHE_TTL_SECONDS
        if now - ts < ttl:
            board = board.model_copy(deep=True)
            board.cached = True
            return board

    proxy = global_proxy if (meta.get("prefer_proxy") and global_proxy) else None
    board = TrendingBoard(
        board_id=board_id,
        name=meta["name"],
        source=meta["source"],
        category=meta["category"],
        emoji=meta["emoji"],
        site_url=meta["site_url"],
    )
    t0 = time.perf_counter()
    try:
        items = await TRENDING_FETCHERS[board_id](max_items, proxy, timeout_sec)
        board.items = items
        if items:
            board.status = "success"
        else:
            board.status = "error"
            board.error_message = "榜单源未返回数据（接口可能变更或被限流）"
    except Exception as e:  # noqa: BLE001 单源失败不影响其他榜单
        board.status = "error"
        board.error_message = str(e)[:200]
    board.latency_ms = int((time.perf_counter() - t0) * 1000)
    board.fetched_at = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _board_cache[board_id] = (now, board.model_copy(deep=True))
    return board
