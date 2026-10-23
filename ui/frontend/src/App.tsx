import { useEffect, useRef, useState, type FormEvent } from 'react';
import { ArrowDown, ArrowUp, Check, ChevronDown, Circle, Copy, LoaderCircle, Menu, Monitor, RotateCcw, Search, Settings2, X } from 'lucide-react';
import { addEvent, api, eventSchema, mergeRuns, plainText, runPreview, runStatusLabel, runUpdateSchema, type Agent, type Health, type Run, type RunEvent } from './api';
import { Identity as Avatar, MeshIdentity } from './Identity';
import { Inspector } from './Inspector';
import { Composer } from './Composer';
import { PeerMessages, messageGroups } from './PeerMessages';
import { ConsentRequest } from './ConsentRequest';
import { CredentialRequest } from './CredentialRequest';
import { ApprovalRequest, approvalDecision } from './ApprovalRequest';
import { Markdown } from './Markdown';
import { ActivityTimeline } from './ActivityTimeline';
import { ArtifactCard } from './ArtifactCard';
import { OutputView } from './OutputView';

const time = (value: string) => new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
function Status({ run }: { run: Run }) {
  const status = run.status;
  return <span className={`run-status ${status}`}>
    {status === 'running' ? <LoaderCircle className="spin" size={13} /> : status === 'completed' ? <Check size={13} /> : <Circle size={10} />}
    {runStatusLabel(run)}
  </span>;
}

function isPublicStructuredEvent(event: RunEvent, events: RunEvent[]) {
  if (event.type !== 'structured_output') return false;
  const data = event.data.data;
  if (!data) return false;
  const keys = new Set(Object.keys(data));
  if (keys.has('owner_id') && keys.has('objective') && keys.has('success_criteria')) {
    return false;
  }
  if (event.data.output_type === 'opportunity_set') {
    return !events.some(candidate => (
      candidate.type === 'structured_output'
      && candidate.seq > event.seq
      && candidate.data.output_type !== 'opportunity_set'
    ));
  }
  return true;
}

