import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// The API is versioned and served under /api/v1. In development we proxy it
// rather than pointing the browser at another origin: the backend enables CORS
// locally, but a proxy keeps the deployed and local shapes identical, so the
// client never needs an absolute base URL and there is no code path that only
// runs in one environment.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_DEV_API_PROXY ?? 'http://127.0.0.1:8010'

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      port: 5173,
      proxy: {
        '/api': { target, changeOrigin: true },
      },
    },
    // `preview` serves the built bundle, and it needs the same proxy for the
    // same reason: without it the only way to exercise a production build is to
    // deploy it, which makes the deploy the first place a bundling problem can
    // show up. Point VITE_DEV_API_PROXY at the deployed API to QA the real
    // thing — the frontend cannot tell the difference, which is the point.
    preview: {
      port: 4173,
      proxy: {
        '/api': { target, changeOrigin: true },
      },
    },
    build: {
      // Route-level code splitting is handled by React.lazy; this keeps the
      // charting library out of the initial bundle, which is the single
      // biggest win available and does not depend on route boundaries.
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (id.includes('node_modules/recharts') || id.includes('node_modules/d3-')) {
              return 'charts'
            }
            return undefined
          },
        },
      },
    },
  }
})
