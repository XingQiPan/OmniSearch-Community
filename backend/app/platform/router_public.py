"""对外开放的搜索服务 API（``/v1/*``）。

接口设计对齐 Tavily / Exa / Serper / Brave / 博查 / Perplexity 的公共约定：
- ``Authorization: Bearer sk-omni-xxx``（同时兼容 ``X-API-Key``）；
- ``POST /v1/search`` 返回 ``{request_id, results[], usage{}}``；
- 每次成功调用都在 ``usage`` 中回传消耗次数与余额，可对账；
- 错误统一为 ``{"error": {code, type, message, request_id}}``；
- 全站回传 ``X-Request-Id`` / ``X-RateLimit-*`` / ``X-Quota-Remaining`` 响应头。
"""
import asyncio
import json
import re
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.database import get_settings
from app.gateway.dispatcher import dispatch_unified_search
from app.gateway.key_pool import key_pool
from app.platform import store
from app.platform import metering
from app.platform.auth import AuthContext, ensure_scope, require_auth
from app.platform.errors import ApiError
from app.platform.metering import (
    assert_feature,
    resolve_answer_units,
    resolve_chat_units,
    resolve_extract_units,
    resolve_research_units,
    resolve_search_units,
    usage_block,
)
from app.platform.schemas import (
    Citation,
    ExtractResponse,
    ExtractResultItem,
    MeKey,
    MeResponse,
    ModelCard,
    ModelListResponse,
    PublicAnswerRequest,
    PublicExtractRequest,
    PublicResearchRequest,
    PublicSearchRequest,
    ResearchResponse,
    SearchResponse,
    SearchResultItem,
    SignupRequest,
    SignupResponse,
    UsageResponse,
)
from app.providers.adapters import read_url_evidence
from app.schemas import AgentSearchRequest, UnifiedSearchItem, UnifiedSearchRequest, UnifiedSearchResponse

router = APIRouter(prefix="/v1", tags=["开放 API v1"])

TOPIC_ROUTE = {
    "general": "auto",
    "news": "auto",
    "academic": "academic",
    "code": "code",
    "social": "social",
    "entertainment": "entertainment",
}

FRESHNESS_MAP = {
    "pd": "day", "d": "day", "day": "day", "1d": "day",
    "pw": "week", "w": "week", "week": "week", "7d": "week",
    "pm": "month", "m": "month", "month": "month", "30d": "month",
    "py": "year", "y": "year", "year": "year", "1y": "year",
    "all": None, "any": None, "": None,
}


# ==================== 通用工具 ====================

def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "") or f"req_{uuid.uuid4().hex[:24]}"


