import json
import os
import sqlite3
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "gateway.db")

_db_lock = threading.RLock()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


DEFAULT_PROVIDERS = [
    # 1. 免 Key 通用与垂直搜索源 (开箱即用)
    {
        "id": "bing_web",
        "name": "Bing 国际/国内网页检索",
        "category": "web",
        "provider_type": "search",
        "requires_key": 0,
        "enabled": 1,
        "weight": 1.4,
        "timeout_ms": 6000,
        "use_proxy": 0,
        "custom_proxy": "",
        "base_url": "https://www.bing.com/search",
        "default_model": "",
        "strategy": "round_robin",
        "icon": "GlobalOutlined",
        "description": "免 API Key 直接抓取解析 Bing 实时网页搜索结果，支持中英文高速直连检索",
        "doc_url": "https://www.bing.com",
    },
    {
        "id": "duckduckgo",
        "name": "DuckDuckGo 隐私元搜索",
        "category": "web",
        "provider_type": "search",
        "requires_key": 0,
        "enabled": 1,
        "weight": 1.3,
        "timeout_ms": 7000,
        "use_proxy": 1,
        "custom_proxy": "",
        "base_url": "https://html.duckduckgo.com/html/",
        "default_model": "",
        "strategy": "round_robin",
        "icon": "SafetyCertificateOutlined",
        "description": "免 API Key 全球隐私搜索引擎，英文与技术资料召回率极高（建议开启代理）",
        "doc_url": "https://duckduckgo.com",
    },
    {
        "id": "wikipedia",
        "name": "Wikipedia 维基百科 API",
        "category": "web",
        "provider_type": "search",
        "requires_key": 0,
        "enabled": 1,
        "weight": 1.2,
        "timeout_ms": 6000,
        "use_proxy": 1,
        "custom_proxy": "",
        "base_url": "https://zh.wikipedia.org/w/api.php",
        "default_model": "",
        "strategy": "round_robin",
        "icon": "ReadOutlined",
        "description": "免 Key 官方 MediaWiki 搜索接口，提供权威百科词条与概念定义验证",
        "doc_url": "https://www.mediawiki.org/wiki/API:Search",
    },
    {
        "id": "arxiv",
        "name": "arXiv 学术预印本库",
        "category": "academic",
        "provider_type": "search",
        "requires_key": 0,
        "enabled": 1,
        "weight": 1.6,
        "timeout_ms": 8000,
        "use_proxy": 1,
        "custom_proxy": "",
        "base_url": "https://export.arxiv.org/api/query",
        "default_model": "",
        "strategy": "round_robin",
        "icon": "ExperimentOutlined",
        "description": "免 Key 官方学术论文接口，覆盖 AI、物理、数学、计算机最新预印本及 PDF 链接",
        "doc_url": "https://info.arxiv.org/help/api/index.html",
    },
    {
        "id": "openalex",
        "name": "OpenAlex 全球学术图谱",
        "category": "academic",
        "provider_type": "search",
        "requires_key": 0,
        "enabled": 1,
        "weight": 1.5,
        "timeout_ms": 7000,
        "use_proxy": 1,
        "custom_proxy": "",
        "base_url": "https://api.openalex.org/works",
        "default_model": "",
        "strategy": "round_robin",
        "icon": "BankOutlined",
        "description": "免 Key 2.5 亿篇全球学术文献与引用量检索，包含 DOI、摘要还原与期刊质量信息",
        "doc_url": "https://docs.openalex.org/",
    },
    {
        "id": "github",
        "name": "GitHub 开源仓库检索",
        "category": "code",
        "provider_type": "search",
        "requires_key": 0,
        "enabled": 1,
        "weight": 1.5,
        "timeout_ms": 7000,
        "use_proxy": 1,
        "custom_proxy": "",
        "base_url": "https://api.github.com/search/repositories",
        "default_model": "",
        "strategy": "weighted",
        "icon": "GithubOutlined",
        "description": "支持免 Key 公共访问或配置 Personal Access Token 提升限额，按 Star 与相关性检索开源项目",
        "doc_url": "https://docs.github.com/en/rest/search",
    },
    {
        "id": "trending",
        "name": "全网热榜检索 (百度/微博/知乎/抖音/B站/GitHub)",
        "category": "entertainment",
        "provider_type": "search",
        "requires_key": 0,
        "enabled": 1,
        "weight": 2.0,
        "timeout_ms": 12000,
        "use_proxy": 0,
        "custom_proxy": "",
        "base_url": "builtin://trending",
        "default_model": "",
        "strategy": "round_robin",
        "icon": "FireOutlined",
        "description": "把公开榜单接入检索链路：命中「抖音/微博热搜/百度榜/B站排行」等关键词时，直接返回榜单条目（含名次、热度）；无关查询不触网、零开销",
        "doc_url": "https://github.com",
    },
    {
        "id": "hackernews",
        "name": "Hacker News (Algolia API)",
        "category": "social",
        "provider_type": "search",
        "requires_key": 0,
        "enabled": 1,
        "weight": 1.3,
        "timeout_ms": 6000,
        "use_proxy": 1,
        "custom_proxy": "",
        "base_url": "https://hn.algolia.com/api/v1/search",
        "default_model": "",
        "strategy": "round_robin",
        "icon": "FireOutlined",
        "description": "免 Key 硅谷技术社区实时讨论、架构评测与最新创业产品舆情检索",
        "doc_url": "https://hn.algolia.com/api",
    },
    {
        "id": "reddit",
        "name": "Reddit 社区实时讨论",
        "category": "social",
        "provider_type": "search",
        "requires_key": 0,
        "enabled": 1,
        "weight": 1.2,
        "timeout_ms": 7000,
        "use_proxy": 1,
        "custom_proxy": "",
        "base_url": "https://www.reddit.com/search.json",
        "default_model": "",
        "strategy": "round_robin",
        "icon": "CommentOutlined",
        "description": "免 Key 检索全球最大社区真实用户体验、避坑指南与热门讨论帖",
        "doc_url": "https://www.reddit.com/dev/api/",
    },
    {
        "id": "bluesky",
        "name": "Bluesky 实时短贴 (AT Protocol)",
        "category": "social",
        "provider_type": "search",
        "requires_key": 0,
        "enabled": 1,
        "weight": 1.4,
        "timeout_ms": 8000,
        "use_proxy": 1,
        "custom_proxy": "",
        "base_url": "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts",
        "default_model": "",
        "strategy": "round_robin",
        "icon": "GlobalOutlined",
        "description": "免 Key 调用 Bluesky 公共 AT Protocol 检索，按最新排序，适合抓外网突发、记者与技术社区的第一手短贴",
        "doc_url": "https://docs.bsky.app/docs/api/app-bsky-feed-search-posts",
    },
    {
        "id": "x_search",
        "name": "X (Twitter) 官方 API v2",
        "category": "social",
        "provider_type": "search",
        "requires_key": 1,
        "enabled": 0,
        "weight": 1.5,
        "timeout_ms": 8000,
        "use_proxy": 1,
        "custom_proxy": "",
        "base_url": "https://api.x.com/2",
        "default_model": "",
        "strategy": "round_robin",
        "icon": "GlobalOutlined",
        "description": "X 官方 recent search（需 Bearer Token，免费层无读取额度，Basic 起约 $200/月）；也可把 base_url 指向兼容 v2 的第三方转发服务",
        "doc_url": "https://docs.x.com/x-api/posts/search-recent",
    },
    {
        "id": "bilibili",
        "name": "B站视频搜索 (官方 web 接口)",
        "category": "social",
        "provider_type": "search",
        "requires_key": 0,
        "enabled": 1,
        "weight": 1.3,
        "timeout_ms": 12000,
        "use_proxy": 1,
        "custom_proxy": "",
        "base_url": "https://api.bilibili.com/x/web-interface/search/type",
        "default_model": "",
        "strategy": "round_robin",
        "icon": "VideoCameraOutlined",
        "description": "免登录调用 B站官方搜索接口（带 buvid3/buvid4 指纹），返回标题、UP主、播放/弹幕、时长与发布日期；评论通过 /api/v1/video/bilibili/comments 抓取",
        "doc_url": "https://search.bilibili.com",
    },
    {
        "id": "tencent_news",
        "name": "腾讯新闻资讯检索 (Tencent News)",
        "category": "web",
        "provider_type": "search",
        "requires_key": 0,
        "enabled": 1,
        "weight": 1.45,
        "timeout_ms": 7000,
        "use_proxy": 0,
        "custom_proxy": "",
        "base_url": "https://i.news.qq.com/gw/pc_search/result",
        "default_model": "",
        "strategy": "round_robin",
        "icon": "NotificationOutlined",
        "description": "免 Key 直连腾讯新闻 PC 搜索接口：时政、财经、社会资讯一手权威信源，返回标题、摘要、媒体与发布日期",
        "doc_url": "https://news.qq.com",
    },
    {
        "id": "zhihu",
        "name": "知乎问答检索 (Zhihu)",
        "category": "social",
        "provider_type": "search",
        "requires_key": 0,
        "enabled": 1,
        "weight": 1.45,
        "timeout_ms": 7000,
        "use_proxy": 0,
        "custom_proxy": "",
        "base_url": "builtin://zhihu",
        "default_model": "",
        "strategy": "round_robin",
        "icon": "QuestionCircleOutlined",
        "description": "免 Key 检索知乎问答与专栏（搜狗站内收录 + Bing site: 兜底）：经验讨论、行业观点与深度长文",
        "doc_url": "https://www.zhihu.com",
    },
    # 2. 商业高精搜索 API (填入 API Key 即刻激活)
    {
        "id": "bocha",
        "name": "博查 AI 搜索 (Bocha)",
        "category": "web",
        "provider_type": "search",
        "requires_key": 1,
        "enabled": 1,
        "weight": 2.0,
        "timeout_ms": 6000,
        "use_proxy": 0,
        "custom_proxy": "",
        "base_url": "https://api.bochaai.com/v1/web-search",
        "default_model": "",
        "strategy": "weighted",
        "icon": "ThunderboltOutlined",
        "description": "国内专为 AI Agent 打造的联网搜索 API，自带长文本 Summary 与极速国内直连响应",
        "doc_url": "https://open.bochaai.com",
    },
    {
        "id": "tavily",
        "name": "Tavily AI Search",
        "category": "web",
        "provider_type": "search",
        "requires_key": 1,
        "enabled": 1,
        "weight": 2.0,
        "timeout_ms": 7000,
        "use_proxy": 1,
        "custom_proxy": "",
        "base_url": "https://api.tavily.com/search",
        "default_model": "",
        "strategy": "weighted",
        "icon": "CompassOutlined",
        "description": "海外最主流的 Agent 专用搜索引擎，直接返回针对 RAG 优化的高质量切片与答案",
        "doc_url": "https://tavily.com",
    },
    {
        "id": "serper",
        "name": "Serper (Google SERP API)",
        "category": "web",
        "provider_type": "search",
        "requires_key": 1,
        "enabled": 1,
        "weight": 1.9,
        "timeout_ms": 6000,
        "use_proxy": 1,
        "custom_proxy": "",
        "base_url": "https://google.serper.dev/search",
        "default_model": "",
        "strategy": "weighted",
        "icon": "GoogleOutlined",
        "description": "极速低成本的 Google 搜索结果 API，支持网页、新闻、学术与知识图谱卡片",
        "doc_url": "https://serper.dev",
    },
    {
        "id": "exa",
        "name": "Exa 神经网络语义搜索",
        "category": "web",
        "provider_type": "search",
        "requires_key": 1,
        "enabled": 1,
        "weight": 1.8,
        "timeout_ms": 8000,
        "use_proxy": 1,
        "custom_proxy": "",
        "base_url": "https://api.exa.ai/search",
        "default_model": "",
        "strategy": "weighted",
        "icon": "DeploymentUnitOutlined",
        "description": "基于 Embeddings 的神经搜索引擎，擅长深度技术博客、长文报告与相似网页检索",
        "doc_url": "https://exa.ai",
    },
    {
        "id": "brave",
        "name": "Brave Search API",
        "category": "web",
        "provider_type": "search",
        "requires_key": 1,
        "enabled": 1,
        "weight": 1.7,
        "timeout_ms": 6000,
        "use_proxy": 1,
        "custom_proxy": "",
        "base_url": "https://api.search.brave.com/res/v1/web/search",
        "default_model": "",
        "strategy": "weighted",
        "icon": "CrownOutlined",
        "description": "拥有独立网页索引库的海外搜索 API，无广告污染，适合作为主力交叉验证源",
        "doc_url": "https://brave.com/search/api/",
    },
    # 3. 网页正文抽取器 (Scrapers)
    {
        "id": "jina_reader",
        "name": "Jina Reader (r.jina.ai)",
        "category": "scraper",
        "provider_type": "scraper",
        "requires_key": 0,
        "enabled": 1,
        "weight": 1.8,
        "timeout_ms": 10000,
        "use_proxy": 1,
        "custom_proxy": "",
        "base_url": "https://r.jina.ai/",
        "default_model": "",
        "strategy": "round_robin",
        "icon": "FileMarkdownOutlined",
        "description": "支持免 Key 或填入 Jina Key 高速将任意 URL 转换为干净的 LLM 友好 Markdown 全文",
        "doc_url": "https://jina.ai/reader/",
    },
    {
        "id": "firecrawl",
        "name": "Firecrawl 深度网页抓取",
        "category": "scraper",
        "provider_type": "scraper",
        "requires_key": 1,
        "enabled": 1,
        "weight": 1.9,
        "timeout_ms": 12000,
        "use_proxy": 1,
        "custom_proxy": "",
        "base_url": "https://api.firecrawl.dev/v1/scrape",
        "default_model": "",
        "strategy": "weighted",
        "icon": "FireOutlined",
        "description": "支持动态 JS 渲染与反爬绕过的商业级网页转 Markdown 引擎",
        "doc_url": "https://firecrawl.dev",
    },
    # 4. 重排器与大模型池 (Reranker & LLM)
    {
        "id": "jina_reranker",
        "name": "Jina Reranker 语义精排",
        "category": "reranker",
        "provider_type": "reranker",
        "requires_key": 1,
        "enabled": 1,
        "weight": 1.0,
        "timeout_ms": 5000,
        "use_proxy": 1,
        "custom_proxy": "",
        "base_url": "https://api.jina.ai/v1/rerank",
        "default_model": "jina-reranker-v2-base-multilingual",
        "strategy": "round_robin",
        "icon": "SortAscendingOutlined",
        "description": "Jina 官方多语言交叉编码语义重排 API",
        "doc_url": "https://jina.ai/reranker/",
    },
    {
        "id": "siliconflow_reranker",
        "name": "硅基流动 BGE 语义重排 (SiliconFlow Rerank)",
        "category": "reranker",
        "provider_type": "reranker",
        "requires_key": 1,
        "enabled": 1,
        "weight": 1.2,
        "timeout_ms": 5000,
        "use_proxy": 0,
        "custom_proxy": "",
        "base_url": "https://api.siliconflow.cn/v1/rerank",
        "default_model": "BAAI/bge-reranker-v2-m3",
        "strategy": "weighted",
        "icon": "SortAscendingOutlined",
        "description": "国内高速直连 BAAI/bge-reranker-v2-m3 与 Qwen3-Reranker 语义精排服务",
        "doc_url": "https://siliconflow.cn",
    },
    {
        "id": "cohere_reranker",
        "name": "Cohere / 通用兼容 Rerank 接口",
        "category": "reranker",
        "provider_type": "reranker",
        "requires_key": 1,
        "enabled": 1,
        "weight": 1.0,
        "timeout_ms": 6000,
        "use_proxy": 1,
        "custom_proxy": "",
        "base_url": "https://api.cohere.com/v1/rerank",
        "default_model": "rerank-multilingual-v3.0",
        "strategy": "round_robin",
        "icon": "SortAscendingOutlined",
        "description": "兼容 Cohere / OneAPI / NewAPI / Xinference / vLLM 标准 /v1/rerank 端点",
        "doc_url": "https://cohere.com/rerank",
    },
    {
        "id": "siliconflow",
        "name": "硅基流动 (SiliconFlow LLM & Rerank)",
        "category": "llm",
        "provider_type": "llm",
        "requires_key": 1,
        "enabled": 1,
        "weight": 1.5,
        "timeout_ms": 30000,
        "use_proxy": 0,
        "custom_proxy": "",
        "base_url": "https://api.siliconflow.cn/v1",
        "default_model": "deepseek-ai/DeepSeek-V3",
        "strategy": "weighted",
        "icon": "RocketOutlined",
        "description": "国内高速直连大模型与 BAAI/bge-reranker-v2-m3 重排一体服务商",
        "doc_url": "https://siliconflow.cn",
    },
    {
        "id": "deepseek",
        "name": "DeepSeek 官方开放平台",
        "category": "llm",
        "provider_type": "llm",
        "requires_key": 1,
        "enabled": 1,
        "weight": 1.5,
        "timeout_ms": 30000,
        "use_proxy": 0,
        "custom_proxy": "",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "strategy": "weighted",
        "icon": "BulbOutlined",
        "description": "DeepSeek-V3 / R1 推理与问答生成模型，支持国内直连",
        "doc_url": "https://platform.deepseek.com",
    },
    {
        "id": "openai_compat",
        "name": "OpenAI / 通用兼容大模型接口",
        "category": "llm",
        "provider_type": "llm",
        "requires_key": 1,
        "enabled": 1,
        "weight": 1.5,
        "timeout_ms": 30000,
        "use_proxy": 1,
        "custom_proxy": "",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "strategy": "weighted",
        "icon": "ApiOutlined",
        "description": "支持 OpenAI、OneAPI、NewAPI、通义千问、智谱、Ollama 等任意兼容 /v1/chat/completions 的端点",
        "doc_url": "https://platform.openai.com",
    },
]

