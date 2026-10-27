"""国内渠道（知乎 / 腾讯新闻）与正文抽取的离线回归。

只验证解析、注册与种子配置；真实联网在部署环境验证。
"""
import json
import unittest

from bs4 import BeautifulSoup

from app.core.database import DEFAULT_PROVIDERS, DEFAULT_ROUTE_GROUPS
from app.providers.adapters import SEARCH_ADAPTER_REGISTRY, extract_main_text
from app.providers.tencent_news import parse_tencent_search
from app.providers.trending_search import direct_data_boards, match_boards
from app.providers.zhihu import parse_sogou_zhihu


class CnChannelRegistrationTests(unittest.TestCase):
    def test_adapters_registered(self):
        self.assertIn('zhihu', SEARCH_ADAPTER_REGISTRY)
        self.assertIn('tencent_news', SEARCH_ADAPTER_REGISTRY)

    def test_provider_seeds(self):
        seeds = {p['id']: p for p in DEFAULT_PROVIDERS}
        for channel_id in ('zhihu', 'tencent_news'):
            self.assertEqual(seeds[channel_id]['requires_key'], 0, channel_id)
            self.assertEqual(seeds[channel_id]['enabled'], 1, channel_id)
            self.assertEqual(seeds[channel_id]['use_proxy'], 0, channel_id)

    def test_channels_mounted_into_routes(self):
        routes = {g['id']: g for g in DEFAULT_ROUTE_GROUPS}
        for group_id in ('auto', 'web'):
            self.assertIn('zhihu', routes[group_id]['engines'], group_id)
            self.assertIn('tencent_news', routes[group_id]['engines'], group_id)
            self.assertIn('zhihu', routes[group_id]['fallback_engines'], group_id)
            self.assertIn('tencent_news', routes[group_id]['fallback_engines'], group_id)
        self.assertIn('zhihu', routes['social']['engines'])
        self.assertIn('zhihu', routes['social']['fallback_engines'])


class ZhihuSogouParseTests(unittest.TestCase):
    FIXTURE = """
    <html><body>
      <div class="vrwrap"><div class="special-wrap">广告位，无 h3/a</div></div>
      <div class="vrwrap">
        <h3><a href="/link?url=http://sogou-redirect">Python异步编程全攻略</a></h3>
        <div class="ft">asyncio 事件循环、协程与任务调用的实战总结。</div>
        <div data-url="https://zhuanlan.zhihu.com/p/540852844"></div>
      </div>
      <div class="rb">
        <h3><a href="https://www.zhihu.com/question/19550226">Python 有哪些好的异步库？</a></h3>
        <p class="star-wiki">推荐 asyncio、uvloop 等主流方案。</p>
      </div>
      <div class="rb">
        <h3><a href="https://juejin.cn/post/1">站外结果应被过滤</a></h3>
      </div>
    </body></html>
    """

    def test_keeps_zhihu_links_only_and_resolves_data_url(self):
        items = parse_sogou_zhihu(self.FIXTURE, 10)
        urls = [it.url for it in items]
        self.assertEqual(urls, [
            'https://zhuanlan.zhihu.com/p/540852844',
            'https://www.zhihu.com/question/19550226',
        ])
        self.assertTrue(items[0].snippet.startswith('[知乎]'))
        self.assertEqual(items[0].metadata['platform'], 'zhihu')

    def test_empty_and_broken_html(self):
        self.assertEqual(parse_sogou_zhihu('', 10), [])
        self.assertEqual(parse_sogou_zhihu('<html><body>not results', 10), [])


class TencentNewsParseTests(unittest.TestCase):
    @staticmethod
    def _payload_bytes():
        payload = {
            "ret": 0,
            "secList": [
                {"secType": 0, "newsList": [
                    {"title": "<em>AI</em>治理新规落地", "url": "https://view.inews.qq.com/a/20261024A07SAU00",
                     "abstract": "新规将于下月实施。", "chlname": "新华社",
                     "timestamp": 1792819200, "time": "今天 08:00"},
                    {"title": "腾讯新闻用户最关注的热点，每10分钟更新一次", "url": "https://new.qq.com/promo"},
                    {"title": "无链接条目", "url": "javascript:void(0)"},
                    {"title": "站外域名", "url": "https://example.com/news"},
                    {"title": "AI 芯片出口新规", "url": "https://new.qq.com/rain/a/20261023A0BGMC00",
                     "shareUrl": "https://new.qq.com/rain/a/20261023A0BGMC00", "media_name": "界面新闻"},
                ]},
            ],
        }
        return json.dumps(payload, ensure_ascii=False).encode('utf-8')

    def test_parses_items_and_filters_promos_and_offsite(self):
        items = parse_tencent_search(self._payload_bytes(), 10)
        self.assertEqual([it.title for it in items], ['AI治理新规落地', 'AI 芯片出口新规'])
        first = items[0]
        self.assertEqual(first.url, 'https://view.inews.qq.com/a/20261024A07SAU00')
        self.assertEqual(first.published_at, '2026-10-24')
        self.assertEqual(first.metadata['media'], '新华社')
        self.assertTrue(first.snippet.startswith('[腾讯新闻]'))

    def test_gbk_payload_decodes(self):
        raw = self._payload_bytes().decode('utf-8').encode('gbk', 'replace')
        items = parse_tencent_search(raw, 10)
        self.assertTrue(items)
        self.assertEqual(items[0].metadata['media'], '新华社')

    def test_bad_payload_returns_empty(self):
        self.assertEqual(parse_tencent_search(b'not json', 10), [])
        self.assertEqual(parse_tencent_search(json.dumps({'ret': 500}).encode(), 10), [])