def _normalize_time_range(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = str(value).strip().lower()
    if v in FRESHNESS_MAP:
        return FRESHNESS_MAP[v]
    # Brave / 博查风格区间过滤：只取区间长度映射到时间范围
    m = re.match(r"^(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})$", v)
    if m:
        return "month"
    return None


def _favicon(domain: str) -> Optional[str]:
    if not domain:
        return None
    return f"https://{domain}/favicon.ico"


def _extract_images(item: UnifiedSearchItem) -> List[str]:
    images: List[str] = []
    meta = item.metadata or {}
    for key in ("image", "cover", "thumbnail", "thumbnail_url", "og_image"):
        value = meta.get(key)
        if isinstance(value, str) and value.startswith("http"):
            images.append(value)
    extra = meta.get("images")
    if isinstance(extra, list):
        images.extend([u for u in extra if isinstance(u, str) and u.startswith("http")])
    seen, out = set(), []
    for url in images:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out[:4]


def _to_public_item(item: UnifiedSearchItem, index: int, max_score: float,
                    include_raw: bool, include_favicon: bool,
                    include_images: bool) -> SearchResultItem:
    score = round(item.final_score / max_score, 4) if max_score > 0 else 0.0
    metadata = {
        "source_engine": item.source_engine,
        "positions": item.positions,
        "rrf_score": round(item.rrf_score, 6),
    }
    if item.rerank_score is not None:
        metadata["rerank_score"] = round(item.rerank_score, 6)
    for key in ("read_status", "queried_at", "freshness", "translated_query", "query_variant", "evidence"):
        if item.metadata.get(key) is not None:
            metadata[key] = item.metadata[key]
    return SearchResultItem(
        id=f"r{index}",
        title=item.title or item.url,
        url=item.url,
        snippet=(item.snippet or "")[:2000],
        content=(item.content or None) if include_raw else None,
        domain=item.domain or "",
        published_at=item.published_at,
        favicon=_favicon(item.domain) if include_favicon else None,
        score=max(0.0, min(1.0, score)),
        category=item.category or "web",
        sources=list(item.engines or [item.source_engine]),
        images=_extract_images(item) if include_images else [],
        metadata=metadata,
    )


def _public_items(items: List[UnifiedSearchItem], include_raw: bool = False,
                  include_favicon: bool = True, include_images: bool = False) -> List[SearchResultItem]:
    max_score = max((i.final_score for i in items), default=0.0)
    return [
        _to_public_item(item, idx, max_score, include_raw, include_favicon, include_images)
        for idx, item in enumerate(items, start=1)
    ]


def _public_trace(result: UnifiedSearchResponse) -> Dict[str, Any]:
    """检索过程的对外视图。

    只暴露实际参与检索的引擎与状态：内部的密钥掩码、代理、原始报错（可能含带 key 的上游 URL）
    以及未配置/已禁用的渠道一律不出网关。
    """
    engines = [
        {
            "id": t.engine_id,
            "name": t.engine_name,
            "status": t.status,
            "latency_ms": t.latency_ms,
            "result_count": t.result_count,
        }
        for t in result.engine_traces or []
        if t.status != "skipped"
    ]
    return {
        "route": result.resolved_route,
        "queries": list(result.rewritten_queries or []),
        "raw_results": result.total_raw_results,
        "merged_results": result.total_merged_results,
        "cross_engine_hits": result.cross_engine_hits,
        "engines": engines,
    }


def _render_markdown(query: str, answer: Optional[str], results: List[SearchResultItem]) -> str:
    lines = [f"# {query}", ""]
    if answer:
        lines += [answer.strip(), ""]
    lines.append(f"## 检索结果（{len(results)} 条）")
    lines.append("")
    for idx, item in enumerate(results, start=1):
        lines.append(f"### {idx}. [{item.title}]({item.url})")
        meta = f"`{item.domain}` · 相关度 {item.score:.2f} · 来源 {', '.join(item.sources) or 'gateway'}"
        if item.published_at:
            meta += f" · 发布 {item.published_at}"
        lines.append(meta)
        if item.snippet:
            lines.append("")
            lines.append(item.snippet.strip())
        if item.content:
            lines.append("")
            lines.append(item.content.strip()[:4000])
        lines.append("")
    return "\n".join(lines).strip()


def _build_search_request(payload: PublicSearchRequest, max_results: int) -> UnifiedSearchRequest:
    depth = payload.search_depth
    rerank = payload.rerank if payload.rerank is not None else depth in ("advanced", "deep")
    timeout_default = {"basic": 6000, "advanced": 9000, "deep": 15000}[depth]
    scrape_top_n = 0
    if payload.include_raw_content:
        scrape_top_n = min(max_results, 4)
    elif depth == "deep":
        # deep 的计费口径包含正文抽取：不需要再额外传 include_raw_content
        scrape_top_n = min(max_results, 3)
    time_range = _normalize_time_range(payload.time_range)
    query = (payload.query or "").strip()
    return UnifiedSearchRequest(
        query=query,
        route_group=TOPIC_ROUTE.get(payload.topic, "auto"),
        engines=payload.engines or None,
        top_k=max_results,
        timeout_ms=payload.timeout_ms or timeout_default,
        enable_dedup=True,
        enable_rrf=True,
        enable_rerank=bool(rerank),
        include_domains=[d.strip().lower() for d in payload.include_domains if d.strip()],
        exclude_domains=[d.strip().lower() for d in payload.exclude_domains if d.strip()],
        time_range=time_range,  # type: ignore[arg-type]
        scrape_top_n=scrape_top_n,
        use_cache=payload.cache,
    )


def _filter_by_date(items: List[UnifiedSearchItem], start_date: Optional[str],
                    end_date: Optional[str]) -> List[UnifiedSearchItem]:
    if not start_date and not end_date:
        return items

    def keep(item: UnifiedSearchItem) -> bool:
        published = (item.published_at or "")[:10]
        if not published or len(published) < 10:
            return True  # 无发布时间的条目不做误杀
        if start_date and published < start_date:
            return False
        if end_date and published > end_date:
            return False
        return True

    return [item for item in items if keep(item)]


# ==================== 答案合成 ====================

_ANSWER_SYSTEM = (
    "你是联网搜索答案引擎。请只依据给定资料回答，用 [1][2] 这样的编号标注引用；"
    "资料不足时明确说明「资料未覆盖」，不要编造事实。输出简洁的中文 Markdown。"
)

#: ``stream_llm_text`` 在 LLM 不可达时会以文本形式吐出运维告警，付费 API 不能让这类内容
#: 混进答案里——一旦命中就直接判定为「本次没用上大模型」，走降级合成。
_LLM_WARNING_MARKERS = ("⚠️", "大模型流式调用异常", "已自动切换为网关内置智能摘要模式",
                        "大模型接口返回 HTTP")


def _is_llm_warning(text: str) -> bool:
    return any(marker in text for marker in _LLM_WARNING_MARKERS)


def _answer_prompt(query: str, items: List[UnifiedSearchItem], detailed: bool) -> str:
    budget = 2400 if detailed else 900
    blocks = []
    for idx, item in enumerate(items[:12], start=1):
        body = (item.content or item.snippet or "")[: budget]
        blocks.append(f"[{idx}] {item.title}\nURL: {item.url}\n{body}")
    return f"问题：{query}\n\n资料：\n" + "\n\n".join(blocks)


async def _llm_answer(query: str, items: List[UnifiedSearchItem], mode: str) -> Optional[str]:
    from app.agents.search_agent import resolve_active_llm, stream_llm_text

    prov, key_info, proxy, model = resolve_active_llm()
    if not prov or not key_info:
        return None
    detailed = mode == "deep"
    messages = [
        {"role": "system", "content": _ANSWER_SYSTEM},
        {"role": "user", "content": _answer_prompt(query, items, detailed)},
    ]
    chunks: List[str] = []
    try:
        async for delta in stream_llm_text(messages, prov, key_info, proxy, model):
            if _is_llm_warning(delta):
                return None
            chunks.append(delta)
            if sum(len(c) for c in chunks) > 6000:
                break
    except Exception:
        return None
    text = "".join(chunks).strip()
    return text or None


def _lexical_answer(query: str, items: List[UnifiedSearchItem], mode: str) -> str:
    from app.agents.search_agent import generate_extractive_synthesis

    return generate_extractive_synthesis(query, items, mode="deep" if mode == "deep" else "fast")


def _citations(items: List[UnifiedSearchItem], limit: int = 12) -> List[Citation]:
    out = []
    for idx, item in enumerate(items[:limit], start=1):
        out.append(Citation(index=idx, title=item.title or item.url, url=item.url,
                            domain=item.domain or ""))
    return out


# ==================== /v1/search ====================

async def _execute_search(request: Request, auth: AuthContext,
                          payload: PublicSearchRequest) -> Dict[str, Any]:
    query = (payload.query or "").strip()
    if not query:
        raise ApiError("missing_query", param="query")
    if payload.engines:
        assert_feature(auth, "allow_rerank", "自定义检索引擎编排")
    if payload.include_answer:
        assert_feature(auth, "allow_answer", "带引用的答案生成")
    if payload.include_raw_content:
        assert_feature(auth, "allow_extract", "网页正文抓取")

    effective_rerank = payload.rerank if payload.rerank is not None else payload.search_depth in (
        "advanced", "deep")
    units = resolve_search_units(auth, payload.search_depth, bool(effective_rerank))
    # 套餐返回条数上限：超出部分静默截断（对齐 Tavily / Brave 的 cap 语义）
    plan_max = int(auth.plan.get("max_results") or 50)
    effective_max = max(1, min(payload.max_results, plan_max))
    internal_req = _build_search_request(payload, effective_max)
    started = time.perf_counter()
    try:
        result = await dispatch_unified_search(internal_req, mode_label="public_api")
    except asyncio.TimeoutError:
        raise ApiError("upstream_timeout")
    except Exception as exc:  # noqa: BLE001
        raise ApiError("search_failed", message=f"搜索执行失败：{str(exc)[:120]}")

    items = _filter_by_date(list(result.results), payload.start_date, payload.end_date)
    include_raw = bool(payload.include_raw_content) or payload.search_depth == "deep"
    public_items = _public_items(items, include_raw, payload.include_favicon, payload.include_images)

    answer: Optional[str] = None
    if payload.include_answer and items:
        detailed = payload.include_answer == "detailed"
        answer = await _llm_answer(query, items, "deep" if detailed else "fast")
        if not answer:
            answer = _lexical_answer(query, items, "deep" if detailed else "fast")

    images: List[str] = []
    for item in public_items:
        for url in item.images:
            if url not in images:
                images.append(url)

    latency_ms = int((time.perf_counter() - started) * 1000)
    usage = usage_block(units, auth)

    body: Dict[str, Any] = {
        "request_id": _request_id(request),
        "object": "search",
        "query": query,
        "route": result.resolved_route,
        "answer": answer,
        "results": [i.model_dump() for i in public_items],
        "images": images,
        "cached": bool(result.cache_hit),
        "latency_ms": latency_ms,
        "engine_count": len(result.engine_traces or []),
        "usage": usage,
    }
    if payload.response_format == "markdown":
        body["markdown"] = _render_markdown(query, answer, public_items)
    if payload.include_trace:
        body["trace"] = _public_trace(result)

    request.state.units = units
    request.state.route = result.resolved_route
    request.state.query = query
    request.state.result_count = len(public_items)
    request.state.cached = bool(result.cache_hit)
    return body


@router.post("/search", response_model=SearchResponse, summary="多源聚合搜索")
async def search_endpoint(
    request: Request,
    payload: PublicSearchRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    auth: AuthContext = Depends(require_auth),
) -> Any:
    """一次请求并发扇出多个检索源，跨源去重后用 RRF 融合排序返回。不调用大模型。

    - `search_depth=basic`：快速召回，1 次计费；
    - `search_depth=advanced`：叠加语义重排，2 次计费；
    - `search_depth=deep`：多源 + 重排 + Top 3 正文抽取（写入 `content`），3 次计费；
    - `include_trace=true`：附带引擎扇出与召回/去重统计，不额外计费。

    需要大模型参与时往上走：`/v1/answer`（带引用答案）→ `/v1/research`（子问题 / Agent 研究）。
    """
    ensure_scope(auth, "search")
    cached = _idempotent_replay(request, auth, idempotency_key, payload.model_dump())
    if cached is not None:
        return cached

    body = await _execute_search(request, auth, payload)
    _idempotent_store(auth, idempotency_key, payload.model_dump(), body)
    return body


@router.get("/search", summary="GET 风格聚合搜索（便于 curl 快速验证）")
async def search_get_endpoint(
    request: Request,
    q: str = Query(..., description="检索词"),
    max_results: int = Query(10, ge=1, le=50),
    search_depth: str = Query("basic"),
    topic: str = Query("general"),
    time_range: Optional[str] = Query(None),
    include_answer: bool = Query(False),
    include_trace: bool = Query(False),
    auth: AuthContext = Depends(require_auth),
) -> Any:
    payload = PublicSearchRequest(
        query=q,
        max_results=max_results,
        search_depth=search_depth,  # type: ignore[arg-type]
        topic=topic,  # type: ignore[arg-type]
        time_range=time_range,
        include_answer=include_answer,
        include_trace=include_trace,
    )
    ensure_scope(auth, "search")
    return await _execute_search(request, auth, payload)


# ==================== 幂等 ====================

def _idempotent_replay(request: Request, auth: AuthContext, idem_key: Optional[str],
                       payload: Dict[str, Any]) -> Optional[JSONResponse]:
    if not idem_key:
        return None
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    request_hash = store.hash_key(raw)
    try:
        hit = store.idempotency_get(auth.client_id, idem_key, request_hash)
    except ValueError:
        raise ApiError("idempotency_conflict")
    if not hit:
        return None
    status, body = hit
    request.state.units = 0
    request.state.idempotent_replay = True
    headers = {"Idempotent-Replayed": "true"}
    return JSONResponse(status_code=status, content=body, headers=headers)


def _idempotent_store(auth: AuthContext, idem_key: Optional[str],
                      payload: Dict[str, Any], body: Dict[str, Any]) -> None:
    if not idem_key:
        return
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    try:
        store.idempotency_put(auth.client_id, idem_key, store.hash_key(raw), 200, body)
    except Exception:
        pass


# ==================== /v1/extract ====================

def _try_title(markdown: str) -> Optional[str]:
    for line in markdown.splitlines()[:20]:
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()[:200]
        if line.startswith("Title:"):
            return line.split(":", 1)[1].strip()[:200]
    return None


@router.post("/extract", response_model=ExtractResponse, summary="网页正文抽取（Markdown）")
async def extract_endpoint(
    request: Request,
    payload: PublicExtractRequest,
    auth: AuthContext = Depends(require_auth),
) -> Any:
    ensure_scope(auth, "extract")
    urls: List[str] = []
    for raw_url in payload.urls:
        url = (raw_url or "").strip()
        if not url.startswith(("http://", "https://")):
            raise ApiError("invalid_url", message=f"非法 URL：{url[:80]}", param="urls")
        if url not in urls:
            urls.append(url)

    limit = metering.max_extract_urls()
    if len(urls) > limit:
        raise ApiError("too_many_urls", message=f"单次最多抽取 {limit} 个 URL，当前 {len(urls)} 个",
                       details={"limit": limit})

    units = resolve_extract_units(auth, len(urls))
    started = time.perf_counter()
    _, jina_key_info, jina_proxy = key_pool.acquire_credentials("jina_reader")
    jina_key = jina_key_info["api_key"] if jina_key_info else None

    semaphore = asyncio.Semaphore(5)

    async def run_one(url: str) -> ExtractResultItem:
        async with semaphore:
            try:
                evidence = await read_url_evidence(
                    url, proxy=jina_proxy, api_key=jina_key,
                    timeout_sec=max(5.0, payload.timeout_ms / 1000.0),
                    min_chars=60,
                )
                text = evidence.get("text") or ""
                if payload.format == "text" and text:
                    text = re.sub(r"```[a-zA-Z]*", "", text)
                    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
                    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
                    text = re.sub(r"[#>*`_-]{2,}", " ", text)
                    text = re.sub(r"\n{3,}", "\n\n", text).strip()
                status = "success" if text else "error"
                return ExtractResultItem(
                    url=url,
                    title=_try_title(evidence.get("text") or ""),
                    content=text,
                    format=payload.format,
                    length=len(text),
                    status=status,  # type: ignore[arg-type]
                    error=None if text else (evidence.get("read_status") or "正文为空或站点反爬"),
                    published_at=evidence.get("published_at"),
                    retrieved_at=evidence.get("retrieved_at"),
                    truncated=bool(evidence.get("content_truncated")),
                )
            except Exception as exc:  # noqa: BLE001
                return ExtractResultItem(url=url, status="error", format=payload.format,
                                         error=str(exc)[:200])

    results = await asyncio.gather(*[run_one(u) for u in urls])
    success = sum(1 for r in results if r.status == "success")
    latency_ms = int((time.perf_counter() - started) * 1000)

    # 只对成功抽取的 URL 计费（对齐 Tavily“按成功抽取计费”的口径）
    charged_units = metering.extract_units(success)
    request.state.units = charged_units
    request.state.endpoint = "/v1/extract"
    request.state.result_count = success
    request.state.query = urls[0] if urls else ""

    return {
        "request_id": _request_id(request),
        "object": "extract",
        "results": [r.model_dump() for r in results],
        "success_count": success,
        "failed_count": len(results) - success,
        "latency_ms": latency_ms,
        "usage": usage_block(charged_units, auth),
    }


# ==================== /v1/answer ====================

def _sse(event: str, data: Any) -> str:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


async def _answer_stream(
    request: Request,
    auth: AuthContext,
    query: str,
    items: List[UnifiedSearchItem],
    mode: str,
    units: int,
    include_citations: bool,
    started: float,
) -> AsyncGenerator[str, None]:
    cits = _citations(items) if include_citations else []
    yield _sse("meta", {
        "request_id": _request_id(request),
        "object": "answer.chunk",
        "query": query,
        "model": f"omni-{mode}",
        "citations": [c.model_dump() for c in cits],
        "usage": usage_block(units, auth),
    })

    from app.agents.search_agent import resolve_active_llm, stream_llm_text

    prov, key_info, proxy, model_name = resolve_active_llm()
    emitted = 0
    llm_failed = False
    if prov and key_info:
        messages = [
            {"role": "system", "content": _ANSWER_SYSTEM},
            {"role": "user", "content": _answer_prompt(query, items, mode == "deep")},
        ]
        try:
            async for delta in stream_llm_text(messages, prov, key_info, proxy, model_name):
                if not delta:
                    continue
                if _is_llm_warning(delta):
                    llm_failed = True
                    break
                emitted += len(delta)
                yield _sse("delta", {"type": "delta", "text": delta})
                if emitted > 6000:
                    break
        except Exception:
            llm_failed = True

    if emitted == 0:
        fallback = _lexical_answer(query, items, mode)
        step = 60
        for i in range(0, len(fallback), step):
            yield _sse("delta", {"type": "delta", "text": fallback[i:i + step]})

    latency_ms = int((time.perf_counter() - started) * 1000)
    yield _sse("done", {
        "request_id": _request_id(request),
        "object": "answer.done",
        "latency_ms": latency_ms,
        "llm_generated": emitted > 0 and not llm_failed,
        "citations": [c.model_dump() for c in cits],
        "usage": usage_block(units, auth),
    })
    yield "data: [DONE]\n\n"


@router.post("/answer", summary="带引用的答案生成（支持 SSE 流式）")
async def answer_endpoint(
    request: Request,
    payload: PublicAnswerRequest,
    auth: AuthContext = Depends(require_auth),
) -> Any:
    ensure_scope(auth, "answer")
    query = (payload.query or "").strip()
    if not query:
        raise ApiError("missing_query", param="query")

    mode = "deep" if "deep" in payload.model else "fast"
    units = resolve_answer_units(auth, mode, payload.stream)
    started = time.perf_counter()

    internal_req = UnifiedSearchRequest(
        query=query,
        route_group=TOPIC_ROUTE.get(payload.topic, "auto"),
        top_k=max(payload.max_results, 8),
        timeout_ms=payload.timeout_ms or (15000 if mode == "deep" else 8000),
        enable_rerank=True if mode == "deep" or auth.plan_flag("allow_rerank") else False,
        enable_dedup=True,
        enable_rrf=True,
        include_domains=payload.include_domains,
        exclude_domains=payload.exclude_domains,
        time_range=_normalize_time_range(payload.time_range),  # type: ignore[arg-type]
        scrape_top_n=3 if mode == "deep" else 0,
    )
    result = await dispatch_unified_search(internal_req, mode_label="public_answer")
    items = list(result.results)

    request.state.units = units
    request.state.route = result.resolved_route
    request.state.query = query
    request.state.result_count = len(items)

    if payload.stream:
        return StreamingResponse(
            _answer_stream(request, auth, query, items, mode, units,
                           payload.citations, started),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Request-Id": _request_id(request),
            },
        )

    answer = await _llm_answer(query, items, mode)
    if not answer:
        answer = _lexical_answer(query, items, mode)
    cits = _citations(items) if payload.citations else []
    latency_ms = int((time.perf_counter() - started) * 1000)
    body: Dict[str, Any] = {
        "request_id": _request_id(request),
        "object": "answer",
        "query": query,
        "model": f"omni-{mode}",
        "answer": answer,
        "citations": [c.model_dump() for c in cits],
        "latency_ms": latency_ms,
        "usage": usage_block(units, auth),
    }
    if payload.response_format == "markdown":
        body["markdown"] = answer
    return body


