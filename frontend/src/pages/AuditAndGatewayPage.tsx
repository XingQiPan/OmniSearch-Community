import React, { useEffect, useState } from 'react';
import { Button, Input, Table, message } from 'antd';
import { EmptyState, PageHeader, Pill, Section } from '../components/ui';
import {
  IconArrowUpRight,
  IconCopy,
  IconDownload,
  IconKey,
  IconLayers,
  IconRefresh,
  IconRoute,
  IconTerminal,
} from '../components/icons';
import { fmtNum, fmtTime } from '../utils/format';

export const AuditAndGatewayPage: React.FC<{ onOpenPlatform?: () => void }> = ({ onOpenPlatform }) => {
  const [traces, setTraces] = useState<any[]>([]);
  const [tokens, setTokens] = useState<any[]>([]);
  const [tokenName, setTokenName] = useState('外部 Agent 接入密钥');
  const [loading, setLoading] = useState(false);
  const [skillManifest, setSkillManifest] = useState<any>(null);
  const [skillFiles, setSkillFiles] = useState<any[]>([]);
  const [skillBaseUrl, setSkillBaseUrl] = useState('http://127.0.0.1:8088');

  const loadData = async () => {
    setLoading(true);
    try {
      const [tResp, kResp, sResp] = await Promise.all([
        fetch('/api/admin/traces?limit=50'),
        fetch('/api/admin/gateway-tokens'),
        fetch('/api/v1/skill/manifest'),
      ]);
      setTraces(await tResp.json());
      setTokens(await kResp.json());
      const sData = await sResp.json();
      setSkillManifest(sData.manifest);
      setSkillFiles(sData.files || []);
      if (sData.manifest?.entrypoints?.http_search) {
        setSkillBaseUrl(sData.manifest.entrypoints.http_search.replace('/api/v1/search', ''));
      }
    } catch (e: any) {
      message.error(`加载审计日志失败: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleDownloadSkill = () => {
    const url = `/api/v1/skill/download?base_url=${encodeURIComponent(skillBaseUrl)}`;
    window.open(url, '_blank');
    message.success('skill 包已开始下载，解压后可直接放入 Agent 的 skills 目录');
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleCreateToken = async () => {
    await fetch(`/api/admin/gateway-tokens?name=${encodeURIComponent(tokenName)}`, {
      method: 'POST',
    });
    message.success('已生成新的对外网关接入密钥');
    loadData();
  };

  const handleDeleteToken = async (tok: string) => {
    await fetch(`/api/admin/gateway-tokens/${tok}`, { method: 'DELETE' });
    message.success('密钥已删除');
    loadData();
  };

  const skillFileList: any[] = skillFiles.length
    ? skillFiles
    : [
        { path: 'SKILL.md', desc: '技能说明' },
        { path: 'skill.json', desc: '机器可读清单' },
        { path: 'config.json', desc: '网关地址与 Token' },
        { path: 'reference.md', desc: '接口参数速查' },
        { path: 'examples.md', desc: '调用示例' },
        { path: 'scripts/omni_search.py', desc: 'Python 客户端' },
        { path: 'scripts/omni_search.mjs', desc: 'Node 客户端' },
      ];

  const skillUsage = [
    <>
      解压到 Agent 的 skills 目录，如 <code className="code-inline">~/.claude/skills/</code> 或{' '}
      <code className="code-inline">.codex/skills/</code>
    </>,
    <>
      Agent 读取 <code className="code-inline">SKILL.md</code> 即自动学会调用，脚本零依赖
    </>,
    <>
      也可把 <code className="code-inline">/v1/chat/completions</code> 配成 OpenAI 兼容模型直接接入 IDE
    </>,
  ];

  return (
    <div>
      <PageHeader
        icon={<IconTerminal size={21} />}
        title="调用日志与技能包"
        subtitle="检索 trace 审计与 Agent 技能包。"
        extra={
          <Button icon={<IconRefresh size={15} />} onClick={loadData} loading={loading}>
            刷新日志
          </Button>
        }
      />

      {/* 对外网关 Token 分发已迁出本页 */}
      <div
        className="card section-gap"
        style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '13px 18px', flexWrap: 'wrap' }}
      >
        <div
          style={{
            width: 32,
            height: 32,
            borderRadius: 10,
            display: 'grid',
            placeItems: 'center',
            background: 'var(--surface-2)',
            color: 'var(--teal)',
            flex: 'none',
          }}
        >
          <IconKey size={15} />
        </div>
        <div style={{ flex: '1 1 300px', minWidth: 0, fontSize: 13, color: 'var(--text-2)', lineHeight: 1.5 }}>
          对外网关密钥不再在本页分发，签发、计费与吊销统一由「开放 API 平台」的付费 Key 管理。
        </div>
        <Pill tone="teal">已迁移至 开放 API 平台</Pill>
        <Button
          type="text"
          size="small"
          icon={<IconArrowUpRight size={14} />}
          onClick={() =>
            onOpenPlatform
              ? onOpenPlatform()
              : message.info('请从左侧导航进入「开放 API 平台」管理密钥与客户')
          }
        >
          前往
        </Button>
      </div>

      {/* Skill 包下载 */}
      <Section
        className="section-gap"
        title="Agent 技能包"
        subtitle="把本网关封装成可直接安装的技能，Claude Code / Cursor / Codex 与自研 Agent 通用"
        extra={<Pill tone="purple">{skillFileList.length} 个文件 · 零依赖</Pill>}
      >
        <div className="grid cols-2" style={{ gap: 24, alignItems: 'start' }}>
          <div style={{ minWidth: 0 }}>
            <p style={{ margin: 0, fontSize: 13, color: 'var(--text-2)', lineHeight: 1.62 }}>
              下载得到一个 <code className="code-inline">omnisearch-gateway</code> 技能包（zip），内含{' '}
              <code className="code-inline">SKILL.md</code>（带 YAML frontmatter，可被 Agent 直接识别）、机器可读清单、
              参数速查与示例，以及 Python / Node 客户端脚本 —— 解压即用，无需安装任何第三方库。
            </p>

            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 14 }}>
              <Input
                value={skillBaseUrl}
                onChange={(e) => setSkillBaseUrl(e.target.value)}
                placeholder="网关对外地址（如 http://192.168.1.10:8088）"
                style={{ flex: '1 1 240px', minWidth: 0 }}
              />
              <Button type="primary" icon={<IconDownload size={15} />} onClick={handleDownloadSkill}>
                下载 skill 包
              </Button>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10 }}>
              <code
                className="code-inline truncate"
                style={{ flex: '1 1 auto', minWidth: 0, display: 'block', padding: '4px 8px' }}
              >
                python scripts/omni_search.py "检索词" --mode agentic --route auto
              </code>
              <Button
                size="small"
                icon={<IconCopy size={13} />}
                onClick={() => {
                  navigator.clipboard.writeText(
                    `python scripts/omni_search.py "检索词" --mode agentic --route auto`,
                  );
                  message.success('已复制脚本调用示例');
                }}
              >
                复制
              </Button>
            </div>

            <div style={{ marginTop: 18, paddingTop: 14, borderTop: '1px solid var(--line-soft)' }}>
              <div className="tiny faint" style={{ fontWeight: 600, marginBottom: 9 }}>
                使用方式
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {skillUsage.map((text, idx) => (
                  <div key={idx} style={{ display: 'flex', gap: 9, alignItems: 'flex-start' }}>
                    <span
                      style={{
                        width: 16,
                        height: 16,
                        marginTop: 2,
                        borderRadius: '50%',
                        background: 'var(--surface-2)',
                        color: 'var(--text-3)',
                        display: 'grid',
                        placeItems: 'center',
                        fontSize: 10.5,
                        fontWeight: 600,
                        flex: 'none',
                      }}
                    >
                      {idx + 1}
                    </span>
                    <span style={{ fontSize: 12.5, color: 'var(--text-2)', lineHeight: 1.55 }}>{text}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 8 }}>
              <IconLayers size={14} style={{ color: 'var(--text-3)' }} />
              <span style={{ fontSize: 12.5, fontWeight: 600 }}>技能包内容预览</span>
            </div>
            <div>
              {skillFileList.map((f: any, idx: number) => (
                <div
                  key={f.path}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 10,
                    padding: '7px 0',
                    borderBottom: idx === skillFileList.length - 1 ? 'none' : '1px solid var(--line-soft)',
                  }}
                >
                  <code className="code-inline truncate" style={{ flex: 'none', maxWidth: '60%' }}>
                    {f.path}
                  </code>
                  <span className="tiny faint truncate" style={{ marginLeft: 'auto' }}>
                    {f.desc}
                  </span>
                </div>
              ))}
            </div>

            {skillManifest ? (
              <div style={{ marginTop: 16 }}>
                <div className="tiny faint" style={{ fontWeight: 600, marginBottom: 8 }}>
                  已声明能力
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {(skillManifest.capabilities || []).map((c: string) => (
                    <Pill key={`cap-${c}`} tone="purple">
                      {c}
                    </Pill>
                  ))}
                  {(skillManifest.modes || []).map((m: string) => (
                    <Pill key={`mode-${m}`} tone="accent">
                      mode: {m}
                    </Pill>
                  ))}
                  {(skillManifest.route_groups || []).map((g: string) => (
                    <Pill key={`group-${g}`} tone="teal">
                      group: {g}
                    </Pill>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </Section>

      {/* 全链路调用瀑布流审计表 */}
      <Section
        title="全链路调用日志"
        subtitle="点击任意一行展开，查看各检索源的并发耗时瀑布流"
        extra={<Pill tone="accent">{fmtNum(traces.length)} 条</Pill>}
        flush
      >
        <Table
          rowKey="trace_id"
          size="small"
          loading={loading}
          dataSource={traces}
          scroll={{ x: 960 }}
          locale={{
            emptyText: (
              <EmptyState
                icon={<IconTerminal size={20} />}
                title="还没有调用记录"
                desc="发起一次搜索后，trace 会实时出现在这里。"
              />
            ),
          }}
          expandable={{
            expandedRowRender: (record: any) => {
              const maxLat = Math.max(record.total_latency_ms || 1, 1);
              const engines: any[] = record.engine_traces || [];
              return (
                <div style={{ padding: '4px 2px 6px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
                    <IconRoute size={14} style={{ color: 'var(--text-3)' }} />
                    <span style={{ fontSize: 12.5, fontWeight: 600 }}>多源并发瀑布流</span>
                    <span className="tiny faint">
                      {engines.length} 个引擎 · 端到端 {fmtNum(record.total_latency_ms)} ms
                    </span>
                  </div>

                  {engines.length === 0 ? (
                    <div className="tiny faint">该 trace 没有记录扇出明细。</div>
                  ) : (
                    <div className="grid cols-2" style={{ gap: '12px 26px' }}>
                      {engines.map((et: any, i: number) => {
                        const pct = Math.min(100, Math.round(((et.latency_ms || 0) / maxLat) * 100));
                        const ok = et.status === 'success';
                        return (
                          <div key={i} style={{ minWidth: 0 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 6 }}>
                              <span className="truncate" style={{ fontSize: 12.5, fontWeight: 600 }}>
                                {et.engine_name}
                              </span>
                              <Pill tone={ok ? 'green' : 'red'} style={{ fontSize: 10.5, padding: '0 7px' }}>
                                {et.status}
                              </Pill>
                              <span className="tiny faint nowrap">
                                {et.result_count} 条 · {et.used_proxy ? '代理' : '直连'}
                              </span>
                              <span
                                className="tiny num nowrap"
                                style={{ marginLeft: 'auto', color: ok ? 'var(--text-2)' : 'var(--red)' }}
                              >
                                {fmtNum(et.latency_ms)} ms
                              </span>
                            </div>
                            <div style={{ height: 5, borderRadius: 999, background: 'var(--fill)', overflow: 'hidden' }}>
                              <div
                                style={{
                                  height: '100%',
                                  width: `${Math.max(2, pct)}%`,
                                  borderRadius: 999,
                                  background: ok ? 'var(--accent)' : 'var(--red)',
                                }}
                              />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            },
          }}
          columns={[
            {
              title: 'TRACE',
              dataIndex: 'trace_id',
              width: 155,
              render: (v: string) => <code className="code-inline">{v}</code>,
            },
            {
              title: '查询词',
              dataIndex: 'query',
              ellipsis: true,
              render: (v: string) => <span style={{ fontWeight: 500 }}>{v}</span>,
            },
            {
              title: '模式',
              dataIndex: 'mode',
              width: 110,
              render: (v: string) => <Pill tone={String(v || '').includes('deep') ? 'purple' : 'accent'}>{v || '—'}</Pill>,
            },
            {
              title: '路由',
              dataIndex: 'resolved_route',
              width: 100,
              render: (v: string) => <code className="code-inline">{String(v || '—').toUpperCase()}</code>,
            },
            {
              title: '原始 → 融合',
              width: 130,
              align: 'right',
              render: (_: any, r: any) => (
                <span className="small num">
                  {fmtNum(r.total_raw_results)} → <strong>{fmtNum(r.total_merged_results)}</strong>
                </span>
              ),
            },
            {
              title: '跨源重合',
              dataIndex: 'cross_engine_hits',
              width: 100,
              align: 'right',
              render: (v: number) =>
                v > 0 ? <Pill tone="orange">{fmtNum(v)} 条</Pill> : <span className="faint tiny">—</span>,
            },
            {
              title: '耗时',
              dataIndex: 'total_latency_ms',
              width: 105,
              align: 'right',
              render: (v: number) => (
                <span
                  className="num small nowrap"
                  style={{ color: Number(v) < 3000 ? 'var(--green)' : 'var(--orange)' }}
                >
                  {fmtNum(v)} ms
                </span>
              ),
            },
            {
              title: '时间',
              dataIndex: 'created_at',
              width: 165,
              render: (v: number) => <span className="tiny faint num">{fmtTime(v)}</span>,
            },
          ]}
        />
      </Section>
    </div>
  );
};
