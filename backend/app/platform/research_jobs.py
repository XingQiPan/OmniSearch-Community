"""并行后台研究任务：提交后独立运行，步骤落 SQLite，浏览器断开不影响。

采用后台任务模式，按当前 FastAPI + SQLite
架构收敛为最小闭环：

- `research_jobs` 保存任务状态与最终结果；
- `research_steps` 保存 SSE 事件（token 会按 1 秒合并，避免逐字写库）；
- 每个任务一个 asyncio.Task，消费 `run_agent_search_stream`；
- `/stream` 先从 SQLite 回放，再订阅运行中的内存广播，断线可续看；
- 服务进程重启时，未完成任务标记为 interrupted（不做跨进程续跑）。
"""
import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional, Set

from app.agents.search_agent import run_agent_search_stream
from app.core.database import _db_lock, get_conn
from app.schemas import AgentSearchRequest, ResearchJobCreate

MAX_ACTIVE_JOBS = 3
TOKEN_FLUSH_SECONDS = 1.0


@dataclass
class _Runtime:
    job_id: str
    task: Optional[asyncio.Task] = None
    subscribers: Set[asyncio.Queue] = field(default_factory=set)


_RUNTIME: Dict[str, _Runtime] = {}


# ==================== 数据库 ====================

def _row_to_job(row) -> Dict[str, Any]:
    job = dict(row)
    try:
        job["result_json"] = json.loads(job.get("result_json") or "{}")
    except (TypeError, ValueError):
        job["result_json"] = {}
    job["result_text"] = job.get("result_text") or ""
    return job


def _get_job_row(job_id: str) -> Optional[Dict[str, Any]]:
    with _db_lock:
        conn = get_conn()
        row = conn.execute("SELECT * FROM research_jobs WHERE id = ?", (job_id,)).fetchone()
        conn.close()
    return _row_to_job(row) if row else None


def _update_job(job_id: str, **fields: Any) -> None:
    allowed = {"status", "started_at", "finished_at", "latency_ms", "result_text", "result_json", "error"}
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return
    assignments = ", ".join(f"{key} = ?" for key in updates)
    values = [json.dumps(value, ensure_ascii=False) if key == "result_json" else value
              for key, value in updates.items()]
    with _db_lock:
        conn = get_conn()
        conn.execute(f"UPDATE research_jobs SET {assignments} WHERE id = ?", (*values, job_id))
        conn.commit()
        conn.close()


def _append_step(job_id: str, seq: int, event_type: str, payload: Any) -> None:
    with _db_lock:
        conn = get_conn()
        conn.execute(
            "INSERT INTO research_steps (job_id, seq, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (job_id, seq, event_type, json.dumps(payload, ensure_ascii=False), time.time()),
        )
        conn.commit()
        conn.close()


def _list_steps(job_id: str, after_seq: int = 0, limit: int = 500) -> List[Dict[str, Any]]:
    with _db_lock:
        conn = get_conn()
        rows = conn.execute(
            "SELECT seq, event_type, payload_json, created_at FROM research_steps "
            "WHERE job_id = ? AND seq > ? ORDER BY seq LIMIT ?",
            (job_id, after_seq, limit),
        ).fetchall()
        conn.close()
    steps = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, ValueError):
            payload = None
        steps.append({
            "seq": row["seq"],
            "type": row["event_type"],
            "data": payload,
            "created_at": row["created_at"],
        })
    return steps


# ==================== 事件广播 ====================

def _broadcast(job_id: str, item: Dict[str, Any]) -> None:
    runtime = _RUNTIME.get(job_id)
    if not runtime:
        return
    for queue in list(runtime.subscribers):
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            # 订阅端太慢时丢弃实时事件；重连会从 SQLite 回放补齐。
            continue


def _sse(event_type: str, data: Any, seq: Optional[int] = None) -> str:
    payload: Dict[str, Any] = {"type": event_type, "data": data}
    if seq is not None:
        payload["seq"] = seq
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _parse_sse(chunk: str) -> Optional[Dict[str, Any]]:
    for line in (chunk or "").splitlines():
        if line.startswith("data:"):
            try:
                parsed = json.loads(line[5:].strip())
                return parsed if isinstance(parsed, dict) else None
            except (TypeError, ValueError):
                return None
    return None