# ==================== /v1/research ====================

_PLAN_FIELDS = ("id", "title", "query", "route", "round", "status", "result_count", "latency_ms")
_READ_FIELDS = ("round", "title", "url", "domain", "status", "chars", "truncated", "published_at", "freshness")
_PAGE_FIELDS = ("url", "final_url", "title", "content", "format", "length", "status", "error",
                "published_at", "retrieved_at", "truncated")


def _pick(data: Dict[str, Any], fields: Tuple[str, ...]) -> Dict[str, Any]:
    return {key: data[key] for key in fields if key in data}


def _agent_event(chunk: str) -> Optional[Dict[str, Any]]:
    for line in (chunk or "").splitlines():
        if line.startswith("data:"):
            try:
                event = json.loads(line[5:].strip())
            except ValueError:
                return None
            return event if isinstance(event, dict) else None
    return None


class _ResearchRun:
    """把工作台 Agent 的内部事件流整理成对外事件，同时累积非流式响应需要的字段。

    对外事件：status / plan / read / decision / page / sources / delta / suggestions。
    与 ``/v1/answer`` 一致，大模型告警不会混进报告：报告阶段一个字都没写出来时，
    用内置抽取式合成兜底，并如实返回 ``llm_generated=false``。
    """

    def __init__(self, query: str):
        self.query = query
        self.route = "auto"
        self.items: List[UnifiedSearchItem] = []
        self.plan: List[Dict[str, Any]] = []
        self.reads: List[Dict[str, Any]] = []
        self.decisions: List[Dict[str, Any]] = []
        self.pages: List[Dict[str, Any]] = []
        self.suggestions: List[str] = []
        self.answer_parts: List[str] = []
        self.data_direct = False
        self.llm_available = False
        self._synthesizing = False
        self._synth_chars = 0

    @property
    def answer(self) -> str:
        return "".join(self.answer_parts).strip()

    @property
    def llm_generated(self) -> bool:
        return self.llm_available and self._synth_chars > 0 and not self.data_direct

    async def events(self, req: AgentSearchRequest) -> AsyncGenerator[Tuple[str, Any], None]:
        from app.agents.search_agent import resolve_active_llm, run_agent_search_stream

        prov, key_info, _, _ = resolve_active_llm()
        self.llm_available = bool(prov and key_info)
        async for chunk in run_agent_search_stream(req):
            event = _agent_event(chunk)
            if event is None:
                continue
            out = self._consume(str(event.get("type") or ""), event.get("data"))
            if out is not None:
                yield out

        if self._synthesizing and self._synth_chars == 0 and self.items:
            fallback = _lexical_answer(self.query, self.items, "deep")
            self.answer_parts.append(fallback)
            for i in range(0, len(fallback), 60):
                yield "delta", {"type": "delta", "text": fallback[i:i + 60]}

    def _consume(self, kind: str, data: Any) -> Optional[Tuple[str, Any]]:
        if kind == "step" and isinstance(data, dict):
            if data.get("stage") == "synthesizing":
                self._synthesizing = True
            self.data_direct = self.data_direct or bool(data.get("data_direct"))
            return "status", {"stage": data.get("stage"), "message": data.get("message")}
        if kind == "dag" and isinstance(data, dict):
            self.plan = [_pick(n, _PLAN_FIELDS) for n in data.get("nodes") or [] if isinstance(n, dict)]
            return "plan", {"nodes": self.plan}
        if kind == "agent_read" and isinstance(data, dict):
            reads = [_pick(r, _READ_FIELDS) for r in data.get("items") or [] if isinstance(r, dict)]
            self.reads.extend(reads)
            return "read", {"items": reads}
        if kind == "agent_decision" and isinstance(data, dict):
            decision = _pick(data, ("round", "need_more", "thought"))
            self.decisions.append(decision)
            return "decision", decision
        if kind == "page" and isinstance(data, dict):
            self.pages = [_pick(p, _PAGE_FIELDS) for p in data.get("pages") or [] if isinstance(p, dict)]
            return "page", {"pages": self.pages}
        if kind == "sources" and isinstance(data, dict):
            self.route = str(data.get("resolved_route") or self.route)
            self.data_direct = self.data_direct or bool(data.get("data_direct"))
            self.items = [UnifiedSearchItem.model_validate(r) for r in data.get("results") or []
                          if isinstance(r, dict)]
            return "sources", {"route": self.route,
                               "results": [i.model_dump() for i in _public_items(self.items)]}
        if kind == "token" and isinstance(data, str):
            # 只在报告阶段过滤告警：数据直出的原文里出现 ⚠️ 不能被误删
            if self._synthesizing and _is_llm_warning(data):
                return None
            self.answer_parts.append(data)
            if self._synthesizing:
                self._synth_chars += len(data)
            return "delta", {"type": "delta", "text": data}
        if kind == "suggestions" and isinstance(data, list):
            self.suggestions = [str(s) for s in data]
            return "suggestions", {"items": self.suggestions}
        return None


