import React, { useEffect, useState } from 'react';
import {
  AutoComplete,
  Button,
  Col,
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
import type { ApiKeyItem, ProviderItem } from '../api';
import { EmptyState, KeyValue, PageHeader, Pill, Section, Stat } from '../components/ui';
import {
  IconCheck,
  IconClock,
  IconDownload,
  IconFilter,
  IconPlus,
  IconRefresh,
  IconSliders,
  IconSparkles,
  IconTrash,
  IconZap,
} from '../components/icons';
import { fmtNum } from '../utils/format';

/** 与后端 dispatcher.apply_semantic_rerank 保持一致：每次精排最多送审 25 条融合候选 */
const RERANK_TOP_N = 25;

const healthPill = (status: string) => {
  if (status === 'ready') return <Pill tone="green">在线</Pill>;
  if (status === 'missing_key') return <Pill tone="orange">待配密钥</Pill>;
  if (status === 'circuit_open') return <Pill tone="red">熔断保护</Pill>;
  return <Pill>已停用</Pill>;
};

const keyStatusPill = (status: string) => {
  if (status === 'healthy') return <Pill tone="green">正常</Pill>;
  if (status === 'error') return <Pill tone="red">异常</Pill>;
  return <Pill>{status || '未使用'}</Pill>;
};

export const RerankerConfigPage: React.FC<{ embedded?: boolean }> = ({ embedded = false }) => {
  const [providers, setProviders] = useState<ProviderItem[]>([]);
  const [settings, setSettings] = useState<any>({});
  const [loading, setLoading] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [fetchingModelsId, setFetchingModelsId] = useState<string | null>(null);
  const [modelCatalog, setModelCatalog] = useState<Record<string, string[]>>({});
  const [globalForm] = Form.useForm();
  const [addChannelOpen, setAddChannelOpen] = useState(false);
  const [addChannelForm] = Form.useForm();

  const [newKeys, setNewKeys] = useState<Record<string, { label: string; api_key: string; daily_quota: number }>>({});
  const [modelEdits, setModelEdits] = useState<Record<string, { base_url: string; default_model: string; timeout_ms: number }>>({});

  const loadData = async () => {
    setLoading(true);
    try {
      const [pResp, sResp] = await Promise.all([
        fetch('/api/admin/providers?provider_type=reranker'),
        fetch('/api/admin/settings'),
      ]);
      const pData: ProviderItem[] = await pResp.json();
      const sData = await sResp.json();
      setProviders(pData);
      setSettings(sData);
      globalForm.setFieldsValue({
        default_reranker_provider: sData.default_reranker_provider || 'jina_reranker',
      });
      const edits: Record<string, { base_url: string; default_model: string; timeout_ms: number }> = {};
      for (const p of pData) {
        edits[p.id] = {
          base_url: p.base_url,
          default_model: p.default_model,
          timeout_ms: p.timeout_ms,
        };
      }
      setModelEdits(edits);

      pData.forEach((p) => {
        fetch(`/api/admin/providers/${p.id}/models`)
          .then((r) => r.json())
          .then((d) => {
            if (Array.isArray(d.models)) {
              setModelCatalog((prev) => ({ ...prev, [p.id]: d.models }));
            }
          })
          .catch(() => {});
      });
    } catch (e: any) {
      message.error(`加载失败: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleFetchModels = async (prov: ProviderItem) => {
    setFetchingModelsId(prov.id);
    try {
      const resp = await fetch(`/api/admin/providers/${prov.id}/models`);
      const data = await resp.json();
      if (Array.isArray(data.models) && data.models.length > 0) {
        setModelCatalog((prev) => ({ ...prev, [prov.id]: data.models }));
        const srcText = data.source === 'remote_api' ? '远程接口' : '内置模型库';
        message.success(`已从 ${srcText} 拉取 ${data.models.length} 个重排模型`);
      }
    } catch (e: any) {
      message.error(`拉取失败: ${e.message}`);
    } finally {
      setFetchingModelsId(null);
    }
  };

  const handleSaveGlobalReranker = async (values: any) => {
    await fetch('/api/admin/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(values),
    });
    message.success('首选重排器已保存');
    loadData();
  };

  const handleSaveProviderParams = async (prov: ProviderItem) => {
    const edit = modelEdits[prov.id];
    if (!edit) return;
    await fetch(`/api/admin/providers/${prov.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(edit),
    });
    message.success(`[${prov.name}] 已保存`);
    loadData();
  };

  const handleToggleProvider = async (prov: ProviderItem, field: 'enabled' | 'use_proxy', val: boolean) => {
    await fetch(`/api/admin/providers/${prov.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [field]: val }),
    });
    loadData();
  };

  const handleAddKeyInline = async (prov: ProviderItem) => {
    const entry = newKeys[prov.id];
    if (!entry || !entry.api_key?.trim()) {
      message.warning('请输入 API Key');
      return;
    }
    const resp = await fetch('/api/admin/keys', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider_id: prov.id,
        label: entry.label || '默认密钥',
        api_key: entry.api_key.trim(),
        daily_quota: entry.daily_quota || 10000,
        weight: 1,
        rpm_limit: 60,
        enabled: true,
      }),
    });
    if (!resp.ok) {
      message.error(`添加失败: HTTP ${resp.status}`);
      return;
    }
    message.success(`已添加密钥`);
    setNewKeys((prev) => ({ ...prev, [prov.id]: { label: '', api_key: '', daily_quota: 10000 } }));
    loadData();
  };

  const handleDeleteKey = async (keyId: string) => {
    await fetch(`/api/admin/keys/${keyId}`, { method: 'DELETE' });
    loadData();
  };

  const handleTestReranker = async (prov: ProviderItem) => {
    setTestingId(prov.id);
    try {
      const resp = await fetch(`/api/admin/providers/${prov.id}/test`, { method: 'POST' });
      const res = await resp.json();
      if (res.status === 'success') {
        message.success(`[${prov.name}] 探活成功 (${res.latency_ms} ms)`);
      } else {
        message.warning(`[${prov.name}] ${res.status}: ${res.error_message || ''}`);
      }
      loadData();
    } catch (e: any) {
      message.error(`探活异常: ${e.message}`);
    } finally {
      setTestingId(null);
    }
  };

  const handleCreateCustomReranker = async (values: any) => {
    const resp = await fetch('/api/admin/providers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...values,
        provider_type: 'reranker',
        category: 'reranker',
      }),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      message.error(err.detail || `创建失败 HTTP ${resp.status}`);
      return;
    }
    message.success(`已新增 [${values.name}]`);
    setAddChannelOpen(false);
    addChannelForm.resetFields();
    loadData();
  };

  /* ---------- 仅用于展示的派生指标，不参与任何业务请求 ---------- */
  const primaryId = settings.default_reranker_provider || '';
  const primaryProv = providers.find((p) => p.id === primaryId) || providers[0];
  const readyCount = providers.filter((p) => p.health_status === 'ready').length;
  const activeKeys = providers.reduce((acc, p) => acc + Number(p.active_key_count || 0), 0);
  const billed = providers.filter((p) => Number(p.total_calls || 0) > 0);
  const billedCalls = billed.reduce((acc, p) => acc + Number(p.total_calls || 0), 0);
  const avgRerankMs = billedCalls
    ? Math.round(
        billed.reduce((acc, p) => acc + Number(p.avg_latency_ms || 0) * Number(p.total_calls || 0), 0) / billedCalls
      )
    : providers.length
    ? Math.round(providers.reduce((acc, p) => acc + Number(p.avg_latency_ms || 0), 0) / providers.length)
    : 0;

  return (
    <div>
      {!embedded && (
        <PageHeader
          icon={<IconSliders size={21} />}
          title="语义重排"
          tags={<Pill tone="accent">{providers.length} 个渠道</Pill>}
          subtitle="精排通道、模型与密钥池。"
          extra={
            <>
              <Button type="primary" icon={<IconPlus size={15} />} onClick={() => setAddChannelOpen(true)}>
                新增渠道
              </Button>
              <Button icon={<IconRefresh size={15} />} onClick={loadData} loading={loading}>
                刷新
              </Button>
            </>
          }
        />
      )}

      <div className="grid cols-3 section-gap">
        <Stat
          label="默认重排模型"
          value={
            <span
              className="truncate"
              style={{ fontSize: 16, fontWeight: 600, letterSpacing: '-0.01em', minWidth: 0, maxWidth: '100%' }}
            >
              {primaryProv?.default_model || '未配置'}
            </span>
          }
          icon={<IconSparkles size={14} />}
          tone="purple"
          hint={primaryProv ? `${primaryProv.name} · 全局首选通道` : '尚未接入重排通道'}
        />
        <Stat
          label="Top-N 截断"
          value={fmtNum(RERANK_TOP_N)}
          suffix="条"
          icon={<IconFilter size={14} />}
          tone="teal"
          hint="每次精排最多送审的融合候选数"
        />
        <Stat
          label="平均重排耗时"
          value={fmtNum(avgRerankMs)}
          suffix="ms"
          icon={<IconClock size={14} />}
          tone="orange"
          hint={billedCalls ? `基于 ${fmtNum(billedCalls)} 次重排调用` : '还没有重排调用记录'}
        />
      </div>

      <div className="grid cols-2 section-gap">
        <Section
          title="首选精排通道"
          subtitle="请求未显式指定 reranker_provider 时优先使用此通道"
          extra={
            <Pill tone={readyCount > 0 ? 'green' : 'orange'}>
              {readyCount}/{providers.length} 在线
            </Pill>
          }
        >
          <Form form={globalForm} layout="vertical" onFinish={handleSaveGlobalReranker}>
            <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
              <Form.Item
                name="default_reranker_provider"
                label="默认重排通道"
                style={{ flex: '1 1 260px', marginBottom: 0 }}
              >
                <Select
                  style={{ width: '100%' }}
                  options={providers.map((p) => ({
                    label: `${p.name} [${p.default_model}] (${p.active_key_count > 0 ? '已配密钥' : '待配密钥'})`,
                    value: p.id,
                  }))}
                />
              </Form.Item>
              <Button type="primary" htmlType="submit" icon={<IconCheck size={15} />}>
                保存首选
              </Button>
            </div>
          </Form>
          <div className="hairline" style={{ margin: '16px 0' }} />
          <KeyValue
            columns={2}
            items={[
              { label: '优先级', value: '请求参数 → 默认通道 → 其余渠道' },
              { label: '可用密钥', value: `${fmtNum(activeKeys)} 个` },
              { label: '当前首选', value: primaryProv ? primaryProv.name : '—' },
              { label: '精排模型', value: <code className="code-inline">{primaryProv?.default_model || '—'}</code> },
            ]}
          />
        </Section>

        <Section
          title="两阶段排序"
          subtitle="RRF 融合 → 语义精排 的约定值"
          extra={<Pill tone="purple">RRF → Rerank</Pill>}
        >
          <KeyValue
            columns={2}
            items={[
              {
                label: 'RRF 融合常数',
                value: <span>k = <strong className="num">{fmtNum(settings.rrf_k ?? 60)}</strong></span>,
              },
              {
                label: '多源重合提权',
                value: <span>× {Number(settings.multi_source_boost ?? 1.45).toFixed(2)}</span>,
              },
              { label: '送审候选', value: `Top ${fmtNum(RERANK_TOP_N)} 条` },
              { label: '远程超时', value: '4.5 s 后放弃打分' },
              { label: '精排打分', value: 'Cross-Encoder relevance' },
              { label: '无 Key 回退', value: '词法相关性加权' },
            ]}
          />
          <div className="tiny faint" style={{ marginTop: 14, lineHeight: 1.6 }}>
            密钥缺失或远程失败时，整批结果自动回退为词法排序，不影响检索主链路。
          </div>
        </Section>
      </div>

      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, margin: '26px 0 14px', flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 15, fontWeight: 600, letterSpacing: '-0.01em' }}>重排渠道</h2>
        <span className="tiny faint">每个渠道独立维护端点、模型、超时与多 Key 密钥池</span>
      </div>

      {providers.length === 0 ? (
        <Section>
          <EmptyState
            icon={<IconSliders size={20} />}
            title="还没有接入重排渠道"
            desc="新增任意兼容 POST /v1/rerank 的端点，即可启用语义精排。"
            action={
              <Button type="primary" icon={<IconPlus size={15} />} onClick={() => setAddChannelOpen(true)}>
                新增渠道
              </Button>
            }
          />
        </Section>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {providers.map((prov) => {
            const edit = modelEdits[prov.id] || {
              base_url: prov.base_url,
              default_model: prov.default_model,
              timeout_ms: prov.timeout_ms,
            };
            const nk = newKeys[prov.id] || { label: '', api_key: '', daily_quota: 10000 };
            const isPrimary = settings.default_reranker_provider === prov.id;
            const provModels = (modelCatalog[prov.id] || []).map((m) => ({ label: m, value: m }));

            return (
              <Section
                key={prov.id}
                title={
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    {prov.name}
                    <code className="code-inline" style={{ fontWeight: 400 }}>{prov.id}</code>
                    {isPrimary ? <Pill tone="accent">首选</Pill> : null}
                  </span>
                }
                subtitle={prov.description || '兼容 /v1/rerank 标准协议的精排端点'}
                extra={
                  <>
                    <Button
                      size="small"
                      icon={<IconDownload size={14} />}
                      loading={fetchingModelsId === prov.id}
                      onClick={() => handleFetchModels(prov)}
                    >
                      拉取模型
                    </Button>
                    <Button
                      size="small"
                      type="primary"
                      ghost
                      icon={<IconZap size={14} />}
                      loading={testingId === prov.id}
                      onClick={() => handleTestReranker(prov)}
                    >
                      测速
                    </Button>
                  </>
                }
              >
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 14,
                    flexWrap: 'wrap',
                    paddingBottom: 14,
                    marginBottom: 16,
                    borderBottom: '1px solid var(--line-soft)',
                  }}
                >
                  {healthPill(prov.health_status)}
                  <span className="tiny faint">
                    密钥 <strong style={{ color: 'var(--text)' }}>{prov.active_key_count}</strong> / {prov.total_key_count}
                  </span>
                  <span className="tiny faint">
                    调用 <strong style={{ color: 'var(--text)' }}>{fmtNum(prov.total_calls)}</strong> 次
                  </span>
                  <span className="tiny faint">
                    成功 <strong style={{ color: 'var(--text)' }}>{fmtNum(prov.success_calls)}</strong> 次
                  </span>
                  <span className="tiny faint">
                    平均 <strong style={{ color: 'var(--text)' }}>{fmtNum(Math.round(prov.avg_latency_ms || 0))}</strong> ms
                  </span>
                  <span style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 18 }}>
                    <span className="tiny faint" style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
                      代理
                      <Switch
                        size="small"
                        checked={Boolean(prov.use_proxy)}
                        onChange={(v) => handleToggleProvider(prov, 'use_proxy', v)}
                      />
                    </span>
                    <span className="tiny faint" style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
                      启用
                      <Switch
                        size="small"
                        checked={Boolean(prov.enabled)}
                        onChange={(v) => handleToggleProvider(prov, 'enabled', v)}
                      />
                    </span>
                  </span>
                </div>

                <Row gutter={[10, 10]}>
                  <Col xs={24} md={9}>
                    <div className="tiny faint" style={{ marginBottom: 5 }}>Endpoint</div>
                    <Input
                      value={edit.base_url}
                      onChange={(e) =>
                        setModelEdits((prev) => ({
                          ...prev,
                          [prov.id]: { ...edit, base_url: e.target.value },
                        }))
                      }
                    />
                  </Col>
                  <Col xs={24} md={9}>
                    <div className="tiny faint" style={{ marginBottom: 5 }}>重排模型</div>
                    <AutoComplete
                      style={{ width: '100%' }}
                      value={edit.default_model}
                      options={provModels}
                      onChange={(val) =>
                        setModelEdits((prev) => ({
                          ...prev,
                          [prov.id]: { ...edit, default_model: val },
                        }))
                      }
                      placeholder="下拉选择或输入重排模型"
                    />
                  </Col>
                  <Col xs={12} md={3}>
                    <div className="tiny faint" style={{ marginBottom: 5 }}>超时</div>
                    <InputNumber
                      style={{ width: '100%' }}
                      value={edit.timeout_ms}
                      step={500}
                      addonAfter="ms"
                      onChange={(v) =>
                        setModelEdits((prev) => ({
                          ...prev,
                          [prov.id]: { ...edit, timeout_ms: Number(v || 5000) },
                        }))
                      }
                    />
                  </Col>
                  <Col xs={12} md={3}>
                    <div className="tiny faint" style={{ marginBottom: 5 }} aria-hidden="true">&nbsp;</div>
                    <Button block icon={<IconCheck size={14} />} onClick={() => handleSaveProviderParams(prov)}>
                      保存
                    </Button>
                  </Col>
                </Row>

                <div style={{ marginTop: 20, paddingTop: 16, borderTop: '1px solid var(--line-soft)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
                    <span style={{ fontSize: 12.5, fontWeight: 600, color: 'var(--text)' }}>密钥池</span>
                    <Pill tone={prov.active_key_count > 0 ? 'green' : 'orange'}>
                      {prov.active_key_count} 可用 / {prov.total_key_count} 个
                    </Pill>
                    <span className="tiny faint">多 Key 轮询 · 每日配额自动计数</span>
                  </div>

                  <div
                    style={{
                      padding: '12px 12px 14px',
                      borderRadius: 12,
                      background: 'var(--surface-2)',
                      marginBottom: prov.keys.length > 0 ? 14 : 0,
                    }}
                  >
                    <Row gutter={[10, 10]} align="middle">
                      <Col xs={24} md={5}>
                        <Input
                          size="small"
                          placeholder="备注，如 主力密钥"
                          value={nk.label}
                          onChange={(e) =>
                            setNewKeys((prev) => ({ ...prev, [prov.id]: { ...nk, label: e.target.value } }))
                          }
                        />
                      </Col>
                      <Col xs={24} md={11}>
                        <Input.Password
                          size="small"
                          placeholder="粘贴 API Key"
                          value={nk.api_key}
                          onChange={(e) =>
                            setNewKeys((prev) => ({ ...prev, [prov.id]: { ...nk, api_key: e.target.value } }))
                          }
                        />
                      </Col>
                      <Col xs={12} md={5}>
                        <InputNumber
                          size="small"
                          style={{ width: '100%' }}
                          value={nk.daily_quota}
                          addonAfter="次/日"
                          onChange={(v) =>
                            setNewKeys((prev) => ({ ...prev, [prov.id]: { ...nk, daily_quota: Number(v || 10000) } }))
                          }
                        />
                      </Col>
                      <Col xs={12} md={3}>
                        <Button
                          size="small"
                          type="primary"
                          block
                          icon={<IconPlus size={14} />}
                          onClick={() => handleAddKeyInline(prov)}
                        >
                          添加
                        </Button>
                      </Col>
                    </Row>
                  </div>

                  {prov.keys.length > 0 ? (
                    <Table
                      rowKey="id"
                      size="small"
                      pagination={false}
                      dataSource={prov.keys}
                      scroll={{ x: 720 }}
                      columns={[
                        {
                          title: '备注',
                          dataIndex: 'label',
                          width: 130,
                          ellipsis: true,
                          render: (v: string) => <span style={{ fontWeight: 500 }}>{v || '默认密钥'}</span>,
                        },
                        {
                          title: '密钥',
                          dataIndex: 'api_key_masked',
                          render: (v: string) => <code className="code-inline">{v}</code>,
                        },
                        {
                          title: '今日 / 上限',
                          width: 130,
                          align: 'right',
                          render: (_, k: ApiKeyItem) => (
                            <span className="num small">
                              {fmtNum(k.used_today)} <span className="faint">/ {fmtNum(k.daily_quota)}</span>
                            </span>
                          ),
                        },
                        {
                          title: '累计',
                          dataIndex: 'total_used',
                          width: 90,
                          align: 'right',
                          render: (v: number) => <span className="num small">{fmtNum(v)}</span>,
                        },
                        {
                          title: '最近延迟',
                          dataIndex: 'last_latency_ms',
                          width: 100,
                          align: 'right',
                          render: (v: number) => (
                            <span className="num small faint">{v ? `${fmtNum(v)} ms` : '—'}</span>
                          ),
                        },
                        {
                          title: '状态',
                          dataIndex: 'last_status',
                          width: 100,
                          render: (v: string) => keyStatusPill(v),
                        },
                        {
                          title: '',
                          width: 56,
                          align: 'right',
                          render: (_, k: ApiKeyItem) => (
                            <Popconfirm title="确认删除？" onConfirm={() => handleDeleteKey(k.id)}>
                              <Button size="small" type="text" danger icon={<IconTrash size={14} />} />
                            </Popconfirm>
                          ),
                        },
                      ]}
                    />
                  ) : (
                    <div className="tiny faint" style={{ padding: '4px 0' }}>
                      尚未配置密钥，该渠道暂不可用，重排会自动回退到其他渠道或词法排序。
                    </div>
                  )}
                </div>
              </Section>
            );
          })}
        </div>
      )}

      <Modal
        title="新增自定义 Rerank 渠道"
        open={addChannelOpen}
        onCancel={() => setAddChannelOpen(false)}
        onOk={() => addChannelForm.submit()}
        okText="创建渠道"
        width={560}
      >
        <div style={{ fontSize: 12.5, color: 'var(--text-2)', marginBottom: 16, lineHeight: 1.6 }}>
          兼容 <code className="code-inline">POST /v1/rerank</code> 的 Xinference、vLLM、OneAPI 等服务均可直接接入。
        </div>
        <Form form={addChannelForm} layout="vertical" onFinish={handleCreateCustomReranker}>
          <Row gutter={14}>
            <Col span={12}>
              <Form.Item name="id" label="渠道 ID" rules={[{ required: true }]}>
                <Input placeholder="xinference_rerank" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="name" label="名称" rules={[{ required: true }]}>
                <Input placeholder="本地 BGE 重排" />
              </Form.Item>
            </Col>
            <Col span={24}>
              <Form.Item name="base_url" label="Endpoint URL" rules={[{ required: true }]}>
                <Input placeholder="https://api.siliconflow.cn/v1/rerank" />
              </Form.Item>
            </Col>
            <Col span={24}>
              <Form.Item name="default_model" label="默认模型" rules={[{ required: true }]}>
                <Input placeholder="BAAI/bge-reranker-v2-m3" />
              </Form.Item>
            </Col>
            <Col span={24}>
              <Form.Item name="api_key" label="初始 API Key" extra="可留空，创建后在渠道卡片里补配">
                <Input.Password placeholder="sk-..." />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="use_proxy" label="走代理" valuePropName="checked" initialValue={false}>
                <Switch />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </div>
  );
};
