import { defineConfig, devices } from '@playwright/test'

/**
 * Browser tests.
 *
 * `E2E_BASE_URL` decides what is under test and nothing else changes:
 *
 *   - unset            -> a local `vite preview` of the production bundle in
 *                         `dist/`, proxying /api to the local API (or to
 *                         whatever VITE_DEV_API_PROXY names). Run
 *                         `npm run build` first.
 *   - a Railway origin -> the real deployment, real data, same origin.
 *
 * Local is the default. It used to be the deployment, which made a red test
 * ambiguous — this checkout, or this week's data — and meant a change could
 * only be tested after it shipped. The deployment is still the right target
 * for what only exists there (cold start, gzip, SPA deep links), and it is one
 * variable away.
 *
 * Two sets of projects:
 *
 *   - `desktop`, `mobile`               -> `tests/e2e`, behaviour, against a
 *                                          live API.
 *   - `visual-desktop`, `visual-tablet`, `visual-mobile`
 *                                       -> `tests/visual`, screenshots, against
 *                                          recorded API responses. No backend.
 */
const LOCAL_PREVIEW = 'http://localhost:4173'
const baseURL = process.env.E2E_BASE_URL ?? LOCAL_PREVIEW
const isLocal = baseURL.includes('localhost') || baseURL.includes('127.0.0.1')

export default defineConfig({
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
  // Baselines are kept per platform: text is rasterised differently on Windows
  // and Linux, and one platform's picture never matches the other's.
  snapshotPathTemplate: '{testDir}/__screenshots__/{platform}/{projectName}/{arg}{ext}',
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
    {
      name: 'desktop',
      testDir: './tests/e2e',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    { name: 'mobile', testDir: './tests/e2e', use: { ...devices['Pixel 7'] } },
    {
      name: 'visual-desktop',
      testDir: './tests/visual',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
    {
      // Between the two: no sidebar, and less room than a laptop. Only the
      // screens whose tables change shape here are photographed at it (see
      // `tablet` in `visual.spec.ts`).
      name: 'visual-tablet',
      testDir: './tests/visual',
      use: { ...devices['Desktop Chrome'], viewport: { width: 820, height: 1180 }, hasTouch: true },
    },
    {
      name: 'visual-mobile',
      testDir: './tests/visual',
      // A Pixel 7's width and touch behaviour at one device pixel per CSS
      // pixel: the layout is what is under review, and a 2.6x picture of it is
      // seven times the bytes in the repository for the same information.
      use: { ...devices['Pixel 7'], deviceScaleFactor: 1 },
    },
  ],
  webServer: isLocal
    ? { command: 'npm run preview -- --port 4173', url: baseURL, reuseExistingServer: true, timeout: 60_000 }
    : undefined,
})