def _research_request(payload: PublicResearchRequest, query: str) -> AgentSearchRequest:
    return AgentSearchRequest(
        query=query,
        mode=payload.mode,
        route_group=TOPIC_ROUTE.get(payload.topic, "auto"),
        top_k=payload.max_results,
        scrape_top_n=2,
        max_rounds=payload.max_rounds,
        reading_budget=payload.reading_budget,
        time_range=_normalize_time_range(payload.time_range),  # type: ignore[arg-type]
    )


async def _research_stream(
    request: Request,
    auth: AuthContext,
    run: _ResearchRun,
    req: AgentSearchRequest,
    units: int,
    started: float,
) -> AsyncGenerator[str, None]:
    yield _sse("meta", {
        "request_id": _request_id(request),
        "object": "research.chunk",
        "query": run.query,
        "mode": req.mode,
        "usage": usage_block(units, auth),
    })
    try:
        async for event, data in run.events(req):
            yield _sse(event, data)
    except Exception as exc:  # noqa: BLE001 - 流已开始，只能用事件告知客户端
        yield _sse("error", {"code": "search_failed", "message": f"研究执行失败：{str(exc)[:120]}",
                             "request_id": _request_id(request)})
    yield _sse("done", {
        "request_id": _request_id(request),
        "object": "research.done",
        "route": run.route,
        "result_count": len(run.items),
        "llm_generated": run.llm_generated,
        "data_direct": run.data_direct,
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "usage": usage_block(units, auth),
    })
    yield "data: [DONE]\n\n"


