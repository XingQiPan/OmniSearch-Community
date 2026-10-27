import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Modal, Switch, Table, Tooltip, message } from 'antd';
import { EmptyState, PageHeader, Pill, Section, SubTabs, Toolbar } from '../components/ui';
import { IconAlert, IconDownload, IconExternal, IconFlame, IconRefresh } from '../components/icons';
import { fmtNum } from '../utils/format';
import type { TrendingBoard } from '../api';

interface VideoTrack {
  label: string;
  url: string;
  kind: string;
  size_bytes?: number | null;
  width?: number | null;
  height?: number | null;
  codec?: string | null;
  ext?: string;
  watermark?: boolean | null;
  note?: string | null;
}

interface VideoInfo {
  platform: string;
  platform_name: string;
  id: string;
  share_url: string;
  title: string;
  author: string;
  duration_text?: string | null;
  cover?: string | null;
  tracks: VideoTrack[];
  matched_keyword?: string;
  note?: string | null;
}

function formatBytes(bytes?: number | null): string {
  if (!bytes || bytes <= 0) return '-';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = bytes;
  let idx = 0;
  while (value >= 1024 && idx < units.length - 1) {
    value /= 1024;
    idx += 1;
  }
  return `${value.toFixed(value >= 100 || idx === 0 ? 0 : 1)} ${units[idx]}`;
}


const CATEGORY_OPTIONS = [
  { label: '全部榜单', value: 'all' },
  { label: '🔥 综合热搜', value: 'comprehensive' },
  { label: '💻 科技热榜', value: 'tech' },
  { label: '💬 社区热帖', value: 'community' },
  { label: '📚 知识百科', value: 'knowledge' },
  { label: '🎬 娱乐短剧', value: 'entertainment' },
  { label: '📖 网文数据', value: 'webnovel' },
];

/** 热度文字配色：金 / 橙 / 灰，只用文字色，不加色块底 */
const hotTone = (rank: number): React.CSSProperties => {
  if (rank === 1) return { color: 'var(--orange)', fontWeight: 600, opacity: 1 };
  if (rank === 2) return { color: 'var(--orange)', fontWeight: 600, opacity: 0.72 };
  if (rank === 3) return { color: 'var(--text-2)', fontWeight: 600, opacity: 1 };
  return { color: 'var(--text-3)', fontWeight: 500, opacity: 1 };
};

const SkeletonRows: React.FC<{ rows?: number }> = ({ rows = 6 }) => (
  <div>
    {Array.from({ length: rows }).map((_, i) => (
      <div
        key={i}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '11px 16px',
          borderBottom: '1px solid var(--line-soft)',
        }}
      >
        <div style={{ width: 14, height: 9, borderRadius: 4, background: 'var(--surface-2)', flex: 'none' }} />
        <div
          style={{
            height: 10,
            borderRadius: 5,
            background: 'var(--surface-2)',
            flex: 1,
            maxWidth: `${76 - i * 7}%`,
          }}
        />
        <div style={{ width: 32, height: 9, borderRadius: 4, background: 'var(--surface-2)', flex: 'none' }} />
      </div>
    ))}
  </div>
);

const SkeletonBoardCard: React.FC = () => (
  <div className="card" style={{ overflow: 'hidden' }}>
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '13px 16px',
        borderBottom: '1px solid var(--line-soft)',
      }}
    >
      <div style={{ width: 28, height: 28, borderRadius: 8, background: 'var(--surface-2)', flex: 'none' }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ height: 11, width: '42%', borderRadius: 5, background: 'var(--surface-2)' }} />
        <div style={{ height: 9, width: '24%', borderRadius: 4, background: 'var(--surface-2)', marginTop: 6 }} />
      </div>
      <div style={{ width: 56, height: 18, borderRadius: 980, background: 'var(--surface-2)', flex: 'none' }} />
    </div>
    <SkeletonRows />
  </div>
);

