"""管理端 API：套餐定价、客户、密钥、用量账单与营收大盘。

路径统一挂在 ``/api/admin/platform/*``，与既有的控制台管理接口并列，
由前端「开放 API 平台」页面消费。
"""
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.gateway.key_pool import key_pool
from app.platform import store
from app.platform.errors import ERROR_CATALOG

router = APIRouter(prefix="/api/admin/platform", tags=["开放 API 平台管理"])


def provider_health_snapshot() -> List[Dict[str, Any]]:
    """上游检索引擎健康快照：客户看到的是网关可用性，控制台需要看到上游风险。"""
    out = []
    for prov in key_pool.list_providers("search"):
        out.append({
            "id": prov["id"],
            "name": prov["name"],
            "health_status": prov["health_status"],
            "weight": prov["weight"],
            "total_calls": prov["total_calls"],
            "success_calls": prov["success_calls"],
            "avg_latency_ms": prov["avg_latency_ms"],
            "is_circuit_open": prov["is_circuit_open"],
        })
    return out


# ==================== 请求体 ====================

class ClientCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    email: str = ""
    company: str = ""
    plan_id: str = "trial"
    note: str = ""
    billing_mode: str = "prepaid"
    grant_units: Optional[int] = None
    issue_key: bool = True
    key_label: str = "默认密钥"


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    company: Optional[str] = None
    plan_id: Optional[str] = None
    status: Optional[str] = None
    billing_mode: Optional[str] = None
    credit_limit_cny: Optional[float] = None
    note: Optional[str] = None
    balance_units: Optional[int] = None


class TopupRequest(BaseModel):
    amount_cny: float = 0.0
    units: Optional[int] = None
    note: str = ""


class KeyCreate(BaseModel):
    client_id: str
    label: str = "默认密钥"
    scopes: List[str] = Field(default_factory=lambda: ["search", "extract", "answer", "chat"])
    rpm_limit: int = 0
    rpd_limit: int = 0
    ip_allowlist: str = ""
    expires_days: int = 0


class KeyUpdate(BaseModel):
    label: Optional[str] = None
    scopes: Optional[List[str]] = None
    rpm_limit: Optional[int] = None
    rpd_limit: Optional[int] = None
    ip_allowlist: Optional[str] = None
    enabled: Optional[int] = None
    expires_days: Optional[int] = None


class PlanUpsert(BaseModel):
    name: Optional[str] = None
    tagline: Optional[str] = None
    price_per_1k_cny: Optional[float] = None
    min_topup_cny: Optional[float] = None
    included_units: Optional[int] = None
    rpm_limit: Optional[int] = None
    rpd_limit: Optional[int] = None
    max_results: Optional[int] = None
    allow_rerank: Optional[int] = None
    allow_extract: Optional[int] = None
    allow_answer: Optional[int] = None
    allow_deep: Optional[int] = None
    allow_stream: Optional[int] = None
    allow_postpaid: Optional[int] = None
    features: Optional[List[str]] = None
    highlight: Optional[int] = None
    enabled: Optional[int] = None


# ==================== 概览 ====================

