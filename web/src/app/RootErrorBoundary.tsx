import { isRouteErrorResponse, Link, useRouteError } from 'react-router-dom'

import { ErrorState } from '@/components/feedback/States'
import { Card } from '@/components/ui/Card'

/**
 * The last line of defence.
 *
 * Route-level failures are caught by the views themselves; this catches what
 * they could not — a render crash, a chunk that failed to download. It shows
 * the same error language as everywhere else rather than React's default
 * white-screen, and offers the one action that reliably recovers.
 */
export function RootErrorBoundary() {
  const error = useRouteError()

  if (isRouteErrorResponse(error) && error.status === 404) {
    return (
      <div className="mx-auto max-w-lg px-4 py-20">
        <Card className="p-8 text-center">
          <h1 className="text-ink text-lg font-semibold">Page not found</h1>
          <p className="text-ink-secondary mt-2 text-sm">
            That address doesn't match anything in the app.
          </p>
          <Link
            to="/"
            className="bg-accent text-on-accent hover:bg-accent-hover mt-5 inline-flex h-10 items-center rounded-[var(--radius-control)] px-4 text-sm font-medium transition-colors"
          >
            Back to this week
          </Link>
        </Card>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-lg px-4 py-20">
      <Card>
        <ErrorState error={error} onRetry={() => window.location.reload()} />
      </Card>
    </div>
  )
}
