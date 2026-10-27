import ipaddress
import re
from datetime import datetime, timezone
from typing import Dict, List, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from app.core.database import get_settings
from app.schemas import UnifiedSearchItem

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "spm", "from", "src", "ref", "fbclid", "gclid", "msclkid", "_ga"
}


def normalize_url(raw_url: str) -> str:
    if not raw_url:
        return ""
    try:
        parsed = urlparse(raw_url.strip())
        scheme = "https" if parsed.scheme in ("http", "https") else parsed.scheme
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        path = parsed.path.rstrip("/") or "/"
        query_pairs = [
            (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=False)
            if k.lower() not in TRACKING_PARAMS
        ]
        query_pairs.sort(key=lambda x: x[0])
        clean_query = urlencode(query_pairs)
        return urlunparse((scheme, netloc, path, "", clean_query, ""))
    except Exception:
        return raw_url.strip().rstrip("/")


def canonical_host(value: str) -> str:
    """Normalize a hostname, not a URL/path/substring or wildcard rule."""
    value = (value or '').strip().rstrip('.').lower()
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass
    try:
        value = value.encode('idna').decode('ascii')
    except UnicodeError:
        return ''
    if len(value) > 253 or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in value.split('.')):
        return ''
    return value


def domain_matches(host: str, rule: str) -> bool:
    host, rule = canonical_host(host), canonical_host(rule)
    if not host or not rule:
        return False
    if host == rule:
        return True
    try:
        ipaddress.ip_address(rule)
        return False  # IP literals have no subdomains.
    except ValueError:
        return host.endswith('.' + rule)


def extract_domain(raw_url: str) -> str:
    try:
        return canonical_host(urlparse(raw_url).hostname or '')
    except ValueError:
        return ''


