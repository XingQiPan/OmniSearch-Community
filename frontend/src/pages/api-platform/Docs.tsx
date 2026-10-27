import React, { useMemo, useState } from 'react';
import { Button, Input, Select, Table, message } from 'antd';
import { CodeBlock, KeyValue, Pill, Section, SubTabs } from '../../components/ui';
import {
  IconCheck,
  IconCode,
  IconExternal,
  IconInfo,
  IconKey,
  IconZap,
} from '../../components/icons';
import { API_LADDER, rungUnits } from '../search/levels';

const ENDPOINT_DOCS = [
  {
    method: 'POST',
    path: '/v1/search',
    desc: '多源聚合搜索：并发扇出多个检索源，跨源去重 + RRF 融合排序；不生成回答。include_trace 返回引擎扇出明细。',
    body: '{\n  "query": "大模型 Agent 记忆机制",\n  "search_depth": "basic",\n  "max_results": 10,\n  "include_trace": true\n}',
  },
  {
    method: 'POST',
    path: '/v1/extract',
    desc: '网页正文抽取：返回 Markdown / 纯文本，适合喂给大模型。',
    body: '{\n  "urls": ["https://example.com/article"],\n  "format": "markdown"\n}',
  },
  {
    method: 'POST',
    path: '/v1/answer',
    desc: '带引用的答案生成，支持 stream=true 的 SSE 增量输出。',
    body: '{\n  "query": "2026 年开源搜索框架有哪些",\n  "model": "omni-fast",\n  "stream": false\n}',
  },
  {
    method: 'POST',
    path: '/v1/research',
    desc: '深度研究 / Agent 自主研究：与搜索工作台同一引擎；返回报告、信源、子问题与精读记录，stream=true 实时推送过程。',
    body: '{\n  "query": "AI Agent 记忆机制最新进展",\n  "mode": "deep",\n  "stream": false\n}',
  },
  {
    method: 'POST',
    path: '/v1/chat/completions',
    desc: 'OpenAI 兼容接口，可直接接入 Cursor / NextChat / Open WebUI。',
    body: '{\n  "model": "omni-fast",\n  "messages": [{"role": "user", "content": "总结今天 AI 圈大事"}]\n}',
  },
  { method: 'GET', path: '/v1/me', desc: '查询当前密钥的套餐、余额与限流。', body: '' },
  { method: 'GET', path: '/v1/usage', desc: '查询用量明细与按天序列。', body: '' },
];

