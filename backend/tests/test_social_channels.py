"""外网实时渠道（Bluesky / X API v2）的离线回归。

只验证解析、注册与凭证缺失时的失败语义；真实联网需代理，未在本机证明可用。
"""
import unittest

from app.core.database import DEFAULT_PROVIDERS, DEFAULT_ROUTE_GROUPS
from app.providers.adapters import SEARCH_ADAPTER_REGISTRY, _parse_bluesky_posts, search_x_api


class ChannelRegistrationTests(unittest.TestCase):
    def test_adapters_registered(self):
        self.assertIn('bluesky', SEARCH_ADAPTER_REGISTRY)
        self.assertIn('x_search', SEARCH_ADAPTER_REGISTRY)

    def test_provider_seeds(self):
        seeds = {p['id']: p for p in DEFAULT_PROVIDERS}
        self.assertEqual(seeds['bluesky']['requires_key'], 0)
        self.assertEqual(seeds['bluesky']['enabled'], 1)
        # X 官方 API 需要付费读取额度，默认不启用，避免无 Key 时干扰检索
        self.assertEqual(seeds['x_search']['requires_key'], 1)
        self.assertEqual(seeds['x_search']['enabled'], 0)

    def test_bluesky_mounted_into_social_route(self):
        social = next(g for g in DEFAULT_ROUTE_GROUPS if g['id'] == 'social')
        self.assertIn('bluesky', social['engines'])
        self.assertIn('bluesky', social['fallback_engines'])


class BlueskyParseTests(unittest.TestCase):
    def test_maps_post_urls_and_metrics(self):
        payload = {
            'posts': [
                {
                    'uri': 'at://did:plc:abc/app.bsky.feed.post/3kxyz',
                    'author': {'handle': 'alice.bsky.social', 'displayName': 'Alice'},
                    'record': {'text': 'breaking  news\nsecond line', 'createdAt': '2026-10-18T03:00:00.000Z', 'langs': ['en']},
                    'indexedAt': '2026-10-18T03:00:01.000Z',
                    'likeCount': 12, 'repostCount': 3, 'replyCount': 4,
                }
            ]
        }
        parsed = _parse_bluesky_posts(payload)
        self.assertEqual(len(parsed), 1)
        post = parsed[0]
        self.assertEqual(post['url'], 'https://bsky.app/profile/alice.bsky.social/post/3kxyz')
        self.assertEqual(post['text'], 'breaking news second line')
        self.assertEqual(post['published_at'], '2026-10-18T03:00:00.000Z')
        self.assertEqual((post['likes'], post['reposts'], post['replies']), (12, 3, 4))

    def test_skips_malformed_posts(self):
        self.assertEqual(_parse_bluesky_posts({'posts': [{'uri': 'bad', 'record': {}}]}), [])
        self.assertEqual(_parse_bluesky_posts({}), [])


class XChannelGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_bearer_token_fails_loudly(self):
        with self.assertRaises(RuntimeError) as ctx:
            await search_x_api('AI', 10, None, 5, api_key=None)
        self.assertIn('Bearer', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
