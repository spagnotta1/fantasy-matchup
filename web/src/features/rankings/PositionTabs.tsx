import { NavLink, useSearchParams } from 'react-router-dom'

import { Tooltip } from '@/components/ui/Tooltip'
import { Skeleton } from '@/components/ui/Skeleton'
import { usePositions } from '@/hooks/useCatalog'
import { COMPARE_PARAM, compareSearch, parsePlayerIds } from '@/hooks/useCompareSelection'
import { useSlidingIndicator } from '@/hooks/useSlidingIndicator'
import { cn } from '@/utils/cn'

/**
 * The position selector.
 *
 * Links rather than buttons, because the position lives in the path — a board
 * for running backs is a thing people send each other, and the browser's back
 * button should walk between positions.
 *
 * The list comes from `/meta/positions`, never from a constant. Positions the
 * API reports as unprojected are still rendered, disabled, with the reason the
 * API gave: a manager looking for kickers learns they do not exist yet instead
 * of assuming the filter is broken. The day a kicker model ships, this grows a
 * tab with no change here.
 *
 * It draws no rule of its own. It sits at the foot of the board's sticky bar,
 * whose bottom border is the line the active tab's underline lands on.
 *
 * A tab carries one thing across: the players ticked to compare. Search, team
 * and sort belong to the board they were set on and are dropped, as before. A
 * selection is the reader's, not the board's — a flex decision is a running
 * back against a wide receiver, ticked on two tabs.
 */
export function PositionTabs({ active, className }: { active: string | null; className?: string }) {
  const { data, isPending } = usePositions()
  const [searchParams] = useSearchParams()
  const search = compareSearch(parsePlayerIds(searchParams.get(COMPARE_PARAM)))
  // One underline that slides between tabs. Changing position is a param
  // change on a mounted page (see `routes.tsx`), which is what lets it slide
  // rather than reappear.
  const [ref, underline] = useSlidingIndicator<HTMLUListElement>(`${active}:${data?.length ?? 0}`)

  if (isPending) {
    return (
      <div className={cn('flex gap-2 pb-1.5', className)} aria-hidden>
        {Array.from({ length: 6 }, (_, index) => (
          <Skeleton key={index} className="rounded-control h-6 w-12" />
        ))}
      </div>
    )
  }

  return (
    <nav aria-label="Position" className={cn('-mx-1 overflow-x-auto px-1', className)}>
      <ul ref={ref} className="relative flex min-w-max items-center gap-1">
        {underline && (
          <li
            aria-hidden
            className="bg-accent pointer-events-none absolute h-0.5 rounded-full"
            style={{ ...underline, top: undefined, height: undefined, bottom: 0 }}
          />
        )}
        <li>
          <TabLink to={{ pathname: '/rankings', search }} active={active === null} slid={underline !== null}>
            All
          </TabLink>
        </li>
        {(data ?? []).map((position) => (
          <li key={position.position}>
            {position.projected ? (
              <TabLink
                to={{ pathname: `/rankings/${position.position}`, search }}
                active={active === position.position}
                slid={underline !== null}
                title={position.label}
              >
                {position.position}
              </TabLink>
            ) : (
              <Tooltip content={`${position.label} is not projected yet. ${position.reason ?? ''}`}>
                <span
                  aria-disabled="true"
                  className={cn(TAB, 'text-ink-muted/70 cursor-not-allowed line-through')}
                >
                  {position.position}
                </span>
              </Tooltip>
            )}
          </li>
        ))}
      </ul>
    </nav>
  )
}

/** 32px, the toolbar height, and 44px under a finger: these are the page's navigation. */
const TAB =
  'h-control-sm pointer-coarse:h-touch rounded-t-control text-body inline-flex items-center px-3 font-medium'

function TabLink({
  to,
  active,
  title,
  slid,
  children,
}: {
  to: { pathname: string; search: string }
  active: boolean
  /** The sliding underline is drawn, so the tab should not draw its own. */
  slid: boolean
  title?: string
  children: React.ReactNode
}) {
  return (
    <NavLink
      to={to}
      end
      title={title}
      aria-current={active ? 'page' : undefined}
      data-active={active}
      className={cn(
        TAB,
        'transition-colors',
        // The underline is drawn as a bottom border on the tab itself so it
        // sits on the nav's border rather than floating above it.
        'border-b-2',
        active
          ? cn('text-ink', slid ? 'border-transparent' : 'border-accent')
          : 'text-ink-muted hover:text-ink border-transparent hover:border-line-strong',
      )}
    >
      {children}
    </NavLink>
  )
}
