"""Offline evidence and temporal regression tests; no external APIs or persistent writes."""
import asyncio
import json
import unittest
import httpx
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from app.agents import evidence, search_agent
from app.gateway import freshness, dispatcher
from app.providers import adapters
from app.schemas import AgentSearchRequest, UnifiedSearchItem, UnifiedSearchResponse, UnifiedSearchRequest, EngineExecutionTrace


def item(i, domain=None):
    return UnifiedSearchItem(title=f'Item {i}', url=f'https://{domain or str(i)+".test"}/{i}',
                             source_engine='test', snippet='source summary', final_score=1/(i+1))


class TimeTests(unittest.TestCase):
    def test_intent_and_dates(self):
        self.assertEqual(freshness.infer_time_range('最新模型发布'), 'month')
        self.assertIsNone(freshness.infer_time_range('2024 年最新模型'))
        self.assertIsNone(freshness.infer_time_range('最新模型', 'all'))
        self.assertEqual(freshness.infer_time_range('历史论文', 'year'), 'year')
        now = datetime(2026, 10, 17, tzinfo=timezone.utc)
        self.assertEqual(freshness.parse_date('2 days ago', now).day, 15)
        self.assertIsNone(freshness.parse_date('2099-01-01', now))
        self.assertIsNone(freshness.parse_date('not a date', now))
        self.assertIsNotNone(freshness.parse_date('Fri, 16 Oct 2026 10:00:00 GMT', now))
        source = item(0)
        freshness.annotate_time(source, 'week', now)
        self.assertEqual(source.metadata['freshness'], 'unknown')
        self.assertIsNone(source.published_at)
        source.published_at = '2020-01-01'
        freshness.annotate_time(source, 'week', now)
        self.assertEqual(source.metadata['freshness'], 'stale')

    def test_native_parameters(self):
        self.assertEqual(adapters.time_filter_params('duckduckgo', 'week'), {'df': 'w'})
        self.assertEqual(adapters.time_filter_params('serper', 'month'), {'tbs': 'qdr:m'})
        self.assertEqual(adapters.time_filter_params('brave', 'year'), {'freshness': 'py'})
        self.assertEqual(adapters.time_filter_params('bing_web', 'week'), {})
        self.assertIn('startPublishedDate', adapters.time_filter_params('exa', 'month'))

    def test_diversity_and_dedup(self):
        a, b, c = item(0, 'same.test'), item(1, 'same.test'), item(2, 'other.test')
        self.assertEqual(evidence.choose_sources([a,b,c], set(), 2, [a,a,b]), [a,c])
        self.assertNotIn(a, evidence.choose_sources([a,b,c], {a.url}, 2))


class EvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_reader_challenge_fallback_and_date_provenance(self):
        def handler(request):
            if request.url.host == 'r.jina.ai':
                return httpx.Response(200, text='Published Time: 2099-01-01\nMarkdown Content: Access denied ' + 'x'*300)
            return httpx.Response(200, headers={'content-type':'text/html'}, text=
                '<meta property="article:published_time" content="2026-10-16"><article>' + '正文 '*6000 + '</article>')
        @asynccontextmanager
        async def client(*args, **kwargs):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
                yield c
        with patch.object(adapters, 'make_async_client', client):
            result = await adapters.read_url_evidence('https://example.test/article', None)
        self.assertEqual(result['published_at'], '2026-10-16')
        self.assertEqual(result['reader_source'], 'direct_html')
        self.assertTrue(result['content_truncated'])
        self.assertEqual(len(result['text']), 16000)

    async def test_native_time_parameters_reach_transport(self):
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={'hits':[]})
        @asynccontextmanager
        async def client(*args, **kwargs):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
                yield c
        with patch.object(adapters, 'make_async_client', client):
            await adapters.search_hackernews('sample', 3, None, 5, time_range='week')
        self.assertIn('created_at_i>', requests[0].url.params['numericFilters'])

    async def test_failures_not_counted_as_read_and_bounded_concurrency(self):
        active = peak = 0
        async def read(url, *args):
            nonlocal active, peak
            active += 1
            peak = max(active, peak)
            await asyncio.sleep(.001)
            active -= 1
            return {'text': 'body'*100 if '/0' in url else '', 'read_status': 'fulltext' if '/0' in url else 'failed'}
        sources = [item(i) for i in range(8)]
        with patch.object(evidence, 'read_url_evidence', side_effect=read):
            events = await evidence.read_sources(sources, 1, None, None, 'month')
        self.assertLessEqual(peak, 4)
        self.assertEqual(sum(e['status']=='fulltext' for e in events), 1)
        self.assertEqual(events[1]['status'], 'summary_only')
        self.assertEqual(events[1]['chars'], 0)

    async def test_agent_budget_and_source_order(self):
        async def search(req, **kwargs):
            self.assertEqual(req.time_range, 'month')
            return UnifiedSearchResponse(trace_id='test', query=req.query, resolved_route='web',
                total_latency_ms=1, total_raw_results=16, total_merged_results=16,
                results=[item(i) for i in range(16)])
        async def read(*args):
            return {'text': 'valid body '*100, 'read_status': 'fulltext',
                    'published_at': freshness.utc_now().isoformat(), 'content_truncated': False}
        for budget in (0, 8, 10, 12):
            with patch.object(search_agent, 'resolve_active_llm', return_value=(None,None,None,'')), \
                 patch.object(search_agent, 'dispatch_unified_search', side_effect=search), \
                 patch.object(search_agent.key_pool, 'acquire_credentials', return_value=(None,None,None)), \
                 patch.object(evidence, 'read_url_evidence', side_effect=read):
                packets = [json.loads(p[6:]) async for p in search_agent.run_agent_search_stream(
                    AgentSearchRequest(query='最新模型', route_group='web', mode='agentic', max_rounds=2, reading_budget=budget))]
            reads = [e for p in packets if p['type']=='agent_read' for e in p['data']['items']]
            self.assertEqual(len(reads), budget)
            self.assertEqual(len({e['url'] for e in reads}), budget)
            self.assertEqual(packets[-1]['type'], 'done')
            self.assertTrue(any(p['type']=='token' and '核验时间' in p['data'] for p in packets))

    async def test_time_range_is_forwarded_and_cache_isolated(self):
        provider = {'id':'test', 'health_status':'ready', 'weight':1}
        async def run(**kwargs):
            return EngineExecutionTrace(engine_id='test',engine_name='test',status='success'), [item(0)]
        execute = AsyncMock(side_effect=run)
        dispatcher._SEARCH_CACHE.clear()
        with patch.object(dispatcher,'get_settings', return_value={'enable_cache':True}), \
             patch.object(dispatcher,'get_route_group_config',return_value={'engines':['test']}), \
             patch.object(dispatcher.key_pool,'list_providers',return_value=[provider]), \
             patch.object(dispatcher,'execute_single_engine', execute), \
             patch.object(dispatcher,'_save_trace_log'), patch('app.gateway.fusion.get_settings',return_value={}):
            for window in ['week','month','month']:
                response = await dispatcher.dispatch_unified_search(UnifiedSearchRequest(query='sample', route_group='web', time_range=window))
            self.assertEqual(execute.await_count, 2)
            self.assertEqual(execute.call_args.kwargs['time_range'], 'month')
            self.assertTrue(response.cache_hit)
        dispatcher._SEARCH_CACHE.clear()


if __name__ == '__main__':
    unittest.main()