class TrendingBoardTests(unittest.TestCase):
    def test_tencent_board_matches(self):
        self.assertIn('tencent_hot', match_boards('腾讯新闻热搜'))
        self.assertIn('tencent_hot', match_boards('腾讯热榜'))
        # 只说平台名不触发直出（不算榜单意图）
        self.assertEqual(direct_data_boards('腾讯新闻最新报道'), [])
        self.assertIn('tencent_hot', direct_data_boards('腾讯热榜'))

    def test_zhihu_board_still_matches(self):
        self.assertIn('zhihu_hot', match_boards('知乎热榜'))


class MainTextExtractionTests(unittest.TestCase):
    NOISY_PAGE = """
    <html><head><title>深度学习入门指南</title></head>
    <body>
      <nav class="main-nav"><a href="/">首页</a><a href="/hot">热点</a><a href="/login">登录</a></nav>
      <div class="sidebar"><div class="hot-list"><a href="/1">推荐一</a><a href="/2">推荐二</a><a href="/3">推荐三</a></div></div>
      <article>
        <h1>深度学习入门指南</h1>
        <p>深度学习是机器学习的一个分支，它通过多层神经网络自动学习数据的高层特征表示。近年来在图像、语音与自然语言处理领域取得了突破性进展，成为人工智能浪潮的核心驱动力之一。</p>
        <p>反向传播算法是训练神经网络的基础。它通过链式法则把损失函数对每个参数的梯度逐层回传，配合随机梯度下降及其变体完成参数更新，使网络在大量样本上逐步逼近目标映射。</p>
        <div class="article-share"><a href="#">分享到微博</a><a href="#">分享到微信</a></div>
        <p>实践深度学习项目时，数据质量往往比模型结构更重要。清洗标注、构造合理的验证集与防止数据泄漏，是决定线上效果的关键步骤，值得投入与调参同等的精力。</p>
      </article>
      <footer class="site-footer"><p>版权所有 © 2026 示例站点</p></footer>
      <script>window.tracking = true;</script>
    </body></html>
    """

    def test_keeps_paragraphs_and_drops_boilerplate(self):
        text = extract_main_text(BeautifulSoup(self.NOISY_PAGE, 'html.parser'))
        self.assertIn('深度学习是机器学习的一个分支', text)
        # 段落保留换行而不是挤成一行
        self.assertEqual(len([l for l in text.splitlines() if '深度学习' in l or '反向传播' in l]) >= 2, True)
        for noise in ('推荐一', '分享到微博', '版权所有', '首页', 'window.tracking'):
            self.assertNotIn(noise, text)

    def test_site_hint_container_wins(self):
        wechat_page = """
        <html><body><div id="js_content">
          <p>微信公众号正文第一段，内容足够长以便通过最低长度门槛的校验逻辑。</p>
          <p>微信公众号正文第二段，同样包含实际内容而不只是导航或广告位。</p>
        </div><div class="qr-wrapper">扫码关注</div></body></html>
        """
        text = extract_main_text(
            BeautifulSoup(wechat_page, 'html.parser'), 'https://mp.weixin.qq.com/s/abc'
        )
        self.assertIn('第一段', text)
        self.assertIn('第二段', text)
        self.assertNotIn('扫码关注', text)

    def test_link_dense_small_blocks_dropped(self):
        page = """
        <html><body><main>
          <p><a href="/a">链接一</a><a href="/b">链接二</a><a href="/c">链接三</a><a href="/d">链接四</a></p>
          <p>正文段落：这里是一段足够长的正文内容，用于验证高链接密度的小块不会污染正文输出结果。</p>
        </main></body></html>
        """
        text = extract_main_text(BeautifulSoup(page, 'html.parser'))
        self.assertNotIn('链接一', text)
        self.assertIn('正文段落', text)


if __name__ == '__main__':
    unittest.main()
