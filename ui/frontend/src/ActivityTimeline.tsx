import { Check, ChevronDown, CircleCheckBig, FileText, LoaderCircle, Search, UserRound } from 'lucide-react';
import type { RunEvent } from './api';

const time = (value: string) => new Date(value).toLocaleTimeString([], {
  hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
});

function ActivityIcon({ event }: { event: RunEvent }) {
  if (event.data.kind === 'agent') return <UserRound size={15} />;
  if (event.data.kind === 'tool') return event.data.tool === 'search' ? <Search size={15} /> : <FileText size={15} />;
  return <CircleCheckBig size={15} />;
}

function activityLabel(event: RunEvent) {
  const agent = event.data.agent ?? 'Agent';
  return event.data.kind === 'decision' ? `${agent} decision` : agent;
}

export function ActivityTimeline({ events, running }: { events: RunEvent[]; running: boolean }) {
  const all = events.filter(event => event.type === 'activity'
    && (event.data.kind === 'agent' || event.data.kind === 'decision' || event.data.kind === 'tool'));
  // A finished tool call supersedes its own "started" row.
  const activity = all.filter((event, index) => !(event.data.kind === 'tool' && event.data.outcome === 'started'
    && all.slice(index + 1).some(later => later.data.kind === 'tool' && later.data.agent === event.data.agent
      && later.data.tool === event.data.tool && later.data.outcome !== 'started')));
  if (!activity.length) return null;
  const summary = running ? 'Working' : `${activity.length} update${activity.length === 1 ? '' : 's'}`;
  return <details className="activity" open={running || undefined}>
    <summary>
      <span>{running ? <LoaderCircle className="spin" size={16} /> : <Check size={16} />}Execution</span>
      <span className="activity-count">{summary}<ChevronDown size={15} /></span>
    </summary>
    <ol className="execution-tree">{activity.map(event => <li key={event.seq} className={event.data.outcome ?? event.data.kind ?? 'status'}>
      <span className="activity-node"><ActivityIcon event={event} /></span>
      <span className="activity-copy"><strong>{activityLabel(event)}</strong><span>{event.data.summary ?? event.data.message}</span></span>
      <time dateTime={event.timestamp}>{time(event.timestamp)}</time>
    </li>)}</ol>
  </details>;
}