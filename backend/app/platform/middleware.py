"""``/v1/*`` 统一接入中间件：请求 ID、限流头、用量落库与统一异常兜底。

之所以放在中间件而不是每个 endpoint 里，是为了保证「任何一次到达网关的
付费调用」都必然留下一条可对账的用量事件——包括 4xx/5xx。
"""
import logging
import time
import traceback
import uuid
from typing import Any, Optional

from fastapi import Request
from fastapi.responses import JSONResponse

from app.platform import store
from app.platform.auth import AuthContext, rate_limit_headers
from app.platform.errors import error_body

logger = logging.getLogger("omnisearch.api_gateway")

API_PREFIX = "/v1"
UNMETERED_PATHS = {"/v1/health", "/v1/models", "/v1/me", "/v1/usage"}


def _is_public_api(path: str) -> bool:
    return path == API_PREFIX or path.startswith(f"{API_PREFIX}/")


async def api_gateway_middleware(request: Request, call_next):
    path = request.url.path
    if not _is_public_api(path) or request.method == "OPTIONS":
        return await call_next(request)

    request_id = f"req_{uuid.uuid4().hex[:24]}"
    request.state.request_id = request_id
    request.state.units = 0
    request.state.cached = False
    request.state.result_count = 0
    request.state.query = ""
    request.state.route = ""
    request.state.error_code = ""

    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:  # noqa: BLE001
        latency_ms = int((time.perf_counter() - started) * 1000)
        request.state.error_code = "internal_error"
        logger.error("public api failed: %s\n%s", exc, traceback.format_exc())
        _record(request, status="error", http_status=500, latency_ms=latency_ms, units=0)
        return JSONResponse(
            status_code=500,
            content=error_body(
                "internal_error",
                "服务内部错误，我们的工程师已收到告警；请携带 request_id 联系支持",
                request_id,
            ),
            headers={"X-Request-Id": request_id},
        )

    latency_ms = int((time.perf_counter() - started) * 1000)
    auth: Optional[AuthContext] = getattr(request.state, "auth", None)
    units = int(getattr(request.state, "units", 0) or 0)
    cached = bool(getattr(request.state, "cached", False))
    success = response.status_code < 400
    charge_units = units if (success and not getattr(request.state, "idempotent_replay", False)) else 0

    remaining: Optional[int] = None
    if auth is not None and path not in UNMETERED_PATHS:
        remaining = _record(
            request,
            status="success" if success else "error",
            http_status=response.status_code,
            latency_ms=latency_ms,
            units=charge_units,
            cached=cached,
            auth=auth,
        )
        for header, value in rate_limit_headers(auth).items():
            response.headers.setdefault(header, value)
        if remaining is not None and remaining >= 0:
            response.headers["X-Quota-Remaining"] = str(remaining)
            response.headers["X-Quota-Used"] = str(units)

    response.headers["X-Request-Id"] = request_id
    response.headers["X-API-Version"] = "v1"
    response.headers["X-Cache"] = "HIT" if cached else "MISS"
    response.headers["X-Latency-Ms"] = str(latency_ms)
    return response


def _record(
    request: Request,
    status: str,
    http_status: int,
    latency_ms: int,
    units: int,
    cached: bool = False,
    auth: Optional[AuthContext] = None,
) -> Optional[int]:
    if auth is None:
        return None
    try:
        return store.record_usage_event(
            request_id=getattr(request.state, "request_id", ""),
            client_id=auth.client_id,
            key_id=auth.key_id,
            endpoint=request.url.path,
            units=units,
            unit_price=auth.price_per_1k,
            status=status,
            http_status=http_status,
            error_code=getattr(request.state, "error_code", "") or "",
            latency_ms=latency_ms,
            cached=cached,
            query=getattr(request.state, "query", "") or "",
            route=getattr(request.state, "route", "") or "",
            result_count=int(getattr(request.state, "result_count", 0) or 0),
            charge=units > 0 and not auth.is_internal,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("usage record failed: %s", exc)
        return None