# ==================== 任务执行 ====================

async def _run_job(job_id: str, req: AgentSearchRequest) -> None:
    started = time.time()
    t0 = time.perf_counter()
    seq = 0
    token_parts: List[str] = []
    pending_tokens: List[str] = []
    last_flush = time.monotonic()
    final_event: Dict[str, Any] = {}
    status = "succeeded"
    error = ""

    def next_seq() -> int:
        nonlocal seq
        seq += 1
        return seq

    def flush_tokens() -> None:
        nonlocal pending_tokens
        if not pending_tokens:
            return
        text = "".join(pending_tokens)
        pending_tokens = []
        step_seq = next_seq()
        _append_step(job_id, step_seq, "token", text)
        _broadcast(job_id, {"type": "token", "data": text, "seq": step_seq})

    _update_job(job_id, status="running", started_at=started, error="")
    try:
        async for chunk in run_agent_search_stream(req):
            event = _parse_sse(chunk)
            if not event:
                continue
            event_type = str(event.get("type") or "message")
            data = event.get("data")
            if event_type == "token" and isinstance(data, str):
                token_parts.append(data)
                pending_tokens.append(data)
                if time.monotonic() - last_flush >= TOKEN_FLUSH_SECONDS:
                    flush_tokens()
                    last_flush = time.monotonic()
                continue
            if event_type == "done":
                final_event = data if isinstance(data, dict) else {}
            step_seq = next_seq()
            _append_step(job_id, step_seq, event_type, data)
            _broadcast(job_id, {"type": event_type, "data": data, "seq": step_seq})
        flush_tokens()
    except asyncio.CancelledError:
        status = "cancelled"
        error = "任务已取消"
    except Exception as exc:  # noqa: BLE001 - 后台任务必须记录任何异常并结束
        status = "failed"
        error = str(exc)[:500] or exc.__class__.__name__
    finally:
        try:
            flush_tokens()
        except Exception:
            pass
        latency_ms = int((time.perf_counter() - t0) * 1000)
        _update_job(
            job_id,
            status=status,
            finished_at=time.time(),
            latency_ms=latency_ms,
            result_text="".join(token_parts),
            result_json={**final_event, "step_count": seq, "status": status},
            error=error,
        )
        _broadcast(job_id, {
            "type": "end",
            "data": {"status": status, "error": error, "latency_ms": latency_ms, "seq": seq},
            "seq": seq + 1,
        })
        _RUNTIME.pop(job_id, None)


def start_research_job(job_id: str, req: Optional[AgentSearchRequest] = None) -> None:
    runtime = _RUNTIME.get(job_id)
    if runtime and runtime.task and not runtime.task.done():
        return
    job = _get_job_row(job_id)
    if not job:
        return
    if req is None:
        req = AgentSearchRequest(
            query=job["query"],
            mode=job["mode"] if job["mode"] in ("fast", "deep", "agentic") else "deep",
            route_group=job.get("route_group") or "auto",
            top_k=16,
            scrape_top_n=2,
            max_rounds=3,
            reading_budget=10,
        )
    runtime = _RUNTIME.setdefault(job_id, _Runtime(job_id=job_id))
    runtime.task = asyncio.create_task(_run_job(job_id, req))


def create_research_job(payload: ResearchJobCreate) -> Dict[str, Any]:
    with _db_lock:
        conn = get_conn()
        active = conn.execute(
            "SELECT COUNT(*) AS n FROM research_jobs WHERE status IN ('queued', 'running')"
        ).fetchone()["n"]
        conn.close()
    if active >= MAX_ACTIVE_JOBS:
        raise RuntimeError(f"当前已有 {MAX_ACTIVE_JOBS} 个研究任务在运行，请等待完成或先取消")

    job_id = f"rj-{uuid.uuid4().hex[:12]}"
    now = time.time()
    with _db_lock:
        conn = get_conn()
        conn.execute(
            "INSERT INTO research_jobs (id, query, mode, route_group, status, created_at) "
            "VALUES (?, ?, ?, ?, 'queued', ?)",
            (job_id, payload.query.strip(), payload.mode, payload.route_group, now),
        )
        conn.commit()
        conn.close()
    req = AgentSearchRequest(
        query=payload.query.strip(),
        mode=payload.mode,
        route_group=payload.route_group,
        top_k=payload.top_k,
        scrape_top_n=2,
        max_rounds=payload.max_rounds,
        reading_budget=payload.reading_budget,
    )
    start_research_job(job_id, req)
    job = _get_job_row(job_id)
    return job or {"id": job_id, "query": payload.query, "status": "queued"}


