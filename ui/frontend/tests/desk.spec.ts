import { expect, test, type APIResponse, type Page } from '@playwright/test';

type SavedRun = { id: string; status: string };
const savedRuns = async (response: APIResponse) => await response.json() as SavedRun[];
const savedRun = async (response: APIResponse) => await response.json() as SavedRun;
const selected = (page: Page) => page.locator('.topbar-title strong');
const latestTurn = (page: Page) => page.locator('.conversation-turn').last();

async function openNavigation(page: Page) {
  const button = page.getByRole('button', { name: 'Open navigation' });
  if (await button.isVisible()) await button.click();
}

test('isolated offline worker streams results and reloads the conversation without rerunning', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/#agent=offline-check');
  await expect(selected(page)).toHaveText('Offline validation');
  await page.getByRole('button', { name: 'Run', exact: true }).click();
  await expect(latestTurn(page).locator('.run-end')).toContainText('Execution finished');
  await expect(latestTurn(page).locator('.result')).toHaveCount(3);
  await expect(latestTurn(page).locator('.result').last()).toContainText('1 new, 1 changed and 2 unchanged');
  await expect(latestTurn(page).locator('.result').last()).toContainText('not buying intent');
  const sidebarName = page.getByRole('navigation', { name: 'Agents', exact: true })
    .getByRole('button', { name: 'Offline validation', exact: true }).locator('strong');
  expect(await sidebarName.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
  await expect(page.getByRole('button', { name: 'Run', exact: true })).toBeInViewport();
  await expect(page.getByRole('textbox', { name: /Message/ })).toHaveCount(0);
  const noOverflow = await page.evaluate(() => ({
    horizontal: document.documentElement.scrollWidth <= window.innerWidth,
    vertical: document.documentElement.scrollHeight <= window.innerHeight,
  }));
  expect(noOverflow).toEqual({ horizontal: true, vertical: true });
  const historyBefore = await savedRuns(await page.request.get('/api/runs'));
  await page.reload();
  await expect(latestTurn(page).locator('.result')).toHaveCount(3);
  await expect(latestTurn(page).locator('.run-end')).toContainText('Execution finished');
  expect(await savedRuns(await page.request.get('/api/runs'))).toHaveLength(historyBefore.length);
  await expect(page.getByRole('button', { name: /New task|Task history|Export run|Refresh desk/ })).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('completed-run.png') });
  expect(errors).toEqual([]);
});

test('connection failure is visible and automatically recovers', async ({ page }) => {
  await page.route('**/api/agents', route => route.abort());
  await page.goto('/');
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Run', exact: true })).toBeDisabled();
  await page.unroute('**/api/agents');
  await expect(selected(page)).toHaveText('GTM Agent');
  await expect(page.getByRole('alert')).toHaveCount(0);
});

const agent = {
  id: 'controlled-peer', name: 'Controlled Peer', description: 'Browser test adapter only', blueprint: 'test',
  supports_reconciliation: true,
  operations: [{ id: 'ask', label: 'Ask peer', description: 'Controlled browser test', allows_message: true }],
};
const initial = {
  id: 'controlled-run', agent_id: agent.id, operation: 'ask', message: 'Account question',
  context: { mesh_workflow_id: 'desk-test-controlled-peer' },
  status: 'running', created_at: '2026-09-05T10:00:00Z', updated_at: '2026-09-05T10:00:00Z',
  events: [{ seq: 1, type: 'status', timestamp: '2026-09-05T10:00:00Z', data: { message: 'Waiting for evidence.' } }],
};

for (const configured of [
  { ...agent, id: 'personal-intelligence-mesh', name: 'Personal Intelligence', blueprint: 'personal-intelligence', kind: 'mesh' },
  { ...agent, id: 'field-research-peer', name: 'Field Research', blueprint: 'field-research', kind: 'agent' },
]) {
  test(`configured agents share approval and resume UI: ${configured.blueprint}`, async ({ page }, info) => {
    const waiting = { ...initial, agent_id: configured.id, status: 'waiting', events: [
      ...initial.events,
      { seq: 2, type: 'approval_required', timestamp: initial.created_at, data: {
        action_id: 'approved-action', action: 'Submit the verified order', consequence: 'Creates the provider commitment.',
      } },
      { seq: 3, type: 'waiting', timestamp: initial.created_at, data: { status: 'waiting' } },
    ] };
    let decision: unknown;
    await page.route('**/api/agents', route => route.fulfill({ json: [configured] }));
    await page.route('**/api/runs', route => route.fulfill({ json: [waiting] }));
    await page.route('**/api/runs/controlled-run/approval', route => {
      decision = route.request().postDataJSON();
      return route.fulfill({ json: { ...waiting, status: 'running', events: [...waiting.events, {
        seq: 4, type: 'status', timestamp: initial.created_at, data: { message: 'Resuming the approved action.' },
      }] } });
    });
    await page.goto(`/#agent=${configured.id}&task=controlled-run`);
    await expect(selected(page)).toHaveText(configured.name);
    await expect(page.locator('.topbar .run-status')).toHaveText('Waiting for approval');
    await expect(latestTurn(page).locator('.run-end')).toContainText('Waiting for approval');
    await expect(page.getByRole('button', { name: 'Approve', exact: true })).toBeVisible();
    const card = page.locator('.approval');
    await expect(card.locator('p').first()).toHaveText('Creates the provider commitment.');
    await expect(card.locator('.approval-action')).toHaveText('Submit the verified order');
    await expect(card).not.toContainText('Consequence:');
    const [approveFill, rejectFill] = await Promise.all(['Approve', 'Reject'].map(name =>
      card.getByRole('button', { name, exact: true }).evaluate(element => getComputedStyle(element).backgroundColor)));
    expect(approveFill).not.toBe(rejectFill);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath('configured-approval.png') });
    await page.getByRole('button', { name: 'Approve', exact: true }).click();
    expect(decision).toEqual({ action_id: 'approved-action', approved: true });
    await expect(page.locator('.topbar .run-status')).toHaveText('Running');
    await expect(latestTurn(page).locator('.working')).toContainText('Resuming the approved action.');
  });
}