export const DocsTab: React.FC<{ meta: any }> = ({ meta }) => {
  const [endpoint, setEndpoint] = useState('/v1/search');
  const [body, setBody] = useState(ENDPOINT_DOCS[0].body);
  const [key, setKey] = useState('');
  const [resp, setResp] = useState('');
  const [status, setStatus] = useState('');
  const [sending, setSending] = useState(false);
  const [lang, setLang] = useState('curl');

  const base = typeof window !== 'undefined' ? window.location.origin : 'http://127.0.0.1:8088';
  const current = useMemo(() => ENDPOINT_DOCS.find((e) => e.path === endpoint) || ENDPOINT_DOCS[0], [endpoint]);

  const send = async () => {
    if (!key.trim()) return message.warning('请先粘贴一个以 sk-omni- 开头的密钥');
    setSending(true);
    setResp('');
    setStatus('');
    try {
      const init: RequestInit = {
        method: current.method,
        headers: { Authorization: `Bearer ${key.trim()}`, 'Content-Type': 'application/json' },
      };
      if (current.method === 'POST') init.body = body || '{}';
      const r = await fetch(current.path, init);
      const text = await r.text();
      setStatus(`${r.status} ${r.statusText}`);
      try {
        setResp(JSON.stringify(JSON.parse(text), null, 2));
      } catch {
        setResp(text.slice(0, 12000));
      }
    } catch (e: any) {
      setResp(String(e?.message || e));
    } finally {
      setSending(false);
    }
  };

  const snippets: Record<string, string> = {
    curl: `curl -s ${base}/v1/search \\
  -H "Authorization: Bearer sk-omni-xxxxxxxx" \\
  -H "Content-Type: application/json" \\
  -d '{"query":"AI 搜索","search_depth":"basic","max_results":5}'`,
    python: `import requests

resp = requests.post(
    "${base}/v1/search",
    headers={"Authorization": "Bearer sk-omni-xxxxxxxx"},
    json={"query": "AI 搜索", "search_depth": "basic", "max_results": 5},
    timeout=20,
)
data = resp.json()
print(data["usage"])          # {"units": 1, "remaining_units": 499, ...}
for item in data["results"]:
    print(item["score"], item["title"], item["url"])`,
    node: `const resp = await fetch("${base}/v1/search", {
  method: "POST",
  headers: {
    Authorization: "Bearer sk-omni-xxxxxxxx",
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ query: "AI 搜索", search_depth: "basic" }),
});
const data = await resp.json();
console.log(data.usage, data.results.length);`,
    openai: `from openai import OpenAI

client = OpenAI(
    base_url="${base}/v1",
    api_key="sk-omni-xxxxxxxx",
)
resp = client.chat.completions.create(
    model="omni-fast",   # 或 omni-deep
    messages=[{"role": "user", "content": "总结今天 AI 圈大事"}],
)
print(resp.choices[0].message.content)`,
  };

  const ok = status.startsWith('2');

  return (
    <div>
      <Section
        title="能力阶梯 · 由浅入深"
        subtitle="先用最浅的一档拿结果，需要时再往下加：重排 → 正文 → 答案 → 研究；与搜索工作台四档模式一一对应"
        style={{ marginBottom: 18 }}
      >
        <div className="ladder-table">
          {API_LADDER.map((rung, idx) => (
            <div key={rung.id} className="ladder-row">
              <span className="ladder-idx num">{idx + 1}</span>
              <span className="ladder-call">
                <code>{rung.path}</code>
                <span className="faint">{rung.param}</span>
              </span>
              <span className="ladder-adds">{rung.adds}</span>
              <span className="ladder-units num">
                {rung.llm ? <Pill tone="purple">大模型</Pill> : <Pill tone="teal">纯检索</Pill>}
                {rungUnits(rung, meta?.units)} 次
              </span>
            </div>
          ))}
        </div>
      </Section>

      <div className="grid" style={{ gridTemplateColumns: 'minmax(0, 1.05fr) minmax(0, 1fr)', gap: 18 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          <Section
            title="对外接口目录"
            subtitle="只暴露 /v1/*，控制台接口不对公网开放"
            extra={
              <a className="tiny" href="/docs/api" target="_blank" rel="noreferrer" style={{ color: 'var(--accent)', display: 'inline-flex', gap: 4, alignItems: 'center' }}>
                Swagger <IconExternal size={12} />
              </a>
            }
            flush
          >
            <Table
              rowKey="path"
              size="small"
              pagination={false}
              dataSource={meta?.endpoints || []}
              columns={[
                {
                  title: '方法',
                  dataIndex: 'method',
                  width: 68,
                  render: (v: string) => <Pill tone={v === 'GET' ? 'teal' : 'green'}>{v}</Pill>,
                },
                {
                  title: '接口',
                  dataIndex: 'path',
                  render: (v: string, r: any) => (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                      <code className="code-inline" style={{ alignSelf: 'flex-start' }}>{v}</code>
                      <span className="tiny faint">{r.summary}</span>
                    </div>
                  ),
                },
                { title: '计费', dataIndex: 'units', width: 96, render: (v: string) => <span className="tiny faint nowrap">{v}</span> },
              ]}
            />
          </Section>

          <Section title="错误码" subtitle="客户侧 SDK 可按 code 分支处理" flush>
            <Table
              rowKey="code"
              size="small"
              pagination={{ pageSize: 9, showSizeChanger: false }}
              dataSource={meta?.errors || []}
              columns={[
                { title: 'HTTP', dataIndex: 'http_status', width: 64, render: (v: number) => <Pill tone={v < 400 ? 'green' : v < 500 ? 'orange' : 'red'}>{v}</Pill> },
                { title: 'code', dataIndex: 'code', width: 200, render: (v: string) => <code className="code-inline">{v}</code> },
                { title: '含义', dataIndex: 'message' },
              ]}
            />
          </Section>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
          <Section
            title="在线调试"
            subtitle="真实调用、真实扣费，建议用小额度密钥试"
            extra={<Pill tone="orange">会扣次数</Pill>}
          >
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <Input
                prefix={<IconKey size={15} style={{ color: 'var(--text-3)' }} />}
                placeholder="粘贴 sk-omni- 开头的密钥"
                value={key}
                onChange={(e) => setKey(e.target.value)}
              />
              <Select
                value={endpoint}
                onChange={(v) => {
                  setEndpoint(v);
                  const doc = ENDPOINT_DOCS.find((e) => e.path === v);
                  setBody(doc?.body || '');
                }}
                options={ENDPOINT_DOCS.map((e) => ({ label: `${e.method} ${e.path}`, value: e.path }))}
              />
              <div className="tiny faint" style={{ lineHeight: 1.5 }}>{current.desc}</div>
              {current.method === 'POST' ? (
                <Input.TextArea
                  rows={6}
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}
                />
              ) : null}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <Button type="primary" icon={<IconZap size={15} />} loading={sending} onClick={send}>
                  发送请求
                </Button>
                {status ? <Pill tone={ok ? 'green' : 'red'}>{status}</Pill> : null}
              </div>
              {resp ? (
                <CodeBlock code={resp} maxHeight={300} />
              ) : (
                <div
                  style={{
                    padding: 18,
                    borderRadius: 12,
                    border: '1px dashed var(--line)',
                    color: 'var(--text-3)',
                    fontSize: 12,
                    textAlign: 'center',
                  }}
                >
                  响应会显示在这里
                </div>
              )}
            </div>
          </Section>

          <Section
            title="快速接入"
            subtitle="复制即可运行"
            extra={<IconCode size={15} style={{ color: 'var(--text-3)' }} />}
          >
            <div style={{ marginBottom: 12 }}>
              <SubTabs
                value={lang}
                onChange={setLang}
                items={[
                  { key: 'curl', label: 'cURL' },
                  { key: 'python', label: 'Python' },
                  { key: 'node', label: 'Node.js' },
                  { key: 'openai', label: 'OpenAI SDK' },
                ]}
              />
            </div>
            <CodeBlock code={snippets[lang]} maxHeight={280} language={lang} />
          </Section>
        </div>
      </div>

      <Section title="参数速查与计费口径" subtitle="接入前值得花 30 秒读完" style={{ marginTop: 18 }}>
        <KeyValue
          columns={2}
          items={[
            { label: '鉴权方式', value: <code className="code-inline">Authorization: Bearer sk-omni-xxx</code> },
            { label: '请求追踪', value: '响应头 X-Request-Id + 响应体 request_id' },
            {
              label: '限流响应头',
              value: <span className="tiny">X-RateLimit-Limit / Remaining / Reset，429 时带 Retry-After</span>,
            },
            { label: '额度响应头', value: <span className="tiny">X-Quota-Remaining / X-Quota-Used</span> },
            { label: '缓存', value: <span className="tiny">X-Cache: HIT / MISS；cache=false 可强制绕过</span> },
            {
              label: '幂等',
              value: <span className="tiny">POST 加 Idempotency-Key，10 分钟内重放不重复扣费</span>,
            },
            {
              label: '时间过滤',
              value: <span className="tiny">time_range=day/week/month/year，或 freshness=pd/pw/pm/py</span>,
            },
            {
              label: 'LLM 友好输出',
              value: <span className="tiny">response_format=markdown；include_raw_content=true 返回正文</span>,
            },
            {
              label: '计费单位',
              value: (
                <span className="tiny">
                  搜索 basic {meta?.units?.search?.basic ?? 1} / advanced {meta?.units?.search?.advanced ?? 2} /
                  deep {meta?.units?.search?.deep ?? 3}；抽取 {meta?.units?.extract?.per_url ?? 1} 次/URL；答案 fast{' '}
                  {meta?.units?.answer?.fast ?? 2} / deep {meta?.units?.answer?.deep ?? 5}；研究 deep{' '}
                  {meta?.units?.research?.deep ?? 5} / agentic {meta?.units?.research?.agentic ?? 8}；chat {meta?.units?.chat ?? 2}
                </span>
              ),
            },
            {
              label: '套餐能力',
              value: <span className="tiny">语义重排 / 深度研究 / 答案生成 / SSE 由套餐开关控制，未开通返回 403 feature_not_in_plan；/v1/research 复用 answer 权限</span>,
            },
          ]}
        />
        <div
          style={{
            marginTop: 16,
            padding: '12px 14px',
            borderRadius: 12,
            background: 'var(--accent-soft)',
            color: 'var(--accent-text)',
            fontSize: 12.5,
            display: 'flex',
            gap: 8,
            alignItems: 'flex-start',
          }}
        >
          <IconInfo size={15} style={{ marginTop: 1, flex: 'none' }} />
          <span>
            生产部署请只对公网暴露 <code style={{ fontSize: 11.5 }}>/v1/*</code>，控制台接口
            <code style={{ fontSize: 11.5 }}>/api/*</code>保持内网访问。反向代理与安全建议见设计文档第七节。
          </span>
        </div>
      </Section>

      <div style={{ display: 'flex', gap: 8, marginTop: 14 }} className="tiny faint">
        <IconCheck size={13} /> 接口契约稳定，破坏性变更会走 /v2；新增参数一律可选。
      </div>
    </div>
  );
};
