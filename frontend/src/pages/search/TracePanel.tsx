import React from 'react';
import { Button, Tooltip } from 'antd';
import type { EngineExecutionTrace, UnifiedSearchResponse } from '../../api';
import { Pill, Section, StatusDot } from '../../components/ui';
import { IconAlert, IconChevronDown, IconChevronRight, IconTerminal } from '../../components/icons';
import { fmtDuration, fmtNum } from '../../utils/format';

export interface DirectInfo {
  data_direct: boolean;
  processed_by_llm?: boolean;
  direct_reason?: string;
  boards?: string[];
  source_breakdown?: Record<string, number>;
  fetched_at?: string;
}

export interface DagNode {
  id: string;
  title: string;
  query: string;
  route: string;
  round?: number;
  status: 'running' | 'completed';
  result_count?: number;
  latency_ms?: number;
}

export interface AgentReadEvent {
  round: number;
  title: string;
  url: string;
  domain: string;
  engines: string[];
  chars: number;
  status?: 'fulltext' | 'summary_only' | 'failed';
  truncated?: boolean;
  published_at?: string;
}

export interface AgentDecisionEvent {
  round: number;
  need_more: boolean;
  thought: string;
}

/* --------------------------------------------------------------------------
   执行轨迹：运行中展开看实时进度；回答开始输出后自动收起成一行摘要。
   -------------------------------------------------------------------------- */
