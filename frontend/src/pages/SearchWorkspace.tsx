import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Button, Col, Drawer, Input, Row, Segmented, Select, Spin, Tooltip, message } from 'antd';
import type { InputRef } from 'antd';
import type { UnifiedSearchResponse } from '../api';
import { readWebpage } from '../api';
import { CopyButton, EmptyState, Kbd, PageHeader, Pill, Section } from '../components/ui';
import {
  IconAlert,
  IconArrowUpRight,
  IconBot,
  IconChevronRight,
  IconCode,
  IconGlobe,
  IconLayers,
  IconSearch,
  IconSparkles,
  IconZap,
} from '../components/icons';
import { renderMarkdownWithCitations } from './search/markdown';
import { DirectPage, PageContentView, ResultCard } from './search/ResultCard';
import { DirectResults } from './search/DirectResults';
import { ApiDrawer } from './search/ApiDrawer';
import { AgentDecisionEvent, AgentReadEvent, DagNode, DirectInfo, TracePanel } from './search/TracePanel';
import {
  buildApiRequest,
  DEPTH_REQUEST,
  DEPTHS,
  MODES,
  modeMeta,
  ROUTE_OPTIONS,
  SearchDepth,
  SearchMode,
  TIME_OPTIONS,
} from './search/levels';

const looksLikeUrl = (value: string): boolean =>
  /https?:\/\//i.test(value) || /(^|\s)www\./i.test(value) || /^[\w.-]+\.[a-z]{2,}(\/\S*)?$/i.test(value.trim());

const MODE_ICONS: Record<SearchMode, React.ReactNode> = {
  direct: <IconSearch size={15} />,
  fast: <IconZap size={15} />,
  deep: <IconLayers size={15} />,
  agentic: <IconBot size={15} />,
};

const PLACEHOLDERS: Record<SearchMode, string> = {
  direct: '输入关键词直接检索，看各引擎表现与融合排序；也可粘贴网页 / 抖音 / B站链接',
  fast: '输入问题：检索后由大模型给出带引用角标的回答',
  deep: '输入研究课题：自动拆成子问题并发检索，再写研究报告',
  agentic: '输入复杂课题：Agent 多轮检索、精读正文、反思补检后成文',
};

const SUBMIT_LABELS: Record<SearchMode, string> = {
  direct: '搜索',
  fast: '快答',
  deep: '开始研究',
  agentic: '启动 Agent',
};

const EXAMPLES = ['RRF 倒数排名融合', '2026 开源 AI 搜索框架', 'FastAPI SSE 流式输出', 'Agent 记忆机制 综述'];

type Layout = 'serp' | 'answer' | null;

interface PageDrawerState {
  open: boolean;
  loading: boolean;
  page: DirectPage | null;
  error?: string;
}