test('adapter discovery, live-event deduplication and cancellation', async ({ page }) => {
  let cancelled = false;
  const active = { ...initial, events: [
    {
      seq: 1, type: 'activity', timestamp: initial.created_at,
      data: { kind: 'agent', summary: 'Waiting for evidence.', agent: 'Controlled Peer', outcome: 'started' },
    },
    {
      seq: 2, type: 'activity', timestamp: initial.created_at,
      data: { kind: 'tool', summary: 'Running provider lookup.', agent: 'Controlled Peer', tool: 'lookup', outcome: 'started' },
    },
  ] };
  await page.route('**/api/agents', route => route.fulfill({ json: [agent] }));
  await page.route('**/api/runs', route => route.fulfill({ json: [active] }));
  await page.route('**/api/runs/controlled-run', route => route.fulfill({ json: active }));
  await page.route('**/api/runs/controlled-run/events', route => route.fulfill({
    contentType: 'text/event-stream', body: `id: 1\ndata: ${JSON.stringify(active.events[0])}\n\n`,
  }));
  await page.route('**/api/runs/controlled-run/cancel', route => {
    cancelled = true;
    return route.fulfill({ json: { ...active, status: 'cancelled', events: [...active.events, {
      seq: 2, type: 'cancelled', timestamp: '2026-09-05T10:00:01Z', data: { status: 'cancelled' },
    }] } });
  });
  await page.goto('/');
  await expect(page.locator('.activity li')).toHaveCount(2);
  await expect(page.locator('.activity')).toContainText('Running provider lookup.');
  await expect(page.locator('.working')).toContainText('Controlled Peer: Running provider lookup.');
  await expect(page.getByRole('textbox', { name: 'Message Controlled Peer' })).toBeDisabled();
  await page.getByRole('button', { name: 'Stop run' }).click();
  await expect(page.locator('.run-end')).toContainText('Cancelled');
  expect(cancelled).toBe(true);
  await expect(page.getByRole('textbox', { name: 'Message Controlled Peer' })).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Run', exact: true })).toBeDisabled();
  await page.getByRole('textbox', { name: 'Message Controlled Peer' }).fill('Follow-up task');
  await expect(page.getByRole('button', { name: 'Run', exact: true })).toBeEnabled();
});

test('new execution status supersedes stale activity from a prior epoch', async ({ page }) => {
  const resumed = { ...initial, events: [
    {
      seq: 1, type: 'activity', timestamp: initial.created_at,
      data: { kind: 'agent', summary: 'Finished prior work.', agent: 'Controlled Peer', outcome: 'succeeded' },
    },
    {
      seq: 2, type: 'status', timestamp: '2026-09-05T10:01:00Z',
      data: { message: 'Connecting configured agents to durable workflow state.' },
    },
  ] };
  await page.route('**/api/agents', route => route.fulfill({ json: [agent] }));
  await page.route('**/api/runs', route => route.fulfill({ json: [resumed] }));
  await page.route('**/api/runs/controlled-run', route => route.fulfill({ json: resumed }));
  await page.route('**/api/runs/controlled-run/events', route => route.fulfill({
    contentType: 'text/event-stream', body: '',
  }));

  await page.goto('/');

  await expect(page.locator('.working')).toContainText(
    'Connecting configured agents to durable workflow state.',
  );
  await expect(page.locator('.working')).not.toContainText('Finished prior work.');
});

test('answered approvals read as decided and offer no live buttons', async ({ page }) => {
  const request = (seq: number, consequence: string) => ({
    seq, type: 'approval_required', timestamp: initial.created_at,
    data: { action_id: `action-${seq}`, action: 'Click “Place order” on shop.test/basket', consequence },
  });
  const cancelled = { ...initial, status: 'cancelled', events: [...initial.events,
    request(2, 'Places the first order.'),
    { seq: 3, type: 'status', timestamp: initial.created_at, data: { message: 'Access approved. Resuming the task.' } },
    request(4, 'Places the retried order.'),
    { seq: 5, type: 'status', timestamp: initial.created_at, data: { message: 'The action was not approved.' } },
    { seq: 6, type: 'cancelled', timestamp: initial.created_at, data: { status: 'cancelled' } },
  ] };
  await page.route('**/api/agents', route => route.fulfill({ json: [agent] }));
  await page.route('**/api/runs', route => route.fulfill({ json: [cancelled] }));
  await page.goto('/');

  const cards = page.locator('.approval');
  await expect(cards).toHaveCount(2);
  await expect(cards.nth(0)).toContainText('Approved');
  await expect(cards.nth(1)).toContainText('Not approved');
  await expect(page.getByRole('button', { name: /^(Approve|Reject)$/ })).toHaveCount(0);
});

test('failed output stays failed and model text is not interpreted as HTML', async ({ page }) => {
  const failed = { ...initial, status: 'failed', events: [
    ...initial.events,
    { seq: 2, type: 'error', timestamp: initial.created_at, data: { message: 'Assessment failed. No judgement recorded.' } },
    { seq: 3, type: 'result', timestamp: initial.created_at, data: { text: '<img src=x onerror=alert(1)> Evidence only.' } },
    { seq: 4, type: 'completed', timestamp: initial.created_at, data: { status: 'failed' } },
  ] };
  await page.route('**/api/agents', route => route.fulfill({ json: [agent] }));
  await page.route('**/api/runs', route => route.fulfill({ json: [failed] }));
  await page.goto('/');
  await expect(selected(page)).toHaveText('Controlled Peer');
  await expect(page.getByRole('alert')).toContainText('Assessment failed');
  await expect(page.locator('.run-end')).toContainText('Execution failed');
  await expect(page.locator('.result img')).toHaveCount(0);
  await expect(page.locator('.result')).toContainText('<img src=x onerror=alert(1)>');
  await page.getByRole('button', { name: 'Inspect trace' }).click();
  await expect(page.getByRole('region', { name: 'Framework inspection' })).toBeVisible();
});

test('failed mesh run can continue when reconciliation is configured', async ({ page }) => {
  const failed = { ...initial, status: 'failed', events: [
    ...initial.events,
    { seq: 2, type: 'error', timestamp: initial.created_at, data: { message: 'Planning failed.' } },
    { seq: 3, type: 'completed', timestamp: initial.created_at, data: { status: 'failed' } },
  ] };
  let reconciled = false;
  await page.route('**/api/agents', route => route.fulfill({ json: [agent] }));
  await page.route('**/api/runs', route => route.fulfill({ json: [failed] }));
  await page.route('**/api/runs/controlled-run/reconcile', route => {
    reconciled = true;
    return route.fulfill({ json: {
      ...failed,
      status: 'running',
      events: [...failed.events, {
        seq: 4, type: 'status', timestamp: initial.created_at,
        data: { message: 'Goal reconciliation started.' },
      }],
    } });
  });

  await page.goto('/');
  await page.getByRole('button', { name: 'Continue goal' }).click();

  await expect(page.locator('.working')).toContainText('Goal reconciliation started.');
  expect(reconciled).toBe(true);
});

