import React, { useMemo, useState } from 'react';
import { Button, Col, Row, Tooltip } from 'antd';
import type { UnifiedSearchItem, UnifiedSearchResponse } from '../../api';
import { CopyButton, EmptyState, Pill, Section, SubTabs } from '../../components/ui';
import { IconCode, IconLayers, IconSearch } from '../../components/icons';
import { fmtDuration, fmtNum } from '../../utils/format';
import { DirectPage, hostOf, ResultCard } from './ResultCard';
import { DEPTHS, SearchDepth } from './levels';

/** 与 /v1/search 的 response_format=markdown 同一排版，方便直接贴给大模型。 */
export function resultsToMarkdown(query: string, items: UnifiedSearchItem[]): string {
  const maxScore = Math.max(0, ...items.map((i) => i.final_score || 0));
  const lines = [`# ${query}`, '', `## 检索结果（${items.length} 条）`, ''];
  items.forEach((item, idx) => {
    lines.push(`### ${idx + 1}. [${item.title || item.url}](${item.url})`);
    const score = maxScore > 0 ? (item.final_score / maxScore).toFixed(2) : '0.00';
    let meta = `\`${hostOf(item)}\` · 相关度 ${score} · 来源 ${(item.engines || []).join(', ') || item.source_engine}`;
    if (item.published_at) meta += ` · 发布 ${item.published_at}`;
    lines.push(meta);
    if (item.snippet) lines.push('', item.snippet.trim());
    if (item.content) lines.push('', item.content.trim().slice(0, 4000));
    lines.push('');
  });
  return lines.join('\n').trim();
}

const STATUS_TEXT: Record<string, string> = {
  success: '成功',
  error: '出错',
  timeout: '超时',
  circuit_open: '熔断中',
  skipped: '未参与',
};

/** 渠道名里括号内的补充说明在标签页上太长，只保留主名称。 */
const shortName = (name: string) => name.replace(/\s*[（(][^）)]*[)）]/g, '').trim() || name;

const StatCell: React.FC<{ label: string; value: React.ReactNode; hint?: React.ReactNode }> = ({ label, value, hint }) => (
  <div className="ws-stat">
    <div className="ws-stat-label">{label}</div>
    <div className="ws-stat-value num">{value}</div>
    {hint ? <div className="ws-stat-hint">{hint}</div> : null}
  </div>
);

