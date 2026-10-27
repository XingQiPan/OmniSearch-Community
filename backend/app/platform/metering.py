"""计量与计费规则：把一次调用折算成「次数（units）」和「金额（元）」。

单位设计对齐主流搜索 API 的 credit 模型：
- 基础搜索 1 次；开启语义重排 2 次；深度（重排 + 正文）3 次；
- 正文抽取按 URL 计 1 次/条；
- 带引用的答案生成 2 次，深度答案 5 次；
- 研究接口：子问题并发研究 5 次，Agent 多轮自主研究 8 次。
单价由套餐 ``price_per_1k_cny``（元/千次）决定，便于按千次售卖。
"""
from typing import Any, Dict, Optional

from app.platform import store
from app.platform.auth import AuthContext, ensure_balance
from app.platform.errors import ApiError


def search_units(depth: str, rerank: bool = False) -> int:
    cfg = store.get_units_config().get("search", {})
    depth = (depth or "basic").lower()
    if depth not in ("basic", "advanced", "deep"):
        depth = "basic"
    units = int(cfg.get(depth, 1))
    if rerank and depth == "basic":
        units = max(units, int(cfg.get("advanced", 2)))
    return max(1, units)


def answer_units(mode: str) -> int:
    cfg = store.get_units_config().get("answer", {})
    mode = (mode or "fast").lower()
    return max(1, int(cfg.get(mode, 2)))


def extract_units(url_count: int) -> int:
    """按成功抽取的 URL 数计费；0 条成功即 0 次。"""
    cfg = store.get_units_config().get("extract", {})
    per_url = max(1, int(cfg.get("per_url", 1)))
    return max(0, url_count) * per_url


def research_units(mode: str) -> int:
    cfg = store.get_units_config().get("research", {})
    mode = "agentic" if (mode or "").lower() == "agentic" else "deep"
    return max(1, int(cfg.get(mode, 8 if mode == "agentic" else 5)))


def chat_units() -> int:
    return max(1, int(store.get_units_config().get("chat", 2)))


def max_extract_urls() -> int:
    return max(1, int(store.get_units_config().get("max_extract_urls", 20)))


def cost_cny(units: int, price_per_1k: float) -> float:
    return round(units * float(price_per_1k) / 1000.0, 6)


def usage_block(units: int, auth: AuthContext, remaining_after: Optional[int] = None) -> Dict[str, Any]:
    """响应体里的 ``usage`` 字段，保持与 OpenAI / Tavily 一致的阅读习惯。"""
    price = auth.price_per_1k
    if remaining_after is None:
        remaining_after = auth.balance_units - units if auth.billing_mode == "prepaid" else -1
    block: Dict[str, Any] = {
        "units": units,
        "unit": "request",
        "credits_used": units,
        "unit_price_cny_per_1k": price,
        "cost_cny": cost_cny(units, price),
        "currency": "CNY",
        "billing_mode": auth.billing_mode,
    }
    if auth.billing_mode == "prepaid" and not auth.is_internal:
        block["remaining_units"] = max(0, int(remaining_after))
        block["credits_remaining"] = max(0, int(remaining_after))
    return block


def assert_feature(auth: AuthContext, flag: str, label: str) -> None:
    if auth.is_internal:
        return
    if not auth.plan_flag(flag):
        raise ApiError(
            "feature_not_in_plan",
            message=f"当前「{auth.plan.get('name')}」套餐未开通{label}，请升级套餐后重试",
            details={"feature": flag, "plan": auth.plan.get("id")},
        )


def resolve_search_units(auth: AuthContext, depth: str, rerank: bool) -> int:
    if depth == "deep":
        assert_feature(auth, "allow_deep", "深度研究检索")
    if rerank:
        assert_feature(auth, "allow_rerank", "语义重排 Rerank")
    units = search_units(depth, rerank)
    ensure_balance(auth, units)
    return units


def resolve_extract_units(auth: AuthContext, url_count: int) -> int:
    assert_feature(auth, "allow_extract", "网页正文抽取")
    units = extract_units(url_count)
    ensure_balance(auth, units)
    return units


def resolve_answer_units(auth: AuthContext, mode: str, stream: bool) -> int:
    assert_feature(auth, "allow_answer", "带引用的答案生成")
    if stream:
        assert_feature(auth, "allow_stream", "SSE 流式输出")
    if mode == "deep":
        assert_feature(auth, "allow_deep", "深度研究")
    units = answer_units(mode)
    ensure_balance(auth, units)
    return units


def resolve_research_units(auth: AuthContext, mode: str, stream: bool) -> int:
    assert_feature(auth, "allow_deep", "深度研究 / Agent 自主研究")
    if stream:
        assert_feature(auth, "allow_stream", "SSE 流式输出")
    units = research_units(mode)
    ensure_balance(auth, units)
    return units


def resolve_chat_units(auth: AuthContext) -> int:
    units = chat_units()
    ensure_balance(auth, units)
    return units
