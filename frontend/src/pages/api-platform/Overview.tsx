import React from 'react';
import { Table } from 'antd';
import {
  AreaChart,
  BarList,
  EmptyState,
  Pill,
  Section,
  Stat,
  StatusDot,
} from '../../components/ui';
import {
  IconChart,
  IconServer,
  IconThunderbolt,
  IconUsers,
  IconWallet,
  IconZap,
} from '../../components/icons';
import { fmtCny, fmtNum } from '../../utils/format';

export const OverviewTab: React.FC<{ data: any; loading: boolean }> = ({ data, loading }) => {
  const kpis = data?.kpis || {};
  const series: any[] = data?.series || [];
  const endpoints: any[] = data?.endpoints || [];
  const topClients: any[] = data?.top_clients || [];
  const plans: any[] = data?.plans || [];
  const planDist: any[] = data?.plan_distribution || [];
  const providers: any[] = data?.providers || [];

  // 后端只返回有数据的日期，这里补齐 30 天，趋势图才不会被单点数据压成一条线
  const byDay = new Map<string, number>(series.map((s) => [String(s.day || ''), Number(s.requests || 0)]));
  const filled: { day: string; value: number }[] = [];
  for (let i = 29; i >= 0; i -= 1) {
    const d = new Date();
    d.setDate(d.getDate() - i);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    filled.push({ day: key, value: byDay.get(key) || 0 });
  }
  const calls = filled.map((f) => f.value);
  const labels = filled.map((f) => f.day.slice(5));

  return (
    <div>
      <div className="grid cols-6 section-gap">
        <Stat
          label="窗口期营收"
          value={fmtCny(kpis.revenue_cny, 0)}
          icon={<IconWallet size={14} />}
          tone="green"
          hint="近 30 天充值到账（真实营收）"
        />
        <Stat
          label="用量折算消耗"
          value={fmtCny(kpis.consumed_cny, 2)}
          icon={<IconZap size={14} />}
          tone="purple"
          hint="按千次单价折算的客户用量"
        />
        <Stat
          label="付费客户"
          value={kpis.clients_paid || 0}
          suffix="家"
          icon={<IconUsers size={14} />}
          tone="accent"
          hint={`客户总数 ${kpis.clients_total || 0} 家`}
        />
        <Stat
          label="窗口期调用"
          value={fmtNum(kpis.requests || 0)}
          suffix="次"
          icon={<IconThunderbolt size={14} />}
          spark={calls}
          hint={`消耗 ${fmtNum(kpis.units || 0)} 次额度`}
        />
        <Stat
          label="P95 延迟"
          value={fmtNum(kpis.p95_latency_ms || 0)}
          suffix="ms"
          tone="orange"
          icon={<IconChart size={14} />}
          hint="95% 的请求快于此值"
        />
        <Stat
          label="失败率 / 缓存"
          value={`${Number(kpis.error_rate || 0).toFixed(1)}%`}
          suffix={`/ ${Number(kpis.cache_hit_rate || 0).toFixed(0)}%`}
          tone={Number(kpis.error_rate || 0) > 5 ? 'red' : 'green'}
          hint="失败率越低、缓存越高越健康"
        />
      </div>

      <div className="grid section-gap" style={{ gridTemplateColumns: 'minmax(0, 1.7fr) minmax(0, 1fr)', alignItems: 'start' }}>
        <Section
          title="调用趋势"
          subtitle="近 30 天每天的请求量"
          extra={<Pill tone="accent">{fmtNum(calls.reduce((a, b) => a + b, 0))} 次</Pill>}
        >
          <AreaChart data={calls} labels={labels} height={168} />
          <div style={{ display: 'flex', gap: 18, marginTop: 14, flexWrap: 'wrap' }}>
            <span className="tiny faint">
              客户侧剩余额度 <strong style={{ color: 'var(--text)' }}>{fmtNum(kpis.balance_units_total || 0)}</strong> 次
            </span>
            <span className="tiny faint">
              ARPU <strong style={{ color: 'var(--text)' }}>{fmtCny(kpis.arpu_cny || 0)}</strong>
            </span>
            <span className="tiny faint">
              累计营收 <strong style={{ color: 'var(--text)' }}>{fmtCny(kpis.revenue_total_cny || 0)}</strong>
            </span>
          </div>
        </Section>

        <Section title="接口分布" subtitle="按调用量排序">
          {endpoints.length === 0 ? (
            <EmptyState title="还没有对外调用" desc="客户拿到密钥后，这里会实时出现调用分布。" />
          ) : (
            <BarList
              items={endpoints.map((e) => ({
                label: <code className="code-inline">{e.endpoint}</code>,
                value: Number(e.requests || 0),
              }))}
              format={(v) => `${fmtNum(v)} 次`}
            />
          )}
        </Section>
      </div>

      <div className="grid section-gap" style={{ gridTemplateColumns: 'minmax(0, 1.6fr) minmax(0, 1fr)', alignItems: 'start' }}>
        <Section title="消耗 Top 客户" subtitle="按计费额度排序" flush>
          <Table
            rowKey="client_id"
            size="small"
            pagination={false}
            loading={loading}
            dataSource={topClients}
            locale={{ emptyText: '暂无客户调用' }}
            columns={[
              { title: '客户', dataIndex: 'client_name', ellipsis: true },
              {
                title: '套餐',
                dataIndex: 'plan_name',
                width: 110,
                render: (v: string) => <Pill tone="accent">{v || '—'}</Pill>,
              },
              { title: '调用', dataIndex: 'requests', width: 80, render: (v: number) => <span className="num">{fmtNum(v)}</span> },
              { title: '额度', dataIndex: 'units', width: 80, render: (v: number) => <span className="num">{fmtNum(v)}</span> },
              { title: '折算金额', dataIndex: 'cost_cny', width: 110, render: (v: number) => <span className="num">{fmtCny(v)}</span> },
              {
                title: '失败',
                dataIndex: 'errors',
                width: 70,
                render: (v: number) =>
                  v > 0 ? <span style={{ color: 'var(--red)' }}>{v}</span> : <span className="faint">0</span>,
              },
            ]}
          />
        </Section>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Section title="套餐分布" subtitle="按客户所属套餐统计">
            {planDist.length === 0 ? (
              <span className="tiny faint">暂无客户</span>
            ) : (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {planDist.map((p) => (
                  <Pill key={p.name} tone="purple">
                    {p.name} · {p.count} 家
                  </Pill>
                ))}
              </div>
            )}

          </Section>

          <Section
            title="上游风险"
            subtitle="高级源不可全量透传"
            extra={<IconServer size={15} style={{ color: 'var(--text-3)' }} />}
          >
            {providers.slice(0, 6).map((p) => (
              <div className="list-row" key={p.id} style={{ padding: '8px 0' }}>
                <StatusDot
                  tone={p.health_status === 'ready' ? 'green' : p.health_status === 'circuit_open' ? 'red' : 'orange'}
                />
                <span className="small truncate" style={{ flex: 1 }}>{p.name}</span>
                <span className="tiny faint num">{Math.round(p.avg_latency_ms || 0)} ms</span>
              </div>
            ))}
          </Section>
        </div>
      </div>
    </div>
  );
};
