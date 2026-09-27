import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from 'react-router-dom'

import { queryClient } from '@/app/queryClient'
import { router } from '@/app/routes'

// Self-hosted rather than fetched from a font CDN: no third-party request on
// every page load, and the face is in the bundle the service already caches.
import '@fontsource-variable/commissioner'
import './styles/index.css'

const container = document.getElementById('root')
if (!container) throw new Error('Root element #root is missing from index.html')

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