@router.get("/overview")
def platform_overview(days: int = Query(30, ge=1, le=365)) -> Dict[str, Any]:
    stats = store.usage_stats(days=days, top_queries=10)
    revenue = store.revenue_summary(days=days)
    clients = store.list_clients(limit=1000)
    plans = store.list_plans()

    plan_distribution: Dict[str, int] = {}
    for client in clients:
        if client.get("source") == "internal":
            continue
        plan_distribution[client.get("plan_name") or client.get("plan_id")] = (
            plan_distribution.get(client.get("plan_name") or client.get("plan_id"), 0) + 1
        )

    top_clients: List[Dict[str, Any]] = []
    since = time.time() - days * 86400
    with store._db_lock:
        conn = store.get_conn()
        rows = conn.execute(
            """
            SELECT u.client_id, c.name AS client_name, p.name AS plan_name,
                   COUNT(*) AS requests, COALESCE(SUM(u.units), 0) AS units,
                   COALESCE(SUM(u.cost_cny), 0) AS cost_cny,
                   SUM(CASE WHEN u.status = 'error' THEN 1 ELSE 0 END) AS errors
            FROM platform_usage_events u
            LEFT JOIN platform_clients c ON c.id = u.client_id
            LEFT JOIN platform_plans p ON p.id = c.plan_id
            WHERE u.created_at >= ? AND u.client_id <> 'internal'
            GROUP BY u.client_id ORDER BY units DESC LIMIT 10
            """,
            (since,),
        ).fetchall()
        conn.close()
    for row in rows:
        item = dict(row)
        item["cost_cny"] = round(float(item.get("cost_cny") or 0), 4)
        top_clients.append(item)

    return {
        "kpis": {
            "requests": stats["totals"]["requests"],
            "units": stats["totals"]["units"],
            "consumed_cny": stats["totals"]["cost_cny"],
            "revenue_cny": revenue["revenue_window_cny"],
            "revenue_total_cny": revenue["revenue_total_cny"],
            "clients_total": revenue["clients_total"],
            "clients_paid": revenue["clients_paid"],
            "clients_active": revenue["clients_active"],
            "balance_units_total": revenue["balance_units_total"],
            "error_rate": stats["totals"]["error_rate"],
            "cache_hit_rate": stats["totals"]["cache_hit_rate"],
            "p95_latency_ms": stats["totals"]["p95_latency_ms"],
            "arpu_cny": round(revenue["revenue_total_cny"] / max(1, revenue["clients_paid"]), 2),
        },
        "series": stats["series"],
        "endpoints": stats["endpoints"],
        "top_queries": stats["top_queries"],
        "top_clients": top_clients,
        "plan_distribution": [{"name": k, "count": v} for k, v in plan_distribution.items()],
        "plans": plans,
        "providers": provider_health_snapshot(),
    }


# ==================== 套餐定价 ====================

@router.get("/plans")
def list_plans(all: bool = Query(True)) -> List[Dict[str, Any]]:
    return store.list_plans(enabled_only=not all)


@router.put("/plans/{plan_id}")
def upsert_plan(plan_id: str, payload: PlanUpsert) -> Dict[str, Any]:
    data = payload.model_dump(exclude_none=True)
    if "features" in data:
        import json as _json

        data["features_json"] = _json.dumps(data.pop("features"), ensure_ascii=False)
    return store.upsert_plan(plan_id, data)


@router.delete("/plans/{plan_id}")
def disable_plan(plan_id: str) -> Dict[str, Any]:
    store.delete_plan(plan_id)
    return {"status": "ok", "plan_id": plan_id, "enabled": 0}


# ==================== 客户 ====================

@router.get("/clients")
def list_clients(q: str = Query(""), limit: int = Query(200, ge=1, le=1000)) -> List[Dict[str, Any]]:
    return store.list_clients(query=q, limit=limit)


@router.get("/clients/{client_id}")
def get_client(client_id: str) -> Dict[str, Any]:
    client = store.get_client(client_id)
    if not client:
        raise HTTPException(status_code=404, detail="客户不存在")
    client["keys"] = store.list_api_keys(client_id)
    client["usage"] = store.usage_stats(client_id=client_id, days=30)["totals"]
    client["topups"] = store.list_topups(client_id=client_id, limit=20)
    return client


@router.post("/clients")
def create_client(payload: ClientCreate) -> Dict[str, Any]:
    if not store.get_plan(payload.plan_id):
        raise HTTPException(status_code=400, detail=f"套餐 {payload.plan_id} 不存在")
    client = store.create_client(
        name=payload.name,
        email=payload.email,
        company=payload.company,
        plan_id=payload.plan_id,
        note=payload.note,
        source="admin",
        billing_mode=payload.billing_mode,
        grant_units=payload.grant_units,
    )
    raw_key = None
    if payload.issue_key:
        raw_key, _ = store.create_api_key(client["id"], label=payload.key_label)
    return {"client": client, "api_key": raw_key}


