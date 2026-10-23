import { useState } from 'react';
import { Check, ShieldAlert, X } from 'lucide-react';

import { api, type Run, type RunEvent } from './api';

export type ApprovalDecision = 'pending' | 'approved' | 'rejected';

// The person's recorded decision is the answer; runs from before decisions were
// recorded fall back to how they ended.
export function approvalDecision(run: Run, events: RunEvent[], event: RunEvent): ApprovalDecision {
  const decided = [...events].reverse().find(item =>
    item.type === 'approval_decided' && item.data.action_id === event.data.action_id && item.seq > event.seq);
  if (decided) return decided.data.approved ? 'approved' : 'rejected';
  const newest = [...events].reverse().find(item => item.type === 'approval_required');
  if (newest?.seq !== event.seq) return 'approved';
  if (run.status === 'waiting') return 'pending';
  return run.status === 'cancelled' ? 'rejected' : 'approved';
}

export function ApprovalRequest({ runId, event, decision, onSaved }: {
  runId: string; event: RunEvent; decision: ApprovalDecision; onSaved: (run: Run) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const actionId = event.data.action_id;
  if (!actionId) return null;
  async function decide(approved: boolean) {
    setBusy(true); setError('');
    try { onSaved(await api.approval(runId, actionId!, approved)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Decision could not be recorded.'); }
    finally { setBusy(false); }
  }
  return <section className={`consent approval approval-${decision}`} role={decision === 'pending' ? 'alert' : undefined}>
    <h2><ShieldAlert size={16} />{decision === 'pending' ? 'Approval needed' : 'Approval request'}</h2>
    {event.data.consequence && <p className="approval-consequence">{event.data.consequence}</p>}
    {event.data.action && <p className="approval-action">{event.data.action}</p>}
    {error && <div className="inline-error">{error}</div>}
    {decision === 'pending' ? <div className="approval-actions">
      <button className="approval-approve" disabled={busy} onClick={() => void decide(true)}>Approve</button>
      <button className="text-button" disabled={busy} onClick={() => void decide(false)}>Reject</button>
    </div> : <p className="approval-decision">{decision === 'approved'
      ? <><Check size={14} />Approved</> : <><X size={14} />Not approved</>}</p>}
  </section>;
}