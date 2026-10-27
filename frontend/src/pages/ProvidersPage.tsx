import React, { useEffect, useState } from 'react';
import {
  Button,
  Col,
  Drawer,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Select,
  Switch,
  Table,
  message,
} from 'antd';
import {
  IconAlert,
  IconChevronRight,
  IconDownload,
  IconGrid,
  IconKey,
  IconLayers,
  IconPlus,
  IconRefresh,
  IconSearch,
  IconSparkles,
} from '../components/icons';
import { EmptyState, KeyValue, PageHeader, Pill, Section, SubTabs, Toolbar } from '../components/ui';
import type { Tone } from '../components/ui';
import { fmtNum } from '../utils/format';
import type { ApiKeyItem, ProviderItem } from '../api';

/* -------------------------------------------------------------------------- */
/*  纯视觉映射：状态 → 色调 / 文案                                             */
/* -------------------------------------------------------------------------- */

const providerTone = (p: ProviderItem): Tone => {
  if (p.health_status === 'ready') return 'green';
  if (p.health_status === 'missing_key') return 'orange';
  if (p.health_status === 'circuit_open') return 'red';
  return 'default';
};

const providerDot = (p: ProviderItem) => {
  const tone = providerTone(p);
  return tone === 'default' ? 'dot' : `dot ${tone}`;
};

const healthPill = (p: ProviderItem) => {
  const tone = providerTone(p);
  const text =
    p.health_status === 'ready'
      ? '在线'
      : p.health_status === 'missing_key'
      ? '待配密钥'
      : p.health_status === 'circuit_open'
      ? '熔断保护'
      : '已停用';
  return <Pill tone={tone}>{text}</Pill>;
};

const typeTone = (value: string): Tone => {
  if (value === 'scraper') return 'teal';
  if (value === 'llm' || value === 'reranker') return 'purple';
  return 'accent';
};

const typeLabel = (value: string) => {
  if (value === 'scraper') return '抓取器';
  if (value === 'llm') return '大模型';
  if (value === 'reranker') return '重排';
  return '搜索源';
};

const strategyLabel = (value: string) => {
  if (value === 'round_robin') return '顺序轮询';
  if (value === 'weighted') return '加权随机';
  if (value === 'least_used') return '最少使用';
  if (value === 'priority') return '优先级';
  return value || '加权随机';
};

const TYPE_OPTIONS = [
  { label: '搜索源 search', value: 'search' },
  { label: '抓取器 scraper', value: 'scraper' },
  { label: '大模型 llm', value: 'llm' },
  { label: '重排 reranker', value: 'reranker' },
];

const CATEGORY_OPTIONS = [
  { label: 'web · 通用网页', value: 'web' },
  { label: 'academic · 学术', value: 'academic' },
  { label: 'code · 代码', value: 'code' },
  { label: 'social · 社交', value: 'social' },
  { label: 'entertainment · 娱乐', value: 'entertainment' },
  { label: 'scraper · 抓取', value: 'scraper' },
  { label: 'llm · 大模型', value: 'llm' },
  { label: 'reranker · 重排', value: 'reranker' },
];

const STRATEGY_OPTIONS = [
  { label: '顺序轮询 Round Robin', value: 'round_robin' },
  { label: '加权随机 Weighted', value: 'weighted' },
  { label: '最少使用 Least Used', value: 'least_used' },
  { label: '优先级 Priority', value: 'priority' },
];

/* -------------------------------------------------------------------------- */
/*  密钥行：掩码 + 配额进度 + 状态 + 移除                                       */
/* -------------------------------------------------------------------------- */

