import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Button, Input, Select, Spin, message } from 'antd';
import { EmptyState, PageHeader, Pill, Section, StatusDot } from '../components/ui';
import { IconAlert, IconClock, IconFlask, IconRefresh, IconThunderbolt } from '../components/icons';
import { renderMarkdownWithCitations } from './search/markdown';

const { TextArea } = Input;

type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'interrupted';

interface ResearchStep {
  seq: number;
  type: string;
  data: any;
  created_at: number;
}

interface ResearchJob {
  id: string;
  query: string;
  mode: string;
  route_group: string;
  status: JobStatus;
  created_at: number;
  started_at?: number | null;
  finished_at?: number | null;
  latency_ms?: number;
  result_text?: string;
  result_preview?: string;
  result_json?: Record<string, any>;
  error?: string;
  steps?: ResearchStep[];
}

const MODE_OPTIONS = [
  { value: 'fast', label: '快速 · Fast（1 轮检索 + 综合）' },
  { value: 'deep', label: '深度 · Deep（多源交叉验证）' },
  { value: 'agentic', label: '智能体 · Agentic（DAG 多轮探索）' },
];

const ROUTE_OPTIONS = [
  { value: 'auto', label: '智能路由' },
  { value: 'web', label: '全网综合' },
  { value: 'academic', label: '学术文献' },
  { value: 'code', label: '代码与技术' },
  { value: 'social', label: '社区舆情' },
  { value: 'entertainment', label: '娱乐媒体' },
];

const STATUS_META: Record<JobStatus, { label: string; tone: 'green' | 'orange' | 'red' | 'accent' | 'default'; dot: 'green' | 'orange' | 'red' | 'accent' | 'default' }> = {
  queued: { label: '排队中', tone: 'default', dot: 'default' },
  running: { label: '运行中', tone: 'accent', dot: 'accent' },
  succeeded: { label: '已完成', tone: 'green', dot: 'green' },
  failed: { label: '失败', tone: 'red', dot: 'red' },
  cancelled: { label: '已取消', tone: 'orange', dot: 'orange' },
  interrupted: { label: '已中断', tone: 'orange', dot: 'orange' },
};

function fmtTime(value?: number | null): string {
  if (!value) return '-';
  return new Date(value * 1000).toLocaleString('zh-CN', { hour12: false });
}

function fmtDuration(ms?: number): string {
  if (!ms) return '-';
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
}

async function readJson(resp: Response) {
  const body = await resp.json().catch(() => null);
  if (!resp.ok) throw new Error(body?.detail || `HTTP ${resp.status}`);
  return body;
}

