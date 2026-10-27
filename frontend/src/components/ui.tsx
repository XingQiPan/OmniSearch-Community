import React, { useId, useMemo, useState } from 'react';
import { message } from 'antd';
import { IconCheck, IconCopy } from './icons';
import { fmtNum } from '../utils/format';

/* ==========================================================================
   Shared UI primitives — the visual vocabulary every page composes with.
   Keep them dumb: no data fetching, no business logic.
   ========================================================================== */

export type Tone = 'default' | 'accent' | 'green' | 'orange' | 'red' | 'purple' | 'teal';

/* ------------------------------ page header ------------------------------ */

export const PageHeader: React.FC<{
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  icon?: React.ReactNode;
  tags?: React.ReactNode;
  extra?: React.ReactNode;
}> = ({ title, subtitle, icon, tags, extra }) => (
  <div className="page-head">
    {icon ? <div className="page-head-icon">{icon}</div> : null}
    <div className="page-head-main">
      <div className="page-head-row">
        <h1 className="page-title">
          {title}
          {tags}
        </h1>
        {extra ? <div className="page-actions">{extra}</div> : null}
      </div>
      {subtitle ? <div className="page-sub">{subtitle}</div> : null}
    </div>
  </div>
);

/* --------------------------------- section -------------------------------- */

export const Section: React.FC<{
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  extra?: React.ReactNode;
  children?: React.ReactNode;
  flush?: boolean;
  tight?: boolean;
  gap?: boolean;
  style?: React.CSSProperties;
  className?: string;
  hoverable?: boolean;
}> = ({ title, subtitle, extra, children, flush, tight, gap, style, className, hoverable }) => (
  <section className={`card ${gap ? 'section-gap' : ''} ${hoverable ? 'hoverable' : ''} ${className || ''}`} style={style}>
    {title || extra ? (
      <header className="card-head">
        <div style={{ minWidth: 0 }}>
          <h3>{title}</h3>
          {subtitle ? <div className="sub">{subtitle}</div> : null}
        </div>
        {extra ? <div className="card-head-extra">{extra}</div> : null}
      </header>
    ) : null}
    <div className={`card-body ${flush ? 'flush' : ''} ${tight ? 'tight' : ''}`}>{children}</div>
  </section>
);

/* ---------------------------------- stats ---------------------------------- */

export const Stat: React.FC<{
  label: React.ReactNode;
  value: React.ReactNode;
  suffix?: React.ReactNode;
  hint?: React.ReactNode;
  icon?: React.ReactNode;
  tone?: Tone;
  spark?: number[];
  onClick?: () => void;
}> = ({ label, value, suffix, hint, icon, tone = 'accent', spark, onClick }) => (
  <div className="stat" style={{ cursor: onClick ? 'pointer' : undefined }} onClick={onClick}>
    <div className="stat-label">
      {icon ? <span style={{ color: `var(--${tone === 'default' ? 'text-3' : tone})` }}>{icon}</span> : null}
      {label}
    </div>
    <div className="stat-value">
      {value}
      {suffix ? <span className="stat-suffix">{suffix}</span> : null}
    </div>
    {hint ? <div className="stat-hint">{hint}</div> : null}
    {spark && spark.length > 1 ? <MiniSpark data={spark} color={`var(--${tone === 'default' ? 'text-3' : tone})`} /> : null}
  </div>
);