export const TracePanel: React.FC<{
  open: boolean;
  onToggle: () => void;
  loading: boolean;
  stopped?: boolean;
  error: string;
  stepMsg: string;
  meta: UnifiedSearchResponse | null;
  directInfo: DirectInfo | null;
  dagNodes: DagNode[];
  agentReads: AgentReadEvent[];
  agentDecisions: AgentDecisionEvent[];
}> = ({ open, onToggle, loading, stopped, error, stepMsg, meta, directInfo, dagNodes, agentReads, agentDecisions }) => {
  const rounds = Math.max(0, ...dagNodes.map((n) => n.round || 0));
  const readOk = agentReads.filter((r) => r.status === 'fulltext').length;
  const tone = error ? 'red' : loading ? 'accent' : stopped ? 'orange' : 'green';

  return (
    <Section
      gap
      className="trace-card"
      title={
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          <IconTerminal size={15} style={{ color: 'var(--text-2)' }} />
          执行轨迹
        </span>
      }
      subtitle={
        <span className="trace-summary">
          {meta ? <span>路由 {meta.resolved_route.toUpperCase()}</span> : null}
          {rounds ? <span>{rounds} 轮 · {dagNodes.length} 个检索节点</span> : dagNodes.length ? <span>{dagNodes.length} 个子问题</span> : null}
          {meta ? <span>召回 {fmtNum(meta.total_raw_results)} → 精选 {fmtNum(meta.total_merged_results)}</span> : null}
          {agentReads.length ? <span>精读 {readOk}/{agentReads.length} 篇</span> : null}
          {meta ? <span>检索耗时 {fmtDuration(meta.total_latency_ms)}</span> : null}
          {!meta && !dagNodes.length ? <span>意图路由 · 多源扇出 · 融合</span> : null}
        </span>
      }
      extra={
        <>
          <StatusDot tone={tone} label={error ? '执行异常' : loading ? '运行中' : stopped ? '已停止' : '已完成'} />
          <Button
            size="small"
            type="text"
            onClick={onToggle}
            icon={open ? <IconChevronDown size={14} /> : <IconChevronRight size={14} />}
            style={{ color: 'var(--text-2)' }}
          >
            {open ? '收起' : '展开'}
          </Button>
        </>
      }
    >
      <div className="trace-step">
        <span className="trace-prompt">$</span>
        <span className={loading ? 'trace-live' : ''}>{stepMsg || '等待检索指令…'}</span>
      </div>

      {error ? (
        <div className="notice red" style={{ marginTop: 12 }}>
          <IconAlert size={15} style={{ color: 'var(--red)', flex: 'none', marginTop: 1 }} />
          <span>{error}</span>
        </div>
      ) : null}

      {open ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14, marginTop: 14 }}>
          {meta || directInfo?.data_direct ? (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
              {meta && meta.cross_engine_hits > 0 ? (
                <Tooltip title="同一 URL 被多个引擎返回，不代表独立来源证实">
                  <span>
                    <Pill tone="orange">多引擎 URL 重合 {fmtNum(meta.cross_engine_hits)}</Pill>
                  </span>
                </Tooltip>
              ) : null}
              {meta?.cache_hit ? <Pill tone="teal">命中缓存</Pill> : null}
              {directInfo?.data_direct && <Pill tone="green">数据直出 · 未经大模型处理</Pill>}
              {directInfo?.data_direct && directInfo.direct_reason === 'trending_data' && (
                <Pill tone="orange">榜单渠道 {directInfo.boards?.length || 0} 个</Pill>
              )}
              {directInfo?.data_direct && directInfo.fetched_at && <span className="tiny faint">抓取时间 {directInfo.fetched_at}</span>}
            </div>
          ) : null}

          {dagNodes.length > 0 && (
            <div>
              <div className="trace-label">{rounds ? '多轮检索节点' : '子问题并发检索'}</div>
              <div className="dag-grid">
                {dagNodes.map((n, idx) => (
                  <div key={`${n.id}_${idx}`} className={`dag-node ${n.status}`}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginBottom: 7 }}>
                      <Pill tone="purple">{n.round ? `第 ${n.round} 轮` : `子问题 ${idx + 1}`}</Pill>
                      <Pill outline>{n.route.toUpperCase()}</Pill>
                      <span style={{ marginLeft: 'auto' }}>
                        <Pill tone={n.status === 'completed' ? 'green' : 'accent'}>
                          {n.status === 'completed' ? `${fmtNum(n.result_count || 0)} 条 · ${fmtDuration(n.latency_ms)}` : '检索中'}
                        </Pill>
                      </span>
                    </div>
                    <div className="truncate" title={n.title} style={{ fontSize: 13, fontWeight: 600, letterSpacing: '-0.01em' }}>
                      {n.title}
                    </div>
                    <div className="tiny faint truncate" title={n.query} style={{ marginTop: 2 }}>
                      {n.query}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {(agentReads.length > 0 || agentDecisions.length > 0) && (
            <div className="trace-box">
              {agentReads.length > 0 && (
                <div>
                  <div className="trace-label">
                    正文读取成功 {readOk} / 尝试 {agentReads.length} 篇
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                    {agentReads.map((ar, i) => (
                      <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, minWidth: 0 }}>
                        <Pill tone={ar.status === 'fulltext' ? 'teal' : 'orange'}>R{ar.round}</Pill>
                        <span className="faint nowrap truncate" style={{ maxWidth: 132 }}>
                          {ar.domain}
                        </span>
                        <a href={ar.url} target="_blank" rel="noreferrer" className="truncate" style={{ flex: 1, color: 'var(--text-2)', textDecoration: 'none' }}>
                          {ar.title}
                        </a>
                        <span className="tiny faint num nowrap">
                          {ar.status === 'fulltext'
                            ? `${fmtNum(ar.chars)} 字${ar.truncated ? ' · 截断' : ''}`
                            : ar.status === 'summary_only'
                            ? '仅摘要'
                            : '读取失败'}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {agentDecisions.map((ad, i) => (
                <div
                  key={i}
                  style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: 8,
                    fontSize: 12,
                    color: 'var(--text-2)',
                    borderTop: i === 0 && agentReads.length > 0 ? '1px solid var(--line-soft)' : undefined,
                    paddingTop: i === 0 && agentReads.length > 0 ? 8 : 0,
                  }}
                >
                  <Pill tone={ad.need_more ? 'orange' : 'green'}>
                    第 {ad.round} 轮 · {ad.need_more ? '继续深挖' : '停止深挖'}
                  </Pill>
                  <span style={{ flex: 1 }}>{ad.thought}</span>
                </div>
              ))}
            </div>
          )}

          {meta && meta.engine_traces.length > 0 && (
            <div>
              <div className="trace-label">引擎扇出明细</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {meta.engine_traces.map((t: EngineExecutionTrace, i: number) => (
                  <Tooltip
                    key={i}
                    title={t.error_message ? `${t.engine_name}: ${t.error_message}` : `密钥: ${t.used_key_masked} | 代理: ${t.used_proxy ? '开启' : '直连'}`}
                  >
                    <span className="engine-chip">
                      <span
                        className={`dot ${t.status === 'success' ? 'green' : t.status === 'skipped' ? '' : 'red'}`}
                        style={{ width: 6, height: 6, boxShadow: 'none' }}
                      />
                      <span style={{ color: 'var(--text-2)', fontWeight: 500 }}>{t.engine_name}</span>
                      <span className="faint num">
                        {t.status === 'success' ? `${fmtNum(t.result_count)} 条 · ${fmtNum(t.latency_ms)} ms` : t.status}
                      </span>
                    </span>
                  </Tooltip>
                ))}
              </div>
            </div>
          )}
        </div>
      ) : null}
    </Section>
  );
};
