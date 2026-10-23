import { useEffect, useState } from 'react';
import { Activity, ArrowLeft, Check, CircleAlert, Clock3, Coins, ExternalLink, Gauge, RefreshCw, Workflow, X } from 'lucide-react';
import { api, type Health, type Inspection, type Metrics, type Trace, type Workspace } from './api';

const label = (value: string) => value.replace(/^jarviscore_/, '').replaceAll('_', ' ')
  .replace(/\b\w/g, character => character.toUpperCase());

function metricValue(name: string, value: number) {
  if (name.endsWith('_seconds')) return `${value.toLocaleString(undefined, { maximumFractionDigits: 2 })} s`;
  if (name.includes('cost')) return `$${value.toLocaleString(undefined, { maximumFractionDigits: 4 })}`;
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export function Inspector({ health, onClose, initialWorkflow = '' }: {
  health: Health | null; onClose: () => void; initialWorkflow?: string;
}) {
  const [tab, setTab] = useState<'inspect' | 'settings' | 'metrics'>('inspect');
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [inspection, setInspection] = useState<Inspection | null>(null);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [trace, setTrace] = useState<Trace | null>(null);
  const [selected, setSelected] = useState(initialWorkflow);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let active = true;
    Promise.all([api.inspect(), api.workspace()]).then(([records, config]) => {
      if (active) { setInspection(records); setWorkspace(config); setError(''); }
    }).catch(reason => { if (active) setError(String(reason)); });
    return () => { active = false; };
  }, [refresh]);
  useEffect(() => {
    if (tab !== 'metrics') return;
    let active = true;
    api.metrics().then(value => { if (active) setMetrics(value); })
      .catch(reason => { if (active) setError(String(reason)); });
    return () => { active = false; };
  }, [tab, refresh]);
  useEffect(() => {
    if (!selected) return;
    let active = true;
    api.trace(selected).then(value => { if (active) setTrace(value); })
      .catch(reason => { if (active) setError(String(reason)); });
    return () => { active = false; };
  }, [selected, refresh]);
  return <section className="inspector" aria-label="Framework inspection">
    <header><strong>Observability</strong><button className="icon-button" aria-label="Refresh inspection" title="Refresh inspection" onClick={() => setRefresh(value => value + 1)}><RefreshCw size={16} /></button><button className="icon-button" aria-label="Close inspection" onClick={onClose}><X size={18} /></button></header>
    <div className="panel-tabs" role="tablist" aria-label="Workspace views">
      <button role="tab" aria-selected={tab === 'inspect'} onClick={() => setTab('inspect')}>Inspect</button>
      <button role="tab" aria-selected={tab === 'metrics'} onClick={() => setTab('metrics')}>Telemetry</button>
      <button role="tab" aria-selected={tab === 'settings'} onClick={() => setTab('settings')}>Configuration</button>
    </div>
    {error && <p role="alert" className="error-text">{error}</p>}
    <div className="panel-body">
      {tab === 'inspect' ? <>
        <div className="panel-caption"><Workflow size={13} />WORKFLOWS</div>
        {!inspection ? <p className="muted">Loading traces...</p> : !inspection.configured ? <p className="muted">Trace directory not configured.</p> : !inspection.workflows.length ? <p className="muted">No framework traces recorded.</p> : selected ? <>
          <button className="text-button" onClick={() => setSelected('')}><ArrowLeft size={14} />Workflows</button>
          <div className="trace-heading"><span>Workflow trace</span><code className="workflow-id">{selected}</code></div>
          <ol className="trace-list">{trace?.events.map((event, index) => <li key={index}>
            <span className="trace-marker">{event.type.includes('fail') || event.type.includes('error') ? <CircleAlert size={14} /> : <Check size={14} />}</span>
            <div><span className="trace-time">{event.timestamp.slice(11, 19)}</span><strong>{label(event.type)}</strong>
              {event.step_id && <code className="step-id">{event.step_id}</code>}
              {Object.entries(event.data).length > 0 && <dl className="trace-data">{Object.entries(event.data).map(([key, value]) => <div key={key}><dt>{label(key)}</dt><dd>{metricValue(key, value)}</dd></div>)}</dl>}
            </div>
          </li>)}</ol>
        </> : <div className="workflow-list">{inspection.workflows.map(workflow => <button key={workflow.id} onClick={() => { setTrace(null); setSelected(workflow.id); }}>
          <span className="workflow-heading"><strong>{workflow.display_name}</strong><span className={`workflow-status ${workflow.status}`}>{workflow.status}</span></span>
          <small>{workflow.reference} · {workflow.started}</small>
          <span className="workflow-stats"><span><Activity size={12} />{workflow.steps} steps</span><span><Gauge size={12} />{workflow.tokens.toLocaleString()} tokens</span><span><Clock3 size={12} />{workflow.duration || 'Unavailable'}</span>{workflow.failures > 0 && <span className="failed"><CircleAlert size={12} />{workflow.failures}</span>}</span>
        </button>)}</div>}
      </> : tab === 'metrics' ? <>
        <div className="panel-caption"><Activity size={13} />TELEMETRY</div>
        {!metrics ? <p className="muted">Loading metrics...</p> : metrics.status !== 'available' ? <p className="muted">Metrics endpoint unavailable.</p> : !metrics.samples.length ? <p className="muted">No JarvisCore metrics reported.</p> : <>{metrics.source === 'local_traces' && <p className="muted">Local trace totals. Configure Prometheus for live provider and model metrics.</p>}<div className="metric-list">{metrics.samples.map((sample, index) => <section className="metric-row" key={`${sample.name}-${index}`}>
          <div className="metric-copy"><strong>{label(sample.name)}</strong>{Object.keys(sample.labels).length > 0 && <span className="metric-labels">{Object.entries(sample.labels).map(([key, value]) => <small key={key}>{label(key)}: {value}</small>)}</span>}</div>
          <data value={sample.value}>{sample.name.includes('cost') ? <Coins size={13} /> : <Gauge size={13} />}{metricValue(sample.name, sample.value)}</data>
        </section>)}</div></>}
      </> : <>
        <div className="panel-caption"><Gauge size={13} />RUNTIME</div>
        <dl className="runtime-facts"><dt>Framework</dt><dd>{health?.framework_version ?? 'Unavailable'}</dd><dt>Install</dt><dd>{health?.framework_editable ? 'Editable checkout' : 'Distribution'}</dd><dt>Branch</dt><dd>{health?.framework_branch ?? 'Not reported'}</dd><dt>Revision</dt><dd>{health?.framework_revision?.slice(0, 12) ?? 'Not reported'}{health?.framework_dirty ? ' + local changes' : ''}</dd><dt>Source</dt><dd>{health?.framework_source ?? 'Not reported'}</dd></dl>
        <div className="panel-caption">CONNECTIONS</div>
        <dl className="runtime-facts"><dt>Configuration</dt><dd>{workspace?.configured ? workspace.name : 'Installed adapters'}</dd><dt>Traces</dt><dd>{workspace?.inspection ? 'Local framework records' : 'Not configured'}</dd><dt>Prometheus</dt><dd>{workspace?.metrics_url ? <a href={workspace.metrics_url} target="_blank" rel="noreferrer">Metrics endpoint <ExternalLink size={12} /></a> : 'Not configured'}</dd></dl>
      </>}
    </div>
  </section>;
}