import { defineConfig, devices } from '@playwright/test'

/**
 * Phase 8 QA harness.
 *
 * `E2E_BASE_URL` decides what is under test and nothing else changes:
 *
 *   - unset            -> a local `vite preview` of the production bundle,
 *                         proxying /api to whatever VITE_DEV_API_PROXY names.
 *   - a Railway origin -> the real deployment, real data, same origin.
 *
 * The deployed origin is the default target because most of what Phase 8 asks
 * about — cold start, gzip, SPA deep links, a published week that actually has
 * projections in it — only exists there. A local server would answer a
 * different question convincingly.
 */
const baseURL = process.env.E2E_BASE_URL ?? 'https://api-production-e5552.up.railway.app'
const isLocal = baseURL.includes('localhost') || baseURL.includes('127.0.0.1')

export default defineConfig({
  testDir: './tests/e2e',
  // Two workers whether the target is local or deployed. Every run — including
  // the local one — goes through a single API instance behind a single cache,
  // so the default worker count measures contention rather than the app: runs
  // at eight workers produced request timeouts that pass on their own.
  workers: 2,
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  timeout: 60_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL,
    // A simulation against the live API is genuinely slow; the default 30s
    // action timeout fails on a legitimate response rather than a defect.
    actionTimeout: 20_000,
    navigationTimeout: 45_000,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
    { name: 'mobile', use: { ...devices['Pixel 7'] } },
  ],
  webServer: isLocal
    ? { command: 'npm run preview -- --port 4173', url: baseURL, reuseExistingServer: true, timeout: 60_000 }
    : undefined,
})
