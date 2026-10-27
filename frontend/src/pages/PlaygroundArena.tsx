import React, { useEffect, useState } from 'react';
import { Button, Checkbox, Input, Switch, message } from 'antd';
import type { ProviderItem, UnifiedSearchItem, UnifiedSearchResponse } from '../api';
import { CopyButton, EmptyState, PageHeader, Pill, Section } from '../components/ui';
import {
  IconAlert,
  IconClock,
  IconExternal,
  IconFlask,
  IconLayers,
  IconRefresh,
  IconRoute,
  IconSearch,
  IconSparkles,
  IconThunderbolt,
} from '../components/icons';
import { fmtNum } from '../utils/format';

/* 引擎密钥状态 —— 纯展示映射 */
const engineBadge = (p: ProviderItem) => {
  if (p.health_status === 'missing_key') return <Pill tone="orange">缺 Key</Pill>;
  if (p.health_status === 'circuit_open') return <Pill tone="red">熔断</Pill>;
  if (p.health_status === 'disabled') return <Pill>停用</Pill>;
  return p.requires_key ? <Pill tone="green">已配 Key</Pill> : <Pill tone="teal">免 Key</Pill>;
};

const traceTone = (status: string): 'green' | 'orange' | 'red' =>
  status === 'success' ? 'green' : status === 'timeout' ? 'orange' : 'red';

const Toggle: React.FC<{
  label: string;
  hint: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}> = ({ label, hint, checked, onChange }) => (
  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
    <Switch checked={checked} onChange={onChange} size="small" />
    <div style={{ lineHeight: 1.35 }}>
      <div style={{ fontSize: 12.5, fontWeight: 500 }}>{label}</div>
      <div className="tiny faint">{hint}</div>
    </div>
  </div>
);