test('mesh membership and configured runtime are visible', async ({ page }, info) => {
  await page.route('**/api/inspect', route => route.fulfill({ json: { configured: true, workflows: [{
    id: 'desk-gtm-mesh-20260905', display_name: 'Acme GTM launch', reference: 'GTM mesh · 2026-09-05 12:00 UTC',
    steps: 4, events: 9, tokens: 1200, failures: 0, status: 'completed', started: '2026-09-05T12:00:00Z', duration: '3 s',
  }] } }));
  await page.route('**/api/metrics', route => route.fulfill({ json: {
    status: 'available', source: 'local_traces',
    samples: [{ name: 'jarviscore_workflows_total', value: 1, labels: {} }],
  } }));
  const health: unknown = await page.request.get('/api/health').then(response => response.json());
  if (!health || typeof health !== 'object' || !('framework_version' in health)
      || typeof health.framework_version !== 'string') {
    throw new Error('Health response has no framework version.');
  }
  const frameworkVersion = health.framework_version;
  await page.goto('/');
  await openNavigation(page);
  const navigation = page.getByRole('navigation', { name: 'Agents', exact: true });
  await expect(navigation.getByRole('button', { name: 'GTM Agent', exact: true })).toHaveCount(1);
  await navigation.getByRole('button', { name: 'GTM Agent', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'GTM Agent', exact: true })).toBeVisible();
  await expect(page.locator('.empty-state .mesh-identity > .avatar')).toHaveCount(1);
  await page.getByRole('button', { name: 'Inspect framework' }).click();
  await expect(page.getByRole('region', { name: 'Framework inspection' })).toBeVisible();
  await expect(page.getByText('Acme GTM launch')).toBeVisible();
  await expect(page.getByText(/GTM mesh · 2026-09-05 12:00 UTC/)).toBeVisible();
  await page.getByRole('tab', { name: 'Telemetry' }).click();
  await expect(page.getByText('Local trace totals. Configure Prometheus for live provider and model metrics.')).toBeVisible();
  await page.getByRole('tab', { name: 'Configuration' }).click();
  await expect(page.locator('.runtime-facts').first()).toContainText(frameworkVersion);
  await page.screenshot({ path: info.outputPath('mesh-configuration.png') });
  await page.getByRole('button', { name: 'Close inspection' }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

const members = [
  { ...agent, id: 'researcher', name: 'Researcher', color: '#397b72', capabilities: ['research'] },
  { ...agent, id: 'writer', name: 'Writer', color: '#bd6847', capabilities: ['writing'] },
  { ...agent, id: 'reviewer', name: 'Reviewer', color: '#4975bd', capabilities: ['review'] },
  { ...agent, id: 'analyst', name: 'Analyst', color: '#b58b32', capabilities: ['analysis'] },
];
const mesh = { ...agent, id: 'mesh', name: 'Mesh', kind: 'mesh', members: members.map(member => member.id) };

test('mesh is a flat peer row with a composite avatar, not an expandable group', async ({ page }, info) => {
  await page.route('**/api/agents', route => route.fulfill({ json: [...members, mesh] }));
  await page.route('**/api/runs', route => route.fulfill({ json: [] }));
  await page.goto('/');
  await openNavigation(page);
  const navigation = page.getByRole('navigation', { name: 'Agents', exact: true });
  const rows = navigation.locator(':scope > .agent-row');
  await expect(rows).toHaveCount(5);
  await expect(rows.last()).toContainText('Mesh');
  await expect(navigation.getByRole('group')).toHaveCount(0);
  await expect(navigation.getByRole('button', { name: /Collapse|Expand/ })).toHaveCount(0);
  await expect(page.locator('.sidebar .section-label')).toHaveCount(0);
  await expect(page.locator('.sidebar').getByText('Tasks', { exact: true })).toHaveCount(0);
  await expect(page.locator('.sidebar').getByRole('navigation', { name: 'Task history' })).toHaveCount(0);
  await expect(navigation.locator('.mesh-identity > .avatar')).toHaveCount(3);
  await expect(navigation.locator('.member-overflow')).toHaveText('+1');
  const colors = await navigation.locator('.agent-row > .avatar').evaluateAll(elements => elements.map(element => getComputedStyle(element).backgroundColor));
  expect(new Set(colors).size).toBe(4);
  const positions = await rows.evaluateAll(elements => elements.map(element => element.getBoundingClientRect().left));
  expect(new Set(positions).size).toBe(1);
  await page.getByRole('textbox', { name: 'Search agents' }).fill('writing');
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText('Writer');
  await expect(page.getByText('No matching agents.')).toHaveCount(0);
  await page.getByRole('textbox', { name: 'Search agents' }).clear();
  await expect(rows).toHaveCount(5);
  await expect(page.locator('.brand .avatar')).toHaveCount(0);
  await expect(page.getByRole('img', { name: 'JarvisCore', exact: true })).toBeVisible();
  expect(await page.locator('.wordmark').evaluate(element => (element as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  expect(await page.locator('.search').evaluate(element => getComputedStyle(element).borderRadius)).toBe('22px');
  expect(await page.locator('body').evaluate(element => getComputedStyle(element).fontFamily)).toContain('Helvetica Neue');
  await page.screenshot({ path: info.outputPath('flat-sidebar.png') });
  await navigation.getByRole('button', { name: 'Writer', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Writer', exact: true })).toBeVisible();
  await expect(page.getByText('Ready', { exact: true })).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('message-composer.png') });
});

test('a one-agent mesh is the product conversation, named for the product', async ({ page }) => {
  const only = { ...agent, id: 'personal-intelligence-agent', name: 'Personal Intelligence' };
  const product = { ...agent, id: 'personal-intelligence-mesh', name: 'Personal Intelligence', kind: 'mesh', members: [only.id] };
  await page.route('**/api/agents', route => route.fulfill({ json: [only, product] }));
  await page.route('**/api/runs', route => route.fulfill({ json: [] }));
  await page.goto('/');
  await openNavigation(page);
  const rows = page.getByRole('navigation', { name: 'Agents', exact: true }).locator(':scope > .agent-row');
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toHaveAttribute('aria-current', 'page');
  await expect(page.getByRole('textbox', { name: 'Message Personal Intelligence' })).toBeVisible();
  await expect(page.getByText('Mesh', { exact: true })).toHaveCount(0);
});

test('live agents expose task entry without development actions', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('textbox', { name: 'Message GTM Agent' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Choose action' })).toHaveCount(0);
  await expect(page.getByText(/Fixture-data preview|Watch Monzo live/)).toHaveCount(0);
  await expect(page.locator('.run-end')).toHaveCount(0);
  expect(await page.locator('.composer').evaluate(element => getComputedStyle(element).borderRadius)).toBe('32px');
});

test('message composer sends with Enter, preserves newlines, and prevents empty requests', async ({ page }) => {
  const posted: string[] = [];
  await page.route('**/api/agents', route => route.fulfill({ json: [agent] }));
  await page.route('**/api/runs', route => {
    if (route.request().method() === 'POST') {
      const message = (route.request().postDataJSON() as { message: string }).message;
      posted.push(message);
      return route.fulfill({ json: { ...initial, message, status: 'completed', events: [] } });
    }
    return route.fulfill({ json: [] });
  });
  await page.goto('/');
  const input = page.getByRole('textbox', { name: 'Message Controlled Peer' });
  await expect(input).toBeVisible();
  await expect(page.getByRole('button', { name: 'Run', exact: true })).toBeDisabled();
  await input.fill('Review evidence');
  await input.press('Shift+Enter');
  await input.press('a');
  expect(posted).toHaveLength(0);
  await input.press('Enter');
  const bubble = page.locator('.request-message');
  await expect(bubble).toHaveText('Review evidence\na');
  // The person's own words, not the action that carried them.
  await expect(bubble).not.toContainText('Ask peer');
  expect(await bubble.evaluate(element => getComputedStyle(element).borderRadius)).toBe('22px');
  expect(await bubble.evaluate(element => getComputedStyle(element).fontSize))
    .toBe((page.viewportSize()?.width ?? 0) <= 760 ? '13px' : '14px');
  expect(posted).toEqual(['Review evidence\na']);
  await expect(input).toHaveValue('');
  await input.fill('   ');
  await input.press('Enter');
  expect(posted).toHaveLength(1);
  await expect(page.getByRole('button', { name: 'Run', exact: true })).toBeDisabled();
});

test('slow roster loading never paints a fallback identity, including on reload', async ({ page }, info) => {
  let release: () => void = () => {};
  let barrier = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/agents', async route => {
    await barrier;
    await route.fulfill({ json: members });
  });
  await page.route('**/api/runs', route => route.fulfill({ json: [] }));
  await page.goto('/#agent=writer');
  for (const pass of ['initial', 'reload']) {
    if (pass === 'reload') {
      barrier = new Promise<void>(resolve => { release = resolve; });
      await page.reload();
    }
    await expect(page.locator('.topbar .identity-placeholder')).toBeVisible();
    await expect(page.locator('.workspace .avatar')).toHaveCount(0);
    await expect(page.locator('.workspace .monogram')).toHaveCount(0);
    await expect(page.getByText('Ready', { exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Run', exact: true })).toBeDisabled();
    if (pass === 'initial') await page.screenshot({ path: info.outputPath('loading-state.png') });
    release();
    await expect(page.getByRole('heading', { name: 'Writer', exact: true })).toBeVisible();
    await expect(page.locator('.topbar .avatar')).toHaveCSS('background-color', 'rgb(189, 104, 71)');
    await expect(page.locator('.identity-placeholder')).toHaveCount(0);
    await expect(page).toHaveURL(/agent=writer/);
  }
});

test('refresh preserves the chosen mesh and its task entry', async ({ page }) => {
  let submissions = 0;
  page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith('/api/runs')) submissions++; });
  await page.goto('/');
  await openNavigation(page);
  await page.getByRole('navigation', { name: 'Agents', exact: true }).getByRole('button', { name: 'GTM Agent', exact: true }).click();
  await expect(page).toHaveURL(/agent=gtm-mesh/);
  await expect(page.getByRole('textbox', { name: 'Message GTM Agent' })).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Run', exact: true })).toBeDisabled();
  await page.reload();
  await expect(selected(page)).toHaveText('GTM Agent');
  await expect(page.getByRole('button', { name: 'Choose action' })).toHaveCount(0);
  await expect(page.getByRole('textbox', { name: 'Message GTM Agent' })).toBeEnabled();
  expect(submissions).toBe(0);
});

test('two open browsers discover a separate-client run without refresh', async ({ page, context, request }, info) => {
  const second = await context.newPage();
  for (const client of [page, second]) {
    const connected = client.waitForResponse(response => response.url().endsWith('/api/runs/stream'));
    await client.goto('/#agent=offline-check');
    await connected;
    await expect(selected(client)).toHaveText('Offline validation');
  }
  const response = await request.post('/api/runs', { data: { agent_id: 'offline-check', operation: 'check' } });
  expect(response.status()).toBe(202);
  const created = await savedRun(response);
  for (const client of [page, second]) {
    await expect(client).toHaveURL(new RegExp(`task=${created.id}`));
    await expect(latestTurn(client).locator('.run-end')).toContainText('Execution finished');
    await expect(latestTurn(client).locator('.result')).toHaveCount(3);
    await expect(latestTurn(client).locator('.result').last()).toContainText('1 new, 1 changed and 2 unchanged');
  }
  const count = (await savedRuns(await request.get('/api/runs'))).length;
  await page.reload();
  await expect(latestTurn(page).locator('.result')).toHaveCount(3);
  expect((await savedRuns(await request.get('/api/runs'))).length).toBe(count);
  await page.screenshot({ path: info.outputPath('external-run-discovered.png') });
  await second.close();
});

test('desk reconnect replays tasks completed while offline without resubmitting', async ({ page, context, request }) => {
  const cursors: Promise<string | null>[] = [];
  await context.setExtraHTTPHeaders({ 'x-test-disconnect': '1' });
  page.on('request', request => {
    if (request.url().endsWith('/api/runs/stream')) cursors.push(request.headerValue('last-event-id'));
  });
  await page.goto('/#agent=offline-check');
  await expect(selected(page)).toHaveText('Offline validation');
  const submitted = page.waitForResponse(response =>
    response.url().endsWith('/api/runs') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Run', exact: true }).click();
  const own = await (await submitted).json() as SavedRun;
  await expect(page).toHaveURL(new RegExp(`task=${own.id}`));
  await expect(latestTurn(page).locator('.run-end')).toContainText('Execution finished');
  await context.setOffline(true);
  await expect(page.locator('.connection-banner')).toContainText('Reconnecting');
  const response = await request.post('/api/runs', { data: { agent_id: 'offline-check', operation: 'check' } });
  expect(response.status()).toBe(202);
  const created = await savedRun(response);
  const events = await request.get(`/api/runs/${created.id}/events`);
  expect(await events.text()).toContain('"status": "completed"');
  const count = (await savedRuns(await request.get('/api/runs'))).length;
  await context.setExtraHTTPHeaders({});
  await context.setOffline(false);
  await expect(page).toHaveURL(new RegExp(`task=${created.id}`), { timeout: 15000 });
  await expect(latestTurn(page).locator('.run-end')).toContainText('Execution finished');
  await expect(latestTurn(page).locator('.result')).toHaveCount(3);
  await expect(page.locator('.connection-banner')).toHaveCount(0);
  expect((await Promise.all(cursors)).some(cursor => cursor !== null && /^\d+$/.test(cursor))).toBe(true);
  expect((await savedRuns(await request.get('/api/runs'))).length).toBe(count);
});

test('desk updates preserve a draft and reject stale snapshots', async ({ page }) => {
  let release: () => void = () => {};
  const barrier = new Promise<void>(resolve => { release = resolve; });
  const completed = { ...initial, status: 'completed', events: [...initial.events,
    { seq: 2, type: 'result', timestamp: initial.created_at, data: { text: 'External answer' } },
    { seq: 3, type: 'completed', timestamp: initial.created_at, data: { status: 'completed' } },
  ] };
  await page.route('**/api/agents', route => route.fulfill({ json: [agent] }));
  await page.route('**/api/runs', route => route.fulfill({ json: [] }));
  await page.route('**/api/runs/stream', async route => {
    await barrier;
    await route.fulfill({ contentType: 'text/event-stream', body: [completed, initial].map((run, index) =>
      `id: ${index + 1}\ndata: ${JSON.stringify({ runs: [run] })}\n\n`).join('') });
  });
  await page.goto('/');
  const input = page.getByRole('textbox', { name: 'Message Controlled Peer' });
  await input.fill('My unsent task');
  release();
  await openNavigation(page);
  await expect(page.getByRole('navigation', { name: 'Agents', exact: true })
    .getByRole('button', { name: agent.name }).locator('small')).toHaveText('External answer');
  await expect(input).toHaveValue('My unsent task');
  await expect(page).not.toHaveURL(/task=/);
});

test('stale selections cannot show another agents task or overwrite its identity', async ({ page }) => {
  const otherRun = { ...initial, agent_id: 'researcher', status: 'completed', events: [] };
  await page.route('**/api/agents', route => route.fulfill({ json: members }));
  await page.route('**/api/runs', route => route.fulfill({ json: [otherRun] }));
  await page.goto('/#agent=writer&task=controlled-run&action=removed');
  await expect(selected(page)).toHaveText('Writer');
  await expect(page.locator('.request-message')).toHaveCount(0);
  await expect(page).not.toHaveURL(/task=|action=removed/);
  await page.goto('/#agent=removed&task=missing');
  await expect(selected(page)).toHaveText('Researcher');
  await expect(page).toHaveURL(/agent=researcher/);
});

test('all persisted agent turns remain visible across reload', async ({ page }) => {
  const older = { ...initial, id: 'older-run', status: 'completed', message: 'Earlier question',
    created_at: '2026-09-04T09:00:00Z', updated_at: '2026-09-04T09:01:00Z', events: [] };
  await page.route('**/api/agents', route => route.fulfill({ json: [agent] }));
  await page.route('**/api/runs', route => route.fulfill({ json: [
    { ...initial, status: 'completed', message: 'Latest question', events: [] }, older,
  ] }));
  await page.goto('/');
  await expect(selected(page)).toHaveText('Controlled Peer');
  await expect(page.locator('.request-message')).toHaveText(['Earlier question', 'Latest question']);
  await expect(page).toHaveURL(/task=controlled-run/);
  await page.reload();
  await expect(page.locator('.request-message')).toHaveText(['Earlier question', 'Latest question']);
  await expect(page).toHaveURL(/task=controlled-run/);
  await expect(page.getByRole('button', { name: /New task|Task history|Export run|Refresh desk/ })).toHaveCount(0);
});

test('agent markdown renders as structure and never as markup', async ({ page }) => {
  const markdown = [
    '## How the desk assigned this',
    '- **pipeline_builder** — owns it (0.93). See [source](https://sifted.eu/x).',
    '  - Contact owner@example.com at 2026-09-05T10:00:00Z in step_collect_1.',
    '- revenue_operations — declines. <img src=x onerror=alert(1)>',
    '',
    'Approach them with `data-platform` framing.',
    'Record abc123456789 and open https://docs.google.com/document/d/abc123456789/edit.',
    'Hours: https://gallery.example/visit; and https://tate.example/visit.',
    '',
    '```',
    'nexus_call("hubspot", "list_contacts")',
    '```',
  ].join('\n');
  await page.route('**/api/agents', route => route.fulfill({ json: [agent] }));
  await page.route('**/api/runs', route => route.fulfill({ json: [{ ...initial, status: 'completed', events: [
    { seq: 2, type: 'result', timestamp: initial.created_at, data: { text: markdown, obligation_status: 'blocked' } },
    { seq: 3, type: 'completed', timestamp: initial.created_at, data: { status: 'completed' } },
  ] }] }));
  let reconciled = false;
  await page.route('**/api/runs/controlled-run/reconcile', route => {
    reconciled = true;
    return route.fulfill({ json: {
      ...initial, status: 'running', events: [
        { seq: 2, type: 'result', timestamp: initial.created_at, data: { text: markdown, obligation_status: 'blocked' } },
        { seq: 3, type: 'completed', timestamp: initial.created_at, data: { status: 'completed' } },
        { seq: 4, type: 'status', timestamp: initial.created_at, data: { message: 'Goal reconciliation started.' } },
      ],
    } });
  });
  await page.goto('/');
  const result = page.locator('.result-text');
  await expect(page.locator('.goal-outcome')).toHaveText('Goal blocked');
  await expect(page.locator('.run-end')).toContainText('Execution finished');
  await expect(result.getByRole('heading', { name: 'How the desk assigned this' })).toBeVisible();
  await expect(result.locator('li')).toHaveCount(3);
  await expect(result.locator('.markdown > ul > li > ul > li')).toHaveCount(1);
  await expect(result.locator('li strong').first()).toHaveText('pipeline_builder');
  await expect(result.getByText('data-platform', { exact: true })).toBeVisible();
  await expect(result.locator('a.entity-email')).toHaveAttribute('href', 'mailto:owner@example.com');
  await expect(result.locator('time.entity-time')).toHaveAttribute('datetime', '2026-09-05T10:00:00Z');
  await expect(result.locator('code.entity-step')).toContainText(['step_collect_1', 'revenue_operations']);
  await expect(result.locator('code.entity-id')).toHaveText('abc123456789');
  await expect(result.locator('a.entity-link').filter({ hasText: 'Google document' })).toHaveAttribute('target', '_blank');
  await expect(result.locator('a.entity-link').filter({ hasText: 'Google document' })).toHaveAttribute('href', 'https://docs.google.com/document/d/abc123456789/edit');
  await expect(result.locator('a.entity-link').filter({ hasText: 'gallery.example' })).toHaveAttribute('href', 'https://gallery.example/visit');
  await expect(result.locator('a.entity-link').filter({ hasText: 'tate.example' })).toHaveAttribute('href', 'https://tate.example/visit');
  await expect(result).toContainText('gallery.example; and');
  await expect(result.locator('pre')).toContainText('nexus_call("hubspot", "list_contacts")');
  const link = result.getByRole('link', { name: 'source' });
  await expect(link).toHaveAttribute('href', 'https://sifted.eu/x');
  await expect(link).toHaveAttribute('rel', /noreferrer/);
  await expect(result).not.toContainText('##');
  await expect(result).not.toContainText('**');
  await expect(result.locator('img')).toHaveCount(0);
  await expect(result).toContainText('<img src=x onerror=alert(1)>');
  await page.getByRole('button', { name: 'Continue goal' }).click();
  await expect(page.locator('.working')).toContainText('Goal reconciliation started.');
  expect(reconciled).toBe(true);
});

test('typed agent outputs render as artifacts with safe previews', async ({ page }, info) => {
  const types = ['document', 'presentation', 'spreadsheet', 'pdf', 'email', 'image', 'audio', 'video', 'archive', 'file'];
  const artifactRun = { ...initial, status: 'completed', events: [
    { seq: 1, type: 'result', timestamp: initial.created_at, data: { text: 'The requested outputs are ready.' } },
    ...types.map((artifactType, index) => ({
      seq: index + 2, type: 'artifact', timestamp: initial.created_at, data: {
        schema_version: '1', id: `${artifactType}-1`, artifact_type: artifactType,
        title: artifactType === 'email' ? 'Acme follow-up' : `Acme ${artifactType}`,
        url: artifactType === 'email' ? undefined : `https://example.com/${artifactType}-1`,
        provider: artifactType === 'email' ? 'gmail' : 'workspace',
        description: `${artifactType} output from the mesh.`,
        metadata: artifactType === 'email' ? { To: 'buyer@acme.example', Status: 'Draft' } : { Status: 'Created' },
        mime_type: artifactType === 'document' ? 'text/markdown' : undefined,
        preview: artifactType === 'email' ? { kind: 'text', text: 'Hello <script>alert(1)</script> buyer.' }
          : artifactType === 'document' ? { kind: 'text', text: '# Sunday checklist\n\n## Timeline\n\n- [ ] **10:00** Wash vegetables\n- [x] Pack lunches\n\nKeep <b>chilled</b>.' }
          : undefined,
      },
    })),
    { seq: 12, type: 'completed', timestamp: initial.created_at, data: { status: 'completed' } },
  ] };
  await page.route('**/api/agents', route => route.fulfill({ json: [agent] }));
  await page.route('**/api/runs', route => route.fulfill({ json: [artifactRun] }));
  await page.goto('/');

  await expect(page.locator('.artifact')).toHaveCount(types.length);
  await expect(page.getByRole('article', { name: 'Presentation output: Acme presentation' })).toBeVisible();
  await expect(page.getByRole('article', { name: 'Spreadsheet output: Acme spreadsheet' })).toBeVisible();
  const documentArtifact = page.getByRole('article', { name: 'Document output: Acme document' });
  await expect(documentArtifact.getByRole('link', { name: 'Open Acme document' })).toHaveAttribute('target', '_blank');
  await documentArtifact.getByRole('button', { name: 'Preview Acme document' }).click();
  const documentPreview = page.getByRole('dialog', { name: 'Preview Acme document' });
  await expect(documentPreview.getByRole('heading', { name: 'Sunday checklist' })).toBeVisible();
  await expect(documentPreview.getByRole('heading', { name: 'Timeline' })).toBeVisible();
  await expect(documentPreview.locator('strong', { hasText: '10:00' })).toBeVisible();
  await expect(documentPreview.locator('input[type="checkbox"]')).toHaveCount(2);
  await expect(documentPreview.locator('input[type="checkbox"]').nth(1)).toBeChecked();
  await expect(documentPreview).not.toContainText('# Sunday');
  await expect(documentPreview).not.toContainText('[ ]');
  await expect(documentPreview).not.toContainText('**');
  await expect(documentPreview.locator('b')).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('document-preview.png') });
  await documentPreview.getByRole('button', { name: 'Close preview' }).last().click();
  const artifactBorders = await documentArtifact.evaluate(element => {
    const style = getComputedStyle(element);
    return [style.borderTopColor, style.borderLeftColor, style.borderTopWidth, style.borderLeftWidth];
  });
  expect(artifactBorders[0]).toBe(artifactBorders[1]);
  expect(artifactBorders[2]).toBe(artifactBorders[3]);

  const email = page.getByRole('article', { name: 'Email output: Acme follow-up' });
  await email.getByRole('button', { name: 'Preview Acme follow-up' }).click();
  const preview = page.getByRole('dialog', { name: 'Preview Acme follow-up' });
  await expect(preview).toContainText('buyer@acme.example');
  await expect(preview).toContainText('Hello <script>alert(1)</script> buyer.');
  await expect(preview.locator('script')).toHaveCount(0);
  await page.screenshot({ path: info.outputPath('artifact-preview.png') });
  await preview.getByRole('button', { name: 'Close preview' }).last().click();
  await expect(preview).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('structured outputs render their records with output-specific styling', async ({ page }, info) => {
  const outputRun = { ...initial, status: 'completed', events: [
    { seq: 1, type: 'result', timestamp: initial.created_at, data: { text: 'Your schedule and meal plan are ready.' } },
    { seq: 2, type: 'structured_output', timestamp: initial.created_at, data: {
      schema_version: '1', output_type: 'output', title: 'Internal goal', data: {
        owner_id: 'owner-1', objective: 'Plan dinner', success_criteria: ['Complete it'], constraints: ['Tonight'],
      },
    } },
    { seq: 3, type: 'structured_output', timestamp: initial.created_at, data: {
      schema_version: '1', output_type: 'opportunity_set', title: 'Opportunity Set', data: {
        status: 'ready', opportunities: [{ title: 'Internal candidate' }],
      },
    } },
    { seq: 4, type: 'structured_output', timestamp: initial.created_at, data: {
      schema_version: '1', output_type: 'calendar_review', title: 'Next seven days', data: {
        status: 'executed', events: [
          { event_id: 'event-1', title: 'Engineering stand-up', start: '2026-09-24T10:00:00+03:00', end: '2026-09-24T10:15:00+03:00' },
          { event_id: 'event-2', title: 'Deployment', start: '2026-09-24T15:00:00+03:00', end: '2026-09-24T16:00:00+03:00' },
        ], evidence: [{ pointer: 'tool:calendar:1', supports: 'Provider returned both events.' }],
      },
    } },
    { seq: 5, type: 'structured_output', timestamp: initial.created_at, data: {
      schema_version: '1', output_type: 'shopping_plan', title: 'Five vegetarian dinners', data: {
        dinners: [{ title: 'Black bean tacos', servings: 2, ingredients: ['black beans', 'tortillas'] }],
        shopping_items: ['1 can black beans', '4 tortillas'], mutation: { tool_receipt_id: 'tool:file:1', path: 'output/personal-actions/dinners.md' },
      },
    } },
    { seq: 6, type: 'structured_output', timestamp: initial.created_at, data: {
      schema_version: '1', output_type: 'decision_brief', title: 'Weekdays or weekend?', data: {
        status: 'ready', question: 'Weekdays or weekend?', recommendation_option: 'Two weekday sessions',
        options: [
          { title: 'Two weekday sessions', advantages: ['More routine occasions'], risks: ['Less evening flexibility'], unknowns: ['Long-term consistency'] },
          { title: 'One weekend session', advantages: ['Keeps weekdays open'], risks: ['One routine occasion'] },
        ],
        rationale: 'Internal chain of deliberation.', dissent: ['Prefer weekends.'], unresolved: ['No long-term history.'],
      },
    } },
    { seq: 7, type: 'structured_output', timestamp: initial.created_at, data: {
      schema_version: '1', output_type: 'executed', title: 'Executed', data: { status: 'executed' },
    } },
    { seq: 8, type: 'completed', timestamp: initial.created_at, data: { status: 'completed' } },
  ] };
  await page.route('**/api/agents', route => route.fulfill({ json: [agent] }));
  await page.route('**/api/runs', route => route.fulfill({ json: [outputRun] }));
  await page.goto('/');

  const calendar = page.getByRole('article', { name: 'Calendar output: Next seven days' });
  const shopping = page.getByRole('article', { name: 'Meal plan output: Five vegetarian dinners' });
  const decision = page.getByRole('article', { name: 'Decision output: Weekdays or weekend?' });
  await expect(calendar).toHaveClass(/output-family-calendar/);
  await expect(calendar).toContainText('Engineering stand-up');
  await expect(calendar).toContainText('Deployment');
  await expect(shopping).toHaveClass(/output-family-shopping/);
  await expect(shopping).toContainText('Black bean tacos');
  await expect(shopping).toContainText('1 can black beans');
  await expect(decision).toContainText('Recommendation');
  await expect(decision).toContainText('Two weekday sessions');
  await expect(decision).not.toContainText('More routine occasions');
  await expect(decision).not.toContainText('Less evening flexibility');
  await expect(decision).not.toContainText('Internal chain of deliberation');
  await expect(decision).not.toContainText('Prefer weekends');
  await expect(decision).not.toContainText('No long-term history');
  await expect(decision).not.toContainText('Long-term consistency');
  await expect(page.getByText('Internal goal', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Opportunity Set', { exact: true })).toHaveCount(0);
  await expect(calendar).not.toContainText('tool:calendar:1');
  await expect(page.getByRole('button', { name: 'Show provenance' })).toHaveCount(0);
  await expect(page.getByRole('article', { name: 'Executed output: Executed' })).toHaveCount(0);
  const borders = await calendar.evaluate(element => {
    const style = getComputedStyle(element);
    return [style.borderTopColor, style.borderRightColor, style.borderBottomColor, style.borderLeftColor,
      style.borderTopWidth, style.borderLeftWidth];
  });
  expect(new Set(borders.slice(0, 4)).size).toBe(1);
  expect(borders[4]).toBe(borders[5]);
  await page.screenshot({ path: info.outputPath('structured-outputs.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('household work reads as a prep brief and plan, not raw fields', async ({ page }, info) => {
  const householdRun = { ...initial, status: 'completed', events: [
    { seq: 1, type: 'result', timestamp: initial.created_at, data: { text: 'Chicken fajitas for four on Monday.' } },
    { seq: 2, type: 'structured_output', timestamp: initial.created_at, data: {
      schema_version: '1', output_type: 'meal_prep', title: 'Chicken fajitas', data: {
        status: 'done',
        prep: {
          dinner: 'Chicken fajitas', start_cooking_at: '18:00', eat_at: '18:30', servings: 4,
          eating: ['Tunde', 'Claire', 'Ada', 'Noah'],
          ingredients: [
            { item: 'Chicken thighs', quantity: 600, unit: 'g' },
            { item: 'Mixed peppers', quantity: 3, unit: 'each' },
          ],
          steps: ['Slice chicken, peppers and onion', 'Fry hot for 12 minutes'],
        },
      },
    } },
    { seq: 3, type: 'structured_output', timestamp: initial.created_at, data: {
      schema_version: '1', output_type: 'household_plan', title: 'Dinners and shopping', data: {
        status: 'done',
        meal_plan: [{ day: '2026-10-05', recipe: 'Chicken fajitas', servings: 4, eat_at: '18:30', guests: 0 }],
        restock: [{ name: 'Semi-skimmed milk 2L', packs: 4, cost_gbp: 6.6, needed_for: ['daily use'] }],
        restock_total_gbp: 72.5,
        recorded: ['FC-1001 recorded'],
      },
    } },
    { seq: 4, type: 'completed', timestamp: initial.created_at, data: { status: 'completed' } },
  ] };
  await page.route('**/api/agents', route => route.fulfill({ json: [agent] }));
  await page.route('**/api/runs', route => route.fulfill({ json: [householdRun] }));
  await page.goto('/');

  const prep = page.getByRole('article', { name: 'Dinner prep output: Chicken fajitas' });
  await expect(prep).toContainText('Start at 18:00 to eat at 18:30');
  await expect(prep).toContainText('For Tunde, Claire, Ada, Noah');
  await expect(prep).toContainText('600 g Chicken thighs');
  await expect(prep).toContainText('3 × Mixed peppers');
  const plan = page.getByRole('article', { name: 'Dinners and shopping output: Dinners and shopping' });
  await expect(plan).toContainText('Chicken fajitas');
  await expect(plan).toContainText('Total £72.50');
  await expect(plan).toContainText('£6.60');
  for (const raw of ['2026-10-05', 'Start Cooking At', 'Eat At', 'Restock Total', 'FC-1001', 'Done', '{', 'cost_gbp']) {
    await expect(page.locator('article.structured-output')).not.toContainText([raw]);
  }
  await page.screenshot({ path: info.outputPath('household.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('verification reads as confirmed places with official links, not field labels', async ({ page }, info) => {
  const verificationRun = { ...initial, status: 'completed', events: [
    { seq: 1, type: 'result', timestamp: initial.created_at, data: { text: 'Both museums are open on Sunday.' } },
    { seq: 2, type: 'structured_output', timestamp: initial.created_at, data: {
      schema_version: '1', output_type: 'verification_report', title: 'Verification', data: {
        status: 'partial',
        targets: [
          {
            name: 'The National Gallery', finding: 'Free, open Sunday 10:00–18:00.',
            description: 'Long evidence narrative that should stay out of the card.',
            status: 'confirmed', source_name: 'The National Gallery official website',
            url: 'https://www.nationalgallery.org.uk/visiting/plan-your-visit', location: 'Trafalgar Square',
          },
          {
            description: 'Tate Britain opening times were not published for that date.',
            status: 'unknown', source_name: 'Tate official website', url: 'https://www.tate.org.uk/visit',
          },
        ],
        next_checks: ['Check Tate Britain on Saturday.'],
        checked_at: '2026-10-03T07:44:56Z',
      },
    } },
    { seq: 3, type: 'completed', timestamp: initial.created_at, data: { status: 'completed' } },
  ] };
  await page.route('**/api/agents', route => route.fulfill({ json: [agent] }));
  await page.route('**/api/runs', route => route.fulfill({ json: [verificationRun] }));
  await page.goto('/');

  const card = page.getByRole('article', { name: 'Verification output: Verification' });
  await expect(card.getByRole('heading', { name: '1 of 2 confirmed' })).toBeVisible();
  await expect(card).toContainText('The National Gallery');
  await expect(card).toContainText('Free, open Sunday 10:00–18:00.');
  await expect(card).toContainText('Not confirmed');
  await expect(card).toContainText('Tate Britain opening times were not published');
  await expect(card).toContainText('Check Tate Britain on Saturday.');
  await expect(card.getByRole('link', { name: /nationalgallery\.org\.uk/ })).toHaveAttribute('href', 'https://www.nationalgallery.org.uk/visiting/plan-your-visit');
  for (const raw of ['Long evidence narrative', 'Source Name', 'Url', 'Checked At', 'Description', 'Targets']) {
    await expect(card).not.toContainText(raw);
  }
  await page.screenshot({ path: info.outputPath('verification.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('compact sidebar shows latest task results and never wraps long agent names', async ({ page }, info) => {
  const longName = 'Customer Operations and Strategic Account Intelligence';
  const longResult = 'Reviewed the renewal notes and prepared the account summary for tomorrow. '.repeat(5);
  const roster = [{ ...members[0], name: longName }, members[1], members[2], members[3], mesh];
  const finished = {
    ...initial, id: 'latest-finished', agent_id: members[0].id, status: 'completed',
    updated_at: '2026-09-05T13:22:00Z', message: 'The older request must not replace the answer.',
    events: [
      { seq: 2, type: 'result', timestamp: '2026-09-05T13:21:00Z', data: { text: longResult } },
      { seq: 3, type: 'status', timestamp: '2026-09-05T13:22:00Z', data: { message: 'Internal bookkeeping complete.' } },
      { seq: 4, type: 'completed', timestamp: '2026-09-05T13:22:00Z', data: { status: 'completed' } },
    ],
  };
  const older = { ...finished, id: 'older', updated_at: '2026-09-04T13:22:00Z', events: [
    { seq: 1, type: 'result', timestamp: '2026-09-04T13:22:00Z', data: { text: 'Yesterday answer' } },
  ] };
  const failed = { ...finished, id: 'failed', agent_id: members[2].id, status: 'failed', events: [
    { seq: 1, type: 'error', timestamp: finished.updated_at, data: { message: 'Account data unavailable.' } },
    { seq: 2, type: 'result', timestamp: finished.updated_at, data: { text: 'A partial answer is not a success.' } },
  ] };
  const shared = { ...finished, id: 'mesh-finished', agent_id: mesh.id, events: [
    { seq: 1, type: 'result', timestamp: finished.updated_at, data: { text: 'Meeting brief is prepared.' } },
  ] };
  await page.route('**/api/agents', route => route.fulfill({ json: roster }));
  await page.route('**/api/runs', route => route.fulfill({ json: [older, failed, shared, finished] }));
  await page.goto('/');
  await expect(selected(page)).toHaveText(longName);
  await expect(page.locator('.topbar')).toHaveCSS('height', '56px');
  await expect(page.locator('.topbar-title small')).toHaveCount(0);
  await expect(page.locator('.topbar-title strong')).toHaveCSS('font-weight', '400');
  await expect(page.locator('.topbar-title strong')).toHaveText(longName);
  await openNavigation(page);
  const nav = page.getByRole('navigation', { name: 'Agents', exact: true });
  const row = nav.getByRole('button', { name: longName, exact: true });
  await expect(row.locator('small')).toHaveText(longResult.trim());
  await expect(row.locator('time')).toHaveAttribute('datetime', finished.updated_at);
  await expect(row.locator('strong')).toHaveAttribute('title', longName);
  await expect(nav.getByRole('button', { name: 'Writer', exact: true }).locator('small')).toBeEmpty();
  await expect(nav.getByRole('button', { name: 'Reviewer', exact: true }).locator('small')).toHaveText('Account data unavailable.');
  await expect(nav.getByRole('button', { name: 'Mesh', exact: true }).locator('small')).toHaveText('Meeting brief is prepared.');
  await expect(row.locator('strong')).toHaveCSS('white-space', 'nowrap');
  await expect(row.locator('strong')).toHaveCSS('text-overflow', 'ellipsis');
  await expect(row.locator('strong')).toHaveCSS('font-weight', '400');
  const layout = await row.evaluate(element => {
    const name = element.querySelector('strong')!;
    const preview = element.querySelector('small')!;
    const time = element.querySelector('time')!;
    return {
      nameHeight: name.getBoundingClientRect().height,
      previewHeight: preview.getBoundingClientRect().height,
      nameOverflows: name.scrollWidth > name.clientWidth,
      fitsBeforeTime: name.getBoundingClientRect().right <= time.getBoundingClientRect().left,
      timeInside: time.getBoundingClientRect().right <= element.getBoundingClientRect().right,
    };
  });
  expect(layout).toEqual({ nameHeight: 20, previewHeight: 17, nameOverflows: true, fitsBeforeTime: true, timeInside: true });
  await expect(page.locator('.brand')).toHaveCSS('height', '56px');
  await expect(page.locator('.wordmark')).toHaveCSS('width', '120px');
  await page.screenshot({ path: info.outputPath('compact-sidebar-previews.png') });
  if (info.project.name === 'mobile') await page.locator('.sidebar').getByRole('button', { name: 'Close navigation' }).click();
  await expect(page.locator('.conversation-turn')).toHaveCount(2);
  await expect(page.locator('.result-text').last()).toContainText(longResult.trim());
  await page.screenshot({ path: info.outputPath('compact-conversation.png') });
});

test('sidebar preview follows live results and survives refresh', async ({ page }) => {
  const resultEvent = { seq: 2, type: 'result', timestamp: initial.created_at, data: { text: 'Finished checking the renewal evidence.' } };
  const completedEvent = { seq: 3, type: 'completed', timestamp: initial.created_at, data: { status: 'completed' } };
  let completed = false;
  const saved = { ...initial, status: 'completed', events: [...initial.events, resultEvent, completedEvent] };
  await page.route('**/api/agents', route => route.fulfill({ json: [agent] }));
  await page.route('**/api/runs', route => route.fulfill({ json: [completed ? saved : initial] }));
  await page.route('**/api/runs/controlled-run', route => route.fulfill({ json: saved }));
  await page.route('**/api/runs/controlled-run/events', route => {
    completed = true;
    return route.fulfill({ contentType: 'text/event-stream', body: [resultEvent, completedEvent]
      .map(event => `id: ${event.seq}\ndata: ${JSON.stringify(event)}\n\n`).join('') });
  });
  await page.goto('/');
  const preview = page.getByRole('navigation', { name: 'Agents', exact: true }).getByRole('button', { name: agent.name }).locator('small');
  await openNavigation(page);
  await expect(preview).toHaveText(resultEvent.data.text);
  await page.reload();
  await openNavigation(page);
  await expect(preview).toHaveText(resultEvent.data.text);
});