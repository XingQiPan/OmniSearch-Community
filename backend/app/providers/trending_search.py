"""把全网热榜接入统一检索链路。

设计要点：
- 纯字符串匹配决定是否命中，无关查询立即返回空列表，不产生任何网络请求；
- 命中后并发抓取最多 4 个榜单，复用 trending 模块 5 分钟缓存；
- 榜单抓取时间只写入 metadata，绝不当成发布时间（published_at）。
"""
import asyncio
from typing import Any, Dict, List

from app.providers.adapters import SEARCH_ADAPTER_REGISTRY
from app.providers.trending import BOARD_META, fetch_trending_board
from app.schemas import UnifiedSearchItem

# 每个榜单的显式别名（用户实际输入的说法）
BOARD_QUERY_ALIASES: Dict[str, List[str]] = {
    "baidu_hot": ["百度热搜", "百度热点", "百度榜", "百度排行", "百度"],
    "weibo_hot": ["微博热搜", "微博热点", "微博榜", "微博排行", "微博"],
    "zhihu_hot": ["知乎热榜", "知乎热搜", "知乎榜", "知乎"],
    "tencent_hot": ["腾讯新闻热搜", "腾讯热榜", "腾讯新闻热榜", "腾讯热点", "腾讯新闻榜", "腾讯新闻"],
    "douyin_hot": ["抖音热搜", "抖音热点", "抖音榜", "抖音排行", "抖音"],
    "bilibili_rank": ["b站排行", "b站榜", "b站排行榜", "bilibili排行", "b站", "bilibili"],
    "github_trending": ["github趋势", "github trending", "github热榜", "github"],
    "hackernews_top": ["hacker news", "hn热榜", "hn榜", "hackernews"],
    "juejin_hot": ["掘金热榜", "掘金榜", "掘金"],
    "v2ex_hot": ["v2ex热帖", "v2ex"],
    "reddit_hot": ["reddit热帖", "reddit"],
    "wikipedia_mostread": ["维基百科热门", "维基百科榜", "维基百科"],
}

# 只出现平台名时，顺带返回该平台旗下的一组榜（例如“红果”含热播/新剧/推荐/飙升）
PLATFORM_BOARDS: Dict[str, List[str]] = {
    "抖音": ["douyin_hot"],
    "知乎": ["zhihu_hot"],
    "腾讯": ["tencent_hot"],
    "b站": ["bilibili_rank"],
    "bilibili": ["bilibili_rank"],
    "微博": ["weibo_hot"],
    "百度": ["baidu_hot"],
}

# 只说“热榜/热搜”这类泛指词时，返回一组综合榜
GENERIC_TRENDING_WORDS = ["热榜", "热搜", "榜单", "排行榜", "排行", "热门", "trending", "hot list"]
GENERIC_BOARDS = ["baidu_hot", "weibo_hot", "douyin_hot", "zhihu_hot", "bilibili_rank", "tencent_hot"]
MAX_BOARDS_PER_QUERY = 4
GENERIC_BOARD_LIMIT = 6

# 带这些词说明用户要的是解读而不是原始数据，保留模型综合分析
ANALYSIS_WORDS = ["分析", "解读", "趋势", "原因", "为什么", "对比", "总结", "洞察", "影响",
                  "报告", "研究", "评价", "看法", "怎么", "如何", "意味着"]
# 只有出现这些"榜单词"才视为要原始榜单数据；仅平台名不够
RANKING_INTENT_WORDS = ["榜", "热搜", "热榜", "排行", "trending", "hot list"]


def match_boards(query: str) -> List[str]:
    """纯本地匹配，不触网。返回按相关度排序的 board_id。"""
    q = (query or "").lower().strip()
    if not q:
        return []
    scores: Dict[str, int] = {}
    for board_id, meta in BOARD_META.items():
        aliases = [a.lower() for a in BOARD_QUERY_ALIASES.get(board_id, [])]
        name = (meta.get("name") or "").lower()
        base_name = name.split("(")[0].split("（")[0].strip()
        if any(alias in q for alias in aliases):
            scores[board_id] = max(scores.get(board_id, 0), 3)
        elif base_name and base_name in q:
            scores[board_id] = max(scores.get(board_id, 0), 2)
        elif (meta.get("source") or "").lower() and meta["source"].lower() in q:
            scores[board_id] = max(scores.get(board_id, 0), 1)
    # 平台名命中时补齐该平台旗下榜单，避免只看到其中一个榜
    for platform, board_ids in PLATFORM_BOARDS.items():
        if platform in q:
            for board_id in board_ids:
                if board_id in BOARD_META:
                    scores[board_id] = max(scores.get(board_id, 0), 3)
    if not scores and any(word in q for word in GENERIC_TRENDING_WORDS):
        return GENERIC_BOARDS[:GENERIC_BOARD_LIMIT]
    # 稳定排序：分数降序，同分按 board_id，避免顺序抖动
    ranked = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
    return [board_id for board_id, _ in ranked[:MAX_BOARDS_PER_QUERY]]


def direct_data_boards(query: str) -> List[str]:
    """纯榜单数据查询才直出：必须出现"榜/排行/热搜"等榜单词，且不含分析类词。

    只出现平台名（如"抖音""b站最火up主"）不算榜单查询，仍走正常检索＋模型综述。
    """
    q = (query or "").lower()
    if any(word in q for word in ANALYSIS_WORDS):
        return []
    if not any(word in q for word in RANKING_INTENT_WORDS):
        return []
    return match_boards(query)


async def search_trending(
    query: str,
    max_results: int,
    proxy: str | None,
    timeout_sec: float,
    **kwargs: Any,
) -> List[UnifiedSearchItem]:
    board_ids = match_boards(query)
    if not board_ids:
        return []
    per_board = max(1, min(int(max_results or 10), 10))
    boards = await asyncio.gather(
        *(
            fetch_trending_board(board_id, max_items=per_board, global_proxy=proxy, timeout_sec=timeout_sec)
            for board_id in board_ids
        ),
        return_exceptions=True,
    )

    items: List[UnifiedSearchItem] = []
    for board in boards:
        if isinstance(board, BaseException) or board.status != "success":
            continue
        for entry in board.items:
            # 榜单条目偶尔缺详情链接：用带名次的榜单地址兜底，保证每条独立不被去重合并
            entry_url = entry.url or f"{board.site_url}{'&' if '?' in board.site_url else '?'}rank={entry.rank}"
            items.append(
                UnifiedSearchItem(
                    title=f"{board.name} #{entry.rank} {entry.title}",
                    url=entry_url,
                    normalized_url="",
                    snippet=entry.subtitle or (f"热度：{entry.hot_value}" if entry.hot_value else ""),
                    content=None,
                    published_at=None,  # 榜单抓取时间不是发布时间，绝不复用
                    domain="",
                    source_engine="trending",
                    engines=["trending"],
                    positions={"trending": entry.rank},
                    raw_score=round(1.0 / max(1, entry.rank), 4),
                    category=board.category,
                    metadata={
                        "trending": True,
                        "board_id": board.board_id,
                        "board_name": board.name,
                        "board_source": board.source,
                        "board_fetched_at": board.fetched_at,
                        "board_cached": board.cached,
                        "rank": entry.rank,
                        "hot_value": entry.hot_value,
                        "hot_score": entry.hot_score,
                        "tag": entry.tag,
                        "video_platform": entry.video_platform,
                        "video_id": entry.video_id,
                    },
                )
            )
            if len(items) >= max_results:
                return items
    return items


SEARCH_ADAPTER_REGISTRY["trending"] = search_trending
