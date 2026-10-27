export const fmtNum = (value: any, digits = 0): string => {
  const n = Number(value || 0);
  if (!Number.isFinite(n)) return '0';
  return n.toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
};

export const fmtCny = (value: any, digits = 2): string => `¥${fmtNum(value, digits)}`;

export const fmtCnyCompact = (value: any): string => {
  const n = Number(value || 0);
  if (n >= 10000) return `¥${(n / 10000).toFixed(1)}万`;
  return fmtCny(n, n >= 100 ? 0 : 2);
};

export const fmtPercent = (value: any, digits = 1): string => `${Number(value || 0).toFixed(digits)}%`;

export const fmtTime = (ts: number | string | null | undefined): string => {
  if (!ts) return '—';
  const numeric = typeof ts === 'number' ? ts : Number(ts);
  if (Number.isFinite(numeric) && numeric > 1e9) {
    return new Date(numeric * 1000).toLocaleString('zh-CN', { hour12: false });
  }
  const date = new Date(ts as string);
  if (Number.isNaN(date.getTime())) return String(ts);
  return date.toLocaleString('zh-CN', { hour12: false });
};

export const fmtDate = (ts: number | string | null | undefined): string => {
  if (!ts) return '—';
  const numeric = typeof ts === 'number' ? ts : Number(ts);
  if (Number.isFinite(numeric) && numeric > 1e9) {
    return new Date(numeric * 1000).toLocaleDateString('zh-CN');
  }
  return String(ts).slice(0, 10);
};

export const fmtDuration = (ms: number | null | undefined): string => {
  const n = Number(ms || 0);
  if (n <= 0) return '—';
  if (n < 1000) return `${Math.round(n)} ms`;
  if (n < 60000) return `${(n / 1000).toFixed(n < 10000 ? 2 : 1)} s`;
  return `${(n / 60000).toFixed(1)} min`;
};

export const shortId = (id: string, head = 8, tail = 4): string => {
  if (!id) return '—';
  if (id.length <= head + tail + 1) return id;
  return `${id.slice(0, head)}…${id.slice(-tail)}`;
};

export const todayMonth = (): string => new Date().toISOString().slice(0, 7);

export const relativeTime = (ts: number | null | undefined): string => {
  if (!ts) return '—';
  const diff = Date.now() / 1000 - Number(ts);
  if (diff < 60) return '刚刚';
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
  if (diff < 86400 * 30) return `${Math.floor(diff / 86400)} 天前`;
  return fmtDate(ts);
};