export const TrendingCenter: React.FC = () => {
  const [boards, setBoards] = useState<TrendingBoard[]>([]);
  const [loading, setLoading] = useState(false);
  const [category, setCategory] = useState<string>('all');
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [generatedAt, setGeneratedAt] = useState<string>('');
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 视频取链弹窗
  const [linkModal, setLinkModal] = useState<{
    open: boolean;
    loading: boolean;
    title: string;
    videos: VideoInfo[];
    note?: string | null;
    error?: string | null;
  }>({ open: false, loading: false, title: '', videos: [] });

  const fetchVideoLinks = useCallback(
    async (platform: string, keyword: string, videoId?: string | null) => {
      setLinkModal({ open: true, loading: true, title: keyword, videos: [], note: null, error: null });
      try {
        const qs = new URLSearchParams({ platform, keyword, limit: '3' });
        if (videoId) qs.set('video_id', videoId);
        const resp = await fetch(`/api/v1/video/trending-link?${qs.toString()}`);
        const json = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(json?.detail || `HTTP ${resp.status}`);
        const videos: VideoInfo[] = json.videos || [];
        setLinkModal({
          open: true,
          loading: false,
          title: keyword,
          videos,
          note: json.note,
          error: videos.length ? null : json.note || '未获取到下载直链',
        });
        if (videos.length) message.success(`已获取 ${videos.length} 个视频的下载直链`);
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setLinkModal({ open: true, loading: false, title: keyword, videos: [], error: msg });
        message.error(`取链失败: ${msg}`);
      }
    },
    [],
  );

  const copyUrl = useCallback(async (url: string) => {
    try {
      await navigator.clipboard.writeText(url);
      message.success('已复制直链');
    } catch {
      message.error('剪贴板不可用');
    }
  }, []);

  const loadBoards = useCallback(async (refresh = false) => {
    setLoading(true);
    try {
      const resp = await fetch(`/api/v1/trending?limit=20${refresh ? '&refresh=true' : ''}`);
      const json = await resp.json();
      setBoards(json.boards || []);
      setGeneratedAt(json.generated_at || '');
      if (refresh) {
        message.success(`已刷新 ${json.success_boards}/${json.total_boards} 个榜单`);
      }
    } catch (e) {
      message.error(`榜单加载失败: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  }, []);

  const refreshSingleBoard = useCallback(async (boardId: string) => {
    try {
      const resp = await fetch(`/api/v1/trending/${boardId}?limit=20&refresh=true`);
      const json = await resp.json();
      if (json.status === 'success') {
        setBoards((prev) => prev.map((b) => (b.board_id === boardId ? { ...json, cached: false } : b)));
      } else {
        message.warning(`${json.name || boardId}: ${json.error_message || '刷新失败'}`);
      }
    } catch {
      message.error('单榜单刷新失败');
    }
  }, []);

  useEffect(() => {
    loadBoards();
  }, [loadBoards]);

  useEffect(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    if (autoRefresh) {
      timerRef.current = setInterval(() => loadBoards(true), 60_000);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [autoRefresh, loadBoards]);

  const visibleBoards = category === 'all' ? boards : boards.filter((b) => b.category === category);
  const okCount = boards.filter((b) => b.status === 'success').length;

  return (
    <div>
      <PageHeader
        icon={<IconFlame size={21} />}
        title="全网热榜"
        subtitle={`一次并发聚合百度 / 微博 / 知乎 / 抖音 / B站 / GitHub / HN / 掘金 / V2EX / Reddit / 维基百科等热榜，服务端缓存 5 分钟防限流，海外源自动复用网关全局代理${
          generatedAt ? ` · 数据时间 ${generatedAt}` : ''
        }。`}
        tags={
          boards.length ? (
            <Pill tone={okCount === boards.length ? 'green' : 'orange'}>
              {okCount}/{boards.length} 在线
            </Pill>
          ) : undefined
        }
        extra={
          <>
            <span className="tiny faint">每 60s 自动刷新</span>
            <Switch checked={autoRefresh} onChange={setAutoRefresh} size="small" />
            <Button type="primary" icon={<IconRefresh size={15} />} loading={loading} onClick={() => loadBoards(true)}>
              强制刷新
            </Button>
          </>
        }
      />

      <Toolbar
        right={
          <span className="tiny faint">
            {visibleBoards.length} 个榜单 · {okCount} 个源在线 · 缓存 5 分钟
          </span>
        }
      >
        <SubTabs
          items={CATEGORY_OPTIONS.map((o) => ({ key: o.value, label: o.label }))}
          value={category}
          onChange={setCategory}
        />
      </Toolbar>

      {loading && boards.length === 0 ? (
        <div className="grid cols-2">
          {[0, 1, 2, 3].map((i) => (
            <SkeletonBoardCard key={i} />
          ))}
        </div>
      ) : visibleBoards.length === 0 ? (
        <Section flush>
          <EmptyState
            icon={<IconFlame size={20} />}
            title="没有该分类的榜单"
            desc="换一个分类看看，或点右上角「强制刷新」重新聚合各平台热榜。"
          />
        </Section>
      ) : (
        <div className="grid cols-2">
          {visibleBoards.map((board) => {
            const ok = board.status === 'success';
            return (
              <article
                key={board.board_id}
                className="card"
                style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}
              >
                <header
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 10,
                    flexWrap: 'wrap',
                    rowGap: 8,
                    padding: '12px 16px',
                    borderBottom: '1px solid var(--line-soft)',
                  }}
                >
                  <span
                    style={{
                      width: 28,
                      height: 28,
                      borderRadius: 8,
                      background: 'var(--surface-2)',
                      display: 'grid',
                      placeItems: 'center',
                      fontSize: 14,
                      lineHeight: 1,
                      flex: 'none',
                    }}
                  >
                    {board.emoji || '📄'}
                  </span>
                  <div style={{ minWidth: 0, flex: '1 1 120px' }}>
                    <div className="truncate" style={{ fontSize: 14, fontWeight: 600, letterSpacing: '-0.01em' }}>
                      {board.name}
                    </div>
                    <div className="tiny faint truncate" style={{ marginTop: 1 }}>
                      {board.source}
                    </div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, flex: 'none' }}>
                    {board.cached ? <Pill tone="teal">缓存</Pill> : null}
                    <Pill tone={ok ? 'green' : 'red'}>{ok ? '成功' : '失败'}</Pill>
                    <span className="tiny faint num">{fmtNum(Math.round(board.latency_ms || 0))} ms</span>
                    <a
                      className="icon-btn"
                      href={board.site_url}
                      target="_blank"
                      rel="noreferrer"
                      title={`打开 ${board.source} 原站`}
                      style={{
                        width: 26,
                        height: 26,
                        borderRadius: 8,
                        border: 0,
                        background: 'transparent',
                        color: 'var(--text-3)',
                      }}
                    >
                      <IconExternal size={13} />
                    </a>
                    <button
                      className="icon-btn"
                      type="button"
                      title="单独刷新该榜单"
                      onClick={() => refreshSingleBoard(board.board_id)}
                      style={{
                        width: 26,
                        height: 26,
                        borderRadius: 8,
                        border: 0,
                        background: 'transparent',
                        color: 'var(--text-3)',
                      }}
                    >
                      <IconRefresh size={13} />
                    </button>
                  </div>
                </header>

                {!ok ? (
                  <div style={{ padding: '18px 16px' }}>
                    <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                      <span style={{ color: 'var(--orange)', flex: 'none', marginTop: 1 }}>
                        <IconAlert size={16} />
                      </span>
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-2)' }}>
                          该榜单源暂时不可用
                        </div>
                        <div className="tiny faint" style={{ marginTop: 3, wordBreak: 'break-word' }}>
                          {board.error_message || '上游接口暂无响应，可稍后重试。'}
                        </div>
                        <Button
                          size="small"
                          icon={<IconRefresh size={13} />}
                          style={{ marginTop: 12 }}
                          onClick={() => refreshSingleBoard(board.board_id)}
                        >
                          重试
                        </Button>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div style={{ maxHeight: 424, overflowY: 'auto' }}>
                    {board.items.length === 0 ? (
                      <div className="tiny faint" style={{ padding: '20px 16px' }}>
                        该榜单暂无条目
                      </div>
                    ) : (
                      board.items.map((item, idx) => (
                        <div
                          key={`${board.board_id}-${item.rank}`}
                          style={{
                            display: 'flex',
                            alignItems: 'flex-start',
                            gap: 10,
                            padding: '9px 16px',
                            borderBottom:
                              idx === board.items.length - 1 ? 'none' : '1px solid var(--line-soft)',
                            transition: 'background 160ms var(--ease)',
                          }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.background = 'var(--fill)';
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.background = 'transparent';
                          }}
                        >
                          <span
                            className="mono num"
                            style={{
                              width: 20,
                              flex: 'none',
                              textAlign: 'right',
                              fontSize: 11,
                              lineHeight: '20px',
                              color: item.rank <= 3 ? 'var(--text-2)' : 'var(--text-3)',
                            }}
                          >
                            {item.rank}
                          </span>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                              <a
                                href={item.url}
                                target="_blank"
                                rel="noreferrer"
                                title={item.title}
                                className="truncate"
                                style={{
                                  flex: 1,
                                  minWidth: 0,
                                  fontSize: 14,
                                  lineHeight: '20px',
                                  letterSpacing: '-0.01em',
                                  color: 'var(--text)',
                                  textDecoration: 'none',
                                }}
                                onMouseEnter={(e) => {
                                  e.currentTarget.style.color = 'var(--accent)';
                                }}
                                onMouseLeave={(e) => {
                                  e.currentTarget.style.color = 'var(--text)';
                                }}
                              >
                                {item.title}
                              </a>
                              {item.tag ? (
                                <span style={{ flex: 'none' }}>
                                  <Pill tone="orange">{item.tag}</Pill>
                                </span>
                              ) : null}
                              {item.video_platform ? (
                                <Tooltip
                                  title={
                                    item.video_platform === 'bilibili'
                                      ? '按 BV 号直接解析该视频下载直链'
                                      : item.video_platform === 'douyin'
                                        ? '以该热词检索抖音视频并解析下载直链'
                                          : '打开该条目详情'
                                  }
                                >
                                  <button
                                    type="button"
                                    onClick={() =>
                                      fetchVideoLinks(item.video_platform!, item.title, item.video_id)
                                    }
                                    style={{
                                      flex: 'none',
                                      width: 22,
                                      height: 22,
                                      padding: 0,
                                      border: 0,
                                      borderRadius: 6,
                                      background: 'transparent',
                                      color: 'var(--text-3)',
                                      display: 'grid',
                                      placeItems: 'center',
                                      cursor: 'pointer',
                                    }}
                                    onMouseEnter={(e) => {
                                      e.currentTarget.style.color = 'var(--accent)';
                                      e.currentTarget.style.background = 'var(--fill)';
                                    }}
                                    onMouseLeave={(e) => {
                                      e.currentTarget.style.color = 'var(--text-3)';
                                      e.currentTarget.style.background = 'transparent';
                                    }}
                                  >
                                    <IconDownload size={13} />
                                  </button>
                                </Tooltip>
                              ) : null}
                              {item.hot_value ? (
                                <span
                                  className="num nowrap"
                                  style={{ flex: 'none', fontSize: 11.5, ...hotTone(item.rank) }}
                                >
                                  {item.hot_value}
                                </span>
                              ) : null}
                            </div>
                            {item.subtitle ? (
                              <div className="tiny faint truncate" title={item.subtitle} style={{ marginTop: 1 }}>
                                {item.subtitle}
                              </div>
                            ) : null}
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                )}
              </article>
            );
          })}
        </div>
      )}

      <Modal
        open={linkModal.open}
        onCancel={() => setLinkModal((s) => ({ ...s, open: false }))}
        footer={null}
        width={920}
        title={
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, minWidth: 0, maxWidth: '100%' }}>
            <span style={{ color: 'var(--text-2)', display: 'inline-flex' }}>
              <IconDownload size={17} />
            </span>
            <span>下载直链</span>
            <span
              className="tiny faint"
              style={{
                fontWeight: 400,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                minWidth: 0,
              }}
            >
              {linkModal.title.slice(0, 40)}
            </span>
          </span>
        }
      >
        {linkModal.loading ? (
          <div>
            <div className="small muted" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span className="dot accent" />
              正在解析视频并获取下载直链…（抖音关键词桥接最长约 20 秒）
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 16 }}>
              {[0, 1, 2].map((i) => (
                <div key={i} style={{ height: 54, borderRadius: 12, background: 'var(--surface-2)' }} />
              ))}
            </div>
          </div>
        ) : linkModal.error ? (
          <div style={{ padding: '14px 16px', borderRadius: 14, background: 'var(--orange-soft)' }}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                fontSize: 12.5,
                fontWeight: 600,
                color: 'var(--orange)',
              }}
            >
              <IconAlert size={15} />
              未获取到下载直链
            </div>
            <div style={{ marginTop: 6, fontSize: 12.5, color: 'var(--text-2)', wordBreak: 'break-word' }}>
              {linkModal.error}
            </div>
            <div className="tiny faint" style={{ marginTop: 6 }}>
              抖音/微博等关键词类榜单依赖第三方检索桥接，偶发限流时重试即可；B站榜单按 BV 号直取，通常更稳定。
            </div>
          </div>
        ) : (
          <div>
            {linkModal.videos.map((v, i) => (
              <div
                key={`${v.platform}-${v.id}-${i}`}
                style={{
                  padding: i === 0 ? '0 0 12px' : '12px 0',
                  borderTop: i === 0 ? 'none' : '1px solid var(--line-soft)',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
                  <Pill tone={v.platform === 'douyin' ? 'red' : 'accent'}>{v.platform_name}</Pill>
                  <span
                    style={{
                      flex: '1 1 240px',
                      minWidth: 0,
                      fontSize: 13.5,
                      fontWeight: 600,
                      letterSpacing: '-0.01em',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {v.title.slice(0, 60)}
                  </span>
                  {v.author ? <span className="tiny faint">{v.author}</span> : null}
                  {v.duration_text ? <span className="tiny faint num">{v.duration_text}</span> : null}
                  <Pill tone="green">{v.tracks.length} 条直链</Pill>
                </div>
                <Table<VideoTrack>
                  rowKey={(r) => `${r.label}-${r.url.slice(-20)}`}
                  dataSource={v.tracks}
                  pagination={false}
                  size="small"
                  scroll={{ x: 800 }}
                  columns={[
                    {
                      title: '清晰度 / 轨道',
                      dataIndex: 'label',
                      width: 170,
                      render: (label: string, r) => (
                        <span style={{ display: 'inline-flex', gap: 6, flexWrap: 'wrap' }}>
                          <Pill tone={r.watermark ? 'default' : r.kind === 'audio' ? 'purple' : 'green'}>
                            {label}
                          </Pill>
                          {r.watermark === false ? <Pill tone="orange">无水印</Pill> : null}
                        </span>
                      ),
                    },
                    {
                      title: '规格',
                      width: 180,
                      render: (_, r) => (
                        <span
                          className="tiny faint num"
                          style={{ display: 'inline-flex', alignItems: 'center', flexWrap: 'wrap', gap: 6 }}
                        >
                          {r.width && r.height ? <span>{r.width}×{r.height}</span> : null}
                          {r.size_bytes ? <span>{formatBytes(r.size_bytes)}</span> : null}
                          {r.codec ? <code className="code-inline">{r.codec}</code> : null}
                        </span>
                      ),
                    },
                    {
                      title: '直链',
                      dataIndex: 'url',
                      width: 300,
                      render: (url: string) => (
                        <code
                          className="code-inline"
                          title={url}
                          style={{
                            display: 'inline-block',
                            maxWidth: '100%',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                            verticalAlign: 'middle',
                          }}
                        >
                          {url.length > 64 ? `${url.slice(0, 64)}…` : url}
                        </code>
                      ),
                    },
                    {
                      title: '操作',
                      width: 150,
                      render: (_, r) => (
                        <span style={{ display: 'inline-flex', gap: 6 }}>
                          <Button size="small" onClick={() => copyUrl(r.url)}>
                            复制
                          </Button>
                          <Button
                            size="small"
                            icon={<IconDownload size={13} />}
                            onClick={() => window.open(r.url, '_blank', 'noopener,noreferrer')}
                          >
                            下载
                          </Button>
                        </span>
                      ),
                    },
                  ]}
                />
              </div>
            ))}
          </div>
        )}
        {!linkModal.loading && !linkModal.error && linkModal.note ? (
          <div className="tiny faint" style={{ marginTop: 12 }}>
            {linkModal.note}
          </div>
        ) : null}
      </Modal>
    </div>
  );
};
