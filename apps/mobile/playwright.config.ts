import { defineConfig } from '@playwright/test'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'
const python =
  process.env.REMOTE_TEST_PYTHON ||
  resolve(existsSync('../../.venv/Scripts/python.exe') ? '../../.venv/Scripts/python.exe' : '../../.venv/bin/python')
export default defineConfig({
  testDir: './tests',
  testMatch: '*.spec.ts',
  fullyParallel: false,
  workers: 1,
  timeout: 30000,
  use: {
    baseURL: 'http://127.0.0.1:8791',
    viewport: { width: 360, height: 800 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure'
  },
  webServer: {
    command: `"${python}" tests/relay_fixture.py`,
    url: 'http://127.0.0.1:8791/api/remote/me',
    reuseExistingServer: false,
    timeout: 30000
  }
})
