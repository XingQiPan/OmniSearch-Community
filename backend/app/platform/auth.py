"""API Key 鉴权：把 Bearer 密钥解析为「客户 + 套餐 + 额度」上下文。

鉴权顺序刻意做成主流 API 的「先身份、再权限、再配额、最后计费前置校验」，
每一层失败都返回可编程处理的错误码，不泄露内部实现。
"""
import time
from dataclasses import dataclass, field
from ipaddress import ip_address, ip_network
from typing import Any, Dict, List, Optional

from fastapi import Header, Request

from app.platform import store
from app.platform.errors import ApiError
from app.platform.ratelimit import limiter


@dataclass
class AuthContext:
    request_id: str
    client: Dict[str, Any]
    key: Dict[str, Any]
    plan: Dict[str, Any]
    scopes: List[str] = field(default_factory=list)
    rpm_limit: int = 0
    rpd_limit: int = 0
    remaining_rpm: int = -1
    reset_in: int = 60

    @property
    def client_id(self) -> str:
        return str(self.client.get("id") or "")

    @property
    def key_id(self) -> str:
        return str(self.key.get("id") or "")

    @property
    def plan_id(self) -> str:
        return str(self.plan.get("id") or "")

    @property
    def price_per_1k(self) -> float:
        return float(self.plan.get("price_per_1k_cny") or 0.0)

    @property
    def billing_mode(self) -> str:
        return str(self.client.get("billing_mode") or "prepaid")

    @property
    def balance_units(self) -> int:
        return int(self.client.get("balance_units") or 0)

    @property
    def is_internal(self) -> bool:
        return self.client_id == "internal" or self.billing_mode == "internal"

    def has_scope(self, scope: str) -> bool:
        scopes = self.scopes or []
        return scope in scopes or "all" in scopes or "*" in scopes

    def plan_flag(self, flag: str) -> bool:
        return bool(self.plan.get(flag) or 0)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for") or ""
    if forwarded:
        return forwarded.split(",")[0].strip()
    real = request.headers.get("x-real-ip") or ""
    if real:
        return real.strip()
    return request.client.host if request.client else ""


def _ip_allowed(client_ip: str, allowlist: str) -> bool:
    entries = [e.strip() for e in (allowlist or "").replace("\n", ",").split(",") if e.strip()]
    if not entries:
        return True
    if not client_ip:
        return False
    try:
        addr = ip_address(client_ip)
    except ValueError:
        return False
    for entry in entries:
        try:
            if "/" in entry:
                if addr in ip_network(entry, strict=False):
                    return True
            elif addr == ip_address(entry):
                return True
        except ValueError:
            continue
    return False


def extract_token(authorization: Optional[str], x_api_key: Optional[str]) -> str:
    if x_api_key and x_api_key.strip():
        return x_api_key.strip()
    if authorization:
        auth = authorization.strip()
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return auth
    return ""


def _auth_disabled() -> bool:
    cfg = store.get_platform_setting("auth", {}) or {}
    return cfg.get("require_key") is False


