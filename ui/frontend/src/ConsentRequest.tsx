import { ExternalLink, ShieldCheck } from 'lucide-react';

import type { RunEvent } from './api';

/**
 * The agent is waiting on a person, so the ask belongs where the person is.
 * The run stays open while this sits here: consenting is what unblocks it.
 */
export function ConsentRequest({ event }: { event: RunEvent }) {
  const provider = event.data.label ?? event.data.provider ?? 'this provider';
  const url = event.data.auth_url;
  if (!url) return null;
  return (
    <section className="consent" role="alert" aria-labelledby={`consent-${event.seq}`}>
      <h2 id={`consent-${event.seq}`}><ShieldCheck size={16} />Connect {provider}</h2>
      <p>
        {provider} is set up, but no account has been connected to it yet, so nothing
        can be signed on your behalf. Approve access and the agent carries on with
        the task.
      </p>
      <a className="consent-action" href={url} target="_blank" rel="noreferrer noopener">
        Connect {provider}<ExternalLink size={15} />
      </a>
    </section>
  );
}