def list_research_jobs(status: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
    limit = max(1, min(int(limit or 50), 200))
    with _db_lock:
        conn = get_conn()
        if status:
            rows = conn.execute(
                "SELECT * FROM research_jobs WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM research_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        counts = {
            row["status"]: row["n"]
            for row in conn.execute(
                "SELECT status, COUNT(*) AS n FROM research_jobs GROUP BY status"
            ).fetchall()
        }
        conn.close()
    jobs = []
    for row in rows:
        job = _row_to_job(row)
        text = job.pop("result_text", "") or ""
        job["result_preview"] = text[:240]
        jobs.append(job)
    return {"jobs": jobs, "counts": counts, "active": counts.get("running", 0) + counts.get("queued", 0)}


def get_research_job(job_id: str, include_steps: bool = True) -> Optional[Dict[str, Any]]:
    job = _get_job_row(job_id)
    if not job:
        return None
    job["steps"] = _list_steps(job_id) if include_steps else []
    return job


def cancel_research_job(job_id: str) -> Dict[str, Any]:
    job = _get_job_row(job_id)
    if not job:
        raise KeyError(job_id)
    if job["status"] not in ("queued", "running"):
        raise ValueError(f"任务已结束（{job['status']}），无需取消")
    runtime = _RUNTIME.get(job_id)
    if runtime and runtime.task and not runtime.task.done():
        runtime.task.cancel()
        # 立即落状态，避免前端在任务协程收尾前仍看到 running。
        _update_job(job_id, status="cancelled", finished_at=time.time(), error="任务已取消")
        _broadcast(job_id, {"type": "end", "data": {"status": "cancelled"}})
    else:
        _update_job(job_id, status="cancelled", finished_at=time.time(), error="任务已取消")
        _broadcast(job_id, {"type": "end", "data": {"status": "cancelled"}})
    return _get_job_row(job_id) or job


async def stream_research_job(job_id: str, after_seq: int = 0) -> AsyncGenerator[str, None]:
    job = _get_job_row(job_id)
    if not job:
        yield _sse("error", {"message": "任务不存在"})
        return

    runtime = _RUNTIME.get(job_id)
    queue: Optional[asyncio.Queue] = None
    if runtime:
        queue = asyncio.Queue(maxsize=200)
        runtime.subscribers.add(queue)

    last_seq = after_seq
    try:
        # 先回放已落库步骤，再消费实时队列；按 seq 去重，避免回放与订阅窗口重复。
        for step in _list_steps(job_id, after_seq):
            yield _sse(step["type"], step["data"], step["seq"])
            last_seq = max(last_seq, int(step["seq"]))
        if queue is None:
            yield _sse("end", {"status": job["status"]})
            return
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue
            item_seq = int(item.get("seq") or 0)
            if item_seq and item_seq <= last_seq:
                continue
            last_seq = max(last_seq, item_seq)
            yield _sse(item.get("type") or "message", item.get("data"), item_seq or None)
            if item.get("type") == "end":
                return
    finally:
        if runtime and queue is not None:
            runtime.subscribers.discard(queue)


def recover_research_jobs() -> int:
    """服务启动时把上次进程遗留的 running/queued 任务标记为中断，避免永久占位。"""
    now = time.time()
    with _db_lock:
        conn = get_conn()
        cursor = conn.execute(
            "UPDATE research_jobs SET status = 'interrupted', finished_at = ?, "
            "error = '服务重启，任务已中断；可重新提交' WHERE status IN ('queued', 'running')",
            (now,),
        )
        conn.commit()
        changed = cursor.rowcount
        conn.close()
    return changed