@router.post("/research", response_model=ResearchResponse,
             summary="深度研究 / Agent 自主研究（支持 SSE 流式）")
async def research_endpoint(
    request: Request,
    payload: PublicResearchRequest,
    auth: AuthContext = Depends(require_auth),
) -> Any:
    """与控制台「搜索工作台」同一套研究引擎，按 `mode` 由浅入深：

    - `mode=deep`：把课题拆成 3~4 个子问题并发检索、跨源融合，输出带引用的研究报告；
    - `mode=agentic`：多轮检索 → 精读正文 → 反思证据缺口 → 定向补检，证据充足后撰写报告。

    研究通常需要 10~90 秒，推荐 `stream=true`；非流式调用请把客户端超时设到 180 秒以上。
    权限复用 `answer` scope，需要套餐开通深度研究。
    """
    ensure_scope(auth, "answer")
    query = (payload.query or "").strip()
    if not query:
        raise ApiError("missing_query", param="query")

    units = resolve_research_units(auth, payload.mode, payload.stream)
    started = time.perf_counter()
    req = _research_request(payload, query)
    run = _ResearchRun(query)

    request.state.units = units
    request.state.query = query
    request.state.route = req.route_group

    if payload.stream:
        return StreamingResponse(
            _research_stream(request, auth, run, req, units, started),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "X-Request-Id": _request_id(request),
            },
        )

    try:
        async for _ in run.events(req):
            pass
    except Exception as exc:  # noqa: BLE001
        raise ApiError("search_failed", message=f"研究执行失败：{str(exc)[:120]}")

    public_items = _public_items(run.items)
    request.state.route = run.route
    request.state.result_count = len(public_items)
    body: Dict[str, Any] = {
        "request_id": _request_id(request),
        "object": "research",
        "query": query,
        "mode": payload.mode,
        "route": run.route,
        "answer": run.answer,
        "results": [i.model_dump() for i in public_items],
        "plan": run.plan,
        "reads": run.reads,
        "decisions": run.decisions,
        "pages": run.pages,
        "suggestions": run.suggestions,
        "llm_generated": run.llm_generated,
        "data_direct": run.data_direct,
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "usage": usage_block(units, auth),
    }
    if payload.response_format == "markdown":
        body["markdown"] = run.answer
    return body