const MiniSpark: React.FC<{ data: number[]; color: string }> = ({ data, color }) => {
  const id = useId().replace(/:/g, '');
  const max = Math.max(1, ...data);
  const step = 100 / Math.max(1, data.length - 1);
  const pts = data.map((v, i) => `${(i * step).toFixed(2)},${(34 - (v / max) * 30).toFixed(2)}`).join(' ');
  return (
    <svg className="stat-spark" viewBox="0 0 100 36" preserveAspectRatio="none">
      <defs>
        <linearGradient id={`sp-${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.22" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={`0,36 ${pts} 100,36`} fill={`url(#sp-${id})`} />
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.4" vectorEffect="non-scaling-stroke" />
    </svg>
  );
};

/* ---------------------------------- pills ---------------------------------- */

export const Pill: React.FC<{
  tone?: Tone;
  children: React.ReactNode;
  outline?: boolean;
  style?: React.CSSProperties;
}> = ({ tone = 'default', children, outline, style }) => (
  <span className={`pill ${tone} ${outline ? 'outline' : ''}`} style={style}>
    {children}
  </span>
);

export const StatusDot: React.FC<{ tone?: 'green' | 'orange' | 'red' | 'accent' | 'default'; label?: React.ReactNode }> = ({
  tone = 'default',
  label,
}) => (
  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 12.5, color: 'var(--text-2)' }}>
    <span className={`dot ${tone}`} />
    {label}
  </span>
);

/* --------------------------------- toolbar --------------------------------- */

export const Toolbar: React.FC<{ children: React.ReactNode; right?: React.ReactNode }> = ({ children, right }) => (
  <div className="toolbar">
    {children}
    {right ? <div className="toolbar-spacer">{null}</div> : null}
    {right}
  </div>
);

/* -------------------------------- sub tabs -------------------------------- */

export const SubTabs: React.FC<{
  items: { key: string; label: React.ReactNode; icon?: React.ReactNode }[];
  value: string;
  onChange: (key: string) => void;
}> = ({ items, value, onChange }) => (
  <div className="subtabs" role="tablist">
    {items.map((item) => (
      <button
        key={item.key}
        role="tab"
        aria-selected={item.key === value}
        className={`subtab ${item.key === value ? 'active' : ''}`}
        onClick={() => onChange(item.key)}
        type="button"
      >
        {item.icon}
        {item.label}
      </button>
    ))}
  </div>
);

/* ------------------------------- empty state ------------------------------ */

export const EmptyState: React.FC<{
  icon?: React.ReactNode;
  title: React.ReactNode;
  desc?: React.ReactNode;
  action?: React.ReactNode;
}> = ({ icon, title, desc, action }) => (
  <div className="empty">
    {icon ? <div className="empty-icon">{icon}</div> : null}
    <div className="empty-title">{title}</div>
    {desc ? <div className="empty-desc">{desc}</div> : null}
    {action ? <div style={{ marginTop: 14 }}>{action}</div> : null}
  </div>
);

/* -------------------------------- area chart ------------------------------- */

export const AreaChart: React.FC<{
  data: number[];
  labels?: string[];
  height?: number;
  tone?: Tone;
  formatValue?: (v: number) => string;
}> = ({ data, labels, height = 148, tone = 'accent', formatValue }) => {
  const id = useId().replace(/:/g, '');
  const safe = data && data.length ? data : [0, 0];
  const max = Math.max(1, ...safe);
  const min = Math.min(0, ...safe);
  const span = Math.max(1, max - min);
  const W = 100;
  const H = 40;
  const step = safe.length > 1 ? W / (safe.length - 1) : W;
  const points = safe.map((v, i) => ({
    x: i * step,
    y: H - ((v - min) / span) * (H - 4) - 2,
  }));

  const path = useMemo(() => {
    if (points.length < 2) return '';
    let d = `M ${points[0].x.toFixed(2)} ${points[0].y.toFixed(2)}`;
    for (let i = 0; i < points.length - 1; i += 1) {
      const p0 = points[i];
      const p1 = points[i + 1];
      const cx = (p0.x + p1.x) / 2;
      d += ` C ${cx.toFixed(2)} ${p0.y.toFixed(2)}, ${cx.toFixed(2)} ${p1.y.toFixed(2)}, ${p1.x.toFixed(2)} ${p1.y.toFixed(2)}`;
    }
    return d;
  }, [points]);

  const color = `var(--${tone === 'default' ? 'text-3' : tone})`;
  const total = safe.reduce((a, b) => a + b, 0);

  return (
    <div>
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ height }}>
        <defs>
          <linearGradient id={`area-${id}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.26" />
            <stop offset="100%" stopColor={color} stopOpacity="0.015" />
          </linearGradient>
        </defs>
        {[0.25, 0.5, 0.75].map((ratio) => (
          <line
            key={ratio}
            x1="0"
            x2={W}
            y1={H * ratio}
            y2={H * ratio}
            stroke="var(--line-soft)"
            strokeWidth="1"
            vectorEffect="non-scaling-stroke"
          />
        ))}
        <path d={`${path} L ${W} ${H} L 0 ${H} Z`} fill={`url(#area-${id})`} stroke="none" />
        <path d={path} fill="none" stroke={color} strokeWidth="1.8" vectorEffect="non-scaling-stroke" strokeLinecap="round" />
        <circle cx={points[points.length - 1].x} cy={points[points.length - 1].y} r="3" fill={color} stroke="var(--surface)" strokeWidth="1.5" />
      </svg>
      <div className="chart-axis">
        <span>{labels?.[0] || '—'}</span>
        <span>{formatValue ? formatValue(total) : `${fmtNum(total)} 次`}</span>
        <span>{labels?.[labels.length - 1] || '—'}</span>
      </div>
    </div>
  );
};