export const SearchWorkspace: React.FC = () => {
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState<SearchMode>('direct');
  const [depth, setDepth] = useState<SearchDepth>('basic');
  const [topK, setTopK] = useState(20);
  const [routeGroup, setRouteGroup] = useState('auto');
  const [timeRange, setTimeRange] = useState('auto');
  const [scrapeTopN, setScrapeTopN] = useState(2);
  const [maxRounds, setMaxRounds] = useState(2);
  const [readingBudget, setReadingBudget] = useState(10);

  const [layout, setLayout] = useState<Layout>(null);
  const [ranMode, setRanMode] = useState<SearchMode>('direct');
  const [loading, setLoading] = useState(false);
  const [stopped, setStopped] = useState(false);
  const [stepMsg, setStepMsg] = useState('');
  const [searchError, setSearchError] = useState('');
  const [direct, setDirect] = useState<{ resp: UnifiedSearchResponse; depth: SearchDepth } | null>(null);
  const [dagNodes, setDagNodes] = useState<DagNode[]>([]);
  const [agentReads, setAgentReads] = useState<AgentReadEvent[]>([]);
  const [agentDecisions, setAgentDecisions] = useState<AgentDecisionEvent[]>([]);
  const [searchMeta, setSearchMeta] = useState<UnifiedSearchResponse | null>(null);
  const [directInfo, setDirectInfo] = useState<DirectInfo | null>(null);
  const [directPages, setDirectPages] = useState<DirectPage[]>([]);
  const [answerMd, setAnswerMd] = useState('');
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [traceOpen, setTraceOpen] = useState(true);
  const [apiOpen, setApiOpen] = useState(false);
  const [pageDrawer, setPageDrawer] = useState<PageDrawerState>({ open: false, loading: false, page: null });

  const abortRef = useRef<AbortController | null>(null);
  const traceTouched = useRef(false);
  const traceCollapsed = useRef(false);
  const inputRef = useRef<InputRef>(null);

  // 「/」快速聚焦搜索框；离开页面时中断进行中的检索
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey) return;
      const target = e.target as HTMLElement | null;
      if (target && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))) return;
      e.preventDefault();
      inputRef.current?.focus();
    };
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('keydown', onKey);
      abortRef.current?.abort();
    };
  }, []);

  const resetResults = () => {
    setSearchError('');
    setStopped(false);
    setDirect(null);
    setDagNodes([]);
    setAgentReads([]);
    setAgentDecisions([]);
    setSearchMeta(null);
    setDirectInfo(null);
    setDirectPages([]);
    setAnswerMd('');
    setSuggestions([]);
    setPageDrawer((prev) => ({ ...prev, open: false }));
    setTraceOpen(true);
    traceTouched.current = false;
    traceCollapsed.current = false;
  };

  /** L0 直接搜索：调用与 /v1/search 同一内核的 /api/v1/search，不生成回答。 */
  const runDirect = async (q: string, signal: AbortSignal) => {
    setLayout('serp');
    setStepMsg('多源并发检索中…');
    const resp = await fetch('/api/v1/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal,
      body: JSON.stringify({
        query: q,
        route_group: routeGroup,
        top_k: topK,
        ...DEPTH_REQUEST[depth],
        ...(timeRange !== 'auto' ? { time_range: timeRange } : {}),
      }),
    });
    const data = await resp.json().catch(() => null);
    if (!resp.ok || !data) {
      const detail = data?.detail ? (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)) : '';
      throw new Error(detail.slice(0, 200) || `HTTP ${resp.status}`);
    }
    if (signal.aborted) return;
    const result = data as UnifiedSearchResponse;
    setDirect({ resp: result, depth });
    setSearchMeta(result);
    const ok = result.engine_traces.filter((t) => t.status === 'success').length;
    setStepMsg(`检索完成：${ok} 个引擎返回 ${result.total_raw_results} 条，融合为 ${result.total_merged_results} 条`);
  };

  /** L1~L3（以及直接搜索里粘贴的链接）：走工作台 Agent 的 SSE 流。 */
  const runStream = async (q: string, activeMode: SearchMode, signal: AbortSignal) => {
    setLayout('answer');
    setStepMsg('正在启动意图路由与多源扇出调度…');
    const rawOnly = activeMode === 'direct';
    const resp = await fetch('/api/v1/agent/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal,
      body: JSON.stringify({
        query: q,
        mode: rawOnly ? 'fast' : activeMode,
        route_group: routeGroup,
        top_k: 15,
        scrape_top_n: scrapeTopN,
        max_rounds: maxRounds,
        reading_budget: readingBudget,
        time_range: timeRange === 'auto' ? null : timeRange,
        raw: rawOnly,
      }),
    });
    if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`);

    const reader = resp.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    let completed = false;

    while (true) {
      const { value, done } = await reader.read();
      if (done || signal.aborted) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split('\n\n');
      buffer = events.pop() || '';

      for (const ev of events) {
        const line = ev.trim();
        if (!line.startsWith('data:')) continue;
        let payload: any;
        try {
          payload = JSON.parse(line.slice(5).trim());
        } catch {
          continue; // 半截 JSON，等下一块
        }
        if (payload.type === 'step') {
          setStepMsg(payload.data.message);
        } else if (payload.type === 'dag') {
          setDagNodes(payload.data.nodes || []);
        } else if (payload.type === 'agent_read') {
          setAgentReads((prev) => [...prev, ...(payload.data.items || [])]);
        } else if (payload.type === 'agent_decision') {
          setAgentDecisions((prev) => [...prev, payload.data]);
        } else if (payload.type === 'page') {
          setDirectPages(payload.data?.pages || []);
        } else if (payload.type === 'sources') {
          setSearchMeta(payload.data);
          setDirectInfo({
            data_direct: Boolean(payload.data?.data_direct),
            processed_by_llm: payload.data?.processed_by_llm,
            direct_reason: payload.data?.direct_reason,
            boards: payload.data?.boards || [],
            source_breakdown: payload.data?.source_breakdown || {},
            fetched_at: payload.data?.fetched_at,
          });
        } else if (payload.type === 'token') {
          // 回答开始输出：轨迹自动收起成一行摘要（用户手动展开过则尊重用户）
          if (!traceTouched.current && !traceCollapsed.current) {
            traceCollapsed.current = true;
            setTraceOpen(false);
          }
          setAnswerMd((prev) => prev + payload.data);
        } else if (payload.type === 'suggestions') {
          setSuggestions(payload.data || []);
        } else if (payload.type === 'done') {
          completed = true;
          setStepMsg('检索与合成已完成');
        }
      }
    }
    if (!completed && !signal.aborted) throw new Error('响应流提前结束，未收到完成信号，请重试');
  };

  const handleSearch = async (override?: { query?: string; mode?: SearchMode }) => {
    const q = (override?.query ?? query).trim();
    if (!q) {
      message.warning('请输入要检索的问题、关键词或链接');
      inputRef.current?.focus();
      return;
    }
    const activeMode = override?.mode ?? mode;
    if (override?.query !== undefined) setQuery(override.query);
    if (override?.mode) setMode(override.mode);

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    resetResults();
    setRanMode(activeMode);
    setLoading(true);

    try {
      if (activeMode === 'direct' && !looksLikeUrl(q)) {
        await runDirect(q, controller.signal);
      } else {
        await runStream(q, activeMode, controller.signal);
      }
    } catch (err: unknown) {
      if (controller.signal.aborted) {
        // 被新的检索替换时静默；用户点「停止」时给出提示
        if (abortRef.current === controller) {
          setStopped(true);
          setStepMsg('已手动停止');
        }
        return;
      }
      const detail = err instanceof Error ? err.message : String(err);
      setStepMsg('搜索失败');
      setSearchError(`搜索请求异常：${detail}`);
      message.error(`搜索请求异常：${detail}`);
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null;
        setLoading(false);
      }
    }
  };

  const stopSearch = () => abortRef.current?.abort();

  const handleReadPage = async (url: string, preloaded?: DirectPage) => {
    if (preloaded) {
      setPageDrawer({ open: true, loading: false, page: preloaded });
      return;
    }
    setPageDrawer({ open: true, loading: true, page: null });
    try {
      const data = await readWebpage([url]);
      const page = (data.results?.[0] || null) as DirectPage | null;
      setPageDrawer({ open: true, loading: false, page, error: page ? undefined : '接口未返回网页内容' });
    } catch (err: unknown) {
      const detail = err instanceof Error ? err.message : String(err);
      setPageDrawer({ open: true, loading: false, page: null, error: detail });
      message.error(`正文读取失败：${detail}`);
    }
  };

  const current = modeMeta(mode);
  const hasUrl = looksLikeUrl(query);
  const apiParams = useMemo(
    () => ({ mode, query, depth, routeGroup, timeRange, topK, maxRounds, readingBudget }),
    [mode, query, depth, routeGroup, timeRange, topK, maxRounds, readingBudget],
  );
  const apiRequest = useMemo(() => buildApiRequest(apiParams), [apiParams]);
  const pipeline =
    mode === 'direct'
      ? [...current.pipeline, ...DEPTHS.slice(1, DEPTHS.findIndex((d) => d.key === depth) + 1).map((d) => d.step as string)]
      : current.pipeline;

  const isDirect = Boolean(directInfo?.data_direct);
  const answerTitle = isDirect
    ? directInfo?.direct_reason === 'trending_data'
      ? '数据直出结果'
      : directInfo?.direct_reason === 'url_direct'
      ? '网页正文直读'
      : '原样返回内容'
    : ranMode === 'deep'
    ? '深度研究报告'
    : ranMode === 'agentic'
    ? 'Agent 研究报告'
    : 'AI 聚合回答';
  const answerResults = searchMeta?.results || [];
  const answerMaxScore = Math.max(0, ...answerResults.map((r) => r.final_score || 0));
  const hasRun = layout !== null;

  return (
    <div className="ws">
      <PageHeader
        icon={<IconSearch size={21} />}
        title="搜索工作台"
        subtitle="由浅入深四档：直接搜索 → 极速快答 → 深度研究 → Agent 自主；每一档都有等价的开放 API 调用。"
        extra={
          <Pill tone={searchError ? 'red' : loading ? 'accent' : stopped ? 'orange' : hasRun ? 'green' : 'default'}>
            <span
              className={`dot ${searchError ? 'red' : loading ? 'accent' : stopped ? 'orange' : hasRun ? 'green' : ''}`}
              style={{ boxShadow: 'none', width: 6, height: 6 }}
            />
            {searchError ? '上次检索异常' : loading ? '检索进行中' : stopped ? '已停止' : hasRun ? '检索已完成' : '待命'}
          </Pill>
        }
      />

      {/* 搜索主卡：模式阶梯 + 输入 + 当前模式的参数 */}
      <div className="card ws-hero section-gap">
        <div className="ws-ladder" role="tablist" aria-label="搜索模式">
          {MODES.map((m, idx) => (
            <button
              key={m.key}
              type="button"
              role="tab"
              aria-selected={mode === m.key}
              className={`ws-step ${mode === m.key ? 'active' : ''}`}
              style={{ '--lv': idx } as React.CSSProperties}
              onClick={() => setMode(m.key)}
            >
              <span className="ws-step-head">
                <span className="ws-step-icon">{MODE_ICONS[m.key]}</span>
                <span className="ws-step-label">{m.label}</span>
                <span className="ws-step-level">{m.level}</span>
              </span>
              <span className="ws-step-cap">{m.caption}</span>
            </button>
          ))}
        </div>

        <div className="ws-query">
          <Input
            ref={inputRef}
            size="large"
            value={query}
            allowClear
            onChange={(e) => setQuery(e.target.value)}
            onPressEnter={() => handleSearch()}
            prefix={hasUrl ? <IconGlobe size={17} style={{ color: 'var(--accent)' }} /> : <IconSearch size={17} style={{ color: 'var(--text-3)' }} />}
            suffix={query ? undefined : <Kbd>/</Kbd>}
            placeholder={PLACEHOLDERS[mode]}
            className="ws-input"
          />
          {loading ? (
            <Button size="large" danger onClick={stopSearch} className="ws-submit">
              停止
            </Button>
          ) : (
            <Button
              type="primary"
              size="large"
              onClick={() => handleSearch()}
              icon={hasUrl ? <IconGlobe size={16} /> : MODE_ICONS[mode]}
              className="ws-submit"
            >
              {hasUrl ? '读取网页' : SUBMIT_LABELS[mode]}
            </Button>
          )}
        </div>

        {hasUrl ? (
          <div className="ws-url-hint">
            <IconGlobe size={12} />
            检测到链接：直接抓取网页正文（抖音 / B站链接解析视频直链）；链接外的文字会继续检索。
          </div>
        ) : null}

        <div className="ws-options">
          <div className="ws-opt">
            <span>路由</span>
            <Select size="small" value={routeGroup} onChange={setRouteGroup} options={ROUTE_OPTIONS} style={{ width: 132 }} popupMatchSelectWidth={false} />
          </div>
          <div className="ws-opt">
            <span>时间</span>
            <Select size="small" value={timeRange} onChange={setTimeRange} options={TIME_OPTIONS} style={{ width: 104 }} />
          </div>
          {mode === 'direct' ? (
            <>
              <div className="ws-opt">
                <span>深度</span>
                <Segmented
                  size="small"
                  value={depth}
                  onChange={(v) => setDepth(v as SearchDepth)}
                  options={DEPTHS.map((d) => ({
                    value: d.key,
                    label: (
                      <Tooltip title={d.hint} mouseEnterDelay={0.3}>
                        <span>{d.label}</span>
                      </Tooltip>
                    ),
                  }))}
                />
              </div>
              <div className="ws-opt">
                <span>条数</span>
                <Select
                  size="small"
                  value={topK}
                  onChange={setTopK}
                  style={{ width: 82 }}
                  options={[10, 20, 30].map((n) => ({ label: `${n} 条`, value: n }))}
                />
              </div>
            </>
          ) : null}
          {mode === 'fast' ? (
            <div className="ws-opt">
              <span>精读信源</span>
              <Select
                size="small"
                value={scrapeTopN}
                onChange={setScrapeTopN}
                style={{ width: 92 }}
                options={[
                  { label: '只用摘要', value: 0 },
                  { label: 'Top 1', value: 1 },
                  { label: 'Top 2', value: 2 },
                  { label: 'Top 3', value: 3 },
                ]}
              />
            </div>
          ) : null}
          {mode === 'agentic' ? (
            <>
              <div className="ws-opt">
                <span>最多</span>
                <Select
                  size="small"
                  value={maxRounds}
                  onChange={setMaxRounds}
                  style={{ width: 76 }}
                  options={[1, 2, 3].map((n) => ({ label: `${n} 轮`, value: n }))}
                />
              </div>
              <div className="ws-opt">
                <span>精读预算</span>
                <Select
                  size="small"
                  value={readingBudget}
                  onChange={setReadingBudget}
                  style={{ width: 92 }}
                  options={[
                    { label: '只用摘要', value: 0 },
                    { label: '8 篇', value: 8 },
                    { label: '10 篇', value: 10 },
                    { label: '12 篇', value: 12 },
                  ]}
                />
              </div>
            </>
          ) : null}

          <Tooltip title="查看这一档对应的开放 API 请求与返回">
            <button type="button" className="ws-api-chip" onClick={() => setApiOpen(true)}>
              <IconCode size={13} />
              <span className="ws-api-path">{apiRequest.path}</span>
              <span className="faint">{apiRequest.label}</span>
            </button>
          </Tooltip>
        </div>
      </div>

      {/* 空闲态：当前模式的处理流程 + 示例 */}
      {!hasRun ? (
        <div className="ws-intro section-gap">
          <div className="ws-flow" aria-label={`${current.label}的处理流程`}>
            <Pill tone="accent">{current.level}</Pill>
            <strong className="ws-flow-title">{current.label}</strong>
            <span className="tiny faint">{current.llmCalls}</span>
            <span className="ws-flow-steps">
              {pipeline.map((step, idx) => (
                <React.Fragment key={step}>
                  {idx > 0 ? <IconChevronRight size={12} className="ws-flow-arrow" /> : null}
                  <span className="ws-flow-step">{step}</span>
                </React.Fragment>
              ))}
            </span>
          </div>
          <div className="ws-examples">
            <span className="tiny faint">试试</span>
            {EXAMPLES.map((ex) => (
              <button key={ex} type="button" className="chip" onClick={() => handleSearch({ query: ex })}>
                {ex}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {/* L0 直接搜索：结果页 */}
      {layout === 'serp' ? (
        direct ? (
          <DirectResults
            key={direct.resp.trace_id}
            resp={direct.resp}
            depth={direct.depth}
            onOpenApi={() => setApiOpen(true)}
           
            onReadPage={handleReadPage}
          />
        ) : searchError ? (
          <div className="notice red section-gap">
            <IconAlert size={15} style={{ color: 'var(--red)', flex: 'none', marginTop: 1 }} />
            <span>{searchError}</span>
          </div>
        ) : !loading ? (
          <Section gap>
            <EmptyState title="检索已停止" desc="调整关键词或参数后重新搜索。" />
          </Section>
        ) : (
          <Section gap>
            <div className="serp-loading">
              <Spin size="small" />
              <span>{stepMsg || '检索中…'}</span>
            </div>
            <div className="rcard-list">
              {[0, 1, 2].map((i) => (
                <div key={i} className="rcard skeleton">
                  <span className="sk-line" style={{ width: '28%' }} />
                  <span className="sk-line" style={{ width: '64%', height: 14 }} />
                  <span className="sk-line" style={{ width: '92%' }} />
                  <span className="sk-line" style={{ width: '76%' }} />
                </div>
              ))}
            </div>
          </Section>
        )
      ) : null}

      {/* L1~L3：执行轨迹 + 回答 / 报告 + 信源 */}
      {layout === 'answer' ? (
        <>
          <TracePanel
            open={traceOpen}
            onToggle={() => {
              traceTouched.current = true;
              setTraceOpen((prev) => !prev);
            }}
            loading={loading}
            stopped={stopped}
            error={searchError}
            stepMsg={stepMsg}
            meta={searchMeta}
            directInfo={directInfo}
            dagNodes={dagNodes}
            agentReads={agentReads}
            agentDecisions={agentDecisions}
          />

          {/* 链接 + 关键词：正文已随 page 事件直读返回，单独呈现，避免和检索综述混淆 */}
          {directPages.length > 0 && !isDirect ? (
            <Section
              gap
              title={
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                  <IconGlobe size={15} style={{ color: 'var(--green)' }} />
                  网页正文直读
                </span>
              }
              subtitle="链接正文直接抓取，无需搜索引擎转述；链接外的文字继续走多源检索"
              extra={
                <Pill tone="green">
                  {directPages.filter((p) => p.status === 'success').length} / {directPages.length} 篇
                </Pill>
              }
            >
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {directPages.map((page, idx) => (
                  <div key={`${page.url}_${idx}`} style={{ border: '1px solid var(--line-soft)', borderRadius: 12, padding: '12px 14px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, minWidth: 0 }}>
                      <a
                        href={page.final_url || page.url}
                        target="_blank"
                        rel="noreferrer"
                        className="truncate"
                        title={page.title || page.url}
                        style={{ flex: 1, minWidth: 0, fontSize: 13.5, fontWeight: 600, color: 'var(--text)', textDecoration: 'none' }}
                      >
                        {page.title || page.url}
                      </a>
                      <Pill tone={page.status === 'success' ? 'green' : 'orange'}>{page.status === 'success' ? '已读取' : '读取失败'}</Pill>
                      {page.status === 'success' ? <CopyButton text={page.content} label="复制正文" /> : null}
                    </div>
                    <PageContentView page={page} maxHeight={360} />
                  </div>
                ))}
              </div>
            </Section>
          ) : null}

          {answerMd || searchMeta ? (
            <Row gutter={[16, 16]}>
              <Col xs={24} lg={14}>
                <Section
                  title={
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                      <IconSparkles size={15} style={{ color: 'var(--accent)' }} />
                      {answerTitle}
                    </span>
                  }
                  subtitle={
                    isDirect
                      ? directInfo?.direct_reason === 'url_direct'
                        ? '链接正文直接抓取并原样返回，未经大模型改写'
                        : '检索内容原样呈现，未经大模型改写'
                      : '正文中的数字角标可点击回溯原始信源'
                  }
                  extra={answerMd ? <CopyButton text={answerMd} label="复制全文" /> : undefined}
                >
                  {answerMd ? (
                    renderMarkdownWithCitations(answerMd)
                  ) : (
                    <div className="tiny faint" style={{ fontFamily: 'var(--font-mono)' }}>
                      {loading ? '等待模型输出…' : '本次没有生成正文'}
                    </div>
                  )}

                  {suggestions.length > 0 && (
                    <div style={{ marginTop: 22, paddingTop: 16, borderTop: '1px solid var(--line-soft)' }}>
                      <div className="tiny faint" style={{ marginBottom: 10 }}>
                        延伸追问
                      </div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                        {suggestions.map((s, idx) => (
                          <button key={idx} type="button" className="chip" title={s} onClick={() => handleSearch({ query: s })}>
                            <IconArrowUpRight size={13} style={{ color: 'var(--accent)', flex: 'none' }} />
                            <span className="truncate" style={{ maxWidth: 320 }}>
                              {s}
                            </span>
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </Section>
              </Col>

              <Col xs={24} lg={10}>
                <Section
                  title={
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                      <IconGlobe size={15} style={{ color: 'var(--green)' }} />
                      融合信源
                    </span>
                  }
                  subtitle="RRF 融合排序 · 多引擎去重"
                  extra={<Pill tone="green">{answerResults.length} 条</Pill>}
                >
                  <div className="rcard-list scroll">
                    {answerResults.length === 0 ? (
                      <EmptyState title="暂无融合结果" desc="换一个模式，或放宽时间范围再试一次。" />
                    ) : (
                      answerResults.map((item, idx) => (
                        <ResultCard
                          key={`${item.url}-${idx}`}
                          item={item}
                          index={idx}
                          maxScore={answerMaxScore}
                          compact
                         
                          onReadPage={handleReadPage}
                        />
                      ))
                    )}
                  </div>
                </Section>
              </Col>
            </Row>
          ) : null}
        </>
      ) : null}

      <ApiDrawer open={apiOpen} onClose={() => setApiOpen(false)} params={apiParams} lastDirect={direct} />

      <Drawer
        width="min(920px, 100vw)"
        open={pageDrawer.open}
        onClose={() => setPageDrawer((prev) => ({ ...prev, open: false }))}
        title={
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
            <IconGlobe size={16} style={{ color: 'var(--accent)' }} />
            <span className="truncate" style={{ maxWidth: 680 }}>
              {pageDrawer.page?.title || '网页正文直读'}
            </span>
          </span>
        }
        styles={{ body: { padding: 18 } }}
      >
        {pageDrawer.loading ? (
          <div style={{ display: 'grid', placeItems: 'center', padding: '56px 0' }}>
            <Spin />
          </div>
        ) : pageDrawer.error ? (
          <div className="notice red">
            <IconAlert size={15} style={{ color: 'var(--red)', flex: 'none', marginTop: 1 }} />
            <span>{pageDrawer.error}</span>
          </div>
        ) : pageDrawer.page ? (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, minWidth: 0 }}>
              <a
                href={pageDrawer.page.final_url || pageDrawer.page.url}
                target="_blank"
                rel="noreferrer"
                className="truncate"
                style={{ flex: 1, minWidth: 0, fontSize: 12, color: 'var(--text-3)', textDecoration: 'none' }}
                title={pageDrawer.page.final_url || pageDrawer.page.url}
              >
                {pageDrawer.page.final_url || pageDrawer.page.url}
              </a>
              {pageDrawer.page.status === 'success' ? <CopyButton text={pageDrawer.page.content} label="复制正文" /> : null}
            </div>
            <PageContentView page={pageDrawer.page} maxHeight={680} />
          </>
        ) : null}
      </Drawer>
    </div>
  );
};
