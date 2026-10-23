import { Fragment, type CSSProperties } from 'react';
import { Identity } from './Identity';
import { Markdown } from './Markdown';
import type { Agent, RunEvent } from './api';

export function PeerMessages({ events, agents, selectedId, onSelect }: {
  events: RunEvent[]; agents: Agent[]; selectedId: string; onSelect: (id: string) => void;
}) {
  const messages = events.flatMap(event => event.data.messages ?? []);
  const senders = [...new Set(messages.map(message => message.sender_id))];
  const recipient = agents.find(agent => agent.id === events[0]?.data.recipient_id);
  const selectedSent = senders.includes(selectedId);
  function badge(id: string) {
    const agent = agents.find(item => item.id === id);
    return agent ? <button className="peer-badge" type="button" title={`Open ${agent.name}`} aria-label={`Open ${agent.name}`}
      style={{ '--peer-color': agent.color } as CSSProperties} onClick={() => onSelect(id)}>
      <Identity agent={agent} small /><span>{agent.name}</span>
    </button> : <span className="peer-unavailable">Unavailable peer</span>;
  }
  return <section className="peer-messages" aria-label="Peer messages">
    <header><span>{selectedSent ? `Sent${recipient ? ` to ${recipient.name}` : ''}`
      : `Received${recipient && recipient.id !== selectedId ? ` by ${recipient.name}` : ''} from`}</span>
      {senders.map((id, index) => <Fragment key={id}>{index > 0 && <span>{index === senders.length - 1 ? 'and' : ','}</span>}{badge(id)}</Fragment>)}
    </header>
    <div className="peer-message-body">{messages.map((message, index) => <div key={index} className="peer-message">
      {badge(message.sender_id)}<Markdown text={message.text} />
    </div>)}</div>
  </section>;
}

export function messageGroups<Event extends RunEvent>(events: Event[]): Event[][] {
  const groups: Event[][] = [];
  let previousEvent: RunEvent | undefined;
  for (const event of events) {
    if (!['result', 'structured_output', 'artifact', 'error', 'peer_message', 'consent_required', 'credential_input_required', 'approval_required'].includes(event.type)) continue;
    if (event.type === 'peer_message' && previousEvent?.type === 'peer_message') {
      const fingerprint = JSON.stringify([
        event.data.recipient_id,
        event.data.messages?.map(message => [message.sender_id, message.text]),
      ]);
      const previousFingerprint = JSON.stringify([
        previousEvent.data.recipient_id,
        previousEvent.data.messages?.map(message => [message.sender_id, message.text]),
      ]);
      const elapsed = new Date(event.timestamp).getTime() - new Date(previousEvent.timestamp).getTime();
      if (fingerprint === previousFingerprint && elapsed >= 0 && elapsed <= 2_000) continue;
    }
    const previous = groups[groups.length - 1];
    if (event.type === 'peer_message' && previous?.[0].type === 'peer_message'
      && previous[0].data.recipient_id === event.data.recipient_id) previous.push(event);
    else groups.push([event]);
    previousEvent = event;
  }
  return groups;
}