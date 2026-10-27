import asyncio
import json
import re
import secrets
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, StreamingResponse, Response

from app.agents.search_agent import generate_extractive_synthesis, resolve_active_llm, run_agent_search_stream
from app.core.database import (
    _db_lock,
    get_conn,
    get_settings,
    init_db,
    mask_key,
    update_settings,
)
from app.gateway.dispatcher import dispatch_unified_search, execute_single_engine, resolve_smart_route
from app.gateway.key_pool import key_pool
from app.platform.errors import register_error_handlers
from app.platform.middleware import api_gateway_middleware
from app.platform.research_jobs import (
    cancel_research_job,
    create_research_job,
    get_research_job,
    list_research_jobs,
    recover_research_jobs,
    stream_research_job,
)
from app.platform.router_admin import router as platform_admin_router
from app.platform.router_public import router as public_api_router
from app.platform.store import init_platform_db
from app.providers.adapters import make_async_client, scrape_url_markdown
from app.providers.webpage import is_http_url, read_webpages
from app.skill_package import build_skill_zip, list_skill_files, skill_manifest
from app.providers.trending import BOARD_META, fetch_trending_board, get_trending_catalog
from app.providers import trending_search as trending_search_provider  # noqa: F401  (registers SEARCH_ADAPTER_REGISTRY["trending"])
from app.schemas import (
    AgentSearchRequest,
    ApiKeyCreate,
    GatewaySettingsUpdate,
    ProviderCreate,
    ProviderUpdate,
    ResearchJobCreate,
    RouteGroupUpdate,
    UnifiedSearchRequest,
    UnifiedSearchResponse,
    WebpageReadRequest,
    WebpageReadResponse,
)

