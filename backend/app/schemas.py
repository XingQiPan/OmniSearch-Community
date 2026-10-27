from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class UnifiedSearchItem(BaseModel):
    title: str
    url: str
    normalized_url: str = ""
    snippet: str = ""
    content: Optional[str] = None
    published_at: Optional[str] = None
    favicon: Optional[str] = None
    domain: str = ""
    source_engine: str
    engines: List[str] = Field(default_factory=list)
    positions: Dict[str, int] = Field(default_factory=dict)
    raw_score: float = 0.0
    rrf_score: float = 0.0
    rerank_score: Optional[float] = None
    final_score: float = 0.0
    category: str = "web"  # web, academic, code, social, news, entertainment
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EngineExecutionTrace(BaseModel):
    engine_id: str
    engine_name: str
    status: Literal["success", "error", "timeout", "skipped", "circuit_open"]
    latency_ms: int = 0
    result_count: int = 0
    used_key_masked: Optional[str] = None
    used_proxy: bool = False
    error_message: Optional[str] = None


class UnifiedSearchRequest(BaseModel):
    query: str
    route_group: Optional[str] = "auto"  # auto, web, academic, code, social, entertainment, deep, custom
    engines: Optional[List[str]] = None  # explicit engines override
    top_k: int = 20
    timeout_ms: int = 8000
    enable_dedup: bool = True
    enable_rrf: bool = True
    enable_rerank: bool = False
    reranker_provider: Optional[str] = None
    include_domains: List[str] = Field(default_factory=list)
    exclude_domains: List[str] = Field(default_factory=list)
    time_range: Optional[Literal["day", "week", "month", "year", "all"]] = None
    scrape_top_n: int = 0  # 0 means don't scrape full text
    use_cache: Optional[bool] = None  # False 强制绕过语义缓存（对外 API 的 cache=false）


class UnifiedSearchResponse(BaseModel):
    trace_id: str
    query: str
    rewritten_queries: List[str] = Field(default_factory=list)
    resolved_route: str
    total_latency_ms: int
    total_raw_results: int
    total_merged_results: int
    cross_engine_hits: int = 0
    cache_hit: bool = False
    engine_traces: List[EngineExecutionTrace] = Field(default_factory=list)
    results: List[UnifiedSearchItem] = Field(default_factory=list)
    per_engine_results: Dict[str, List[UnifiedSearchItem]] = Field(default_factory=dict)


class ResearchJobCreate(BaseModel):
    query: str = Field(..., min_length=2, max_length=2000)
    mode: Literal["fast", "deep", "agentic"] = "deep"
    route_group: str = "auto"
    top_k: int = Field(16, ge=5, le=40)
    max_rounds: int = Field(3, ge=1, le=4)
    reading_budget: int = Field(10, ge=0, le=12)


class WebpageReadRequest(BaseModel):
    urls: List[str] = Field(..., min_length=1, max_length=10)  # 单次最多 10 个链接
    format: Literal["markdown", "text"] = "markdown"
    timeout_ms: int = Field(15000, ge=2000, le=60000)
    max_chars: int = Field(16000, ge=500, le=50000)


class WebpageReadItem(BaseModel):
    url: str
    final_url: str = ""
    title: str = ""
    content: str = ""
    format: str = "markdown"
    length: int = 0
    status: Literal["success", "error"] = "success"
    error: Optional[str] = None
    published_at: Optional[str] = None
    retrieved_at: Optional[str] = None
    truncated: bool = False
    read_source: Optional[str] = None
    latency_ms: int = 0


class WebpageReadResponse(BaseModel):
    object: str = "webpage.read"
    results: List[WebpageReadItem] = Field(default_factory=list)
    success_count: int = 0
    failed_count: int = 0
    latency_ms: int = 0


