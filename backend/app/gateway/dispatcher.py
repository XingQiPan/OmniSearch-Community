import asyncio
import json
import math
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.core.database import _db_lock, get_conn, get_settings, mask_key
from app.gateway.fusion import fuse_and_deduplicate
from app.gateway.key_pool import key_pool
from app.gateway.freshness import annotate_time, infer_time_range
from app.gateway.intent_filters import (
    apply_language_bias,
    detect_lang,
    filter_academic_noise,
    filter_low_overlap_zh,
    is_academic_intent,
)
from app.gateway.query_expansion import english_query_variants
from app.providers.adapters import TIME_FILTER_ENGINES, SEARCH_ADAPTER_REGISTRY, make_async_client, read_url_evidence
from app.providers import trending_search as _trending_search_provider  # noqa: F401  (registers SEARCH_ADAPTER_REGISTRY["trending"])
from app.providers import zhihu as _zhihu_provider  # noqa: F401  (registers SEARCH_ADAPTER_REGISTRY["zhihu"])
from app.providers import tencent_news as _tencent_news_provider  # noqa: F401  (registers SEARCH_ADAPTER_REGISTRY["tencent_news"])
from app.schemas import (
    EngineExecutionTrace,
    UnifiedSearchItem,
    UnifiedSearchRequest,
    UnifiedSearchResponse,
)

# Simple in-memory LRU cache: key -> (expire_ts, UnifiedSearchResponse)
_SEARCH_CACHE: Dict[str, Tuple[float, UnifiedSearchResponse]] = {}


def classify_query_route(query: str) -> str:
    """
    Fast rule + keyword hybrid intent router inspired by Scira's auto-router.
    """
    q_low = query.lower()
    if any(k in q_low for k in [
        "paper", "arxiv", "doi", "citation", "journal", "pubmed", "theorem",
        "论文", "文献", "学术", "研究综述", "引用", "期刊", "实验"
    ]):
        return "academic"
    if any(k in q_low for k in [
        "github", "repo", "open source", "typescript", "python", "rust", "golang",
        "fastapi", "react", "docker", "kubernetes", "bug", "报错", "源码", "开源",
        "框架", "代码", "库", "sdk", "api"
    ]):
        return "code"
    if any(k in q_low for k in [
        "reddit", "hackernews", "hn", "twitter", "评价", "吐槽", "体验", "口碑",
        "舆情", "讨论", "网友", "值得买", "对比评测"
    ]):
        return "social"
    if any(k in q_low for k in [
        "短剧", "红果", "霸总", "逆袭", "穿越短剧", "甜宠", "古装短剧", "复仇短剧",
                "抖音视频", "b站视频", "下载视频", "视频下载"
    ]):
        return "entertainment"
    if any(k in q_low for k in [
        "音乐", "歌曲", "歌名", "歌词", "歌手", "点歌", "听歌", "专辑", "翻唱",
        "歌单", "新歌", "热歌", "单曲", "好听", "ost", "bgm", "music"
    ]):
        return "entertainment"
    return "web"


ROUTE_SEMANTIC_DESCRIPTIONS: Dict[str, str] = {
    "web": "通用网页搜索、最新新闻资讯、百科知识、产品官网、行业报告与日常综合问答 (general web search, news, encyclopedia, facts)",
    "academic": "学术论文、科研文献、arXiv预印本、DOI期刊、数学物理计算机理论、医学实验与文献综述 (academic papers, scientific research, arxiv, citations)",
    "code": "编程开发、GitHub开源项目、代码报错排查、软件架构、API文档、SDK框架与技术实现 (software engineering, programming, github repositories, code debugging)",
    "social": "社交媒体舆情、网友真实评价、Reddit/HackerNews/B站社区讨论、产品口碑吐槽与避坑体验 (social media discussions, reddit, hackernews, user reviews, community opinions)",
    "entertainment": "娱乐内容检索：影视、综艺、音乐与短视频相关资讯",
}


def _cosine_sim(v1: List[float], v2: List[float]) -> float:
    dot = sum(a * b for a, b in zip(v1, v2))
    n1 = sum(a * a for a in v1) ** 0.5
    n2 = sum(b * b for b in v2) ** 0.5
    if n1 == 0 or n2 == 0:
        return 0.0
    return dot / (n1 * n2)


