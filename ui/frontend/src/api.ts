import { z } from 'zod';

export const statusSchema = z.enum(['running', 'waiting', 'completed', 'failed', 'cancelled', 'interrupted']);
const artifactTypeSchema = z.enum(['document', 'presentation', 'spreadsheet', 'pdf', 'email', 'image', 'audio', 'video', 'archive', 'file']);
const artifactPreviewSchema = z.object({
  kind: z.enum(['text', 'image', 'pdf']),
  text: z.string().max(20000).optional(),
  url: z.string().url().startsWith('https://').optional(),
}).refine(preview => preview.kind === 'text' ? Boolean(preview.text && !preview.url) : Boolean(preview.url && !preview.text),
  'Artifact preview content must match its kind');
const artifactMetadataSchema = z.record(z.string().min(1).max(80), z.string().max(1000))
  .refine(metadata => Object.keys(metadata).length <= 12, 'Artifact metadata has at most 12 entries');
export const artifactSchema = z.object({
  schema_version: z.literal('1'),
  id: z.string().min(1).max(256),
  artifact_type: artifactTypeSchema,
  title: z.string().min(1).max(240),
  url: z.string().url().startsWith('https://').optional(),
  mime_type: z.string().max(160).optional(),
  provider: z.string().max(80).optional(),
  description: z.string().max(1000).optional(),
  metadata: artifactMetadataSchema.default({}),
  preview: artifactPreviewSchema.optional(),
});
export const structuredOutputSchema = z.object({
  schema_version: z.literal('1'),
  output_type: z.string().regex(/^[a-z][a-z0-9_]{0,79}$/),
  title: z.string().min(1).max(240),
  data: z.record(z.string(), z.unknown()),
});
export const eventSchema = z.object({
  seq: z.number().int(),
  type: z.enum(['status', 'result', 'structured_output', 'artifact', 'error', 'peer_message', 'consent_required', 'credential_input_required', 'approval_required', 'approval_decided', 'waiting', 'activity', 'completed', 'cancelled']),
  timestamp: z.string(),
  data: z.object({ message: z.string().optional(), text: z.string().optional(), status: statusSchema.optional(),
    obligation_status: z.enum(['satisfied', 'blocked', 'incomplete']).optional(),
    recipient_id: z.string().optional(),
    provider: z.string().optional(),
    label: z.string().optional(),
    auth_url: z.string().url().startsWith('https://').optional(),
    connection_id: z.string().optional(), workflow_id: z.string().optional(), step_id: z.string().optional(),
    state: z.string().optional(), schema: z.record(z.string(), z.unknown()).optional(),
    kind: z.enum(['reasoning', 'tool', 'agent', 'decision']).optional(), summary: z.string().optional(),
    agent: z.string().optional(),
    tool: z.string().nullable().optional(),
    outcome: z.enum(['started', 'succeeded', 'failed']).nullable().optional(),
    action_id: z.string().optional(), action: z.string().optional(), consequence: z.string().optional(),
    approved: z.boolean().optional(),
    schema_version: z.literal('1').optional(), id: z.string().optional(),
    artifact_type: artifactTypeSchema.optional(), title: z.string().optional(),
    output_type: z.string().optional(), data: z.record(z.string(), z.unknown()).optional(),
    url: z.string().optional(), mime_type: z.string().optional(), description: z.string().optional(),
    metadata: artifactMetadataSchema.optional(), preview: artifactPreviewSchema.optional(),
    messages: z.array(z.object({ sender_id: z.string(), text: z.string() })).min(1).max(32).optional(),
  }),
}).refine(event => event.type !== 'peer_message' || Boolean(event.data.recipient_id && event.data.messages?.length),
  'Peer messages require recipient and senders')
  .refine(event => event.type !== 'artifact' || artifactSchema.safeParse(event.data).success,
    'Artifact events require a valid display resource')
  .refine(event => event.type !== 'structured_output' || structuredOutputSchema.safeParse(event.data).success,
    'Structured output events require valid display data')
  .refine(event => event.type !== 'consent_required' || Boolean(event.data.provider && event.data.auth_url),
  'Consent requests require a provider and an authorization URL');
