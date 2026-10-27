import React, { useEffect, useState } from 'react';
import { Button, message } from 'antd';
import { PageHeader, Pill, SubTabs } from '../../components/ui';
import { IconCode, IconExternal, IconRefresh } from '../../components/icons';
import { OverviewTab } from './Overview';
import { CustomersTab } from './Customers';
import { PlansTab } from './Plans';
import { BillingTab } from './Billing';
import { DocsTab } from './Docs';

const TABS = [
  { key: 'overview', label: '商业化概览' },
  { key: 'customers', label: '客户与密钥' },
  { key: 'plans', label: '套餐与定价' },
  { key: 'billing', label: '用量与账单' },
  { key: 'docs', label: '接入与调试' },
];

export const ApiPlatformPage: React.FC = () => {
  const [tab, setTab] = useState(() => new URLSearchParams(window.location.search).get('tab') || 'overview');
  const [overview, setOverview] = useState<any>(null);
  const [clients, setClients] = useState<any[]>([]);
  const [plans, setPlans] = useState<any[]>([]);
  const [meta, setMeta] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [ov, cl, pl, mt] = await Promise.all([
        fetch('/api/admin/platform/overview?days=30').then((r) => r.json()),
        fetch('/api/admin/platform/clients').then((r) => r.json()),
        fetch('/api/admin/platform/plans').then((r) => r.json()),
        fetch('/api/admin/platform/meta').then((r) => r.json()),
      ]);
      setOverview(ov);
      setClients(Array.isArray(cl) ? cl : []);
      setPlans(Array.isArray(pl) ? pl : []);
      setMeta(mt);
    } catch (e: any) {
      message.error(`加载开放 API 平台数据失败: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAll();
  }, []);

  return (
    <div>
      <PageHeader
        icon={<IconCode size={21} />}
        title="开放 API 平台"
        tags={<Pill tone="green">按千次计费</Pill>}
        subtitle="多源聚合搜索的标准商业 API：鉴权、配额、计量与账单。"
        extra={
          <>
            <Button icon={<IconRefresh size={15} />} onClick={loadAll} loading={loading}>
              刷新
            </Button>
            <Button
              type="primary"
              icon={<IconExternal size={15} />}
              href="/docs/api"
              target="_blank"
              rel="noreferrer"
            >
              对外文档
            </Button>
          </>
        }
      />

      <div style={{ marginBottom: 18 }}>
        <SubTabs items={TABS} value={tab} onChange={setTab} />
      </div>

      {tab === 'overview' ? <OverviewTab data={overview} loading={loading} /> : null}
      {tab === 'customers' ? (
        <CustomersTab clients={clients} plans={plans} loading={loading} reload={loadAll} />
      ) : null}
      {tab === 'plans' ? <PlansTab plans={plans} loading={loading} reload={loadAll} /> : null}
      {tab === 'billing' ? <BillingTab clients={clients} plans={plans} /> : null}
      {tab === 'docs' ? <DocsTab meta={meta} /> : null}
    </div>
  );
};
