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
import { EmptyState, PageHeader, Pill, Section } from '../components/ui';
import {
  IconBot,
  IconCheck,
  IconClock,
  IconDownload,
  IconPlus,
  IconRefresh,
  IconRoute,
  IconTrash,
  IconZap,
} from '../components/icons';
import { fmtNum, fmtTime } from '../utils/format';
import type { ApiKeyItem, ProviderItem } from '../api';

/* 渠道健康状态 → 状态色 Pill */
const healthPill = (status?: string) => {
  if (status === 'ready') return <Pill tone="green">在线可用</Pill>;
  if (status === 'missing_key') return <Pill tone="orange">待配密钥</Pill>;
  if (status === 'circuit_open') return <Pill tone="red">熔断保护</Pill>;
  return <Pill>已停用</Pill>;
};

const keyStatusPill = (status?: string) => {
  if (status === 'healthy') return <Pill tone="green">健康</Pill>;
  if (status === 'error') return <Pill tone="red">异常</Pill>;
  return <Pill>待使用</Pill>;
};

/* 表单小标签，替代 Input 的 addonBefore 视觉噪音 */
const Field: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div style={{ minWidth: 0 }}>
    <div className="tiny faint" style={{ marginBottom: 5, fontWeight: 500 }}>
      {label}
    </div>
    {children}
  </div>
);

/* 渠道内的字段分组：左侧小标题 + 右侧控件，窄屏自然折行 */
const Group: React.FC<{ label: string; hint?: string; children: React.ReactNode }> = ({ label, hint, children }) => (
  <div style={{ display: 'flex', gap: 18, alignItems: 'flex-start', flexWrap: 'wrap' }}>
    <div style={{ width: 96, flex: 'none', paddingTop: 1 }}>
      <div style={{ fontSize: 12.5, fontWeight: 600, letterSpacing: '-0.005em' }}>{label}</div>
      {hint ? (
        <div className="tiny faint" style={{ marginTop: 2, lineHeight: 1.45 }}>
          {hint}
        </div>
      ) : null}
    </div>
    <div style={{ flex: '1 1 380px', minWidth: 0 }}>{children}</div>
  </div>
);