export const PlaygroundArena: React.FC = () => {
  const [providers, setProviders] = useState<ProviderItem[]>([]);
  const [selectedEngines, setSelectedEngines] = useState<string[]>([
    'bing_web',
    'duckduckgo',
    'wikipedia',
    'github',
    'hackernews',
  ]);
  const [query, setQuery] = useState('open source AI metasearch engine');
  const [enableDedup, setEnableDedup] = useState(true);
  const [enableRrf, setEnableRrf] = useState(true);
  const [enableRerank, setEnableRerank] = useState(true);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<UnifiedSearchResponse | null>(null);

  useEffect(() => {
    fetch('/api/admin/providers?provider_type=search')
      .then((r) => r.json())
      .then((data) => setProviders(data));
  }, []);

  const runComparison = async () => {
    if (!query.trim()) {
      message.warning('请输入测试 Query');
      return;
    }
    if (selectedEngines.length === 0) {
      message.warning('请至少勾选 1 个要对比的搜索引擎');
      return;
    }
    setLoading(true);
    try {
      const resp = await fetch('/api/v1/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: query.trim(),
          engines: selectedEngines,
          top_k: 20,
          enable_dedup: enableDedup,
          enable_rrf: enableRrf,
          enable_rerank: enableRerank,
        }),
      });
      const data = await resp.json();
      setResult(data);
    } catch (e: any) {
      message.error(`联调执行异常: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <PageHeader
        icon={<IconFlask size={21} />}
        title="多源演练场"
        subtitle="同一条 Query 并排下发到多个引擎，逐列查看各自的原始召回，再与网关的 RRF 融合、重排结果对照。"
        extra={
          <Button
            icon={<IconRefresh size={15} />}
            onClick={runComparison}
            loading={loading}
          >
            {result ? '重新运行' : '运行对比'}
          </Button>
        }
      />

      {/* ---------------- 查询卡 ---------------- */}
      <div className="card section-gap" style={{ padding: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <Input
            size="large"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onPressEnter={runComparison}
            placeholder="输入要并排对比的检索词"
            prefix={<IconSearch size={16} style={{ color: 'var(--text-3)', marginRight: 2 }} />}
            style={{ flex: 1, minWidth: 200 }}
          />
          <Button
            type="primary"
            size="large"
            icon={<IconThunderbolt size={16} />}
            loading={loading}
            onClick={runComparison}
          >
            并发对比
          </Button>
        </div>

        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            flexWrap: 'wrap',
            gap: 8,
            rowGap: 4,
            margin: '18px 0 10px',
          }}
        >
          <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text-2)', letterSpacing: '-0.005em' }}>
            参与对比的引擎
          </span>
          <span className="tiny faint num">
            已选 {selectedEngines.length}
            {providers.length > 0 ? ` / ${providers.length}` : ''}
          </span>
          <span className="tiny faint" style={{ marginLeft: 'auto' }}>
            并发下发 · 单个源失败不影响其余结果
          </span>
        </div>

        <Checkbox.Group
          value={selectedEngines}
          onChange={(vals) => setSelectedEngines(vals as string[])}
          style={{ display: 'block', width: '100%' }}
        >
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(210px, 1fr))',
              gap: 8,
            }}
          >
            {providers.map((p) => {
              const checked = selectedEngines.includes(p.id);
              return (
                <div
                  key={p.id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    minWidth: 0,
                    padding: '6px 10px',
                    borderRadius: 9,
                    border: '1px solid transparent',
                    background: checked ? 'var(--accent-soft)' : 'var(--surface-2)',
                    transition: 'background 160ms var(--ease)',
                  }}
                >
                  <Checkbox value={p.id} style={{ marginRight: 0, flex: 1, minWidth: 0 }}>
                    <span
                      className="truncate"
                      title={p.name}
                      style={{ display: 'block', fontSize: 12.5, fontWeight: 500, lineHeight: 1.5 }}
                    >
                      {p.name}
                    </span>
                  </Checkbox>
                  <span style={{ flex: 'none' }}>{engineBadge(p)}</span>
                </div>
              );
            })}
            {providers.length === 0 ? (
              <span className="tiny faint">正在加载可用的检索源…</span>
            ) : null}
          </div>
        </Checkbox.Group>

        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: '12px 28px',
            marginTop: 18,
            paddingTop: 15,
            borderTop: '1px solid var(--line-soft)',
          }}
        >
          <Toggle
            label="URL 归一化去重"
            hint="同一链接只保留一条"
            checked={enableDedup}
            onChange={setEnableDedup}
          />
          <Toggle
            label="跨源重合 RRF 提权"
            hint="多源命中优先"
            checked={enableRrf}
            onChange={setEnableRrf}
          />
          <Toggle
            label="语义 / 词法重排"
            hint="Rerank 二次排序"
            checked={enableRerank}
            onChange={setEnableRerank}
          />
        </div>
      </div>

      {!result ? (
        <Section>
          <EmptyState
            icon={<IconFlask size={22} />}
            title="还没有运行对比"
            desc="输入检索词、勾选要对比的引擎，点击「并发对比」即可看到各源原始返回与 RRF 融合排序。"
          />
        </Section>
      ) : (
        <>
          {/* ---------------- 本次运行概要 ---------------- */}
          <div
            className="card section-gap"
            style={{
              padding: '13px 20px',
              display: 'flex',
              alignItems: 'center',
              gap: 14,
              rowGap: 10,
              flexWrap: 'wrap',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 7, minWidth: 0 }}>
              <span className="tiny faint" style={{ letterSpacing: '0.06em' }}>
                TRACE
              </span>
              <code className="code-inline" style={{ minWidth: 0 }}>{result.trace_id}</code>
              <span style={{ flex: 'none', display: 'inline-flex' }}>
                <CopyButton text={result.trace_id} label="复制 Trace ID" />
              </span>
            </div>
            <span style={{ width: 1, height: 16, background: 'var(--line-soft)' }} />
            <span className="tiny muted" style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
              <IconClock size={13} style={{ color: 'var(--text-3)' }} />
              总并发耗时
              <strong className="num" style={{ color: 'var(--text)' }}>
                {fmtNum(result.total_latency_ms)}
              </strong>
              ms
            </span>
            <span className="tiny muted" style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
              <IconLayers size={13} style={{ color: 'var(--text-3)' }} />
              原始
              <strong className="num" style={{ color: 'var(--text)' }}>
                {fmtNum(result.total_raw_results)}
              </strong>
              → 融合
              <strong className="num" style={{ color: 'var(--text)' }}>
                {fmtNum(result.total_merged_results)}
              </strong>
              条
            </span>
            {result.cross_engine_hits > 0 ? (
              <Pill tone="purple">多源重合 {fmtNum(result.cross_engine_hits)} 条</Pill>
            ) : null}
            {result.cache_hit ? <Pill tone="teal">缓存命中</Pill> : null}
            {result.resolved_route ? (
              <Pill tone="accent" style={{ marginLeft: 'auto' }}>
                <IconRoute size={11} />
                {result.resolved_route}
              </Pill>
            ) : null}
          </div>

          {/* ---------------- 融合结果 ---------------- */}
          <Section
            gap
            title={
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
                <IconSparkles size={15} style={{ color: 'var(--accent)' }} />
                融合结果
              </span>
            }
            subtitle="RRF 跨源提权 + 重排后的最终排序"
            extra={<Pill tone="accent">{fmtNum(result.results.length)} 条</Pill>}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                rowGap: 6,
                flexWrap: 'wrap',
                padding: '11px 14px',
                borderRadius: 12,
                background: 'var(--accent-soft)',
                marginBottom: 14,
              }}
            >
              <IconLayers size={15} style={{ color: 'var(--accent)', flex: 'none' }} />
              <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--accent-text)' }}>
                RRF 融合排序
              </span>
              <span className="tiny" style={{ color: 'var(--accent-text)', opacity: 0.85 }}>
                同一 URL 被多个源命中时按倒数排名累加提权，分数越高越靠前
              </span>
              <span style={{ marginLeft: 'auto', display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                <Pill outline>
                  原始 {fmtNum(result.total_raw_results)} → 融合 {fmtNum(result.total_merged_results)}
                </Pill>
                {result.cross_engine_hits > 0 ? (
                  <Pill tone="purple">重合 {fmtNum(result.cross_engine_hits)}</Pill>
                ) : null}
              </span>
            </div>

            {result.results.length === 0 ? (
              <EmptyState title="没有融合结果" desc="换一个 Query 或增选引擎后再试一次。" />
            ) : (
              <>
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 12,
                    padding: '0 4px 7px',
                    borderBottom: '1px solid var(--line-soft)',
                  }}
                >
                  <span className="tiny faint" style={{ width: 22, flex: 'none' }}>
                    #
                  </span>
                  <span className="tiny faint" style={{ flex: 1 }}>
                    标题 · 摘要 · 命中引擎
                  </span>
                  <span className="tiny faint nowrap" style={{ flex: 'none', width: 92, textAlign: 'right' }}>
                    最终分 / RRF
                  </span>
                </div>
                <div style={{ maxHeight: 620, overflowY: 'auto' }}>
                  {result.results.map((item: UnifiedSearchItem, idx: number) => (
                    <div
                      key={idx}
                      className="list-row"
                      style={{ alignItems: 'flex-start', gap: 12, padding: '12px 4px' }}
                    >
                      <span
                        className="tiny faint num"
                        style={{ width: 22, flex: 'none', paddingTop: 2 }}
                      >
                        {idx + 1}
                      </span>
                      <div style={{ minWidth: 0, flex: 1 }}>
                        <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, minWidth: 0 }}>
                          <a
                            href={item.url}
                            target="_blank"
                            rel="noreferrer"
                            title={item.title}
                            className="truncate"
                            style={{
                              fontSize: 13.5,
                              fontWeight: 600,
                              color: 'var(--text)',
                              textDecoration: 'none',
                              letterSpacing: '-0.01em',
                            }}
                          >
                            {item.title}
                          </a>
                          <IconExternal size={12} style={{ color: 'var(--text-3)', flex: 'none' }} />
                        </div>
                        <div className="tiny faint truncate" style={{ marginTop: 1 }}>
                          {item.domain || item.url}
                        </div>
                        {item.snippet ? (
                          <div
                            className="tiny muted"
                            style={{
                              marginTop: 4,
                              lineHeight: 1.5,
                              display: '-webkit-box',
                              WebkitLineClamp: 2,
                              WebkitBoxOrient: 'vertical',
                              overflow: 'hidden',
                            }}
                          >
                            {item.snippet}
                          </div>
                        ) : null}
                        <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginTop: 6 }}>
                          {item.engines.map((e) => (
                            <Pill key={e} tone="teal">
                              #{e} · {item.positions[e]}
                            </Pill>
                          ))}
                          {item.engines.length > 1 ? <Pill tone="purple">多源共同命中</Pill> : null}
                        </div>
                      </div>
                      <div style={{ flex: 'none', textAlign: 'right', minWidth: 92 }}>
                        <div
                          className="small num"
                          style={{ fontWeight: 600, color: 'var(--accent)', lineHeight: 1.4 }}
                        >
                          {item.final_score.toFixed(4)}
                        </div>
                        <div className="tiny faint num">
                          RRF {Number(item.rrf_score || 0).toFixed(4)}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </Section>

          {/* ---------------- 各引擎原始返回 ---------------- */}
          <Section
            gap
            flush
            title="各引擎原始返回"
            subtitle={`${result.engine_traces.length} 列并排 · 每列是该源独立召回，未经融合 · 可横向滚动`}
            extra={
              <Pill tone="green">
                {result.engine_traces.filter((t) => t.status === 'success').length} 个源成功
              </Pill>
            }
          >
            {result.engine_traces.length === 0 ? (
              <EmptyState title="没有引擎执行记录" desc="本次请求没有扇出到任何检索源。" />
            ) : (
              <div style={{ display: 'flex', alignItems: 'stretch', overflowX: 'auto' }}>
                {result.engine_traces.map((tr, colIdx) => {
                  const rawItems = result.per_engine_results[tr.engine_id] || [];
                  return (
                    <div
                      key={tr.engine_id}
                      style={{
                        flex: '1 1 240px',
                        minWidth: 240,
                        padding: colIdx === 0 ? '0 16px 4px 20px' : '0 16px 4px',
                        borderLeft: colIdx === 0 ? 'none' : '1px solid var(--line-soft)',
                      }}
                    >
                      <div
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 8,
                          padding: '15px 0 10px',
                          borderBottom: '1px solid var(--line-soft)',
                        }}
                      >
                        <span className={`dot ${traceTone(tr.status)}`} />
                        <span className="truncate" style={{ fontSize: 13, fontWeight: 600, flex: 1 }}>
                          {tr.engine_name}
                        </span>
                        <span className="tiny faint num" style={{ flex: 'none' }}>
                          {fmtNum(tr.latency_ms)} ms
                        </span>
                        <Pill tone={traceTone(tr.status)}>{tr.result_count} 条</Pill>
                      </div>
                      <div
                        className="tiny faint truncate"
                        style={{ paddingTop: 7, fontFamily: 'var(--font-mono)' }}
                      >
                        {tr.engine_id}
                        {tr.used_proxy ? ' · 代理' : ''}
                      </div>

                      <div style={{ maxHeight: 460, overflowY: 'auto', paddingBottom: 6 }}>
                        {tr.error_message ? (
                          <div
                            style={{
                              display: 'flex',
                              alignItems: 'flex-start',
                              gap: 6,
                              padding: '10px 0',
                              color: 'var(--red)',
                            }}
                          >
                            <IconAlert size={13} style={{ marginTop: 2, flex: 'none' }} />
                            <span className="tiny" style={{ lineHeight: 1.5 }}>
                              {tr.error_message}
                            </span>
                          </div>
                        ) : null}

                        {rawItems.length === 0 ? (
                          tr.error_message ? null : (
                            <div className="empty" style={{ padding: '28px 4px' }}>
                              <div className="empty-desc">
                                {tr.status === 'success' ? '该引擎返回 0 条结果' : '没有返回结果'}
                              </div>
                            </div>
                          )
                        ) : (
                          rawItems.map((it, idx) => (
                            <div
                              key={idx}
                              style={{
                                padding: '10px 0',
                                borderBottom:
                                  idx === rawItems.length - 1
                                    ? 'none'
                                    : '1px solid var(--line-soft)',
                              }}
                            >
                              <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
                                <span
                                  className="tiny faint num"
                                  style={{ flex: 'none', width: 16 }}
                                >
                                  {idx + 1}
                                </span>
                                <a
                                  href={it.url}
                                  target="_blank"
                                  rel="noreferrer"
                                  title={it.title}
                                  className="truncate"
                                  style={{
                                    flex: 1,
                                    minWidth: 0,
                                    fontSize: 12.5,
                                    fontWeight: 500,
                                    color: 'var(--text)',
                                    textDecoration: 'none',
                                  }}
                                >
                                  {it.title}
                                </a>
                                <span className="tiny faint num nowrap" style={{ flex: 'none' }}>
                                  {fmtNum(it.raw_score, 3)}
                                </span>
                              </div>
                              <div
                                className="tiny faint truncate"
                                style={{ marginTop: 2, paddingLeft: 22 }}
                              >
                                {it.url}
                              </div>
                            </div>
                          ))
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </Section>
        </>
      )}
    </div>
  );
};