export const ResearchJobs: React.FC = () => {
  const [jobs, setJobs] = useState<ResearchJob[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ResearchJob | null>(null);
  const [liveText, setLiveText] = useState('');
  const [liveSteps, setLiveSteps] = useState<ResearchStep[]>([]);
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState('deep');
  const [routeGroup, setRouteGroup] = useState('auto');
  const [submitting, setSubmitting] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);

  const loadJobs = useCallback(async () => {
    try {
      const data = await readJson(await fetch('/api/v1/research/jobs?limit=50'));
      setJobs(data.jobs || []);
      setCounts(data.counts || {});
      setSelectedId((prev) => prev || (data.jobs?.[0]?.id ?? null));
    } catch {
      /* 后端未就绪时静默 */
    }
  }, []);

  const loadDetail = useCallback(async (jobId: string) => {
    setLoadingDetail(true);
    try {
      const data = await readJson(await fetch(`/api/v1/research/jobs/${jobId}`));
      setDetail(data);
      setLiveSteps(data.steps || []);
      if (data.status === 'succeeded') setLiveText('');
    } catch (err: any) {
      message.error(err.message || '读取任务失败');
    } finally {
      setLoadingDetail(false);
    }
  }, []);

  useEffect(() => {
    loadJobs();
    const timer = window.setInterval(loadJobs, 4000);
    return () => window.clearInterval(timer);
  }, [loadJobs]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    setLiveText('');
    setLiveSteps([]);
    loadDetail(selectedId);
  }, [selectedId, loadDetail]);

  // 运行中的任务通过 SSE 续看；结束后重新拉取完整结果。
  useEffect(() => {
    if (!selectedId || !detail) return;
    if (detail.status !== 'running' && detail.status !== 'queued') return;
    const es = new EventSource(`/api/v1/research/jobs/${selectedId}/stream`);
    es.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'token' && typeof msg.data === 'string') {
          setLiveText((prev) => prev + msg.data);
        } else if (msg.type === 'end') {
          es.close();
          loadDetail(selectedId);
        } else if (msg.type && msg.type !== 'sources') {
          const seq = Number(msg.seq || 0);
          setLiveSteps((prev) => (seq && prev.some((step) => step.seq === seq)
            ? prev
            : [...prev, { seq: seq || prev.length + 1, type: msg.type, data: msg.data, created_at: Date.now() / 1000 }]));
        }
      } catch {
        /* 忽略非 JSON 心跳 */
      }
    };
    es.onerror = () => es.close();
    return () => es.close();
  }, [selectedId, detail?.status, loadDetail]);

  const submit = async () => {
    const text = query.trim();
    if (!text) return;
    setSubmitting(true);
    try {
      const job = await readJson(
        await fetch('/api/v1/research/jobs', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: text, mode, route_group: routeGroup, top_k: 16 }),
        }),
      );
      setQuery('');
      setSelectedId(job.id);
      message.success('已提交，后台会持续运行，关闭页面不影响');
      await loadJobs();
    } catch (err: any) {
      message.error(err.message || '提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  const cancel = async (jobId: string) => {
    try {
      await readJson(await fetch(`/api/v1/research/jobs/${jobId}/cancel`, { method: 'POST' }));
      message.success('已取消');
      await loadDetail(jobId);
      await loadJobs();
    } catch (err: any) {
      message.error(err.message || '取消失败');
    }
  };

  const total = useMemo(
    () => Object.values(counts).reduce((sum, value) => sum + value, 0),
    [counts],
  );
  const activeJobs = jobs.filter((job) => job.status === 'running' || job.status === 'queued');
  const text = liveText || detail?.result_text || '';
  const running = detail?.status === 'running' || detail?.status === 'queued';

  return (
    <div>
      <PageHeader
        icon={<IconFlask size={21} />}
        title="深度研究任务"
        tags={<Pill tone="purple">后台并行</Pill>}
        subtitle="后台并行研究，步骤与结果可回放。"
        extra={
          <Button icon={<IconRefresh size={15} />} onClick={() => { loadJobs(); if (selectedId) loadDetail(selectedId); }}>
            刷新
          </Button>
        }
      />

      <Section className="section-gap" title="新建研究" subtitle="复杂课题建议选 Deep 或 Agentic；单点事实用 Fast 更快">
        <TextArea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="例如：对比 2026 年主流开源向量数据库的架构、成本与适用场景，并给出选型建议"
          autoSize={{ minRows: 2, maxRows: 5 }}
          allowClear
          style={{ fontSize: 14, lineHeight: 1.6, borderRadius: 12, padding: '11px 14px' }}
        />
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginTop: 14 }}>
          <Select value={mode} onChange={setMode} options={MODE_OPTIONS} style={{ width: 280 }} />
          <Select value={routeGroup} onChange={setRouteGroup} options={ROUTE_OPTIONS} style={{ width: 160 }} />
          <Button
            type="primary"
            shape="round"
            size="large"
            icon={<IconThunderbolt size={16} />}
            loading={submitting}
            disabled={!query.trim()}
            onClick={submit}
            style={{ height: 42, paddingInline: 22, fontWeight: 600 }}
          >
            提交后台研究
          </Button>
          <span className="tiny faint">已运行 {counts.running || 0} · 排队 {counts.queued || 0} · 累计 {total}</span>
        </div>
      </Section>

      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', marginTop: 16, flexWrap: 'wrap' }}>
        <div style={{ width: 330, flex: '0 0 330px', minWidth: 280 }}>
          <Section title="任务列表" subtitle={`${jobs.length} 个 · 点击切换`} flush>
            {jobs.length === 0 ? (
              <EmptyState icon={<IconClock size={20} />} title="还没有研究任务" desc="提交第一个课题后，这里会出现可回放的任务。" />
            ) : (
              <div style={{ maxHeight: 620, overflowY: 'auto' }}>
                {jobs.map((job) => {
                  const meta = STATUS_META[job.status] || STATUS_META.queued;
                  const selected = job.id === selectedId;
                  return (
                    <button
                      key={job.id}
                      onClick={() => setSelectedId(job.id)}
                      style={{
                        display: 'block',
                        width: '100%',
                        textAlign: 'left',
                        padding: '12px 15px',
                        border: 'none',
                        borderBottom: '1px solid var(--line-soft)',
                        background: selected ? 'var(--surface-2)' : 'transparent',
                        cursor: 'pointer',
                        color: 'inherit',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <StatusDot tone={meta.dot} />
                        <span className="small strong truncate" style={{ flex: 1, minWidth: 0 }}>{job.query}</span>
                      </div>
                      <div className="tiny faint" style={{ marginTop: 6, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                        <span>{meta.label}</span>
                        <span>·</span>
                        <span>{job.mode}</span>
                        <span>·</span>
                        <span>{fmtDuration(job.latency_ms)}</span>
                        <span>·</span>
                        <span>{fmtTime(job.created_at)}</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </Section>
        </div>

        <div style={{ flex: 1, minWidth: 320 }}>
          {!detail ? (
            <Section>
              <EmptyState icon={<IconFlask size={20} />} title="选择一个任务" desc="左侧列表可查看运行状态、步骤与最终报告。" />
            </Section>
          ) : (
            <>
              <Section
                title={detail.query}
                subtitle={`${detail.mode} · ${detail.route_group} · ${fmtTime(detail.created_at)}`}
                extra={
                  running ? (
                    <Button danger size="small" onClick={() => cancel(detail.id)}>取消任务</Button>
                  ) : (
                    <Pill tone={STATUS_META[detail.status]?.tone || 'default'}>{STATUS_META[detail.status]?.label || detail.status}</Pill>
                  )
                }
              >
                <div className="small" style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                  <span>状态 <StatusDot tone={STATUS_META[detail.status]?.dot || 'default'} label={STATUS_META[detail.status]?.label || detail.status} /></span>
                  <span>耗时 <b>{fmtDuration(detail.latency_ms)}</b></span>
                  <span>步骤 <b>{detail.steps?.length || liveSteps.length}</b></span>
                  <span>产出 <b>{text.length}</b> 字</span>
                </div>
                {detail.error ? (
                  <div className="tiny" style={{ marginTop: 10, color: 'var(--red)', display: 'flex', gap: 6, alignItems: 'flex-start' }}>
                    <IconAlert size={14} />
                    <span>{detail.error}</span>
                  </div>
                ) : null}
                {activeJobs.length > 1 ? (
                  <div className="tiny faint" style={{ marginTop: 10 }}>
                    另有 {activeJobs.length - (running ? 1 : 0)} 个任务在后台运行，关闭页面不会中断。
                  </div>
                ) : null}
              </Section>

              {running ? (
                <Section className="section-gap" title="实时步骤" subtitle="SSE 推送；断线重连会从 SQLite 回放">
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {liveSteps.length === 0 ? <Spin size="small" /> : null}
                    {liveSteps.slice(-12).map((step, index) => (
                      <div key={`${step.seq}-${index}`} className="tiny" style={{ display: 'flex', gap: 8 }}>
                        <Pill outline>{step.type}</Pill>
                        <span style={{ flex: 1, minWidth: 0 }}>
                          {step.type === 'step'
                            ? String(step.data?.message || step.data?.stage || '')
                            : step.type === 'sources'
                              ? `收到来源 ${step.data?.results?.length ?? step.data?.total_merged_results ?? 0} 条`
                              : step.type === 'dag'
                                ? `DAG 节点 ${Array.isArray(step.data) ? step.data.length : '更新'}`
                                : step.type === 'page'
                                  ? `读取网页 ${step.data?.pages?.length || 0} 个`
                                  : ''}
                        </span>
                      </div>
                    ))}
                  </div>
                </Section>
              ) : null}

              <Section className="section-gap" title="研究结果" subtitle={running ? '生成中，已完成部分会实时追加' : 'Markdown 渲染，引用可点击'}>
                {loadingDetail && !text ? (
                  <Spin />
                ) : text ? (
                  <div style={{ fontSize: 14, lineHeight: 1.75 }}>{renderMarkdownWithCitations(text)}</div>
                ) : (
                  <EmptyState
                    icon={<IconClock size={20} />}
                    title={running ? '正在生成结果' : '暂无结果'}
                    desc={running ? '任务在后台运行，可关闭页面稍后回来查看。' : detail.error || '该任务没有产出文本。'}
                  />
                )}
              </Section>
            </>
          )}
        </div>
      </div>
    </div>
  );
};
