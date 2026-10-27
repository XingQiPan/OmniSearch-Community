import React, { useEffect, useState } from 'react';
import { Button, Table, message } from 'antd';
import type { ProviderItem } from '../api';
import { AreaChart, PageHeader, Pill, Section, Stat, StatusDot } from '../components/ui';
import {
  IconClock,
  IconGlobe,
  IconGrid,
  IconLayers,
  IconRefresh,
  IconServer,
  IconShield,
  IconZap,
} from '../components/icons';
import { fmtNum, fmtTime } from '../utils/format';

const healthPill = (status: string) => {
  if (status === 'ready') return <Pill tone="green">在线</Pill>;
  if (status === 'missing_key') return <Pill tone="orange">待配密钥</Pill>;
  if (status === 'circuit_open') return <Pill tone="red">熔断保护</Pill>;
  return <Pill>已停用</Pill>;
};

export const Dashboard: React.FC = () => {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const loadDashboard = async () => {
    setLoading(true);
    try {
      const resp = await fetch('/api/admin/dashboard');
      const json = await resp.json();
      setData(json);
    } catch (e: any) {
      message.error(`加载监控大盘失败: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDashboard();
  }, []);

  const kpis = data?.kpis || {};
  const providers: ProviderItem[] = data?.providers || [];
  const recentTraces: any[] = data?.recent_traces || [];
  const routeDist: { resolved_route: string; cnt: number }[] = data?.route_distribution || [];
  const visible = providers.filter((p) => p.health_status !== 'disabled');
  const ready = visible.filter((p) => p.health_status === 'ready');
  const disabledCount = providers.length - visible.length;


  return (
    <div>
      <PageHeader
        icon={<IconGrid size={21} />}
        title="态势大盘"
        subtitle="检索源健康度、路由分布与调用链路。"
        extra={
          <Button icon={<IconRefresh size={15} />} onClick={loadDashboard} loading={loading}>
            刷新态势
          </Button>
        }
      />

      <div className="grid cols-6 section-gap">
        <Stat
          label="在线检索源"
          value={kpis.ready_search_engines || 0}
          suffix={`/ ${kpis.total_search_engines || 0}`}
          icon={<IconServer size={14} />}
          tone="green"
          hint="已就绪的上游引擎"
        />
        <Stat
          label="累计搜索请求"
          value={fmtNum(kpis.total_searches || 0)}
          suffix="次"
          icon={<IconZap size={14} />}
          hint="端到端聚合检索次数"
        />
        <Stat
          label="扇出调用"
          value={fmtNum(kpis.total_api_fanout_calls || 0)}
          suffix="次"
          icon={<IconLayers size={14} />}
          tone="purple"
          hint="单次请求平均打 3~5 个源"
        />
        <Stat
          label="平均首包延迟"
          value={Math.round(kpis.avg_latency_ms || 0)}
          suffix="ms"
          icon={<IconClock size={14} />}
          tone="orange"
          hint="网关侧端到端耗时"
        />
        <Stat
          label="调度成功率"
          value={Number(kpis.api_success_rate ?? 100).toFixed(1)}
          suffix="%"
          icon={<IconShield size={14} />}
          tone="teal"
          hint="熔断与重试后仍成功的占比"
        />
        <Stat
          label="跨源重合提权"
          value={fmtNum(kpis.cross_engine_hits || 0)}
          suffix="条"
          icon={<IconGlobe size={14} />}
          tone="purple"
          hint="被 2 个以上引擎同时命中的 URL"
        />
      </div>

      <div className="grid cols-3 section-gap" style={{ gridTemplateColumns: 'minmax(0, 2fr) minmax(0, 1fr)' }}>
        <Section
          title="引擎健康矩阵"
          subtitle={`${ready.length} 个渠道在线 · 权重越高在融合排序中越占优`}
          extra={
            <Pill tone="green">
              {visible.length} 个渠道{disabledCount > 0 ? ` · ${disabledCount} 已停用` : ''}
            </Pill>
          }
        >
          <div className="grid cols-2" style={{ gap: 10 }}>
            {visible.map((p) => (
              <div
                key={p.id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                  padding: '11px 12px',
                  borderRadius: 12,
                  border: '1px solid var(--line-soft)',
                  background: p.health_status === 'ready' ? 'var(--surface)' : 'var(--surface-2)',
                }}
              >
                <span
                  className={`dot ${
                    p.health_status === 'ready'
                      ? 'green'
                      : p.health_status === 'circuit_open'
                      ? 'red'
                      : p.health_status === 'missing_key'
                      ? 'orange'
                      : ''
                  }`}
                />
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div className="truncate" style={{ fontSize: 13, fontWeight: 600, letterSpacing: '-0.01em' }}>
                    {p.name}
                  </div>
                  <div className="tiny faint truncate">
                    {p.category.toUpperCase()} · 权重 {p.weight}x · {p.requires_key ? `${p.active_key_count} 个 Key` : '免 Key'}
                  </div>
                </div>
                <div style={{ textAlign: 'right', flex: 'none' }}>
                  {healthPill(p.health_status)}
                  <div className="tiny faint" style={{ marginTop: 3 }}>
                    {Math.round(p.avg_latency_ms || 0)} ms
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Section>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Section title="路由分布" subtitle="自动路由命中的意图分组">
            <AreaChart
              data={routeDist.length ? routeDist.map((r) => r.cnt) : [0, 0]}
              labels={routeDist.map((r) => r.resolved_route)}
              height={110}
              formatValue={(v) => `${fmtNum(v)} 次`}
            />
            <div style={{ marginTop: 12, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {routeDist.slice(0, 6).map((r) => (
                <Pill key={r.resolved_route} tone="accent">
                  {r.resolved_route.toUpperCase()} · {r.cnt}
                </Pill>
              ))}
              {routeDist.length === 0 ? <span className="tiny faint">暂无路由数据</span> : null}
            </div>
          </Section>

          <Section title="运行状态" subtitle="持续自检的网关健康度">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div className="list-row" style={{ padding: '4px 0', borderBottom: 0 }}>
                <span className="dot green" />
                <span className="small" style={{ flex: 1 }}>网关进程</span>
                <Pill tone="green">运行中</Pill>
              </div>
              <div className="list-row" style={{ padding: '4px 0', borderBottom: 0 }}>
                <span className="dot green" />
                <span className="small" style={{ flex: 1 }}>语义缓存</span>
                <Pill tone="teal">{fmtNum(kpis.cache_hits || 0)} 次命中</Pill>
              </div>
              <div className="list-row" style={{ padding: '4px 0', borderBottom: 0 }}>
                <span className={`dot ${kpis.circuit_open_count ? 'orange' : 'green'}`} />
                <span className="small" style={{ flex: 1 }}>熔断保护</span>
                <Pill tone={kpis.circuit_open_count ? 'orange' : 'green'}>{kpis.circuit_open_count || 0} 个</Pill>
              </div>
              <div className="list-row" style={{ padding: '4px 0', borderBottom: 0 }}>
                <StatusDot tone="accent" label={<span className="tiny faint">监听端口 8088 · OpenAI 兼容已开启</span>} />
              </div>
            </div>
          </Section>
        </div>
      </div>

      <Section title="最近调用" subtitle="每一次聚合检索都会留下可审计的 trace" flush>
        <Table
          rowKey="trace_id"
          size="small"
          pagination={false}
          dataSource={recentTraces}
          locale={{ emptyText: '还没有调用记录' }}
          columns={[
            {
              title: 'TRACE',
              dataIndex: 'trace_id',
              width: 170,
              render: (v: string) => <code className="code-inline">{v}</code>,
            },
            {
              title: '检索词',
              dataIndex: 'query',
              ellipsis: true,
              render: (v: string) => <span style={{ fontWeight: 500 }}>{v}</span>,
            },
            {
              title: '模式',
              dataIndex: 'mode',
              width: 120,
              render: (v: string) => (
                <Pill tone={v?.includes('deep') ? 'purple' : 'accent'}>{v}</Pill>
              ),
            },
            {
              title: '路由',
              dataIndex: 'resolved_route',
              width: 100,
              render: (v: string) => <code className="code-inline">{v}</code>,
            },
            {
              title: '原始 → 融合',
              width: 150,
              render: (_, r: any) => (
                <span className="small num">
                  {r.total_raw_results} → <strong>{r.total_merged_results}</strong>
                  {r.cross_engine_hits > 0 ? (
                    <Pill tone="orange" style={{ marginLeft: 6 }}>重合 {r.cross_engine_hits}</Pill>
                  ) : null}
                </span>
              ),
            },
            {
              title: '耗时',
              dataIndex: 'total_latency_ms',
              width: 100,
              render: (v: number) => (
                <span className="num small" style={{ color: v < 3000 ? 'var(--green)' : 'var(--orange)' }}>
                  {fmtNum(v)} ms
                </span>
              ),
            },
            {
              title: '时间',
              dataIndex: 'created_at',
              width: 165,
              render: (v: number) => <span className="tiny faint num">{fmtTime(v)}</span>,
            },
          ]}
        />
      </Section>
    </div>
  );
};