@router.put("/clients/{client_id}")
def update_client(client_id: str, payload: ClientUpdate) -> Dict[str, Any]:
    client = store.update_client(client_id, payload.model_dump(exclude_none=True))
    if not client:
        raise HTTPException(status_code=404, detail="客户不存在")
    return client


@router.post("/clients/{client_id}/topup")
def topup(client_id: str, payload: TopupRequest) -> Dict[str, Any]:
    try:
        client = store.topup_client(
            client_id, amount_cny=payload.amount_cny, units=payload.units, note=payload.note
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    topups = store.list_topups(client_id=client_id, limit=1)
    return {"client": client, "topup": topups[0] if topups else None}


@router.post("/clients/{client_id}/keys")
def create_key(client_id: str, payload: KeyCreate) -> Dict[str, Any]:
    if not store.get_client(client_id):
        raise HTTPException(status_code=404, detail="客户不存在")
    expires_at = time.time() + payload.expires_days * 86400 if payload.expires_days > 0 else 0
    raw, key = store.create_api_key(
        client_id,
        label=payload.label,
        scopes=payload.scopes,
        rpm_limit=payload.rpm_limit,
        rpd_limit=payload.rpd_limit,
        ip_allowlist=payload.ip_allowlist,
        expires_at=expires_at,
    )
    return {"api_key": raw, "key": key, "warning": "明文密钥仅本次返回，请立即妥善保存"}


# ==================== 密钥 ====================

@router.get("/keys")
def list_keys(client_id: Optional[str] = Query(None)) -> List[Dict[str, Any]]:
    return store.list_api_keys(client_id)


@router.put("/keys/{key_id}")
def update_key(key_id: str, payload: KeyUpdate) -> Dict[str, Any]:
    data = payload.model_dump(exclude_none=True)
    if "scopes" in data:
        import json as _json

        data["scopes_json"] = _json.dumps(data.pop("scopes"), ensure_ascii=False)
    if "expires_days" in data:
        days = data.pop("expires_days")
        data["expires_at"] = time.time() + days * 86400 if days and days > 0 else 0
    key = store.update_api_key(key_id, data)
    if not key:
        raise HTTPException(status_code=404, detail="密钥不存在")
    return key


@router.post("/keys/{key_id}/revoke")
def revoke_key(key_id: str) -> Dict[str, Any]:
    if not store.revoke_api_key(key_id):
        raise HTTPException(status_code=404, detail="密钥不存在")
    return {"status": "ok", "key_id": key_id, "revoked": True}


@router.post("/keys/{key_id}/rotate")
def rotate_key(key_id: str) -> Dict[str, Any]:
    old = store.get_api_key(key_id)
    if not old:
        raise HTTPException(status_code=404, detail="密钥不存在")
    raw, new_key = store.create_api_key(
        old["client_id"],
        label=f"{old.get('label') or '密钥'}（轮换 {time.strftime('%Y-%m-%d')}）",
        scopes=old.get("scopes") or ["search"],
        rpm_limit=int(old.get("rpm_limit") or 0),
        rpd_limit=int(old.get("rpd_limit") or 0),
        ip_allowlist=old.get("ip_allowlist") or "",
        expires_at=float(old.get("expires_at") or 0),
    )
    store.revoke_api_key(key_id)
    return {"api_key": raw, "key": new_key, "revoked_key_id": key_id,
            "warning": "明文密钥仅本次返回，旧密钥已吊销"}


# ==================== 用量与账单 ====================

@router.get("/usage")
def usage_events(
    client_id: Optional[str] = Query(None),
    key_id: Optional[str] = Query(None),
    endpoint: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    days: int = Query(7, ge=1, le=365),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    since = time.time() - days * 86400
    return store.query_usage_events(
        client_id=client_id, key_id=key_id, endpoint=endpoint, status=status,
        since_ts=since, limit=limit, offset=offset,
    )


@router.get("/usage/stats")
def usage_stats(
    client_id: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=365),
) -> Dict[str, Any]:
    return store.usage_stats(client_id=client_id, days=days)


@router.get("/invoices")
def invoices(month: Optional[str] = Query(None, description="YYYY-MM，默认当月")) -> Dict[str, Any]:
    try:
        items = store.monthly_invoice(month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    total_cost = round(sum(float(i.get("cost_cny") or 0) for i in items), 2)
    total_units = sum(int(i.get("units") or 0) for i in items)
    return {
        "month": month or time.strftime("%Y-%m"),
        "items": items,
        "total_cost_cny": total_cost,
        "total_units": total_units,
    }


@router.get("/topups")
def list_topups(client_id: Optional[str] = Query(None),
                limit: int = Query(100, ge=1, le=500)) -> List[Dict[str, Any]]:
    return store.list_topups(client_id=client_id, limit=limit)


# ==================== 平台设置 ====================

@router.get("/settings")
def get_platform_settings() -> Dict[str, Any]:
    return {
        "units": store.get_units_config(),
        "signup": store.get_platform_setting("signup", {}),
        "auth": store.get_platform_setting("auth", {}),
    }


@router.put("/settings")
def update_platform_settings(payload: Dict[str, Any]) -> Dict[str, Any]:
    for section in ("units", "signup", "auth"):
        if section in payload and isinstance(payload[section], dict):
            current = store.get_platform_setting(section, {}) or {}
            current.update(payload[section])
            store.set_platform_setting(section, current)
    return get_platform_settings()


@router.get("/meta")
def platform_meta() -> Dict[str, Any]:
    """接口目录与错误码清单，供文档页与客户自助排查使用。"""
    endpoints = [
        {
            "method": "POST", "path": "/v1/search", "scope": "search",
            "summary": "多源聚合搜索（不调用大模型；deep 含正文）",
            "units": "basic 1 / advanced 2 / deep 3",
        },
        {
            "method": "GET", "path": "/v1/search", "scope": "search",
            "summary": "GET 风格聚合搜索",
            "units": "取决于 search_depth",
        },
        {
            "method": "POST", "path": "/v1/extract", "scope": "extract",
            "summary": "网页正文抽取（Markdown）",
            "units": "1 次 / URL",
        },
        {
            "method": "POST", "path": "/v1/answer", "scope": "answer",
            "summary": "带引用的答案生成（支持 SSE）",
            "units": "fast 2 / deep 5",
        },
        {
            "method": "POST", "path": "/v1/research", "scope": "answer",
            "summary": "深度研究 / Agent 自主研究（支持 SSE）",
            "units": "deep 5 / agentic 8",
        },
        {
            "method": "POST", "path": "/v1/chat/completions", "scope": "chat",
            "summary": "OpenAI 兼容联网问答",
            "units": "2",
        },
        {
            "method": "GET", "path": "/v1/me", "scope": "-",
            "summary": "账户套餐与余额", "units": "0",
        },
        {
            "method": "GET", "path": "/v1/usage", "scope": "-",
            "summary": "用量与账单明细", "units": "0",
        },
        {
            "method": "GET", "path": "/v1/models", "scope": "-",
            "summary": "可用答案模型列表", "units": "0",
        },
        {
            "method": "POST", "path": "/v1/signup", "scope": "-",
            "summary": "自助注册领取试用密钥", "units": "0",
        },
        {
            "method": "GET", "path": "/v1/health", "scope": "-",
            "summary": "健康检查", "units": "0",
        },
    ]
    errors = [
        {
            "code": code,
            "http_status": meta["status"],
            "type": meta["type"],
            "message": meta["message"],
        }
        for code, meta in ERROR_CATALOG.items()
    ]
    return {"endpoints": endpoints, "errors": errors, "units": store.get_units_config()}
