import { useState, type FormEvent } from 'react';
import { KeyRound } from 'lucide-react';

import { api, type RunEvent } from './api';

type Property = { title?: string; description?: string; format?: string };

export function CredentialRequest({ runId, event, onSaved }: {
  runId: string; event: RunEvent; onSaved: (run: Awaited<ReturnType<typeof api.run>>) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const schema = event.data.schema ?? {};
  const properties = (schema.properties ?? {}) as Record<string, Property>;
  const required = new Set(Array.isArray(schema.required) ? schema.required as string[] : []);
  const label = event.data.label ?? event.data.provider ?? 'provider';

  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError('');
    try { onSaved(await api.credentials(runId, values)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Credentials were not accepted.'); }
    finally { setBusy(false); }
  }

  return <form className="consent" onSubmit={event => void submit(event)}>
    <h2><KeyRound size={16} />Connect {label}</h2>
    <p>Enter the credentials required by {label}. They are sent directly to Nexus for validation and encrypted storage; the agent never receives them.</p>
    {Object.entries(properties).map(([name, property]) => <label className="credential-field" key={name}>
      <span>{property.title ?? name.replaceAll('_', ' ')}</span>
      <input type={property.format === 'password' ? 'password' : 'text'} required={required.has(name)}
        autoComplete="off" value={values[name] ?? ''}
        onChange={event => setValues(current => ({ ...current, [name]: event.target.value }))} />
      {property.description && <small>{property.description}</small>}
    </label>)}
    {error && <div className="inline-error" role="alert">{error}</div>}
    <button className="consent-action" type="submit" disabled={busy}>{busy ? 'Checking...' : `Connect ${label}`}</button>
  </form>;
}