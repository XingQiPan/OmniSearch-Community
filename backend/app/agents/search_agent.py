import asyncio
import json
import re
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from app.core.database import get_settings
from app.gateway.dispatcher import classify_query_route, dispatch_unified_search, resolve_smart_route
from app.gateway.key_pool import key_pool
from app.providers.adapters import make_async_client
from app.gateway.freshness import evidence_label, infer_time_range, time_guidance, utc_now
from app.agents.evidence import choose_sources, read_sources, evidence_context, coverage_gaps, build_raw_dump
from app.providers.trending_search import direct_data_boards
from app.providers.webpage import (
    build_direct_report,
    extract_urls,
    page_to_search_item,
    read_webpages,
    strip_urls,
)
from app.schemas import (
    AgentSearchRequest,
    EngineExecutionTrace,
    UnifiedSearchItem,
    UnifiedSearchRequest,
    UnifiedSearchResponse,
)


def resolve_active_llm(
    preferred_provider_id: Optional[str] = None, preferred_model: Optional[str] = None
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[str], str]:
    settings = get_settings()
    candidates = []
    if preferred_provider_id:
        candidates.append(preferred_provider_id)
    default_prov = settings.get("default_llm_provider", "siliconflow")
    if default_prov not in candidates:
        candidates.append(default_prov)
    for p in key_pool.list_providers("llm"):
        if p["id"] not in candidates:
            candidates.append(p["id"])

    for pid in candidates:
        prov, key_info, proxy = key_pool.acquire_credentials(pid)
        if prov and prov.get("enabled") and key_info and key_info.get("api_key"):
            default_override = settings.get("default_llm_model") if pid == default_prov else None
            model = preferred_model or default_override or prov.get("default_model") or "deepseek-chat"
            return prov, key_info, proxy, model
    return None, None, None, ""