export const LlmConfigPage: React.FC<{ embedded?: boolean }> = ({ embedded = false }) => {
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
        fetch('/api/admin/providers?provider_type=llm'),
        fetch('/api/admin/settings'),
      ]);
      const pData: ProviderItem[] = await pResp.json();
      const sData = await sResp.json();
      setProviders(pData);
      setSettings(sData);
      globalForm.setFieldsValue({
        default_llm_provider: sData.default_llm_provider || 'siliconflow',
        default_llm_model: sData.default_llm_model || 'deepseek-ai/DeepSeek-V3',
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

      // Preload preset/remote models for each provider
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
      // 使用页面上当前填写的 Base URL / Key（未保存也可直接拉取）
      const edit = modelEdits[prov.id];
      const nk = newKeys[prov.id];
      const params = new URLSearchParams();
      if (edit?.base_url) params.set('base_url', edit.base_url);
      if (nk?.api_key) params.set('api_key', nk.api_key);
      const qs = params.toString();
      const resp = await fetch(`/api/admin/providers/${prov.id}/models${qs ? `?${qs}` : ''}`);
      const data = await resp.json();
      if (Array.isArray(data.models) && data.models.length > 0) {
        setModelCatalog((prev) => ({ ...prev, [prov.id]: data.models }));
        const srcText =
          data.source === 'remote_api' ? '远程 /v1/models 接口' : data.source === 'preset_fallback' ? '内置模型库（远程拉取失败）' : '内置模型库';
        if (data.source === 'remote_api') {
          message.success(`已从 ${srcText} 拉取 ${data.models.length} 个可选模型`);
        } else {
          message.warning(`${srcText}（${data.note || '未配置 Key 或远程不可达'}），已载入 ${data.models.length} 个预设模型`);
        }
      } else {
        message.warning(`未获取到模型列表：${data.note || '空列表'}`);
      }
    } catch (e: any) {
      message.error(`拉取模型列表失败: ${e.message}`);
    } finally {
      setFetchingModelsId(null);
    }
  };

  const handleSaveGlobalLlm = async (values: any) => {
    await fetch('/api/admin/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(values),
    });
    message.success('全局首选大模型已保存');
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

  const handleTestLlm = async (prov: ProviderItem) => {
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
      message.error(`探活失败: ${e.message}`);
    } finally {
      setTestingId(null);
    }
  };

  const handleCreateCustomLlm = async (values: any) => {
    const resp = await fetch('/api/admin/providers', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...values,
        provider_type: 'llm',
        category: 'llm',
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

  const activeGlobalProv = Form.useWatch('default_llm_provider', globalForm) || settings.default_llm_provider || 'siliconflow';
  const globalModelOptions = (modelCatalog[activeGlobalProv] || []).map((m) => ({ label: m, value: m }));
  const savedProv = providers.find((p) => p.id === settings.default_llm_provider);
  const routerProvName =
    providers.find((p) => p.id === settings.ai_router_provider)?.name || settings.ai_router_provider || '';

  return (
    <div>
      {!embedded && (
        <PageHeader
          icon={<IconBot size={21} />}
          title="大模型配置"
          subtitle="默认模型、LLM 渠道与多 Key 轮换。"
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

      <Section
        title="当前默认模型"
        subtitle="全局兜底模型；单个渠道仍可覆盖自己的默认模型"
        extra={savedProv ? healthPill(savedProv.health_status) : loading ? <Pill>加载中</Pill> : <Pill>未匹配渠道</Pill>}
        gap
      >
        <div style={{ display: 'flex', gap: 28, alignItems: 'flex-start', flexWrap: 'wrap' }}>
          <div style={{ flex: '1 1 320px', minWidth: 0 }}>
            <div
              style={{
                fontSize: 22,
                fontWeight: 700,
                letterSpacing: '-0.03em',
                lineHeight: 1.25,
                wordBreak: 'break-word',
              }}
            >
              {settings.default_llm_model || savedProv?.default_model || '尚未设置默认模型'}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 10, flexWrap: 'wrap' }}>
              <Pill tone="accent">{savedProv?.name || settings.default_llm_provider || '未指定服务商'}</Pill>
              <span className="tiny faint" style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                <IconClock size={13} /> 平均延迟 {Math.round(savedProv?.avg_latency_ms || 0)} ms
              </span>
              <span className="tiny faint num">累计调用 {fmtNum(savedProv?.total_calls || 0)} 次</span>
              {savedProv && savedProv.total_calls > 0 ? (
                <span className="tiny faint num">
                  成功率 {((savedProv.success_calls / savedProv.total_calls) * 100).toFixed(1)}%
                </span>
              ) : null}
            </div>

            <hr className="hairline" style={{ margin: '16px 0 12px' }} />

            <div style={{ display: 'flex', gap: 30, flexWrap: 'wrap' }}>
              <div>
                <div className="tiny faint" style={{ marginBottom: 2 }}>
                  路由小模型
                </div>
                <div className="small" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <IconRoute size={13} style={{ color: 'var(--text-3)' }} />
                  {settings.ai_router_model || '未设置'}
                </div>
              </div>
              <div>
                <div className="tiny faint" style={{ marginBottom: 2 }}>
                  路由服务商
                </div>
                <div className="small">{routerProvName || '未设置'}</div>
              </div>
              <div>
                <div className="tiny faint" style={{ marginBottom: 2 }}>
                  路由模式
                </div>
                <div className="small">
                  {settings.router_mode ? <Pill tone="teal">{settings.router_mode}</Pill> : '—'}
                </div>
              </div>
            </div>
          </div>

          <div style={{ flex: '0 1 330px', minWidth: 250 }}>
            <Form
              form={globalForm}
              layout="vertical"
              onFinish={handleSaveGlobalLlm}
              onValuesChange={(changed) => {
                if (changed.default_llm_provider) {
                  const p = providers.find((x) => x.id === changed.default_llm_provider);
                  if (p?.default_model) {
                    globalForm.setFieldValue('default_llm_model', p.default_model);
                  }
                }
              }}
            >
              <Form.Item name="default_llm_provider" label="全局首选服务商" style={{ marginBottom: 14 }}>
                <Select
                  style={{ width: '100%' }}
                  options={providers.map((p) => ({
                    label: `${p.name} · ${p.active_key_count > 0 ? '已配 Key' : '待配 Key'}`,
                    value: p.id,
                  }))}
                />
              </Form.Item>
              <Form.Item name="default_llm_model" label="首选模型" style={{ marginBottom: 14 }}>
                <AutoComplete
                  style={{ width: '100%' }}
                  options={globalModelOptions}
                  placeholder="下拉选择或输入模型名"
                  filterOption={(inputValue, option) =>
                    (option?.value ?? '').toLowerCase().includes(inputValue.toLowerCase())
                  }
                />
              </Form.Item>
              <Button type="primary" htmlType="submit" icon={<IconCheck size={15} />}>
                保存首选
              </Button>
            </Form>
          </div>
        </div>
      </Section>

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          margin: '26px 0 12px',
          flexWrap: 'wrap',
        }}
      >
        <span style={{ fontSize: 15, fontWeight: 650, letterSpacing: '-0.02em' }}>LLM 渠道</span>
        <Pill>{providers.length} 个</Pill>
        <span className="tiny faint" style={{ marginLeft: 'auto' }}>
          每个渠道支持多把 Key 与独立代理
        </span>
      </div>

      {providers.length === 0 ? (
        <Section>
          {loading ? (
            <div className="empty">
              <div className="empty-desc">正在加载 LLM 渠道…</div>
            </div>
          ) : (
            <EmptyState
              icon={<IconBot size={22} />}
              title="还没有 LLM 渠道"
              desc="新增一个 OpenAI 兼容渠道（DashScope / vLLM / Ollama 等）即可开始使用。"
              action={
                <Button type="primary" icon={<IconPlus size={15} />} onClick={() => setAddChannelOpen(true)}>
                  新增渠道
                </Button>
              }
            />
          )}
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
          const isPrimary = settings.default_llm_provider === prov.id;
          const provModels = (modelCatalog[prov.id] || []).map((m) => ({ label: m, value: m }));

          return (
            <Section
              key={prov.id}
              title={
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <span>{prov.name}</span>
                  <code className="code-inline" style={{ fontWeight: 400 }}>
                    {prov.id}
                  </code>
                  {isPrimary ? <Pill tone="accent">全局首选</Pill> : null}
                  {healthPill(prov.health_status)}
                  <Pill>Key {prov.active_key_count}</Pill>
                </span>
              }
              subtitle={`调用 ${fmtNum(prov.total_calls)} 次 · 成功 ${fmtNum(prov.success_calls)} 次 · 平均 ${Math.round(
                prov.avg_latency_ms || 0,
              )} ms`}
              extra={
                <Button
                  size="small"
                  icon={<IconZap size={14} />}
                  loading={testingId === prov.id}
                  onClick={() => handleTestLlm(prov)}
                >
                  测速
                </Button>
              }
            >
              <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
                <Group label="基础参数" hint="连接 · 模型 · 超时">
                  <Row gutter={[14, 14]}>
                    <Col xs={24} md={10}>
                      <Field label="Base URL">
                        <Input
                          value={edit.base_url}
                          placeholder="https://api.example.com/v1"
                          onChange={(e) =>
                            setModelEdits((prev) => ({
                              ...prev,
                              [prov.id]: { ...edit, base_url: e.target.value },
                            }))
                          }
                        />
                      </Field>
                    </Col>
                    <Col xs={24} md={9}>
                      <Field label="默认模型">
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
                          filterOption={(input, option) => {
                            const val = (option?.value ?? '').toLowerCase();
                            const typed = input.toLowerCase();
                            // 框内还是已选中的值时展示全部选项，真正输入新内容时才过滤
                            if (typed === (edit.default_model || '').toLowerCase()) return true;
                            return val.includes(typed);
                          }}
                          placeholder="可直接输入模型 ID，或点「拉取模型」后下拉选择"
                        />
                      </Field>
                    </Col>
                    <Col xs={24} md={5}>
                      <Field label="超时">
                        <InputNumber
                          style={{ width: '100%' }}
                          value={edit.timeout_ms}
                          step={1000}
                          addonAfter="ms"
                          onChange={(v) =>
                            setModelEdits((prev) => ({
                              ...prev,
                              [prov.id]: { ...edit, timeout_ms: Number(v || 30000) },
                            }))
                          }
                        />
                      </Field>
                    </Col>
                  </Row>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
                    <span className="tiny faint">模型可直接输入 ID，也可从上游 /v1/models 拉取</span>
                    <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, flexWrap: 'wrap' }}>
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
                        icon={<IconCheck size={14} />}
                        onClick={() => handleSaveProviderParams(prov)}
                      >
                        保存参数
                      </Button>
                    </div>
                  </div>
                </Group>

                <hr className="hairline" />

                <Group label="密钥" hint="多 Key 轮换">
                  <Row gutter={[10, 10]} align="bottom">
                    <Col xs={24} md={6}>
                      <Field label="备注">
                        <Input
                          placeholder="备注（可选）"
                          value={nk.label}
                          onChange={(e) =>
                            setNewKeys((prev) => ({ ...prev, [prov.id]: { ...nk, label: e.target.value } }))
                          }
                        />
                      </Field>
                    </Col>
                    <Col xs={24} md={10}>
                      <Field label="API Key">
                        <Input.Password
                          placeholder="粘贴 API Key（sk-...）"
                          value={nk.api_key}
                          onChange={(e) =>
                            setNewKeys((prev) => ({ ...prev, [prov.id]: { ...nk, api_key: e.target.value } }))
                          }
                        />
                      </Field>
                    </Col>
                    <Col xs={24} md={5}>
                      <Field label="每日上限">
                        <InputNumber
                          style={{ width: '100%' }}
                          value={nk.daily_quota}
                          onChange={(v) =>
                            setNewKeys((prev) => ({ ...prev, [prov.id]: { ...nk, daily_quota: Number(v || 10000) } }))
                          }
                        />
                      </Field>
                    </Col>
                    <Col xs={24} md={3}>
                      <Button block icon={<IconPlus size={14} />} onClick={() => handleAddKeyInline(prov)}>
                        加 Key
                      </Button>
                    </Col>
                  </Row>

                  {prov.keys.length > 0 ? (
                    <Table
                      rowKey="id"
                      size="small"
                      pagination={false}
                      dataSource={prov.keys}
                      style={{ marginTop: 14 }}
                      scroll={{ x: 760 }}
                      columns={[
                        {
                          title: '备注',
                          dataIndex: 'label',
                          width: 150,
                          render: (v: string, k: ApiKeyItem) => (
                            <div style={{ minWidth: 0 }}>
                              <div className="truncate" style={{ fontWeight: 500 }}>
                                {v || '默认密钥'}
                              </div>
                              <div className="tiny faint">
                                {k.last_used_at ? `最后使用 ${fmtTime(k.last_used_at)}` : '尚未使用'}
                              </div>
                            </div>
                          ),
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
                          title: '累计调用',
                          dataIndex: 'total_used',
                          width: 100,
                          align: 'right',
                          render: (v: number) => <span className="num small">{fmtNum(v)}</span>,
                        },
                        {
                          title: '状态',
                          width: 130,
                          render: (_, k: ApiKeyItem) => (
                            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                              {keyStatusPill(k.last_status)}
                              {k.last_latency_ms ? (
                                <span className="tiny faint num">{k.last_latency_ms}ms</span>
                              ) : null}
                            </span>
                          ),
                        },
                        {
                          title: '',
                          width: 56,
                          align: 'right',
                          render: (_, k: ApiKeyItem) => (
                            <Popconfirm
                              title="确认删除这把 Key？"
                              okText="删除"
                              cancelText="取消"
                              okButtonProps={{ danger: true }}
                              onConfirm={() => handleDeleteKey(k.id)}
                            >
                              <Button size="small" type="text" danger icon={<IconTrash size={14} />} />
                            </Popconfirm>
                          ),
                        },
                      ]}
                    />
                  ) : (
                    <div className="tiny faint" style={{ marginTop: 12 }}>
                      尚未添加密钥，填写后点「加 Key」即可启用该渠道。
                    </div>
                  )}
                </Group>

                <hr className="hairline" />

                <Group label="代理与开关" hint="出网 · 启停">
                  <div style={{ display: 'flex', gap: 36, flexWrap: 'wrap' }}>
                    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                      <Switch
                        checked={Boolean(prov.enabled)}
                        onChange={(v) => handleToggleProvider(prov, 'enabled', v)}
                      />
                      <div>
                        <div className="small" style={{ fontWeight: 600 }}>
                          启用渠道
                        </div>
                        <div className="tiny faint">停用后不参与默认模型与自动路由</div>
                      </div>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
                      <Switch
                        checked={Boolean(prov.use_proxy)}
                        onChange={(v) => handleToggleProvider(prov, 'use_proxy', v)}
                      />
                      <div>
                        <div className="small" style={{ fontWeight: 600 }}>
                          走代理
                        </div>
                        <div className="tiny faint" style={{ wordBreak: 'break-all' }}>
                          {prov.custom_proxy || '跟随全局代理设置'}
                        </div>
                      </div>
                    </div>
                  </div>
                </Group>
              </div>
            </Section>
          );
        })}
      </div>
      )}

      <Modal
        title="新增自定义大模型渠道"
        open={addChannelOpen}
        onCancel={() => setAddChannelOpen(false)}
        onOk={() => addChannelForm.submit()}
        okText="创建渠道"
        width={600}
      >
        <div style={{ fontSize: 12.5, color: 'var(--text-2)', marginBottom: 16, lineHeight: 1.5 }}>
          任意 OpenAI 兼容服务（DashScope / vLLM / Ollama 等），填写 Base URL 与默认模型即可接入。
        </div>
        <Form form={addChannelForm} layout="vertical" onFinish={handleCreateCustomLlm}>
          <Row gutter={14}>
            <Col span={10}>
              <Form.Item name="id" label="渠道 ID" rules={[{ required: true }]}>
                <Input placeholder="dashscope" />
              </Form.Item>
            </Col>
            <Col span={14}>
              <Form.Item name="name" label="名称" rules={[{ required: true }]}>
                <Input placeholder="阿里云百炼" />
              </Form.Item>
            </Col>
            <Col span={24}>
              <Form.Item name="base_url" label="Base URL" rules={[{ required: true }]}>
                <Input placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1" />
              </Form.Item>
            </Col>
            <Col span={14}>
              <Form.Item name="default_model" label="默认模型" rules={[{ required: true }]}>
                <Input placeholder="qwen-max" />
              </Form.Item>
            </Col>
            <Col span={10}>
              <Form.Item name="api_key" label="初始 API Key">
                <Input.Password placeholder="sk-..." />
              </Form.Item>
            </Col>
            <Col span={24}>
              <Form.Item
                name="use_proxy"
                label="走代理"
                valuePropName="checked"
                initialValue={false}
                extra="开启后经全局代理出网，适合需要代理的海外服务"
                style={{ marginBottom: 0 }}
              >
                <Switch />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </div>
  );
};
