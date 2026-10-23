import { expect, test } from '@playwright/test';
import { runPreview, type Run } from '../src/api';

const base: Run = {
  id: 'test', agent_id: 'agent', operation: 'ask', message: 'Human task',
  status: 'running', created_at: '2026-09-05T10:00:00Z', updated_at: '2026-09-05T10:00:00Z',
  events: [],
};

test('preview uses structured lifecycle and actual event content without rewriting it', () => {
  expect(runPreview(base)).toBe('Human task');
  const events: Run['events'] = [
    { seq: 2, type: 'result', timestamp: base.updated_at, data: { text: 'The full answer\nwith evidence.' } },
    { seq: 1, type: 'status', timestamp: base.updated_at, data: { message: 'Reading evidence.' } },
    { seq: 3, type: 'status', timestamp: base.updated_at, data: { message: 'Writing the journal.' } },
  ];
  expect(runPreview({ ...base, events })).toBe('Writing the journal.');
  expect(runPreview({ ...base, status: 'completed', events })).toBe('The full answer with evidence.');
  expect(events.map(event => event.seq)).toEqual([2, 1, 3]);
  expect(runPreview({ ...base, status: 'failed', events })).toBe('Execution failed');
  expect(runPreview({ ...base, status: 'cancelled', events })).toBe('Cancelled');
  expect(runPreview({ ...base, status: 'interrupted', events })).toBe('Interrupted');
  expect(runPreview({ ...base, status: 'completed' })).toBe('Execution finished');
});

test('previews read as one line of prose, never as markdown source', () => {
  const markdown = '## How the desk assigned this\n- **pipeline_builder** owns it. See [source](https://sifted.eu/x).\n\n```\ncode\n```';
  const events: Run['events'] = [{ seq: 1, type: 'result', timestamp: base.updated_at, data: { text: markdown } }];
  expect(runPreview({ ...base, status: 'completed', events }))
    .toBe('How the desk assigned this pipeline_builder owns it. See source.');
});