import { defineConfig, devices } from '@playwright/test';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

const ui = resolve('..');
const home = mkdtempSync(join(tmpdir(), 'jarviscore-ui-e2e-'));

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  use: { baseURL: 'http://127.0.0.1:8766', trace: 'retain-on-failure' },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
    { name: 'mobile', use: { ...devices['Pixel 7'], viewport: { width: 390, height: 844 } } },
  ],
  webServer: {
    command: `PYTHONPATH="${ui}" JARVISCORE_DESK_HOME="${home}" "${ui}/.venv/bin/python" -m uvicorn tests.browser_server:app --host 127.0.0.1 --port 8766 --timeout-graceful-shutdown 2`,
    url: 'http://127.0.0.1:8766/api/health',
    reuseExistingServer: false,
    timeout: 30000,
  },
});