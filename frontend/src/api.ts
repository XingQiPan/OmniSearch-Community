export interface ApiKeyItem {
  id: string;
  provider_id: string;
  label: string;
  api_key_masked: string;
  base_url: string;
  weight: number;
  rpm_limit: number;
  daily_quota: number;
  used_today: number;
  total_used: number;
  use_proxy: number;
  custom_proxy: string;
  enabled: number;
  last_used_at: number;
  last_latency_ms: number;
  last_status: string;
  last_error: string;
}

export interface ProviderItem {
  id: string;
  name: string;
  category: string;
  provider_type: 'search' | 'scraper' | 'reranker' | 'llm';
  requires_key: number;
  enabled: number;
  weight: number;
  timeout_ms: number;
  use_proxy: number;
  custom_proxy: string;
  base_url: string;
  default_model: string;
  strategy: string;
  icon: string;
  description: string;
  doc_url: string;
  total_calls: number;
  success_calls: number;
  failed_calls: number;
  avg_latency_ms: number;
  consecutive_failures: number;
  is_circuit_open: boolean;
  health_status: 'ready' | 'missing_key' | 'circuit_open' | 'disabled';
  last_error: string;
  keys: ApiKeyItem[];
  active_key_count: number;
  total_key_count: number;
}

export interface RouteGroupItem {
  id: string;
  name: string;
  description: string;
  engines: string[];
  fallback_engines: string[];
  timeout_ms: number;
  top_k: number;
  enable_rerank: number;
  scrape_top_n: number;
  enabled: number;
}

export interface UnifiedSearchItem {
  title: string;
  url: string;
  normalized_url: string;
  snippet: string;
  content?: string;
  published_at?: string;
  favicon?: string;
  domain: string;
  source_engine: string;
  engines: string[];
  positions: Record<string, number>;
  raw_score: number;
  rrf_score: number;
  rerank_score?: number;
  final_score: number;
  category: string;
  metadata?: Record<string, any>;
}

export interface TrendingItem {
  rank: number;
  title: string;
  url: string;
  hot_value?: string;
  hot_score?: number;
  subtitle?: string;
  cover?: string;
  tag?: string;
  video_platform?: 'bilibili';
  video_id?: string | null;
}

export interface TrendingBoard {
  board_id: string;
  name: string;
  source: string;
  category: string;
  emoji: string;
  site_url: string;
  items: TrendingItem[];
  status: 'success' | 'error';
  error_message?: string;
  latency_ms: number;
  fetched_at?: string;
  cached: boolean;
}

export interface EngineExecutionTrace {
  engine_id: string;
  engine_name: string;
  status: 'success' | 'error' | 'timeout' | 'skipped' | 'circuit_open';
  latency_ms: number;
  result_count: number;
  used_key_masked?: string;
  used_proxy: boolean;
  error_message?: string;
}

export interface UnifiedSearchResponse {
  trace_id: string;
  query: string;
  rewritten_queries: string[];
  resolved_route: string;
  total_latency_ms: number;
  total_raw_results: number;
  total_merged_results: number;
  cross_engine_hits: number;
  cache_hit: boolean;
  engine_traces: EngineExecutionTrace[];
  results: UnifiedSearchItem[];
  per_engine_results: Record<string, UnifiedSearchItem[]>;
}

export interface WebpageReadItem {
  url: string;
  final_url: string;
  title: string;
  content: string;
  format: 'markdown' | 'text' | string;
  length: number;
  status: 'success' | 'error';
  error?: string | null;
  published_at?: string | null;
  retrieved_at?: string | null;
  truncated: boolean;
  read_source?: string | null;
  latency_ms: number;
}

export interface WebpageReadResponse {
  object: string;
  results: WebpageReadItem[];
  success_count: number;
  failed_count: number;
  latency_ms: number;
}

/** 直接读取链接正文；普通关键词搜索仍由 /api/v1/agent/stream 负责。 */
export async function readWebpage(
  urls: string[],
  format: 'markdown' | 'text' = 'markdown',
): Promise<WebpageReadResponse> {
  const resp = await fetch('/api/v1/webpage/read', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ urls, format, timeout_ms: 15000, max_chars: 16000 }),
  });
  const body = await resp.json().catch(() => null);
  if (!resp.ok) {
    throw new Error(body?.detail || `HTTP ${resp.status}`);
  }
  return body as WebpageReadResponse;
}
