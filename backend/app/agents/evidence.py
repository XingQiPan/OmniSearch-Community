"""Bounded Agent reading budget, source diversity and truthful read accounting."""
import asyncio
from urllib.parse import urlparse

from app.gateway.freshness import annotate_time, evidence_label, utc_now
from app.providers.adapters import read_url_evidence


def choose_sources(items, attempted, limit, preferred=None):
    candidates = sorted(
        [item for item in items if (item.normalized_url or item.url) not in attempted],
        key=lambda item: item.final_score, reverse=True,
    )[:24]
    ordered = []
    for item in list(preferred or []) + candidates:
        if item in candidates and item not in ordered:
            ordered.append(item)
    selected, domains = [], set()
    for item in ordered:
        domain = urlparse(item.url).hostname or item.domain
        if domain not in domains:
            selected.append(item)
            domains.add(domain)
        if len(selected) >= limit:
            return selected[:limit]
    for item in ordered:
        if item not in selected:
            selected.append(item)
        if len(selected) >= limit:
            break
    return selected[:limit]


async def read_sources(items, round_idx, proxy, api_key, window):
    semaphore = asyncio.Semaphore(4)

    async def read(item):
        async with semaphore:
            try:
                result = await asyncio.wait_for(read_url_evidence(item.url, proxy, api_key, 6.5), timeout=14)
            except Exception:
                result = {'text': '', 'read_status': 'failed', 'retrieved_at': utc_now().isoformat()}
        text = result.pop('text', '')
        published = result.pop('published_at', None)
        if published:
            item.metadata['search_reported_published_at'] = item.published_at
            item.published_at = published
        item.metadata.update(result)
        if text:
            item.content = text
        else:
            item.metadata['read_status'] = 'summary_only' if item.snippet else 'failed'
        annotate_time(item, window)
        return {'round': round_idx, 'title': item.title, 'url': item.url,
                'domain': item.domain, 'engines': item.engines, 'chars': len(text),
                'status': item.metadata['read_status'],
                'truncated': item.metadata.get('content_truncated', False),
                'published_at': item.published_at,
                'freshness': item.metadata['freshness']}

    return await asyncio.gather(*(read(item) for item in items))


def evidence_context(item, index, max_chars=8000):
    body = item.content or item.snippet or ''
    return (f"[{index}] 标题: {item.title}\nURL: {item.url}\n"
            f"证据时间与读取状态: {evidence_label(item)}\n"
            f"报告上下文截断: {len(body) > max_chars}\n内容: {body[:max_chars]}\n")


def build_raw_dump(query, items, max_content_chars=1200, extra_header=None):
    """原样回传：不做摘要、不改写、不调用模型；缺失内容如实标注。"""
    lines = [f'### 原始检索结果：{query}', '',
             f'- 条数：{len(items)}', '- 本结果由检索引擎直接返回，未经任何大模型处理。']
    for line in (extra_header or []):
        lines.append(f'- {line}')
    lines.append('')
    for index, item in enumerate(items, start=1):
        meta = item.metadata or {}
        lines.append(f'#### {index}. {item.title}')
        lines.append(f'- 链接：{item.url}')
        lines.append(f'- 来源：{item.domain or "未知"} ｜ 引擎：{", ".join(item.engines) or item.source_engine}')
        lines.append(f'- 发布时间：{item.published_at or "未知"}')
        if meta.get('board_name'):
            lines.append(f'- 榜单：{meta["board_name"]} 第 {meta.get("rank", "-")} 名 ｜ 热度：{meta.get("hot_value") or "未提供"}')
        if meta.get('video_platform'):
            lines.append(f'- 可解析：{meta["video_platform"]} ｜ ID：{meta.get("video_id") or "无"}')
        if item.snippet:
            lines.append(f'- 摘要：{item.snippet}')
        if item.content:
            body = item.content[:max_content_chars]
            suffix = '（已截断）' if len(item.content) > max_content_chars else ''
            lines.append(f'- 正文{suffix}：{body}')
        lines.append('')
    return '\n'.join(lines)


def coverage_gaps(items, window, budget, successful_count):
    gaps = []
    if budget and successful_count < min(4, budget):
        gaps.append('成功读取正文的独立页面不足，请补查官方文档与独立验证来源')
    if window and not any(item.metadata.get('freshness') == 'recent' for item in items):
        gaps.append('尚无可确认处于时间范围内的证据，请补查带发布日期的官方公告或版本记录')
    return gaps