# ==================== /v1/chat/completions（OpenAI 兼容） ====================

def _last_user_message(messages: List[Dict[str, Any]]) -> str:
    for message in reversed(messages or []):
        if message.get("role") == "user":
            content = message.get("content")
            if isinstance(content, list):
                parts = [p.get("text", "") for p in content if isinstance(p, dict)]
                return "".join(parts)
            return str(content or "")
    return ""


@router.post("/chat/completions", summary="OpenAI 兼容的联网问答接口")
async def chat_completions_endpoint(
    request: Request,
    body: Dict[str, Any],
    auth: AuthContext = Depends(require_auth),
) -> Any:
    ensure_scope(auth, "chat")
    query = _last_user_message(body.get("messages") or []).strip()
    if not query:
        raise ApiError("missing_query", message="messages 中没有 user 消息", param="messages")

    model_req = str(body.get("model") or "omni-fast")
    mode = "deep" if "deep" in model_req.lower() else "fast"
    units = resolve_chat_units(auth)
    started = time.perf_counter()

    result = await dispatch_unified_search(
        UnifiedSearchRequest(
            query=query,
            route_group="auto",
            top_k=10,
            timeout_ms=15000 if mode == "deep" else 8000,
            enable_rerank=True,
            enable_dedup=True,
            enable_rrf=True,
            scrape_top_n=2 if mode == "deep" else 0,
        ),
        mode_label="openai_compat",
    )
    items = list(result.results)
    cits = _citations(items)

    request.state.units = units
    request.state.route = result.resolved_route
    request.state.query = query
    request.state.result_count = len(items)

    chat_id = f"chatcmpl-{uuid.uuid4().hex[:20]}"
    created = int(time.time())
    usage_meta = usage_block(units, auth)

    if body.get("stream"):
        async def gen() -> AsyncGenerator[str, None]:
            from app.agents.search_agent import resolve_active_llm, stream_llm_text

            prov, key_info, proxy, model_name = resolve_active_llm()
            emitted = 0
            base_chunk = {
                "id": chat_id, "object": "chat.completion.chunk", "created": created,
                "model": model_req,
            }
            yield "data: " + json.dumps({**base_chunk, "choices": [
                {"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}
            ]}, ensure_ascii=False) + "\n\n"

            if prov and key_info:
                messages = [
                    {"role": "system", "content": _ANSWER_SYSTEM},
                    {"role": "user", "content": _answer_prompt(query, items, mode == "deep")},
                ]
                try:
                    async for delta in stream_llm_text(messages, prov, key_info, proxy, model_name):
                        if not delta:
                            continue
                        if _is_llm_warning(delta):
                            break
                        emitted += len(delta)
                        yield "data: " + json.dumps({**base_chunk, "choices": [
                            {"index": 0, "delta": {"content": delta}, "finish_reason": None}
                        ]}, ensure_ascii=False) + "\n\n"
                except Exception:
                    pass
            if emitted == 0:
                fallback = _lexical_answer(query, items, mode)
                for i in range(0, len(fallback), 60):
                    yield "data: " + json.dumps({**base_chunk, "choices": [
                        {"index": 0, "delta": {"content": fallback[i:i + 60]}, "finish_reason": None}
                    ]}, ensure_ascii=False) + "\n\n"
            yield "data: " + json.dumps({**base_chunk, "choices": [
                {"index": 0, "delta": {}, "finish_reason": "stop"}
            ], "x_omnisearch": {
                "citations": [c.model_dump() for c in cits],
                "usage": usage_meta,
                "latency_ms": int((time.perf_counter() - started) * 1000),
            }}, ensure_ascii=False) + "\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    answer = await _llm_answer(query, items, mode)
    if not answer:
        answer = _lexical_answer(query, items, mode)
    latency_ms = int((time.perf_counter() - started) * 1000)

    return {
        "id": chat_id,
        "object": "chat.completion",
        "created": created,
        "model": model_req,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": answer},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": len(query),
            "completion_tokens": len(answer),
            "total_tokens": len(query) + len(answer),
        },
        "citations": [c.model_dump() for c in cits],
        "x_omnisearch": {
            "request_id": _request_id(request),
            "resolved_route": result.resolved_route,
            "sources_count": len(items),
            "latency_ms": latency_ms,
            "usage": usage_meta,
        },
    }


