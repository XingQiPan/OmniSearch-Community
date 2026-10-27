import React, { useEffect, useState } from 'react';
import { Button, Input, Segmented, Select, Table, Tooltip, message } from 'antd';
import { EmptyState, Pill, Section, Stat, Toolbar } from '../../components/ui';
import { IconDownload, IconFilter, IconRefresh, IconWallet } from '../../components/icons';
import { fmtCny, fmtNum, fmtTime, shortId, todayMonth } from '../../utils/format';

export const BillingTab: React.FC<{ clients: any[]; plans: any[] }> = ({ clients, plans }) => {
  const [events, setEvents] = useState<any>({ total: 0, items: [] });
  const [loading, setLoading] = useState(false);
  const [clientId, setClientId] = useState<string | undefined>();
  const [endpoint, setEndpoint] = useState<string | undefined>();
  const [status, setStatus] = useState<string | undefined>();
  const [days, setDays] = useState(7);
  const [page, setPage] = useState(1);
  const [invoices, setInvoices] = useState<any>({ items: [], total_cost_cny: 0, total_units: 0 });
  const [month, setMonth] = useState(todayMonth);

  const loadEvents = async (p = page) => {
    setLoading(true);
    const qs = new URLSearchParams({ days: String(days), limit: '20', offset: String((p - 1) * 20) });
    if (clientId) qs.set('client_id', clientId);
    if (endpoint) qs.set('endpoint', endpoint);
    if (status) qs.set('status', status);
    const resp = await fetch(`/api/admin/platform/usage?${qs.toString()}`);
    setEvents(await resp.json());
    setLoading(false);
  };

  const loadInvoices = async (m = month) => {
    const resp = await fetch(`/api/admin/platform/invoices?month=${m}`);
    setInvoices(await resp.json());
  };

  useEffect(() => {
    loadEvents(1);
    setPage(1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientId, endpoint, status, days]);

  useEffect(() => {
    loadInvoices();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [month]);

  const exportCsv = () => {
    const header = '客户,套餐,请求数,额度,金额(元),失败数\n';
    const rows = (invoices.items || [])
      .map((i: any) => `${i.client_name},${i.plan_name},${i.requests},${i.units},${i.cost_cny},${i.errors}`)
      .join('\n');
    const blob = new Blob([`\uFEFF${header}${rows}`], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `omnisearch-billing-${month}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    message.success('账单已导出');
  };

  return (
    <div>
      <div className="grid cols-3 section-gap">
        <Stat
          label="本月合计金额"
          value={fmtCny(invoices.total_cost_cny)}
          icon={<IconWallet size={14} />}
          tone="purple"
          hint={`${invoices.month} 按客户汇总`}
        />
        <Stat
          label="本月计费额度"
          value={fmtNum(invoices.total_units)}
          suffix="次"
          tone="accent"
          hint="所有客户用量之和"
        />
        <Stat
          label="本月请求"
          value={fmtNum(events.total)}
          suffix="次"
          tone="green"
          hint="含缓存命中与失败请求"
        />
      </div>

      <Section
        title="调用明细"
        subtitle="每次付费调用都会落库，可逐条对账"
        extra={
          <Button icon={<IconRefresh size={15} />} onClick={() => loadEvents()}>
            刷新
          </Button>
        }
        gap
        flush
      >
        <div style={{ padding: '12px 20px 4px' }}>
          <Toolbar
            right={
              <span className="tiny faint" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                <IconFilter size={13} /> 共 {fmtNum(events.total)} 条
              </span>
            }
          >
            <Select
              allowClear
              placeholder="全部客户"
              style={{ width: 190 }}
              value={clientId}
              onChange={setClientId}
              options={clients.filter((c) => c.source !== 'internal').map((c: any) => ({ label: c.name, value: c.id }))}
            />
            <Select
              allowClear
              placeholder="全部接口"
              style={{ width: 190 }}
              value={endpoint}
              onChange={setEndpoint}
              options={['/v1/search', '/v1/extract', '/v1/answer', '/v1/chat/completions'].map((v) => ({ label: v, value: v }))}
            />
            <Select
              allowClear
              placeholder="全部状态"
              style={{ width: 140 }}
              value={status}
              onChange={setStatus}
              options={[
                { label: '成功', value: 'success' },
                { label: '失败', value: 'error' },
              ]}
            />
            <Segmented
              value={days}
              onChange={(v) => setDays(Number(v))}
              options={[
                { label: '1 天', value: 1 },
                { label: '7 天', value: 7 },
                { label: '30 天', value: 30 },
                { label: '90 天', value: 90 },
              ]}
            />
          </Toolbar>
        </div>

        <Table
          rowKey="id"
          size="small"
          loading={loading}
          dataSource={events.items || []}
          locale={{ emptyText: <EmptyState title="没有匹配的调用记录" desc="试试放宽筛选条件或切换时间范围。" /> }}
          pagination={{
            current: page,
            pageSize: 20,
            total: events.total || 0,
            onChange: (p) => {
              setPage(p);
              loadEvents(p);
            },
            showSizeChanger: false,
          }}
          columns={[
            { title: '时间', dataIndex: 'created_at', width: 132, render: (v: number) => <span className="tiny faint num">{fmtTime(v)}</span> },
            { title: '客户', dataIndex: 'client_name', width: 146, ellipsis: true },
            {
              title: '接口',
              dataIndex: 'endpoint',
              width: 158,
              ellipsis: true,
              render: (v: string) => (
                <Tooltip title={v}>
                  <code className="code-inline" style={{ fontSize: 10.5 }}>{v}</code>
                </Tooltip>
              ),
            },
            { title: '检索词', dataIndex: 'query', ellipsis: true, render: (v: string) => <span className="small">{v || '—'}</span> },
            {
              title: '状态',
              dataIndex: 'status',
              width: 62,
              render: (v: string, r: any) =>
                v === 'success' ? <Pill tone="green">{r.http_status}</Pill> : <Pill tone="red">{r.http_status}</Pill>,
            },
            { title: '额度', dataIndex: 'units', width: 56, align: 'right', render: (v: number) => <span className="num">{v}</span> },
            { title: '金额', dataIndex: 'cost_cny', width: 92, align: 'right', render: (v: number) => <span className="num">{fmtCny(v, 4)}</span> },
            {
              title: '延迟',
              dataIndex: 'latency_ms',
              width: 104,
              render: (v: number, r: any) => (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                  <span className="num tiny" style={{ color: v < 3000 ? 'var(--green)' : 'var(--orange)' }}>{fmtNum(v)}</span>
                  {r.cached ? <Pill tone="teal">HIT</Pill> : null}
                </span>
              ),
            },
            {
              title: 'REQUEST ID',
              dataIndex: 'request_id',
              width: 118,
              render: (v: string) => (
                <Tooltip title={v}>
                  <code className="code-inline" style={{ fontSize: 10, cursor: 'copy' }} onClick={() => {
                    navigator.clipboard.writeText(v);
                    message.success('Request ID 已复制');
                  }}>{shortId(v, 6, 4)}</code>
                </Tooltip>
              ),
            },
          ]}
        />
      </Section>

      <Section
        title="月度账单"
        subtitle="按自然月汇总每个客户的用量与金额，可直接开票"
        extra={
          <>
            <Input
              value={month}
              onChange={(e) => setMonth(e.target.value)}
              style={{ width: 120 }}
              placeholder="YYYY-MM"
              size="small"
            />
            <Button size="small" onClick={() => loadInvoices()}>查询</Button>
            <Button size="small" icon={<IconDownload size={14} />} onClick={exportCsv}>导出 CSV</Button>
          </>
        }
        flush
      >
        <Table
          rowKey="client_id"
          size="small"
          pagination={false}
          dataSource={invoices.items || []}
          locale={{ emptyText: <EmptyState title="本月还没有用量" desc="客户调用后，这里会自动生成账单。" /> }}
          columns={[
            { title: '客户', dataIndex: 'client_name' },
            { title: '套餐', dataIndex: 'plan_name', width: 120, render: (v: string) => <Pill tone="accent">{v || '—'}</Pill> },
            { title: '千次单价', dataIndex: 'price_per_1k_cny', width: 110, render: (v: number) => <span className="num">{fmtCny(v)}</span> },
            { title: '请求数', dataIndex: 'requests', width: 90, render: (v: number) => <span className="num">{fmtNum(v)}</span> },
            { title: '额度', dataIndex: 'units', width: 90, render: (v: number) => <span className="num">{fmtNum(v)}</span> },
            { title: '金额', dataIndex: 'cost_cny', width: 110, render: (v: number) => <span className="num strong">{fmtCny(v)}</span> },
            {
              title: '失败数',
              dataIndex: 'errors',
              width: 90,
              render: (v: number) => (v > 0 ? <span style={{ color: 'var(--red)' }}>{v}</span> : <span className="faint">0</span>),
            },
          ]}
        />
      </Section>

      <div style={{ marginTop: 14 }} className="tiny faint">
        在售套餐：
        {(plans || []).map((p: any) => `${p.name} ${fmtCny(p.price_per_1k_cny)}/千次`).join(' · ') || '—'}
      </div>
    </div>
  );
};
