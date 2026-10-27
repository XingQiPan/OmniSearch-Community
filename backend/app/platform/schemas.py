"""对外 API 的请求/响应模型（OpenAPI 即接口文档）。

命名对齐主流搜索 API 的公开字段，同时对内做别名兼容：
``query``/``q``、``max_results``/``top_k``、``search_depth``/``mode``、
``freshness``/``time_range`` 均可使用。
"""
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SearchDepth = Literal["basic", "advanced", "deep"]
Topic = Literal["general", "news", "academic", "code", "social", "entertainment"]
ResponseFormat = Literal["json", "markdown"]
ResearchMode = Literal["deep", "agentic"]


class UsageInfo(BaseModel):
    units: int = Field(..., description="本次调用消耗的次数（计费单位）")
    unit: str = Field("request", description="计量单位，固定为 request")
    credits_used: Optional[int] = Field(None, description="`units` 的 credit 命名别名，便于对标 Tavily / Firecrawl")
    unit_price_cny_per_1k: float = Field(0.0, description="当前套餐的千次单价（元/千次）")
    cost_cny: float = Field(0.0, description="本次调用折算金额（元）")
    currency: str = Field("CNY")
    billing_mode: str = Field("prepaid", description="prepaid 预付费 / postpaid 后付费 / internal 内部计费")
    remaining_units: Optional[int] = Field(None, description="预付费账户扣费后的剩余次数")
    credits_remaining: Optional[int] = Field(None, description="`remaining_units` 的 credit 命名别名")


class PublicSearchRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    query: Optional[str] = Field(None, description="检索词，1~2000 字；也可用 `q`")
    q: Optional[str] = Field(None, description="`query` 的简写别名")

    search_depth: SearchDepth = Field("basic", description="basic 快速召回 / advanced 语义重排 / deep 深度研究")
    mode: Optional[SearchDepth] = Field(None, description="`search_depth` 的别名，兼容旧调用")
    topic: Topic = Field("general", description="检索领域，决定路由分组与信源池")

    max_results: int = Field(10, ge=1, le=50, description="返回条数上限")
    top_k: Optional[int] = Field(None, ge=1, le=50, description="`max_results` 的别名")

    include_domains: List[str] = Field(default_factory=list, description="仅保留这些域名")
    exclude_domains: List[str] = Field(default_factory=list, description="排除这些域名")

    time_range: Optional[str] = Field(None, description="day / week / month / year；也可直接传 freshness 的 pd/pw/pm/py")
    freshness: Optional[str] = Field(None, description="Brave 风格时间过滤：pd/pw/pm/py 或 YYYY-MM-DDtoYYYY-MM-DD")
    start_date: Optional[str] = Field(None, description="起始发布日期，YYYY-MM-DD（尽力而为过滤）")
    end_date: Optional[str] = Field(None, description="结束发布日期，YYYY-MM-DD")

    include_answer: Union[bool, Literal["basic", "detailed"]] = Field(
        False, description="是否在响应中附带跨源答案：false / true / \"basic\" / \"detailed\""
    )
    include_raw_content: Union[bool, Literal["markdown", "text"]] = Field(
        False, description="是否为 Top 结果抓取网页正文写入 content"
    )
    include_images: bool = Field(False, description="是否返回结果中的封面/配图 URL")
    include_favicon: bool = Field(True, description="是否返回站点 favicon")
    include_trace: bool = Field(False, description="是否返回 trace：路由、各引擎状态/耗时/条数、召回与去重统计（不额外计费）")

    response_format: ResponseFormat = Field("json", description="json 标准结构 / markdown 追加 LLM 友好的 markdown 字段")
    country: Optional[str] = Field(None, description="国家/地区代码，如 CN / US")
    language: Optional[str] = Field(None, description="结果语言偏好，如 zh / en")

    engines: Optional[List[str]] = Field(None, description="指定检索引擎 ID，仅限专业版及以上")
    rerank: Optional[bool] = Field(None, description="是否对融合结果做语义重排（专业版及以上）")
    cache: bool = Field(True, description="是否允许命中网关语义缓存")
    timeout_ms: Optional[int] = Field(None, ge=2000, le=30000, description="端到端超时预算（毫秒）")

    @field_validator("query", "q")
    @classmethod
    def _strip(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _normalize(self):
        if not self.query and self.q:
            self.query = self.q
        if self.query is not None and len(self.query) > 2000:
            raise ValueError("query 最长 2000 字符")
        if self.top_k is not None:
            self.max_results = self.top_k
        if self.mode:
            self.search_depth = self.mode
        if not self.time_range and self.freshness:
            self.time_range = self.freshness
        return self


class SearchResultItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(..., description="结果在本响应内的稳定编号")
    title: str
    url: str
    snippet: str = Field("", description="检索摘要（清洗后的短文本）")
    content: Optional[str] = Field(None, description="正文；仅在 include_raw_content 时填充")
    domain: str = ""
    published_at: Optional[str] = None
    favicon: Optional[str] = None
    score: float = Field(0.0, description="归一化到 0~1 的相关度分数")
    category: str = "web"
    sources: List[str] = Field(default_factory=list, description="命中该 URL 的引擎列表（跨源重合度）")
    images: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    request_id: str
    object: str = "search"
    query: str
    route: str = "auto"
    answer: Optional[str] = Field(None, description="include_answer 为真时的跨源答案")
    results: List[SearchResultItem] = Field(default_factory=list)
    images: List[str] = Field(default_factory=list)
    markdown: Optional[str] = Field(None, description="response_format=markdown 时的 LLM 友好文本")
    trace: Optional[Dict[str, Any]] = Field(None, description="include_trace 为真时的检索过程：路由、引擎扇出、召回/去重统计")
    cached: bool = False
    latency_ms: int = 0
    engine_count: int = Field(0, description="本次实际参与检索的上游引擎数量")
    usage: UsageInfo


class PublicExtractRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    urls: List[str] = Field(..., min_length=1, description="待抽取正文的 URL 列表（单次上限 20）")
    format: Literal["markdown", "text", "html"] = Field("markdown", description="正文输出格式")
    include_images: bool = False
    timeout_ms: int = Field(15000, ge=2000, le=60000)


class ExtractResultItem(BaseModel):
    url: str
    title: Optional[str] = None
    content: str = ""
    format: str = "markdown"
    length: int = 0
    status: Literal["success", "error"] = "success"
    error: Optional[str] = None
    published_at: Optional[str] = None
    retrieved_at: Optional[str] = None
    truncated: bool = False


class ExtractResponse(BaseModel):
    request_id: str
    object: str = "extract"
    results: List[ExtractResultItem] = Field(default_factory=list)
    success_count: int = 0
    failed_count: int = 0
    latency_ms: int = 0
    usage: UsageInfo


class PublicAnswerRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    query: Optional[str] = Field(None, description="问题或检索词")
    q: Optional[str] = Field(None, description="`query` 的别名")
    model: Literal["omni-fast", "omni-deep", "omni-fast-search", "omni-deep-research"] = Field(
        "omni-fast", description="答案模型：omni-fast 快答 / omni-deep 深度研究"
    )
    topic: Topic = "general"
    max_results: int = Field(8, ge=1, le=30)
    include_domains: List[str] = Field(default_factory=list)
    exclude_domains: List[str] = Field(default_factory=list)
    time_range: Optional[str] = None
    stream: bool = Field(False, description="true 时返回 text/event-stream 增量答案")
    citations: bool = Field(True, description="是否返回带编号的引用来源列表")
    response_format: ResponseFormat = "json"
    timeout_ms: Optional[int] = Field(None, ge=2000, le=30000)

    @field_validator("query", "q")
    @classmethod
    def _strip(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _normalize(self):
        if not self.query and self.q:
            self.query = self.q
        if self.query is not None and len(self.query) > 2000:
            raise ValueError("query 最长 2000 字符")
        return self


class Citation(BaseModel):
    index: int
    title: str
    url: str
    domain: str = ""


class AnswerResponse(BaseModel):
    request_id: str
    object: str = "answer"
    query: str
    model: str = "omni-fast"
    answer: str = ""
    citations: List[Citation] = Field(default_factory=list)
    markdown: Optional[str] = None
    cached: bool = False
    latency_ms: int = 0
    usage: UsageInfo


class PublicResearchRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    query: Optional[str] = Field(None, description="研究课题；也可用 `q`")
    q: Optional[str] = Field(None, description="`query` 的别名")
    mode: ResearchMode = Field(
        "deep", description="deep 子问题拆解并发检索 + 研究报告 / agentic 多轮反思、正文精读、证据缺口补检"
    )
    topic: Topic = "general"
    max_results: int = Field(12, ge=5, le=30, description="报告引用的信源条数上限")
    max_rounds: int = Field(2, ge=1, le=4, description="agentic 最大探索轮数")
    reading_budget: int = Field(8, ge=0, le=12, description="agentic 正文精读预算（篇），0 表示只用摘要")
    time_range: Optional[str] = Field(None, description="day / week / month / year，或 pd/pw/pm/py")
    stream: bool = Field(False, description="true 时以 SSE 推送研究过程（plan/read/decision/sources）与增量报告")
    response_format: ResponseFormat = "json"

    @field_validator("query", "q")
    @classmethod
    def _strip(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _normalize(self):
        if not self.query and self.q:
            self.query = self.q
        if self.query is not None and len(self.query) > 2000:
            raise ValueError("query 最长 2000 字符")
        return self


class ResearchResponse(BaseModel):
    request_id: str
    object: str = "research"
    query: str
    mode: str = "deep"
    route: str = "auto"
    answer: str = Field("", description="带 [n](URL) 引用的 Markdown 研究报告")
    results: List[SearchResultItem] = Field(default_factory=list, description="报告使用的融合信源")
    plan: List[Dict[str, Any]] = Field(default_factory=list, description="子问题 / 各轮检索节点")
    reads: List[Dict[str, Any]] = Field(default_factory=list, description="正文精读记录（agentic）")
    decisions: List[Dict[str, Any]] = Field(default_factory=list, description="每轮是否继续深挖的判断（agentic）")
    pages: List[Dict[str, Any]] = Field(default_factory=list, description="课题里带链接时直接读取的网页正文")
    suggestions: List[str] = Field(default_factory=list)
    llm_generated: bool = Field(False, description="报告是否由大模型撰写；false 表示内置抽取式合成或数据直出")
    data_direct: bool = Field(False, description="是否命中数据直出（榜单 / 链接直读），未经大模型改写")
    markdown: Optional[str] = None
    latency_ms: int = 0
    usage: UsageInfo


class MeKey(BaseModel):
    id: str
    label: str
    masked: str
    scopes: List[str] = Field(default_factory=list)
    rpm_limit: int = 0
    rpd_limit: int = 0
    expires_at: float = 0
    created_at: float = 0


class MeResponse(BaseModel):
    object: str = "account"
    client_id: str
    name: str
    email: str = ""
    company: str = ""
    status: str = "active"
    billing_mode: str = "prepaid"
    plan: Dict[str, Any] = Field(default_factory=dict)
    balance_units: int = 0
    limits: Dict[str, Any] = Field(default_factory=dict)
    key: MeKey
    usage_this_month: Dict[str, Any] = Field(default_factory=dict)


class UsageResponse(BaseModel):
    object: str = "usage"
    client_id: str
    range: Dict[str, Any] = Field(default_factory=dict)
    totals: Dict[str, Any] = Field(default_factory=dict)
    series: List[Dict[str, Any]] = Field(default_factory=list)
    endpoints: List[Dict[str, Any]] = Field(default_factory=list)


class ModelCard(BaseModel):
    id: str
    object: str = "model"
    owned_by: str = "omnisearch"
    description: str = ""
    search_depth: str = "basic"


class ModelListResponse(BaseModel):
    object: str = "list"
    data: List[ModelCard] = Field(default_factory=list)


class SignupRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=80, description="客户/团队名称")
    email: str = Field(..., min_length=5, max_length=120)
    company: str = Field("", max_length=120)
    use_case: str = Field("", max_length=300, description="使用场景，便于商务跟进")


class SignupResponse(BaseModel):
    object: str = "signup"
    client_id: str
    api_key: str = Field(..., description="明文密钥，仅此一次返回，请立即保存")
    plan: Dict[str, Any] = Field(default_factory=dict)
    balance_units: int = 0
    quickstart: Dict[str, str] = Field(default_factory=dict)