export const DirectResults: React.FC<{
  resp: UnifiedSearchResponse;
  depth: SearchDepth;
  onOpenApi: () => void;
  onOpenHongguo?: (bookId: string) => void;
  onReadPage: (url: string, preloaded?: DirectPage) => void;
}> = ({ resp, depth, onOpenApi, onOpenHongguo, onReadPage }) => {
  const [view, setView] = useState<string>('fused');

  const traces = resp.engine_traces || [];
  const ran = traces.filter((t) => t.status !== 'skipped');
  const skipped = traces.filter((t) => t.status === 'skipped');
  const okCount = ran.filter((t) => t.status === 'success').length;
  const maxLatency = Math.max(1, ...ran.map((t) => t.latency_ms || 0));
  const maxScore = Math.max(0, ...resp.results.map((r) => r.final_score || 0));
  const depthMeta = DEPTHS.find((d) => d.key === depth) || DEPTHS[0];

  const nameOf = useMemo(
    () => Object.fromEntries(traces.map((t) => [t.engine_id, t.engine_name])) as Record<string, string>,
    [traces],
  );
  const engineLists = useMemo(
    () =>
      Object.entries(resp.per_engine_results || {})
        .filter(([, items]) => items.length > 0)
        .sort((a, b) => b[1].length - a[1].length),
    [resp],
  );
  // 融合时每个引擎的 positions 记录的就是它在原始列表里的序号，据此回查原始条目的去向
  const fusedRankOf = (engineId: string, rawIndex: number): number | null => {
    const idx = resp.results.findIndex((r) => r.positions?.[engineId] === rawIndex + 1);
    return idx >= 0 ? idx + 1 : null;
  };
  const contribution = useMemo(() => {
    const counts: Record<string, number> = {};
    resp.results.forEach((r) => (r.engines || []).forEach((e) => (counts[e] = (counts[e] || 0) + 1)));
    return counts;
  }, [resp]);

  const activeView = view === 'fused' || resp.per_engine_results?.[view]?.length ? view : 'fused';
  const items = activeView === 'fused' ? resp.results : resp.per_engine_results[activeView] || [];
  const markdown = useMemo(() => resultsToMarkdown(resp.query, resp.results), [resp]);

  return (
    <div className="section-gap">
      <div className="ws-stats section-gap">
        <StatCell label="命中路由" value={resp.resolved_route.toUpperCase()} hint={resp.cache_hit ? '命中缓存' : '实时检索'} />
        <StatCell label="引擎成功" value={`${okCount} / ${ran.length}`} hint={skipped.length ? `另有 ${skipped.length} 个未参与` : '全部参与'} />
        <StatCell label="召回 → 精选" value={`${fmtNum(resp.total_raw_results)} → ${fmtNum(resp.total_merged_results)}`} hint="URL 去重 + RRF 融合" />
        <StatCell label="多引擎命中" value={fmtNum(resp.cross_engine_hits)} hint="同一 URL 被多个引擎返回" />
        <StatCell label="总耗时" value={fmtDuration(resp.total_latency_ms)} hint={`深度：${depthMeta.label}`} />
      </div>

      <Row gutter={[16, 16]}>
        <Col xs={24} xl={16}>
          <Section
            title={
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                <IconSearch size={15} style={{ color: 'var(--accent)' }} />
                {activeView === 'fused' ? '融合结果' : `${shortName(nameOf[activeView] || activeView)} · 原始结果`}
              </span>
            }
            subtitle={
              activeView === 'fused'
                ? '多源去重后按 RRF 融合排序；相关度为相对本次最高分（即 API 的 score）'
                : '该引擎返回的原始顺序；绿色标签表示它在融合后的名次'
            }
            extra={
              <>
                <Pill tone="green">{items.length} 条</Pill>
                <CopyButton text={markdown} label="复制为 Markdown（与 API 的 markdown 输出一致）" />
                <Tooltip title="查看等价的 API 请求与返回结构">
                  <Button size="small" icon={<IconCode size={14} />} onClick={onOpenApi}>
                    API
                  </Button>
                </Tooltip>
              </>
            }
          >
            {engineLists.length > 1 ? (
              <div style={{ marginBottom: 14 }}>
                <SubTabs
                  value={activeView}
                  onChange={setView}
                  items={[
                    { key: 'fused', label: `融合 ${resp.results.length}` },
                    ...engineLists.map(([engineId, list]) => ({
                      key: engineId,
                      label: `${shortName(nameOf[engineId] || engineId)} ${list.length}`,
                    })),
                  ]}
                />
              </div>
            ) : null}

            {items.length === 0 ? (
              <EmptyState title="没有可展示的结果" desc="放宽时间范围、换个路由，或把深度调到「重排」再试。" />
            ) : (
              <div className="rcard-list">
                {items.map((item, idx) => (
                  <ResultCard
                    key={`${activeView}-${item.url}-${idx}`}
                    item={item}
                    index={idx}
                    maxScore={maxScore}
                    rawEngine={activeView === 'fused' ? undefined : activeView}
                    fusedRank={activeView === 'fused' ? undefined : fusedRankOf(activeView, idx)}
                    onOpenHongguo={onOpenHongguo}
                    onReadPage={onReadPage}
                  />
                ))}
              </div>
            )}
          </Section>
        </Col>

        <Col xs={24} xl={8}>
          <Section
            title={
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                <IconLayers size={15} style={{ color: 'var(--teal)' }} />
                引擎扇出
              </span>
            }
            subtitle="点击引擎查看它的原始结果"
            extra={<Pill tone={okCount === ran.length ? 'green' : 'orange'}>{okCount}/{ran.length} 成功</Pill>}
          >
            <div className="engine-rows">
              {ran
                .slice()
                .sort((a, b) => (b.result_count || 0) - (a.result_count || 0))
                .map((t) => {
                  const clickable = Boolean(resp.per_engine_results?.[t.engine_id]?.length);
                  const row = (
                    <button
                      key={t.engine_id}
                      type="button"
                      className={`engine-row ${activeView === t.engine_id ? 'active' : ''} ${clickable ? '' : 'static'}`}
                      aria-disabled={!clickable}
                      onClick={clickable ? () => setView(activeView === t.engine_id ? 'fused' : t.engine_id) : undefined}
                    >
                      <span className="engine-row-top">
                        <span className={`dot ${t.status === 'success' ? 'green' : t.status === 'timeout' ? 'orange' : 'red'}`} />
                        <span className="truncate engine-row-name">{t.engine_name}</span>
                        <span className="engine-row-meta num">
                          {t.status === 'success' ? `${fmtNum(t.result_count)} 条` : STATUS_TEXT[t.status] || t.status}
                        </span>
                      </span>
                      <span className="engine-row-bar">
                        <span
                          className={t.status === 'success' ? '' : 'warn'}
                          style={{ width: `${Math.max(3, ((t.latency_ms || 0) / maxLatency) * 100)}%` }}
                        />
                      </span>
                      <span className="engine-row-sub num">
                        <span>{fmtDuration(t.latency_ms)}</span>
                        {contribution[t.engine_id] ? <span>入选融合 {contribution[t.engine_id]} 条</span> : null}
                      </span>
                    </button>
                  );
                  return t.error_message ? (
                    <Tooltip key={t.engine_id} title={t.error_message} placement="left">
                      {row}
                    </Tooltip>
                  ) : (
                    row
                  );
                })}
            </div>
            {skipped.length ? (
              <Tooltip
                title={skipped.map((t) => `${t.engine_name}：${t.error_message || '未参与'}`).join('；')}
                placement="bottomLeft"
              >
                <div className="tiny faint" style={{ marginTop: 12, cursor: 'help' }}>
                  另有 {skipped.length} 个渠道未参与（未配置密钥或已禁用），悬停查看
                </div>
              </Tooltip>
            ) : null}
          </Section>
        </Col>
      </Row>
    </div>
  );
};
