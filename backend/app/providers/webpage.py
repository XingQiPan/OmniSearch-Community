"""直接读取网页正文：URL 识别、单页抓取与统一结果构造。

与搜索链路互补：普通关键词仍走多源检索；当查询里出现链接时，
这里直接抓取目标页面，返回标题、正文、发布时间与读取状态。
"""
import asyncio
import ipaddress
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from app.gateway.freshness import utc_now
from app.gateway.fusion import extract_domain, normalize_url
from app.providers.adapters import read_url_evidence
from app.schemas import UnifiedSearchItem

# 只匹配显式 http(s) 链接；裸域名/裸 www 在下面单独做保守识别。
_URL_RE = re.compile(r"https?://[^\s<>\"'`，。；！？、：」「』《》]+", re.IGNORECASE)
_WWW_RE = re.compile(r"(?<![\w@])(www\.[^\s<>\"'`，。；！？、：」「』《》]+)", re.IGNORECASE)
_BARE_URL_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}(?::\d{1,5})?(?:/[^\s]*)?$",
    re.IGNORECASE,
)
_TRAILING_PUNCT = ".,;:!?)]}>，。；：！？）】｝、"


def _trim_url(url: str) -> str:
    value = (url or "").strip()
    pairs = {")": "(", "]": "[", "}": "{"}
    while value and value[-1] in _TRAILING_PUNCT:
        # Keep a closing bracket when it belongs to the URL (e.g. Wikipedia titles).
        if value[-1] in pairs and value.count(pairs[value[-1]]) >= value.count(value[-1]):
            break
        value = value[:-1]
    return value


def _with_scheme(url: str) -> str:
    value = (url or "").strip()
    if value.startswith("//"):
        return "https:" + value
    if not re.match(r"^[a-z][a-z0-9+.-]*://", value, re.IGNORECASE):
        return "https://" + value
    return value


def is_http_url(value: str) -> bool:
    """Scheme check only; host safety is enforced in validate_target_url()."""
    try:
        parsed = urlparse((value or "").strip())
        return parsed.scheme in ("http", "https") and bool(parsed.hostname)
    except ValueError:
        return False


def validate_target_url(value: str) -> Tuple[Optional[str], Optional[str]]:
    """Normalize a user supplied URL and reject local/private targets (SSRF guard)."""
    target = _with_scheme(value)
    if not is_http_url(target):
        return None, "仅支持 http/https 网页链接"
    host = (urlparse(target).hostname or "").strip().lower().rstrip(".")
    if not host:
        return None, "链接缺少有效域名"
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return None, "不允许读取本地或内网地址"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return target, None
    if (address.is_private or address.is_loopback or address.is_link_local
            or address.is_reserved or address.is_unspecified or address.is_multicast):
        return None, "不允许读取本地或内网地址"
    return target, None


def extract_urls(text: str, limit: int = 5) -> List[str]:
    """Extract unique http(s) URLs from a query, including a bare URL-only query."""
    raw = (text or "").strip()
    if not raw or limit <= 0:
        return []
    candidates: List[str] = []
    for match in _URL_RE.finditer(raw):
        candidates.append(_trim_url(match.group(0)))
    for match in _WWW_RE.finditer(raw):
        candidates.append(_trim_url("https://" + match.group(1)))
    if not candidates and _BARE_URL_RE.match(raw):
        candidates.append(_trim_url(_with_scheme(raw)))

    urls: List[str] = []
    seen = set()
    for candidate in candidates:
        target, _ = validate_target_url(candidate)
        if not target:
            continue
        key = normalize_url(target)
        if not key or key in seen:
            continue
        seen.add(key)
        urls.append(target)
        if len(urls) >= limit:
            break
    return urls


def strip_urls(text: str) -> str:
    """Remove extracted links so the remaining text can still drive normal search."""
    raw = text or ""
    if _BARE_URL_RE.match(raw.strip()):
        return ""
    cleaned = _URL_RE.sub(" ", raw)
    cleaned = _WWW_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned.strip(" ,;，；.。")


def title_from_markdown(text: str) -> str:
    for line in (text or "").splitlines()[:30]:
        line = line.strip()
        lowered = line.lower()
        if lowered.startswith("title:"):
            value = line.split(":", 1)[1].strip()
            if value:
                return value[:200]
        if line.startswith("# "):
            return line[2:].strip()[:200]
    return ""


def to_plain_text(text: str) -> str:
    """Strip common Markdown syntax for callers that ask for plain text."""
    value = text or ""
    value = re.sub(r"```[a-zA-Z]*", "", value)
    value = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", value)
    value = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"[#>*`_-]{2,}", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _error_item(url: str, error: str, started: float, output_format: str) -> Dict[str, Any]:
    return {
        "url": url,
        "final_url": url,
        "title": urlparse(url).hostname or url,
        "content": "",
        "format": output_format,
        "length": 0,
        "status": "error",
        "error": (error or "读取失败")[:200],
        "published_at": None,
        "retrieved_at": utc_now().isoformat(),
        "truncated": False,
        "read_source": None,
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }


