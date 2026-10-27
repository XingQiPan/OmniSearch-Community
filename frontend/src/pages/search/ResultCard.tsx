import React from 'react';
import { Button, Tooltip, Typography, message } from 'antd';
import type { UnifiedSearchItem } from '../../api';
import { Pill } from '../../components/ui';
import { IconAlert, IconArrowUpRight, IconDownload, IconFlame, IconGlobe } from '../../components/icons';
import { fmtNum } from '../../utils/format';
import { renderMarkdownWithCitations } from './markdown';

const { Paragraph } = Typography;

export interface DirectPage {
  url: string;
  final_url?: string;
  title: string;
  content: string;
  format: string;
  length: number;
  status: 'success' | 'error';
  error?: string | null;
  published_at?: string | null;
  retrieved_at?: string | null;
  truncated?: boolean;
  read_source?: string | null;
  latency_ms?: number;
}

export const hostOf = (item: Pick<UnifiedSearchItem, 'domain' | 'url'>): string => {
  if (item.domain) return item.domain;
  try {
    return new URL(item.url).hostname.replace(/^www\./, '');
  } catch {
    return '';
  }
};

/** 已抓到正文的结果（deep 深读 / Agent 精读）直接复用，不再二次请求。 */
const pageFromItem = (item: UnifiedSearchItem): DirectPage => ({
  url: item.url,
  title: item.title,
  content: item.content || '',
  format: 'markdown',
  length: (item.content || '').length,
  status: 'success',
  published_at: item.published_at,
  retrieved_at: item.metadata?.retrieved_at,
  truncated: Boolean(item.metadata?.content_truncated),
  read_source: item.metadata?.read_source || null,
});

/* ------------------------------ 站点首字母头像 ------------------------------ */

export const DomainAvatar: React.FC<{ domain: string; size?: number }> = ({ domain, size = 18 }) => {
  const clean = (domain || '?').replace(/^www\./, '');
  let hash = 0;
  for (let i = 0; i < clean.length; i++) hash = (hash * 31 + clean.charCodeAt(i)) % 360;
  return (
    <span
      className="domain-avatar"
      aria-hidden="true"
      style={{
        width: size,
        height: size,
        fontSize: Math.round(size * 0.56),
        color: `hsl(${hash} 58% 50%)`,
        background: `hsl(${hash} 70% 50% / 0.14)`,
      }}
    >
      {clean.charAt(0).toUpperCase()}
    </span>
  );
};

/* --------------------------------------------------------------------------
   网页正文：SSE 直读结果与结果卡“读正文”抽屉共用同一渲染层
   -------------------------------------------------------------------------- */
export const PageContentView: React.FC<{ page: DirectPage; maxHeight?: number }> = ({ page, maxHeight = 620 }) => {
  if (page.status !== 'success') {
    return (
      <div className="notice orange">
        <IconAlert size={15} style={{ color: 'var(--orange)', flex: 'none', marginTop: 1 }} />
        <span>
          读取失败：{page.error || '正文为空或站点反爬'}
          <br />
          <span className="faint">{page.url}</span>
        </span>
      </div>
    );
  }
  return (
    <div>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6 }}>
        <Pill tone="green">{fmtNum(page.length)} 字</Pill>
        {page.published_at ? <Pill outline>发布 {String(page.published_at).slice(0, 19)}</Pill> : null}
        {page.retrieved_at ? <Pill outline>读取 {String(page.retrieved_at).slice(0, 19)}</Pill> : null}
        {page.truncated ? <Pill tone="orange">已截断</Pill> : null}
        {page.read_source === 'meta_description' ? (
          <Pill tone="orange">仅页面摘要</Pill>
        ) : page.read_source ? (
          <Pill tone="teal">{page.read_source}</Pill>
        ) : null}
        <a href={page.final_url || page.url} target="_blank" rel="noreferrer" className="md-link" style={{ marginLeft: 'auto', fontSize: 12 }}>
          打开原文
          <IconArrowUpRight size={11} style={{ marginLeft: 3, verticalAlign: '-1px', display: 'inline-block' }} />
        </a>
      </div>
      <div
        style={{
          marginTop: 10,
          maxHeight,
          overflowY: 'auto',
          paddingRight: 6,
          borderTop: '1px solid var(--line-soft)',
          paddingTop: 10,
        }}
      >
        {page.format === 'text' ? (
          <pre
            style={{
              margin: 0,
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              fontFamily: 'var(--font-mono)',
              fontSize: 12.5,
              lineHeight: 1.7,
              color: 'var(--text-2)',
            }}
          >
            {page.content}
          </pre>
        ) : (
          renderMarkdownWithCitations(page.content)
        )}
      </div>
      {page.read_source === 'meta_description' ? (
        <div className="tiny faint" style={{ marginTop: 8, lineHeight: 1.6 }}>
          该页面主要由前端脚本渲染，静态抓取只能拿到站点摘要；完整内容请打开原文。
        </div>
      ) : null}
    </div>
  );
};

