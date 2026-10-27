"""统一错误模型：所有 ``/v1/*`` 错误都返回同一信封，便于客户侧 SDK 统一处理。

行业约定（参考 Stripe / OpenAI / Tavily）：HTTP 状态码表达大类，``error.code``
表达可编程处理的细分原因，``request_id`` 贯穿日志以便排查。
"""
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# code -> (type, http_status, 默认中文提示)
ERROR_CATALOG: Dict[str, Dict[str, Any]] = {
    # 请求侧
    "invalid_request": {"type": "invalid_request_error", "status": 400, "message": "请求参数不合法"},
    "missing_query": {"type": "invalid_request_error", "status": 400, "message": "缺少必填参数 query"},
    "query_too_long": {"type": "invalid_request_error", "status": 400, "message": "query 超过长度上限"},
    "invalid_time_range": {"type": "invalid_request_error", "status": 400, "message": "time_range 取值非法"},
    "invalid_url": {"type": "invalid_request_error", "status": 400, "message": "urls 中存在非法 URL"},
    "too_many_urls": {"type": "invalid_request_error", "status": 400, "message": "单次抽取 URL 数量超过上限"},
    "idempotency_conflict": {"type": "invalid_request_error", "status": 409,
                             "message": "Idempotency-Key 已用于不同的请求体"},
    # 鉴权 / 权限
    "missing_api_key": {"type": "authentication_error", "status": 401,
                        "message": "缺少 API Key，请在 Authorization: Bearer <key> 中携带"},
    "invalid_api_key": {"type": "authentication_error", "status": 401, "message": "API Key 无效"},
    "key_expired": {"type": "authentication_error", "status": 401, "message": "API Key 已过期"},
    "key_revoked": {"type": "authentication_error", "status": 401, "message": "API Key 已被吊销"},
    "ip_not_allowed": {"type": "permission_error", "status": 403, "message": "调用来源 IP 不在白名单内"},
    "scope_denied": {"type": "permission_error", "status": 403, "message": "当前 Key 未授权该能力"},
    "feature_not_in_plan": {"type": "permission_error", "status": 403,
                            "message": "当前套餐未开通该能力，请升级套餐"},
    # 额度 / 计费
    "insufficient_balance": {"type": "billing_error", "status": 402,
                             "message": "账户余额不足，请充值后重试"},
    "account_suspended": {"type": "permission_error", "status": 403, "message": "账户已被停用"},
    "rate_limit_exceeded": {"type": "rate_limit_error", "status": 429,
                            "message": "请求过于频繁，已触发每分钟限流"},
    "daily_limit_exceeded": {"type": "rate_limit_error", "status": 429,
                             "message": "已超出该 Key 的每日调用上限"},
    # 上游 / 服务
    "upstream_timeout": {"type": "upstream_error", "status": 504, "message": "上游检索源超时"},
    "upstream_unavailable": {"type": "upstream_error", "status": 502, "message": "上游检索源不可用"},
    "search_failed": {"type": "upstream_error", "status": 502, "message": "搜索执行失败"},
    "extract_failed": {"type": "upstream_error", "status": 502, "message": "网页正文抽取失败"},
    "endpoint_not_found": {"type": "invalid_request_error", "status": 404, "message": "接口不存在"},
    "method_not_allowed": {"type": "invalid_request_error", "status": 405, "message": "请求方法不允许"},
    "internal_error": {"type": "server_error", "status": 500, "message": "服务内部错误，请联系支持"},
    "service_unavailable": {"type": "server_error", "status": 503, "message": "服务暂时不可用"},
}


class ApiError(Exception):
    """业务异常。由全局 handler 转换成统一错误信封。"""

    def __init__(
        self,
        code: str,
        message: Optional[str] = None,
        status_code: Optional[int] = None,
        param: Optional[str] = None,
        details: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        meta = ERROR_CATALOG.get(code, ERROR_CATALOG["internal_error"])
        self.code = code if code in ERROR_CATALOG else "internal_error"
        self.type = meta["type"]
        self.status_code = status_code or int(meta["status"])
        self.message = message or meta["message"]
        self.param = param
        self.details = details
        self.headers = headers or {}
        super().__init__(self.message)


def error_body(
    code: str,
    message: str,
    request_id: str = "",
    param: Optional[str] = None,
    details: Optional[Any] = None,
    type_: Optional[str] = None,
) -> Dict[str, Any]:
    meta = ERROR_CATALOG.get(code, ERROR_CATALOG["internal_error"])
    err: Dict[str, Any] = {
        "code": code,
        "type": type_ or meta["type"],
        "message": message,
        "request_id": request_id,
        "docs_url": "/docs/api",
    }
    if param:
        err["param"] = param
    if details is not None:
        err["details"] = details
    return {"error": err}


def get_request_id(request: Optional[Request]) -> str:
    if request is None:
        return ""
    rid = getattr(request.state, "request_id", None)
    return rid or ""


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        rid = get_request_id(request)
        request.state.error_code = exc.code
        headers = {"X-Request-Id": rid} if rid else {}
        headers.update(exc.headers)
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, rid, exc.param, exc.details, exc.type),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        rid = get_request_id(request)
        # 控制台内部接口保持 FastAPI 默认的 422/detail 形状，避免前端解析回归
        if not request.url.path.startswith("/v1/"):
            return JSONResponse(status_code=422, content={"detail": exc.errors()})
        request.state.error_code = "invalid_request"
        errors: List[Dict[str, Any]] = []
        first_param = None
        for item in exc.errors():
            loc = [str(x) for x in item.get("loc", []) if x not in ("body", "query", "path")]
            field = ".".join(loc) or None
            first_param = first_param or field
            errors.append({
                "param": field,
                "message": item.get("msg", ""),
                "type": item.get("type", ""),
            })
        # FastAPI 自身返回 422；对外统一用 400 + 结构化 details，降低接入摩擦
        headers = {"X-Request-Id": rid} if rid else {}
        return JSONResponse(
            status_code=400,
            content=error_body(
                "invalid_request",
                "请求参数校验失败",
                rid,
                param=first_param,
                details={"errors": errors},
            ),
            headers=headers,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        rid = get_request_id(request)
        # 控制台内部接口保持 {"detail": ...}，对外 API 使用结构化错误信封
        if not request.url.path.startswith("/v1/"):
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers=dict(exc.headers or {}),
            )
        if exc.status_code == 404:
            code = "endpoint_not_found"
        elif exc.status_code == 405:
            code = "method_not_allowed"
        elif exc.status_code == 401:
            code = "invalid_api_key"
        elif exc.status_code == 403:
            code = "scope_denied"
        elif exc.status_code == 429:
            code = "rate_limit_exceeded"
        else:
            code = "internal_error" if exc.status_code >= 500 else "invalid_request"
        request.state.error_code = code
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        headers = dict(exc.headers or {})
        if rid:
            headers.setdefault("X-Request-Id", rid)
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(code, detail, rid),
            headers=headers,
        )


def error_response(code: str, message: Optional[str] = None, request_id: str = "",
                   status_code: Optional[int] = None,
                   headers: Optional[Dict[str, str]] = None) -> JSONResponse:
    meta = ERROR_CATALOG.get(code, ERROR_CATALOG["internal_error"])
    hdrs = {"X-Request-Id": request_id} if request_id else {}
    if headers:
        hdrs.update(headers)
    return JSONResponse(
        status_code=status_code or int(meta["status"]),
        content=error_body(code, message or meta["message"], request_id),
        headers=hdrs,
    )
