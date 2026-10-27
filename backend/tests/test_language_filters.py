"""学术噪音过滤、语言偏置与英文扩展的离线回归。"""
import unittest
from unittest.mock import patch

from app.gateway import query_expansion
from app.gateway.intent_filters import (
    apply_language_bias,
    detect_lang,
    filter_academic_noise,
    filter_low_overlap_zh,
    is_academic_domain,
    is_academic_intent,
    is_cn_content_domain,
)
from app.schemas import UnifiedSearchItem


def item(url: str, score: float = 1.0) -> UnifiedSearchItem:
    return UnifiedSearchItem(title='T', url=url, snippet='s', final_score=score, source_engine='seginge')


class LanguageTests(unittest.TestCase):
    def test_detect_lang(self):
        self.assertEqual(detect_lang('抖音热榜'), 'zh')
        self.assertEqual(detect_lang('vibe coding prompts'), 'en')
        self.assertEqual(detect_lang('OpenAI 最新消息'), 'mixed')
        self.assertEqual(detect_lang('2026'), 'other')


class AcademicFilterTests(unittest.TestCase):
    def test_domains(self):
        self.assertTrue(is_academic_domain('https://doi.org/10.64216/3104-9672.25.02.031'))
        self.assertTrue(is_academic_domain('https://link.springer.com/article/1'))
        self.assertFalse(is_academic_domain('https://github.com/a/b'))
        self.assertFalse(is_academic_domain('https://doi.org.evil.test/x'))

    def test_intent(self):
        self.assertFalse(is_academic_intent('全网vibecoding 提示词'))
        self.assertTrue(is_academic_intent('transformer 论文'))
        self.assertTrue(is_academic_intent('随便搜点东西', 'academic'))

    def test_filters_doiorg_only_for_non_academic(self):
        items = [item('https://doi.org/10.1/x'), item('https://github.com/a/b')]
        kept = filter_academic_noise(items, '全网vibecoding 提示词')
        self.assertEqual([i.url for i in kept], ['https://github.com/a/b'])
        kept_academic = filter_academic_noise(items, 'transformer 论文')
        self.assertEqual(len(kept_academic), 2)


class ZhOverlapTests(unittest.TestCase):
    def test_drops_single_char_dictionary_pages(self):
        relevant = [item('https://github.com/x/prompts'), item('https://example.com/a')]
        relevant[0].title = 'VibeCoding 常用提示词模板'
        relevant[0].snippet = '提示词 模板'
        relevant[1].title = '全网 vibecoding 提示词大全'
        noisy = [item('https://www.zdic.net/hans/%E5%85%A8'), item('https://www.hgcha.com/zidian/1')]
        noisy[0].title = '全 quán - 漢典'
        noisy[0].snippet = '全的拼音、部首、笔顺'
        noisy[1].title = '全的意思'
        noisy[1].snippet = '全字的意思、组词'
        kept = filter_low_overlap_zh(relevant + noisy, '全网vibecoding 提示词')
        self.assertEqual([i.url for i in kept], [relevant[0].url, relevant[1].url])

    def test_falls_back_when_too_much_would_be_removed(self):
        items = [item('https://a.test/1'), item('https://a.test/2'), item('https://a.test/3'), item('https://a.test/4')]
        for idx, it in enumerate(items):
            it.title = f'无关标题{idx}'
        kept = filter_low_overlap_zh(items, '完全不相干的中文查询词')
        self.assertEqual(len(kept), 4)

    def test_drops_all_when_query_has_latin_token(self):
        items = []
        for idx in range(5):
            it = item(f'https://dict{idx}.test/x')
            it.title = '全的意思'
            it.snippet = '全的拼音、部首、笔顺'
            items.append(it)
        self.assertEqual(filter_low_overlap_zh(items, '全网vibecoding 提示词'), [])

    def test_skips_non_chinese_queries(self):
        items = [item('https://github.com/a/b')]
        self.assertEqual(filter_low_overlap_zh(items, 'vibe coding prompts'), items)


class LanguageBiasTests(unittest.TestCase):
    def test_cn_domains(self):
        self.assertTrue(is_cn_content_domain('https://blog.csdn.net/x/article'))
        self.assertTrue(is_cn_content_domain('https://www.bilibili.com/video/BV1'))
        self.assertTrue(is_cn_content_domain('https://mp.weixin.qq.com/s/abc'))
        self.assertFalse(is_cn_content_domain('https://github.com/a/b'))

    def test_penalty_only_for_en_or_mixed(self):
        items = [item('https://blog.csdn.net/x/article', 1.0), item('https://github.com/a/b', 1.0)]
        adjusted = apply_language_bias(items, 'vibe coding prompts')
        self.assertEqual(adjusted, 1)
        self.assertAlmostEqual(items[0].final_score, 0.6, places=4)
        self.assertEqual(items[1].final_score, 1.0)
        self.assertEqual(items[0].metadata['language_bias'], 'cn_content_x0.6')

        untouched = [item('https://blog.csdn.net/x/article', 1.0)]
        self.assertEqual(apply_language_bias(untouched, '中文提示词教程'), 0)
        self.assertEqual(untouched[0].final_score, 1.0)


class QueryExpansionTests(unittest.IsolatedAsyncioTestCase):
    async def test_skips_non_chinese(self):
        self.assertEqual(await query_expansion.english_query_variants('vibe coding prompts'), [])

    async def test_without_llm_returns_empty(self):
        query_expansion.clear_cache()
        with patch.object(query_expansion, '_pick_llm', return_value=(None, None, None, None)):
            self.assertEqual(await query_expansion.english_query_variants('全网vibecoding 提示词'), [])

    def test_clean_rejects_chinese_or_quotes(self):
        self.assertEqual(query_expansion._clean('"vibe coding prompts"'), 'vibe coding prompts')
        self.assertEqual(query_expansion._clean('提示词模板'), '')
        self.assertEqual(query_expansion._clean(''), '')


if __name__ == '__main__':
    unittest.main()
