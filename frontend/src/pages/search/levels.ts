import type { UnifiedSearchResponse } from '../../api';

/* --------------------------------------------------------------------------
   由浅入深的四档能力：工作台的每一档都对应一个开放 API 调用，
   这里是两边共用的单一事实来源（模式说明、参数映射、请求示例）。
   -------------------------------------------------------------------------- */

export type SearchMode = 'direct' | 'fast' | 'deep' | 'agentic';
export type SearchDepth = 'basic' | 'advanced' | 'deep';

export interface ModeMeta {
  key: SearchMode;
  level: string;
  label: string;
  caption: string;
  llmCalls: string;
  pipeline: string[];
  api: string;
}

export const MODES: ModeMeta[] = [
  {
    key: 'direct',
    level: 'L0',
    label: '直接搜索',
    caption: '纯检索 · 不生成回答',
    llmCalls: '不生成回答',
    pipeline: ['意图路由', '多源并发扇出', 'URL 归一去重', 'RRF 融合排序'],
    api: 'POST /v1/search',
  },
  {
    key: 'fast',
    level: 'L1',
    label: '极速快答',
    caption: '单轮检索 + 带引用回答',
    llmCalls: '大模型 1 次',
    pipeline: ['意图路由', '多源扇出 + 融合', '语义重排', '精读 Top 信源', '带引用回答'],
    api: 'POST /v1/answer',
  },
  {
    key: 'deep',
    level: 'L2',
    label: '深度研究',
    caption: '子问题并发 + 研究报告',
    llmCalls: '大模型 2 次',
    pipeline: ['拆解 3 个子问题', '子问题并发检索', '跨子问题融合', '结构化研究报告'],
    api: 'POST /v1/research · deep',
  },
  {
    key: 'agentic',
    level: 'L3',
    label: 'Agent 自主',
    caption: '多轮反思 + 正文精读',
    llmCalls: '大模型多轮',
    pipeline: ['规划首轮任务', '并发检索', '精读正文', '反思证据缺口', '定向补检', '成文'],
    api: 'POST /v1/research · agentic',
  },
];

export const modeMeta = (key: SearchMode): ModeMeta => MODES.find((m) => m.key === key) || MODES[0];

export const DEPTHS: { key: SearchDepth; label: string; hint: string; step?: string }[] = [
  { key: 'basic', label: '基础', hint: '多源召回 + RRF 融合' },
  { key: 'advanced', label: '重排', hint: '再做语义重排', step: '语义重排' },
  { key: 'deep', label: '深读', hint: '重排 + 抓取 Top 3 正文', step: 'Top 3 正文抽取' },
];

/** 直接搜索各深度对应的内部请求参数，与 /v1/search 的 search_depth 口径一致。 */
export const DEPTH_REQUEST: Record<SearchDepth, { enable_rerank: boolean; scrape_top_n: number }> = {
  basic: { enable_rerank: false, scrape_top_n: 0 },
  advanced: { enable_rerank: true, scrape_top_n: 0 },
  deep: { enable_rerank: true, scrape_top_n: 3 },
};

export const ROUTE_OPTIONS = [
  {
    label: '自动判断',
    options: [
      { label: '智能路由', value: 'auto' },
      { label: '关键词规则', value: 'rule' },
      { label: '大模型判断', value: 'ai' },
      { label: 'Jev 决策模型', value: 'jev' },
    ],
  },
  {
    label: '指定领域',
    options: [
      { label: '全网综合', value: 'web' },
      { label: '学术文献', value: 'academic' },
      { label: '开源代码', value: 'code' },
      { label: '社区舆情', value: 'social' },
      { label: '娱乐 / 音乐 / 短剧', value: 'entertainment' },
    ],
  },
];

export const TIME_OPTIONS = [
  { label: '智能判断', value: 'auto' },
  { label: '不限时间', value: 'all' },
  { label: '近一天', value: 'day' },
  { label: '近一周', value: 'week' },
  { label: '近一月', value: 'month' },
  { label: '近一年', value: 'year' },
];

/* ------------------------------ API 映射 ------------------------------ */

const ROUTE_TO_TOPIC: Record<string, string> = {
  academic: 'academic',
  code: 'code',
  social: 'social',
  entertainment: 'entertainment',
};

