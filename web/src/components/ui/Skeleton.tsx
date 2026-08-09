import { cn } from '@/utils/cn'

/**
 * A loading placeholder.
 *
 * Skeletons rather than a spinner, because the shape of a screen is information
 * on its own: a user who can see a table forming knows what is coming and does
 * not re-read the page when it arrives. Every skeleton here should be the same
 * height as the content it stands in for, or it causes the layout shift it was
 * meant to prevent.
 */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={cn('bg-surface-sunken animate-shimmer rounded-md', className)}
    />
  )
}

/** A block of stacked lines, for prose and list rows. */
export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={cn('space-y-2', className)}>
      {Array.from({ length: lines }, (_, index) => (
        <Skeleton
          key={index}
          // A ragged last line reads as text rather than as a grey brick.
          className={cn('h-3.5', index === lines - 1 ? 'w-2/3' : 'w-full')}
        />
      ))}
    </div>
  )
}

/**
 * A table-shaped placeholder that preserves the real column layout, so the
 * header does not jump sideways when rows arrive.
 */
export function SkeletonTable({ rows = 8, columns = 5 }: { rows?: number; columns?: number }) {
  return (
    <div role="status" aria-label="Loading data" className="space-y-2 p-4">
      {Array.from({ length: rows }, (_, rowIndex) => (
        <div
          key={rowIndex}
          className="grid items-center gap-4"
          style={{ gridTemplateColumns: `2.5rem 2fr repeat(${Math.max(columns - 2, 1)}, 1fr)` }}
        >
          <Skeleton className="h-4 w-6" />
          <Skeleton className="h-4 w-full max-w-44" />
          {Array.from({ length: Math.max(columns - 2, 1) }, (_, cellIndex) => (
            <Skeleton key={cellIndex} className="h-4 w-12 justify-self-end" />
          ))}
        </div>
      ))}
    </div>
  )
}

/** A grid of card placeholders, for the card view and dashboard panels. */
export function SkeletonCards({ count = 6 }: { count?: number }) {
  return (
    <div
      role="status"
      aria-label="Loading"
      className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3"
    >
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className="bg-surface border-line rounded-[var(--radius-card)] border p-4">
          <div className="flex items-center gap-3">
            <Skeleton className="size-10 rounded-full" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-3 w-20" />
            </div>
          </div>
          <Skeleton className="mt-4 h-8 w-24" />
          <div className="mt-4 flex gap-2">
            <Skeleton className="h-6 w-16" />
            <Skeleton className="h-6 w-16" />
          </div>
        </div>
      ))}
    </div>
  )
}
