import { useEffect, useRef, type FormEvent } from 'react';
import { ArrowUp, Check, LoaderCircle, Plus, Square } from 'lucide-react';
import type { Agent } from './api';

type Props = {
  agent?: Agent;
  operation?: Agent['operations'][number];
  message: string;
  busy: boolean;
  loading: boolean;
  running: boolean;
  onMessage: (value: string) => void;
  onOperation: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
  onCancel: () => void;
};

export function Composer({ agent, operation, message, busy, loading, running, onMessage, onOperation, onSubmit, onCancel }: Props) {
  const input = useRef<HTMLTextAreaElement>(null);
  const menu = useRef<HTMLDetailsElement>(null);
  const freeform = Boolean(operation?.allows_message);
  const value = freeform ? message : operation?.label ?? '';
  const blocked = busy || loading || running;

  useEffect(() => {
    if (!input.current) return;
    input.current.style.height = '24px';
    input.current.style.height = `${Math.min(input.current.scrollHeight, 144)}px`;
  }, [value, agent?.id]);

  useEffect(() => {
    function dismiss(event: PointerEvent) {
      if (menu.current && !menu.current.contains(event.target as Node)) menu.current.open = false;
    }
    document.addEventListener('pointerdown', dismiss);
    return () => document.removeEventListener('pointerdown', dismiss);
  }, []);

  return <form className="composer" onSubmit={onSubmit}>
    {(agent?.operations.length ?? 0) > 1 && <details className="operation-menu" ref={menu} onKeyDown={event => {
      if (event.key === 'Escape') { menu.current!.open = false; menu.current?.querySelector('summary')?.focus(); }
    }}>
      <summary role="button" className="composer-add" aria-label="Choose action" title="Choose action"><Plus size={21} strokeWidth={1.6} /></summary>
      <div className="operation-options" role="group" aria-label="Available actions">
        {agent?.operations.map(item => <button key={item.id} type="button" disabled={blocked}
          aria-pressed={item.id === operation?.id} title={item.description} onClick={() => {
            onOperation(item.id); menu.current!.open = false; input.current?.focus();
          }}><span>{item.label}</span>{item.id === operation?.id && <Check size={15} />}</button>)}
      </div>
    </details>}
    <textarea ref={input} aria-label={freeform ? `Message ${agent?.name}` : 'Selected action'}
      placeholder={operation ? `Message ${agent?.name}` : loading ? 'Loading...' : 'Task entry not configured'}
      value={value} onChange={event => onMessage(event.target.value)} readOnly={!freeform}
      disabled={blocked || !operation} maxLength={8000} rows={1}
      onKeyDown={event => {
        if (freeform && event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
          event.preventDefault();
          if (message.trim() && !blocked) event.currentTarget.form?.requestSubmit();
        }
      }} />
    {running ? <button type="button" className="send-button stop" aria-label="Stop run" title="Stop run" disabled={busy} onClick={onCancel}><Square size={14} fill="currentColor" /></button>
      : <button type="submit" className="send-button" aria-label="Run" title={freeform ? 'Send message' : `Run ${operation?.label ?? 'action'}`}
        disabled={!operation || busy || loading || (freeform && !message.trim())}>
        {busy ? <LoaderCircle size={19} className="spin" /> : <ArrowUp size={22} strokeWidth={1.8} />}
      </button>}
  </form>;
}