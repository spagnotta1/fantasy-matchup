import { QueryClient } from '@tanstack/react-query'

import { ApiError } from '@/api/client'

/**
 * Server-state defaults.
 *
 * Tuned to what this API actually is: a read-mostly service over data that
 * changes on a weekly job schedule, behind a response cache that already serves
 * repeated reads. Refetching a projection board because a window regained focus
 * would spend a request to receive a byte-identical body.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // A published model run never changes. Five minutes is short enough for
      // the one thing that does move — the default week rolling forward at
      // kickoff — and long enough that navigating between views is free.
      staleTime: 5 * 60 * 1000,
      gcTime: 30 * 60 * 1000,
      refetchOnWindowFocus: false,
      refetchOnReconnect: true,
      retry: (failureCount, error) => {
        // Retrying a 404 or a 422 is pointless: the request is wrong and will
        // be wrong again. Only transient failures are worth a second attempt.
        if (error instanceof ApiError && !error.isRetryable) return false
        return failureCount < 2
      },
      retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
    },
    mutations: {
      retry: false,
    },
  },
})
