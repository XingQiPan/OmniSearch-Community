import React, { useState } from 'react';
import {
  Button,
  Col,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Switch,
  Table,
  message,
} from 'antd';
import { Pill, Section, Stat } from '../../components/ui';
import { IconCheck, IconEdit, IconSliders, IconWallet } from '../../components/icons';
import { fmtCny, fmtNum } from '../../utils/format';

const CAPS: [string, string][] = [
  ['allow_rerank', '语义重排'],
  ['allow_extract', '正文抽取'],
  ['allow_answer', '答案生成'],
  ['allow_deep', '深度研究'],
  ['allow_stream', 'SSE 流式'],
  ['allow_postpaid', '后付费'],
];

export const PlansTab: React.FC<{ plans: any[]; loading: boolean; reload: () => void }> = ({
  plans,
  loading,
  reload,
}) => {
  const [editTarget, setEditTarget] = useState<any>(null);
  const [form] = Form.useForm();
  const [monthlyCalls, setMonthlyCalls] = useState<number>(10000);

  const openEdit = (plan: any) => {
    setEditTarget(plan);
    form.setFieldsValue({ ...plan, features: (plan.features || []).join('\n') });
  };

  const submit = async () => {
    const values = await form.validateFields();
    const payload = {
      ...values,
      features: String(values.features || '')
        .split('\n')
        .map((s: string) => s.trim())
        .filter(Boolean),
    };
    const resp = await fetch(`/api/admin/platform/plans/${editTarget.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) {
      const err = await resp.json();
      return message.error(err.detail || '保存失败');
    }
    message.success('套餐已更新');
    setEditTarget(null);
    reload();
  };

  const quote = (plan: any) => (Number(monthlyCalls || 0) / 1000) * Number(plan.price_per_1k_cny || 0);
  const sorted = [...plans].sort((a, b) => Number(a.price_per_1k_cny) - Number(b.price_per_1k_cny));

  return (
    <div>
      <Section
        title="定价计算器"
        subtitle="按调用量估算各档套餐成本。"
        gap
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
          <div style={{ position: 'relative' }}>
            <InputNumber
              min={0}
              step={5000}
              value={monthlyCalls}
              onChange={(v) => setMonthlyCalls(Number(v || 0))}
              style={{ width: 210, height: 42, fontSize: 16, fontWeight: 600 }}
              addonAfter="次 / 月"
            />
          </div>
          <div className="tiny faint" style={{ maxWidth: 520 }}>
            按各档千次单价折算。实际扣费以「次」为单位：基础搜索 1 次、语义重排 2 次、深度研究 3 次。
          </div>
        </div>
      </Section>

      <div className="grid section-gap" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(196px, 1fr))' }}>
        {sorted.map((p: any) => {
          const highlight = p.highlight;
          return (
            <div
              key={p.id}
              className="card"
              style={{
                padding: '20px 20px 18px',
                borderColor: highlight ? 'var(--accent)' : undefined,
                boxShadow: highlight ? '0 18px 44px -26px rgba(0,113,227,.55)' : undefined,
                position: 'relative',
                display: 'flex',
                flexDirection: 'column',
                gap: 10,
                opacity: p.enabled ? 1 : 0.55,
              }}
            >
              {highlight ? (
                <span
                  style={{
                    position: 'absolute',
                    top: 14,
                    right: 14,
                    fontSize: 10.5,
                    fontWeight: 700,
                    letterSpacing: '0.04em',
                    color: 'var(--accent)',
                    background: 'var(--accent-soft)',
                    padding: '2px 8px',
                    borderRadius: 980,
                  }}
                >
                  推荐
                </span>
              ) : null}

              <div>
                <div style={{ fontSize: 15, fontWeight: 650, letterSpacing: '-0.02em' }}>{p.name}</div>
                <div className="tiny faint" style={{ marginTop: 3, minHeight: 32, lineHeight: 1.5 }}>{p.tagline}</div>
              </div>

              <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
                <span style={{ fontSize: 30, fontWeight: 700, letterSpacing: '-0.035em' }}>
                  {Number(p.price_per_1k_cny) === 0 ? '免费' : fmtCny(p.price_per_1k_cny, 0)}
                </span>
                {Number(p.price_per_1k_cny) > 0 ? <span className="tiny faint">/ 千次</span> : null}
              </div>

              <div
                style={{
                  padding: '10px 12px',
                  borderRadius: 12,
                  background: 'var(--surface-2)',
                  fontSize: 12,
                  color: 'var(--text-2)',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 3,
                }}
              >
                <span>
                  月成本约 <strong style={{ color: 'var(--text)' }}>{fmtCny(quote(p), 0)}</strong>
                </span>
                <span>
                  起充 {fmtCny(p.min_topup_cny, 0)} · 赠送 {fmtNum(p.included_units)} 次
                </span>
                <span>
                  {fmtNum(p.rpm_limit)} RPM · {fmtNum(p.rpd_limit)} 次/日
                </span>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: 1 }}>
                {(p.features || []).slice(0, 6).map((f: string) => (
                  <span key={f} className="small" style={{ display: 'flex', gap: 7, alignItems: 'flex-start' }}>
                    <span style={{ color: 'var(--accent)', marginTop: 2, flex: 'none' }}>
                      <IconCheck size={13} strokeWidth={2} />
                    </span>
                    <span style={{ color: 'var(--text-2)', lineHeight: 1.45 }}>{f}</span>
                  </span>
                ))}
              </div>

              <Button icon={<IconEdit size={14} />} onClick={() => openEdit(p)} block>
                编辑定价
              </Button>
            </div>
          );
        })}
      </div>

      <Section title="配置一览" subtitle="限流、返回条数与能力开关" flush>
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          pagination={false}
          dataSource={plans}
          scroll={{ x: 1000 }}
          columns={[
            { title: '套餐', dataIndex: 'name', width: 150, render: (v: string, r: any) => (
              <div>
                <div style={{ fontWeight: 600 }}>{v}</div>
                <div className="tiny faint">{r.id}</div>
              </div>
            ) },
            { title: '千次单价', dataIndex: 'price_per_1k_cny', width: 100, render: (v: number) => <span className="num">{fmtCny(v)}</span> },
            { title: '起充', dataIndex: 'min_topup_cny', width: 90, render: (v: number) => <span className="num">{fmtCny(v)}</span> },
            { title: '赠送', dataIndex: 'included_units', width: 80, render: (v: number) => <span className="num">{fmtNum(v)}</span> },
            { title: 'RPM', dataIndex: 'rpm_limit', width: 80, render: (v: number) => <span className="num">{fmtNum(v)}</span> },
            { title: '每日上限', dataIndex: 'rpd_limit', width: 110, render: (v: number) => <span className="num">{fmtNum(v)}</span> },
            { title: '返回条数', dataIndex: 'max_results', width: 90 },
            {
              title: '能力',
              render: (_, r: any) => (
                <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                  {CAPS.filter(([k]) => r[k]).map(([k, label]) => (
                    <Pill key={k} tone="accent">{label}</Pill>
                  ))}
                  {CAPS.every(([k]) => !r[k]) ? <span className="tiny faint">仅搜索</span> : null}
                </div>
              ),
            },
            {
              title: '状态',
              dataIndex: 'enabled',
              width: 80,
              render: (v: number) => <Pill tone={v ? 'green' : 'default'}>{v ? '上架' : '下架'}</Pill>,
            },
          ]}
        />
      </Section>

      <Modal
        title={`编辑套餐 · ${editTarget?.name || ''}`}
        open={!!editTarget}
        onOk={submit}
        onCancel={() => setEditTarget(null)}
        width={700}
        okText="保存定价"
      >
        <Form form={form} layout="vertical">
          <Row gutter={14}>
            <Col span={8}>
              <Form.Item name="name" label="套餐名">
                <Input />
              </Form.Item>
            </Col>
            <Col span={16}>
              <Form.Item name="tagline" label="一句话卖点">
                <Input />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="price_per_1k_cny" label="千次单价（元）">
                <InputNumber min={0} step={1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="min_topup_cny" label="起充金额（元）">
                <InputNumber min={0} step={50} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="included_units" label="新客户赠送（次）">
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={6}>
              <Form.Item name="max_results" label="单次最大返回条数">
                <InputNumber min={1} max={50} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="rpm_limit" label="每分钟限流 RPM">
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="rpd_limit" label="每 Key 每日上限">
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={14}>
            {CAPS.map(([field, label]) => (
              <Col span={8} key={field}>
                <Form.Item name={field} label={label} valuePropName="checked" getValueFromEvent={(v) => (v ? 1 : 0)}>
                  <Switch />
                </Form.Item>
              </Col>
            ))}
            <Col span={8}>
              <Form.Item name="highlight" label="标记推荐" valuePropName="checked" getValueFromEvent={(v) => (v ? 1 : 0)}>
                <Switch />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="enabled" label="上架销售" valuePropName="checked" getValueFromEvent={(v) => (v ? 1 : 0)}>
                <Switch />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="features" label="卖点列表（每行一条）">
            <Input.TextArea rows={5} />
          </Form.Item>
        </Form>
      </Modal>

      <div style={{ marginTop: 16 }}>
        <Stat
          label="计费口径提示"
          value={<span style={{ fontSize: 13, fontWeight: 400, lineHeight: 1.6, color: 'var(--text-2)' }}>
            失败请求不计费；正文抽取按成功 URL 计费；缓存命中照常返回 usage 但不重复调用上游。
            修改定价只影响新扣费，不改历史账单。
          </span>}
          icon={<IconWallet size={14} />}
          tone="accent"
        />
      </div>
    </div>
  );
};