function Result({ event, agent, compact = false }: { event: RunEvent; agent?: Agent; compact?: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState('');
  const text = event.data.text ?? event.data.message ?? '';
  const obligation = event.data.obligation_status;
  const long = text.length > (compact ? 480 : 1800);
  async function copy() {
    try { await navigator.clipboard.writeText(text); setCopied(true); setError(''); }
    catch { setError('Clipboard unavailable. Select the output to copy it.'); }
  }
  return <article className={`result ${compact ? 'compact' : ''}`}>
    <div className="message-meta"><Avatar agent={agent} small /><strong>{agent?.name ?? 'Result'}</strong><time>{time(event.timestamp)}</time>
      {obligation && <span className={`goal-outcome ${obligation}`}>Goal {obligation}</span>}
      <button className="icon-button" aria-label="Copy result" title="Copy result" onClick={() => void copy()}>{copied ? <Check size={15} /> : <Copy size={15} />}</button>
    </div>
    <div className={`result-text ${long && !expanded ? 'condensed' : ''}`}><Markdown text={text} /></div>
    {long && <button className="text-button" onClick={() => setExpanded(!expanded)}>{expanded ? 'Collapse output' : 'Expand full output'}<ChevronDown className={expanded ? 'rotated' : ''} size={15} /></button>}
    {error && <p role="alert" className="error-text">{error}</p>}
  </article>;
}

// A refresh should land on the conversation the agent already had, not a blank pane.
function latestFor(runs: Run[], agentId?: string): string | null {
  if (!agentId) return null;
  const latest = runs.filter(item => item.agent_id === agentId)
    .sort((left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at))[0];
  return latest?.id ?? null;
}

// A mesh of one agent is that agent's product conversation; the bare agent would skip its goals and approvals.
function listedAgents(agents: Agent[]): Agent[] {
  const represented = new Set(agents.filter(item => item.kind === 'mesh' && item.members.length === 1)
    .map(item => item.members[0]));
  return agents.filter(item => !represented.has(item.id));
}

export function App() {
  const savedSelection = () => new URLSearchParams(window.location.hash.slice(1));
  const [agents, setAgents] = useState<Agent[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [workspaceName, setWorkspaceName] = useState('JarvisCore Agents');
  const [agentId, setAgentId] = useState(() => savedSelection().get('agent') ?? '');
  const [runId, setRunId] = useState<string | null>(() => savedSelection().get('task'));
  const [operationId, setOperationId] = useState(() => savedSelection().get('action') ?? '');
  const [message, setMessage] = useState('');
  const [search, setSearch] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const [sidebar, setSidebar] = useState(false);
  const [fault, setFault] = useState<'desk' | 'activity' | null>(null);
  const [follow, setFollow] = useState(true);
  const [inspection, setInspection] = useState(false);
  const [inspectionTarget, setInspectionTarget] = useState('');
  const selection = useRef({ agentId, runId, operationId, message });
  const knownRuns = useRef(new Set<string>());
  const visible = useRef<Run[]>([]);
  const scroll = useRef<HTMLDivElement>(null);

  // Streams and fetches resolve outside render; they read the selection as committed.
  useEffect(() => {
    const url = new URL(window.location.href);
    const connectionId = url.searchParams.get('connection_id');
    const succeeded = url.searchParams.get('status') === 'success';
    const taskId = url.searchParams.get('run_id')
      ?? new URLSearchParams(url.hash.slice(1)).get('task');
    if (!connectionId || !succeeded || !taskId) return;
    url.search = '';
    window.history.replaceState(window.history.state, '', url);
    api.resume(taskId, connectionId)
      .then(saved => setRuns(current => mergeRuns(current, [saved])))
      .catch(reason => setError(reason instanceof Error ? reason.message : 'Unable to resume the task.'));
  }, []);

  useEffect(() => {
    selection.current = { agentId, runId, operationId, message };
    visible.current = runs;
  });

  useEffect(() => {
    function restoreSelection() {
      const saved = savedSelection();
      setAgentId(saved.get('agent') ?? '');
      setRunId(saved.get('task'));
      setOperationId(saved.get('action') ?? '');
      setMessage('');
      setLoading(true);
      setRetry(value => value + 1);
    }
    window.addEventListener('hashchange', restoreSelection);
    return () => window.removeEventListener('hashchange', restoreSelection);
  }, []);

  useEffect(() => {
    let active = true;
    async function connect() {
      while (active) {
        try {
          const [available, history, server, workspace] = await Promise.all([
            api.agents(), api.runs(), api.health(), api.workspace(),
          ]);
          if (!active) return;
          const saved = selection.current;
          const selectedRun = history.find(item => item.id === saved.runId);
          const selectedAgent = available.find(item => item.id === saved.agentId)
            ?? available.find(item => item.id === selectedRun?.agent_id) ?? listedAgents(available)[0];
          setAgents(available); setRuns(history); setHealth(server); setError('');
          knownRuns.current = new Set(history.map(item => item.id));
          setWorkspaceName(workspace.name);
          setAgentId(selectedAgent?.id ?? '');
          setRunId(selectedRun && selectedRun.agent_id === selectedAgent?.id
            ? selectedRun.id : latestFor(history, selectedAgent?.id));
          setOperationId(selectedAgent?.operations.some(item => item.id === saved.operationId) ? saved.operationId : '');
          setLoading(false);
          return;
        } catch (reason) {
          if (!active) return;
          setError(reason instanceof Error ? reason.message : 'Unable to reach the desk.');
          setLoading(false);
          await new Promise(resolve => window.setTimeout(resolve, 1000));
        }
      }
    }
    void connect();
    return () => { active = false; };
  }, [retry]);

  const agent = agents.find(item => item.id === agentId);
  const operation = agent?.operations.find(item => item.id === operationId) ?? agent?.operations[0];
  const run = agent ? runs.find(item => item.id === runId && item.agent_id === agentId) : undefined;
  const activeRun = runs.find(item => item.agent_id === agentId && ['running', 'waiting'].includes(item.status));
  const history = runs.filter(item => item.agent_id === agentId)
    .sort((left, right) => Date.parse(left.created_at) - Date.parse(right.created_at));
  const latestRun = history.at(-1);
  const runningIds = runs.filter(item => item.status === 'running').map(item => item.id).join(',');
  const [selectedAgent, selectedTask, selectedAction] = [agent?.id, run?.id, operation?.id];
  // A stale activity banner would otherwise outlive the run whose stream raised it.
  const connection = fault === 'desk' ? 'Reconnecting to desk updates...'
    : fault === 'activity' && runningIds ? 'Reconnecting to live activity...' : '';

  useEffect(() => {
    if (loading || !agents.length) return;
    let active = true;
    function receive(updated: Run[]) {
      if (!active) return;
      const fresh = updated.filter(item => !knownRuns.current.has(item.id));
      updated.forEach(item => knownRuns.current.add(item.id));
      const selected = selection.current;
      // Follow a new task only for a viewer already at the head of this thread.
      const atHead = !selected.runId || selected.runId === latestFor(visible.current, selected.agentId);
      setRuns(current => mergeRuns(current, updated));
      if (atHead && !selected.message.trim()) {
        const newTask = fresh.filter(item => item.agent_id === selected.agentId)
          .sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at))[0];
        if (newTask) setRunId(newTask.id);
      }
    }
    const stream = new EventSource('/api/runs/stream');
    stream.onopen = () => { if (active) setFault(current => current === 'desk' ? null : current); };
    stream.onmessage = event => {
      try { receive(runUpdateSchema.parse(JSON.parse(String(event.data))).runs); }
      catch { if (active) setError('Unsupported desk update. Refresh after updating the server.'); }
    };
    stream.onerror = () => {
      if (!active) return;
      setFault('desk');
      api.runs().then(receive).catch(() => { /* EventSource reconnects with Last-Event-ID. */ });
    };
    return () => { active = false; stream.close(); };
  }, [loading, agents]);

  useEffect(() => {
    if (loading || !selectedAgent) return;
    const saved = new URLSearchParams({ agent: selectedAgent });
    if (selectedTask) saved.set('task', selectedTask);
    if (selectedAction) saved.set('action', selectedAction);
    const url = new URL(window.location.href);
    url.hash = saved.toString();
    window.history.replaceState(window.history.state, '', url);
  }, [loading, selectedAgent, selectedTask, selectedAction]);

  useEffect(() => {
    if (!runningIds) return;
    let alive = true;
    const streams = runningIds.split(',').map(id => {
      const stream = new EventSource(`/api/runs/${encodeURIComponent(id)}/events`);
      stream.onopen = () => { if (alive) setFault(current => current === 'activity' ? null : current); };
      stream.onmessage = messageEvent => {
        if (!alive) return;
        try {
          const event = eventSchema.parse(JSON.parse(String(messageEvent.data)));
          setRuns(current => current.map(item => item.id === id ? addEvent(item, event) : item));
          if (event.type === 'completed' || event.type === 'cancelled') stream.close();
        } catch { stream.close(); setError('Unsupported live event. Refresh to reload the saved run.'); }
      };
      stream.onerror = () => {
        if (!alive) return;
        setFault('activity');
        api.run(id).then(saved => {
          if (!alive) return;
          setRuns(current => mergeRuns(current, [saved]));
          if (saved.status !== 'running') stream.close();
        }).catch(() => { /* EventSource reconnects with Last-Event-ID. */ });
      };
      return stream;
    });
    return () => { alive = false; streams.forEach(stream => stream.close()); };
  }, [runningIds]);

  const conversationRevision = history.map(item => `${item.id}:${item.events.length}`).join(',');
  useEffect(() => { if (follow) scroll.current?.scrollTo({ top: scroll.current.scrollHeight, behavior: 'instant' }); }, [conversationRevision, follow]);

  function chooseAgent(id: string) {
    setAgentId(id); setRunId(latestFor(runs, id)); setOperationId(''); setMessage(''); setSidebar(false); setFollow(true);
  }

  async function start(event: FormEvent) {
    event.preventDefault();
    if (!agent || !operation || activeRun || busy || (operation.allows_message && !message.trim())) return;
    setBusy(true); setError('');
    try {
      const created = await api.start(agent.id, operation.id, operation.allows_message ? message.trim() || undefined : undefined);
      setRuns(current => mergeRuns(current, [created])); setRunId(created.id); setMessage(''); setFollow(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The run could not start.');
      api.runs().then(saved => { setRuns(current => mergeRuns(current, saved)); }).catch(() => { /* The banner already reports the failure. */ });
    } finally { setBusy(false); }
  }

  async function cancel() {
    if (!activeRun || busy) return;
    setBusy(true); setError('');
    try {
      const saved = await api.cancel(activeRun.id);
      setRuns(current => mergeRuns(current, [saved]));
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Cancellation failed.'); }
    finally { setBusy(false); }
  }

  async function reconcile(id: string) {
    if (busy || activeRun) return;
    setBusy(true); setError('');
    try {
      const saved = await api.reconcile(id);
      setRuns(current => mergeRuns(current, [saved])); setRunId(id); setFollow(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Goal reconciliation failed.');
    } finally { setBusy(false); }
  }

  const visibleAgents = listedAgents(agents).filter(item => `${item.name} ${item.blueprint} ${item.capabilities.join(' ')}`.toLowerCase().includes(search.toLowerCase()));
  const membersOf = (mesh: Agent) => agents.filter(item => mesh.members.includes(item.id));
  const selectedMembers = agent?.kind === 'mesh' ? membersOf(agent) : [];
  const incomingFor = (id: string) => runs.flatMap(saved => saved.events.map(event => ({ ...event, sourceRun: saved.id })))
    .filter(event => event.type === 'peer_message' && (event.data.recipient_id === id
      || event.data.messages?.some(message => message.sender_id === id)))
    .sort((left, right) => Date.parse(left.timestamp) - Date.parse(right.timestamp) || left.seq - right.seq);
  const incoming = incomingFor(agentId);
  const historyRunIds = new Set(history.map(saved => saved.id));
  const externalPeerEvents = incoming.filter(event => !historyRunIds.has(event.sourceRun));
  function agentRow(item: Agent) {
    const latest = runs.filter(saved => saved.agent_id === item.id)
      .sort((left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at))[0];
    const working = latest?.status === 'running';
    const received = incomingFor(item.id).at(-1);
    const showReceived = received && (!latest || Date.parse(received.timestamp) > Date.parse(latest.updated_at));
    const preview = showReceived ? plainText(received.data.messages?.map(message => message.text).join(' ') ?? '')
      : latest ? runPreview(latest) : '';
    const updated = showReceived ? received.timestamp : latest?.updated_at;
    return <button key={item.id} className={`agent-row ${agentId === item.id ? 'selected' : ''}`} onClick={() => chooseAgent(item.id)} aria-label={item.name} aria-current={agentId === item.id ? 'page' : undefined}>
      {item.kind === 'mesh' ? <MeshIdentity members={membersOf(item)} /> : <Avatar agent={item} />}
      <span className="agent-copy"><span className="agent-heading">
        <strong title={item.name}>{item.name}</strong>{working && <span className="busy-dot" />}
        {updated && <time dateTime={updated}>{time(updated)}</time>}
      </span><small>{preview}</small></span>
    </button>;
  }
  return <div className={`desk ${inspection ? 'with-inspector' : ''}`}>
    {sidebar && <button className="scrim" aria-label="Close navigation" onClick={() => setSidebar(false)} />}
    <aside className={`sidebar ${sidebar ? 'open' : ''}`}>
      <div className="brand"><img className="wordmark" src="/brand/jarviscore-wordmark.svg" width="120" height="19" alt="JarvisCore" /><span className="brand-suffix">Agents</span>
        <button className="icon-button mobile" aria-label="Close navigation" onClick={() => setSidebar(false)}><X size={18} /></button>
      </div>
      <label className="search"><Search size={17} /><input value={search} onChange={event => setSearch(event.target.value)} aria-label="Search agents" placeholder="Search agents" /></label>
      <nav aria-label="Agents" className="roster">
        {visibleAgents.filter(item => item.kind === 'agent').map(agentRow)}
        {visibleAgents.filter(item => item.kind === 'mesh').map(agentRow)}
        {!loading && !agents.length && <p className="sidebar-note">No adapters registered.</p>}
        {agents.length > 0 && !visibleAgents.length && <p className="sidebar-note">No matching agents.</p>}
      </nav>
      <footer className="sidebar-footer"><Monitor size={17} /><span>{workspaceName === 'JarvisCore Agents' ? 'Local workspace' : workspaceName}<small>{health?.framework_version ? `JarvisCore ${health.framework_version}` : loading ? 'Connecting...' : 'Framework unavailable'}</small></span><button className="icon-button" aria-label="Workspace configuration" title="Workspace configuration" onClick={() => { setInspection(!inspection); setSidebar(false); }}><Settings2 size={17} /></button></footer>
    </aside>
    <main className="workspace">
      <header className="topbar">
        <button className="icon-button mobile" aria-label="Open navigation" onClick={() => setSidebar(true)}><Menu size={20} /></button>
        {agent?.kind === 'mesh' ? <MeshIdentity members={selectedMembers} small /> : <Avatar agent={agent} small />}<div className="topbar-title"><strong title={agent?.name}>{agent?.name ?? (loading ? 'Loading...' : 'No agent selected')}</strong></div>
        <div className="topbar-actions">{(activeRun ?? latestRun) && <Status run={(activeRun ?? latestRun)!} />}
          <button className="icon-button" aria-label="Inspect framework" title="Inspect framework" aria-pressed={inspection} onClick={() => setInspection(!inspection)}><Settings2 size={17} /></button>
        </div>
      </header>
      {error && <div className="error-banner" role="alert"><span>{error}</span><button className="icon-button" aria-label="Dismiss error" onClick={() => setError('')}><X size={16} /></button></div>}
      {connection && <div className="connection-banner" role="status">{connection}</div>}
      <div className="transcript" ref={scroll} onScroll={() => { const node = scroll.current; if (node) setFollow(node.scrollHeight - node.scrollTop - node.clientHeight < 80); }}>
        <div className="conversation">
          {!history.length && !incoming.length && <div className="empty-state">
            {agent?.kind === 'mesh' ? <MeshIdentity members={selectedMembers} /> : <Avatar agent={agent} />}<h1>{agent?.name ?? (loading ? 'Loading...' : 'No agents connected')}</h1>
            {agent && (activeRun || !agent.operations.length) && <div className="availability">{activeRun ? 'Task in progress' : 'Mesh task handler not configured'}</div>}
            {activeRun && <button className="text-button" onClick={() => setRunId(activeRun.id)}>View active run<ArrowUp size={16} /></button>}
          </div>}
          {externalPeerEvents.length > 0 && messageGroups(externalPeerEvents).map(group => <PeerMessages
            key={`${group[0].sourceRun}-${group[0].seq}`} events={group} agents={agents} selectedId={agentId} onSelect={chooseAgent} />)}
          {history.map((savedRun, index) => {
            const events = savedRun.events;
            const isRunning = savedRun.status === 'running';
            const latestStatus = [...events].reverse().find(event => event.type === 'status');
            const latestActivity = [...events].reverse().find(event => event.type === 'activity'
              && (event.data.kind === 'agent' || event.data.kind === 'tool'));
            const latestProgress = [...events].reverse().find(event => event.type === 'status'
              || (event.type === 'activity' && (event.data.kind === 'agent' || event.data.kind === 'tool')));
            const working = latestProgress?.type === 'activity'
              ? `${latestProgress.data.agent ?? 'Agent'}: ${latestProgress.data.summary ?? ''}`
              : latestProgress?.data.message ?? latestStatus?.data.message ?? latestActivity?.data.summary ?? 'Starting...';
            const latestResult = [...events].reverse().find(event => event.type === 'result');
            const hasStructuredOutput = events.some(event => event.type === 'structured_output');
            const canReconcile = Boolean(
              agent?.supports_reconciliation && !activeRun
              && (savedRun.status === 'failed'
                || ['blocked', 'incomplete'].includes(latestResult?.data.obligation_status ?? ''))
            );
            const previous = history[index - 1];
            const startsDay = !previous || new Date(previous.created_at).toDateString() !== new Date(savedRun.created_at).toDateString();
            return <section className="conversation-turn" key={savedRun.id} data-run-id={savedRun.id}>
              {startsDay && <div className="run-date"><span>{new Date(savedRun.created_at).toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' })}</span></div>}
              <div className="request">
                <article className="request-message">{savedRun.message
                  ?? agent?.operations.find(op => op.id === savedRun.operation)?.label ?? savedRun.operation}</article>
                <time dateTime={savedRun.created_at}>{time(savedRun.created_at)}</time>
              </div>
              <ActivityTimeline events={events} running={isRunning} />
              {messageGroups(events).map(group => group[0].type === 'peer_message'
                ? <PeerMessages key={`${savedRun.id}-${group[0].seq}`} events={group} agents={agents} selectedId={agentId} onSelect={chooseAgent} />
                : group[0].type === 'structured_output'
                  ? (isPublicStructuredEvent(group[0], events) ? <OutputView key={`${savedRun.id}-${group[0].seq}`} event={group[0]} /> : null)
                : group[0].type === 'artifact' ? <ArtifactCard key={`${savedRun.id}-${group[0].seq}`} event={group[0]} />
                : group[0].type === 'consent_required' ? <ConsentRequest key={`${savedRun.id}-${group[0].seq}`} event={group[0]} />
                : group[0].type === 'credential_input_required' ? <CredentialRequest key={`${savedRun.id}-${group[0].seq}`} runId={savedRun.id} event={group[0]} onSaved={saved => setRuns(current => mergeRuns(current, [saved]))} />
                : group[0].type === 'approval_required' ? <ApprovalRequest key={`${savedRun.id}-${group[0].seq}`} runId={savedRun.id} event={group[0]}
                    decision={approvalDecision(savedRun, events, group[0])} onSaved={saved => setRuns(current => mergeRuns(current, [saved]))} />
                : group[0].type === 'error' ? <div className="inline-error" role="alert" key={group[0].seq}><span>{group[0].data.message ?? group[0].data.text}</span><button className="text-button" onClick={() => { const target = savedRun.context?.mesh_workflow_id; setInspectionTarget(typeof target === 'string' ? target : ''); setInspection(true); }}>Inspect trace</button></div>
                  : <Result key={`${savedRun.id}-${group[0].seq}`} event={group[0]} agent={agent} compact={hasStructuredOutput} />)}
              {isRunning ? <div className="working" role="status"><LoaderCircle className="spin" size={16} /><span>{working}</span></div> : <div className="run-end"><Status run={savedRun} /><time>{time(savedRun.updated_at)}</time>{canReconcile && <button className="text-button" type="button" disabled={busy} onClick={() => void reconcile(savedRun.id)}><RotateCcw size={14} />Continue goal</button>}</div>}
            </section>;
          })}
        </div>
      </div>
      {history.length > 0 && !follow && <button className="latest-button icon-button" aria-label="Jump to latest activity" title="Jump to latest activity" onClick={() => setFollow(true)}><ArrowDown size={18} /></button>}
      <div className="composer-area">
        <Composer agent={agent} operation={operation} message={message} busy={busy} loading={loading}
          running={Boolean(activeRun)} onMessage={setMessage} onOperation={setOperationId}
          onSubmit={event => void start(event)} onCancel={() => void cancel()} />
      </div>
    </main>
    {inspection && <Inspector health={health} initialWorkflow={inspectionTarget} onClose={() => { setInspection(false); setInspectionTarget(''); }} />}
  </div>;
}