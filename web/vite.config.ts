import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv, type Plugin } from 'vite'

/**
 * Preload the Latin subset of Commissioner.
 *
 * The font is only discovered once the stylesheet has been fetched and parsed
 * and layout has found text that needs it, so the first paint is in the
 * fallback face and every line reflows when the real one arrives. A preload in
 * the document head starts the download with the stylesheet instead of after
 * it. Only the Latin file: it is the one every page uses, and preloading the
 * other five subsets would spend bandwidth on glyphs the page never draws.
 *
 * Build only. The file's hashed name exists only in the bundle, and in
 * development the font is served from `node_modules` uncached anyway.
 */
function preloadLatinFont(): Plugin {
  return {
    name: 'nflfp:preload-latin-font',
    apply: 'build',
    transformIndexHtml: {
      order: 'post',
      handler(_html, context) {
        const font = Object.keys(context.bundle ?? {}).find((file) =>
          /commissioner-latin-wght-normal-[\w-]+\.woff2$/.test(file),
        )
        // A missing file is a changed dependency, not a reason to fail a build:
        // the page still works, it just flashes the fallback again.
        if (!font) {
          this.warn('Commissioner Latin font not found in the bundle; no preload emitted.')
          return []
        }
        return [
          {
            tag: 'link',
            attrs: { rel: 'preload', as: 'font', type: 'font/woff2', href: `/${font}`, crossorigin: '' },
            injectTo: 'head',
          },
        ]
      },
    },
  }
}

// The API is versioned and served under /api/v1. In development we proxy it
// rather than pointing the browser at another origin: the backend enables CORS
// locally, but a proxy keeps the deployed and local shapes identical, so the
// client never needs an absolute base URL and there is no code path that only
// runs in one environment.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_DEV_API_PROXY ?? 'http://127.0.0.1:8010'

  return {
    plugins: [react(), tailwindcss(), preloadLatinFont()],
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
  }
})
