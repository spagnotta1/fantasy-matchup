import { useState, type ReactNode } from 'react'
import { AlertCircle, Inbox, Info, Loader2, RefreshCw, WifiOff } from 'lucide-react'

import { Button } from '@/components/ui/Button'
import { presentError, ApiError } from '@/api/client'
import { cn } from '@/utils/cn'

/**
 * The failure state.
 *
 * A user is never shown a status code, a stack, or the word "500". They are
 * shown what happened in their terms and, when it is true, that trying again
 * might work. The API's `remedy` field is real and useful — but it names
 * operator commands, so it lives behind a disclosure that only someone looking
 * for it will open.
 */
export function ErrorState({
  error,
  onRetry,
  className,
  compact = false,
}: {
  error: unknown
  onRetry?: () => void
  className?: string
  compact?: boolean
}) {
  const [showDetail, setShowDetail] = useState(false)
  const { title, description, canRetry, operatorDetail } = presentError(error)
  const offline = error instanceof ApiError && error.kind === 'network'
  const Icon = offline ? WifiOff : AlertCircle

  return (
    <div
      role="alert"
      className={cn(
        'flex flex-col items-center justify-center text-center',
        compact ? 'gap-2 px-4 py-8' : 'gap-3 px-6 py-14',
        className,
      )}
    >
      <span className="bg-negative-soft text-negative-text flex size-10 items-center justify-center rounded-full">
        <Icon aria-hidden className="size-5" />
      </span>
      <h3 className="text-ink text-sm font-semibold">{title}</h3>
      <p className="text-ink-secondary max-w-sm text-sm leading-relaxed">{description}</p>

      {canRetry && onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry} className="mt-1">
          <RefreshCw aria-hidden className="size-3.5" />
          Try again
        </Button>
      )}

      {operatorDetail && (
        <div className="mt-2">
          <button
            type="button"
            onClick={() => setShowDetail((current) => !current)}
            className="text-ink-muted hover:text-ink-secondary text-xs underline underline-offset-2"
            aria-expanded={showDetail}
          >
            {showDetail ? 'Hide technical detail' : 'Technical detail'}
          </button>
          {showDetail && (
            <p className="bg-surface-sunken text-ink-muted mt-2 max-w-md rounded-md px-3 py-2 text-left font-mono text-xs break-words">
              {operatorDetail}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

/**
 * The empty state.
 *
 * Never a blank table. An empty result in this product has several distinct
 * causes — a filter that matches nothing, a week whose projection job has not
 * run, a bye — and the copy must say which, because "no data" leaves the user
 * unable to tell a working product from a broken one.
 */
export function EmptyState({
  title,
  description,
  action,
  icon,
  className,
}: {
  title: string
  description: ReactNode
  action?: ReactNode
  icon?: ReactNode
  className?: string
}) {
  return (
    <div
      className={cn('flex flex-col items-center justify-center gap-3 px-6 py-14 text-center', className)}
    >
      <span className="bg-surface-sunken text-ink-muted flex size-10 items-center justify-center rounded-full">
        {icon ?? <Inbox aria-hidden className="size-5" />}
      </span>
      <h3 className="text-ink text-sm font-semibold">{title}</h3>
      <p className="text-ink-secondary max-w-sm text-sm leading-relaxed">{description}</p>
      {action && <div className="mt-1">{action}</div>}
    </div>
  )
}

/**
 * The refresh state: content that is on screen but out of date.
 *
 * Distinct from loading, and it needs to look distinct. A first load has
 * nothing to show and gets a skeleton. A *re-request* — a new week, a different
 * scoring profile, a position filter — still has the previous answer on screen,
 * and replacing it with a skeleton throws away something useful to show
 * something that is not.
 *
 * So the rows stay, dimmed and inert, under a label that says what is
 * happening. Dimming is paired with `aria-busy` and a live message rather than
 * carrying the meaning alone, and pointer events come off so nobody clicks
 * through to a player from a board that is being replaced.
 */
export function Refreshing({
  active,
  children,
  label = 'Updating',
  className,
}: {
  active: boolean
  children: ReactNode
  label?: string
  className?: string
}) {
  return (
    <div className={cn('relative', className)} aria-busy={active || undefined}>
      {active && (
        <div className="pointer-events-none absolute inset-x-0 top-0 z-10 flex justify-center p-3">
          <span className="bg-surface-raised border-line text-ink-secondary shadow-raised flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium">
            <Loader2 aria-hidden className="text-accent size-3.5 animate-spin" />
            {label}
          </span>
        </div>
      )}
      <div
        className={cn(
          'transition-opacity duration-200',
          active && 'pointer-events-none opacity-45 select-none',
        )}
        // Hidden from assistive technology while stale so a screen reader is
        // not walked through numbers that are about to be replaced.
        inert={active || undefined}
      >
        {children}
      </div>
      <span className="sr-only" aria-live="polite">
        {active ? `${label}…` : ''}
      </span>
    </div>
  )
}

/**
 * `meta.notices` from a response.
 *
 * The API returns these for non-fatal things a client should surface: an
 * ungraded matchup, an unpublished week, a correlation caveat. They are the
 * backend telling the UI what it must not quietly omit, so they get a
 * consistent, visible home rather than being dropped on the floor.
 */
export function NoticeList({
  notices,
  className,
  title = 'Worth knowing',
  showTitle = false,
}: {
  notices: string[]
  className?: string
  title?: string
  /**
   * Render the title visibly as well as to assistive technology.
   *
   * Off by default: one list on a screen needs no heading, and adding one to
   * every existing caller would be noise. It earns its place when several lists
   * sit together and the reader has to know which is which — the simulation
   * result separates the caveats that name *your* starters from the ones about
   * the run.
   */
  showTitle?: boolean
}) {
  if (notices.length === 0) return null

  return (
    <aside
      className={cn('bg-info-soft rounded-[var(--radius-card)] px-4 py-3', className)}
      aria-label={title}
    >
      <div className="flex gap-2.5">
        <Info aria-hidden className="text-info-text mt-0.5 size-4 shrink-0" />
        <div className="min-w-0">
          {showTitle && (
            <p className="text-info-text mb-1 text-xs font-semibold">{title}</p>
          )}
          <ul className="text-info-text space-y-1.5 text-xs leading-relaxed">
            {notices.map((notice) => (
              <li key={notice}>{notice}</li>
            ))}
          </ul>
        </div>
      </div>
    </aside>
  )
}
