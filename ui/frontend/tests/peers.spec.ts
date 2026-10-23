import { expect, test } from '@playwright/test';

const operation = { id: 'task', label: 'Send task', description: 'Controlled test', allows_message: true };
const peers = [
  { id: 'account', name: 'Account Expert', color: '#397b72' },
  { id: 'revenue_operations', name: 'Revenue Operations', color: '#ab5876' },
  { id: 'pipeline_builder', name: 'Pipeline Builder', color: '#bd6847' },
].map(peer => ({ ...peer, blueprint: 'test', description: 'Test peer', operations: [operation] }));
const timestamp = '2026-09-05T14:30:00Z';
const run = {
  id: 'peer-run', agent_id: 'pipeline_builder', operation: 'task', message: 'Prepare the account draft',
  status: 'completed', created_at: timestamp, updated_at: timestamp,
  events: [
    { seq: 1, type: 'peer_message', timestamp, data: { recipient_id: 'pipeline_builder', messages: [
      { sender_id: 'account', text: 'The account notes identify an upcoming renewal.' },
      { sender_id: 'revenue_operations', text: 'The last interaction is logged; no follow-up has been sent.' },
    ] } },
    { seq: 2, type: 'peer_message', timestamp, data: { recipient_id: 'pipeline_builder', messages: [
      { sender_id: 'account', text: 'The account notes identify an upcoming renewal.' },
      { sender_id: 'revenue_operations', text: 'The last interaction is logged; no follow-up has been sent.' },
    ] } },
    { seq: 3, type: 'result', timestamp, data: { text: 'Prepared a draft from the supplied evidence.' } },
    { seq: 4, type: 'peer_message', timestamp: '2026-09-05T14:30:05Z', data: { recipient_id: 'pipeline_builder', messages: [
      { sender_id: 'account', text: 'The account notes identify an upcoming renewal.' },
      { sender_id: 'revenue_operations', text: 'The last interaction is logged; no follow-up has been sent.' },
    ] } },
    { seq: 5, type: 'completed', timestamp, data: { status: 'completed' } },
  ],
};
const accountRun = {
  id: 'account-run', agent_id: 'account', operation: 'task', message: 'Review account context',
  status: 'completed', created_at: timestamp, updated_at: timestamp,
  events: [
    { seq: 1, type: 'result', timestamp, data: { text: 'Account context reviewed.' } },
    { seq: 2, type: 'completed', timestamp, data: { status: 'completed' } },
  ],
};

test('received peer messages show actual sender identities, survive reload and navigate without rerunning', async ({ page }, info) => {
  let submissions = 0;
  await page.route('**/api/agents', route => route.fulfill({ json: peers }));
  await page.route('**/api/runs', route => {
    if (route.request().method() === 'POST') submissions++;
    return route.fulfill({ json: [run, accountRun] });
  });
  await page.goto('/#agent=pipeline_builder&task=peer-run');
  const received = page.getByRole('region', { name: 'Peer messages' });
  await expect(received).toHaveCount(2);
  await expect(received.first().locator('header')).toContainText('Received from');
  await expect(received.first().locator('header')).toContainText('Account Expert');
  await expect(received.first().locator('header')).toContainText('and');
  await expect(received.first().locator('header')).toContainText('Revenue Operations');
  await expect(received.first().locator('.peer-message-body')).toContainText('no follow-up has been sent');
  await expect(received.first().locator('.peer-message-body .avatar')).toHaveCount(2);
  expect(new Set(await received.first().locator('header .avatar').evaluateAll(elements => elements.map(element => getComputedStyle(element).backgroundColor))).size).toBe(2);
  await page.screenshot({ path: info.outputPath('received-peer-messages.png') });
  await page.reload();
  await expect(received).toHaveCount(2);
  await received.first().locator('header').getByRole('button', { name: 'Open Account Expert' }).click();
  await expect(page.locator('.topbar-title')).toHaveText('Account Expert');
  await expect(page.locator('.request-message')).toContainText('Review account context');
  const accountPeerHistory = page.getByRole('region', { name: 'Peer messages' });
  await expect(accountPeerHistory).toContainText('upcoming renewal');
  await expect(accountPeerHistory.getByText('The account notes identify an upcoming renewal.', { exact: true })).toHaveCount(2);
  const navigation = page.getByRole('button', { name: 'Open navigation' });
  if (await navigation.isVisible()) await navigation.click();
  await page.getByRole('navigation', { name: 'Agents', exact: true }).getByRole('button', { name: 'Pipeline Builder', exact: true }).click();
  await expect(received).toHaveCount(2);
  expect(submissions).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('peer content is text, not HTML, and sender lookup does not invent an identity', async ({ page }) => {
  const hostile = structuredClone(run);
  hostile.events[0].data.messages![0].text = '<img src=x onerror=alert(1)> Test text';
  await page.route('**/api/agents', route => route.fulfill({ json: peers.filter(peer => peer.id !== 'account') }));
  await page.route('**/api/runs', route => route.fulfill({ json: [hostile] }));
  await page.goto('/#agent=pipeline_builder&task=peer-run');
  await expect(page.locator('.peer-message-body').first()).toContainText('<img src=x onerror=alert(1)>');
  await expect(page.locator('.peer-message-body img')).toHaveCount(0);
  await expect(page.locator('.peer-messages header').first()).toContainText('Unavailable peer');
});