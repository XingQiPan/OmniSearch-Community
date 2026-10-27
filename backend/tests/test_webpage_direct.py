"""Direct webpage reading: URL detection, page conversion and agent-stream wiring."""
import json
import unittest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from app.agents.search_agent import run_agent_search_stream
from app.providers import webpage
from app.schemas import (
    AgentSearchRequest,
    EngineExecutionTrace,
    UnifiedSearchItem,
    UnifiedSearchResponse,
)


def _page(url="https://example.com/article", content="# 示例标题\n\n这是网页正文。"):
    return {
        "url": url,
        "final_url": url,
        "title": "示例标题",
        "content": content,
        "format": "markdown",
        "length": len(content),
        "status": "success",
        "error": None,
        "published_at": None,
        "retrieved_at": "2026-01-01T00:00:00Z",
        "truncated": False,
        "read_source": "direct_html",
        "latency_ms": 12,
    }


class UrlExtractionTests(unittest.TestCase):
    def test_extracts_and_dedupes_http_urls(self):
        urls = webpage.extract_urls(
            "看下 https://example.com/a?utm_source=x，以及 https://example.com/a?utm_source=x。"
            "另一个 https://example.org/b。"
        )
        self.assertEqual(urls, ["https://example.com/a?utm_source=x", "https://example.org/b"])

    def test_bare_url_only_query_gets_scheme(self):
        self.assertEqual(webpage.extract_urls("example.com/docs"), ["https://example.com/docs"])
        self.assertEqual(webpage.extract_urls("www.example.com/docs"), ["https://www.example.com/docs"])

    def test_keeps_balanced_url_parentheses(self):
        self.assertEqual(
            webpage.extract_urls("看 https://en.wikipedia.org/wiki/Foo_(bar) 。"),
            ["https://en.wikipedia.org/wiki/Foo_(bar)"],
        )

    def test_strip_urls_keeps_searchable_text(self):
        self.assertEqual(webpage.strip_urls("总结 https://example.com/a 的要点"), "总结 的要点")
        self.assertEqual(webpage.strip_urls("https://example.com/a"), "")

    def test_private_targets_are_not_directly_read(self):
        self.assertEqual(webpage.extract_urls("http://127.0.0.1/admin"), [])
        target, error = webpage.validate_target_url("http://192.168.1.5/secret")
        self.assertIsNone(target)
        self.assertIn("内网", error or "")


class ReadWebpagesTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_failure_and_plain_text(self):
        calls = []

        async def fake_read(url, proxy=None, api_key=None, timeout_sec=8.0, min_chars=200, max_chars=16000):
            calls.append(url)
            if "fail" in url:
                return {"text": "", "read_status": "failed", "retrieved_at": "2026-01-01T00:00:00Z",
                        "content_truncated": False, "published_at": None}
            return {"text": "# 标题\n\n**正文** 内容 [链接](https://example.com)",
                    "read_status": "fulltext", "retrieved_at": "2026-01-01T00:00:00Z",
                    "content_truncated": False, "published_at": None, "reader_source": "jina_reader"}

        with patch("app.providers.webpage.read_url_evidence", fake_read):
            results = await webpage.read_webpages(
                ["https://example.com/ok", "https://example.com/fail"], max_chars=120,
                output_format="text",
            )

        self.assertEqual(len(calls), 2)
        ok, failed = results
        self.assertEqual(ok["status"], "success")
        self.assertEqual(ok["title"], "标题")
        self.assertNotIn("**", ok["content"])
        self.assertNotIn("](https://", ok["content"])
        self.assertEqual(failed["status"], "error")
        self.assertIn("前端渲染", failed["error"])

    async def test_bounds_long_content(self):
        async def fake_read(url, proxy=None, api_key=None, timeout_sec=8.0, min_chars=200, max_chars=16000):
            return {"text": "# 长文\n\n" + "x" * 5000, "read_status": "fulltext",
                    "retrieved_at": "2026-01-01T00:00:00Z", "content_truncated": True,
                    "published_at": None}

        with patch("app.providers.webpage.read_url_evidence", fake_read):
            [page] = await webpage.read_webpages(["https://example.com/long"], max_chars=800)

        self.assertLessEqual(page["length"], 800)
        self.assertTrue(page["truncated"])


class WebpageEndpointTests(unittest.TestCase):
    def test_endpoint_returns_direct_content(self):
        from app.main import app

        with patch("app.main.read_webpages", new=AsyncMock(return_value=[_page()])), \
             patch("app.main.key_pool.acquire_credentials", return_value=(None, None, None)):
            client = TestClient(app)
            response = client.post(
                "/api/v1/webpage/read",
                json={"urls": ["https://example.com/article"]},
            )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["success_count"], 1)
        self.assertEqual(body["results"][0]["content"], "# 示例标题\n\n这是网页正文。")

    def test_endpoint_rejects_invalid_scheme(self):
        from app.main import app

        client = TestClient(app)
        response = client.post("/api/v1/webpage/read", json={"urls": ["ftp://example.com/file"]})
        self.assertEqual(response.status_code, 400)
        self.assertIn("非法 URL", response.json()["detail"])


class ReaderFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_spa_meta_description_is_returned_as_summary(self):
        from app.providers import adapters

        def handler(request):
            if request.url.host == "r.jina.ai":
                return httpx.Response(503, text="reader busy")
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text=(
                    "<html><head><title>豆包工作</title>"
                    '<meta name="description" content="这是站点提供的页面摘要，长度足够用于静态回退展示，'
                    '当前页面由前端脚本渲染，因此只能拿到这段描述。">'
                    '</head><body><div id="app"></div></body></html>'
                ),
            )

        @asynccontextmanager
        async def client(*args, **kwargs):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
                yield c

        with patch.object(adapters, "make_async_client", client):
            result = await adapters.read_url_evidence("https://example.test/spa", None, min_chars=60)

        self.assertEqual(result["read_status"], "metadata_only")
        self.assertEqual(result["reader_source"], "meta_description")
        self.assertIn("页面摘要", result["text"])

    async def test_empty_spa_has_actionable_error(self):
        async def fake_read(url, proxy=None, api_key=None, timeout_sec=8.0, min_chars=200, max_chars=16000):
            return {"text": "", "read_status": "failed", "retrieved_at": "2026-01-01T00:00:00Z",
                    "content_truncated": False, "published_at": None, "title": "空页面"}

        with patch("app.providers.webpage.read_url_evidence", fake_read):
            [page] = await webpage.read_webpages(["https://example.test/spa"])

        self.assertEqual(page["status"], "error")
        self.assertIn("前端渲染", page["error"])


class AgentDirectPageTests(unittest.IsolatedAsyncioTestCase):
    async def _collect(self, query):
        packets = []
        async for packet in run_agent_search_stream(AgentSearchRequest(query=query, mode="fast")):
            packets.append(json.loads(packet[len("data: "):]))
        return packets

    async def test_url_only_reads_page_and_skips_search(self):
        with patch("app.agents.search_agent.read_webpages", new=AsyncMock(return_value=[_page()])), \
             patch("app.agents.search_agent.key_pool.acquire_credentials", return_value=(None, None, None)), \
             patch("app.agents.search_agent.dispatch_unified_search", new=AsyncMock()) as search:
            packets = await self._collect("https://example.com/article")

        types = [packet["type"] for packet in packets]
        self.assertIn("page", types)
        self.assertIn("sources", types)
        search.assert_not_awaited()

        page_event = next(packet for packet in packets if packet["type"] == "page")
        self.assertEqual(page_event["data"]["pages"][0]["title"], "示例标题")
        sources = next(packet for packet in packets if packet["type"] == "sources")
        self.assertEqual(sources["data"]["resolved_route"], "webpage")
        self.assertEqual(sources["data"]["direct_reason"], "url_direct")
        self.assertEqual(sources["data"]["results"][0]["content"], "# 示例标题\n\n这是网页正文。")
        report = "".join(packet["data"] for packet in packets if packet["type"] == "token")
        self.assertIn("这是网页正文", report)

    async def test_url_plus_keyword_still_runs_basic_search(self):
        search_response = UnifiedSearchResponse(
            trace_id="tr-test",
            query="总结",
            rewritten_queries=["总结"],
            resolved_route="web",
            total_latency_ms=5,
            total_raw_results=1,
            total_merged_results=1,
            cross_engine_hits=0,
            cache_hit=False,
            engine_traces=[EngineExecutionTrace(engine_id="test", engine_name="测试源", status="success")],
            results=[UnifiedSearchItem(title="普通结果", url="https://result.example/r", source_engine="test")],
        )

        with patch("app.agents.search_agent.read_webpages", new=AsyncMock(return_value=[_page()])), \
             patch("app.agents.search_agent.key_pool.acquire_credentials", return_value=(None, None, None)), \
             patch("app.agents.search_agent.resolve_active_llm", return_value=(None, None, None, "")), \
             patch("app.agents.search_agent.resolve_smart_route",
                   new=AsyncMock(return_value=("web", {"engine": "test"}))), \
             patch("app.agents.search_agent.dispatch_unified_search",
                   new=AsyncMock(return_value=search_response)) as search:
            packets = await self._collect("总结 https://example.com/article 的要点")

        search.assert_awaited_once()
        forwarded = search.await_args.args[0]
        self.assertIn("总结", forwarded.query)
        self.assertNotIn("https://", forwarded.query)
        self.assertIn("page", [packet["type"] for packet in packets])
        self.assertTrue(any(packet["type"] == "sources" for packet in packets))


if __name__ == "__main__":
    unittest.main()
