import { fileURLToPath, URL } from 'node:url'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Unit tests cover the pure logic under `src/` — sorting, formatting, parsing —
// and run in Node with no DOM. A component is tested here only by rendering it
// to a string, for what it says. Anything that needs a real page is a
// Playwright test under `tests/e2e`, which this config deliberately leaves out.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