export interface ApiParams {
  mode: SearchMode;
  query: string;
  depth: SearchDepth;
  routeGroup: string;
  timeRange: string;
  topK: number;
  maxRounds: number;
  readingBudget: number;
}

export interface ApiRequest {
  path: string;
  label: string;
  rung: string | null;
  body: Record<string, unknown>;
  note: string;
}

const URL_IN_TEXT = /https?:\/\/[^\s<>"'`，。；！？、]+/gi;

/** 开放 API 的能力阶梯：每往下一级多一步处理、多一点计费。units 读取「套餐与定价」里的实时配置。 */
export interface ApiRung {
  id: string;
  path: string;
  param: string;
  adds: string;
  llm: boolean;
  unitsKey: [string, string];
  defaultUnits: number;
}

export const API_LADDER: ApiRung[] = [
  { id: 'search-basic', path: '/v1/search', param: 'search_depth=basic', adds: '多源召回 · 去重 · RRF 融合', llm: false, unitsKey: ['search', 'basic'], defaultUnits: 1 },
  { id: 'search-advanced', path: '/v1/search', param: 'search_depth=advanced', adds: '＋ 语义重排', llm: false, unitsKey: ['search', 'advanced'], defaultUnits: 2 },
  { id: 'search-deep', path: '/v1/search', param: 'search_depth=deep', adds: '＋ Top 3 正文抽取', llm: false, unitsKey: ['search', 'deep'], defaultUnits: 3 },
  { id: 'answer-fast', path: '/v1/answer', param: 'model=omni-fast', adds: '＋ 大模型带引用回答', llm: true, unitsKey: ['answer', 'fast'], defaultUnits: 2 },
  { id: 'research-deep', path: '/v1/research', param: 'mode=deep', adds: '＋ 子问题拆解 · 并发研究报告', llm: true, unitsKey: ['research', 'deep'], defaultUnits: 5 },
  { id: 'research-agentic', path: '/v1/research', param: 'mode=agentic', adds: '＋ 多轮反思 · 正文精读 · 缺口补检', llm: true, unitsKey: ['research', 'agentic'], defaultUnits: 8 },
];

export const rungUnits = (rung: ApiRung, units?: Record<string, any> | null): number => {
  const value = units?.[rung.unitsKey[0]]?.[rung.unitsKey[1]];
  return typeof value === 'number' ? value : rung.defaultUnits;
};

export function buildApiRequest(p: ApiParams): ApiRequest {
  const common: Record<string, unknown> = { query: p.query.trim() || '你的问题' };
  const topic = ROUTE_TO_TOPIC[p.routeGroup];
  if (topic) common.topic = topic;
  if (p.timeRange !== 'auto' && p.timeRange !== 'all') common.time_range = p.timeRange;

  const bare = p.query.trim();
  const urls = p.query.match(URL_IN_TEXT) || (/^(www\.)?[\w.-]+\.[a-z]{2,}(\/\S*)?$/i.test(bare) ? [`https://${bare}`] : null);
  if (p.mode === 'direct' && urls) {
    return {
      path: '/v1/extract',
      label: 'urls',
      rung: null,
      body: { urls: Array.from(new Set(urls)).slice(0, 20), format: 'markdown' },
      note: '直接搜索里粘贴的链接走正文直读，对应 /v1/extract：只按成功抽取的 URL 计费（每条 1 次）。',
    };
  }

  switch (p.mode) {
    case 'fast':
      return {
        path: '/v1/answer',
        label: 'model=omni-fast',
        rung: 'answer-fast',
        body: { ...common, model: 'omni-fast', stream: true },
        note: '单轮检索后由大模型写带 [n] 角标的回答，与本页「极速快答」同一流程（检索参数略有差异）。',
      };
    case 'deep':
      return {
        path: '/v1/research',
        label: 'mode=deep',
        rung: 'research-deep',
        body: { ...common, mode: 'deep', stream: true },
        note: '与本页「深度研究」同一引擎：拆子问题并发检索，再写研究报告。',
      };
    case 'agentic':
      return {
        path: '/v1/research',
        label: 'mode=agentic',
        rung: 'research-agentic',
        body: {
          ...common,
          mode: 'agentic',
          max_rounds: p.maxRounds,
          reading_budget: p.readingBudget,
          stream: true,
        },
        note: '与本页「Agent 自主」同一引擎：多轮检索、精读、反思补检后成文。',
      };
    default:
      return {
        path: '/v1/search',
        label: `search_depth=${p.depth}`,
        rung: `search-${p.depth}`,
        body: { ...common, search_depth: p.depth, max_results: p.topK, include_trace: true },
        note: '与本页「直接搜索」同一内核：不生成回答，返回融合排序后的结果；include_trace 附带各引擎扇出明细，不额外计费。',
      };
  }
}

const shellQuote = (text: string) => `'${text.replace(/'/g, `'\\''`)}'`;

export function toCurl(origin: string, req: ApiRequest): string {
  return [
    `curl -sN ${origin}${req.path} \\`,
    '  -H "Authorization: Bearer sk-omni-xxxxxxxx" \\',
    '  -H "Content-Type: application/json" \\',
    `  -d ${shellQuote(JSON.stringify(req.body))}`,
  ].join('\n');
}

export function toPython(origin: string, req: ApiRequest): string {
  const body = JSON.stringify(req.body, null, 4)
    .replace(/\btrue\b/g, 'True')
    .replace(/\bfalse\b/g, 'False')
    .replace(/\bnull\b/g, 'None');
  const streaming = req.body.stream === true;
  return [
    'import requests',
    '',
    'resp = requests.post(',
    `    "${origin}${req.path}",`,
    '    headers={"Authorization": "Bearer sk-omni-xxxxxxxx"},',
    `    json=${body.replace(/\n/g, '\n    ')},`,
    streaming ? '    stream=True,' : null,
    `    timeout=${streaming ? 180 : 20},`,
    ')',
    streaming
      ? 'for line in resp.iter_lines(decode_unicode=True):\n    if line.startswith(("event:", "data:")):\n        print(line[:160])'
      : 'data = resp.json()\nfor item in data["results"]:\n    print(item["score"], item["title"], item["url"])',
  ]
    .filter((line) => line !== null)
    .join('\n');
}

/* --------------------------- /v1/search 返回预览 --------------------------- */

const round = (value: number, digits: number) => Number((value || 0).toFixed(digits));

/**
 * 把工作台拿到的内部检索结果按 /v1/search 的公开字段整理成预览（节选前 2 条）。
 * 字段口径与后端 router_public._to_public_item / _public_trace 保持一致。
 */
export function toPublicSearchPreview(resp: UnifiedSearchResponse, depth: SearchDepth) {
  const maxScore = Math.max(0, ...resp.results.map((r) => r.final_score || 0));
  const results = resp.results.slice(0, 2).map((item, index) => {
    const metadata: Record<string, unknown> = {
      source_engine: item.source_engine,
      positions: item.positions,
      rrf_score: round(item.rrf_score, 6),
    };
    if (item.rerank_score !== undefined && item.rerank_score !== null) {
      metadata.rerank_score = round(item.rerank_score, 6);
    }
    if (item.metadata?.evidence) metadata.evidence = item.metadata.evidence;
    return {
      id: `r${index + 1}`,
      title: item.title || item.url,
      url: item.url,
      snippet: (item.snippet || '').slice(0, 240) + ((item.snippet || '').length > 240 ? '…' : ''),
      content: depth === 'deep' && item.content ? `${item.content.slice(0, 120)}…（共 ${item.content.length} 字）` : null,
      domain: item.domain,
      published_at: item.published_at || null,
      score: maxScore > 0 ? round(item.final_score / maxScore, 4) : 0,
      category: item.category || 'web',
      sources: item.engines?.length ? item.engines : [item.source_engine],
      metadata,
    };
  });
  return {
    object: 'search',
    query: resp.query,
    route: resp.resolved_route,
    answer: null,
    results: resp.results.length > 2 ? [...results, `…其余 ${resp.results.length - 2} 条结构相同`] : results,
    trace: {
      route: resp.resolved_route,
      queries: resp.rewritten_queries,
      raw_results: resp.total_raw_results,
      merged_results: resp.total_merged_results,
      cross_engine_hits: resp.cross_engine_hits,
      engines: resp.engine_traces
        .filter((t) => t.status !== 'skipped')
        .map((t) => ({ id: t.engine_id, name: t.engine_name, status: t.status, latency_ms: t.latency_ms, result_count: t.result_count })),
    },
    cached: resp.cache_hit,
    engine_count: resp.engine_traces.length,
  };
}
