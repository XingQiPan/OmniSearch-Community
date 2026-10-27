"""中文查询 → 英文检索词扩展。

用途：中文提问时只检索中文页面，容易把 GitHub / 官方文档等外网结果挤到后面。
这里用一次小模型翻译（严格超时 + 内存缓存）生成 1 条英文检索词，交给海外引擎补检。
失败、超时、未配置模型时一律静默返回空列表，绝不影响主检索。
"""
import asyncio
import json
import re
import time
from typing import Dict, List, Optional, Tuple

from app.core.database import get_settings
from app.gateway.intent_filters import _CJK_RE, detect_lang
from app.gateway.key_pool import key_pool
from app.providers.adapters import make_async_client

_CACHE: Dict[str, Tuple[float, List[str]]] = {}
_TTL_SEC = 3600.0
_TIMEOUT_SEC = 5.0
_MAX_QUERIES = 1

_PROMPT = (
    "把下面这条中文检索需求翻译成一条英文检索关键词（保留专有名词与版本号，不要解释、不要引号、不要句号）。\n"
    "只输出这一条英文关键词。\n\n中文：{query}"
)


def _pick_llm() -> Tuple[Optional[dict], Optional[dict], Optional[str], Optional[str]]:
    settings = get_settings()
    default = settings.get("default_llm_provider", "siliconflow")
    order = [default] + [p["id"] for p in key_pool.list_providers("llm") if p["id"] != default]
    for pid in order:
        prov, key_info, proxy = key_pool.acquire_credentials(pid)
        if prov and prov.get("enabled") and key_info and key_info.get("api_key"):
            model = (settings.get("default_llm_model") if pid == default else None) or prov.get("default_model") or ""
            return prov, key_info, proxy, model
    return None, None, None, None


def _clean(text: str) -> str:
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    line = line.strip().strip('"').strip("'").strip("。.").strip()
    if not line or len(line) > 160 or _CJK_RE.search(line):
        return ""
    return line


async def _translate(query: str, prov: dict, key_info: dict, proxy: Optional[str], model: str) -> List[str]:
    base_url = (key_info.get("base_url") or prov.get("base_url") or "").rstrip("/")
    if not base_url:
        return []
    started = time.perf_counter()
    try:
        async with make_async_client(proxy, timeout_sec=_TIMEOUT_SEC) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {key_info['api_key']}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": _PROMPT.format(query=query)}],
                    "temperature": 0,
                    "max_tokens": 60,
                },
            )
        latency = int((time.perf_counter() - started) * 1000)
        if resp.status_code != 200:
            key_pool.record_execution(prov["id"], key_info["id"], False, latency, f"HTTP {resp.status_code}")
            return []
        key_pool.record_execution(prov["id"], key_info["id"], True, latency)
        content = resp.json()["choices"][0]["message"]["content"]
        cleaned = _clean(content)
        return [cleaned] if cleaned else []
    except Exception:
        return []


async def english_query_variants(query: str) -> List[str]:
    """纯中文查询生成 1 条英文检索词；其他语言或不具备条件时返回空。"""
    q = (query or "").strip()
    if not q or detect_lang(q) not in ("zh", "mixed"):
        return []
    now = time.time()
    cached = _CACHE.get(q)
    if cached and cached[0] > now:
        return list(cached[1])
    prov, key_info, proxy, model = _pick_llm()
    if not prov or not key_info or not model:
        return []
    try:
        variants = await asyncio.wait_for(_translate(q, prov, key_info, proxy, model), timeout=_TIMEOUT_SEC + 1.5)
    except Exception:
        variants = []
    variants = variants[:_MAX_QUERIES]
    _CACHE[q] = (now + _TTL_SEC, variants)
    return variants


def clear_cache() -> None:
    _CACHE.clear()