app = FastAPI(
    title="OmniSearch 聚合大搜索引擎 & 总网关控制台 API",
    version="2.1.0",
    description=(
        "多源聚合搜索与 AI 路由总网关：多引擎并发扇出、跨源去重融合、带引用的答案。\n\n"
        "**对外开放的付费搜索 API（/v1/*）** 采用行业标准设计：`Authorization: Bearer sk-omni-xxx`、"
        "统一响应信封、`usage.units` 计量、`X-RateLimit-*` 限流头与结构化错误码，支持按千次计费售卖。"
    ),
    openapi_tags=[
        {"name": "开放 API v1", "description": "对外售卖的搜索服务接口：搜索 / 抽取 / 答案 / OpenAI 兼容"},
        {"name": "开放 API 平台管理", "description": "套餐、客户、密钥、用量与营收管理"},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(api_gateway_middleware)
register_error_handlers(app)
app.include_router(public_api_router)
app.include_router(platform_admin_router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    init_platform_db()
    recover_research_jobs()


@app.get("/openapi-public.json", include_in_schema=False)
def public_openapi_schema() -> Dict[str, Any]:
    """只暴露 /v1/* 的 OpenAPI，用于对外开发者文档。"""
    schema = app.openapi()
    schema["paths"] = {k: v for k, v in schema["paths"].items() if k.startswith("/v1")}
    schema["info"]["title"] = "OmniSearch 开放 API v1（搜索服务）"
    schema["info"]["description"] = (
        "按千次计费的聚合搜索服务：搜索 / 正文抽取 / 带引用的答案 / OpenAI 兼容接口。"
        "鉴权方式 `Authorization: Bearer sk-omni-xxx`。"
    )
    return schema


@app.get("/docs/api", include_in_schema=False)
def public_docs_page() -> HTMLResponse:
    """面向客户的开发者文档页（只含 /v1/* 接口）。"""
    return get_swagger_ui_html(
        openapi_url="/openapi-public.json",
        title="OmniSearch 开放 API 文档",
    )


# ==================== 1. 控制台大盘与监控统计 ====================
@app.get("/api/admin/dashboard")
def get_dashboard_overview() -> Dict[str, Any]:
    providers = key_pool.list_providers()
    search_provs = [p for p in providers if p["provider_type"] == "search"]
    ready_search = [p for p in search_provs if p["health_status"] == "ready"]
    circuit_open = [p for p in providers if p["is_circuit_open"]]

    with _db_lock:
        conn = get_conn()
        trace_stats = conn.execute("""
            SELECT
                COUNT(*) as total_searches,
                COALESCE(AVG(total_latency_ms), 0) as avg_latency,
                COALESCE(SUM(total_raw_results), 0) as sum_raw,
                COALESCE(SUM(total_merged_results), 0) as sum_merged,
                COALESCE(SUM(cross_engine_hits), 0) as sum_cross,
                COALESCE(SUM(cache_hit), 0) as sum_cache
            FROM search_traces
        """).fetchone()

        route_dist = conn.execute("""
            SELECT resolved_route, COUNT(*) as cnt
            FROM search_traces
            GROUP BY resolved_route
            ORDER BY cnt DESC
        """).fetchall()

        recent_traces = conn.execute("""
            SELECT trace_id, query, mode, resolved_route, total_latency_ms,
                   total_raw_results, total_merged_results, cross_engine_hits,
                   cache_hit, created_at
            FROM search_traces
            ORDER BY created_at DESC
            LIMIT 12
        """).fetchall()
        conn.close()

    total_api_calls = sum(p["total_calls"] for p in providers)
    total_api_success = sum(p["success_calls"] for p in providers)
    success_rate = round((total_api_success / total_api_calls * 100), 1) if total_api_calls > 0 else 100.0

    return {
        "kpis": {
            "total_searches": trace_stats["total_searches"] if trace_stats else 0,
            "avg_latency_ms": int(trace_stats["avg_latency"]) if trace_stats else 0,
            "total_api_fanout_calls": total_api_calls,
            "api_success_rate": success_rate,
            "ready_search_engines": len(ready_search),
            "total_search_engines": len(search_provs),
            "circuit_open_count": len(circuit_open),
            "cross_engine_hits": trace_stats["sum_cross"] if trace_stats else 0,
            "cache_hits": trace_stats["sum_cache"] if trace_stats else 0,
        },
        "providers": providers,
        "route_distribution": [dict(r) for r in route_dist],
        "recent_traces": [dict(r) for r in recent_traces],
    }


# ==================== 2. 渠道与多 Key 密钥池管理 ====================
@app.get("/api/admin/providers")
def list_all_providers(provider_type: Optional[str] = None) -> List[Dict[str, Any]]:
    return key_pool.list_providers(provider_type)


@app.post("/api/admin/providers")
def create_custom_provider(body: ProviderCreate) -> Dict[str, Any]:
    pid = body.id.strip().lower().replace(" ", "_")
    if not pid:
        raise HTTPException(status_code=422, detail="渠道标识 ID 不能为空")
    if key_pool.get_provider(pid):
        raise HTTPException(status_code=409, detail=f"渠道 ID '{pid}' 已存在")

    with _db_lock:
        conn = get_conn()
        conn.execute("""
        INSERT INTO providers (
            id, name, category, provider_type, requires_key, enabled, weight,
            timeout_ms, use_proxy, custom_proxy, base_url, default_model,
            strategy, icon, description, doc_url
        ) VALUES (?, ?, ?, ?, 1, 1, ?, ?, ?, ?, ?, ?, ?, 'ApiOutlined', ?, '')
        """, (
            pid,
            body.name.strip() or pid,
            body.category or body.provider_type,
            body.provider_type,
            body.weight,
            body.timeout_ms,
            1 if body.use_proxy else 0,
            (body.custom_proxy or "").strip(),
            body.base_url.strip(),
            body.default_model.strip(),
            body.strategy or "weighted",
            body.description.strip() or f"自定义 {body.provider_type.upper()} 渠道",
        ))
        if body.api_key and body.api_key.strip():
            key_id = f"key-{uuid.uuid4().hex[:10]}"
            conn.execute("""
            INSERT INTO api_keys (
                id, provider_id, label, api_key, base_url, weight,
                rpm_limit, daily_quota, use_proxy, custom_proxy, enabled, created_at
            ) VALUES (?, ?, ?, ?, '', 1, 60, 10000, -1, '', 1, ?)
            """, (key_id, pid, body.key_label or "默认密钥", body.api_key.strip(), time.time()))
        conn.commit()
        conn.close()
    return {"status": "ok", "id": pid}



@app.put("/api/admin/providers/{provider_id}")
def update_provider_config(provider_id: str, body: ProviderUpdate) -> Dict[str, Any]:
    updates = body.model_dump(exclude_none=True)
    if not updates:
        return {"status": "no_op"}
    set_clauses = []
    params = []
    for k, v in updates.items():
        set_clauses.append(f"{k} = ?")
        if isinstance(v, bool):
            params.append(1 if v else 0)
        else:
            params.append(v)
    params.append(provider_id)
    with _db_lock:
        conn = get_conn()
        conn.execute(f"UPDATE providers SET {', '.join(set_clauses)} WHERE id = ?", tuple(params))
        conn.commit()
        conn.close()
    return {"status": "ok", "provider": key_pool.get_provider(provider_id)}


@app.post("/api/admin/providers/{provider_id}/reset-circuit")
def reset_provider_circuit(provider_id: str) -> Dict[str, Any]:
    key_pool.reset_circuit(provider_id)
    return {"status": "ok"}


@app.post("/api/admin/keys")
def add_api_key(body: ApiKeyCreate) -> Dict[str, Any]:
    if not key_pool.get_provider(body.provider_id):
        raise HTTPException(status_code=404, detail="Provider not found")
    if not body.api_key.strip():
        raise HTTPException(status_code=422, detail="API Key cannot be empty")
    if body.weight < 1 or body.rpm_limit < 1 or body.daily_quota < 1:
        raise HTTPException(status_code=422, detail="Weight and quotas must be positive")
    key_id = f"key-{uuid.uuid4().hex[:10]}"
    use_proxy_val = -1 if body.use_proxy is None else (1 if body.use_proxy else 0)
    with _db_lock:
        conn = get_conn()
        conn.execute("""
        INSERT INTO api_keys (
            id, provider_id, label, api_key, base_url, weight,
            rpm_limit, daily_quota, use_proxy, custom_proxy, enabled, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            key_id,
            body.provider_id,
            body.label.strip() or "默认密钥",
            body.api_key.strip(),
            (body.base_url or "").strip(),
            body.weight,
            body.rpm_limit,
            body.daily_quota,
            use_proxy_val,
            (body.custom_proxy or "").strip(),
            1 if body.enabled else 0,
            time.time(),
        ))
        conn.commit()
        conn.close()
    key_pool.reset_circuit(body.provider_id)
    return {"status": "ok", "id": key_id}


@app.delete("/api/admin/keys/{key_id}")
def delete_api_key(key_id: str) -> Dict[str, Any]:
    with _db_lock:
        conn = get_conn()
        conn.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
        conn.commit()
        conn.close()
    return {"status": "ok"}


@app.put("/api/admin/keys/{key_id}/toggle")
def toggle_api_key(key_id: str, enabled: bool = Query(...)) -> Dict[str, Any]:
    with _db_lock:
        conn = get_conn()
        conn.execute("UPDATE api_keys SET enabled = ? WHERE id = ?", (1 if enabled else 0, key_id))
        conn.commit()
        conn.close()
    return {"status": "ok"}


@app.post("/api/admin/providers/{provider_id}/test")
async def test_provider_connectivity(provider_id: str, test_query: str = "OpenAI") -> Dict[str, Any]:
    prov, key_info, proxy = key_pool.acquire_credentials(provider_id)
    if not prov:
        raise HTTPException(status_code=404, detail="Provider not found")

    ptype = prov["provider_type"]
    if ptype == "search":
        trace, items = await execute_single_engine(
            engine_id=provider_id,
            query=test_query,
            max_results=5,
            timeout_sec=8.0,
            bypass_circuit=True,
        )
        return {
            "provider_id": provider_id,
            "status": trace.status,
            "latency_ms": trace.latency_ms,
            "result_count": trace.result_count,
            "used_proxy": trace.used_proxy,
            "error_message": trace.error_message,
            "sample_titles": [it.title for it in items[:3]],
        }

    elif ptype == "scraper":
        t0 = time.perf_counter()
        md = await scrape_url_markdown(
            "https://example.com",
            proxy=proxy,
            api_key=key_info["api_key"] if key_info else None,
            timeout_sec=8.0,
        )
        latency = int((time.perf_counter() - t0) * 1000)
        ok = len(md) > 20
        key_pool.record_execution(provider_id, key_info["id"] if key_info else None, ok, latency)
        return {
            "provider_id": provider_id,
            "status": "success" if ok else "error",
            "latency_ms": latency,
            "result_count": len(md),
            "used_proxy": bool(proxy),
            "sample_titles": [md[:120] + "..."] if ok else [],
        }

    elif ptype in ("llm", "reranker"):
        if not key_info or not key_info.get("api_key"):
            return {
                "provider_id": provider_id,
                "status": "skipped",
                "latency_ms": 0,
                "error_message": "请先为该模型/重排渠道配置 API Key",
            }
        base_url = (key_info.get("base_url") or prov.get("base_url") or "").rstrip("/")
        t0 = time.perf_counter()
        try:
            async with make_async_client(proxy, timeout_sec=10.0) as client:
                if ptype == "reranker":
                    ep = base_url if base_url.endswith("/rerank") else f"{base_url}/rerank"
                    resp = await client.post(
                        ep,
                        headers={"Authorization": f"Bearer {key_info['api_key']}"},
                        json={
                            "model": prov.get("default_model") or "jina-reranker-v2-base-multilingual",
                            "query": "AI search",
                            "documents": ["Open source metasearch engine"],
                        },
                    )
                else:
                    resp = await client.post(
                        f"{base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {key_info['api_key']}"},
                        json={
                            "model": prov.get("default_model") or "deepseek-chat",
                            "messages": [{"role": "user", "content": "ping"}],
                            "max_tokens": 8,
                        },
                    )
                latency = int((time.perf_counter() - t0) * 1000)
                ok = resp.status_code == 200
                key_pool.record_execution(provider_id, key_info["id"], ok, latency, "" if ok else f"HTTP {resp.status_code}")
                return {
                    "provider_id": provider_id,
                    "status": "success" if ok else "error",
                    "latency_ms": latency,
                    "used_proxy": bool(proxy),
                    "error_message": None if ok else f"HTTP {resp.status_code}: {resp.text[:160]}",
                }
        except Exception as e:
            latency = int((time.perf_counter() - t0) * 1000)
            key_pool.record_execution(provider_id, key_info["id"], False, latency, str(e))
            return {
                "provider_id": provider_id,
                "status": "error",
                "latency_ms": latency,
                "error_message": str(e)[:180],
            }


MODEL_PRESET_CATALOG: Dict[str, List[str]] = {
    "siliconflow": [
        "deepseek-ai/DeepSeek-V3",
        "deepseek-ai/DeepSeek-R1",
        "Qwen/Qwen2.5-72B-Instruct",
        "Qwen/Qwen2.5-7B-Instruct",
        "Qwen/QwQ-32B",
        "THUDM/glm-4-9b-chat",
    ],
    "deepseek": [
        "deepseek-chat",
        "deepseek-reasoner",
    ],
    "openai_compat": [
        "gpt-4o-mini",
        "gpt-4o",
        "o3-mini",
        "claude-3-7-sonnet-latest",
        "qwen-max",
        "qwen-plus",
    ],
    "jina_reranker": [
        "jina-reranker-v2-base-multilingual",
        "jina-reranker-m0",
        "jina-colbert-v2",
    ],
    "siliconflow_reranker": [
        "BAAI/bge-reranker-v2-m3",
        "Qwen/Qwen3-Reranker-8B",
        "Qwen/Qwen3-Reranker-4B",
        "netease-youdao/bce-reranker-base_v1",
    ],
    "cohere_reranker": [
        "rerank-multilingual-v3.0",
        "rerank-v3.5",
        "rerank-english-v3.0",
    ],
}


@app.get("/api/admin/providers/{provider_id}/models")
async def fetch_provider_models(
    provider_id: str,
    base_url: Optional[str] = Query(None, description="临时使用的 Base URL（不必先保存）"),
    api_key: Optional[str] = Query(None, description="临时使用的 API Key（不必先保存）"),
) -> Dict[str, Any]:
    prov, key_info, proxy = key_pool.acquire_credentials(provider_id)
    if not prov:
        raise HTTPException(status_code=404, detail="Provider not found")

    presets = list(MODEL_PRESET_CATALOG.get(provider_id, []))
    if prov.get("default_model") and prov["default_model"] not in presets:
        presets.insert(0, prov["default_model"])

    # 优先使用页面即时填写的 base_url/api_key（未保存也可拉取），否则回退已保存凭据
    eff_base = (base_url or "").strip() or (
        key_info.get("base_url") if key_info and key_info.get("base_url") else prov.get("base_url") or ""
    ).rstrip("/")
    eff_key = (api_key or "").strip() or (key_info.get("api_key") if key_info else None)
    if eff_base.endswith("/rerank"):
        eff_base = eff_base[: -len("/rerank")]
    models_ep = f"{eff_base.rstrip('/')}/models" if eff_base else ""

    if eff_key and models_ep.startswith("http"):
        try:
            async with make_async_client(proxy, timeout_sec=8.0) as client:
                resp = await client.get(
                    models_ep,
                    headers={"Authorization": f"Bearer {eff_key}"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    remote_ids = [
                        str(m.get("id"))
                        for m in (data.get("data") or data.get("models") or [])
                        if isinstance(m, dict) and m.get("id")
                    ]
                    if remote_ids:
                        if prov["provider_type"] == "reranker":
                            rerank_filtered = [m for m in remote_ids if "rerank" in m.lower() or "bge" in m.lower()]
                            remote_ids = rerank_filtered or remote_ids
                        merged = list(dict.fromkeys(remote_ids + presets))
                        return {"provider_id": provider_id, "source": "remote_api", "models": merged[:120]}
                    note = "接口返回 200 但模型列表为空"
                else:
                    note = f"HTTP {resp.status_code}: {resp.text[:120]}"
        except Exception as e:
            note = str(e)[:160]
        return {
            "provider_id": provider_id,
            "source": "preset_fallback",
            "models": presets,
            "note": f"远程拉取失败已回退内置模型库：{note}",
        }

    return {
        "provider_id": provider_id,
        "source": "preset",
        "models": presets,
        "note": "当前没有可用的 API Key（页面上填写 Key 后无需保存即可直接拉取）",
    }


# ==================== 3. 路由分组与全局策略配置 ====================
@app.get("/api/admin/routes")
def list_route_groups() -> List[Dict[str, Any]]:
    with _db_lock:
        conn = get_conn()
        rows = conn.execute("SELECT * FROM route_groups").fetchall()
        conn.close()
    res = []
    for r in rows:
        d = dict(r)
        d["engines"] = json.loads(d.get("engines_json") or "[]")
        d["fallback_engines"] = json.loads(d.get("fallback_engines_json") or "[]")
        res.append(d)
    return res


@app.put("/api/admin/routes/{group_id}")
def update_route_group(group_id: str, body: RouteGroupUpdate) -> Dict[str, Any]:
    with _db_lock:
        conn = get_conn()
        existing = conn.execute("SELECT * FROM route_groups WHERE id = ?", (group_id,)).fetchone()
        if not existing:
            conn.close()
            raise HTTPException(status_code=404, detail="Route group not found")

        cur = dict(existing)
        name = body.name if body.name is not None else cur["name"]
        desc = body.description if body.description is not None else cur["description"]
        engines_json = json.dumps(body.engines, ensure_ascii=False) if body.engines is not None else cur["engines_json"]
        fb_json = json.dumps(body.fallback_engines, ensure_ascii=False) if body.fallback_engines is not None else cur["fallback_engines_json"]
        timeout_ms = body.timeout_ms if body.timeout_ms is not None else cur["timeout_ms"]
        top_k = body.top_k if body.top_k is not None else cur["top_k"]
        rerank = (1 if body.enable_rerank else 0) if body.enable_rerank is not None else cur["enable_rerank"]
        scrape_n = body.scrape_top_n if body.scrape_top_n is not None else cur["scrape_top_n"]
        enabled = (1 if body.enabled else 0) if body.enabled is not None else cur["enabled"]

        conn.execute("""
        UPDATE route_groups SET
            name = ?, description = ?, engines_json = ?, fallback_engines_json = ?,
            timeout_ms = ?, top_k = ?, enable_rerank = ?, scrape_top_n = ?, enabled = ?
        WHERE id = ?
        """, (name, desc, engines_json, fb_json, timeout_ms, top_k, rerank, scrape_n, enabled, group_id))
        conn.commit()
        conn.close()
    return {"status": "ok"}


@app.get("/api/admin/settings")
def get_gateway_settings() -> Dict[str, Any]:
    return get_settings()


@app.put("/api/admin/settings")
def save_gateway_settings(body: GatewaySettingsUpdate) -> Dict[str, Any]:
    updates = body.model_dump(exclude_none=True)
    return update_settings(updates)


@app.post("/api/admin/router/test")
async def test_semantic_router(
    query: str = Query("Transformer attention paper arxiv"),
    mode: str = Query("auto"),
) -> Dict[str, Any]:
    resolved, meta = await resolve_smart_route(query, mode)
    return {
        "query": query,
        "requested_mode": mode,
        "resolved_route": resolved,
        "meta": meta,
    }


# ==================== 4. 调用审计日志与对外网关 Token ====================
@app.get("/api/admin/traces")
def list_search_traces(limit: int = 50) -> List[Dict[str, Any]]:
    with _db_lock:
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM search_traces ORDER BY created_at DESC LIMIT ?", (min(limit, 200),)
        ).fetchall()
        conn.close()
    res = []
    for r in rows:
        d = dict(r)
        d["engine_traces"] = json.loads(d.get("engine_traces_json") or "[]")
        d["top_urls"] = json.loads(d.get("top_urls_json") or "[]")
        res.append(d)
    return res


@app.get("/api/admin/gateway-tokens")
def list_gateway_tokens() -> List[Dict[str, Any]]:
    with _db_lock:
        conn = get_conn()
        rows = conn.execute("SELECT * FROM gateway_tokens ORDER BY created_at DESC").fetchall()
        conn.close()
    return [dict(r) for r in rows]


@app.post("/api/admin/gateway-tokens")
def create_gateway_token(name: str = Query("外部 Agent 接入密钥"), daily_limit: int = Query(10000)) -> Dict[str, Any]:
    token = f"sk-omni-{secrets.token_hex(12)}"
    with _db_lock:
        conn = get_conn()
        conn.execute(
            "INSERT INTO gateway_tokens (token, name, daily_limit, used_count, enabled, created_at) VALUES (?, ?, ?, 0, 1, ?)",
            (token, name, daily_limit, time.time())
        )
        conn.commit()
        conn.close()
    return {"status": "ok", "token": token}


@app.delete("/api/admin/gateway-tokens/{token}")
def delete_gateway_token(token: str) -> Dict[str, Any]:
    with _db_lock:
        conn = get_conn()
        conn.execute("DELETE FROM gateway_tokens WHERE token = ?", (token,))
        conn.commit()
        conn.close()
    return {"status": "ok"}


# ==================== 5. 统一聚合搜索与双轨 Agent 接口 ====================
def _infer_public_base_url(request: Optional[Request] = None) -> str:
    """推断网关对外可访问地址，用于写入 skill 包。"""
    if request is not None:
        try:
            return str(request.base_url).rstrip("/")
        except Exception:
            pass
    return "http://127.0.0.1:8088"


def _resolve_skill_token(token: Optional[str]) -> str:
    """确定 skill 包内嵌的接入 Token：显式传入优先，否则取最新签发的一个。"""
    if token:
        return token.strip()
    try:
        with _db_lock:
            conn = get_conn()
            row = conn.execute(
                "SELECT token FROM gateway_tokens WHERE enabled = 1 ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            conn.close()
        return (row["token"] if row else "") or ""
    except Exception:
        return ""


@app.get("/api/v1/skill/manifest")
def get_skill_manifest(
    request: Request,
    base_url: Optional[str] = Query(None, description="覆盖网关对外地址，留空自动推断"),
    token: Optional[str] = Query(None, description="嵌入到 skill 包中的网关 Token，留空则用最新签发的 Token"),
) -> Dict[str, Any]:
    """返回 skill 清单（入口地址、鉴权方式、能力与模式），供前端预览与 Agent 自检。"""
    settings = get_settings()
    resolved_base = (base_url or settings.get("public_base_url") or "").strip() or _infer_public_base_url(request)
    return {
        "manifest": skill_manifest(resolved_base, _resolve_skill_token(token)),
        "files": list_skill_files(),
    }


@app.get("/api/v1/skill/download")
def download_skill_package(
    request: Request,
    base_url: Optional[str] = Query(None, description="覆盖网关对外地址，留空自动推断"),
    token: Optional[str] = Query(None, description="嵌入到 skill 包中的网关 Token，留空则用最新签发的 Token"),
) -> Response:
    """一键下载可直接交给 Agent 使用的技能包（zip）。"""
    settings = get_settings()
    resolved_base = (base_url or settings.get("public_base_url") or "").strip() or _infer_public_base_url(request)
    payload = build_skill_zip(resolved_base, _resolve_skill_token(token))
    return Response(
        content=payload,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="omnisearch-gateway-skill.zip"',
            "Cache-Control": "no-store",
        },
    )


@app.post("/api/v1/search", response_model=UnifiedSearchResponse)
async def unified_search_endpoint(req: UnifiedSearchRequest) -> UnifiedSearchResponse:
    return await dispatch_unified_search(req, mode_label="api_search")


@app.post("/api/v1/webpage/read", response_model=WebpageReadResponse)
async def webpage_read_endpoint(payload: WebpageReadRequest) -> WebpageReadResponse:
    """直接读取网页正文：不经过搜索引擎，适用于用户已持有链接的场景。

    普通关键词检索仍由 `/api/v1/search` 与 `/api/v1/agent/stream` 负责；
    本接口只做“给定 URL → 返回页面正文”，失败条目会单独标注。
    """
    urls: List[str] = []
    for raw in payload.urls:
        url = (raw or "").strip()
        if not url:
            continue
        if not is_http_url(url):
            raise HTTPException(status_code=400, detail=f"非法 URL：{url[:80]}")
        if url not in urls:
            urls.append(url)
    if not urls:
        raise HTTPException(status_code=400, detail="urls 不能为空")

    started = time.perf_counter()
    _, jina_key_info, jina_proxy = key_pool.acquire_credentials("jina_reader")
    jina_key = jina_key_info["api_key"] if jina_key_info else None
    results = await read_webpages(
        urls,
        proxy=jina_proxy,
        api_key=jina_key,
        timeout_sec=max(3.0, payload.timeout_ms / 1000.0),
        max_chars=payload.max_chars,
        output_format=payload.format,
    )
    success = sum(1 for item in results if item.get("status") == "success")
    return WebpageReadResponse(
        results=results,
        success_count=success,
        failed_count=len(results) - success,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


# ==================== 6. 全网热榜聚合中心 ====================
def _resolve_global_proxy() -> Optional[str]:
    settings = get_settings()
    if settings.get("enable_global_proxy", True):
        return settings.get("global_proxy") or None
    return None


@app.get("/api/v1/trending/catalog")
def trending_catalog_endpoint() -> Dict[str, Any]:
    """返回支持的榜单清单（不含条目）。"""
    return {"boards": get_trending_catalog()}


@app.get("/api/v1/trending")
async def get_all_trending_boards(
    boards: Optional[str] = Query(None, description="逗号分隔的 board_id，留空返回全部"),
    limit: int = Query(20, ge=1, le=50),
    refresh: bool = Query(False, description="true 则跳过缓存强制刷新"),
) -> Dict[str, Any]:
    """并发聚合抓取全网各大榜单（内置 5 分钟缓存）。"""
    proxy = _resolve_global_proxy()
    if boards:
        ids = [b.strip() for b in boards.split(",") if b.strip() in BOARD_META]
    else:
        ids = list(BOARD_META)
    if not ids:
        raise HTTPException(status_code=404, detail="没有匹配的榜单 ID")

    results = await asyncio.gather(
        *[fetch_trending_board(bid, max_items=limit, force_refresh=refresh, global_proxy=proxy) for bid in ids]
    )
    ok_count = sum(1 for r in results if r.status == "success")
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_boards": len(results),
        "success_boards": ok_count,
        "boards": [r.model_dump() for r in results],
    }


@app.get("/api/v1/trending/{board_id}")
async def get_single_trending_board(
    board_id: str,
    limit: int = Query(20, ge=1, le=50),
    refresh: bool = Query(False),
) -> Dict[str, Any]:
    """抓取单个榜单详情。"""
    if board_id not in BOARD_META:
        raise HTTPException(status_code=404, detail=f"未知榜单 '{board_id}'，可用: {', '.join(BOARD_META)}")
    proxy = _resolve_global_proxy()
    board = await fetch_trending_board(
        board_id, max_items=limit, force_refresh=refresh, global_proxy=proxy
    )
    return board.model_dump()


# ==================== 7. 并行后台研究任务 ====================
@app.post("/api/v1/research/jobs", status_code=202)
async def create_research_job_endpoint(payload: ResearchJobCreate) -> Dict[str, Any]:
    """提交后台研究任务：立即返回 job_id，浏览器关闭后继续运行。"""
    try:
        return create_research_job(payload)
    except RuntimeError as e:
        raise HTTPException(status_code=429, detail=str(e)[:200])


@app.get("/api/v1/research/jobs")
def list_research_jobs_endpoint(
    status: Optional[str] = Query(None, pattern="^(queued|running|succeeded|failed|cancelled|interrupted)$"),
    limit: int = Query(50, ge=1, le=200),
) -> Dict[str, Any]:
    """研究任务列表（按创建时间倒序，含状态计数）。"""
    return list_research_jobs(status=status, limit=limit)


@app.get("/api/v1/research/jobs/{job_id}")
def get_research_job_endpoint(job_id: str, include_steps: bool = Query(True)) -> Dict[str, Any]:
    """研究任务详情：状态、最终 Markdown 与步骤回放。"""
    job = get_research_job(job_id, include_steps=include_steps)
    if not job:
        raise HTTPException(status_code=404, detail="研究任务不存在")
    return job


@app.post("/api/v1/research/jobs/{job_id}/cancel")
async def cancel_research_job_endpoint(job_id: str) -> Dict[str, Any]:
    """取消运行中的研究任务。"""
    try:
        return cancel_research_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="研究任务不存在")
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)[:200])


@app.get("/api/v1/research/jobs/{job_id}/stream")
async def stream_research_job_endpoint(
    job_id: str,
    after_seq: int = Query(0, ge=0),
) -> StreamingResponse:
    """回放已落库步骤并实时推送新事件；断开后重连传 after_seq 即可续看。"""
    if not get_research_job(job_id, include_steps=False):
        raise HTTPException(status_code=404, detail="研究任务不存在")
    return StreamingResponse(
        stream_research_job(job_id, after_seq=after_seq),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ==================== 8. 红果短剧娱乐渠道 ====================
def _hg_proxy() -> Optional[str]:
    settings = get_settings()
    if settings.get("enable_global_proxy", True):
        return settings.get("global_proxy") or None
    return None


@app.get("/api/v1/video/bilibili/search")
async def bilibili_search_endpoint(
    q: str = Query(..., min_length=1, max_length=80, description="搜索关键词"),
    limit: int = Query(20, ge=1, le=40),
    page: int = Query(1, ge=1, le=50),
    type: str = Query("video", pattern="^(video|user)$", description="video=视频，user=UP主"),
) -> Dict[str, Any]:
    """B站官方搜索（免登录）：type=video 搜视频，type=user 搜 UP主。"""
    from app.providers.bilibili import search_users, search_videos

    try:
        if type == "user":
            result = await search_users(q.strip(), limit=limit, page=page, proxy=_hg_proxy())
        else:
            result = await search_videos(q.strip(), limit=limit, page=page, proxy=_hg_proxy())
        result["type"] = type
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)[:200])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"B站搜索失败: {str(e)[:200]}")


@app.get("/api/v1/video/bilibili/comments")
async def bilibili_comments_endpoint(
    bvid: Optional[str] = Query(None, max_length=32),
    aid: Optional[int] = Query(None, ge=1),
    page: int = Query(1, ge=1, le=200),
    limit: int = Query(20, ge=1, le=49),
    sort: str = Query("hot", pattern="^(hot|new)$"),
) -> Dict[str, Any]:
    """抓取 B站视频评论（按热度或时间，免登录）。"""
    from app.providers.bilibili import fetch_comments

    try:
        return await fetch_comments(bvid=bvid, aid=aid, page=page, limit=limit, sort=sort, proxy=_hg_proxy())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)[:200])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"B站评论抓取失败: {str(e)[:200]}")


@app.post("/api/v1/agent/stream")
@app.get("/api/v1/agent/stream")
async def agent_search_stream_endpoint(req: AgentSearchRequest):
    return StreamingResponse(
        run_agent_search_stream(req),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

