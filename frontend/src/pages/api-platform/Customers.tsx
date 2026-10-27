import React, { useState } from 'react';
import {
  Button,
  Col,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Switch,
  Table,
  message,
} from 'antd';
import { CodeBlock, CopyButton, EmptyState, KeyValue, Pill, Section, Toolbar } from '../../components/ui';
import {
  IconCheck,
  IconEdit,
  IconExternal,
  IconKey,
  IconPlus,
  IconRefresh,
  IconUsers,
  IconWallet,
} from '../../components/icons';
import { fmtCny, fmtNum, fmtTime } from '../../utils/format';

export const CustomersTab: React.FC<{
  clients: any[];
  plans: any[];
  loading: boolean;
  reload: () => void;
}> = ({ clients, plans, loading, reload }) => {
  const [createOpen, setCreateOpen] = useState(false);
  const [createForm] = Form.useForm();
  const [topupTarget, setTopupTarget] = useState<any>(null);
  const [topupForm] = Form.useForm();
  const [keyTarget, setKeyTarget] = useState<any>(null);
  const [keyForm] = Form.useForm();
  const [newKey, setNewKey] = useState<{ key: string; label: string; client?: string } | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const [detailOpen, setDetailOpen] = useState(false);

  const planOptions = plans.map((p: any) => ({
    label: `${p.name} · ${fmtCny(p.price_per_1k_cny)}/千次`,
    value: p.id,
  }));

  const submitCreate = async () => {
    const values = await createForm.validateFields();
    const resp = await fetch('/api/admin/platform/clients', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(values),
    });
    const data = await resp.json();
    if (!resp.ok) return message.error(data.detail || '创建失败');
    message.success('客户已创建');
    setCreateOpen(false);
    createForm.resetFields();
    if (data.api_key) setNewKey({ key: data.api_key, label: `${values.name} · 首次签发密钥` });
    reload();
  };

  const submitTopup = async () => {
    const values = await topupForm.validateFields();
    const resp = await fetch(`/api/admin/platform/clients/${topupTarget.id}/topup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(values),
    });
    const data = await resp.json();
    if (!resp.ok) return message.error(data.detail || '充值失败');
    message.success(`已充值，当前余额 ${fmtNum(data.client.balance_units)} 次`);
    setTopupTarget(null);
    topupForm.resetFields();
    reload();
  };

  const submitKey = async () => {
    const values = await keyForm.validateFields();
    const resp = await fetch(`/api/admin/platform/clients/${keyTarget.id}/keys`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_id: keyTarget.id, ...values }),
    });
    const data = await resp.json();
    if (!resp.ok) return message.error(data.detail || '签发失败');
    setNewKey({ key: data.api_key, label: `${keyTarget.name} · ${values.label || '密钥'}`, client: keyTarget.name });
    setKeyTarget(null);
    keyForm.resetFields();
    reload();
  };

  const rotate = async (clientId: string, keyId: string) => {
    const resp = await fetch(`/api/admin/platform/keys/${keyId}/rotate`, { method: 'POST' });
    const data = await resp.json();
    if (!resp.ok) return message.error(data.detail || '轮换失败');
    setNewKey({ key: data.api_key, label: '新密钥（旧密钥已吊销）' });
    reload();
  };

  const revoke = async (keyId: string) => {
    await fetch(`/api/admin/platform/keys/${keyId}/revoke`, { method: 'POST' });
    message.success('密钥已吊销');
    reload();
  };

  const openDetail = async (client: any) => {
    const resp = await fetch(`/api/admin/platform/clients/${client.id}`);
    setDetail(await resp.json());
    setDetailOpen(true);
  };

  const activeClients = clients.filter((c) => c.source !== 'internal');
  const totalBalance = activeClients.reduce((acc, c) => acc + Number(c.balance_units || 0), 0);

  return (
    <div>
      <Toolbar
        right={
          <span className="tiny faint">
            {activeClients.length} 家客户 · 剩余额度合计 {fmtNum(totalBalance)} 次 · 明文密钥仅在签发时展示一次
          </span>
        }
      >
        <Button type="primary" icon={<IconPlus size={15} />} onClick={() => setCreateOpen(true)}>
          新建客户
        </Button>
        <Button icon={<IconRefresh size={15} />} onClick={reload} loading={loading}>
          刷新
        </Button>
      </Toolbar>

      <Section flush>
        <Table
          rowKey="id"
          size="small"
          loading={loading}
          dataSource={activeClients}
          pagination={activeClients.length > 12 ? { pageSize: 12, showSizeChanger: false } : false}
          locale={{ emptyText: <EmptyState title="还没有客户" desc="点右上角「新建客户」，或让客户自助注册领 500 次试用。" /> }}
          scroll={{ x: 1060 }}
          columns={[
            {
              title: '客户',
              dataIndex: 'name',
              width: 220,
              render: (v: string, r: any) => (
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 13.5 }} className="truncate">
                    {v}
                    {r.source === 'internal' ? <Pill style={{ marginLeft: 6 }}>内部</Pill> : null}
                  </div>
                  <div className="tiny faint truncate">{r.email || r.company || r.id}</div>
                </div>
              ),
            },
            {
              title: '套餐',
              dataIndex: 'plan_name',
              width: 150,
              render: (v: string, r: any) => (
                <div>
                  <Pill tone={r.plan_id === 'enterprise' ? 'orange' : r.plan_id === 'pro' || r.plan_id === 'max' ? 'purple' : 'accent'}>
                    {v || r.plan_id}
                  </Pill>
                  <div className="tiny faint" style={{ marginTop: 3 }}>
                    {fmtCny(r.price_per_1k_cny)} / 千次
                  </div>
                </div>
              ),
            },
            {
              title: '剩余额度',
              dataIndex: 'balance_units',
              width: 150,
              render: (v: number, r: any) => (
                <div>
                  <div
                    className="num"
                    style={{
                      fontWeight: 600,
                      fontSize: 14,
                      color: v > 1000 ? 'var(--green)' : v > 0 ? 'var(--orange)' : 'var(--red)',
                    }}
                  >
                    {fmtNum(v)} 次
                  </div>
                  <div className="tiny faint">
                    {r.billing_mode === 'postpaid' ? '后付费月结' : `累计充值 ${fmtCny(r.total_topup_cny)}`}
                  </div>
                </div>
              ),
            },
            {
              title: '状态',
              dataIndex: 'status',
              width: 100,
              render: (v: string, r: any) => (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <Pill tone={v === 'active' ? 'green' : 'red'}>{v === 'active' ? '正常' : '停用'}</Pill>
                  {r.source === 'self_serve' ? <span className="tiny faint">自助注册</span> : null}
                </div>
              ),
            },
            {
              title: '密钥',
              dataIndex: 'active_keys',
              width: 80,
              render: (v: number) => <span className="num small">{v || 0}</span>,
            },
            {
              title: '操作',
              width: 230,
              render: (_, r: any) => (
                <Space size={6}>
                  <Button size="small" onClick={() => openDetail(r)}>详情</Button>
                  <Button size="small" icon={<IconWallet size={13} />} onClick={() => {
                    setTopupTarget(r);
                    topupForm.setFieldsValue({ amount_cny: r.price_per_1k_cny || 100, units: undefined });
                  }}>
                    充值
                  </Button>
                  <Button size="small" icon={<IconKey size={13} />} onClick={() => setKeyTarget(r)}>
                    签发
                  </Button>
                </Space>
              ),
            },
          ]}
        />
      </Section>

      {/* 新建客户 */}
      <Modal
        title="新建客户"
        open={createOpen}
        onOk={submitCreate}
        onCancel={() => setCreateOpen(false)}
        okText="创建并签发密钥"
        width={580}
      >
        <Form form={createForm} layout="vertical" initialValues={{ plan_id: 'basic', issue_key: true, billing_mode: 'prepaid' }}>
          <Row gutter={14}>
            <Col span={12}>
              <Form.Item name="name" label="客户 / 团队名称" rules={[{ required: true, message: '必填' }]}>
                <Input placeholder="如：某某科技 / 张三" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="email" label="联系邮箱">
                <Input placeholder="用于账单通知" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="company" label="公司">
                <Input />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="plan_id" label="套餐" rules={[{ required: true }]}>
                <Select options={planOptions} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="grant_units" label="赠送次数" extra="留空按套餐默认（体验版 500 次）">
                <InputNumber min={0} style={{ width: '100%' }} placeholder="如 1000" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="billing_mode" label="计费模式">
                <Select
                  options={[
                    { label: '预付费（余额扣减）', value: 'prepaid' },
                    { label: '后付费（月结）', value: 'postpaid' },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col span={24}>
              <Form.Item name="note" label="备注">
                <Input.TextArea rows={2} placeholder="商务备注、来源渠道等" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="issue_key" label="同时签发密钥" valuePropName="checked">
                <Switch />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="key_label" label="密钥备注">
                <Input placeholder="如：生产环境" />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>

      {/* 充值 */}
      <Modal
        title={`为客户充值 · ${topupTarget?.name || ''}`}
        open={!!topupTarget}
        onOk={submitTopup}
        onCancel={() => setTopupTarget(null)}
        okText="确认到账"
        width={520}
      >
        <div
          style={{
            padding: '12px 14px',
            borderRadius: 12,
            background: 'var(--surface-2)',
            marginBottom: 16,
            display: 'flex',
            justifyContent: 'space-between',
            fontSize: 12.5,
            color: 'var(--text-2)',
          }}
        >
          <span>当前单价 <strong style={{ color: 'var(--text)' }}>{fmtCny(topupTarget?.price_per_1k_cny)}/千次</strong></span>
          <span>当前余额 <strong style={{ color: 'var(--text)' }}>{fmtNum(topupTarget?.balance_units)} 次</strong></span>
        </div>
        <Form form={topupForm} layout="vertical">
          <Form.Item name="amount_cny" label="充值金额（元）">
            <InputNumber min={0} step={50} style={{ width: '100%' }} addonBefore="¥" />
          </Form.Item>
          <Form.Item name="units" label="到账次数（可选）" extra="填了就以次数为准，适合人工赠送额度">
            <InputNumber min={1} style={{ width: '100%' }} placeholder="如 1000" addonAfter="次" />
          </Form.Item>
          <Form.Item name="note" label="备注">
            <Input placeholder="如：微信转账 / 合同号" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 签发密钥 */}
      <Modal
        title={`签发新密钥 · ${keyTarget?.name || ''}`}
        open={!!keyTarget}
        onOk={submitKey}
        onCancel={() => setKeyTarget(null)}
        okText="签发"
        width={580}
      >
        <Form
          form={keyForm}
          layout="vertical"
          initialValues={{ label: '生产环境', scopes: ['search', 'extract', 'answer', 'chat'] }}
        >
          <Form.Item name="label" label="密钥备注">
            <Input />
          </Form.Item>
          <Form.Item name="scopes" label="授权能力">
            <Select
              mode="multiple"
              options={[
                { label: 'search 搜索', value: 'search' },
                { label: 'extract 正文抽取', value: 'extract' },
                { label: 'answer 答案生成', value: 'answer' },
                { label: 'chat OpenAI 兼容', value: 'chat' },
              ]}
            />
          </Form.Item>
          <Row gutter={14}>
            <Col span={8}>
              <Form.Item name="rpm_limit" label="RPM（0=套餐默认）">
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="rpd_limit" label="每日上限（0=默认）">
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="expires_days" label="有效期（天，0=永久）">
                <InputNumber min={0} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="ip_allowlist" label="IP 白名单" extra="逗号分隔，支持 CIDR；留空不限制">
            <Input placeholder="如 1.2.3.4,10.0.0.0/8" />
          </Form.Item>
        </Form>
      </Modal>

      {/* 新密钥 */}
      <Modal
        title="密钥已生成"
        open={!!newKey}
        onCancel={() => setNewKey(null)}
        width={620}
        footer={
          <>
            <Button onClick={() => setNewKey(null)}>我已保存</Button>
            <Button type="primary" icon={<IconCheck size={15} />} onClick={() => {
              navigator.clipboard.writeText(newKey?.key || '');
              message.success('已复制密钥');
            }}>
              复制密钥
            </Button>
          </>
        }
      >
        <div
          style={{
            display: 'flex',
            gap: 10,
            alignItems: 'center',
            padding: '12px 14px',
            borderRadius: 12,
            background: 'var(--orange-soft)',
            color: 'var(--orange)',
            fontSize: 12.5,
            marginBottom: 16,
          }}
        >
          关闭后无法再次查看明文密钥，请立即交给客户保存。
        </div>
        <div className="tiny faint" style={{ marginBottom: 6 }}>{newKey?.label}</div>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '12px 14px',
            borderRadius: 12,
            border: '1px solid var(--line-soft)',
            background: 'var(--surface-2)',
            marginBottom: 16,
          }}
        >
          <code style={{ flex: 1, fontFamily: 'var(--font-mono)', fontSize: 12.5, wordBreak: 'break-all' }}>
            {newKey?.key}
          </code>
          <CopyButton text={newKey?.key || ''} />
        </div>
        <CodeBlock
          code={`curl -s ${window.location.origin}/v1/search \\
  -H "Authorization: Bearer ${newKey?.key || ''}" \\
  -H "Content-Type: application/json" \\
  -d '{"query":"AI 搜索","search_depth":"basic","max_results":5}'`}
        />
      </Modal>

      {/* 客户详情 */}
      <Modal
        title={detail?.name ? `客户详情 · ${detail.name}` : '客户详情'}
        open={detailOpen}
        onCancel={() => setDetailOpen(false)}
        footer={null}
        width={920}
      >
        {detail ? (
          <>
            <div
              style={{
                display: 'flex',
                gap: 32,
                flexWrap: 'wrap',
                padding: '14px 16px',
                borderRadius: 14,
                background: 'var(--surface-2)',
                marginBottom: 18,
              }}
            >
              <KeyValue
                items={[
                  { label: '套餐', value: detail.plan_name || detail.plan_id },
                  { label: '千次单价', value: fmtCny(detail.price_per_1k_cny) },
                  { label: '剩余额度', value: `${fmtNum(detail.balance_units)} 次` },
                  { label: '近 30 天调用', value: `${fmtNum(detail.usage?.requests || 0)} 次` },
                ]}
                columns={4}
              />
            </div>

            <div className="tiny faint" style={{ marginBottom: 8, fontWeight: 600, color: 'var(--text-2)' }}>密钥</div>
            <Table
              rowKey="id"
              size="small"
              style={{ marginBottom: 20 }}
              pagination={false}
              dataSource={detail.keys || []}
              columns={[
                { title: '备注', dataIndex: 'label', ellipsis: true },
                { title: '密钥', dataIndex: 'masked', render: (v: string) => <code className="code-inline">{v}</code> },
                {
                  title: '状态',
                  dataIndex: 'enabled',
                  width: 90,
                  render: (v: number, r: any) =>
                    !v || r.revoked_at ? <Pill tone="red">已吊销</Pill> : <Pill tone="green">启用</Pill>,
                },
                { title: '累计消耗', dataIndex: 'total_units', width: 100, render: (v: number) => <span className="num">{fmtNum(v)}</span> },
                {
                  title: '最后使用',
                  dataIndex: 'last_used_at',
                  width: 160,
                  render: (v: number) => <span className="tiny faint">{v ? fmtTime(v) : '—'}</span>,
                },
                {
                  title: '操作',
                  width: 150,
                  render: (_, r: any) => (
                    <Space size={6}>
                      <Popconfirm title="轮换后旧密钥立即失效，确认？" onConfirm={() => rotate(detail.id, r.id)}>
                        <Button size="small" disabled={!r.enabled || !!r.revoked_at}>轮换</Button>
                      </Popconfirm>
                      <Popconfirm title="确认吊销？" onConfirm={() => revoke(r.id)}>
                        <Button size="small" danger disabled={!r.enabled || !!r.revoked_at}>吊销</Button>
                      </Popconfirm>
                    </Space>
                  ),
                },
              ]}
            />

            <div className="tiny faint" style={{ marginBottom: 8, fontWeight: 600, color: 'var(--text-2)' }}>充值记录</div>
            <Table
              rowKey="id"
              size="small"
              pagination={false}
              dataSource={detail.topups || []}
              locale={{ emptyText: '暂无充值记录' }}
              columns={[
                { title: '时间', dataIndex: 'created_at', render: (v: number) => <span className="tiny faint">{fmtTime(v)}</span> },
                { title: '金额', dataIndex: 'amount_cny', render: (v: number) => fmtCny(v) },
                { title: '到账次数', dataIndex: 'units', render: (v: number) => fmtNum(v) },
                { title: '备注', dataIndex: 'note' },
              ]}
            />
          </>
        ) : null}
      </Modal>
    </div>
  );
};