async def classify_query_route_jev(query: str, settings: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """
    Jev (TypeSafe AI System One Decision Model) Router.
    Sends `state` + typed `questions` (`choice` / `noul`) to `https://api.typesafe.ai/v1/systemone`
    (or compatible Jev / Laya / OpenAI Decisions / OpenRouter endpoint), returning calibrated
    probability distributions (`probabilities`) and `confidence` without autoregressive text generation.
    Falls back to `classify_query_route(query)` if API key is missing, confidence is below threshold, or request fails.
    """
    api_url = (settings.get("jev_api_url") or "https://api.typesafe.ai/v1/systemone").strip()
    if "jina.ai/v1/embeddings" in api_url:
        api_url = "https://api.typesafe.ai/v1/systemone"
    api_key = (settings.get("jev_api_key") or "").strip()
    model = (settings.get("jev_model") or "jev-1.13.0").strip()
    if model == "jina-embeddings-v3":
        model = "jev-1.13.0"
    conf_threshold = float(settings.get("jev_confidence_threshold") or 0.45)
    timeout_sec = max(1.5, float(settings.get("jev_timeout_ms") or 4000) / 1000.0)
    proxy = settings.get("global_proxy") if settings.get("enable_global_proxy", True) else None

    if not api_key:
        fb = classify_query_route(query)
        return fb, {"engine": "jev_fallback_rule", "reason": "未配置 Jev (TypeSafe) API Key，已由规则路由兜底"}

    headers: Dict[str, str] = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    payload = {
        "model": model,
        "state": query,
        "questions": {
            "route": {
                "type": "choice",
                "instructions": "Select the most appropriate search engine route group for this user query.",
                "criteria": ROUTE_SEMANTIC_DESCRIPTIONS,
            },
            "needs_deep_read": {
                "type": "noul",
                "instructions": "Does this query require multi-source deep reading and verification?",
            },
        },
    }

    t0 = time.perf_counter()
    try:
        async with make_async_client(proxy, timeout_sec=timeout_sec) as client:
            resp = await client.post(api_url, headers=headers, json=payload)
            latency_ms = int((time.perf_counter() - t0) * 1000)
            if resp.status_code == 200:
                data = resp.json()
                # Parse standard TypeSafe System One response (`answers.route` or `choices.route`)
                answers = data.get("answers") or data.get("choices") or {}
                route_ans = answers.get("route") if isinstance(answers, dict) else None
                if isinstance(route_ans, dict):
                    probs: Dict[str, float] = route_ans.get("probabilities") or {}
                    choice_val = route_ans.get("choice") or (max(probs, key=probs.get) if probs else "web")
                    confidence = float(route_ans.get("confidence", max(probs.values()) if probs else 1.0))
                    noul_ans = (data.get("answers") or data.get("nouls") or {}).get("needs_deep_read", {})
                    deep_prob = noul_ans.get("noul") if isinstance(noul_ans, dict) else None

                    if confidence < conf_threshold:
                        fb = classify_query_route(query)
                        return fb, {
                            "engine": "jev_confidence_gated",
                            "model": data.get("model", model),
                            "latency_ms": latency_ms,
                            "choice": choice_val,
                            "confidence": round(confidence, 4),
                            "probabilities": probs,
                            "reason": f"Jev 置信度 {confidence:.2f} < 门控阈值 {conf_threshold:.2f}，触发门控回退",
                        }

                    chosen = choice_val if choice_val in ROUTE_SEMANTIC_DESCRIPTIONS else "web"
                    return chosen, {
                        "engine": "jev_systemone",
                        "model": data.get("model", model),
                        "latency_ms": latency_ms,
                        "choice": chosen,
                        "confidence": round(confidence, 4),
                        "probabilities": probs,
                        "needs_deep_read_prob": round(float(deep_prob), 4) if deep_prob is not None else None,
                        "usage": data.get("usage"),
                    }

                # Compatible with simplified custom Jev / Laya decision proxy returning {"route": "...", "probabilities": {...}}
                if isinstance(data, dict) and data.get("route") in ROUTE_SEMANTIC_DESCRIPTIONS:
                    return data["route"], {
                        "engine": "jev_systemone",
                        "model": model,
                        "latency_ms": latency_ms,
                        "confidence": data.get("confidence", 1.0),
                        "probabilities": data.get("probabilities", {}),
                    }

            raise RuntimeError(f"Jev API HTTP {resp.status_code}: {resp.text[:180]}")
    except Exception as e:
        fb = classify_query_route(query)
        return fb, {"engine": "jev_fallback_rule", "model": model, "error": str(e)[:180]}


async def classify_query_route_ai(query: str, settings: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """
    AI LLM Router (inspired by Scira's `routeWithAutoRouter`).
    Uses the user-selected LLM provider & model to classify the query into one of the configured route groups.
    Falls back to `classify_query_route(query)` if no LLM key is configured or on timeout.
    """
    prov_id = settings.get("ai_router_provider") or settings.get("default_llm_provider") or "siliconflow"
    preferred_model = (settings.get("ai_router_model") or "").strip()
    timeout_sec = max(2.0, float(settings.get("ai_router_timeout_ms") or 6000) / 1000.0)

    # Acquire credentials from chosen provider, or fallback to any ready LLM provider
    prov, key_info, proxy = key_pool.acquire_credentials(prov_id)
    if not (prov and key_info and key_info.get("api_key")):
        for p in key_pool.list_providers("llm"):
            cand_p, cand_k, cand_px = key_pool.acquire_credentials(p["id"])
            if cand_p and cand_p.get("enabled") and cand_k and cand_k.get("api_key"):
                prov, key_info, proxy = cand_p, cand_k, cand_px
                prov_id = p["id"]
                break

    if not (prov and key_info and key_info.get("api_key")):
        fb = classify_query_route(query)
        return fb, {"engine": "ai_fallback_rule", "reason": f"大模型渠道 [{prov_id}] 尚未配置 API Key，已由规则路由兜底"}

    model = preferred_model or prov.get("default_model") or "deepseek-chat"
    base_url = (key_info.get("base_url") or prov.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    endpoint = f"{base_url}/chat/completions"

    routes_desc = "\n".join(f'- "{k}": {v}' for k, v in ROUTE_SEMANTIC_DESCRIPTIONS.items())
    prompt = (
        "你是聚合搜索引擎的智能意图路由器。请根据用户查询判断最匹配的路由分组名称。\n"
        f"可选路由分组：\n{routes_desc}\n\n"
        f"用户查询：{query}\n\n"
        '请只返回一个 JSON 对象，格式严格为：{"route": "web|academic|code|social", "reason": "简短原因"}'
    )

    t0 = time.perf_counter()
    try:
        async with make_async_client(proxy, timeout_sec=timeout_sec) as client:
            resp = await client.post(
                endpoint,
                headers={"Authorization": f"Bearer {key_info['api_key']}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.0,
                    "max_tokens": 90,
                },
            )
            latency_ms = int((time.perf_counter() - t0) * 1000)
            if resp.status_code == 200:
                key_pool.record_execution(prov_id, key_info["id"], True, latency_ms)
                content = resp.json()["choices"][0]["message"]["content"]
                m = re.search(r"\{[\s\S]*\}", content)
                if m:
                    parsed = json.loads(m.group(0))
                    r_name = str(parsed.get("route", "")).strip().lower()
                    if r_name in ROUTE_SEMANTIC_DESCRIPTIONS:
                        return r_name, {
                            "engine": "ai_llm",
                            "provider": prov_id,
                            "model": model,
                            "latency_ms": latency_ms,
                            "reason": parsed.get("reason", ""),
                        }
                # Fallback keyword scan in LLM output
                for rk in ROUTE_SEMANTIC_DESCRIPTIONS:
                    if rk in content.lower():
                        return rk, {"engine": "ai_llm", "provider": prov_id, "model": model, "latency_ms": latency_ms}
            else:
                key_pool.record_execution(prov_id, key_info["id"], False, latency_ms, f"HTTP {resp.status_code}")
                raise RuntimeError(f"LLM HTTP {resp.status_code}: {resp.text[:160]}")
    except Exception as e:
        fb = classify_query_route(query)
        return fb, {"engine": "ai_fallback_rule", "provider": prov_id, "model": model, "error": str(e)[:180]}

    fb = classify_query_route(query)
    return fb, {"engine": "ai_fallback_rule"}


async def resolve_smart_route(query: str, requested_route: str = "auto") -> Tuple[str, Dict[str, Any]]:
    """
    Unified entry point for route resolution:
    - requested_route in ('web', 'academic', 'code', 'social') -> explicit route
    - requested_route == 'jev' -> force Jev (TypeSafe System One) decision-model router
    - requested_route == 'ai' -> force AI LLM router
    - requested_route == 'rule' -> force fast keyword rule router
    - requested_route == 'auto' -> uses configured `settings['router_mode']` ('rule' | 'jev' | 'ai')
    """
    settings = get_settings()
    mode = requested_route
    if requested_route == "auto":
        mode = settings.get("router_mode", "rule")

    if mode == "jev":
        return await classify_query_route_jev(query, settings)
    if mode == "ai":
        return await classify_query_route_ai(query, settings)
    if mode == "rule" or requested_route == "auto":
        r = classify_query_route(query)
        return r, {"engine": "rule", "latency_ms": 0}
    return requested_route, {"engine": "explicit", "latency_ms": 0}


def get_route_group_config(group_id: str) -> Dict[str, Any]:
    with _db_lock:
        conn = get_conn()
        row = conn.execute("SELECT * FROM route_groups WHERE id = ?", (group_id,)).fetchone()
        if not row:
            row = conn.execute("SELECT * FROM route_groups WHERE id = 'web'").fetchone()
        conn.close()
    if not row:
        return {
            "id": "web",
            "engines": ["bing_web", "duckduckgo", "wikipedia"],
            "fallback_engines": ["bing_web"],
            "timeout_ms": 7000,
            "top_k": 20,
        }
    d = dict(row)
    d["engines"] = json.loads(d.get("engines_json") or "[]")
    d["fallback_engines"] = json.loads(d.get("fallback_engines_json") or "[]")
    return d


async def apply_semantic_rerank(
    query: str, items: List[UnifiedSearchItem], reranker_provider_id: Optional[str] = None
) -> List[UnifiedSearchItem]:
    """
    Applies API-based semantic reranking (Jina / SiliconFlow BGE) if configured with a valid key,
    and blends with lexical overlap + RRF score.
    """
    if not items:
        return items

    settings = get_settings()
    candidates = []
    if reranker_provider_id:
        candidates.append(reranker_provider_id)
    default_prov = settings.get("default_reranker_provider", "jina_reranker")
    if default_prov not in candidates:
        candidates.append(default_prov)
    for p in key_pool.list_providers("reranker"):
        if p["id"] not in candidates:
            candidates.append(p["id"])

    prov, key_info, proxy, prov_id = None, None, None, default_prov
    for cid in candidates:
        p, k, px = key_pool.acquire_credentials(cid)
        if p and p.get("enabled") and k and k.get("api_key"):
            prov, key_info, proxy, prov_id = p, k, px, cid
            break

    # Always compute lightweight lexical relevance boost so even without API key rerank improves quality
    # 说明：这里必须用"有界乘法微调"而非加法。此前用加法常量（最高 +0.045）会超过 RRF 分数
    # 本身（0.02~0.04），导致词法命中完全覆盖 RRF 排序；且 re.split(r"\W+") 不会切分中文，
    # 整串命中即吃满加成。改为按相关性系数 r∈[0,1] 做最多 ±30% 的乘法修正。
    q_low = query.lower()
    q_tokens = [t for t in re.split(r"\W+", q_low) if len(t) >= 2]
    cjk_q = re.sub(r"[^\u4e00-\u9fff]", "", q_low)
    q_bigrams = {cjk_q[i:i + 2] for i in range(len(cjk_q) - 1)} if len(cjk_q) >= 2 else set()

    items = [item.model_copy(deep=True) for item in items]
    for item in items:
        # Preserve fusion input across repeated reranks; never compound boosts.
        base_score = float(item.metadata.setdefault('rerank_base_score', item.final_score))
        item.metadata.pop('semantic_relevance', None)
        item.metadata['rerank_status'] = 'lexical_only'
        text_low = f"{item.title} {item.snippet}".lower()
        relevance = 0.0
        if q_tokens:
            relevance = sum(1 for tok in q_tokens if tok in text_low) / len(q_tokens)
        if q_bigrams:
            cjk_title = re.sub(r"[^\u4e00-\u9fff]", "", item.title.lower())
            title_bigrams = {cjk_title[i:i + 2] for i in range(len(cjk_title) - 1)}
            if title_bigrams:
                relevance = max(relevance, len(q_bigrams & title_bigrams) / len(q_bigrams))
        if q_low and q_low in item.title.lower():
            relevance = max(relevance, 1.0)
        item.rerank_score = round(base_score * (1.0 + 0.3 * relevance), 5)
        item.final_score = item.rerank_score

    # Select candidates deterministically after lexical scoring.
    items.sort(key=lambda x: (-x.final_score, x.normalized_url or x.url, x.source_engine))
    # If external Reranker API key is configured, call remote cross-encoder
    if prov and prov.get("enabled") and key_info and key_info.get("api_key"):
        endpoint = key_info.get("base_url") or prov.get("base_url") or "https://api.jina.ai/v1/rerank"
        if endpoint.endswith("/v1"):
            endpoint = endpoint + "/rerank"
        model = prov.get("default_model") or "jina-reranker-v2-base-multilingual"
        docs = [f"{it.title}\n{it.snippet}"[:600] for it in items[:25]]
        t0 = time.perf_counter()
        try:
            async with make_async_client(proxy, timeout_sec=4.5) as client:
                resp = await client.post(
                    endpoint,
                    headers={"Authorization": f"Bearer {key_info['api_key']}", "Content-Type": "application/json"},
                    json={"model": model, "query": query, "documents": docs, "top_n": len(docs)},
                )
                latency = int((time.perf_counter() - t0) * 1000)
                if resp.status_code == 200:
                    data = resp.json()
                    scores = {}
                    rows = data.get('results')
                    if not isinstance(rows, list):
                        raise ValueError('Reranker results must be a list')
                    for r in rows:
                        idx = r.get('index')
                        raw_score = r.get('relevance_score')
                        if type(idx) is not int or not 0 <= idx < len(docs) or idx in scores:
                            raise ValueError('Reranker index invalid or duplicated')
                        if type(raw_score) not in (int, float) or not math.isfinite(raw_score) or not 0 <= raw_score <= 1:
                            raise ValueError('Reranker relevance_score must be finite and within [0,1]')
                        scores[idx] = float(raw_score)
                    # Validate the entire response before applying anything. Missing candidates
                    # keep lexical scores; all scores stay on the fusion scale, including tail items.
                    for idx, rel_score in scores.items():
                        item = items[idx]
                        item.metadata['semantic_relevance'] = rel_score
                        item.metadata['rerank_status'] = 'semantic'
                        item.final_score = round(item.final_score * (0.7 + 0.6 * rel_score), 5)
                        item.rerank_score = item.final_score
                    key_pool.record_execution(prov_id, key_info["id"], True, latency)
                else:
                    key_pool.record_execution(prov_id, key_info["id"], False, latency, f"HTTP {resp.status_code}")
        except Exception as e:
            latency = int((time.perf_counter() - t0) * 1000)
            key_pool.record_execution(prov_id, key_info["id"], False, latency, str(e))

    items.sort(key=lambda x: (-x.final_score, x.normalized_url or x.url, x.source_engine))
    return items


async def execute_single_engine(
    engine_id: str,
    query: str,
    max_results: int,
    timeout_sec: float,
    bypass_circuit: bool = False,
    time_range: Optional[str] = None,
) -> Tuple[EngineExecutionTrace, List[UnifiedSearchItem]]:
    prov, key_info, proxy = key_pool.acquire_credentials(engine_id)
    if not prov:
        return (
            EngineExecutionTrace(
                engine_id=engine_id,
                engine_name=engine_id,
                status="skipped",
                error_message="Provider not found",
            ),
            [],
        )

    engine_name = prov["name"]
    now = time.time()

    if not bypass_circuit and not prov.get("enabled"):
        return (
            EngineExecutionTrace(
                engine_id=engine_id,
                engine_name=engine_name,
                status="skipped",
                error_message="渠道已禁用",
            ),
            [],
        )

    if not bypass_circuit and prov.get("circuit_open_until", 0) > now:
        remain = int(prov["circuit_open_until"] - now)
        return (
            EngineExecutionTrace(
                engine_id=engine_id,
                engine_name=engine_name,
                status="circuit_open",
                error_message=f"熔断保护中 ({remain}s 后自动恢复)",
            ),
            [],
        )

    if prov.get("requires_key") and (not key_info or not key_info.get("api_key")):
        return (
            EngineExecutionTrace(
                engine_id=engine_id,
                engine_name=engine_name,
                status="skipped",
                error_message="未配置可用 API Key（请在密钥池添加）",
            ),
            [],
        )

    adapter_fn = SEARCH_ADAPTER_REGISTRY.get(engine_id)
    if not adapter_fn:
        return (
            EngineExecutionTrace(
                engine_id=engine_id,
                engine_name=engine_name,
                status="skipped",
                error_message="未找到引擎适配器",
            ),
            [],
        )

    api_key_str = key_info["api_key"] if key_info else None
    key_id = key_info["id"] if key_info else None
    masked = mask_key(api_key_str) if api_key_str else "免密直连"
    base_url = (key_info.get("base_url") if key_info and key_info.get("base_url") else prov.get("base_url")) or None
    effective_timeout = min(timeout_sec, (prov.get("timeout_ms") or 7000) / 1000.0)
    t0 = time.perf_counter()
    try:
        items = await asyncio.wait_for(
            adapter_fn(
                query=query,
                max_results=max_results,
                proxy=proxy,
                timeout_sec=effective_timeout,
                api_key=api_key_str,
                base_url=base_url,
                time_range=time_range,
            ),
            timeout=effective_timeout + 0.5,
        )
        for item in items:
            annotate_time(item, time_range)
            item.metadata['time_filter_support'] = 'native_requested' if engine_id in TIME_FILTER_ENGINES and time_range else 'not_applied'
        latency_ms = int((time.perf_counter() - t0) * 1000)
        key_pool.record_execution(engine_id, key_id, True, latency_ms)
        return (
            EngineExecutionTrace(
                engine_id=engine_id,
                engine_name=engine_name,
                status="success",
                latency_ms=latency_ms,
                result_count=len(items),
                used_key_masked=masked,
                used_proxy=bool(proxy),
            ),
            items,
        )
    except asyncio.TimeoutError:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        key_pool.record_execution(engine_id, key_id, False, latency_ms, "Timeout")
        return (
            EngineExecutionTrace(
                engine_id=engine_id,
                engine_name=engine_name,
                status="timeout",
                latency_ms=latency_ms,
                used_key_masked=masked,
                used_proxy=bool(proxy),
                error_message=f"请求超时 (>{effective_timeout:.1f}s)",
            ),
            [],
        )
    except Exception as e:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        err_str = str(e)
        key_pool.record_execution(engine_id, key_id, False, latency_ms, err_str)
        return (
            EngineExecutionTrace(
                engine_id=engine_id,
                engine_name=engine_name,
                status="error",
                latency_ms=latency_ms,
                used_key_masked=masked,
                used_proxy=bool(proxy),
                error_message=err_str[:220],
            ),
            [],
        )


async def dispatch_unified_search(
    req: UnifiedSearchRequest, mode_label: str = "search"
) -> UnifiedSearchResponse:
    t_start = time.perf_counter()
    settings = get_settings()
    trace_id = f"tr-{uuid.uuid4().hex[:12]}"

    # 1. Resolve route group & candidate engines
    requested_route = req.route_group or "auto"
    if req.engines and len(req.engines) > 0:
        resolved_route = "custom"
        candidate_engines = list(dict.fromkeys(req.engines))
        fallback_engines = ["bing_web", "duckduckgo", "wikipedia"]
        group_cfg = {"timeout_ms": req.timeout_ms, "top_k": req.top_k}
    else:
        if requested_route in ("auto", "rule", "jev", "ai"):
            resolved_route, _ = await resolve_smart_route(req.query, requested_route)
        else:
            resolved_route = requested_route
        group_cfg = get_route_group_config(resolved_route)
        candidate_engines = group_cfg.get("engines", ["bing_web", "duckduckgo", "wikipedia"])
        fallback_engines = group_cfg.get("fallback_engines", ["bing_web", "wikipedia"])

    # Explicit request options override route defaults; omitted options inherit them.
    overrides = {}
    for field in ("timeout_ms", "top_k", "enable_rerank", "scrape_top_n"):
        if field not in req.model_fields_set and field in group_cfg:
            overrides[field] = group_cfg[field]
    req = req.model_copy(update=overrides)
    req = req.model_copy(update={'time_range': infer_time_range(req.query, req.time_range)})

    # Filter out engines that require an API key when no key is configured, unless explicitly requested
    active_engines: List[str] = []
    skipped_traces: List[EngineExecutionTrace] = []
    all_provs = {p["id"]: p for p in key_pool.list_providers("search")}

    for eid in candidate_engines:
        p = all_provs.get(eid)
        if not p:
            continue
        if req.engines:
            # Explicit selection in Playground/Custom mode: run and report exact status
            active_engines.append(eid)
        else:
            if p["health_status"] == "ready":
                active_engines.append(eid)

    if not active_engines:
        for fb in fallback_engines:
            if fb in all_provs and all_provs[fb]["health_status"] == "ready":
                active_engines.append(fb)
        if not active_engines:
            active_engines = ["bing_web", "wikipedia"]

    # Check cache
    cache_key = json.dumps({
        "request": req.model_dump(), "route": resolved_route, "group": group_cfg,
        "engines": active_engines, "settings": settings,
        "providers": {eid: {field: all_provs[eid].get(field) for field in
                      ("weight", "base_url", "enabled", "timeout_ms", "health_status")}
                      for eid in active_engines if eid in all_provs},
    }, sort_keys=True, ensure_ascii=False)
    now = time.time()
    cache_enabled = settings.get("enable_cache", True) and req.use_cache is not False
    if cache_enabled and not req.engines:
        cached = _SEARCH_CACHE.get(cache_key)
        if cached and cached[0] > now:
            cached_resp = cached[1].model_copy(deep=True)
            cached_resp.trace_id = trace_id
            cached_resp.cache_hit = True
            cached_resp.total_latency_ms = int((time.perf_counter() - t_start) * 1000)
            _save_trace_log(cached_resp, mode_label)
            return cached_resp

    # 2. Fan-out concurrent execution
    timeout_sec = max(2.0, (req.timeout_ms or group_cfg.get("timeout_ms", 7500)) / 1000.0)
    per_engine_max = min(max(req.top_k, 10), 40)

    # 中文查询的英文扩展与主检索并发启动，避免额外等待
    translation_task = (
        asyncio.create_task(english_query_variants(req.query))
        if detect_lang(req.query) in ("zh", "mixed") and not req.engines
        else None
    )

    tasks = [
        execute_single_engine(
            engine_id=eid,
            query=req.query,
            max_results=per_engine_max,
            timeout_sec=timeout_sec,
            bypass_circuit=bool(req.engines),
            time_range=req.time_range,
        )
        for eid in active_engines
    ]
    exec_outputs = await asyncio.gather(*tasks)

    engine_traces: List[EngineExecutionTrace] = list(skipped_traces)
    per_engine_results: Dict[str, List[UnifiedSearchItem]] = {}
    engine_weights: Dict[str, float] = {}
    total_raw = 0

    for trace, items in exec_outputs:
        engine_traces.append(trace)
        per_engine_results[trace.engine_id] = items
        total_raw += len(items)
        p_info = all_provs.get(trace.engine_id)
        engine_weights[trace.engine_id] = float(p_info["weight"]) if p_info else 1.0

    # 3. Automatic fallback if all primary engines returned 0 results
    if total_raw == 0 and not req.engines:
        untried_fallbacks = [fb for fb in fallback_engines if fb not in active_engines]
        if untried_fallbacks:
            fb_tasks = [
                execute_single_engine(fb, req.query, per_engine_max, timeout_sec=6.0, time_range=req.time_range)
                for fb in untried_fallbacks
            ]
            fb_outputs = await asyncio.gather(*fb_tasks)
            for trace, items in fb_outputs:
                engine_traces.append(trace)
                per_engine_results[trace.engine_id] = items
                total_raw += len(items)
                engine_weights[trace.engine_id] = 1.0

    # 3.5 纯中文查询补检一版英文检索词：只打海外引擎，失败静默跳过
    if translation_task is not None:
        try:
            variants = await asyncio.wait_for(asyncio.shield(translation_task), timeout=2.0)
        except Exception:
            translation_task.cancel()
            variants = []
        extra_engines = [eid for eid in ("bing_web", "duckduckgo", "github") if eid in active_engines][:2]
        if variants and extra_engines:
            extra_tasks = [
                execute_single_engine(
                    eid, variants[0], 6, timeout_sec=min(timeout_sec, 6.0), time_range=req.time_range
                )
                for eid in extra_engines
            ]
            for trace, items in await asyncio.gather(*extra_tasks):
                bucket = per_engine_results.get(trace.engine_id)
                if bucket is None or not items:
                    continue
                for item in items:
                    if trace.engine_id in item.positions:
                        item.positions[trace.engine_id] += 5
                    item.metadata["query_variant"] = "en"
                    item.metadata["translated_query"] = variants[0]
                bucket.extend(items)
                total_raw += len(items)
                for existing_trace in engine_traces:
                    if existing_trace.engine_id == trace.engine_id:
                        existing_trace.result_count = len(bucket)

    # 3.6 学术噪音过滤：非学术意图时剔除 doi.org / Crossref 等论文站点
    if not is_academic_intent(req.query, resolved_route):
        for engine_id, items in list(per_engine_results.items()):
            kept = filter_academic_noise(items, req.query, resolved_route)
            if len(kept) != len(items):
                per_engine_results[engine_id] = kept
                total_raw -= len(items) - len(kept)
                for trace in engine_traces:
                    if trace.engine_id == engine_id:
                        trace.result_count = len(kept)

    # 3.7 中文词面覆盖过滤：剔除只命中单字的字典页等无关结果（有安全回退）
    for engine_id, items in list(per_engine_results.items()):
        kept = filter_low_overlap_zh(items, req.query)
        if len(kept) != len(items):
            per_engine_results[engine_id] = kept
            total_raw -= len(items) - len(kept)
            for trace in engine_traces:
                if trace.engine_id == engine_id:
                    trace.result_count = len(kept)

    # 4. Fuse & Deduplicate (RRF + Cross-Engine Overlap Boost)
    merged_results, cross_hits = fuse_and_deduplicate(
        per_engine_results=per_engine_results,
        engine_weights=engine_weights,
        enable_dedup=req.enable_dedup,
        enable_rrf=req.enable_rrf,
        include_domains=req.include_domains,
        exclude_domains=req.exclude_domains,
    )

    # 5. Optional Rerank
    if req.enable_rerank and merged_results:
        merged_results = await apply_semantic_rerank(req.query, merged_results, req.reranker_provider)

    if req.time_range:
        # Bounded freshness adjustment, never replacing relevance with date-only ordering.
        for item in merged_results:
            annotate_time(item, req.time_range)
            factor = {'recent': 1.15, 'stale': 0.85}.get(item.metadata['freshness'], 1.0)
            item.final_score = round(item.final_score * factor, 5)
        merged_results.sort(key=lambda item: item.final_score, reverse=True)

    # 5.1 语言偏置：英文/中英混合查询时对中文内容站做有界降权
    if apply_language_bias(merged_results, req.query):
        merged_results.sort(key=lambda item: (-item.final_score, item.normalized_url or item.url, item.source_engine))

    final_results = merged_results[: req.top_k]

    # 6. Optional Full-Text Markdown Scrape for Top N
    if req.scrape_top_n and req.scrape_top_n > 0 and final_results:
        _, jina_key_info, jina_proxy = key_pool.acquire_credentials("jina_reader")
        jina_key = jina_key_info["api_key"] if jina_key_info else None
        scrape_targets = final_results[: min(req.scrape_top_n, 4)]
        scrape_tasks = [
            read_url_evidence(item.url, proxy=jina_proxy, api_key=jina_key, timeout_sec=6.5)
            for item in scrape_targets
        ]
        scraped_texts = await asyncio.gather(*scrape_tasks)
        for item, evidence in zip(scrape_targets, scraped_texts):
            text = evidence.pop('text', '')
            published = evidence.pop('published_at', None)
            if published:
                item.published_at = published
            item.metadata.update(evidence)
            if text:
                item.content = text
            else:
                item.metadata['read_status'] = 'summary_only' if item.snippet else 'failed'
            annotate_time(item, req.time_range)

    total_latency_ms = int((time.perf_counter() - t_start) * 1000)

    response = UnifiedSearchResponse(
        trace_id=trace_id,
        query=req.query,
        rewritten_queries=[req.query],
        resolved_route=resolved_route,
        total_latency_ms=total_latency_ms,
        total_raw_results=total_raw,
        total_merged_results=len(final_results),
        cross_engine_hits=cross_hits,
        cache_hit=False,
        engine_traces=engine_traces,
        results=final_results,
        per_engine_results=per_engine_results,
    )

    if cache_enabled and final_results and not req.engines:
        ttl = int(settings.get("cache_ttl_seconds", 1800))
        if req.time_range:
            ttl = min(ttl, 120 if req.time_range == 'day' else 300)
        _SEARCH_CACHE[cache_key] = (now + ttl, response)

    _save_trace_log(response, mode_label)
    return response


def _save_trace_log(resp: UnifiedSearchResponse, mode_label: str) -> None:
    try:
        traces_data = [t.model_dump() for t in resp.engine_traces]
        top_urls = [{"title": r.title, "url": r.url, "engines": r.engines, "score": r.final_score} for r in resp.results[:5]]
        with _db_lock:
            conn = get_conn()
            conn.execute("""
            INSERT INTO search_traces (
                trace_id, query, mode, resolved_route, total_latency_ms,
                total_raw_results, total_merged_results, cross_engine_hits,
                cache_hit, engine_traces_json, top_urls_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                resp.trace_id,
                resp.query,
                mode_label,
                resp.resolved_route,
                resp.total_latency_ms,
                resp.total_raw_results,
                resp.total_merged_results,
                resp.cross_engine_hits,
                1 if resp.cache_hit else 0,
                json.dumps(traces_data, ensure_ascii=False),
                json.dumps(top_urls, ensure_ascii=False),
                time.time(),
            ))
            conn.commit()
            conn.close()
    except Exception:
        pass