DEFAULT_ROUTE_GROUPS = [
    {
        "id": "auto",
        "name": "智能全能路由 (Auto Router)",
        "description": "根据 Query 意图自动识别所属领域（网页/学术/代码/社媒），动态选择最佳引擎组合并发检索",
        "engines": ["bocha", "tavily", "serper", "bluesky", "bilibili", "tencent_news", "zhihu", "bing_web", "duckduckgo", "wikipedia", "trending"],
        "fallback_engines": ["bluesky", "tencent_news", "zhihu", "bing_web", "duckduckgo", "wikipedia"],
        "timeout_ms": 7500,
        "top_k": 20,
        "enable_rerank": 1,
        "scrape_top_n": 2,
        "enabled": 1,
    },
    {
        "id": "web",
        "name": "全网综合快搜组 (Web Fast)",
        "description": "聚合国内外主流商业搜索 API 与免 Key 网页引擎，跨源 URL 归一化去重与 RRF 融合",
        "engines": ["bocha", "tavily", "serper", "exa", "brave", "bilibili", "tencent_news", "zhihu", "bing_web", "duckduckgo", "trending"],
        "fallback_engines": ["tencent_news", "zhihu", "bing_web", "duckduckgo"],
        "timeout_ms": 6500,
        "top_k": 20,
        "enable_rerank": 1,
        "scrape_top_n": 1,
        "enabled": 1,
    },
    {
        "id": "academic",
        "name": "学术文献与科研组 (Academic)",
        "description": "并发检索 arXiv 预印本、OpenAlex 全球文献库、Wikipedia、Crossref 与 Exa/Tavily 学术网页",
        "engines": ["arxiv", "openalex", "exa", "tavily", "wikipedia"],
        "fallback_engines": ["arxiv", "openalex", "wikipedia"],
        "timeout_ms": 8500,
        "top_k": 20,
        "enable_rerank": 1,
        "scrape_top_n": 2,
        "enabled": 1,
    },
    {
        "id": "code",
        "name": "开源代码与技术架构组 (Code & Dev)",
        "description": "面向程序员与架构调研：并发检索 GitHub 开源仓库、Stack Overflow、Hacker News、DuckDuckGo 与商业引擎",
        "engines": ["github", "hackernews", "tavily", "serper", "duckduckgo", "bing_web"],
        "fallback_engines": ["github", "hackernews", "bing_web"],
        "timeout_ms": 7500,
        "top_k": 20,
        "enable_rerank": 1,
        "scrape_top_n": 2,
        "enabled": 1,
    },
    {
        "id": "social",
        "name": "全球社区与实时舆情组 (Social & Pulse)",
        "description": "打破信息茧房：聚合 Reddit 社区帖、Hacker News、B站与中文站点检索 与实时网页快讯",
        "engines": ["hackernews", "reddit", "bluesky", "bilibili", "zhihu", "bocha", "serper", "bing_web"],
        "fallback_engines": ["hackernews", "reddit", "bluesky", "zhihu", "bing_web"],
        "timeout_ms": 7500,
        "top_k": 20,
        "enable_rerank": 0,
        "scrape_top_n": 1,
        "enabled": 1,
    },
    {
        "id": "entertainment",
        "name": "短剧 / 短视频 / 音乐娱乐组 (Entertainment & Media)",
        "description": "垂直检索红果短剧剧目、抖音/B站短视频与网易云/QQ/酷狗音乐：剧名/题材/热度匹配、粘贴抖音或B站链接可直接解析出下载直链、按歌名点歌可拿播放直链与歌词",
        "engines": ["bing_web"],
        "fallback_engines": [],
        "timeout_ms": 20000,
        "top_k": 15,
        "enable_rerank": 0,
        "scrape_top_n": 0,
        "enabled": 1,
    },
]

