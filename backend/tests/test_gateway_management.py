"""Offline regression tests; never connect to external APIs or production SQLite."""
import asyncio
import json
import sqlite3
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from app.core import database
from app.gateway import dispatcher
from app.gateway.key_pool import KeyPoolManager, current_day_usage
from app.schemas import EngineExecutionTrace, UnifiedSearchItem, UnifiedSearchRequest


class MemoryConnection(sqlite3.Connection):
    def close(self):
        pass


class KeyUsageTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:', factory=MemoryConnection)
        self.conn.row_factory = sqlite3.Row
        self.db_patch = patch('app.core.database.get_conn', return_value=self.conn)
        self.key_patch = patch('app.gateway.key_pool.get_conn', return_value=self.conn)
        self.db_patch.start()
        self.key_patch.start()
        database.init_db()
        yesterday = (datetime.now() - timedelta(days=1)).timestamp()
        self.conn.execute(
            'INSERT INTO api_keys (id, provider_id, label, api_key, used_today, total_used, daily_quota, last_used_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            ('test-key', 'tavily', 'test', 'unit-test-secret-only', 8, 12, 8, yesterday),
        )
        self.conn.commit()
        self.pool = KeyPoolManager()

    def tearDown(self):
        self.key_patch.stop()
        self.db_patch.stop()
        sqlite3.Connection.close(self.conn)

    def test_read_projection_hides_plaintext_and_does_not_write(self):
        provider = next(p for p in self.pool.list_providers() if p['id'] == 'tavily')
        key = provider['keys'][0]
        self.assertNotIn('api_key', key)
        self.assertNotIn('unit-test-secret-only', json.dumps(provider))
        self.assertEqual(key['used_today'], 0)
        self.assertEqual(key['total_used'], 12)
        self.assertEqual(self.conn.execute('SELECT used_today FROM api_keys').fetchone()[0], 8)

    def test_key_becomes_eligible_next_day_and_failure_counts(self):
        _, key, _ = self.pool.acquire_credentials('tavily')
        self.assertEqual(key['id'], 'test-key')
        self.pool.record_execution('tavily', key['id'], False, 200, 'mock failure')
        row = self.conn.execute('SELECT * FROM api_keys').fetchone()
        self.assertEqual(row['used_today'], 1)
        self.assertEqual(row['total_used'], 13)
        self.pool.record_execution('tavily', key['id'], True, 100)
        row = self.conn.execute('SELECT * FROM api_keys').fetchone()
        self.assertEqual(row['used_today'], 2)
        self.assertEqual(row['total_used'], 14)

    def test_today_projection(self):
        self.assertEqual(current_day_usage({'last_used_at': time.time(), 'used_today': 3}), 3)


class RoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_route_defaults_explicit_override_and_cache_isolation(self):
        group = {'id': 'web', 'engines': ['test'], 'fallback_engines': [],
                 'top_k': 1, 'timeout_ms': 3100, 'enable_rerank': False, 'scrape_top_n': 0}
        provider = {'id': 'test', 'weight': 1.0, 'health_status': 'ready'}

        async def execute(**kwargs):
            return (EngineExecutionTrace(engine_id='test', engine_name='test', status='success'),
                    [UnifiedSearchItem(title=f'Item {i}', url=f'https://example.com/{i}', source_engine='test')
                     for i in range(3)])

        executor = AsyncMock(side_effect=execute)
        dispatcher._SEARCH_CACHE.clear()
        with patch.object(dispatcher, 'get_route_group_config', return_value=group), \
             patch.object(dispatcher, 'get_settings', return_value={'enable_cache': True}), \
             patch.object(dispatcher.key_pool, 'list_providers', return_value=[provider]), \
             patch.object(dispatcher, 'execute_single_engine', executor), \
             patch.object(dispatcher, '_save_trace_log'), \
             patch('app.gateway.fusion.get_settings', return_value={}):
            result = await dispatcher.dispatch_unified_search(UnifiedSearchRequest(query='test', route_group='web'))
            self.assertEqual(len(result.results), 1)
            self.assertEqual(executor.call_args.kwargs['timeout_sec'], 3.1)
            override = await dispatcher.dispatch_unified_search(UnifiedSearchRequest(query='test', route_group='web', top_k=3))
            self.assertEqual(len(override.results), 3)
            self.assertFalse(override.cache_hit)
            cached = await dispatcher.dispatch_unified_search(UnifiedSearchRequest(query='test', route_group='web', top_k=3))
            self.assertTrue(cached.cache_hit)
            self.assertEqual(executor.await_count, 2)
        dispatcher._SEARCH_CACHE.clear()


if __name__ == '__main__':
    unittest.main()
