import type { CSSProperties } from 'react';
import type { Agent } from './api';

export function Identity({ agent, small = false }: { agent?: Agent; small?: boolean }) {
  if (!agent) return <span className={`identity-placeholder ${small ? 'small' : ''}`} aria-hidden="true" />;
  return <span className={`avatar ${small ? 'small' : ''} ${agent.shape}`}
    style={{ '--identity': agent.color } as CSSProperties} aria-hidden="true">
    <span className="monogram" />
  </span>;
}

export function MeshIdentity({ members, small = false }: { members: Agent[]; small?: boolean }) {
  const visible = members.slice(0, 3);
  return <span className={`mesh-identity ${small ? 'small' : ''} count-${visible.length}`} aria-hidden="true">
    {visible.length ? visible.map(member => <Identity key={member.id} agent={member} />) : <Identity small={small} />}
    {members.length > 3 && <span className="member-overflow">+{members.length - 3}</span>}
  </span>;
}