class AgentSearchRequest(BaseModel):
    query: str
    mode: Literal["fast", "deep", "agentic"] = "fast"
    route_group: str = "auto"
    engines: Optional[List[str]] = None
    llm_provider_id: Optional[str] = None
    model_name: Optional[str] = None
    top_k: int = 12
    scrape_top_n: int = 2
    max_rounds: int = 3
    reading_budget: int = Field(default=10, ge=0, le=12)
    raw: bool = Field(default=False, description="原样返回检索内容，跳过本地大模型与抽取式改写")
    time_range: Optional[Literal["day", "week", "month", "year", "all"]] = None
    history: List[Dict[str, str]] = Field(default_factory=list)


class TrendingItem(BaseModel):
    rank: int
    title: str
    url: str
    hot_value: Optional[str] = None  # 展示用热度文案，如 "456.7万热度"
    hot_score: Optional[int] = None  # 原始数值热度（如有）
    subtitle: Optional[str] = None  # 副标题 / 摘要
    cover: Optional[str] = None  # 封面图
    tag: Optional[str] = None  # 附加标签，如微博的 热爆新 / 语言名
    video_platform: Optional[str] = None  # bilibili：该条可换取详情
    video_id: Optional[str] = None  # 用于取链的稳定 ID（B站为 BV 号，红果/网文为 book_id）


class TrendingBoard(BaseModel):
    board_id: str
    name: str
    source: str  # 来源站点域名
    category: str  # comprehensive / tech / community / knowledge
    emoji: str
    site_url: str
    items: List[TrendingItem] = Field(default_factory=list)
    status: str = "success"
    error_message: Optional[str] = None
    latency_ms: int = 0
    fetched_at: Optional[str] = None
    cached: bool = False


class ApiKeyCreate(BaseModel):
    provider_id: str
    label: str = "默认密钥"
    api_key: str
    base_url: Optional[str] = None
    weight: int = 1
    rpm_limit: int = 60
    daily_quota: int = 10000
    use_proxy: Optional[bool] = None  # None = inherit from provider
    custom_proxy: Optional[str] = None
    enabled: bool = True


class ProviderUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
    weight: Optional[float] = None
    timeout_ms: Optional[int] = None
    use_proxy: Optional[bool] = None
    custom_proxy: Optional[str] = None
    base_url: Optional[str] = None
    default_model: Optional[str] = None
    strategy: Optional[str] = None  # round_robin, weighted, priority, least_used


class ProviderCreate(BaseModel):
    id: str
    name: str
    provider_type: Literal["llm", "reranker", "search", "scraper"] = "llm"
    category: str = "llm"
    base_url: str
    default_model: str = ""
    use_proxy: bool = False
    custom_proxy: str = ""
    timeout_ms: int = 30000
    weight: float = 1.5
    strategy: str = "weighted"
    description: str = ""
    api_key: Optional[str] = None
    key_label: str = "默认密钥"


class RouteGroupUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    engines: Optional[List[str]] = None
    fallback_engines: Optional[List[str]] = None
    timeout_ms: Optional[int] = None
    top_k: Optional[int] = None
    enable_rerank: Optional[bool] = None
    scrape_top_n: Optional[int] = None
    enabled: Optional[bool] = None


class GatewaySettingsUpdate(BaseModel):
    global_proxy: Optional[str] = None
    enable_global_proxy: Optional[bool] = None
    cache_ttl_seconds: Optional[int] = None
    enable_cache: Optional[bool] = None
    rrf_k: Optional[int] = None
    multi_source_boost: Optional[float] = None
    circuit_breaker_threshold: Optional[int] = None
    circuit_breaker_cooldown_sec: Optional[int] = None
    blocked_domains: Optional[List[str]] = None
    boosted_domains: Optional[List[str]] = None
    default_llm_provider: Optional[str] = None
    default_llm_model: Optional[str] = None
    default_reranker_provider: Optional[str] = None
    router_mode: Optional[Literal["rule", "jev", "ai"]] = None
    jev_api_url: Optional[str] = None
    jev_api_key: Optional[str] = None
    jev_model: Optional[str] = None
    jev_confidence_threshold: Optional[float] = None
    jev_timeout_ms: Optional[int] = None
    ai_router_provider: Optional[str] = None
    ai_router_model: Optional[str] = None
    ai_router_timeout_ms: Optional[int] = None
