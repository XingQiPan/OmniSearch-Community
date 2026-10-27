"""Offline, deterministic ranking/domain regression. No APIs or persistent DB."""
import unittest
from unittest.mock import patch
from contextlib import asynccontextmanager
import httpx

from app.gateway import fusion, dispatcher
from app.schemas import UnifiedSearchItem
from app.agents.search_agent import generate_extractive_synthesis


def item(url, score=.02):
    return UnifiedSearchItem(title='Title', url=url, snippet='text', source_engine='test', final_score=score)


class FusionTests(unittest.TestCase):
    def fuse(self, sources, **kwargs):
        with patch.object(fusion, 'get_settings', return_value={'boosted_domains':['example.com']}):
            return fusion.fuse_and_deduplicate(sources, {}, **kwargs)

    def test_duplicate_engine_vote_is_counted_once(self):
        a = item('https://example.com/a')
        dup = item('http://www.example.com/a/?utm_source=x')
        expected,_ = self.fuse({'a':[a]})
        actual,hits = self.fuse({'a':[a,dup,dup]})
        self.assertEqual(actual[0].final_score, expected[0].final_score)
        self.assertEqual(hits, 0)
        results,hits = self.fuse({'a':[a,dup], 'b':[a]})
        self.assertEqual(hits, 1)
        self.assertEqual(results[0].positions, {'a':1,'b':1})
        self.assertEqual(len(self.fuse({'a':[a,dup]}, enable_dedup=False)[0]), 1)
        self.assertEqual(a.engines, [])  # input objects must not be mutated

    def test_host_rules_and_boosts(self):
        for host in ['example.com','docs.example.com','EXAMPLE.COM.']:
            self.assertTrue(fusion.domain_matches(host,'example.com'))
        for host in ['notexample.com','example.com.evil.test','evil-example.com','bad..example.com']:
            self.assertFalse(fusion.domain_matches(host,'example.com'))
        self.assertFalse(fusion.domain_matches('x.127.0.0.1','127.0.0.1'))
        self.assertEqual(fusion.extract_domain('https://user@example.com:443/a'),'example.com')
        self.assertTrue(fusion.domain_matches('xn--bcher-kva.de','bücher.de'))
        urls=['https://example.com/a','https://docs.example.com/a','https://notexample.com/a',
              'https://example.com.evil.test/a','https://other.test/example.com?q=example.com']
        sources={str(i):[item(url)] for i,url in enumerate(urls)}
        allowed,_ = self.fuse(sources, include_domains=['example.com'])
        self.assertEqual({x.url for x in allowed},set(urls[:2]))
        excluded,_ = self.fuse(sources, exclude_domains=['example.com'])
        self.assertEqual({x.url for x in excluded},set(urls[2:]))
        results,_ = self.fuse(sources)
        self.assertGreater(results[0].final_score, next(x.final_score for x in results if x.url==urls[2]))

    def test_engine_order_and_ties_are_stable(self):
        a,b=item('https://a.test/'),item('https://b.test/')
        first,_=self.fuse({'a':[a],'b':[b]})
        second,_=self.fuse({'b':[b],'a':[a]})
        self.assertEqual([x.model_dump() for x in first],[x.model_dump() for x in second])

    def test_overlap_is_not_claimed_as_verification(self):
        source=item('https://example.com'); source.engines=['a','b']
        for mode in ['fast','deep']:
            text=generate_extractive_synthesis('test',[source],mode)
            self.assertNotIn('跨源权威验证',text)
            self.assertNotIn('多源交叉验证结论',text)
            self.assertIn('不代表' if mode=='fast' else '不证明',text)


class RerankTests(unittest.IsolatedAsyncioTestCase):
    async def rerank(self, results, items=None):
        @asynccontextmanager
        async def client(*args, **kwargs):
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'results':results}))) as c:
                yield c
        with patch.object(dispatcher,'get_settings',return_value={}), \
             patch.object(dispatcher.key_pool,'list_providers',return_value=[]), \
             patch.object(dispatcher.key_pool,'acquire_credentials',return_value=({'enabled':True,'base_url':'https://test/rerank'}, {'api_key':'test','id':'test'},None)), \
             patch.object(dispatcher.key_pool,'record_execution') as record, \
             patch.object(dispatcher,'make_async_client',client):
            result=await dispatcher.apply_semantic_rerank('unmatched',items or [item(f'https://test/{i:02d}') for i in range(30)])
            return result,record.call_args.args

    async def test_candidates_and_tail_stay_on_same_scale(self):
        result,_=await self.rerank([{'index':0,'relevance_score':0},{'index':1,'relevance_score':1}])
        scores={x.url:x.final_score for x in result}
        self.assertAlmostEqual(scores['https://test/00'],.014)
        self.assertAlmostEqual(scores['https://test/01'],.026)
        self.assertAlmostEqual(scores['https://test/25'],.02)
        self.assertEqual(result[0].url,'https://test/01')
        self.assertEqual(result[-1].url,'https://test/00')

    async def test_invalid_response_is_atomic_and_recorded(self):
        for bad in [{'index':25,'relevance_score':1}, {'index':0,'relevance_score':float('inf')},
                    {'index':True,'relevance_score':.5}, {'index':1,'relevance_score':2},
                    {'index':1,'relevance_score':None}, {'index':0,'relevance_score':.2}]:
            # MockTransport JSON rejects infinity before parsing as well; both remain lexical only.
            result,args=await self.rerank([{'index':0,'relevance_score':1},bad])
            self.assertTrue(all(x.final_score==.02 for x in result))
            self.assertFalse(args[2])

    async def test_repeated_rerank_does_not_compound(self):
        original=[item('https://test/a')]
        first,_=await self.rerank([{'index':0,'relevance_score':1}],original)
        second,_=await self.rerank([{'index':0,'relevance_score':1}],first)
        self.assertEqual(first[0].final_score,second[0].final_score)
        self.assertEqual(original[0].final_score,.02)


if __name__=='__main__':
    unittest.main()