DEFAULT_SETTINGS = {
    "global_proxy": "http://127.0.0.1:7890",
    "enable_global_proxy": True,
    "cache_ttl_seconds": 1800,
    "enable_cache": True,
    "rrf_k": 60,
    "multi_source_boost": 1.45,
    "circuit_breaker_threshold": 4,
    "circuit_breaker_cooldown_sec": 120,
    "blocked_domains": ["csdn.net/download"],
    "boosted_domains": ["github.com", "arxiv.org", "wikipedia.org", "huggingface.co", "bilibili.com"],
    "default_llm_provider": "siliconflow",
    "default_llm_model": "deepseek-ai/DeepSeek-V3",
    "default_reranker_provider": "jina_reranker",
    "router_mode": "rule",  # rule | jev | ai
    "jev_api_url": "https://api.typesafe.ai/v1/systemone",
    "jev_api_key": "",
    "jev_model": "jev-1.13.0",
    "jev_confidence_threshold": 0.45,
    "jev_timeout_ms": 4000,
    "ai_router_provider": "siliconflow",
    "ai_router_model": "deepseek-ai/DeepSeek-V3",
    "ai_router_timeout_ms": 6000,
}


def init_db() -> None:
    with _db_lock:
        conn = get_conn()
        cur = conn.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS providers (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            provider_type TEXT NOT NULL,
            requires_key INTEGER DEFAULT 1,
            enabled INTEGER DEFAULT 1,
            weight REAL DEFAULT 1.0,
            timeout_ms INTEGER DEFAULT 6000,
            use_proxy INTEGER DEFAULT 0,
            custom_proxy TEXT DEFAULT '',
            base_url TEXT DEFAULT '',
            default_model TEXT DEFAULT '',
            strategy TEXT DEFAULT 'round_robin',
            icon TEXT DEFAULT '',
            description TEXT DEFAULT '',
            doc_url TEXT DEFAULT '',
            total_calls INTEGER DEFAULT 0,
            success_calls INTEGER DEFAULT 0,
            failed_calls INTEGER DEFAULT 0,
            avg_latency_ms REAL DEFAULT 0.0,
            consecutive_failures INTEGER DEFAULT 0,
            circuit_open_until REAL DEFAULT 0.0,
            last_error TEXT DEFAULT '',
            last_checked_at REAL DEFAULT 0.0
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id TEXT PRIMARY KEY,
            provider_id TEXT NOT NULL,
            label TEXT NOT NULL,
            api_key TEXT NOT NULL,
            base_url TEXT DEFAULT '',
            weight INTEGER DEFAULT 1,
            rpm_limit INTEGER DEFAULT 60,
            daily_quota INTEGER DEFAULT 10000,
            used_today INTEGER DEFAULT 0,
            total_used INTEGER DEFAULT 0,
            use_proxy INTEGER DEFAULT -1,
            custom_proxy TEXT DEFAULT '',
            enabled INTEGER DEFAULT 1,
            last_used_at REAL DEFAULT 0.0,
            last_latency_ms INTEGER DEFAULT 0,
            last_status TEXT DEFAULT 'untested',
            last_error TEXT DEFAULT '',
            created_at REAL DEFAULT 0.0
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS route_groups (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            engines_json TEXT NOT NULL,
            fallback_engines_json TEXT NOT NULL,
            timeout_ms INTEGER DEFAULT 7500,
            top_k INTEGER DEFAULT 20,
            enable_rerank INTEGER DEFAULT 1,
            scrape_top_n INTEGER DEFAULT 2,
            enabled INTEGER DEFAULT 1
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS gateway_settings (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS search_traces (
            trace_id TEXT PRIMARY KEY,
            query TEXT NOT NULL,
            mode TEXT DEFAULT 'search',
            resolved_route TEXT DEFAULT 'auto',
            total_latency_ms INTEGER DEFAULT 0,
            total_raw_results INTEGER DEFAULT 0,
            total_merged_results INTEGER DEFAULT 0,
            cross_engine_hits INTEGER DEFAULT 0,
            cache_hit INTEGER DEFAULT 0,
            engine_traces_json TEXT DEFAULT '[]',
            top_urls_json TEXT DEFAULT '[]',
            created_at REAL NOT NULL
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS research_jobs (
            id TEXT PRIMARY KEY,
            query TEXT NOT NULL,
            mode TEXT NOT NULL DEFAULT 'deep',
            route_group TEXT DEFAULT 'auto',
            status TEXT NOT NULL DEFAULT 'queued',
            created_at REAL NOT NULL,
            started_at REAL,
            finished_at REAL,
            latency_ms INTEGER DEFAULT 0,
            result_text TEXT DEFAULT '',
            result_json TEXT DEFAULT '{}',
            error TEXT DEFAULT ''
        )
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS research_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """)

        cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_research_jobs_created
        ON research_jobs(created_at DESC)
        """)

        cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_research_steps_job_seq
        ON research_steps(job_id, seq)
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS gateway_tokens (
            token TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            daily_limit INTEGER DEFAULT 5000,
            used_count INTEGER DEFAULT 0,
            enabled INTEGER DEFAULT 1,
            created_at REAL NOT NULL
        )
        """)

        # Seed providers
        for p in DEFAULT_PROVIDERS:
            cur.execute("SELECT id FROM providers WHERE id = ?", (p["id"],))
            if not cur.fetchone():
                cur.execute("""
                INSERT INTO providers (
                    id, name, category, provider_type, requires_key, enabled, weight,
                    timeout_ms, use_proxy, custom_proxy, base_url, default_model,
                    strategy, icon, description, doc_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    p["id"], p["name"], p["category"], p["provider_type"], p["requires_key"],
                    p["enabled"], p["weight"], p["timeout_ms"], p["use_proxy"], p["custom_proxy"],
                    p["base_url"], p["default_model"], p["strategy"], p["icon"],
                    p["description"], p["doc_url"]
                ))

        # Seed route groups
        for rg in DEFAULT_ROUTE_GROUPS:
            cur.execute("SELECT id FROM route_groups WHERE id = ?", (rg["id"],))
            if not cur.fetchone():
                cur.execute("""
                INSERT INTO route_groups (
                    id, name, description, engines_json, fallback_engines_json,
                    timeout_ms, top_k, enable_rerank, scrape_top_n, enabled
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    rg["id"], rg["name"], rg["description"],
                    json.dumps(rg["engines"], ensure_ascii=False),
                    json.dumps(rg["fallback_engines"], ensure_ascii=False),
                    rg["timeout_ms"], rg["top_k"], rg["enable_rerank"],
                    rg["scrape_top_n"], rg["enabled"]
                ))

# Mount the trending-board retriever into existing auto/web route groups
        for group_id in ("auto", "web"):
            rg_row = cur.execute(
                "SELECT engines_json, fallback_engines_json FROM route_groups WHERE id = ?", (group_id,)
            ).fetchone()
            if not rg_row:
                continue
            engs = json.loads(rg_row["engines_json"] or "[]")
            if "trending" not in engs:
                engs.append("trending")
                cur.execute(
                    "UPDATE route_groups SET engines_json = ? WHERE id = ?",
                    (json.dumps(engs, ensure_ascii=False), group_id),
                )

# 补齐后续新增的检索渠道（旧库不会因种子变更自动获得新 provider）
        for new_id in ("bluesky", "x_search", "bilibili", "tencent_news", "zhihu"):
            seeded = next((x for x in DEFAULT_PROVIDERS if x["id"] == new_id), None)
            if not seeded:
                continue
            if cur.execute("SELECT id FROM providers WHERE id = ?", (new_id,)).fetchone():
                continue
            cur.execute("""
            INSERT INTO providers (
                id, name, category, provider_type, requires_key, enabled, weight,
                timeout_ms, use_proxy, custom_proxy, base_url, default_model,
                strategy, icon, description, doc_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                seeded["id"], seeded["name"], seeded["category"], seeded["provider_type"],
                seeded["requires_key"], seeded["enabled"], seeded["weight"], seeded["timeout_ms"],
                seeded["use_proxy"], seeded["custom_proxy"], seeded["base_url"], seeded["default_model"],
                seeded["strategy"], seeded["icon"], seeded["description"], seeded["doc_url"],
            ))

        # 修正旧库中 Bluesky 的公开检索入口（public.api 对 searchPosts 返回 403）
        cur.execute(
            "UPDATE providers SET base_url = ? WHERE id = 'bluesky' AND base_url LIKE '%public.api.bsky.app%'",
            ("https://api.bsky.app/xrpc/app.bsky.feed.searchPosts",),
        )

        # 把新增的 Bluesky 渠道挂到已有社交/智能路由组
        for group_id in ("social", "auto", "web"):
            social_row = cur.execute(
                "SELECT engines_json, fallback_engines_json FROM route_groups WHERE id = ?", (group_id,)
            ).fetchone()
            if not social_row:
                continue
            engs = json.loads(social_row["engines_json"] or "[]")
            fbs = json.loads(social_row["fallback_engines_json"] or "[]")
            for engine_id in ("bluesky", "bilibili"):
                if engine_id not in engs:
                    engs.append(engine_id)
                if engine_id not in fbs:
                    fbs.append(engine_id)
            cur.execute(
                "UPDATE route_groups SET engines_json = ?, fallback_engines_json = ? WHERE id = ?",
                (json.dumps(engs, ensure_ascii=False), json.dumps(fbs, ensure_ascii=False), group_id),
            )

        # 把知乎 / 腾讯新闻渠道挂到对应路由组（旧库回填）
        mounts = {"auto": ("tencent_news", "zhihu"), "web": ("tencent_news", "zhihu"), "social": ("zhihu",)}
        for group_id, engine_ids in mounts.items():
            group_row = cur.execute(
                "SELECT engines_json, fallback_engines_json FROM route_groups WHERE id = ?", (group_id,)
            ).fetchone()
            if not group_row:
                continue
            engs = json.loads(group_row["engines_json"] or "[]")
            fbs = json.loads(group_row["fallback_engines_json"] or "[]")
            for engine_id in engine_ids:
                if engine_id not in engs:
                    engs.append(engine_id)
                if engine_id not in fbs:
                    fbs.append(engine_id)
            cur.execute(
                "UPDATE route_groups SET engines_json = ?, fallback_engines_json = ? WHERE id = ?",
                (json.dumps(engs, ensure_ascii=False), json.dumps(fbs, ensure_ascii=False), group_id),
            )

        for k, v in DEFAULT_SETTINGS.items():
            cur.execute("SELECT key FROM gateway_settings WHERE key = ?", (k,))
            if not cur.fetchone():
                cur.execute(
                    "INSERT INTO gateway_settings (key, value_json) VALUES (?, ?)",
                    (k, json.dumps(v, ensure_ascii=False))
                )

        # Seed default gateway token
        cur.execute("SELECT token FROM gateway_tokens LIMIT 1")
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO gateway_tokens (token, name, daily_limit, used_count, enabled, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("sk-omni-gateway-default-key", "默认本地开发网关密钥", 100000, 0, 1, time.time())
            )

        conn.commit()
        conn.close()


def get_settings() -> Dict[str, Any]:
    with _db_lock:
        conn = get_conn()
        rows = conn.execute("SELECT key, value_json FROM gateway_settings").fetchall()
        conn.close()
        res = dict(DEFAULT_SETTINGS)
        for r in rows:
            try:
                res[r["key"]] = json.loads(r["value_json"])
            except Exception:
                pass
        return res


def update_settings(updates: Dict[str, Any]) -> Dict[str, Any]:
    with _db_lock:
        conn = get_conn()
        for k, v in updates.items():
            if v is not None:
                conn.execute(
                    "INSERT OR REPLACE INTO gateway_settings (key, value_json) VALUES (?, ?)",
                    (k, json.dumps(v, ensure_ascii=False))
                )
        conn.commit()
        conn.close()
    return get_settings()


def mask_key(raw: str) -> str:
    if not raw:
        return ""
    if len(raw) <= 8:
        return raw[:2] + "***" + raw[-2:]
    return raw[:5] + "••••••••" + raw[-4:]