/* -------------------------------- bar list -------------------------------- */

export const BarList: React.FC<{
  items: { label: React.ReactNode; value: number; suffix?: React.ReactNode; tone?: string }[];
  format?: (v: number) => string;
}> = ({ items, format }) => {
  const max = Math.max(1, ...items.map((i) => i.value));
  return (
    <div>
      {items.map((item, idx) => (
        <div className="barlist-row" key={idx}>
          <div className="barlist-top">
            <span className="truncate">{item.label}</span>
            <span className="faint num nowrap">{format ? format(item.value) : fmtNum(item.value)}</span>
          </div>
          <div className="barlist-track">
            <div className="barlist-fill" style={{ width: `${Math.max(2, (item.value / max) * 100)}%`, background: item.tone }} />
          </div>
        </div>
      ))}
    </div>
  );
};

/* --------------------------------- copyable -------------------------------- */

export const CopyButton: React.FC<{ text: string; label?: string }> = ({ text, label }) => {
  const [done, setDone] = useState(false);
  const onClick = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setDone(true);
      message.success('已复制');
      window.setTimeout(() => setDone(false), 1600);
    } catch {
      message.warning('复制失败，请手动选中');
    }
  };
  return (
    <button className="icon-btn" onClick={onClick} type="button" title={label || '复制'} style={{ width: 30, height: 30, borderRadius: 8 }}>
      {done ? <IconCheck size={15} /> : <IconCopy size={15} />}
    </button>
  );
};

export const CodeBlock: React.FC<{ code: string; maxHeight?: number; language?: string }> = ({ code, maxHeight = 320, language }) => (
  <div style={{ position: 'relative' }}>
    <pre className="code-block" style={{ maxHeight, overflow: 'auto' }}>
      {code}
    </pre>
    <div style={{ position: 'absolute', top: 8, right: 8, opacity: 0.85 }}>
      <CopyButton text={code} label={language ? `复制 ${language}` : '复制'} />
    </div>
  </div>
);

/* ---------------------------------- misc ---------------------------------- */

export const KeyValue: React.FC<{ items: { label: React.ReactNode; value: React.ReactNode }[]; columns?: number }> = ({
  items,
  columns = 2,
}) => (
  <div
    style={{
      display: 'grid',
      gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
      gap: '14px 24px',
    }}
  >
    {items.map((item, idx) => (
      <div key={idx}>
        <div className="tiny faint" style={{ marginBottom: 2 }}>{item.label}</div>
        <div className="small">{item.value}</div>
      </div>
    ))}
  </div>
);

export const Mono: React.FC<{ children: React.ReactNode; style?: React.CSSProperties }> = ({ children, style }) => (
  <code className="code-inline" style={style}>{children}</code>
);

export const Kbd: React.FC<{ children: React.ReactNode }> = ({ children }) => <span className="kbd">{children}</span>;
