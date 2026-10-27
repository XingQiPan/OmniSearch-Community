import React, { useEffect, useState } from 'react';
import {
  AutoComplete,
  Button,
  Col,
  Form,
  Input,
  InputNumber,
  Row,
  Segmented,
  Select,
  Switch,
  message,
} from 'antd';
import { EmptyState, KeyValue, PageHeader, Pill, Section } from '../components/ui';
import {
  IconCheck,
  IconDownload,
  IconFilter,
  IconGlobe,
  IconKey,
  IconLayers,
  IconRefresh,
  IconRoute,
  IconSearch,
  IconShield,
  IconSliders,
  IconSparkles,
  IconThunderbolt,
  IconZap,
} from '../components/icons';
import type { ProviderItem, RouteGroupItem } from '../api';
import { fmtNum } from '../utils/format';

const MODE_META: Record<string, { label: string; desc: string }> = {
  rule: { label: '极速规则', desc: '关键词规则命中意图，0 ms 额外开销，无外部依赖。' },
  jev: { label: 'Jev 决策模型', desc: 'TypeSafe System One 类型化决策，毫秒级返回校准概率分布与置信度。' },
  ai: { label: 'AI 大模型', desc: '由指定大模型判断意图，最灵活，但每次判定会多一次 LLM 调用。' },
};

const asList = (value: any): string[] => {
  if (Array.isArray(value)) return value;
  if (typeof value === 'string' && value.trim()) return value.split(',').map((s) => s.trim()).filter(Boolean);
  return [];
};

const SubHead: React.FC<{
  icon?: React.ReactNode;
  title: React.ReactNode;
  hint?: React.ReactNode;
  extra?: React.ReactNode;
}> = ({ icon, title, hint, extra }) => (
  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
    {icon ? <span style={{ display: 'inline-flex', color: 'var(--text-3)' }}>{icon}</span> : null}
    <span className="small strong">{title}</span>
    {hint ? <span className="tiny faint">{hint}</span> : null}
    {extra ? <span style={{ marginLeft: 'auto' }}>{extra}</span> : null}
  </div>
);

const SwitchRow: React.FC<{
  icon?: React.ReactNode;
  label: React.ReactNode;
  desc?: React.ReactNode;
  control: React.ReactNode;
}> = ({ icon, label, desc, control }) => (
  <div className="list-row" style={{ padding: '11px 0' }}>
    {icon ? <span style={{ display: 'inline-flex', color: 'var(--text-3)' }}>{icon}</span> : null}
    <div style={{ minWidth: 0, flex: 1 }}>
      <div className="small" style={{ fontWeight: 500 }}>
        {label}
      </div>
      {desc ? <div className="tiny faint">{desc}</div> : null}
    </div>
    {control}
  </div>
);