const KeyRow: React.FC<{ k: ApiKeyItem; onDelete: (keyId: string) => void }> = ({ k, onDelete }) => {
  const quota = Number(k.daily_quota || 0);
  const used = Number(k.used_today || 0);
  const pct = quota > 0 ? Math.min(100, Math.round((used / quota) * 100)) : 0;
  const barColor = pct >= 90 ? 'var(--red)' : pct >= 70 ? 'var(--orange)' : 'var(--accent)';
  const healthy = k.last_status === 'healthy';
  const errored = k.last_status === 'error';

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        flexWrap: 'wrap',
        padding: '12px 0',
        borderBottom: '1px solid var(--line-soft)',
      }}
    >
      <div style={{ flex: '1 1 210px', minWidth: 0, display: 'flex', alignItems: 'flex-start', gap: 10 }}>
        <span className={`dot ${healthy ? 'green' : errored ? 'red' : ''}`} style={{ marginTop: 6 }} />
        <div style={{ minWidth: 0 }}>
          <div className="truncate" style={{ fontSize: 13, fontWeight: 600, letterSpacing: '-0.005em' }}>
            {k.label || '未命名密钥'}
            {k.enabled ? null : <Pill style={{ marginLeft: 6 }}>已停用</Pill>}
          </div>
          <div style={{ marginTop: 4 }}>
            <code className="code-inline" style={{ fontSize: 11 }}>
              {k.api_key_masked || '—'}
            </code>
          </div>
          {errored && k.last_error ? (
            <div className="tiny truncate" style={{ color: 'var(--red)', marginTop: 3, maxWidth: 280 }} title={k.last_error}>
              {k.last_error}
            </div>
          ) : null}
        </div>
      </div>

      <div style={{ flex: '1 1 180px', minWidth: 150 }}>
        <div
          className="num"
          style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', fontSize: 11.5, color: 'var(--text-2)' }}
        >
          <span>
            已用 <strong style={{ color: 'var(--text)', fontWeight: 600 }}>{fmtNum(used)}</strong>
            <span className="faint"> / {quota > 0 ? fmtNum(quota) : '不限'}</span>
          </span>
          <span style={{ color: pct >= 90 ? 'var(--red)' : 'var(--text-3)' }}>{quota > 0 ? `${pct}%` : '—'}</span>
        </div>
        <div style={{ height: 4, borderRadius: 999, background: 'var(--fill)', marginTop: 6, overflow: 'hidden' }}>
          <div
            style={{
              width: `${pct}%`,
              height: '100%',
              borderRadius: 999,
              background: barColor,
              transition: 'width 400ms var(--ease)',
            }}
          />
        </div>
      </div>

      <div style={{ flex: '1 1 130px', minWidth: 116, textAlign: 'right' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 6 }}>
          {healthy && k.last_latency_ms ? (
            <span className="tiny faint num">{Math.round(k.last_latency_ms)} ms</span>
          ) : null}
          <Pill tone={healthy ? 'green' : errored ? 'red' : 'default'}>
            {healthy ? '健康' : errored ? '异常' : '未调用'}
          </Pill>
        </div>
        <div className="tiny faint num" style={{ marginTop: 4 }}>
          权重 {k.weight}x · 累计 {fmtNum(k.total_used)} 次
        </div>
      </div>

      <Popconfirm title="确认移除该密钥？" okText="移除" cancelText="取消" onConfirm={() => onDelete(k.id)}>
        <Button size="small" type="text" danger>
          移除
        </Button>
      </Popconfirm>
    </div>
  );
};

/* -------------------------------------------------------------------------- */
/*  页面                                                                      */
/* -------------------------------------------------------------------------- */