# ==================== 账户与用量 ====================

@router.get("/me", response_model=MeResponse, summary="查询当前密钥的套餐、余额与限流")
async def me_endpoint(auth: AuthContext = Depends(require_auth)) -> Any:
    stats = store.usage_stats(client_id=auth.client_id, days=30, top_queries=0)
    plan = dict(auth.plan)
    return {
        "object": "account",
        "client_id": auth.client_id,
        "name": auth.client.get("name") or "",
        "email": auth.client.get("email") or "",
        "company": auth.client.get("company") or "",
        "status": auth.client.get("status") or "active",
        "billing_mode": auth.billing_mode,
        "plan": {
            "id": plan.get("id"),
            "name": plan.get("name"),
            "price_per_1k_cny": plan.get("price_per_1k_cny"),
            "max_results": plan.get("max_results"),
            "features": plan.get("features") or [],
        },
        "balance_units": auth.balance_units,
        "limits": {
            "rpm": auth.rpm_limit,
            "rpd": auth.rpd_limit,
            "rate_limit_remaining": auth.remaining_rpm,
            "max_results": plan.get("max_results"),
            "allow_rerank": bool(plan.get("allow_rerank")),
            "allow_extract": bool(plan.get("allow_extract")),
            "allow_answer": bool(plan.get("allow_answer")),
            "allow_deep": bool(plan.get("allow_deep")),
        },
        "key": MeKey(
            id=auth.key_id,
            label=auth.key.get("label") or "",
            masked=auth.key.get("masked") or "",
            scopes=auth.scopes,
            rpm_limit=int(auth.key.get("rpm_limit") or 0),
            rpd_limit=int(auth.key.get("rpd_limit") or 0),
            expires_at=float(auth.key.get("expires_at") or 0),
            created_at=float(auth.key.get("created_at") or 0),
        ).model_dump(),
        "usage_this_month": stats["totals"],
    }