async def read_webpages(
    urls: List[str],
    proxy: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout_sec: float = 12.0,
    max_chars: int = 16000,
    output_format: str = "markdown",
    concurrency: int = 5,
) -> List[Dict[str, Any]]:
    """Read pages concurrently. Never raises for a single bad URL; failures are itemized."""
    targets: List[str] = []
    seen = set()
    for raw in urls or []:
        value = (raw or "").strip()
        if not value:
            continue
        key = normalize_url(_with_scheme(value))
        if not key or key in seen:
            continue
        seen.add(key)
        targets.append(value)

    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def read_one(raw_url: str) -> Dict[str, Any]:
        started = time.perf_counter()
        target, error = validate_target_url(raw_url)
        if not target:
            return _error_item(raw_url, error or "链接无效", started, output_format)
        async with semaphore:
            try:
                evidence = await asyncio.wait_for(
                    read_url_evidence(
                        target,
                        proxy=proxy,
                        api_key=api_key,
                        timeout_sec=max(3.0, timeout_sec),
                        min_chars=60,
                        max_chars=max_chars,
                    ),
                    timeout=max(4.0, timeout_sec + 4.0),
                )
            except asyncio.TimeoutError:
                return _error_item(target, "读取超时", started, output_format)
            except Exception as exc:  # noqa: BLE001
                return _error_item(target, str(exc), started, output_format)

        text = evidence.get("text") or ""
        content = to_plain_text(text) if output_format == "text" else text
        content = content[:max_chars]
        success = bool(content.strip())
        final_url = evidence.get("final_url") or target
        title = (evidence.get("title") or title_from_markdown(text)
                 or urlparse(final_url).hostname or final_url)
        read_status = evidence.get("read_status") or "failed"
        error = None
        if not success:
            error = ("页面没有可提取的静态正文（可能是前端渲染、需要登录或站点反爬）"
                     if read_status == "failed" else read_status)
        return {
            "url": target,
            "final_url": final_url,
            "title": title,
            "content": content,
            "format": output_format,
            "length": len(content),
            "status": "success" if success else "error",
            "error": error,
            "published_at": evidence.get("published_at"),
            "retrieved_at": evidence.get("retrieved_at") or utc_now().isoformat(),
            "truncated": bool(evidence.get("content_truncated")) or len(text) > max_chars,
            "read_source": evidence.get("reader_source"),
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }

    return await asyncio.gather(*(read_one(url) for url in targets))


def page_to_search_item(page: Dict[str, Any]) -> UnifiedSearchItem:
    """Convert a successful direct page into the shared search result model."""
    url = page.get("final_url") or page.get("url") or ""
    content = page.get("content") or ""
    domain = extract_domain(url)
    snippet = re.sub(r"\s+", " ", content).strip()[:300]
    return UnifiedSearchItem(
        title=page.get("title") or domain or url,
        url=url,
        normalized_url=normalize_url(url),
        snippet=snippet,
        content=content,
        published_at=page.get("published_at"),
        favicon=f"https://www.google.com/s2/favicons?domain={domain}&sz=64" if domain else None,
        domain=domain,
        source_engine="direct_page",
        engines=["direct_page"],
        positions={"direct_page": 1},
        raw_score=1.0,
        rrf_score=1.0,
        final_score=1.0,
        category="web",
        metadata={
            "direct_read": True,
            "source_url": page.get("url"),
            "final_url": url,
            "read_status": page.get("status"),
            "retrieved_at": page.get("retrieved_at"),
            "content_truncated": bool(page.get("truncated")),
            "read_source": page.get("read_source"),
            "latency_ms": page.get("latency_ms"),
        },
    )


def build_direct_report(pages: List[Dict[str, Any]]) -> str:
    """Render direct page content as Markdown without invoking an LLM."""
    successful = [p for p in pages if p.get("status") == "success"]
    failed = [p for p in pages if p.get("status") != "success"]
    lines = ["# 网页正文直读", ""]
    if not successful:
        lines.append("> 未能读取到网页正文。已保留原链接，并可在搜索工作台继续使用普通关键词检索。")
    for index, page in enumerate(successful, start=1):
        title = page.get("title") or page.get("url")
        lines.append(f"## {index}. {title}")
        meta = [f"原文：{page.get('final_url') or page.get('url')}"]
        if page.get("published_at"):
            meta.append(f"发布时间：{page['published_at']}")
        if page.get("retrieved_at"):
            meta.append(f"读取时间：{page['retrieved_at']}")
        meta.append(f"正文长度：{page.get('length', 0)} 字")
        if page.get("truncated"):
            meta.append("已截断")
        if page.get("read_source") == "meta_description":
            meta.append("仅页面摘要，非全文（前端脚本渲染页面，静态抓取无法获得完整正文）")
        elif page.get("read_source"):
            meta.append(f"读取通道：{page['read_source']}")
        lines.append("> " + " ｜ ".join(meta))
        lines.append("")
        lines.append(page.get("content") or "")
        lines.append("")
    if failed:
        lines.append("## 读取失败的链接")
        lines.append("")
        for page in failed:
            lines.append(f"- {page.get('url')}：{page.get('error') or '读取失败'}")
        lines.append("")
    return "\n".join(lines)
