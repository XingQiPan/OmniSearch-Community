import React, { useEffect, useMemo, useState } from 'react';
import { Drawer } from 'antd';
import type { UnifiedSearchResponse } from '../../api';
import { CodeBlock, Pill, SubTabs } from '../../components/ui';
import { IconCode, IconExternal, IconInfo } from '../../components/icons';
import {
  API_LADDER,
  ApiParams,
  buildApiRequest,
  rungUnits,
  SearchDepth,
  toCurl,
  toPublicSearchPreview,
  toPython,
} from './levels';

/** 各档 API 的返回内容说明（流式事件顺序与非流式字段）。 */
const RESPONSE_SHAPE: Record<string, { stream: string[]; json: string }> = {
  '/v1/extract': {
    stream: [],
    json: '{ results[{ url, title, content, format, length, status, error, published_at, retrieved_at, truncated }], success_count, failed_count, usage }',
  },
  '/v1/answer': {
    stream: ['meta：引用列表 citations[]、usage', 'delta × N：答案增量文本', 'done：llm_generated、citations、usage', 'data: [DONE]'],
    json: '{ answer, citations[], latency_ms, usage }',
  },
  '/v1/research': {
    stream: [
      'meta：query、mode、usage',
      'status：当前阶段提示（规划 / 检索 / 精读 / 撰写）',
      'plan：子问题或各轮检索节点（标题、检索词、条数、耗时）',
      'read / decision：正文精读记录、每轮是否继续深挖（agentic）',
      'sources：融合信源（结构同 /v1/search 的 results，可多次推送，以最后一次为准）',
      'delta × N：报告增量（Markdown，[n](URL) 引用）',
      'suggestions → done：llm_generated、usage → data: [DONE]',
    ],
    json: '{ answer, results[], plan[], reads[], decisions[], suggestions[], llm_generated, usage }',
  },
};

export const ApiDrawer: React.FC<{
  open: boolean;
  onClose: () => void;
  params: ApiParams;
  lastDirect?: { resp: UnifiedSearchResponse; depth: SearchDepth } | null;
}> = ({ open, onClose, params, lastDirect }) => {
  const [lang, setLang] = useState('curl');
  const [units, setUnits] = useState<Record<string, any> | null>(null);
  const origin = typeof window !== 'undefined' ? window.location.origin : 'http://127.0.0.1:8088';
  const request = useMemo(() => buildApiRequest(params), [params]);
  const activeRung = request.rung;

  useEffect(() => {
    if (!open || units) return;
    let alive = true;
    fetch('/api/admin/platform/meta')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (alive && data?.units) setUnits(data.units);
      })
      .catch(() => {
        /* 读不到实时定价时用默认口径 */
      });
    return () => {
      alive = false;
    };
  }, [open, units]);

  const isSearch = request.path === '/v1/search';
  const preview = useMemo(() => {
    if (!isSearch || !lastDirect) return '';
    return JSON.stringify(toPublicSearchPreview(lastDirect.resp, lastDirect.depth), null, 2);
  }, [isSearch, lastDirect]);
  const shape = RESPONSE_SHAPE[request.path];

  return (
    <Drawer
      width="min(760px, 100vw)"
      open={open}
      onClose={onClose}
      title={
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          <IconCode size={16} style={{ color: 'var(--accent)' }} />
          以开放 API 调用
        </span>
      }
      extra={
        <a className="md-link tiny" href="/docs/api" target="_blank" rel="noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          完整文档 <IconExternal size={12} />
        </a>
      }
      styles={{ body: { padding: 20 } }}
    >
      <div className="api-block">
        <div className="api-block-title">能力阶梯 · 由浅入深</div>
        <div className="tiny faint" style={{ marginBottom: 10 }}>
          每往下一级多一步处理；工作台四档模式与这些调用一一对应，当前设置高亮。
        </div>
        <div className="ladder-table">
          {API_LADDER.map((rung, idx) => (
            <div key={rung.id} className={`ladder-row ${rung.id === activeRung ? 'active' : ''}`}>
              <span className="ladder-idx num">{idx + 1}</span>
              <span className="ladder-call">
                <code>{rung.path}</code>
                <span className="faint">{rung.param}</span>
              </span>
              <span className="ladder-adds">{rung.adds}</span>
              <span className="ladder-units num">
                {rung.llm ? <Pill tone="purple">大模型</Pill> : <Pill tone="teal">纯检索</Pill>}
                {rungUnits(rung, units)} 次
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="api-block">
        <div className="api-block-title" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          当前设置的等价请求
          <span style={{ marginLeft: 'auto' }}>
            <SubTabs
              value={lang}
              onChange={setLang}
              items={[
                { key: 'curl', label: 'cURL' },
                { key: 'python', label: 'Python' },
              ]}
            />
          </span>
        </div>
        <div className="tiny faint" style={{ marginBottom: 10, lineHeight: 1.6 }}>
          {request.note}
        </div>
        <CodeBlock code={lang === 'curl' ? toCurl(origin, request) : toPython(origin, request)} maxHeight={260} language={lang} />
      </div>

      <div className="api-block">
        <div className="api-block-title">返回什么</div>
        {isSearch ? (
          preview ? (
            <>
              <div className="tiny faint" style={{ marginBottom: 10, lineHeight: 1.6 }}>
                按 /v1/search 字段整理的「上一次直接搜索」返回预览（节选前 2 条）。实际响应还带 request_id 与 usage（本次消耗次数、余额）；
                deep 档的 content 为完整正文。
              </div>
              <CodeBlock code={preview} maxHeight={420} language="json" />
            </>
          ) : (
            <div className="notice">
              <IconInfo size={15} style={{ flex: 'none', marginTop: 1, color: 'var(--accent)' }} />
              <span>先在工作台跑一次「直接搜索」，这里会按 /v1/search 的字段展示这次结果的返回结构。</span>
            </div>
          )
        ) : shape ? (
          <>
            {shape.stream.length ? (
              <>
                <div className="tiny faint" style={{ marginBottom: 8 }}>stream=true 时的 SSE 事件顺序：</div>
                <ol className="event-list">
                  {shape.stream.map((line) => (
                    <li key={line}>{line}</li>
                  ))}
                </ol>
              </>
            ) : null}
            <div className="tiny faint" style={{ marginTop: shape.stream.length ? 10 : 0, lineHeight: 1.7 }}>
              {shape.stream.length ? 'stream=false 时一次性返回：' : '一次性返回：'}
              <code className="code-inline">{shape.json}</code>
            </div>
          </>
        ) : null}
      </div>
    </Drawer>
  );
};