/* --------------------------------------------------------------------------
   结果卡：站点行 / 标题 / 摘要 / 证据标签。
   - 融合结果：显示相关度（相对本次最高分，等同 /v1/search 的 score）与命中引擎；
   - 单引擎原始结果（rawEngine）：显示它在融合后排第几、或是否被淘汰。
   -------------------------------------------------------------------------- */
export const ResultCard: React.FC<{
  item: UnifiedSearchItem;
  index: number;
  maxScore?: number;
  compact?: boolean;
  rawEngine?: string;
  fusedRank?: number | null;
  onOpenHongguo?: (bookId: string) => void;
  onReadPage?: (url: string, preloaded?: DirectPage) => void;
}> = ({ item, index, maxScore, compact, rawEngine, fusedRank, onOpenHongguo, onReadPage }) => {
  const engines = item.engines?.length ? item.engines : rawEngine ? [] : [item.source_engine];
  const isMultiHit = engines.length > 1;
  const isTrending = engines.includes('trending') || rawEngine === 'trending';
  const isShortVideo = Boolean((engines.includes('shortvideo') || rawEngine === 'shortvideo') && item.metadata?.video);
  const domain = hostOf(item);
  const isHongguo = domain === 'hongguoduanju.com';
  const evidence = item.metadata?.evidence;
  const relevance = !rawEngine && maxScore && maxScore > 0 ? Math.round((item.final_score / maxScore) * 100) : null;
  const scoreTip = [
    `RRF ${Number(item.rrf_score || 0).toFixed(5)}`,
    item.rerank_score !== undefined && item.rerank_score !== null ? `重排 ${Number(item.rerank_score).toFixed(5)}` : '',
    `最终 ${Number(item.final_score || 0).toFixed(5)}`,
    item.metadata?.rerank_status === 'semantic' ? '已语义重排' : item.metadata?.rerank_status === 'lexical_only' ? '词面重排' : '',
  ]
    .filter(Boolean)
    .join(' · ');

  return (
    <article className={`rcard ${compact ? 'compact' : ''}`}>
      <span className="rcard-index num">{String(index + 1).padStart(2, '0')}</span>

      <div className="rcard-main">
        <div className="rcard-site">
          <DomainAvatar domain={domain} />
          <span className="truncate" style={{ minWidth: 0 }}>{domain || '未知站点'}</span>
          <span className="rcard-sep">·</span>
          <span className="nowrap">{item.published_at ? `发布 ${item.published_at.slice(0, 10)}` : '发布时间未知'}</span>
          {item.metadata?.updated_at ? (
            <>
              <span className="rcard-sep">·</span>
              <span className="nowrap">更新 {String(item.metadata.updated_at).slice(0, 10)}</span>
            </>
          ) : null}
          {relevance !== null ? (
            <Tooltip title={scoreTip}>
              <span className="rcard-score num">
                <span className="rcard-score-bar">
                  <span style={{ width: `${Math.max(6, relevance)}%` }} />
                </span>
                {relevance}
              </span>
            </Tooltip>
          ) : null}
        </div>

        <a href={item.url} target="_blank" rel="noreferrer" className="rcard-title" title={item.title}>
          {item.title || item.url}
          <IconArrowUpRight size={12} style={{ marginLeft: 5, color: 'var(--text-3)', verticalAlign: '-1px', display: 'inline-block' }} />
        </a>

        {item.snippet ? (
          <Paragraph ellipsis={{ rows: compact ? 2 : 3, expandable: true, symbol: '展开' }} className="rcard-snippet">
            {item.snippet}
          </Paragraph>
        ) : (
          <div className="rcard-snippet faint">（该来源未返回摘要）</div>
        )}

        <div className="rcard-tags">
          {rawEngine ? (
            fusedRank ? (
              <Pill tone="green">融合后第 {fusedRank} 名</Pill>
            ) : (
              <Tooltip title="被去重合并、域名过滤或排在返回条数之外">
                <span>
                  <Pill outline>未进入融合结果</Pill>
                </span>
              </Tooltip>
            )
          ) : (
            engines.map((eng) => (
              <Pill key={eng} tone="teal">
                {eng} #{item.positions?.[eng] || 1}
              </Pill>
            ))
          )}
          {isMultiHit && <Pill tone="orange">{engines.length} 引擎命中</Pill>}
          {typeof evidence?.confidence === 'number' && !rawEngine && (
            <Tooltip
              title={`检索强度 ${Math.round((evidence.breakdown?.retrieval || 0) * 100)}% · 跨源印证 ${Math.round((evidence.breakdown?.corroboration || 0) * 100)}% · 域名权威 ${Math.round((evidence.breakdown?.authority || 0) * 100)}% · 时效 ${Math.round((evidence.breakdown?.recency || 0) * 100)}%`}
            >
              <span>
                <Pill tone={evidence.confidence >= 0.75 ? 'teal' : evidence.confidence >= 0.55 ? 'accent' : 'default'}>
                  可信度 {Math.round(evidence.confidence * 100)}%
                </Pill>
              </span>
            </Tooltip>
          )}
          {item.content ? <Pill tone="green">已抓正文 {fmtNum(item.content.length)} 字</Pill> : null}
          {item.metadata?.query_variant === 'en' ? (
            <Tooltip title={`英文扩展检索：${item.metadata?.translated_query || ''}`}>
              <span>
                <Pill outline>英文扩展</Pill>
              </span>
            </Tooltip>
          ) : null}
          {item.metadata?.freshness === 'stale' && <Pill tone="orange">超出时间范围</Pill>}
          {item.metadata?.freshness === 'unknown' && <Pill>时间未核实</Pill>}
          {item.metadata?.time_range_requested && item.metadata?.time_filter_support === 'not_applied' && (
            <Pill outline>源端不支持时间筛选</Pill>
          )}
          {isTrending && (
            <Pill tone="orange">
              <IconFlame size={11} />
              {String(item.metadata?.board_name || '热榜')}
            </Pill>
          )}
          {isTrending && item.metadata?.rank ? <Pill tone="purple">第 {String(item.metadata.rank)} 名</Pill> : null}
          {isTrending && item.metadata?.hot_value ? <Pill tone="red">热度 {String(item.metadata.hot_value)}</Pill> : null}

          {isHongguo && (
            <>
              <Pill tone="purple">红果短剧</Pill>
              <Button
                size="small"
                type="primary"
                ghost
                icon={<IconDownload size={14} />}
                onClick={() => {
                  const bid = item.metadata?.book_id || item.url.split('/player/')[1];
                  onOpenHongguo?.(String(bid));
                }}
              >
                获取全剧下载链接
              </Button>
            </>
          )}

          {isShortVideo && (
            <>
              <Pill tone={item.metadata?.platform === 'douyin' ? 'purple' : 'accent'}>
                {item.metadata?.platform === 'douyin' ? '抖音视频' : 'B站视频'}
              </Pill>
              <Button
                size="small"
                type="primary"
                icon={<IconDownload size={14} />}
                onClick={() => {
                  const best = item.metadata?.best_download_url;
                  if (best) window.open(best, '_blank', 'noopener,noreferrer');
                }}
              >
                直接下载
              </Button>
              <Button
                size="small"
                onClick={() => {
                  navigator.clipboard.writeText(item.metadata?.best_download_url || '').then(
                    () => message.success('已复制下载直链'),
                    () => message.error('剪贴板不可用'),
                  );
                }}
              >
                复制直链
              </Button>
            </>
          )}

          {onReadPage && !isShortVideo && !isHongguo && (
            <Button
              size="small"
              type="text"
              icon={<IconGlobe size={13} />}
              className="rcard-action"
              onClick={() => onReadPage(item.url, item.content ? pageFromItem(item) : undefined)}
            >
              读正文
            </Button>
          )}
        </div>
      </div>
    </article>
  );
};