def _recency_score(published_at) -> float:
    """发布时间新鲜度：7 天 1.0 / 30 天 0.85 / 半年 0.65 / 一年 0.45 / 更早 0.3，未知 0.5。"""
    if not published_at:
        return 0.5
    try:
        value = str(published_at).strip().replace('Z', '+00:00')
        parsed = datetime.fromisoformat(value[:10] if re.fullmatch(r'\d{4}-\d{2}-\d{2}.*', value) else value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        days = max(0, (datetime.now(timezone.utc) - parsed).days)
    except (ValueError, TypeError):
        return 0.5
    if days <= 7:
        return 1.0
    if days <= 30:
        return 0.85
    if days <= 180:
        return 0.65
    if days <= 365:
        return 0.45
    return 0.3


def evidence_breakdown(item: UnifiedSearchItem, engine_weights: Dict[str, float],
                       rrf_k: int, boosted_domains: List[str]) -> Dict[str, object]:
    """按「召回强度 + 跨源印证 + 域名权威 + 时效」拆解可信度。

    借鉴 Argo 的证据候选/可信度分解思路，不改变排序，只把可解释性写入 metadata，
    供前端与 Agent 判断证据强弱；所有子项归一到 0~1。
    """
    engines = item.engines or [item.source_engine]
    positions = item.positions or {}
    pairs = [(float(engine_weights.get(e, 1.0)), positions.get(e, 1)) for e in engines]
    total_weight = sum(weight for weight, _ in pairs) or 1.0
    # 平均倒数排名（按引擎权重加权）：rank1 命中记满分，rank2 记 0.5，依此类推。
    weighted_precision = sum(weight / max(1, rank) for weight, rank in pairs) / total_weight
    global_max_weight = max([float(v) for v in engine_weights.values()] or [1.0])
    retrieval = min(1.0, weighted_precision * (max((w for w, _ in pairs), default=1.0) / global_max_weight))
    corroboration = min(1.0, 0.35 + 0.2 * (len(engines) - 1))
    host = item.domain or item.source_engine
    if any(domain_matches(host, b) for b in boosted_domains):
        authority = 1.0
    elif host.endswith(('.gov', '.edu')) or host.startswith(('docs.', 'developer.')):
        authority = 0.85
    else:
        authority = 0.6
    recency = _recency_score(item.published_at)
    confidence = 0.40 * retrieval + 0.20 * corroboration + 0.25 * authority + 0.15 * recency
    return {
        'confidence': round(confidence, 3),
        'engine_count': len(engines),
        'breakdown': {
            'retrieval': round(retrieval, 3),
            'corroboration': round(corroboration, 3),
            'authority': round(authority, 3),
            'recency': round(recency, 3),
        },
        'method': 'rrf+corroboration+authority+recency',
    }


def fuse_and_deduplicate(
    per_engine_results: Dict[str, List[UnifiedSearchItem]],
    engine_weights: Dict[str, float],
    enable_dedup: bool = True,
    enable_rrf: bool = True,
    include_domains: List[str] = None,
    exclude_domains: List[str] = None,
) -> Tuple[List[UnifiedSearchItem], int]:
    """
    Merges multi-engine results using URL normalization and Reciprocal Rank Fusion (RRF)
    plus multi-source overlap boosting.
    Returns (sorted_items, cross_engine_hits_count).
    """
    settings = get_settings()
    rrf_k = int(settings.get("rrf_k", 60))
    multi_source_boost = float(settings.get("multi_source_boost", 1.45))
    blocked_domains = [d.lower() for d in settings.get("blocked_domains", [])]
    boosted_domains = [d.lower() for d in settings.get("boosted_domains", [])]
    inc_domains = [d.lower() for d in (include_domains or []) if d]
    exc_domains = [d.lower() for d in (exclude_domains or []) if d] + blocked_domains

    merged_map: Dict[str, UnifiedSearchItem] = {}
    unmerged_list: List[UnifiedSearchItem] = []

    for engine_id, items in sorted(per_engine_results.items()):
        w = float(engine_weights.get(engine_id, 1.0))
        seen_urls = set()
        for rank_idx, source_item in enumerate(items, start=1):
            item = source_item.model_copy(deep=True)
            if not item.url or not item.title:
                continue
            norm_url = normalize_url(item.url)
            # One vote per normalized URL per engine, even with cross-engine dedup disabled.
            if norm_url in seen_urls:
                continue
            seen_urls.add(norm_url)
            domain = extract_domain(item.url)
            item.normalized_url = norm_url
            item.domain = domain
            if not item.favicon and domain:
                item.favicon = f"https://www.google.com/s2/favicons?domain={domain}&sz=64"

            # Filter domains
            if not domain or urlparse(item.url).scheme.lower() not in ('http', 'https'):
                continue
            if exc_domains and any(domain_matches(domain, ex) for ex in exc_domains):
                continue
            if inc_domains and not any(domain_matches(domain, inc) for inc in inc_domains):
                continue

            pos_rrf = w * (1.0 / (rrf_k + rank_idx))

            if not enable_dedup:
                item.engines = [engine_id]
                item.positions = {engine_id: rank_idx}
                item.rrf_score = round(pos_rrf, 5)
                item.final_score = round(pos_rrf, 5)
                unmerged_list.append(item)
                continue

            if norm_url in merged_map:
                existing = merged_map[norm_url]
                if engine_id not in existing.engines:
                    existing.engines.append(engine_id)
                existing.positions[engine_id] = min(existing.positions.get(engine_id, 999), rank_idx)
                existing.rrf_score += pos_rrf
                # Keep longer snippet / content
                if len(item.snippet or "") > len(existing.snippet or ""):
                    existing.snippet = item.snippet
                if item.content and not existing.content:
                    existing.content = item.content
                if item.published_at and not existing.published_at:
                    existing.published_at = item.published_at
                existing.metadata.update(item.metadata or {})
            else:
                clone = item.model_copy(deep=True)
                clone.engines = [engine_id]
                clone.positions = {engine_id: rank_idx}
                clone.rrf_score = pos_rrf
                merged_map[norm_url] = clone

    results = list(merged_map.values()) if enable_dedup else unmerged_list
    cross_hits = 0

    for r in results:
        hit_count = len(r.engines)
        if hit_count > 1:
            cross_hits += 1
        overlap_multiplier = (multi_source_boost ** (hit_count - 1)) if (enable_rrf and hit_count > 1) else 1.0
        domain_multiplier = 1.2 if any(domain_matches(r.domain, bd) for bd in boosted_domains) else 1.0
        score = r.rrf_score * overlap_multiplier * domain_multiplier
        r.rrf_score = round(r.rrf_score, 5)
        r.final_score = round(score, 5)
        r.metadata['evidence'] = evidence_breakdown(r, engine_weights, rrf_k, boosted_domains)

    results.sort(key=lambda x: (-x.final_score, x.normalized_url or x.url, x.source_engine))
    return results, cross_hits
