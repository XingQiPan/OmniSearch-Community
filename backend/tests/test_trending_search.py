"""热榜检索接入与原样返回模式的离线回归。"""
import json
import unittest
from unittest.mock import AsyncMock, patch

from app.agents import search_agent
from app.agents.evidence import build_raw_dump
from app.providers import trending_search
from app.providers.adapters import SEARCH_ADAPTER_REGISTRY
from app.core.database import init_db
from app.schemas import AgentSearchRequest, UnifiedSearchItem, UnifiedSearchResponse

init_db()


class TrendingMatchTests(unittest.TestCase):
    def test_registered_and_keyword_matching(self):
        self.assertIs(SEARCH_ADAPTER_REGISTRY.get('trending'), trending_search.search_trending)
        for query, expected in [('抖音', 'douyin_hot'), ('微博热搜', 'weibo_hot'),
                                ('B站排行', 'bilibili_rank'), ('掘金', 'juejin_hot')]:
            self.assertIn(expected, trending_search.match_boards(query))
        self.assertEqual(trending_search.match_boards('量子纠缠 论文'), [])
        self.assertEqual(trending_search.match_boards(''), [])
        generic = trending_search.match_boards('今天的热榜')
        self.assertTrue(generic and len(generic) <= trending_search.GENERIC_BOARD_LIMIT)

    def test_platform_expands_to_all_its_boards(self):
        self.assertIn('douyin_hot', trending_search.match_boards('抖音'))
        self.assertIn('bilibili_rank', trending_search.match_boards('B站'))

    def test_direct_data_only_for_pure_data_queries(self):
        self.assertTrue(trending_search.direct_data_boards('抖音热榜'))
        self.assertTrue(trending_search.direct_data_boards('微博热搜'))
        self.assertEqual(trending_search.direct_data_boards('抖音热榜 分析下趋势'), [])
        self.assertEqual(trending_search.direct_data_boards('量子纠缠 论文'), [])
        # 仅平台名/普通检索意图不再自动直出，避免"没开开关却拿到榜单"
        self.assertEqual(trending_search.direct_data_boards('抖音'), [])
        self.assertEqual(trending_search.direct_data_boards('b站最火up主'), [])

    def test_board_count_is_bounded(self):
        self.assertLessEqual(len(trending_search.match_boards('百度 微博 抖音 b站 知乎 掘金')), 4)


class TrendingFetchTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_network_when_unmatched(self):
        async def boom(*args, **kwargs):
            raise AssertionError('无关查询不得触发任何抓取')
        with patch.object(trending_search, 'fetch_trending_board', boom):
            self.assertEqual(await trending_search.search_trending('量子纠缠', 10, None, 5), [])

    async def test_items_carry_board_metadata_but_no_fake_publish_date(self):
        from app.schemas import TrendingBoard, TrendingItem
        board = TrendingBoard(board_id='douyin_hot', name='抖音热点', source='douyin.com',
                              category='comprehensive', emoji='🔥', site_url='https://www.douyin.com/hot',
                              status='success', fetched_at='2026-10-18 10:00:00')
        board.items = [TrendingItem(rank=1, title='热榜第一', url='', hot_value='900万', video_platform='douyin')]
        failed = TrendingBoard(board_id='other', name='其它榜', source='x.test', category='comprehensive',
                               emoji='', site_url='https://x.test', status='failed', fetched_at='')

        async def fake_fetch(board_id, **kwargs):
            return board if board_id == 'douyin_hot' else failed

        with patch.object(trending_search, 'fetch_trending_board', side_effect=fake_fetch):
            items = await trending_search.search_trending('抖音', 5, None, 5)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].url, 'https://www.douyin.com/hot?rank=1')
        self.assertIsNone(items[0].published_at)
        self.assertEqual(items[0].metadata['board_fetched_at'], '2026-10-18 10:00:00')
        self.assertEqual(items[0].metadata['rank'], 1)

    async def test_failed_board_is_skipped(self):
        async def boom(*args, **kwargs):
            raise RuntimeError('source down')
        with patch.object(trending_search, 'fetch_trending_board', boom):
            self.assertEqual(await trending_search.search_trending('抖音', 5, None, 5), [])


class RawModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_raw_mode_skips_model_and_returns_content(self):
        items = [UnifiedSearchItem(title='抖音热点 #1 测试', url='https://www.douyin.com/hot',
                                   source_engine='trending', engines=['trending'],
                                   snippet='热度：900万', metadata={'board_name': '抖音热点', 'rank': 1})]

        async def fake_dispatch(req, **kwargs):
            self.assertEqual(req.time_range, 'all')
            return UnifiedSearchResponse(trace_id='t', query=req.query, resolved_route='web',
                                         total_latency_ms=1, total_raw_results=1,
                                         total_merged_results=1, results=items)

        async def forbidden(*args, **kwargs):
            raise AssertionError('原样返回模式不得调用本地大模型')
            yield ''

        with patch.object(search_agent, 'dispatch_unified_search', fake_dispatch), \
             patch.object(search_agent, 'stream_llm_text', forbidden), \
             patch.object(search_agent, 'get_settings', lambda: {}), \
             patch.object(search_agent, 'resolve_smart_route', AsyncMock(return_value=('web', {'engine': 'rule'}))):
            packets = [json.loads(p[6:]) async for p in search_agent.run_agent_search_stream(
                AgentSearchRequest(query='抖音热榜', mode='fast', raw=True))]
        kinds = [p['type'] for p in packets]
        self.assertEqual(kinds[0], 'step')
        self.assertIn('sources', kinds)
        self.assertEqual(kinds[-1], 'done')
        answer = ''.join(p['data'] for p in packets if p['type'] == 'token')
        self.assertIn('未经任何大模型处理', answer)
        self.assertIn('抖音热点 第 1 名', answer)

    async def test_trending_data_query_is_direct_without_llm(self):
        items = [UnifiedSearchItem(title='抖音热点 #1 测试', url='https://www.douyin.com/hot',
                                   source_engine='trending', engines=['trending'],
                                   snippet='热度：900万', metadata={'board_name': '抖音热点', 'rank': 1})]

        async def fake_dispatch(req, **kwargs):
            self.assertEqual(req.engines, ['trending'])
            self.assertGreaterEqual(req.top_k, 40)
            return UnifiedSearchResponse(trace_id='t', query=req.query, resolved_route='custom',
                                         total_latency_ms=1, total_raw_results=1,
                                         total_merged_results=1, results=items)

        async def forbidden(*args, **kwargs):
            raise AssertionError('榜单数据直出不得调用本地大模型')
            yield ''

        with patch.object(search_agent, 'dispatch_unified_search', fake_dispatch), \
             patch.object(search_agent, 'stream_llm_text', forbidden), \
             patch.object(search_agent, 'get_settings', lambda: {}), \
             patch.object(search_agent, 'resolve_smart_route', AsyncMock(return_value=('web', {'engine': 'rule'}))):
            packets = [json.loads(p[6:]) async for p in search_agent.run_agent_search_stream(
                AgentSearchRequest(query='抖音热榜', mode='agentic'))]
        sources = [p for p in packets if p['type'] == 'sources']
        done = [p for p in packets if p['type'] == 'done'][-1]
        self.assertEqual(sources[0]['data']['resolved_route'], 'trending')
        self.assertTrue(sources[0]['data']['data_direct'])
        self.assertFalse(sources[0]['data']['processed_by_llm'])
        self.assertEqual(sources[0]['data']['source_breakdown'], {'trending': 1})
        self.assertEqual(done['data']['direct_reason'], 'trending_data')
        answer = ''.join(p['data'] for p in packets if p['type'] == 'token')
        self.assertIn('抓取时间', answer)

    def test_raw_dump_is_verbatim(self):
        item = UnifiedSearchItem(title='T', url='https://x.test', source_engine='s',
                                 snippet='原始摘要', content='正文' * 700)
        dump = build_raw_dump('q', [item])
        self.assertIn('原始摘要', dump)
        self.assertIn('已截断', dump)
        self.assertIn('未经任何大模型处理', dump)


if __name__ == '__main__':
    unittest.main()