export const RoutingStudio: React.FC<{ onManageKeys: (providerId: string) => void }> = ({ onManageKeys }) => {
  const [routes, setRoutes] = useState<RouteGroupItem[]>([]);
  const [searchProviders, setSearchProviders] = useState<ProviderItem[]>([]);
  const [llmProviders, setLlmProviders] = useState<ProviderItem[]>([]);
  const [llmModelCatalog, setLlmModelCatalog] = useState<Record<string, string[]>>({});
  const [fetchingLlmModels, setFetchingLlmModels] = useState(false);
  const [settings, setSettings] = useState<any>({});
  const [routerMode, setRouterMode] = useState<'rule' | 'jev' | 'ai'>('rule');
  const [settingsForm] = Form.useForm();
  const [routerForm] = Form.useForm();
  const [loading, setLoading] = useState(false);

  // Router live test state
  const [testQuery, setTestQuery] = useState('DeepSeek R1 论文与训练架构对比');
  const [testingRouter, setTestingRouter] = useState(false);
  const [testResult, setTestResult] = useState<any>(null);

  // 仅用于左侧列表的选中态（纯视觉状态，不参与任何请求）
  const [activeRouteId, setActiveRouteId] = useState('');

  const loadAll = async () => {
    setLoading(true);
    try {
      const [rResp, pResp, lResp, sResp] = await Promise.all([
        fetch('/api/admin/routes'),
        fetch('/api/admin/providers?provider_type=search'),
        fetch('/api/admin/providers?provider_type=llm'),
        fetch('/api/admin/settings'),
      ]);
      const rData = await rResp.json();
      const pData = await pResp.json();
      const lData = await lResp.json();
      const sData = await sResp.json();
      setRoutes(rData);
      setSearchProviders(pData);
      setLlmProviders(lData);
      setSettings(sData);
      lData.forEach((lp: ProviderItem) => {
        fetch(`/api/admin/providers/${lp.id}/models`)
          .then((r) => r.json())
          .then((d) => {
            if (Array.isArray(d.models)) {
              setLlmModelCatalog((prev) => ({ ...prev, [lp.id]: d.models }));
            }
          })
          .catch(() => {});
      });
      const mode = sData.router_mode || 'rule';
      setRouterMode(mode);
      settingsForm.setFieldsValue(sData);
      routerForm.setFieldsValue({
        router_mode: mode,
        jev_api_url:
          !sData.jev_api_url || sData.jev_api_url.includes('jina.ai/v1/embeddings')
            ? 'https://api.typesafe.ai/v1/systemone'
            : sData.jev_api_url,
        jev_api_key: sData.jev_api_key || '',
        jev_model:
          !sData.jev_model || sData.jev_model === 'jina-embeddings-v3'
            ? 'jev-1.13.0'
            : sData.jev_model,
        jev_confidence_threshold: sData.jev_confidence_threshold ?? 0.45,
        jev_timeout_ms: sData.jev_timeout_ms || 4000,
        ai_router_provider: sData.ai_router_provider || 'siliconflow',
        ai_router_model: sData.ai_router_model || 'deepseek-ai/DeepSeek-V3',
        ai_router_timeout_ms: sData.ai_router_timeout_ms || 6000,
      });
    } catch (e: any) {
      message.error(`加载路由与网关策略失败: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAll();
  }, []);

  const handleSaveRoute = async (group: RouteGroupItem) => {
    await fetch(`/api/admin/routes/${group.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        engines: group.engines,
        fallback_engines: group.fallback_engines,
        timeout_ms: group.timeout_ms,
        top_k: group.top_k,
        enable_rerank: Boolean(group.enable_rerank),
        scrape_top_n: group.scrape_top_n,
      }),
    });
    message.success(`路由分组 [${group.name}] 策略已保存`);
    loadAll();
  };

  const handleUpdateRouteField = (id: string, field: string, val: any) => {
    setRoutes((prev) => prev.map((r) => (r.id === id ? { ...r, [field]: val } : r)));
  };

  const handleSaveRouterEngine = async (values: any) => {
    await fetch('/api/admin/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(values),
    });
    message.success(`智能语义路由引擎配置已保存 (当前模式: ${values.router_mode.toUpperCase()})`);
    loadAll();
  };

  const handleTestRouter = async () => {
    if (!testQuery.trim()) {
      message.warning('请输入测试查询词');
      return;
    }
    setTestingRouter(true);
    try {
      // Save current form values first so test uses latest inputs
      const curVals = routerForm.getFieldsValue();
      await fetch('/api/admin/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(curVals),
      });
      const resp = await fetch(
        `/api/admin/router/test?query=${encodeURIComponent(testQuery.trim())}&mode=${encodeURIComponent(curVals.router_mode || routerMode)}`,
        { method: 'POST' }
      );
      const data = await resp.json();
      setTestResult(data);
      message.success(`路由判定完成: 命中 [${data.resolved_route?.toUpperCase()}]`);
    } catch (e: any) {
      message.error(`路由测试失败: ${e.message}`);
    } finally {
      setTestingRouter(false);
    }
  };

  const handleSaveGlobalSettings = async (values: any) => {
    await fetch('/api/admin/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(values),
    });
    message.success('全局网关融合、缓存与熔断策略已保存');
    loadAll();
  };

  /** 勾选 / 取消勾选引擎池里的某个渠道（复用既有的分组字段更新逻辑） */
  const toggleEngine = (group: RouteGroupItem, field: 'engines' | 'fallback_engines', engineId: string) => {
    const current: string[] = group[field] || [];
    const next = current.includes(engineId) ? current.filter((id) => id !== engineId) : [...current, engineId];
    handleUpdateRouteField(group.id, field, next);
  };

  const activeGroup = routes.find((r) => r.id === activeRouteId) || routes[0];
  const maxWeight = Math.max(1, ...searchProviders.map((p) => Number(p.weight || 1)));
  const sharedEngineIds = activeGroup
    ? Array.from(new Set([...(activeGroup.engines || []), ...(activeGroup.fallback_engines || [])]))
    : [];
  const modeMeta = MODE_META[routerMode] || MODE_META.rule;

  return (
    <div>
      <PageHeader
        icon={<IconRoute size={21} />}
        title="路由与融合"
        tags={<Pill tone="accent">{routes.length} 个路由组</Pill>}
        subtitle="意图路由、引擎池与 RRF 融合参数。"
        extra={
          <>
            <Button icon={<IconRefresh size={15} />} onClick={loadAll} loading={loading}>
              刷新
            </Button>
            <Button
              type="primary"
              icon={<IconCheck size={15} />}
              title="保存当前选中的路由分组"
              disabled={!activeGroup}
              onClick={() => activeGroup && handleSaveRoute(activeGroup)}
            >
              保存
            </Button>
          </>
        }
      />

      <Form
        form={routerForm}
        layout="vertical"
        onFinish={handleSaveRouterEngine}
        onValuesChange={(changed) => {
          if (changed.router_mode) setRouterMode(changed.router_mode);
          if (changed.ai_router_provider) {
            const found = llmProviders.find((p) => p.id === changed.ai_router_provider);
            if (found && found.default_model) {
              routerForm.setFieldValue('ai_router_model', found.default_model);
            }
          }
        }}
      >
        <Section
          title="命中测试"
          subtitle="输入 query 立即验证当前决策引擎会落到哪个路由组（测试前会先落库当前表单值）"
          extra={<Pill tone="accent">{modeMeta.label}</Pill>}
          gap
        >
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <Input
              value={testQuery}
              onChange={(e) => setTestQuery(e.target.value)}
              placeholder="输入任意测试 Query 验证当前路由器判断结果..."
              prefix={<IconSearch size={15} style={{ color: 'var(--text-3)' }} />}
              style={{ flex: '1 1 300px', maxWidth: 560 }}
            />
            <Button
              type="primary"
              icon={<IconThunderbolt size={15} />}
              loading={testingRouter}
              onClick={handleTestRouter}
            >
              测试命中
            </Button>
            <span className="tiny faint">结果只做判定，不触发真实检索</span>
          </div>

          {testResult ? (
            <div style={{ marginTop: 14, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <Pill tone="accent">命中 {String(testResult.resolved_route || '—').toUpperCase()}</Pill>
              {testResult.meta?.engine ? <Pill outline>执行器 {testResult.meta.engine}</Pill> : null}
              {testResult.meta?.latency_ms !== undefined ? (
                <Pill tone="teal">{fmtNum(testResult.meta.latency_ms)} ms</Pill>
              ) : null}
              {testResult.meta?.model ? <Pill tone="purple">{testResult.meta.model}</Pill> : null}
              {testResult.meta?.error ? <Pill tone="orange">降级：{testResult.meta.error}</Pill> : null}
              {testResult.meta?.scores ? (
                <span className="tiny faint">
                  向量得分 <code className="code-inline">{JSON.stringify(testResult.meta.scores)}</code>
                </span>
              ) : null}
              {testResult.meta?.reason ? <span className="tiny faint">原因：{testResult.meta.reason}</span> : null}
            </div>
          ) : null}
        </Section>

        <Section
          title="意图路由决策引擎"
          subtitle="请求未显式指定路由组时，Auto 模式按此策略判定 query 意图"
          extra={<Pill tone="purple">Auto 模式</Pill>}
          gap
        >
          <Form.Item name="router_mode" style={{ marginBottom: 8 }}>
            <Segmented
              block
              options={[
                { label: '极速规则', value: 'rule' },
                { label: 'Jev 决策模型', value: 'jev' },
                { label: 'AI 大模型', value: 'ai' },
              ]}
            />
          </Form.Item>
          <div className="tiny faint" style={{ lineHeight: 1.6 }}>{modeMeta.desc}</div>

          {routerMode === 'jev' ? (
            <>
              <div className="hairline" style={{ margin: '16px 0' }} />
              <SubHead
                icon={<IconSparkles size={15} />}
                title="Jev System One 决策模型"
                hint="TypeSafe · 发送 state + Choice/Noul 类型化问题"
                extra={<Pill tone="purple">毫秒级返回</Pill>}
              />
              <Row gutter={[14, 14]}>
                <Col xs={24} md={10}>
                  <Form.Item name="jev_api_url" label="Jev System One 接口地址" style={{ marginBottom: 12 }}>
                    <AutoComplete
                      options={[
                        {
                          value: 'https://api.typesafe.ai/v1/systemone',
                          label: 'TypeSafe 官方 (https://api.typesafe.ai/v1/systemone)',
                        },
                        {
                          value: 'http://127.0.0.1:11434/v1/systemone',
                          label: '本地开源同类模型 Laya / Ollama SystemOne',
                        },
                      ]}
                      placeholder="https://api.typesafe.ai/v1/systemone"
                    />
                  </Form.Item>
                </Col>
                <Col xs={24} md={8}>
                  <Form.Item name="jev_api_key" label="TYPESAFE_API_KEY（Jev 密钥）" style={{ marginBottom: 12 }}>
                    <Input.Password placeholder="输入 console.typesafe.ai 创建的 API Key" />
                  </Form.Item>
                </Col>
                <Col xs={24} md={6}>
                  <Form.Item name="jev_model" label="Jev 决策模型版本" style={{ marginBottom: 12 }}>
                    <AutoComplete
                      options={[
                        { value: 'jev-1.13.0', label: 'jev-1.13.0 (官方推荐固定版)' },
                        { value: 'jev-latest', label: 'jev-latest (最新别名)' },
                        { value: 'jev-preview', label: 'jev-preview (预览版)' },
                        { value: 'laya-multilingual', label: 'laya-multilingual (开源多语言决策模型)' },
                      ]}
                      placeholder="jev-1.13.0"
                    />
                  </Form.Item>
                </Col>
                <Col xs={12} md={6}>
                  <Form.Item name="jev_confidence_threshold" label="置信度门控阈值" style={{ marginBottom: 0 }}>
                    <InputNumber min={0.1} max={0.99} step={0.05} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col xs={12} md={6}>
                  <Form.Item name="jev_timeout_ms" label="超时 (ms)" style={{ marginBottom: 0 }}>
                    <InputNumber min={500} max={15000} step={500} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
                <Col xs={24} md={12}>
                  <div className="tiny faint" style={{ paddingTop: 22, lineHeight: 1.6 }}>
                    置信度低于阈值时自动回退到关键词规则，保证判定链路不阻塞检索。
                  </div>
                </Col>
              </Row>
            </>
          ) : null}

          {routerMode === 'ai' ? (
            <>
              <div className="hairline" style={{ margin: '16px 0' }} />
              <SubHead
                icon={<IconSparkles size={15} />}
                title="AI 大模型路由"
                hint="由 LLM 直接给出意图标签"
                extra={
                  <Button
                    size="small"
                    icon={<IconDownload size={14} />}
                    loading={fetchingLlmModels}
                    onClick={async () => {
                      const pid = routerForm.getFieldValue('ai_router_provider') || 'siliconflow';
                      setFetchingLlmModels(true);
                      try {
                        const r = await fetch(`/api/admin/providers/${pid}/models`);
                        const d = await r.json();
                        if (Array.isArray(d.models)) {
                          setLlmModelCatalog((prev) => ({ ...prev, [pid]: d.models }));
                          message.success(`已拉取 ${d.models.length} 个模型`);
                        }
                      } finally {
                        setFetchingLlmModels(false);
                      }
                    }}
                  >
                    拉取模型列表
                  </Button>
                }
              />
              <Row gutter={[14, 14]}>
                <Col xs={24} md={8}>
                  <Form.Item name="ai_router_provider" label="判断所用大模型渠道" style={{ marginBottom: 12 }}>
                    <Select
                      options={llmProviders.map((p) => ({
                        label: `${p.name} (${p.active_key_count > 0 ? '已配密钥' : '待配密钥'})`,
                        value: p.id,
                      }))}
                    />
                  </Form.Item>
                </Col>
                <Col xs={24} md={10}>
                  <Form.Item name="ai_router_model" label="指定判断模型 Model ID" style={{ marginBottom: 12 }}>
                    <AutoComplete
                      options={(llmModelCatalog[routerForm.getFieldValue('ai_router_provider') || 'siliconflow'] || []).map(
                        (m) => ({ label: m, value: m })
                      )}
                      placeholder="下拉选择或输入模型 ID"
                    />
                  </Form.Item>
                </Col>
                <Col xs={24} md={6}>
                  <Form.Item name="ai_router_timeout_ms" label="超时 (ms)" style={{ marginBottom: 12 }}>
                    <InputNumber min={1500} max={20000} step={500} style={{ width: '100%' }} />
                  </Form.Item>
                </Col>
              </Row>
            </>
          ) : null}

          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              flexWrap: 'wrap',
              marginTop: 18,
              paddingTop: 16,
              borderTop: '1px solid var(--line-soft)',
            }}
          >
            <span className="tiny faint">保存后立即用于下一次 Auto 路由判定</span>
            <Button type="primary" htmlType="submit" icon={<IconCheck size={15} />} style={{ marginLeft: 'auto' }}>
              保存决策引擎
            </Button>
          </div>
        </Section>
      </Form>

      <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
        <Col xs={24} lg={8}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Section
            title="路由分组"
            subtitle="选中后在右侧编排引擎池"
            extra={<Pill tone="accent">{routes.length}</Pill>}
            flush
          >
            <div style={{ padding: '8px 10px 10px', display: 'flex', flexDirection: 'column', gap: 2 }}>
              {routes.length === 0 ? (
                <EmptyState icon={<IconRoute size={20} />} title="暂无路由分组" desc="刷新后从网关读取默认意图分组。" />
              ) : (
                routes.map((rg) => {
                  const isActive = activeGroup?.id === rg.id;
                  return (
                    <button
                      key={rg.id}
                      type="button"
                      onClick={() => setActiveRouteId(rg.id)}
                      style={{
                        display: 'block',
                        width: '100%',
                        textAlign: 'left',
                        padding: '11px 12px',
                        borderRadius: 'var(--r-md)',
                        border: `1px solid ${isActive ? 'var(--line)' : 'transparent'}`,
                        background: isActive ? 'var(--surface-2)' : 'transparent',
                        font: 'inherit',
                        color: 'inherit',
                        cursor: 'pointer',
                        transition: 'background 160ms var(--ease), border-color 160ms var(--ease)',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span className="small strong truncate" style={{ flex: 1, minWidth: 0 }}>
                          {rg.name}
                        </span>
                        <Pill tone={rg.enabled ? 'green' : 'default'}>{rg.enabled ? '启用' : '停用'}</Pill>
                      </div>
                      <div
                        className="tiny faint"
                        style={{ marginTop: 4, display: 'flex', alignItems: 'center', gap: 7, flexWrap: 'wrap' }}
                      >
                        <span className="num">{rg.engines?.length || 0} 引擎</span>
                        <span style={{ opacity: 0.55 }}>·</span>
                        <span className="num">{fmtNum(rg.timeout_ms)} ms</span>
                        <span style={{ opacity: 0.55 }}>·</span>
                        <span className="num">Top {fmtNum(rg.top_k)}</span>
                      </div>
                    </button>
                  );
                })
              )}
            </div>
          </Section>

          <Section
            title="融合基线"
            subtitle="当前生效的全局 RRF 参数"
            extra={<IconLayers size={15} style={{ color: 'var(--text-3)' }} />}
          >
            <KeyValue
              columns={1}
              items={[
                { label: 'RRF 平滑常数 K', value: <span className="num">k = {fmtNum(settings.rrf_k ?? 60)}</span> },
                {
                  label: '多源重合提权',
                  value: <span className="num">× {Number(settings.multi_source_boost ?? 1.45).toFixed(2)}</span>,
                },
                {
                  label: '结果缓存',
                  value: settings.enable_cache ? (
                    <span>
                      启用 · TTL <span className="num">{fmtNum(settings.cache_ttl_seconds ?? 600)}</span> s
                    </span>
                  ) : (
                    <Pill>未启用</Pill>
                  ),
                },
              ]}
            />
            <div className="tiny faint" style={{ marginTop: 12, lineHeight: 1.6 }}>
              融合按 score = Σ weight / (k + rank) 计算，被多个源同时命中的 URL 再乘提权倍率。
            </div>
          </Section>
          </div>
        </Col>

        <Col xs={24} lg={16}>
          {!activeGroup ? (
            <Section>
              <EmptyState
                icon={<IconRoute size={20} />}
                title="选择一个路由分组开始编排"
                desc="左侧列表展示全部意图分组，选中即可编辑引擎池与分组参数。"
              />
            </Section>
          ) : (
            <Section
              title={
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  {activeGroup.name}
                  <code className="code-inline" style={{ fontWeight: 400 }}>
                    {activeGroup.id}
                  </code>
                </span>
              }
              subtitle={activeGroup.description}
              extra={
                <>
                  <Pill tone={activeGroup.enabled ? 'green' : 'default'}>
                    {activeGroup.enabled ? '启用' : '停用'}
                  </Pill>
                  <Pill tone="accent">{activeGroup.engines?.length || 0} 引擎</Pill>
                </>
              }
            >
              <SubHead
                icon={<IconLayers size={15} />}
                title="主力扇出引擎池"
                hint="勾选即加入该路由组的并发扇出"
                extra={
                  <span className="tiny faint num">
                    {activeGroup.engines?.length || 0} / {searchProviders.length}
                  </span>
                }
              />
              {searchProviders.length === 0 ? (
                <span className="tiny faint">还没有可用的检索源</span>
              ) : (
                <div className="grid cols-2" style={{ gap: 8 }}>
                  {searchProviders.map((p) => {
                    const checked = (activeGroup.engines || []).includes(p.id);
                    return (
                      <button
                        key={p.id}
                        type="button"
                        role="checkbox"
                        aria-checked={checked}
                        onClick={() => toggleEngine(activeGroup, 'engines', p.id)}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 10,
                          width: '100%',
                          textAlign: 'left',
                          padding: '10px 12px',
                          borderRadius: 'var(--r-md)',
                          border: `1px solid ${checked ? 'var(--line)' : 'var(--line-soft)'}`,
                          background: checked ? 'var(--accent-soft)' : 'var(--surface)',
                          font: 'inherit',
                          color: 'inherit',
                          cursor: 'pointer',
                          transition: 'background 160ms var(--ease), border-color 160ms var(--ease)',
                        }}
                      >
                        <span
                          style={{
                            width: 18,
                            height: 18,
                            borderRadius: 'var(--r-xs)',
                            flex: 'none',
                            display: 'grid',
                            placeItems: 'center',
                            border: `1px solid ${checked ? 'var(--accent)' : 'var(--line-strong)'}`,
                            background: checked ? 'var(--accent-soft)' : 'transparent',
                            color: 'var(--accent)',
                          }}
                        >
                          {checked ? <IconCheck size={12} strokeWidth={2} /> : null}
                        </span>
                        <span style={{ minWidth: 0, flex: 1 }}>
                          <span className="small truncate" style={{ display: 'block', fontWeight: 500 }}>
                            {p.name}
                          </span>
                          <span className="tiny faint truncate" style={{ display: 'block' }}>
                            {p.category?.toUpperCase()} · {p.id}
                          </span>
                        </span>
                        <span
                          title={`渠道权重 ×${Number(p.weight || 1).toFixed(1)}（在检索源页维护）`}
                          style={{ display: 'flex', alignItems: 'center', gap: 6, flex: 'none' }}
                        >
                          <span className="barlist-track" style={{ width: 44, height: 4 }}>
                            <span
                              className="barlist-fill"
                              style={{ display: 'block', width: `${Math.max(4, (Number(p.weight || 1) / maxWeight) * 100)}%` }}
                            />
                          </span>
                          <span className="tiny faint num">×{Number(p.weight || 1).toFixed(1)}</span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}

              <div className="hairline" style={{ margin: '16px 0' }} />

              <SubHead
                icon={<IconShield size={15} />}
                title="零结果兜底引擎"
                hint="主力全部为空时按序补位"
                extra={<span className="tiny faint num">{activeGroup.fallback_engines?.length || 0} 已选</span>}
              />
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {searchProviders.map((p) => {
                  const on = (activeGroup.fallback_engines || []).includes(p.id);
                  return (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => toggleEngine(activeGroup, 'fallback_engines', p.id)}
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 5,
                        padding: '3px 10px',
                        borderRadius: 'var(--r-pill)',
                        border: `1px solid ${on ? 'var(--accent)' : 'var(--line)'}`,
                        background: on ? 'var(--accent-soft)' : 'var(--surface)',
                        color: on ? 'var(--accent-text)' : 'var(--text-2)',
                        font: 'inherit',
                        fontSize: 11.5,
                        fontWeight: 600,
                        cursor: 'pointer',
                        transition: 'all 160ms var(--ease)',
                      }}
                    >
                      {on ? <IconCheck size={11} strokeWidth={2} /> : null}
                      {p.name}
                    </button>
                  );
                })}
                {searchProviders.length === 0 ? <span className="tiny faint">还没有可用的检索源</span> : null}
              </div>

              <div className="hairline" style={{ margin: '16px 0' }} />

              <SubHead
                icon={<IconSliders size={15} />}
                title="分组参数"
                hint="改动后点右上「保存」写入网关"
                extra={<Pill tone="teal">Top-K {fmtNum(activeGroup.top_k)}</Pill>}
              />
              <Row gutter={[14, 14]}>
                <Col xs={12} sm={8}>
                  <div className="tiny faint" style={{ marginBottom: 6 }}>
                    整组超时 (ms)
                  </div>
                  <InputNumber
                    style={{ width: '100%' }}
                    value={activeGroup.timeout_ms}
                    step={500}
                    onChange={(v) => handleUpdateRouteField(activeGroup.id, 'timeout_ms', v)}
                  />
                </Col>
                <Col xs={12} sm={8}>
                  <div className="tiny faint" style={{ marginBottom: 6 }}>
                    保留 Top-K
                  </div>
                  <InputNumber
                    style={{ width: '100%' }}
                    value={activeGroup.top_k}
                    min={5}
                    max={50}
                    onChange={(v) => handleUpdateRouteField(activeGroup.id, 'top_k', v)}
                  />
                </Col>
                <Col xs={24} sm={8}>
                  <div className="tiny faint" style={{ marginBottom: 6 }}>
                    结果处理
                  </div>
                  <div style={{ paddingTop: 5, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    {activeGroup.enable_rerank ? <Pill tone="purple">语义重排</Pill> : <Pill>融合直出</Pill>}
                    <span className="tiny faint num">抓取 Top {fmtNum(activeGroup.scrape_top_n)}</span>
                  </div>
                </Col>
              </Row>

              <div className="hairline" style={{ margin: '16px 0' }} />

              <KeyValue
                columns={2}
                items={[
                  { label: '主力扇出', value: `${fmtNum(activeGroup.engines?.length || 0)} 个引擎并发` },
                  { label: '零结果兜底', value: `${fmtNum(activeGroup.fallback_engines?.length || 0)} 个引擎` },
                  { label: '超时预算', value: `整组 ${fmtNum(activeGroup.timeout_ms)} ms 截止` },
                  { label: '融合策略', value: <code className="code-inline">RRF · k={fmtNum(settings.rrf_k ?? 60)}</code> },
                ]}
              />

              <div className="hairline" style={{ margin: '16px 0' }} />

              <SubHead icon={<IconKey size={15} />} title="渠道共享密钥池" hint="本地累计调用，非该路由独占用量" />
              {sharedEngineIds.length === 0 ? (
                <span className="tiny faint">该分组还没有关联引擎</span>
              ) : (
                <div>
                  {sharedEngineIds.map((id) => {
                    const provider = searchProviders.find((p) => p.id === id);
                    if (!provider) return null;
                    const keyReady = provider.active_key_count > 0 || !provider.requires_key;
                    return (
                      <div key={id} className="list-row">
                        <span
                          className={`dot ${
                            provider.health_status === 'ready'
                              ? 'green'
                              : provider.health_status === 'circuit_open'
                              ? 'red'
                              : 'orange'
                          }`}
                        />
                        <div style={{ minWidth: 0, flex: 1 }}>
                          <div className="small truncate" style={{ fontWeight: 500 }}>
                            {provider.name}
                          </div>
                          <div className="tiny faint num truncate">
                            调用 {fmtNum(provider.total_calls)} · 成功 {fmtNum(provider.success_calls)} · 失败{' '}
                            {fmtNum(provider.failed_calls)}
                          </div>
                        </div>
                        <Pill tone={keyReady ? 'green' : 'orange'}>
                          可用 Key {provider.active_key_count}/{provider.total_key_count}
                        </Pill>
                        <Button
                          size="small"
                          type="text"
                          icon={<IconKey size={14} />}
                          onClick={() => onManageKeys(id)}
                        >
                          配置 Key
                        </Button>
                      </div>
                    );
                  })}
                </div>
              )}
            </Section>
          )}
        </Col>
      </Row>

      <Section
        title="全局网关参数"
        subtitle="代理 / RRF 融合 / 熔断 / 域名过滤，保存后对全部路由组生效"
        extra={<Pill tone="purple">全局生效</Pill>}
      >
        <KeyValue
          columns={2}
          items={[
            {
              label: 'RRF 倒数排名融合',
              value: (
                <span>
                  k = <strong className="num">{fmtNum(settings.rrf_k ?? 60)}</strong> · 多源重合 ×
                  {Number(settings.multi_source_boost ?? 1.45).toFixed(2)}
                </span>
              ),
            },
            {
              label: '结果缓存',
              value: settings.enable_cache ? (
                <span>
                  启用 · TTL <span className="num">{fmtNum(settings.cache_ttl_seconds ?? 600)}</span> s
                </span>
              ) : (
                <Pill>未启用</Pill>
              ),
            },
            {
              label: '自适应熔断',
              value: (
                <span>
                  连续 <span className="num">{fmtNum(settings.circuit_breaker_threshold ?? 5)}</span> 次失败 → 冷却{' '}
                  <span className="num">{fmtNum(settings.circuit_breaker_cooldown_sec ?? 60)}</span> s
                </span>
              ),
            },
            {
              label: '出网代理',
              value: settings.enable_global_proxy ? (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                  <Pill tone="green">开启</Pill>
                  <code className="code-inline">{settings.global_proxy || '未填写地址'}</code>
                </span>
              ) : (
                <Pill>直连</Pill>
              ),
            },
            {
              label: '权威域名提权',
              value: <span className="num">{asList(settings.boosted_domains).length} 个（×1.2）</span>,
            },
            {
              label: '低质域名屏蔽',
              value: <span className="num">{asList(settings.blocked_domains).length} 个</span>,
            },
          ]}
        />

        <div className="hairline" style={{ margin: '16px 0' }} />

        <Form form={settingsForm} layout="vertical" onFinish={handleSaveGlobalSettings}>
          <SubHead icon={<IconGlobe size={15} />} title="出网代理" hint="上游检索请求统一出口" />
          <Form.Item name="global_proxy" label="全局 HTTP/HTTPS 代理地址" style={{ marginBottom: 12 }}>
            <Input placeholder="http://127.0.0.1:7890" />
          </Form.Item>
          <SwitchRow
            icon={<IconZap size={15} />}
            label="启用全局代理"
            desc="所有上游检索请求经该代理出网"
            control={
              <Form.Item name="enable_global_proxy" valuePropName="checked" noStyle>
                <Switch size="small" checkedChildren="开启" unCheckedChildren="关闭" />
              </Form.Item>
            }
          />

          <div className="hairline" style={{ margin: '16px 0' }} />

          <SubHead icon={<IconLayers size={15} />} title="RRF 倒数排名融合" hint="score = Σ weight / (k + rank)" />
          <Row gutter={[14, 14]}>
            <Col xs={24} md={12}>
              <Form.Item name="rrf_k" label="RRF 平滑常数 K（默认 60）" style={{ marginBottom: 12 }}>
                <InputNumber min={1} max={200} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item name="multi_source_boost" label="多源重合奖励倍率（如 1.45x）" style={{ marginBottom: 12 }}>
                <InputNumber step={0.05} min={1.0} max={5.0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>

          <div className="hairline" style={{ margin: '16px 0' }} />

          <SubHead icon={<IconShield size={15} />} title="自适应熔断与查询缓存" hint="失败自动摘除，冷却后半开重试" />
          <Row gutter={[14, 14]}>
            <Col xs={24} md={8}>
              <Form.Item name="circuit_breaker_threshold" label="连续失败触发熔断次数" style={{ marginBottom: 12 }}>
                <InputNumber min={1} max={20} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item name="circuit_breaker_cooldown_sec" label="熔断自动恢复冷却 (秒)" style={{ marginBottom: 12 }}>
                <InputNumber min={10} max={3600} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={24} md={8}>
              <Form.Item name="cache_ttl_seconds" label="结果缓存有效期 (秒)" style={{ marginBottom: 12 }}>
                <InputNumber min={60} max={86400} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <SwitchRow
            icon={<IconThunderbolt size={15} />}
            label="启用语义 / 精确缓存"
            desc="命中缓存直接返回，跳过全部上游调用"
            control={
              <Form.Item name="enable_cache" valuePropName="checked" noStyle>
                <Switch size="small" checkedChildren="开启" unCheckedChildren="关闭" />
              </Form.Item>
            }
          />

          <div className="hairline" style={{ margin: '16px 0' }} />

          <SubHead icon={<IconFilter size={15} />} title="域名提权与屏蔽" hint="融合阶段即时生效" />
          <Row gutter={[14, 14]}>
            <Col xs={24} md={12}>
              <Form.Item name="boosted_domains" label="权威域名提权白名单（1.2x 加权）" style={{ marginBottom: 12 }}>
                <Select mode="tags" placeholder="输入域名回车，如 github.com" />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item name="blocked_domains" label="内容农场 / 低质域名屏蔽黑名单" style={{ marginBottom: 12 }}>
                <Select mode="tags" placeholder="输入屏蔽域名或路径前缀" />
              </Form.Item>
            </Col>
          </Row>

          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              flexWrap: 'wrap',
              marginTop: 4,
              paddingTop: 14,
              borderTop: '1px solid var(--line-soft)',
            }}
          >
            <span className="tiny faint">保存后立即对新请求生效</span>
            <Button type="primary" htmlType="submit" icon={<IconCheck size={15} />} style={{ marginLeft: 'auto' }}>
              保存全局配置
            </Button>
          </div>
        </Form>
      </Section>
    </div>
  );
};
