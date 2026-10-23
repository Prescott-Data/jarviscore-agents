import { Fragment, type ReactNode } from 'react';

// Model output is never HTML: every node here is constructed, so a result can
// carry backticks and angle brackets without becoming markup.
const INLINE = /(\*\*[^*]+\*\*|\*[^*\n]+\*|`[^`\n]+`|\[[^\]\n]+\]\([^)\s]+\)|https?:\/\/[^\s<>()]*[^\s<>().,;:!?'"]|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?\b|\b[A-Za-z][\w-]*_[\w-]+\b|\b(?=[A-Za-z0-9_-]{12,}\b)(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]+\b)/g;

function safeHref(url: string): string | null {
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : null;
  } catch { return null; }
}

function inline(text: string, key: string): ReactNode[] {
  return text.split(INLINE).filter(Boolean).map((piece, index) => {
    const id = `${key}-${index}`;
    if (piece.startsWith('**') && piece.endsWith('**')) return <strong key={id}>{piece.slice(2, -2)}</strong>;
    if (piece.startsWith('`') && piece.endsWith('`')) return <code key={id}>{piece.slice(1, -1)}</code>;
    if (piece.startsWith('*') && piece.endsWith('*')) return <em key={id}>{piece.slice(1, -1)}</em>;
    const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(piece);
    const href = link ? safeHref(link[2]) : piece.startsWith('http') ? safeHref(piece) : null;
    if (href) {
      const parsed = new URL(href);
      const label = link?.[1] ?? (parsed.hostname.includes('docs.google.com') ? 'Google document'
        : parsed.hostname.includes('drive.google.com') ? 'Drive folder'
        : parsed.hostname.includes('calendar.google.com') ? 'Calendar event'
        : parsed.hostname.includes('hubspot.com') ? 'HubSpot record'
        : parsed.hostname.replace(/^www\./, ''));
      return <a key={id} className="entity-link" href={href} title={`${parsed.hostname}${parsed.pathname}`} target="_blank" rel="noreferrer noopener">{label}</a>;
    }
    if (/^[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}$/.test(piece)) return <a key={id} className="entity-email" href={`mailto:${piece}`}>{piece}</a>;
    if (/^\d{4}-\d{2}-\d{2}T/.test(piece)) return <time key={id} className="entity-time" dateTime={piece}>{piece.replace('T', ' ')}</time>;
    if (/^[A-Za-z][\w-]*_[\w-]+$/.test(piece)) return <code key={id} className="entity-step">{piece}</code>;
    if (/^(?=[A-Za-z0-9_-]{12,}$)(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]+$/.test(piece)) return <code key={id} className="entity-id">{piece}</code>;
    return <Fragment key={id}>{piece}</Fragment>;
  });
}

type Block =
  | { kind: 'heading'; level: 2 | 3; text: string }
  | { kind: 'paragraph'; text: string }
  | { kind: 'code'; text: string }
  | { kind: 'list'; items: { text: string; depth: number; ordered: boolean }[] };

export function blocks(markdown: string): Block[] {
  const lines = markdown.replace(/\r\n/g, '\n').split('\n');
  const parsed: Block[] = [];
  let paragraph: string[] = [];
  let code: string[] | null = null;

  const flush = () => {
    if (paragraph.length) parsed.push({ kind: 'paragraph', text: paragraph.join('\n') });
    paragraph = [];
  };

  for (const line of lines) {
    if (line.trimStart().startsWith('```')) {
      if (code) { parsed.push({ kind: 'code', text: code.join('\n') }); code = null; }
      else { flush(); code = []; }
      continue;
    }
    if (code) { code.push(line); continue; }

    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    const listItem = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/.exec(line);
    const previous = parsed[parsed.length - 1];

    if (heading) {
      flush();
      parsed.push({ kind: 'heading', level: heading[1].length <= 2 ? 2 : 3, text: heading[2].trim() });
    } else if (listItem) {
      flush();
      const item = {
        text: listItem[3],
        depth: Math.floor(listItem[1].replace(/\t/g, '  ').length / 2),
        ordered: /^\d/.test(listItem[2]),
      };
      if (previous?.kind === 'list') previous.items.push(item);
      else parsed.push({ kind: 'list', items: [item] });
    } else if (!line.trim()) {
      flush();
    } else if (previous?.kind === 'list' && paragraph.length === 0 && /^\s{2,}\S/.test(line)) {
      previous.items[previous.items.length - 1].text += `\n${line.trim()}`;
    } else {
      paragraph.push(line.trim());
    }
  }
  if (code) parsed.push({ kind: 'code', text: code.join('\n') });
  flush();
  return parsed;
}

export function Markdown({ text }: { text: string }) {
  function renderList(items: Extract<Block, { kind: 'list' }>['items'], key: string) {
    type Node = typeof items[number] & { children: Node[] };
    const roots: Node[] = [];
    const stack: Node[] = [];
    for (const item of items) {
      const depth = Math.min(item.depth, stack.length);
      const node: Node = { ...item, depth, children: [] };
      if (depth > 0) stack[depth - 1].children.push(node); else roots.push(node);
      stack[depth] = node;
      stack.length = depth + 1;
    }
    function groups(nodes: Node[], groupKey: string): ReactNode[] {
      const result: ReactNode[] = [];
      for (let start = 0; start < nodes.length;) {
        let end = start + 1;
        while (end < nodes.length && nodes[end].ordered === nodes[start].ordered) end++;
        const Tag = nodes[start].ordered ? 'ol' : 'ul';
        result.push(<Tag key={`${groupKey}-${start}`}>{nodes.slice(start, end).map((node, index) => {
          const itemKey = `${groupKey}-${start}-${index}`;
          const task = /^\[([ xX])\]\s+([\s\S]*)$/.exec(node.text);
          return <li key={itemKey} className={task ? 'task-item' : undefined}>
            {task && <input type="checkbox" checked={task[1] !== ' '} disabled aria-hidden="true" />}
            {inline(task ? task[2] : node.text, itemKey)}
            {node.children.length > 0 && groups(node.children, itemKey)}</li>;
        })}</Tag>);
        start = end;
      }
      return result;
    }
    return groups(roots, key);
  }
  return <div className="markdown">{blocks(text).map((block, index) => {
    const key = `b${index}`;
    if (block.kind === 'heading') {
      return block.level === 2 ? <h2 key={key}>{inline(block.text, key)}</h2>
        : <h3 key={key}>{inline(block.text, key)}</h3>;
    }
    if (block.kind === 'code') return <pre key={key}>{block.text}</pre>;
    if (block.kind === 'list') return <Fragment key={key}>{renderList(block.items, key)}</Fragment>;
    return <p key={key}>{inline(block.text, key)}</p>;
  })}</div>;
}