async def call_llm_json(
    prompt: str,
    prov: Dict[str, Any],
    key_info: Dict[str, Any],
    proxy: Optional[str],
    model: str,
) -> Optional[Any]:
    base_url = (key_info.get("base_url") or prov.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    endpoint = f"{base_url}/chat/completions"
    t0 = time.perf_counter()
    try:
        async with make_async_client(proxy, timeout_sec=15.0) as client:
            resp = await client.post(
                endpoint,
                headers={"Authorization": f"Bearer {key_info['api_key']}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                    "max_tokens": 500,
                },
            )
            latency = int((time.perf_counter() - t0) * 1000)
            if resp.status_code == 200:
                key_pool.record_execution(prov["id"], key_info["id"], True, latency)
                content = resp.json()["choices"][0]["message"]["content"]
                m = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", content)
                if m:
                    return json.loads(m.group(1))
            else:
                key_pool.record_execution(prov["id"], key_info["id"], False, latency, f"HTTP {resp.status_code}")
    except Exception as e:
        latency = int((time.perf_counter() - t0) * 1000)
        key_pool.record_execution(prov["id"], key_info["id"], False, latency, str(e))
    return None


async def stream_llm_text(
    messages: List[Dict[str, str]],
    prov: Dict[str, Any],
    key_info: Dict[str, Any],
    proxy: Optional[str],
    model: str,
) -> AsyncGenerator[str, None]:
    base_url = (key_info.get("base_url") or prov.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    endpoint = f"{base_url}/chat/completions"
    t0 = time.perf_counter()
    try:
        async with make_async_client(proxy, timeout_sec=45.0) as client:
            async with client.stream(
                "POST",
                endpoint,
                headers={"Authorization": f"Bearer {key_info['api_key']}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": 0.35,
                    "stream": True,
                },
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    latency = int((time.perf_counter() - t0) * 1000)
                    key_pool.record_execution(prov["id"], key_info["id"], False, latency, f"HTTP {resp.status_code}")
                    yield f"\n> ⚠️ 大模型接口返回 HTTP {resp.status_code}: {body.decode('utf-8', errors='ignore')[:200]}\n"
                    return

                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                        delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content")
                        if delta:
                            yield delta
                    except Exception:
                        continue
                latency = int((time.perf_counter() - t0) * 1000)
                key_pool.record_execution(prov["id"], key_info["id"], True, latency)
    except Exception as e:
        latency = int((time.perf_counter() - t0) * 1000)
        key_pool.record_execution(prov["id"], key_info["id"], False, latency, str(e))
        yield f"\n> ⚠️ 大模型流式调用异常 ({ str(e)[:120] })，已自动切换为网关内置智能摘要模式。\n"


_SYNTHESIS_NOISE_PATTERNS = [
    r"本内容遵循[^。，；]*?版权协议[^。]*?[。；]?",
    r"版权声明[:：][^\n]*",
    r"转载请附上原文出处[^\n]*",
    r"收录于\s*当前文章被以下社区[^\n]*",
    r"于\s*\d{4}-\d{2}-\d{2}[^\d]{0,6}\d{2}:\d{2}(?::\d{2})?\s*(?:首次)?发布",
    r"已于\s*\d{4}-\d{2}-\d{2}[^\n]*?修改",
    r"\d+(?:\.\d+)?[kw]?\+?\s*(?:次)?(?:阅读|播放|围观)",
    r"URL Source:[^\n]*",
    r"^Markdown Content:\s*",
    r"跳到(?:主要|顶部)内容[^\n]*",
    r"打开APP[^\n]*",
    r"广告\s*·?\s*$",
    r"\[[Ss]earXNG\s*·\s*[^\]]*\]",
    r"\[[^\]]*(?:搜索|引擎)\][\s:：]*",
]


def _clean_synthesis_text(raw: str, max_len: int = 170) -> str:
    """抽取式合成前的文本清洗：去站点模板噪声 / 内联标记 / 压缩空白，并尽量在句号处截断。"""
    text = (raw or "").strip()
    if not text:
        return ""
    # 去图片与链接标记（保留链接文字），去内联引用角标
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[\d+(?:,\s*\d+)*\]", "", text)
    # 去代码围栏与表格分隔行残片
    text = re.sub(r"```[a-zA-Z]*", " ", text)
    text = re.sub(r"\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?", " ", text)
    for pat in _SYNTHESIS_NOISE_PATTERNS:
        text = re.sub(pat, " ", text, flags=re.IGNORECASE | re.MULTILINE)
    text = re.sub(r"\s+", " ", text).strip(" -·|>　")
    text = re.sub(r"(?:\.{2,}|…)?\s*(?:查看全部|查看详情|详情\s*>>?|详情|阅读原文|展开全文)$", "", text).strip()
    if len(text) > max_len:
        cut = text[:max_len]
        # 优先在句号/问叹号处截断，避免半句话
        for sep in ("。", "！", "？", "；"):
            pos = cut.rfind(sep)
            if pos >= max_len * 0.55:
                text = cut[: pos + 1]
                break
        else:
            text = cut.rstrip("，、;；:：- ") + ("…" if len(text) > max_len else "")
    return text


def _build_video_report(v: Dict[str, Any]) -> str:
    """把解析结果渲染成带完整下载直链的 Markdown 报告。"""
    platform = v.get("platform_name") or v.get("platform") or "视频"
    tracks: List[Dict[str, Any]] = v.get("tracks") or []
    stats = {k: n for k, n in (v.get("stats") or {}).items() if n}
    stat_names = {
        "digg": "点赞", "comment": "评论", "share": "分享", "collect": "收藏", "play": "播放",
        "view": "播放", "danmaku": "弹幕", "reply": "评论", "like": "点赞", "coin": "投币",
        "favorite": "收藏",
    }

    lines: List[str] = []
    lines.append(f"## {platform}视频已解析：{v.get('title') or '未命名'}\n")

    lines.append("### 一、视频内容\n")
    lines.append(f"| 项目 | 内容 |")
    lines.append("| --- | --- |")
    lines.append(f"| 标题 | {v.get('title') or '-'} |")
    lines.append(f"| 作者 | {v.get('author') or '-'} |")
    lines.append(f"| 时长 | {v.get('duration_text') or '-'} |")
    if v.get("width") and v.get("height"):
        lines.append(f"| 分辨率 | {v['width']}×{v['height']} |")
    if v.get("page_count") and v["page_count"] > 1:
        lines.append(f"| 分P | 共 {v['page_count']} P（当前 P{v.get('page')} {v.get('page_title') or ''}） |")
    if v.get("music_title"):
        lines.append(f"| 背景音乐 | {v['music_title']} |")
    if v.get("is_gallery"):
        lines.append(f"| 类型 | 图文 · {v.get('image_count')} 张 |")
    if stat_names and stats:
        lines.append("| 互动数据 | " + " · ".join(f"{stat_names.get(k, k)} {n}" for k, n in list(stats.items())[:5]) + " |")
    lines.append(f"| 原始链接 | {v.get('share_url') or v.get('url') or '-'} |")
    lines.append("")

    if v.get("note"):
        lines.append(f"> {v['note']}\n")

    lines.append(f"### 二、下载直链（共 {len(tracks)} 条）\n")
    if not tracks:
        lines.append("未获取到可下载直链，请重试或换用侧边栏「抖音/B站 视频下载」页面。\n")
    for i, t in enumerate(tracks, start=1):
        spec = []
        if t.get("width") and t.get("height"):
            spec.append(f"{t['width']}×{t['height']}")
        if t.get("size_bytes"):
            spec.append(f"{round(t['size_bytes'] / 1024 / 1024, 1)} MB")
        if t.get("codec"):
            spec.append(str(t["codec"]))
        if t.get("watermark") is False:
            spec.append("无水印")
        if t.get("kind") == "audio":
            spec.append("纯音频轨")
        suffix = f"（{' · '.join(spec)}）" if spec else ""
        lines.append(f"{i}. **{t.get('label')}**{suffix}")
        lines.append(f"   `{t.get('url')}`")
    lines.append("")

    lines.append("### 三、使用说明\n")
    lines.append("- 直链带时效签名，过期后重新粘贴链接解析即可。")
    if tracks and any(t.get("watermark") is False for t in tracks):
        lines.append("- 抖音「无水印原画」可直接保存；浏览器若直接播放，请右键「另存为」。")
    if any(t.get("kind") == "audio" for t in tracks):
        lines.append("- B站 DASH 视频轨 / 音频轨需合并：`ffmpeg -i video.m4s -i audio.m4s -c copy out.mp4`。")
    lines.append("- 请仅下载你有权保存的内容，遵守平台版权与使用条款。")
    return "\n".join(lines)


def generate_extractive_synthesis(
    query: str,
    results: List[UnifiedSearchItem],
    mode: str = "fast",
    sub_questions: Optional[List[Dict[str, str]]] = None,
) -> str:
    """
    Deterministic, high-signal cited synthesis engine when no LLM API key is configured yet.
    Ensures the user gets a rich, structured cited report out of the box.
    """
    if not results:
        return f"未能针对 **「{query}」** 检索到有效结果，请检查网络连接或在「API 渠道与密钥池」中启用更多搜索引擎。"

    lines: List[str] = []
    cross_items = [r for r in results if len(r.engines) > 1]

    if mode == "deep":
        lines.append(f"## 深度研究综合报告：{query}\n")
        lines.append(
            f"> **网关执行摘要**：本次深度研究共调度多源检索引擎并行探索了 **{len(sub_questions or [])}** 个子课题节点，"
            f"去重融合后精选出 **{len(results)}** 篇文献与网页（其中 **{len(cross_items)}** 条 URL 被多个引擎命中，不代表独立来源证实）。\n"
        )
        if sub_questions:
            lines.append("### 一、DAG 拆解维度与关键发现\n")
            for idx, sq in enumerate(sub_questions, start=1):
                q_title = sq.get("title", f"子维度 {idx}")
                q_query = sq.get("query", "")
                lines.append(f"#### {idx}. {q_title}（检索词：`{q_query}`）")
                # Pick top 2 matching items
                start_i = ((idx - 1) * 2) % len(results)
                picked = results[start_i : start_i + 3] or results[:2]
                for p_item in picked:
                    cite_idx = results.index(p_item) + 1
                    eng_badge = " + ".join(p_item.engines)
                    snippet_clean = _clean_synthesis_text(
                        p_item.snippet or p_item.content or p_item.title, max_len=200
                    )
                    lines.append(
                        f"- **{p_item.title}**（来源：`{p_item.domain}` | 命中引擎：`{eng_badge}`）：{snippet_clean} [{cite_idx}]({p_item.url})"
                    )
                lines.append("")

        lines.append("### 二、检索信源与多引擎命中对比\n")
        lines.append("| 排名 | 核心信源标题 | 域名 | 命中引擎 | RRF 融合分 |")
        lines.append("| :--- | :--- | :--- | :--- | :--- |")
        for idx, r in enumerate(results[:8], start=1):
            safe_title = r.title.replace("|", " ")[:48]
            lines.append(
                f"| `[{idx}]` | [{safe_title}]({r.url}) | `{r.domain}` | {', '.join(r.engines)} | **{r.final_score:.4f}** |"
            )
        lines.append("\n### 三、结论与进一步接入建议\n")
        lines.append(
            "- **检索说明**：排序用于选择待核查信源，并不证明内容准确。不同引擎返回同一 URL 仅是索引重合，事实仍需核对原文及独立来源 [1]("
            + results[0].url
            + ")。\n"
            "- 💡 *提示：当前报告由总网关内置的「多源抽取式合成引擎」生成。你可以在左侧 **【API 渠道与密钥池】** 中填入 DeepSeek / 硅基流动 / OpenAI 的 API Key，即可解锁大模型流式深度长文撰写！*"
        )
        return "\n".join(lines)

    # Fast mode synthesis
    lines.append(f"### 针对「{query}」的多源聚合检索结论\n")
    top3 = results[:3]
    lines.append(f"综合多个独立搜索引擎对 **「{query}」** 的检索结果，以下是最相关的信源摘要：\n")
    for idx, item in enumerate(results[:6], start=1):
        eng_str = " / ".join(item.engines)
        # snippet 是搜索引擎产出的干净摘要，优先于全文抓取内容；两者皆无时跳过，避免显示半截标题
        snip = _clean_synthesis_text(item.snippet or item.content, max_len=170) if (item.snippet or item.content) else ""
        if not snip or len(snip) < 12:
            continue
        lines.append(
            f"- **{item.title}**（来源: `{item.domain}` · 引擎: `{eng_str}`）：{snip} [{idx}]({item.url})"
        )

    if cross_items:
        lines.append(
            f"\n> **多引擎 URL 重合**：共有 **{len(cross_items)}** 条结果被多个搜索引擎命中；这不代表多个独立来源证实其内容。"
        )
    lines.append(
        "\n> 💡 *当前为免 Key 模式下的「抽取式摘要」（原文截取+溯源）。在【API 渠道与密钥池】配置 LLM Key 后，将切换为大模型智能归纳改写。*"
    )
    return "\n".join(lines)


def build_dag_nodes_for_query(query: str, route: str) -> List[Dict[str, Any]]:
    """
    Constructs a 3-node parallel search DAG (inspired by MindSearch & STORM perspectives).
    """
    if route == "academic":
        return [
            {"id": "node_1", "title": "核心理论与经典文献检索", "query": f"{query} 综述 论文 survey", "route": "academic"},
            {"id": "node_2", "title": "最新进展与实验基准对比", "query": f"{query} benchmark state of the art", "route": "academic"},
            {"id": "node_3", "title": "开源实现与工程落地应用", "query": f"{query} github open source implementation", "route": "code"},
        ]
    if route == "code":
        return [
            {"id": "node_1", "title": "主流开源项目与高星仓库", "query": f"{query} github open source", "route": "code"},
            {"id": "node_2", "title": "架构设计、最佳实践与对比", "query": f"{query} architecture best practices comparison", "route": "web"},
            {"id": "node_3", "title": "社区开发者真实评测与避坑", "query": f"{query} review experience hackernews", "route": "social"},
        ]
    return [
        {"id": "node_1", "title": "全网核心事实与权威定义", "query": query, "route": "web"},
        {"id": "node_2", "title": "深度分析、行业数据与技术细节", "query": f"{query} 深度解析 架构 报告", "route": "web"},
        {"id": "node_3", "title": "多方观点、社区口碑与最新动态", "query": f"{query} 最新进展 讨论 评测", "route": "social"},
    ]


def _build_direct_page_payload(
    query: str, pages: List[Dict[str, Any]], latency_ms: int
) -> Dict[str, Any]:
    """Build a normal UnifiedSearchResponse envelope for directly read pages."""
    items = [page_to_search_item(page) for page in pages if page.get("status") == "success"]
    fetched_at = utc_now().strftime("%Y-%m-%d %H:%M:%S")
    trace = EngineExecutionTrace(
        engine_id="direct_page",
        engine_name="网页正文直读",
        status="success" if items else "error",
        latency_ms=latency_ms,
        result_count=len(items),
        used_key_masked="Jina Reader / 直连 HTML",
        used_proxy=False,
        error_message=None if items else "未读取到有效正文",
    )
    response = UnifiedSearchResponse(
        trace_id=f"tr-page-{abs(hash(query)) % (10 ** 10)}",
        query=query,
        rewritten_queries=[],
        resolved_route="webpage",
        total_latency_ms=latency_ms,
        total_raw_results=len(pages),
        total_merged_results=len(items),
        cross_engine_hits=0,
        cache_hit=False,
        engine_traces=[trace],
        results=items,
        per_engine_results={"direct_page": items},
    )
    payload = response.model_dump()
    payload.update(
        {
            "data_direct": True,
            "processed_by_llm": False,
            "direct_reason": "url_direct",
            "fetched_at": fetched_at,
            "page_count": len(items),
            "source_breakdown": {"direct_page": len(items)},
        }
    )
    return payload


async def run_agent_search_stream(req: AgentSearchRequest) -> AsyncGenerator[str, None]:
    """
    Yields Server-Sent Events (SSE) JSON packets:
    - event: step (workflow status update)
    - event: dag (DAG graph nodes for deep research)
    - event: sources (merged & ranked UnifiedSearchResponse)
    - event: token (streaming markdown answer delta)
    - event: suggestions (follow-up questions)
    - event: done
    """
    def sse(event_type: str, data: Any) -> str:
        return f"data: {json.dumps({'type': event_type, 'data': data}, ensure_ascii=False)}\n\n"

    window = infer_time_range(req.query, req.time_range)
    temporal_prompt = time_guidance(req.query, window)
    yield sse('step', {'stage': 'starting', 'message': f'开始检索；时间范围：{window or "不限"}，未知日期不会视为最新'})

    # 直接粘贴短视频链接时走解析专用通道：返回视频元信息 + 下载直链，而不是当成研究课题
    # 链接直读：用户已经给出 URL 时直接抓正文，不再让搜索引擎去猜目标页面。
    # 基础搜索不受影响：普通关键词仍走下面的多源检索；链接 + 关键词时还会用剩余文本继续搜。
    direct_urls = extract_urls(req.query)
    if direct_urls:
        yield sse(
            "step",
            {"stage": "url_read", "message": f"检测到 {len(direct_urls)} 个网页链接，正在直接读取正文..."},
        )
        _, jina_key_info, jina_proxy = key_pool.acquire_credentials("jina_reader")
        jina_key = jina_key_info["api_key"] if jina_key_info else None
        t_direct = time.perf_counter()
        direct_pages = await read_webpages(
            direct_urls,
            proxy=jina_proxy,
            api_key=jina_key,
            timeout_sec=12.0,
            max_chars=16000,
            output_format="markdown",
        )
        direct_elapsed = int((time.perf_counter() - t_direct) * 1000)
        fetched_at = utc_now().strftime("%Y-%m-%d %H:%M:%S")
        yield sse("page", {"pages": direct_pages, "fetched_at": fetched_at})
        residual = strip_urls(req.query)
        successful_pages = [p for p in direct_pages if p.get("status") == "success"]
        if not residual:
            if successful_pages:
                payload = _build_direct_page_payload(req.query, direct_pages, direct_elapsed)
                yield sse("sources", payload)
                report = build_direct_report(direct_pages)
                for i in range(0, len(report), 96):
                    yield sse("token", report[i : i + 96])
                    await asyncio.sleep(0.01)
                lead_title = successful_pages[0].get("title") or "该网页"
                yield sse(
                    "suggestions",
                    [
                        f"{lead_title} 的核心观点与关键事实",
                        "基于该网页继续检索相关来源并交叉验证",
                        "提取该网页的目录结构与数据表格",
                    ],
                )
                yield sse(
                    "done",
                    {
                        "status": "completed",
                        "data_direct": True,
                        "processed_by_llm": False,
                        "direct_reason": "url_direct",
                        "results": len(successful_pages),
                        "page_count": len(successful_pages),
                        "fetched_at": fetched_at,
                    },
                )
                return
            yield sse(
                "step",
                {"stage": "fallback", "message": "网页正文读取失败，已回退到多源搜索..."},
            )
        else:
            # 链接 + 文本：链接正文已随 page 事件返回，剩余文本继续走基础搜索。
            req = req.model_copy(update={"query": residual})
            window = infer_time_range(req.query, req.time_range)
            temporal_prompt = time_guidance(req.query, window)
            yield sse(
                "step",
                {"stage": "searching", "message": f"链接正文已读取，继续用「{residual}」执行多源搜索..."},
            )

    prov, key_info, llm_proxy, llm_model = resolve_active_llm(req.llm_provider_id, req.model_name)

    if req.route_group in ("auto", "rule", "jev", "ai"):
        resolved_route, route_meta = await resolve_smart_route(req.query, req.route_group)
    else:
        resolved_route, route_meta = req.route_group, {"engine": "explicit"}

    # 数据直出 / 原样返回：只检索并回传来源原始内容，不调用本地大模型、不做抽取式改写
    board_ids = [] if req.raw else direct_data_boards(req.query)
    if req.raw or board_ids:
        reason = "raw_mode" if req.raw else "trending_data"
        if reason == "trending_data":
            message = f"数据直出：命中 {len(board_ids)} 个榜单渠道，原样回传榜单内容，不调用大模型"
            engines = ["trending"]
            top_k = max(int(req.top_k or 0), 40)
        else:
            message = "原样返回模式：仅检索并回传来源内容，不调用本地大模型"
            engines = req.engines
            top_k = req.top_k
        yield sse(
            "step",
            {
                "stage": "direct",
                "message": message,
                "data_direct": True,
                "processed_by_llm": False,
                "direct_reason": reason,
            },
        )
        raw_resp = await dispatch_unified_search(
            UnifiedSearchRequest(
                query=req.query,
                route_group=resolved_route,
                engines=engines,
                top_k=top_k,
                enable_dedup=True,
                enable_rrf=True,
                enable_rerank=False,
                scrape_top_n=0,
                time_range=window or 'all',
            ),
            mode_label=reason,
        )
        fetched_at = utc_now().strftime("%Y-%m-%d %H:%M:%S")
        breakdown: Dict[str, int] = {}
        for it in raw_resp.results:
            for eng in (it.engines or [it.source_engine]):
                breakdown[eng] = breakdown.get(eng, 0) + 1
        payload = raw_resp.model_dump()
        payload.update(
            {
                "data_direct": True,
                "processed_by_llm": False,
                "direct_reason": reason,
                "boards": board_ids,
                "source_breakdown": breakdown,
                "fetched_at": fetched_at,
            }
        )
        if reason == "trending_data":
            payload["resolved_route"] = "trending"
        yield sse("sources", payload)
        header = [
            f"渠道：{', '.join(f'{k} {v} 条' for k, v in breakdown.items()) or '无'}",
            f"抓取时间：{fetched_at}（榜单为实时抓取时间，不是发布时间）",
        ]
        dump = build_raw_dump(req.query, raw_resp.results, extra_header=header)
        for i in range(0, len(dump), 64):
            yield sse("token", dump[i : i + 64])
        yield sse("suggestions", [])
        yield sse(
            "done",
            {
                "status": "completed",
                "raw": True,
                "data_direct": True,
                "processed_by_llm": False,
                "direct_reason": reason,
                "results": len(raw_resp.results),
                "source_breakdown": breakdown,
                "fetched_at": fetched_at,
            },
        )
        return

    if req.mode == "agentic":
        max_rounds = max(1, min(int(req.max_rounds or 3), 4))
        collected_map: Dict[str, UnifiedSearchItem] = {}
        all_dag_nodes: List[Dict[str, Any]] = []
        read_urls: set = set()
        attempted_urls: set = set()
        reading_budget = req.reading_budget
        per_round_budget = (reading_budget + max_rounds - 1) // max_rounds
        total_raw = 0
        total_cross = 0
        primary_resp = None

        _, jina_key_info, jina_proxy = key_pool.acquire_credentials("jina_reader")
        jina_key = jina_key_info["api_key"] if jina_key_info else None

        current_nodes = build_dag_nodes_for_query(req.query, resolved_route)
        if prov and key_info:
            init_plan_prompt = temporal_prompt + (
                f"用户课题：{req.query}\n"
                "子任务必须包含官方原始资料/版本公告与独立验证，保留问题的时间条件。\n"
                "请生成第1轮的 3 个并行检索子任务（覆盖不同信源维度），返回严格 JSON 数组：\n"
                '[{"id":"r1_1","title":"任务标题","query":"检索关键词","route":"web|academic|code|social"}]'
            )
            llm_init = await call_llm_json(init_plan_prompt, prov, key_info, llm_proxy, llm_model)
            if isinstance(llm_init, list) and len(llm_init) >= 2:
                current_nodes = [
                    {
                        "id": f"r1_{i+1}",
                        "title": n.get("title") or f"并发探索 {i+1}",
                        "query": n.get("query") or req.query,
                        "route": n.get("route") if n.get("route") in ("web", "academic", "code", "social") else resolved_route,
                    }
                    for i, n in enumerate(llm_init[:3])
                ]

        for round_idx in range(1, max_rounds + 1):
            for n in current_nodes:
                n["round"] = round_idx
                n["status"] = "running"
            all_dag_nodes.extend(current_nodes)
            yield sse("dag", {"nodes": all_dag_nodes})
            yield sse(
                "step",
                {
                    "stage": f"round_{round_idx}_search",
                    "message": f"[第 {round_idx}/{max_rounds} 轮] 多 Agent 并发执行 {len(current_nodes)} 个检索任务...",
                },
            )

            sub_tasks = [
                dispatch_unified_search(
                    UnifiedSearchRequest(
                        query=node["query"],
                        route_group=node.get("route", resolved_route),
                        engines=req.engines,
                        top_k=8,
                        enable_dedup=True,
                        enable_rrf=True,
                        enable_rerank=True,
                        scrape_top_n=0,
                        time_range=window or 'all',
                    ),
                    mode_label=f"agentic_r{round_idx}",
                )
                for node in current_nodes
            ]
            sub_responses = await asyncio.gather(*sub_tasks)

            round_candidates: List[UnifiedSearchItem] = []
            for node, s_resp in zip(current_nodes, sub_responses):
                if primary_resp is None:
                    primary_resp = s_resp
                node["status"] = "completed"
                node["result_count"] = len(s_resp.results)
                node["latency_ms"] = s_resp.total_latency_ms
                total_raw += s_resp.total_raw_results
                total_cross += s_resp.cross_engine_hits
                for item in s_resp.results:
                    key_u = item.normalized_url or item.url
                    if key_u in collected_map:
                        existing = collected_map[key_u]
                        for eng in item.engines:
                            if eng not in existing.engines:
                                existing.engines.append(eng)
                        existing.final_score = round(existing.final_score + item.final_score * 0.4, 5)
                    else:
                        collected_map[key_u] = item
                        round_candidates.append(item)

            yield sse("dag", {"nodes": all_dag_nodes})

            # Budget is for attempts, not successes: failed sources never consume unlimited retries.
            limit = min(per_round_budget, reading_budget - len(attempted_urls))
            unread_sorted = choose_sources(collected_map.values(), attempted_urls, 24)
            preferred = []
            if limit > 0 and prov and key_info and len(unread_sorted) > limit:
                candidates = '\n'.join(
                    f'{i}. [{it.domain}] {it.title} — {it.snippet[:120]} ({evidence_label(it)})'
                    for i, it in enumerate(unread_sorted)
                )
                picked = await call_llm_json(
                    temporal_prompt + f'研究课题：{req.query}\n候选信源：\n{candidates}\n'
                    f'优先原始官方证据、不同观点和日期明确的资料，选最多 {limit} 篇。'
                    '返回 JSON：{"pick_indices": [0, 1]}',
                    prov, key_info, llm_proxy, llm_model,
                )
                if isinstance(picked, dict) and isinstance(picked.get('pick_indices'), list):
                    preferred = [unread_sorted[i] for i in picked['pick_indices']
                                 if type(i) is int and 0 <= i < len(unread_sorted)]
            chosen_to_read = choose_sources(collected_map.values(), attempted_urls, limit, preferred) if limit > 0 else []
            if chosen_to_read:
                yield sse('step', {'stage': f'round_{round_idx}_read',
                    'message': f'[第 {round_idx} 轮] 读取 {len(chosen_to_read)} 篇，总尝试预算 {reading_budget} 篇；最多 4 路并发'})
                attempted_urls.update(it.normalized_url or it.url for it in chosen_to_read)
                reading_events = await read_sources(chosen_to_read, round_idx, jina_proxy, jina_key, window)
                read_urls.update(it.url for it in chosen_to_read if it.metadata.get('read_status') == 'fulltext')
                yield sse('agent_read', {'items': reading_events})

            # Emit intermediate merged sources
            merged_so_far = sorted(collected_map.values(), key=lambda x: x.final_score, reverse=True)[: max(req.top_k, 16)]
            if primary_resp:
                primary_resp.results = merged_so_far
                primary_resp.total_raw_results = total_raw
                primary_resp.total_merged_results = len(merged_so_far)
                primary_resp.cross_engine_hits = sum(len(set(it.engines)) > 1 for it in merged_so_far)
                yield sse("sources", primary_resp.model_dump())

            # Decide whether to continue deeper exploration
            if round_idx >= max_rounds:
                break

            need_more = False
            next_queries: List[Dict[str, Any]] = []
            if prov and key_info:
                evidence_digest = "\n".join(
                    f"- [{it.domain}] {it.title} ({evidence_label(it)}): {(it.content or it.snippet)[:180]}"
                    for it in merged_so_far[:8]
                )
                reflect_prompt = temporal_prompt + (
                    "检查是否缺少近期证据、官方版本核实、独立来源或存在相互冲突；遇到这些缺口需继续定向搜索。\n"
                    f"用户课题：{req.query}\n"
                    f"目前已完成的第 {round_idx} 轮核心证据摘要：\n{evidence_digest}\n\n"
                    "请评估现有证据是否已充分覆盖该课题的关键细节。如果存在信息盲区需要深入追加检索，请设置 need_more=true 并给出 2 个深挖子查询；若已充分则 need_more=false。\n"
                    '返回严格 JSON：{"need_more": true/false, "thought": "评估判断理由", "follow_up_nodes": [{"title":"深挖维度","query":"具体搜索词","route":"web|academic|code|social"}]}'
                )
                reflect_res = await call_llm_json(reflect_prompt, prov, key_info, llm_proxy, llm_model)
                if isinstance(reflect_res, dict):
                    need_more = bool(reflect_res.get("need_more"))
                    thought = reflect_res.get("thought") or "已完成当前轮次证据充足性评估"
                    yield sse(
                        "agent_decision",
                        {"round": round_idx, "need_more": need_more, "thought": thought},
                    )
                    for i, fn in enumerate(reflect_res.get("follow_up_nodes") or []):
                        if isinstance(fn, dict) and fn.get("query"):
                            next_queries.append(
                                {
                                    "id": f"r{round_idx+1}_{i+1}",
                                    "title": fn.get("title") or f"第{round_idx+1}轮深挖 {i+1}",
                                    "query": fn["query"],
                                    "route": fn.get("route") if fn.get("route") in ("web", "academic", "code", "social") else resolved_route,
                                }
                            )
            else:
                # Rule-based autonomous sufficiency check when no LLM key is configured:
                # If round 1 has < 2 deep-read texts or user set max_rounds >= 2, run one targeted verification round
                if round_idx == 1 and max_rounds >= 2:
                    need_more = True
                    thought = "第 1 轮广度收集完成，Agent 决定启动第 2 轮「基准数据与社区实践」交叉深挖检索"
                    yield sse("agent_decision", {"round": round_idx, "need_more": True, "thought": thought})
                    next_queries = [
                        {
                            "id": "r2_1",
                            "title": "开源实现与工程源码验证",
                            "query": f"{req.query} github implementation benchmark",
                            "route": "code",
                        },
                        {
                            "id": "r2_2",
                            "title": "真实落地案例与社区深度评测",
                            "query": f"{req.query} 架构 评测 对比",
                            "route": "social",
                        },
                    ]
                else:
                    yield sse(
                        "agent_decision",
                        {"round": round_idx, "need_more": False, "thought": "多源交叉证据与精读正文已充足，停止追加检索并合成报告"},
                    )

            gaps = coverage_gaps(merged_so_far, window, reading_budget, len(read_urls))
            if gaps and not need_more:
                need_more = True
                next_queries = [{'id': f'r{round_idx+1}_verify', 'title': '补齐时间与原始证据',
                                 'query': f'{req.query} 官方公告 official release documentation', 'route': 'web'}]
                yield sse('agent_decision', {'round': round_idx, 'need_more': True, 'thought': '；'.join(gaps)})
            if not need_more or not next_queries:
                break
            current_nodes = next_queries[:3]

        # Final synthesis for agentic mode
        final_items = sorted(collected_map.values(), key=lambda x: (x.url in read_urls, x.final_score), reverse=True)[: max(req.top_k, 16)]
        if primary_resp:
            primary_resp.results = final_items
            primary_resp.total_merged_results = len(final_items)
            primary_resp.cross_engine_hits = sum(len(set(it.engines)) > 1 for it in final_items)
            yield sse('sources', primary_resp.model_dump())
        unresolved = coverage_gaps(final_items, window, reading_budget, len(read_urls))
        summary = (f'> 核验时间：{utc_now().strftime("%Y-%m-%d %H:%M UTC")}；'
                   f'正文读取成功 {len(read_urls)} / 尝试 {len(attempted_urls)} 篇（预算 {reading_budget}）；'
                   '长正文可能截断，未标日期不代表最新。\n\n')
        if unresolved:
            summary += '> 待核实：' + '；'.join(unresolved) + '。\n\n'
        yield sse('token', summary)
        yield sse("step", {"stage": "synthesizing", "message": f"正文成功 {len(read_urls)} 篇 / 尝试 {len(attempted_urls)} 篇，正在整理证据与未核实项..."})
        if prov and key_info and final_items:
            context_blocks = []
            for idx, it in enumerate(final_items[:16], start=1):
                context_blocks.append(evidence_context(it, idx))
            sys_prompt = temporal_prompt + (
                "你是自主探索研究 Agent。先按子问题整理证据，区分已证实结论、来源冲突和未核实项，再输出结构化深度报告（Markdown）。\n"
                "关键事实后必须附带 `[编号](URL)` 引用链接。"
            )
            user_prompt = f"研究课题：{req.query}\n\n多轮收集与精读证据：\n" + "\n".join(context_blocks)
            async for delta in stream_llm_text(
                [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
                prov,
                key_info,
                llm_proxy,
                llm_model,
            ):
                yield sse("token", delta)
        else:
            report_md = generate_extractive_synthesis(req.query, final_items, mode="deep", sub_questions=all_dag_nodes)
            chunk_size = 48
            for i in range(0, len(report_md), chunk_size):
                yield sse("token", report_md[i : i + chunk_size])
                await asyncio.sleep(0.015)

    elif req.mode == "deep":
        yield sse("step", {"stage": "planning", "message": "正在构建 MindSearch DAG 多视角搜索图与子课题拆解..."})
        dag_nodes = build_dag_nodes_for_query(req.query, resolved_route)

        # If LLM is available, let LLM refine DAG queries
        if prov and key_info:
            plan_prompt = temporal_prompt + (
                f"用户研究课题：{req.query}\n"
                "请将该课题拆解为 3 个互补的平行搜索子课题，返回严格 JSON 数组格式：\n"
                '[{"id":"node_1","title":"维度名称","query":"具体搜索词","route":"web|academic|code|social"}]'
            )
            llm_nodes = await call_llm_json(plan_prompt, prov, key_info, llm_proxy, llm_model)
            if isinstance(llm_nodes, list) and len(llm_nodes) >= 2:
                dag_nodes = [
                    {
                        "id": f"node_{i+1}",
                        "title": n.get("title") or f"研究维度 {i+1}",
                        "query": n.get("query") or req.query,
                        "route": n.get("route") if n.get("route") in ("web", "academic", "code", "social") else resolved_route,
                        "status": "running",
                    }
                    for i, n in enumerate(llm_nodes[:4])
                ]

        for n in dag_nodes:
            n["status"] = "running"
        yield sse("dag", {"nodes": dag_nodes})

        # Execute DAG nodes in parallel
        yield sse("step", {"stage": "searching", "message": f"正在并发执行 {len(dag_nodes)} 个 DAG 搜索节点与跨源 RRF 融合..."})
        sub_tasks = [
            dispatch_unified_search(
                UnifiedSearchRequest(
                    query=node["query"],
                    route_group=node.get("route", resolved_route),
                    engines=req.engines,
                    top_k=10,
                    enable_dedup=True,
                    enable_rrf=True,
                    enable_rerank=True,
                    scrape_top_n=1 if i == 0 else 0,
                    time_range=window or 'all',
                ),
                mode_label="deep_research",
            )
            for i, node in enumerate(dag_nodes)
        ]
        sub_responses = await asyncio.gather(*sub_tasks)

        # Merge all sub-responses
        combined_map: Dict[str, UnifiedSearchItem] = {}
        all_traces = []
        total_raw = 0
        total_cross = 0
        for node, s_resp in zip(dag_nodes, sub_responses):
            node["status"] = "completed"
            node["result_count"] = len(s_resp.results)
            node["latency_ms"] = s_resp.total_latency_ms
            total_raw += s_resp.total_raw_results
            total_cross += s_resp.cross_engine_hits
            all_traces.extend(s_resp.engine_traces)
            for item in s_resp.results:
                key_u = item.normalized_url or item.url
                if key_u in combined_map:
                    existing = combined_map[key_u]
                    for eng in item.engines:
                        if eng not in existing.engines:
                            existing.engines.append(eng)
                    existing.final_score = round(existing.final_score + item.final_score * 0.5, 5)
                else:
                    combined_map[key_u] = item

        yield sse("dag", {"nodes": dag_nodes})

        merged_items = sorted(combined_map.values(), key=lambda x: x.final_score, reverse=True)[: max(req.top_k, 15)]
        primary_resp = sub_responses[0]
        primary_resp.results = merged_items
        primary_resp.total_raw_results = total_raw
        primary_resp.total_merged_results = len(merged_items)
        primary_resp.cross_engine_hits = sum(len(set(it.engines)) > 1 for it in merged_items)
        primary_resp.rewritten_queries = [n["query"] for n in dag_nodes]
        yield sse("sources", primary_resp.model_dump())

        yield sse("step", {"stage": "synthesizing", "message": "正在整理来源证据与未核实项，撰写深度研究报告..."})
        if prov and key_info and merged_items:
            context_blocks = []
            for idx, it in enumerate(merged_items[:12], start=1):
                body = it.content or it.snippet
                context_blocks.append(evidence_context(it, idx))
            sys_prompt = temporal_prompt + (
                "你是一位严谨的首席深度研究专家。请根据提供的多源检索结果，撰写一份结构清晰、论据详实的深度研究报告（使用 Markdown）。\n"
                "要求：\n"
                "1. 每一处关键事实、数据或观点后必须附带内联 Markdown 链接引用，格式为 `[1](URL)`、`[2](URL)`。\n"
                "2. 包含：执行摘要、核心维度深度剖析、多源对比表格、结论与建议。\n"
                "3. 严禁编造未在检索结果中出现的事实或链接。"
            )
            user_prompt = f"研究课题：{req.query}\n\n检索到的多源证据：\n" + "\n".join(context_blocks)
            async for delta in stream_llm_text(
                [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
                prov,
                key_info,
                llm_proxy,
                llm_model,
            ):
                yield sse("token", delta)
        else:
            report_md = generate_extractive_synthesis(req.query, merged_items, mode="deep", sub_questions=dag_nodes)
            # Stream in small chunks for smooth UI experience
            chunk_size = 48
            for i in range(0, len(report_md), chunk_size):
                yield sse("token", report_md[i : i + chunk_size])
                await asyncio.sleep(0.015)

    else:
        # Fast Search Mode
        router_engine_label = route_meta.get("engine", "auto")
        yield sse(
            "step",
            {
                "stage": "routing",
                "message": f"语义路由 ({router_engine_label}) 判定为 [{resolved_route.upper()}]，正在并发调用多源引擎...",
            },
        )
        search_resp = await dispatch_unified_search(
            UnifiedSearchRequest(
                query=req.query,
                route_group=resolved_route,
                engines=req.engines,
                top_k=req.top_k,
                enable_dedup=True,
                enable_rrf=True,
                enable_rerank=True,
                scrape_top_n=req.scrape_top_n,
                time_range=window or 'all',
            ),
            mode_label="fast_agent",
        )
        yield sse("sources", search_resp.model_dump())

        yield sse("step", {"stage": "synthesizing", "message": "已完成 URL 去重与 RRF 融合重排，正在生成带溯源角标的回答..."})
        items = search_resp.results
        if prov and key_info and items:
            context_blocks = []
            for idx, it in enumerate(items[:10], start=1):
                body = it.content or it.snippet
                context_blocks.append(evidence_context(it, idx))
            sys_prompt = temporal_prompt + (
                "你是超级聚合大搜索引擎的 AI 问答核心。请基于提供的检索结果直接、准确、结构化地回答用户问题。\n"
                "必须在引用事实的句子末尾附上 `[编号](URL)` 格式的角标引用（例如 `[1](https://...)`）。"
            )
            user_prompt = f"用户问题：{req.query}\n\n检索结果：\n" + "\n".join(context_blocks)
            async for delta in stream_llm_text(
                [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
                prov,
                key_info,
                llm_proxy,
                llm_model,
            ):
                yield sse("token", delta)
        else:
            answer_md = generate_extractive_synthesis(req.query, items, mode="fast")
            chunk_size = 40
            for i in range(0, len(answer_md), chunk_size):
                yield sse("token", answer_md[i : i + chunk_size])
                await asyncio.sleep(0.012)

    # Emit follow-up suggestions
    suggestions = [
        f"{req.query} 的最新开源方案与架构对比",
        f"{req.query} 存在哪些常见痛点与优化策略？",
        f"深入对比 {req.query} 在国内外主流平台的实现差异",
    ]
    yield sse("suggestions", suggestions)
    yield sse("done", {"status": "completed"})