export const runSchema = z.object({
  id: z.string(), agent_id: z.string(), operation: z.string(), message: z.string().nullable(),
  context: z.record(z.string(), z.unknown()).optional(), status: statusSchema,
  created_at: z.string(), updated_at: z.string(), events: z.array(eventSchema),
});
export const runUpdateSchema = z.object({ runs: z.array(runSchema) });
const agentSchema = z.object({
  id: z.string(), name: z.string(), description: z.string(), blueprint: z.string(),
  kind: z.enum(['agent', 'mesh']).default('agent'), members: z.array(z.string()).default([]),
  capabilities: z.array(z.string()).default([]), color: z.string().regex(/^#[0-9a-fA-F]{6}$/).default('#397b72'),
  supports_reconciliation: z.boolean().default(false),
  shape: z.enum(['circle', 'rounded', 'diamond', 'hexagon']).default('circle'),
  operations: z.array(z.object({
    id: z.string(), label: z.string(), description: z.string(), allows_message: z.boolean(),
  })),
});
const healthSchema = z.object({
  status: z.string(), framework_version: z.string().nullable(), framework_revision: z.string().nullable(),
  framework_source: z.string().nullable().optional(), framework_branch: z.string().nullable().optional(),
  framework_dirty: z.boolean().nullable().optional(), framework_editable: z.boolean().optional(),
});
const workspaceSchema = z.object({ name: z.string(), configured: z.boolean(), room: z.boolean().optional(), inspection: z.boolean(), metrics_url: z.string().nullable() });
const inspectionSchema = z.object({ configured: z.boolean(), workflows: z.array(z.object({
  id: z.string(), display_name: z.string(), reference: z.string(),
  steps: z.number(), events: z.number(), tokens: z.number(), failures: z.number(),
  status: z.string(), started: z.string(), duration: z.string(),
})) });
const traceSchema = z.object({ events: z.array(z.object({
  type: z.string(), timestamp: z.string(), step_id: z.string(), data: z.record(z.string(), z.number()),
})) });

export type Agent = z.infer<typeof agentSchema>;
export type Run = z.infer<typeof runSchema>;
export type RunEvent = z.infer<typeof eventSchema>;
export type Artifact = z.infer<typeof artifactSchema>;
export type StructuredOutput = z.infer<typeof structuredOutputSchema>;
export type Health = z.infer<typeof healthSchema>;
export type Inspection = z.infer<typeof inspectionSchema>;
export type Trace = z.infer<typeof traceSchema>;
export type Workspace = z.infer<typeof workspaceSchema>;
const metricsSchema = z.object({ status: z.enum(['available', 'unavailable', 'not_configured']),
  source: z.enum(['prometheus', 'local_traces']).optional(),
  samples: z.array(z.object({ name: z.string(), value: z.number(), labels: z.record(z.string(), z.string()).default({}) })) });
export type Metrics = z.infer<typeof metricsSchema>;

async function request<Schema extends z.ZodType>(path: string, schema: Schema, body?: unknown): Promise<z.output<Schema>> {
  const response = await fetch(`/api${path}`, body === undefined ? undefined : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  const payload: unknown = await response.json().catch(() => undefined);
  if (!response.ok) {
    const detail = payload && typeof payload === 'object' && 'detail' in payload ? payload.detail : undefined;
    throw new Error(typeof detail === 'string' ? detail : `Request failed (${response.status}).`);
  }
  const parsed = schema.safeParse(payload);
  if (!parsed.success) throw new Error('The server returned an unsupported response. Refresh after updating the desk.');
  return parsed.data;
}

export const api = {
  agents: () => request('/agents', z.array(agentSchema)),
  runs: () => request('/runs', z.array(runSchema)),
  health: () => request('/health', healthSchema),
  workspace: () => request('/workspace', workspaceSchema),
  metrics: () => request('/metrics', metricsSchema),
  inspect: () => request('/inspect', inspectionSchema),
  trace: (id: string) => request(`/inspect/${encodeURIComponent(id)}`, traceSchema),
  run: (id: string) => request(`/runs/${encodeURIComponent(id)}`, runSchema),
  start: (agent_id: string, operation: string, message?: string) => request('/runs', runSchema, { agent_id, operation, message }),
  cancel: (id: string) => request(`/runs/${encodeURIComponent(id)}/cancel`, runSchema, {}),
  reconcile: (id: string) => request(`/runs/${encodeURIComponent(id)}/reconcile`, runSchema, {}),
  resume: (id: string, connection_id: string) => request(
    `/runs/${encodeURIComponent(id)}/resume`, runSchema, { connection_id },
  ),
  credentials: (id: string, credentials: Record<string, string>) => request(
    `/runs/${encodeURIComponent(id)}/credentials`, runSchema, { credentials },
  ),
  approval: (id: string, action_id: string, approved: boolean) => request(
    `/runs/${encodeURIComponent(id)}/approval`, runSchema, { action_id, approved },
  ),
};

export function addEvent(run: Run, event: RunEvent): Run {
  if (run.events.some(existing => existing.seq === event.seq)) return run;
  return {
    ...run, updated_at: event.timestamp, status: event.data.status ?? run.status,
    events: [...run.events, event].sort((left, right) => left.seq - right.seq),
  };
}

// Previews are one line of plain text: markdown syntax is structure, not content.
export function plainText(markdown: string): string {
  return markdown
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/^\s*#{1,6}\s+/gm, '')
    .replace(/^\s*[-*+]\s+/gm, '')
    .replace(/^\s*\d+[.)]\s+/gm, '')
    .replace(/\[([^\]]+)\]\([^)\s]+\)/g, '$1')
    .replace(/[*`]+/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

export function runStatusLabel(run: Run): string {
  if (run.status === 'waiting') {
    const request = [...run.events].sort((left, right) => right.seq - left.seq)
      .find(event => ['approval_required', 'consent_required', 'credential_input_required'].includes(event.type));
    if (request?.type === 'approval_required') return 'Waiting for approval';
    if (request?.type === 'consent_required') return 'Waiting for access';
    if (request?.type === 'credential_input_required') return 'Waiting for credentials';
    return 'Waiting for input';
  }
  return {
    running: 'Running', completed: 'Execution finished', failed: 'Execution failed',
    cancelled: 'Cancelled', interrupted: 'Interrupted',
  }[run.status];
}

export function runPreview(run: Run): string {
  if (run.status === 'waiting') return runStatusLabel(run);
  if (run.status === 'cancelled') return 'Cancelled';
  if (run.status === 'interrupted') return 'Interrupted';
  const events = [...run.events].sort((left, right) => right.seq - left.seq);
  const allowed = run.status === 'running' ? ['status', 'result', 'error']
    : run.status === 'completed' ? ['result'] : ['error'];
  const event = events.find(item => allowed.includes(item.type) && (item.data.text ?? item.data.message)?.trim());
  if (event) return plainText(event.data.text ?? event.data.message ?? '');
  if (run.status === 'running') return run.message?.trim() || 'Running';
  return run.status === 'completed' ? 'Execution finished' : 'Execution failed';
}

export function mergeRuns(current: Run[], incoming: Run[]): Run[] {
  const combined = new Map(current.map(run => [run.id, run]));
  const revision = (run: Run) => run.events.reduce((latest, event) => Math.max(latest, event.seq), 0);
  for (const run of incoming) {
    const previous = combined.get(run.id);
    if (!previous || revision(run) >= revision(previous)) combined.set(run.id, run);
  }
  return [...combined.values()].sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at));
}