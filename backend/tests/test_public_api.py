"""开放 API 平台层的离线回归测试。

覆盖：鉴权、套餐能力门禁、按次数计费、余额不足、幂等重放、错误码信封、
限流响应头、抽取计费、自助注册。全程使用内存 SQLite，不访问外网与生产库。
"""
import json
import sqlite3
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.schemas import EngineExecutionTrace, UnifiedSearchItem, UnifiedSearchResponse


class MemoryConnection(sqlite3.Connection):
    def close(self):
        pass


def _fake_search_results(count: int = 3):
    items = []
    for i in range(count):
        item = UnifiedSearchItem(
            title=f"结果 {i + 1}",
            url=f"https://example{i + 1}.com/post",
            snippet=f"摘要 {i + 1}",
            domain=f"example{i + 1}.com",
            source_engine="bocha",
            engines=["bocha", "bing_web"] if i == 0 else ["bocha"],
        )
        item.final_score = 0.9 - i * 0.1
        item.rrf_score = 0.3 - i * 0.01
        items.append(item)
    return items


async def fake_dispatch(req, mode_label="search"):
    results = _fake_search_results()
    return UnifiedSearchResponse(
        trace_id="tr-unittest",
        query=req.query,
        rewritten_queries=[req.query],
        resolved_route="web",
        total_latency_ms=15,
        total_raw_results=len(results),
        total_merged_results=len(results),
        cross_engine_hits=1,
        cache_hit=False,
        engine_traces=[EngineExecutionTrace(engine_id="bocha", engine_name="博查", status="success")],
        results=results,
    )


def _agent_sse(event_type, data):
    return f"data: {json.dumps({'type': event_type, 'data': data}, ensure_ascii=False)}\n\n"


def fake_agent_stream(report_tokens):
    """模拟工作台 Agent 的事件流：规划 → 精读 → 决策 → 信源 → 报告。"""

    async def stream(req):
        yield _agent_sse("step", {"stage": "starting", "message": "开始检索"})
        yield _agent_sse("dag", {"nodes": [
            {"id": "r1_1", "title": "官方资料", "query": req.query, "route": "web", "round": 1,
             "status": "completed", "result_count": 3, "latency_ms": 20, "internal_note": "不应外泄"},
        ]})
        yield _agent_sse("agent_read", {"items": [
            {"round": 1, "title": "结果 1", "url": "https://example1.com/post", "domain": "example1.com",
             "engines": ["bocha"], "chars": 1200, "status": "fulltext", "truncated": False},
        ]})
        yield _agent_sse("agent_decision", {"round": 1, "need_more": False, "thought": "证据充足"})
        yield _agent_sse("sources", {
            "resolved_route": "web",
            "results": [item.model_dump() for item in _fake_search_results()],
            "engine_traces": [{"engine_id": "bocha", "used_key_masked": "sk-****"}],
        })
        yield _agent_sse("step", {"stage": "synthesizing", "message": "撰写报告"})
        for token in report_tokens:
            yield _agent_sse("token", token)
        yield _agent_sse("suggestions", ["追问一", "追问二"])
        yield _agent_sse("done", {"status": "completed"})

    return stream


def _fake_llm():
    return {"id": "fake_llm"}, {"id": "k1", "api_key": "sk-test"}, None, "fake-model"


class PublicApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = sqlite3.connect(":memory:", factory=MemoryConnection, check_same_thread=False)
        cls.conn.row_factory = sqlite3.Row
        cls.stack = ExitStack()
        for target in (
            "app.core.database.get_conn",
            "app.platform.store.get_conn",
            "app.gateway.key_pool.get_conn",
        ):
            cls.stack.enter_context(patch(target, return_value=cls.conn))
        cls.stack.enter_context(patch("app.platform.router_public.dispatch_unified_search", fake_dispatch))

        async def fake_read(url, proxy, api_key=None, timeout_sec=8.0, min_chars=200):
            return {"text": f"# 标题\n\n{url} 的正文内容", "read_status": "fulltext",
                    "published_at": None, "retrieved_at": "2026-01-01T00:00:00Z",
                    "content_truncated": False}

        cls.stack.enter_context(patch("app.platform.router_public.read_url_evidence", fake_read))
        from app.main import app

        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls.stack.close()
        sqlite3.Connection.close(cls.conn)

    # ---------- helpers ----------
    def _create_client(self, plan_id="basic", units=100):
        payload = {"name": f"测试客户{plan_id}", "email": "", "plan_id": plan_id,
                   "issue_key": True, "key_label": "测试密钥"}
        if units is not None:
            payload["grant_units"] = units
        resp = self.client.post("/api/admin/platform/clients", json=payload)
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        return data["client"], data["api_key"]

    @staticmethod
    def _auth(key):
        return {"Authorization": f"Bearer {key}"}

    def _latest_key_id(self, client_id):
        detail = self.client.get(f"/api/admin/platform/clients/{client_id}").json()
        return detail["keys"][0]["id"]

    # ---------- auth ----------
    def test_missing_key_returns_structured_401(self):
        resp = self.client.post("/v1/search", json={"query": "测试"})
        self.assertEqual(resp.status_code, 401)
        body = resp.json()
        self.assertEqual(body["error"]["code"], "missing_api_key")
        self.assertEqual(body["error"]["type"], "authentication_error")
        self.assertIn("request_id", body["error"])
        self.assertTrue(resp.headers.get("X-Request-Id", "").startswith("req_"))

    def test_invalid_key(self):
        resp = self.client.post("/v1/search", json={"query": "测试"},
                                headers=self._auth("sk-omni-not-a-real-key"))
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], "invalid_api_key")

    def test_revoked_key(self):
        client, key = self._create_client()
        key_id = self._latest_key_id(client["id"])
        self.client.post(f"/api/admin/platform/keys/{key_id}/revoke")
        resp = self.client.get("/v1/me", headers=self._auth(key))
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], "key_revoked")

    # ---------- 搜索与计费 ----------
    def test_search_charges_one_unit_and_returns_usage(self):
        client, key = self._create_client(plan_id="basic", units=10)
        resp = self.client.post("/v1/search", json={"query": "聚合搜索", "max_results": 3},
                                headers=self._auth(key))
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["object"], "search")
        self.assertEqual(len(body["results"]), 3)
        self.assertEqual(body["results"][0]["sources"], ["bocha", "bing_web"])
        self.assertEqual(body["usage"]["units"], 1)
        self.assertAlmostEqual(body["usage"]["cost_cny"], 0.019, places=6)
        self.assertEqual(body["usage"]["remaining_units"], 9)
        self.assertTrue(resp.headers.get("X-RateLimit-Limit"))
        self.assertEqual(resp.headers.get("X-Quota-Remaining"), "9")
        self.assertEqual(resp.headers.get("X-Cache"), "MISS")

        refreshed = self.client.get(f"/api/admin/platform/clients/{client['id']}").json()
        self.assertEqual(refreshed["balance_units"], 9)

    def test_advanced_depth_costs_two_units_on_pro_plan(self):
        _, key = self._create_client(plan_id="pro", units=10)
        resp = self.client.post("/v1/search", json={"query": "深度检索", "search_depth": "advanced"},
                                headers=self._auth(key))
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["usage"]["units"], 2)
        self.assertEqual(resp.json()["usage"]["remaining_units"], 8)

    def test_plan_feature_gate_for_rerank(self):
        _, key = self._create_client(plan_id="basic", units=10)
        resp = self.client.post("/v1/search",
                                json={"query": "测试", "search_depth": "advanced"},
                                headers=self._auth(key))
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "feature_not_in_plan")

    def test_insufficient_balance(self):
        _, key = self._create_client(plan_id="basic", units=1)
        first = self.client.post("/v1/search", json={"query": "第一次"}, headers=self._auth(key))
        self.assertEqual(first.status_code, 200)
        second = self.client.post("/v1/search", json={"query": "第二次"}, headers=self._auth(key))
        self.assertEqual(second.status_code, 402)
        self.assertEqual(second.json()["error"]["code"], "insufficient_balance")

    def test_idempotency_replay_does_not_double_charge(self):
        _, key = self._create_client(plan_id="basic", units=10)
        headers = {**self._auth(key), "Idempotency-Key": "idem-test-001"}
        first = self.client.post("/v1/search", json={"query": "幂等测试"}, headers=headers)
        second = self.client.post("/v1/search", json={"query": "幂等测试"}, headers=headers)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["request_id"], second.json()["request_id"])
        self.assertEqual(second.headers.get("Idempotent-Replayed"), "true")
        usage = self.client.get("/v1/usage", headers=self._auth(key)).json()
        self.assertEqual(usage["totals"]["units"], 1)

    def test_validation_error_is_400_with_details(self):
        _, key = self._create_client()
        resp = self.client.post("/v1/search", json={"query": "测试", "max_results": 999},
                                headers=self._auth(key))
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertEqual(body["error"]["code"], "invalid_request")
        self.assertIn("errors", body["error"]["details"])

    def test_missing_query_has_dedicated_code(self):
        _, key = self._create_client()
        resp = self.client.post("/v1/search", json={"max_results": 3}, headers=self._auth(key))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "missing_query")

    def test_markdown_format(self):
        _, key = self._create_client()
        resp = self.client.post("/v1/search",
                                json={"query": "markdown", "response_format": "markdown"},
                                headers=self._auth(key))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("# markdown", resp.json()["markdown"])

    # ---------- 由浅入深：search_depth / include_trace ----------
    def test_deep_search_scrapes_full_text_without_include_raw_content(self):
        seen = {}

        async def scraping_dispatch(req, mode_label="search"):
            seen["scrape_top_n"] = req.scrape_top_n
            seen["enable_rerank"] = req.enable_rerank
            resp = await fake_dispatch(req, mode_label)
            for item in resp.results[: req.scrape_top_n]:
                item.content = f"{item.title} 的正文"
            return resp

        _, key = self._create_client(plan_id="pro", units=10)
        with patch("app.platform.router_public.dispatch_unified_search", scraping_dispatch):
            resp = self.client.post("/v1/search", json={"query": "深读", "search_depth": "deep"},
                                    headers=self._auth(key))
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(seen, {"scrape_top_n": 3, "enable_rerank": True})
        self.assertEqual(body["usage"]["units"], 3)
        self.assertEqual(body["results"][0]["content"], "结果 1 的正文")

    def test_basic_search_does_not_scrape_or_return_content(self):
        seen = {}

        async def recording_dispatch(req, mode_label="search"):
            seen["scrape_top_n"] = req.scrape_top_n
            return await fake_dispatch(req, mode_label)

        _, key = self._create_client(plan_id="basic", units=10)
        with patch("app.platform.router_public.dispatch_unified_search", recording_dispatch):
            resp = self.client.post("/v1/search", json={"query": "直接搜索"}, headers=self._auth(key))
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(seen["scrape_top_n"], 0)
        self.assertIsNone(resp.json()["results"][0]["content"])
        self.assertIsNone(resp.json()["trace"])

    def test_include_trace_exposes_fanout_but_not_internal_details(self):
        async def traced_dispatch(req, mode_label="search"):
            resp = await fake_dispatch(req, mode_label)
            resp.engine_traces = [
                EngineExecutionTrace(engine_id="bocha", engine_name="博查", status="success",
                                     latency_ms=320, result_count=3, used_key_masked="sk-a****z",
                                     used_proxy=True),
                EngineExecutionTrace(engine_id="google_cse", engine_name="Google", status="error",
                                     latency_ms=90, error_message="403 for url https://x/?key=AIzaSECRET"),
                EngineExecutionTrace(engine_id="tavily", engine_name="Tavily", status="skipped",
                                     error_message="未配置可用 API Key"),
            ]
            return resp

        _, key = self._create_client(plan_id="basic", units=10)
        with patch("app.platform.router_public.dispatch_unified_search", traced_dispatch):
            resp = self.client.post("/v1/search", json={"query": "看过程", "include_trace": True},
                                    headers=self._auth(key))
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        trace = body["trace"]
        self.assertEqual(trace["route"], "web")
        self.assertEqual(trace["cross_engine_hits"], 1)
        self.assertEqual([e["id"] for e in trace["engines"]], ["bocha", "google_cse"])
        self.assertEqual(trace["engines"][0]["latency_ms"], 320)
        raw = json.dumps(trace, ensure_ascii=False)
        for leaked in ("sk-a", "AIzaSECRET", "used_proxy", "未配置"):
            self.assertNotIn(leaked, raw)
        self.assertEqual(body["usage"]["units"], 1)

    # ---------- /v1/research ----------
    def test_research_requires_deep_plan(self):
        _, key = self._create_client(plan_id="basic", units=50)
        resp = self.client.post("/v1/research", json={"query": "研究课题"}, headers=self._auth(key))
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "feature_not_in_plan")

    def test_research_returns_process_sources_and_report(self):
        client, key = self._create_client(plan_id="pro", units=20)
        stream = fake_agent_stream(["## 结论\n\n", "要点 [1](https://example1.com/post)"])
        with patch("app.agents.search_agent.run_agent_search_stream", stream), \
                patch("app.agents.search_agent.resolve_active_llm", _fake_llm):
            resp = self.client.post("/v1/research", json={"query": "Agent 记忆机制", "mode": "agentic"},
                                    headers=self._auth(key))
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["object"], "research")
        self.assertEqual(body["mode"], "agentic")
        self.assertEqual(body["route"], "web")
        self.assertEqual(body["answer"], "## 结论\n\n要点 [1](https://example1.com/post)")
        self.assertTrue(body["llm_generated"])
        self.assertEqual(body["plan"][0]["title"], "官方资料")
        self.assertNotIn("internal_note", body["plan"][0])
        self.assertEqual(body["reads"][0]["status"], "fulltext")
        self.assertNotIn("engines", body["reads"][0])
        self.assertEqual(body["decisions"], [{"round": 1, "need_more": False, "thought": "证据充足"}])
        self.assertEqual(body["results"][0]["id"], "r1")
        self.assertEqual(body["results"][0]["score"], 1.0)
        self.assertEqual(body["suggestions"], ["追问一", "追问二"])
        self.assertEqual(body["usage"]["units"], 8)
        refreshed = self.client.get(f"/api/admin/platform/clients/{client['id']}").json()
        self.assertEqual(refreshed["balance_units"], 12)

    def test_research_falls_back_when_llm_only_returns_warning(self):
        _, key = self._create_client(plan_id="pro", units=20)
        warning = "\n> ⚠️ 大模型流式调用异常 (timeout)，已自动切换为网关内置智能摘要模式。\n"
        with patch("app.agents.search_agent.run_agent_search_stream", fake_agent_stream([warning])), \
                patch("app.agents.search_agent.resolve_active_llm", _fake_llm):
            resp = self.client.post("/v1/research", json={"query": "兜底课题"}, headers=self._auth(key))
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertNotIn("⚠️", body["answer"])
        self.assertIn("兜底课题", body["answer"])
        self.assertFalse(body["llm_generated"])
        self.assertEqual(body["usage"]["units"], 5)

    def test_research_stream_uses_public_event_names(self):
        _, key = self._create_client(plan_id="pro", units=20)
        stream = fake_agent_stream(["报告正文"])
        with patch("app.agents.search_agent.run_agent_search_stream", stream), \
                patch("app.agents.search_agent.resolve_active_llm", _fake_llm):
            resp = self.client.post("/v1/research", json={"query": "流式研究", "stream": True},
                                    headers=self._auth(key))
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertTrue(resp.headers["content-type"].startswith("text/event-stream"))
        events = [line[len("event: "):] for line in resp.text.splitlines() if line.startswith("event: ")]
        self.assertEqual(events[0], "meta")
        for name in ("status", "plan", "read", "decision", "sources", "delta", "suggestions"):
            self.assertIn(name, events)
        self.assertEqual(events[-1], "done")
        self.assertNotIn("token", events)
        self.assertNotIn("used_key_masked", resp.text)
        self.assertTrue(resp.text.rstrip().endswith("data: [DONE]"))

    # ---------- 抽取 ----------
    def test_extract_charges_per_url(self):
        _, key = self._create_client(plan_id="basic", units=10)
        resp = self.client.post("/v1/extract",
                                json={"urls": ["https://a.com/1", "https://b.com/2"]},
                                headers=self._auth(key))
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(body["success_count"], 2)
        self.assertEqual(body["usage"]["units"], 2)
        self.assertEqual(body["usage"]["remaining_units"], 8)

    def test_extract_rejects_bad_url(self):
        _, key = self._create_client()
        resp = self.client.post("/v1/extract", json={"urls": ["ftp://bad"]}, headers=self._auth(key))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["code"], "invalid_url")

    # ---------- 答案与账户 ----------
    def test_answer_requires_plan_feature(self):
        _, key = self._create_client(plan_id="trial")
        resp = self.client.post("/v1/answer", json={"query": "试用版能否用答案"},
                                headers=self._auth(key))
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["error"]["code"], "feature_not_in_plan")

    def test_answer_costs_two_units(self):
        _, key = self._create_client(plan_id="basic", units=10)
        resp = self.client.post("/v1/answer", json={"query": "带引用的答案"},
                                headers=self._auth(key))
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertTrue(body["citations"])
        self.assertEqual(body["usage"]["units"], 2)

    def test_me_endpoint(self):
        _, key = self._create_client(plan_id="pro", units=100)
        resp = self.client.get("/v1/me", headers=self._auth(key))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["plan"]["id"], "pro")
        self.assertEqual(body["balance_units"], 100)
        self.assertTrue(body["limits"]["allow_rerank"])

    def test_models_and_health_are_public(self):
        models = self.client.get("/v1/models")
        self.assertEqual(models.status_code, 200)
        self.assertEqual(len(models.json()["data"]), 4)
        health = self.client.get("/v1/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")

    # ---------- 管理端 ----------
    def test_topup_and_invoice(self):
        client, key = self._create_client(plan_id="basic", units=0)
        topup = self.client.post(f"/api/admin/platform/clients/{client['id']}/topup",
                                 json={"amount_cny": 19})
        self.assertEqual(topup.status_code, 200, topup.text)
        self.assertEqual(topup.json()["client"]["balance_units"], 1000)

        self.client.post("/v1/search", json={"query": "开票测试"}, headers=self._auth(key))
        invoice = self.client.get("/api/admin/platform/invoices").json()
        row = next(i for i in invoice["items"] if i["client_id"] == client["id"])
        self.assertEqual(row["requests"], 1)
        self.assertEqual(row["units"], 1)

    def test_self_serve_signup_issues_trial_key(self):
        resp = self.client.post("/v1/signup", json={"name": "自助客户", "email": "selfserve@example.com"})
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertTrue(body["api_key"].startswith("sk-omni-"))
        self.assertEqual(body["balance_units"], 500)
        search = self.client.post("/v1/search", json={"query": "自助试用"},
                                  headers=self._auth(body["api_key"]))
        self.assertEqual(search.status_code, 200)

    def test_overview_aggregates(self):
        resp = self.client.get("/api/admin/platform/overview?days=7")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        for key in ("requests", "units", "revenue_cny", "clients_total", "p95_latency_ms"):
            self.assertIn(key, body["kpis"])
        self.assertIn("series", body)
        self.assertIn("plan_distribution", body)

    def test_meta_catalog(self):
        body = self.client.get("/api/admin/platform/meta").json()
        paths = [e["path"] for e in body["endpoints"]]
        self.assertIn("/v1/search", paths)
        codes = [e["code"] for e in body["errors"]]
        self.assertIn("insufficient_balance", codes)


if __name__ == "__main__":
    unittest.main()

