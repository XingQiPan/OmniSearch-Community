import React from 'react';
import { Tooltip } from 'antd';

/* --------------------------------------------------------------------------
   轻量 Markdown 渲染：覆盖模型报告与网页正文里常见的结构，
   正文中的 [n](URL) 渲染成可点击的引用角标。
   -------------------------------------------------------------------------- */

const splitRow = (line: string): string[] =>
  line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());

const isTableDivider = (line: string): boolean =>
  /^\|?[\s:|-]+\|[\s:|-]*$/.test(line.trim()) && line.includes('-');

const indentOf = (line: string): number => {
  const match = line.match(/^(\s*)/);
  return Math.min(3, Math.floor((match ? match[1].replace(/\t/g, '  ').length : 0) / 2));
};

export function renderMarkdownWithCitations(md: string) {
  if (!md) return null;
  const lines = md.split('\n');
  const blocks: React.ReactNode[] = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    // 代码块：``` 到下一个 ``` 原样保留
    if (trimmed.startsWith('```')) {
      const code: string[] = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        code.push(lines[i]);
        i++;
      }
      blocks.push(
        <pre key={`code-${i}`} className="code-block" style={{ margin: '12px 0', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
          {code.join('\n')}
        </pre>
      );
      continue;
    }

    // 表格：连续以 | 开头的行聚合渲染为真正的表格
    if (trimmed.startsWith('|')) {
      const tableLines: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        tableLines.push(lines[i]);
        i++;
      }
      i--; // 回退一行给外层 for 自增
      if (tableLines.length >= 2 && isTableDivider(tableLines[1])) {
        const header = splitRow(tableLines[0]);
        const rows = tableLines.slice(2).map(splitRow);
        blocks.push(
          <div key={`tbl-${i}`} className="md-table-wrap">
            <table className="md-table">
              <thead>
                <tr>
                  {header.map((h, hi) => (
                    <th key={hi}>{renderInlineFormatted(h)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((cells, ri) => (
                  <tr key={ri}>
                    {header.map((_, ci) => (
                      <td key={ci}>{renderInlineFormatted(cells[ci] ?? '')}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        );
      } else {
        // 不是合法表格，按等宽文本行显示
        tableLines.forEach((tl, ti) =>
          blocks.push(
            <div key={`tblline-${i}-${ti}`} className="md-raw-line">
              {renderInlineFormatted(tl)}
            </div>
          )
        );
      }
      continue;
    }

    if (!trimmed) {
      blocks.push(<div key={i} style={{ height: 10 }} />);
      continue;
    }
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      blocks.push(<hr key={i} className="hairline" style={{ margin: '16px 0' }} />);
      continue;
    }
    if (/^#{1,2}\s/.test(trimmed)) {
      blocks.push(
        <div key={i} className="md-h2">
          {renderInlineFormatted(trimmed.replace(/^#{1,2}\s+/, ''))}
        </div>
      );
      continue;
    }
    if (trimmed.startsWith('### ')) {
      blocks.push(
        <div key={i} className="md-h3">
          {renderInlineFormatted(trimmed.slice(4))}
        </div>
      );
      continue;
    }
    if (/^#{4,6}\s/.test(trimmed)) {
      blocks.push(
        <div key={i} className="md-h4">
          {renderInlineFormatted(trimmed.replace(/^#{4,6}\s+/, ''))}
        </div>
      );
      continue;
    }
    if (trimmed.startsWith('>')) {
      blocks.push(
        <div key={i} className="md-quote">
          {renderInlineFormatted(trimmed.replace(/^>\s?/, ''))}
        </div>
      );
      continue;
    }
    // 无序列表（按缩进区分层级）
    if (/^[-*+]\s+/.test(trimmed)) {
      blocks.push(
        <div key={i} className="md-li" style={{ paddingLeft: 4 + indentOf(line) * 18 }}>
          <span className="md-bullet">•</span>
          <span style={{ flex: 1, minWidth: 0 }}>{renderInlineFormatted(trimmed.replace(/^[-*+]\s+/, ''))}</span>
        </div>
      );
      continue;
    }
    // 有序列表
    const ordered = trimmed.match(/^(\d+)[.)]\s+(.*)$/);
    if (ordered) {
      blocks.push(
        <div key={i} className="md-li" style={{ paddingLeft: 4 + indentOf(line) * 18 }}>
          <span className="md-num">{ordered[1]}.</span>
          <span style={{ flex: 1, minWidth: 0 }}>{renderInlineFormatted(ordered[2])}</span>
        </div>
      );
      continue;
    }
    blocks.push(
      <div key={i} style={{ marginBottom: 6 }}>
        {renderInlineFormatted(line)}
      </div>
    );
  }

  return <div className="md-body">{blocks}</div>;
}

export function renderInlineFormatted(text: string) {
  // 依次识别 [label](url)、**粗体**、`行内代码`
  const parts = text.split(/(\[[^\]]+\]\([^)]+\)|\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.map((part, idx) => {
    const linkMatch = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (linkMatch) {
      const label = linkMatch[1];
      const url = linkMatch[2];
      const isNumberBadge = /^\d+$/.test(label.trim());
      return (
        <Tooltip key={idx} title={url}>
          <a href={url} target="_blank" rel="noreferrer" className={isNumberBadge ? 'cite-badge' : 'md-link'}>
            {label}
          </a>
        </Tooltip>
      );
    }
    const boldMatch = part.match(/^\*\*([^*]+)\*\*$/);
    if (boldMatch) {
      return (
        <strong key={idx} style={{ fontWeight: 600, color: 'var(--text)' }}>
          {boldMatch[1]}
        </strong>
      );
    }
    const codeMatch = part.match(/^`([^`]+)`$/);
    if (codeMatch) {
      return (
        <code key={idx} className="code-inline">
          {codeMatch[1]}
        </code>
      );
    }
    return <React.Fragment key={idx}>{part}</React.Fragment>;
  });
}