def require_auth(
    request: Request,
    authorization: Optional[str] = Header(None, description="Authorization: Bearer sk-omni-xxx"),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key", description="兼容 X-API-Key 方式传参"),
) -> AuthContext:
    request_id = getattr(request.state, "request_id", "") or ""
    token = extract_token(authorization, x_api_key)

    if not token:
        if _auth_disabled():
            # 仅本地开发场景：显式关闭鉴权后降级为「内部客户」上下文
            client = store.get_client("internal") or {}
            plan = store.get_plan(str(client.get("plan_id") or "enterprise")) or {}
            ctx = AuthContext(request_id=request_id, client=client, key={}, plan=plan,
                              scopes=["all"], rpm_limit=0, rpd_limit=0, remaining_rpm=-1)
            request.state.auth = ctx
            return ctx
        raise ApiError("missing_api_key", headers={"WWW-Authenticate": "Bearer"})

    resolved = store.resolve_api_key(token)
    if not resolved or not resolved.get("key") or not resolved.get("client"):
        raise ApiError("invalid_api_key", headers={"WWW-Authenticate": "Bearer"})

    key = resolved["key"]
    client = resolved["client"]
    plan = resolved.get("plan") or {}

    if not key.get("enabled") or key.get("revoked_at"):
        raise ApiError("key_revoked")
    expires_at = float(key.get("expires_at") or 0)
    if expires_at and expires_at < time.time():
        raise ApiError("key_expired")
    if not plan or not plan.get("enabled", 1):
        raise ApiError("feature_not_in_plan", message="该客户所属套餐已下线，请联系商务")
    if client.get("status") != "active":
        raise ApiError("account_suspended")
    if not _ip_allowed(_client_ip(request), key.get("ip_allowlist") or ""):
        raise ApiError("ip_not_allowed")

    # 限流：Key 级覆盖优先，其次套餐级
    rpm_limit = int(key.get("rpm_limit") or 0) or int(plan.get("rpm_limit") or 0)
    rpd_limit = int(key.get("rpd_limit") or 0) or int(plan.get("rpd_limit") or 0)
    if client.get("id") != "internal":
        allowed, remaining, reset_in = limiter.hit(f"rpm:{key['id']}", rpm_limit, 60)
        if not allowed:
            raise ApiError(
                "rate_limit_exceeded",
                message=f"已超过 {rpm_limit} RPM 限流，请 {reset_in} 秒后重试",
                details={"limit": rpm_limit, "window": "1m", "retry_after": reset_in},
                headers={
                    "Retry-After": str(reset_in),
                    "X-RateLimit-Limit": str(rpm_limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_in),
                },
            )
        if rpd_limit > 0 and store.count_key_requests_today(key["id"]) >= rpd_limit:
            raise ApiError(
                "daily_limit_exceeded",
                message=f"已超出每日 {rpd_limit} 次调用上限",
                details={"limit": rpd_limit, "window": "1d"},
                headers={"Retry-After": "3600", "X-RateLimit-Limit": str(rpd_limit),
                         "X-RateLimit-Remaining": "0"},
            )
    else:
        remaining, reset_in = -1, 60

    ctx = AuthContext(
        request_id=request_id,
        client=client,
        key=key,
        plan=plan,
        scopes=list(key.get("scopes") or []),
        rpm_limit=rpm_limit,
        rpd_limit=rpd_limit,
        remaining_rpm=remaining,
        reset_in=reset_in,
    )

    # 余额校验放在各端点里（拿到本次精确定价后）再做，避免用 402 掩盖参数错误
    store.touch_api_key(key["id"])
    request.state.auth = ctx
    return ctx


def require_scope(scope: str):
    """依赖工厂：校验 Key 是否被授权使用某个能力。"""
    from fastapi import Depends

    def checker(auth: AuthContext = Depends(require_auth)) -> AuthContext:
        ensure_scope(auth, scope)
        return auth

    return checker


def ensure_scope(auth: AuthContext, scope: str) -> None:
    if auth.is_internal:
        return
    if not auth.has_scope(scope):
        raise ApiError(
            "scope_denied",
            message=f"当前 API Key 未被授予 `{scope}` 权限",
            details={"required_scope": scope, "granted_scopes": auth.scopes},
        )


def ensure_balance(auth: AuthContext, units: int) -> None:
    if auth.is_internal or auth.billing_mode != "prepaid":
        return
    if auth.balance_units < units:
        raise ApiError(
            "insufficient_balance",
            message=f"本次调用需要 {units} 次额度，当前余额 {auth.balance_units} 次，请充值",
            details={
                "required_units": units,
                "balance_units": auth.balance_units,
                "price_per_1k_cny": auth.price_per_1k,
            },
        )


def rate_limit_headers(auth: Optional[AuthContext]) -> Dict[str, str]:
    if auth is None:
        return {}
    headers: Dict[str, str] = {}
    if auth.rpm_limit > 0 and auth.remaining_rpm >= 0:
        headers["X-RateLimit-Limit"] = str(auth.rpm_limit)
        headers["X-RateLimit-Remaining"] = str(auth.remaining_rpm)
        headers["X-RateLimit-Reset"] = str(auth.reset_in)
    if auth.rpd_limit > 0:
        headers["X-RateLimit-Day-Limit"] = str(auth.rpd_limit)
    if auth.billing_mode == "prepaid" and not auth.is_internal:
        headers["X-Quota-Remaining"] = str(auth.balance_units)
    return headers