export const ProvidersPage: React.FC<{
  initialProviderId?: string;
  onFocusConsumed?: () => void;
}> = ({ initialProviderId, onFocusConsumed }) => {
  const [providers, setProviders] = useState<ProviderItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState('all');

  // Key Drawer
  const [selectedProv, setSelectedProv] = useState<ProviderItem | null>(null);
  const [keyDrawerOpen, setKeyDrawerOpen] = useState(false);
  const [addKeyForm] = Form.useForm();

  // Provider Edit Modal
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editForm] = Form.useForm();

  // Provider Create Modal
  const [createOpen, setCreateOpen] = useState(false);
  const [createForm] = Form.useForm();

  const loadProviders = async () => {
    setLoading(true);
    try {
      const resp = await fetch('/api/admin/providers');
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      setProviders(data);
      if (selectedProv) {
        const updated = data.find((p: ProviderItem) => p.id === selectedProv.id);
        if (updated) setSelectedProv(updated);
      }
    } catch (e: any) {
      message.error(`加载渠道列表失败: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadProviders();
  }, []);

  useEffect(() => {
    if (!initialProviderId || !providers.length) return;
    const provider = providers.find((p) => p.id === initialProviderId);
    if (provider) {
      setSelectedProv(provider);
      setKeyDrawerOpen(true);
      onFocusConsumed?.();
    }
  }, [initialProviderId, providers, onFocusConsumed]);

  const handleToggleProvider = async (prov: ProviderItem, enabled: boolean) => {
    await fetch(`/api/admin/providers/${prov.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    });
    message.success(`${prov.name} 已${enabled ? '启用' : '停用'}`);
    loadProviders();
  };

  const handleToggleProxy = async (prov: ProviderItem, use_proxy: boolean) => {
    await fetch(`/api/admin/providers/${prov.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ use_proxy }),
    });
    message.success(`${prov.name} 已切换为${use_proxy ? '走代理通道' : '直连通道'}`);
    loadProviders();
  };

  const handleTestConnectivity = async (prov: ProviderItem) => {
    setTestingId(prov.id);
    try {
      const resp = await fetch(`/api/admin/providers/${prov.id}/test?test_query=DeepSeek`, {
        method: 'POST',
      });
      const res = await resp.json();
      if (res.status === 'success') {
        message.success(
          `✅ [${prov.name}] 探活成功！耗时 ${res.latency_ms} ms，返回 ${res.result_count ?? 1} 条数据`
        );
      } else {
        message.warning(`⚠️ [${prov.name}] 探活状态: ${res.status} (${res.error_message || ''})`);
      }
      loadProviders();
    } catch (e: any) {
      message.error(`探活请求失败: ${e.message}`);
    } finally {
      setTestingId(null);
    }
  };

  const handleResetCircuit = async (prov: ProviderItem) => {
    await fetch(`/api/admin/providers/${prov.id}/reset-circuit`, { method: 'POST' });
    message.success(`${prov.name} 熔断器已手动复位`);
    loadProviders();
  };

  const handleAddKey = async (values: any) => {
    if (!selectedProv) return;
    try {
      const resp = await fetch('/api/admin/keys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider_id: selectedProv.id,
          label: values.label || '默认密钥',
          api_key: values.api_key.trim(),
          base_url: values.base_url || '',
          weight: values.weight ?? 1,
          rpm_limit: values.rpm_limit ?? 60,
          daily_quota: values.daily_quota ?? 10000,
          enabled: true,
        }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      message.success(`已向 [${selectedProv.name}] 密钥池添加新 API Key`);
      addKeyForm.resetFields();
      await loadProviders();
    } catch (err: any) {
      message.error(`添加密钥失败：${err.message}`);
    }
  };

  const handleDeleteKey = async (keyId: string) => {
    await fetch(`/api/admin/keys/${keyId}`, { method: 'DELETE' });
    message.success('密钥已移除');
    loadProviders();
  };

  const handleOpenEditModal = (prov: ProviderItem) => {
    setSelectedProv(prov);
    editForm.setFieldsValue({
      weight: prov.weight,
      timeout_ms: prov.timeout_ms,
      base_url: prov.base_url,
      default_model: prov.default_model,
      strategy: prov.strategy,
      custom_proxy: prov.custom_proxy,
    });
    setEditModalOpen(true);
  };

  const handleSaveProviderConfig = async (values: any) => {
    if (!selectedProv) return;
    await fetch(`/api/admin/providers/${selectedProv.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(values),
    });
    message.success(`[${selectedProv.name}] 参数已保存`);
    setEditModalOpen(false);
    loadProviders();
  };

  const handleOpenKeyDrawer = (prov: ProviderItem) => {
    setSelectedProv(prov);
    setKeyDrawerOpen(true);
  };

  const handleCreateProvider = async (values: any) => {
    try {
      const resp = await fetch('/api/admin/providers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...values,
          id: String(values.id || '').trim().toLowerCase().replace(/\s+/g, '_'),
          name: String(values.name || '').trim(),
          category: values.category || values.provider_type,
          use_proxy: false,
        }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        message.error(err.detail || `创建失败 HTTP ${resp.status}`);
        return;
      }
      message.success(`已新增渠道 [${values.name}]`);
      setCreateOpen(false);
      createForm.resetFields();
      loadProviders();
    } catch (e: any) {
      message.error(`创建渠道失败：${e.message}`);
    }
  };

  const filteredProviders = providers.filter((p) => {
    if (activeTab === 'all') return true;
    if (activeTab === 'free_search') return p.provider_type === 'search' && !p.requires_key;
    if (activeTab === 'paid_search') return p.provider_type === 'search' && p.requires_key;
    if (activeTab === 'scraper') return p.provider_type === 'scraper';
    if (activeTab === 'llm_rerank') return p.provider_type === 'llm' || p.provider_type === 'reranker';
    return true;
  });

  const freeSearchCount = providers.filter((p) => p.provider_type === 'search' && !p.requires_key).length;
  const paidSearchCount = providers.filter((p) => p.provider_type === 'search' && p.requires_key).length;
  const scraperCount = providers.filter((p) => p.provider_type === 'scraper').length;
  const llmRerankCount = providers.filter((p) => p.provider_type === 'llm' || p.provider_type === 'reranker').length;
  const readyCount = providers.filter((p) => p.health_status === 'ready').length;
  const missingKeyCount = providers.filter((p) => p.health_status === 'missing_key').length;
  const circuitCount = providers.filter((p) => p.health_status === 'circuit_open').length;
  const disabledCount = providers.filter((p) => p.health_status === 'disabled').length;
  const selectedKeys: ApiKeyItem[] = selectedProv?.keys || [];

  /* ---------------------------- 展开行：密钥池 ---------------------------- */

  const renderProviderKeys = (prov: ProviderItem) => {
    const keys: ApiKeyItem[] = prov.keys || [];
    return (
      <div style={{ padding: '2px 2px 4px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
          <span style={{ fontSize: 12.5, fontWeight: 600 }}>密钥池</span>
          <Pill tone={prov.active_key_count > 0 ? 'teal' : 'orange'}>
            {prov.active_key_count} / {prov.total_key_count} 可用
          </Pill>
          <span className="tiny faint">
            {strategyLabel(prov.strategy)} · 权重 {prov.weight}x · 超时 {prov.timeout_ms} ms ·{' '}
            {prov.use_proxy ? '走代理' : '国内直连'}
          </span>
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }} className="tiny faint">
              走代理
              <Switch size="small" checked={Boolean(prov.use_proxy)} onChange={(v) => handleToggleProxy(prov, v)} />
            </span>
            <Button size="small" type="text" icon={<IconPlus size={13} />} onClick={() => handleOpenKeyDrawer(prov)}>
              添加密钥
            </Button>
          </div>
        </div>

        <div className="tiny faint" style={{ marginBottom: 8 }}>
          {prov.description || '暂无渠道描述'}
        </div>

        {prov.last_error ? (
          <div
            style={{
              display: 'flex',
              alignItems: 'flex-start',
              gap: 7,
              padding: '8px 11px',
              borderRadius: 10,
              background: 'var(--red-soft)',
              color: 'var(--red)',
              fontSize: 11.5,
              lineHeight: 1.5,
              marginBottom: 10,
            }}
          >
            <IconAlert size={13} style={{ marginTop: 1, flex: 'none' }} />
            <span style={{ minWidth: 0, wordBreak: 'break-word' }}>{prov.last_error}</span>
          </div>
        ) : null}

        {keys.length ? (
          keys.map((k) => <KeyRow key={k.id} k={k} onDelete={handleDeleteKey} />)
        ) : (
          <div className="tiny faint" style={{ padding: '14px 0' }}>
            密钥池还是空的。点「添加密钥」把 API Key 加进来，网关会按权重自动轮询并熔断隔离。
          </div>
        )}
      </div>
    );
  };

  return (
    <div>
      <PageHeader
        icon={<IconLayers size={21} />}
        title="渠道与密钥池"
        subtitle="检索源接入、权重与多 Key 轮询。"
        extra={
          <>
            <Button icon={<IconRefresh size={15} />} onClick={loadProviders} loading={loading}>
              刷新
            </Button>
            <Button type="primary" icon={<IconPlus size={15} />} onClick={() => setCreateOpen(true)}>
              新增渠道
            </Button>
          </>
        }
      />

      <Toolbar
        right={
          <span className="tiny faint">
            {providers.length} 条渠道 · {readyCount} 在线
            {missingKeyCount ? ` · ${missingKeyCount} 待配密钥` : ''}
            {circuitCount ? ` · ${circuitCount} 熔断` : ''}
            {disabledCount ? ` · ${disabledCount} 已停用` : ''} · 行首箭头展开密钥池
          </span>
        }
      >
        <SubTabs
          value={activeTab}
          onChange={setActiveTab}
          items={[
            { key: 'all', label: `全部 ${providers.length}`, icon: <IconGrid size={13} /> },
            { key: 'free_search', label: `免 Key 搜索 ${freeSearchCount}`, icon: <IconSearch size={13} /> },
            { key: 'paid_search', label: `商业搜索 ${paidSearchCount}`, icon: <IconKey size={13} /> },
            { key: 'scraper', label: `抓取器 ${scraperCount}`, icon: <IconDownload size={13} /> },
            { key: 'llm_rerank', label: `模型 / 重排 ${llmRerankCount}`, icon: <IconSparkles size={13} /> },
          ]}
        />
      </Toolbar>

      <Section flush style={{ overflow: 'hidden' }}>
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          dataSource={filteredProviders}
          pagination={
            filteredProviders.length > 12
              ? { pageSize: 12, showSizeChanger: false, style: { padding: '0 20px', margin: '14px 0' } }
              : false
          }
          scroll={{ x: 980 }}
          locale={{
            emptyText: (
              <EmptyState
                icon={<IconLayers size={22} />}
                title="没有匹配的渠道"
                desc="换个分类看看，或点右上角「新增渠道」接入新的检索源。"
              />
            ),
          }}
          expandable={{
            expandedRowRender: (prov: ProviderItem) => renderProviderKeys(prov),
            expandIcon: ({ expanded, onExpand, record }: any) => (
              <button
                type="button"
                onClick={(e) => onExpand(record, e)}
                aria-label={expanded ? '收起密钥池' : '展开密钥池'}
                style={{
                  border: 0,
                  background: 'transparent',
                  padding: 3,
                  marginRight: 2,
                  display: 'grid',
                  placeItems: 'center',
                  cursor: 'pointer',
                  color: expanded ? 'var(--accent)' : 'var(--text-3)',
                  borderRadius: 6,
                }}
              >
                <IconChevronRight
                  size={14}
                  strokeWidth={1.8}
                  style={{ transform: expanded ? 'rotate(90deg)' : 'none', transition: 'transform 200ms var(--ease)' }}
                />
              </button>
            ),
          }}
          columns={[
            {
              title: '渠道',
              dataIndex: 'name',
              ellipsis: true,
              render: (_: any, p: ProviderItem) => (
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
                  <span className={providerDot(p)} />
                  <div style={{ minWidth: 0 }}>
                    <div className="truncate" style={{ fontSize: 13.5, fontWeight: 600, letterSpacing: '-0.01em' }}>
                      {p.name}
                    </div>
                    <div className="tiny faint truncate" style={{ marginTop: 2 }}>
                      <code className="code-inline" style={{ fontSize: 10.5, padding: '0 4px' }}>
                        {p.id}
                      </code>
                      <span style={{ marginLeft: 6 }}>{p.category} · {p.requires_key ? '需密钥' : '免 Key'}</span>
                    </div>
                  </div>
                </div>
              ),
            },
            {
              title: '类型',
              dataIndex: 'provider_type',
              width: 96,
              render: (value: string) => <Pill tone={typeTone(value)}>{typeLabel(value)}</Pill>,
            },
            {
              title: '运行指标',
              dataIndex: 'avg_latency_ms',
              width: 158,
              align: 'right',
              render: (_: any, p: ProviderItem) => (
                <div className="num" title={`成功 ${fmtNum(p.success_calls)} / 总计 ${fmtNum(p.total_calls)} 次`}>
                  <div style={{ fontSize: 13, fontWeight: 600 }}>
                    {Math.round(p.avg_latency_ms || 0)}
                    <span className="tiny faint" style={{ marginLeft: 3, fontWeight: 400 }}>
                      ms
                    </span>
                  </div>
                  <div className="tiny faint" style={{ marginTop: 2 }}>
                    权重 {p.weight}x · {fmtNum(p.total_calls)} 次
                  </div>
                </div>
              ),
            },
            {
              title: '启用',
              dataIndex: 'enabled',
              width: 70,
              render: (_: any, p: ProviderItem) => (
                <Switch size="small" checked={Boolean(p.enabled)} onChange={(v) => handleToggleProvider(p, v)} />
              ),
            },
            {
              title: '健康状态',
              dataIndex: 'health_status',
              width: 118,
              render: (_: any, p: ProviderItem) => (
                <div>
                  {healthPill(p)}
                  {p.health_status === 'circuit_open' && p.consecutive_failures ? (
                    <div className="tiny faint" style={{ marginTop: 3 }}>
                      连续失败 {p.consecutive_failures} 次
                    </div>
                  ) : null}
                </div>
              ),
            },
            {
              title: '操作',
              key: 'actions',
              width: 292,
              render: (_: any, p: ProviderItem) => (
                <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap' }}>
                  <Button size="small" type="text" onClick={() => handleOpenKeyDrawer(p)}>
                    管理密钥{p.total_key_count ? ` (${p.total_key_count})` : ''}
                  </Button>
                  <Button size="small" type="text" loading={testingId === p.id} onClick={() => handleTestConnectivity(p)}>
                    测试
                  </Button>
                  <Button size="small" type="text" onClick={() => handleOpenEditModal(p)}>
                    配置
                  </Button>
                  <Button
                    size="small"
                    type="text"
                    danger={p.health_status === 'circuit_open'}
                    onClick={() => handleResetCircuit(p)}
                  >
                    熔断重置
                  </Button>
                </div>
              ),
            },
          ]}
        />
      </Section>

      {/* 多 Key 密钥池抽屉 */}
      <Drawer
        width="min(760px, 100vw)"
        open={keyDrawerOpen}
        onClose={() => setKeyDrawerOpen(false)}
        title={
          selectedProv ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
              <span className={providerDot(selectedProv)} />
              <span className="truncate" style={{ fontSize: 16, fontWeight: 600, letterSpacing: '-0.02em' }}>
                {selectedProv.name}
              </span>
              {healthPill(selectedProv)}
            </div>
          ) : (
            '密钥池管理'
          )
        }
      >
        {selectedProv ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <span className="tiny faint">
                {typeLabel(selectedProv.provider_type)} · {strategyLabel(selectedProv.strategy)} · 权重{' '}
                {selectedProv.weight}x
              </span>
              <Button
                size="small"
                type="text"
                icon={<IconRefresh size={13} />}
                loading={loading}
                onClick={loadProviders}
                style={{ marginLeft: 'auto' }}
              >
                刷新用量
              </Button>
            </div>

            <div style={{ padding: '14px 16px', borderRadius: 14, background: 'var(--surface-2)' }}>
              <KeyValue
                columns={4}
                items={[
                  { label: '可用密钥', value: `${selectedProv.active_key_count} / ${selectedProv.total_key_count}` },
                  { label: '平均延迟', value: `${Math.round(selectedProv.avg_latency_ms || 0)} ms` },
                  { label: '累计调用', value: `${fmtNum(selectedProv.total_calls)} 次` },
                  { label: '超时截断', value: `${selectedProv.timeout_ms} ms` },
                ]}
              />
              <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <span className="tiny faint">接口端点</span>
                <code className="code-inline">{selectedProv.base_url || '—'}</code>
              </div>
            </div>

            <Section title="新增 API Key" subtitle="加入轮询池后按权重分摊请求与配额">
              <Form form={addKeyForm} layout="vertical" onFinish={handleAddKey}>
                <Row gutter={14}>
                  <Col span={12}>
                    <Form.Item name="label" label="密钥备注" initialValue="主力密钥 #1">
                      <Input placeholder="例如：免费额度号 1" />
                    </Form.Item>
                  </Col>
                  <Col span={12}>
                    <Form.Item
                      name="api_key"
                      label="API Key / Token"
                      rules={[{ required: true, message: '请输入 API Key' }]}
                    >
                      <Input.Password placeholder="sk-... / tvly-... / bch-..." />
                    </Form.Item>
                  </Col>
                  <Col span={12}>
                    <Form.Item name="base_url" label="自定义 Base URL（选填）">
                      <Input placeholder={selectedProv.base_url} />
                    </Form.Item>
                  </Col>
                  <Col span={6}>
                    <Form.Item name="weight" label="轮询权重" initialValue={1}>
                      <InputNumber min={1} max={20} style={{ width: '100%' }} />
                    </Form.Item>
                  </Col>
                  <Col span={6}>
                    <Form.Item name="daily_quota" label="每日配额上限" initialValue={10000}>
                      <InputNumber min={10} max={1000000} style={{ width: '100%' }} />
                    </Form.Item>
                  </Col>
                  <Col span={24}>
                    <Form.Item style={{ marginBottom: 0 }}>
                      <Button type="primary" htmlType="submit" icon={<IconPlus size={14} />} block>
                        添加到 [{selectedProv.name}] 密钥池
                      </Button>
                    </Form.Item>
                  </Col>
                </Row>
              </Form>
            </Section>

            <Section title="密钥列表" subtitle={`${selectedKeys.length} 把密钥 · 按权重轮询`} flush>
              <div style={{ padding: '0 20px 4px' }}>
                {selectedKeys.length ? (
                  selectedKeys.map((k) => <KeyRow key={k.id} k={k} onDelete={handleDeleteKey} />)
                ) : (
                  <div className="tiny faint" style={{ padding: '16px 0' }}>
                    还没有密钥，先在上方添加一把。
                  </div>
                )}
              </div>
            </Section>
          </div>
        ) : null}
      </Drawer>

      {/* 渠道高级参数弹窗 */}
      <Modal
        title={selectedProv ? `渠道参数 · ${selectedProv.name}` : '渠道参数'}
        open={editModalOpen}
        onCancel={() => setEditModalOpen(false)}
        onOk={() => editForm.submit()}
        okText="保存参数"
        width={640}
      >
        <Form form={editForm} layout="vertical" onFinish={handleSaveProviderConfig}>
          <Row gutter={14}>
            <Col span={24}>
              <Form.Item name="base_url" label="接口端点 Base URL">
                <Input />
              </Form.Item>
            </Col>
            <Col span={24}>
              <Form.Item name="default_model" label="默认模型（仅 LLM / Reranker 生效）">
                <Input placeholder="例如 deepseek-chat / jina-reranker-v2-base-multilingual" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="weight" label="RRF 融合权重">
                <InputNumber step={0.1} min={0.1} max={10} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="timeout_ms" label="超时截断 (ms)">
                <InputNumber step={500} min={1000} max={60000} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="strategy" label="多 Key 轮询策略">
                <Select options={STRATEGY_OPTIONS} />
              </Form.Item>
            </Col>
            <Col span={24}>
              <Form.Item name="custom_proxy" label="渠道专属代理（留空用全局代理）">
                <Input placeholder="例如 http://127.0.0.1:7890" />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>

      {/* 新增渠道弹窗 */}
      <Modal
        title="新增渠道"
        open={createOpen}
        onCancel={() => {
          setCreateOpen(false);
          createForm.resetFields();
        }}
        onOk={() => createForm.submit()}
        okText="创建渠道"
        width={760}
      >
        <Form
          form={createForm}
          layout="vertical"
          initialValues={{
            provider_type: 'search',
            category: 'web',
            weight: 1.5,
            timeout_ms: 30000,
            strategy: 'weighted',
            key_label: '默认密钥',
          }}
          onFinish={handleCreateProvider}
          onValuesChange={(changed) => {
            if (changed.provider_type) {
              createForm.setFieldValue(
                'category',
                changed.provider_type === 'search' ? 'web' : changed.provider_type
              );
            }
          }}
        >
          <Row gutter={14}>
            <Col span={12}>
              <Form.Item
                name="id"
                label="渠道 ID"
                rules={[{ required: true, message: '请填写唯一渠道 ID' }]}
                extra="小写字母 / 数字 / 下划线，创建后不可修改"
              >
                <Input placeholder="例如 my_serper" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="name" label="显示名称" rules={[{ required: true, message: '请填写渠道名称' }]}>
                <Input placeholder="例如 Serper 商业搜索" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="provider_type" label="渠道类型">
                <Select options={TYPE_OPTIONS} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="category" label="分类">
                <Select options={CATEGORY_OPTIONS} />
              </Form.Item>
            </Col>
            <Col span={16}>
              <Form.Item
                name="base_url"
                label="接口端点 Base URL"
                rules={[{ required: true, message: '请填写 Base URL' }]}
              >
                <Input placeholder="https://api.example.com" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="weight" label="融合权重">
                <InputNumber min={0.1} max={20} step={0.1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="timeout_ms" label="超时截断 (ms)">
                <InputNumber min={1000} max={60000} step={500} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="strategy" label="多 Key 轮询策略">
                <Select options={STRATEGY_OPTIONS} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="api_key" label="首个 API Key（选填）">
                <Input.Password placeholder="创建后也可在密钥池继续追加" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="key_label" label="密钥备注">
                <Input placeholder="默认密钥" />
              </Form.Item>
            </Col>
            <Col span={24}>
              <Form.Item name="description" label="渠道描述">
                <Input placeholder="一句话说明渠道定位，会展示在列表详情里" />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </div>
  );
};