@router.get("/usage", response_model=UsageResponse, summary="查询调用用量与账单明细")
async def usage_endpoint(
    days: int = Query(30, ge=1, le=365),
    auth: AuthContext = Depends(require_auth),
) -> Any:
    stats = store.usage_stats(client_id=auth.client_id, days=days, top_queries=5)
    return {
        "object": "usage",
        "client_id": auth.client_id,
        "range": stats["range"],
        "totals": stats["totals"],
        "series": stats["series"],
        "endpoints": stats["endpoints"],
    }


@router.get("/models", response_model=ModelListResponse, summary="可用答案模型列表（OpenAI 兼容）")
async def models_endpoint() -> Any:
    return {
        "object": "list",
        "data": [
            ModelCard(id="omni-fast", description="多源快答：1~3 秒返回带引用的答案", search_depth="basic").model_dump(),
            ModelCard(id="omni-deep", description="深度研究：多轮检索 + 语义重排 + 正文抽取", search_depth="deep").model_dump(),
            ModelCard(id="omni-fast-search", description="omni-fast 的 OpenAI 兼容别名", search_depth="basic").model_dump(),
            ModelCard(id="omni-deep-research", description="omni-deep 的 OpenAI 兼容别名", search_depth="deep").model_dump(),
        ],
    }


# ==================== 自助注册（试用） ====================

@router.post("/signup", response_model=SignupResponse, summary="自助注册领取免费试用密钥")
async def signup_endpoint(request: Request, payload: SignupRequest) -> Any:
    cfg = store.get_platform_setting("signup", {}) or {}
    if not cfg.get("enabled", True):
        raise ApiError("service_unavailable", message="当前未开放自助注册，请联系商务开通")
    plan_id = cfg.get("plan_id", "trial")
    daily_limit = int(cfg.get("daily_limit", 50) or 0)
    email = payload.email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise ApiError("invalid_request", message="邮箱格式不正确", param="email")

    with store._db_lock:
        conn = store.get_conn()
        existing = conn.execute(
            "SELECT id FROM platform_clients WHERE lower(email) = ? AND source = 'self_serve'",
            (email,),
        ).fetchone()
        created_today = conn.execute(
            "SELECT COUNT(*) AS c FROM platform_clients WHERE source = 'self_serve' AND created_at >= ?",
            (store._day_start(),),
        ).fetchone()
        conn.close()
    if existing:
        raise ApiError("invalid_request", message="该邮箱已注册，请使用已签发的密钥或联系商务",
                       param="email")
    if daily_limit > 0 and int(created_today["c"] or 0) >= daily_limit:
        raise ApiError("rate_limit_exceeded",
                       message="今日试用名额已发放完毕，请联系商务开通正式套餐",
                       headers={"Retry-After": "3600"})

    client = store.create_client(
        name=payload.name.strip(),
        email=email,
        company=payload.company.strip(),
        plan_id=plan_id,
        note=payload.use_case[:300],
        source="self_serve",
    )
    raw_key, _ = store.create_api_key(client["id"], label="自助注册试用密钥",
                                      scopes=["search", "extract", "answer", "chat"])
    plan = store.get_plan(client["plan_id"]) or {}
    base = store.get_platform_setting("public_base_url", "") or ""

    return {
        "object": "signup",
        "client_id": client["id"],
        "api_key": raw_key,
        "plan": {
            "id": plan.get("id"),
            "name": plan.get("name"),
            "price_per_1k_cny": plan.get("price_per_1k_cny"),
        },
        "balance_units": int(client.get("balance_units") or 0),
        "quickstart": {
            "search": f'curl -s {base}/v1/search -H "Authorization: Bearer {raw_key}" '
                      f'-H "Content-Type: application/json" '
                      f'-d \'{{"query":"AI 搜索","search_depth":"basic"}}\'',
            "extract": f'curl -s {base}/v1/extract -H "Authorization: Bearer {raw_key}" '
                       f'-H "Content-Type: application/json" -d \'{{"urls":["https://example.com"]}}\'',
            "docs": f"{base}/docs/api",
        },
    }


@router.get("/health", summary="健康检查（免鉴权）")
async def health_endpoint() -> Any:
    settings = get_settings()
    providers = key_pool.list_providers("search")
    ready = [p for p in providers if p["health_status"] == "ready"]
    return {
        "status": "ok",
        "service": "omnisearch-gateway",
        "version": "v1",
        "search_engines_ready": len(ready),
        "search_engines_total": len(providers),
        "cache_enabled": bool(settings.get("enable_cache", True)),
        "time": int(time.time()),
    }
