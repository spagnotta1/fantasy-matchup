import { useEffect, useState, type MouseEvent, type Ref, type RefObject } from 'react'
import { Check, ChevronLeft, ChevronRight, GitCompareArrows, UserPlus } from 'lucide-react'

import { IconButton, IconButtonLink } from '@/components/ui/Button'
import { PlayerAvatar } from '@/components/domain/PlayerIdentity'
import { OutcomeRange, ProjectionValue } from '@/components/domain/ProjectionValue'
import { useSlate } from '@/app/slate-context'
import { cn } from '@/utils/cn'
import { scrollBehavior } from '@/utils/motion'
import { formatPercent, formatThreshold } from '@/utils/format'
import type { Player, Projection } from '@/api/schemas'

/** A part of the page the bar can jump to. The id is the section's element id. */
export interface PageSection {
  id: string
  label: string
}

/** The bar's own width from which the section links fit inside it, in pixels. */
export const BAR_LINKS_FROM = 720

/**
 * The width from which the links, the name, the chance of 20+ and the two
 * actions all fit beside the stepper. Between the two, the links are in the
 * bar and the name gets what is left: at 820px the rest squeezed it to
 * nothing, and a bar that says "17.1" without saying whose is no use.
 */
export const BAR_ROOMY_FROM = 960

/**
 * The bar that stays in view down the player page.
 *
 * The page is three screens long, and its two questions are asked from anywhere
 * in it: who is this and what are they projected for, and what about the week
 * before. So three things stay under the application bar while the page
 * scrolls:
 *
 *   - **The week stepper.** One press moves the whole page a week, from
 *     wherever the reader is: looking at the matchup, step back, and it is last
 *     week's matchup. It writes the same `?week=` every other screen reads.
 *   - **Who and how much**, once the header above has scrolled away: the name
 *     and the projection always, and the range strip, the chance of 20+ and
 *     the header's two actions where there is room. Until then the header
 *     says all of it and the bar does not repeat it.
 *   - **The section links**, where there is room for them. On a phone the bar
 *     is one line, and the links sit under the header instead: a second sticky
 *     line would cost a tenth of the screen for the whole scroll.
 *
 * The summary repeats the header for the eye and is hidden from assistive
 * technology, which has the header's own heading and figures to go by.
 */
export function PlayerBar({
  player,
  projection,
  sections,
  heroRef,
  withLinks,
  roomy,
  onRoster,
  onAdd,
  ref,
}: {
  player: Player
  projection: Projection | null | undefined
  sections: PageSection[]
  /** The header above. The summary is drawn once this is out of view. */
  heroRef: RefObject<HTMLElement | null>
  /** The bar has room for the section links (the caller measures it). */
  withLinks: boolean
  /** And for the chance of 20+ and the header's actions beside them. */
  roomy: boolean
  /** Null where the player cannot be added to a roster: a kicker. */
  onRoster: boolean | null
  onAdd: () => void
  ref?: Ref<HTMLDivElement>
}) {
  const heroGone = useScrolledPast(heroRef)
  const points = projection?.prediction.points

  return (
    <div
      ref={ref}
      data-player-bar=""
      className="bg-bg border-line @container sticky top-[calc(var(--spacing-shell-bar)+1px)] z-20 -mx-4 mb-4 flex min-h-11 items-center gap-x-4 border-b px-4 py-1 sm:-mx-6 sm:px-6"
    >
      {withLinks && <SectionLinks sections={sections} className="shrink-0" />}

      <div
        aria-hidden
        data-visible={heroGone || undefined}
        className={cn(
          'flex min-w-0 flex-1 items-center gap-2 transition-opacity duration-150',
          withLinks && 'justify-end',
          heroGone ? 'opacity-100' : 'invisible opacity-0',
        )}
      >
        <PlayerAvatar player={player} size="xs" />
        <span className="text-ink text-body truncate font-semibold">{player.name}</span>
        {points && (
          <>
            <ProjectionValue points={points} className="shrink-0" />
            <OutcomeRange
              floor={points.floor}
              p25={points.p25}
              median={points.median}
              p75={points.p75}
              ceiling={points.ceiling}
              threshold={points.boom_threshold}
              scaleMax={Math.max(40, points.ceiling ?? 0)}
              className="w-56 shrink-0 max-xl:hidden"
            />
            {/* Where the links share the bar, and on the narrowest phones,
                the name needs the room more. */}
            {(roomy || !withLinks) && (
              <span className="text-ink-secondary tnum text-chip shrink-0 whitespace-nowrap @max-[25rem]:hidden">
                <span className="text-ink font-semibold">{formatPercent(points.boom_probability)}</span> of{' '}
                {formatThreshold(points.boom_threshold)}+
              </span>
            )}
          </>
        )}
      </div>

      {/* The header's two actions, where the header itself is out of reach. */}
      {heroGone && roomy && onRoster !== null && (
        <div className="flex shrink-0 items-center">
          {onRoster ? (
            <IconButtonLink to="/my-team" label="On your team">
              <Check />
            </IconButtonLink>
          ) : (
            <IconButton label="Add to my team" onClick={onAdd}>
              <UserPlus />
            </IconButton>
          )}
          <IconButtonLink to={`/compare?players=${player.player_id}`} label="Compare">
            <GitCompareArrows />
          </IconButtonLink>
        </div>
      )}

      <WeekStepper />
    </div>
  )
}

/**
 * Links to the parts of the page. In-page anchors: each scrolls its section to
 * just under the bar and moves focus there, so the next Tab carries on from the
 * section and not from the top of the page.
 */
export function SectionLinks({ sections, className }: { sections: PageSection[]; className?: string }) {
  const jump = (event: MouseEvent<HTMLAnchorElement>, id: string) => {
    const target = document.getElementById(id)
    if (!target) return
    event.preventDefault()
    target.scrollIntoView({ behavior: scrollBehavior(), block: 'start' })
    target.focus({ preventScroll: true })
  }

  return (
    <nav aria-label="On this page" className={cn('-mx-1 overflow-x-auto px-1', className)}>
      <ul className="flex min-w-max items-center gap-1">
        {sections.map((section) => (
          <li key={section.id}>
            <a
              href={`#${section.id}`}
              onClick={(event) => jump(event, section.id)}
              className="text-ink-secondary hover:text-ink hover:bg-surface-hover rounded-control text-detail h-control-sm pointer-coarse:h-touch inline-flex items-center px-2.5 font-medium whitespace-nowrap transition-colors"
            >
              {section.label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  )
}

/**
 * One week back, one week on.
 *
 * It steps through the weeks that have a published board, so a press never
 * lands on an empty page. At either end the button stays where it is and says
 * why it does nothing: a button that disappears, or is disabled outright,
 * drops the keyboard's focus to the top of the document mid-way through
 * stepping.
 */
function WeekStepper() {
  const slate = useSlate()
  const { week, availableWeeks } = slate
  const earlier = week === null ? undefined : availableWeeks.filter((candidate) => candidate < week).at(-1)
  const later = week === null ? undefined : availableWeeks.find((candidate) => candidate > week)

  return (
    <div role="group" aria-label="Week" className="ml-auto flex shrink-0 items-center">
      <IconButton
        label={earlier === undefined ? 'No earlier week is published' : `Previous week: week ${earlier}`}
        aria-disabled={earlier === undefined || undefined}
        onClick={() => earlier !== undefined && slate.setWeek(earlier)}
      >
        <ChevronLeft />
      </IconButton>
      <span className="text-ink tnum text-detail min-w-16 text-center font-semibold whitespace-nowrap" aria-live="polite">
        Week {week ?? '—'}
      </span>
      <IconButton
        label={later === undefined ? 'No later week is published' : `Next week: week ${later}`}
        aria-disabled={later === undefined || undefined}
        onClick={() => later !== undefined && slate.setWeek(later)}
      >
        <ChevronRight />
      </IconButton>
    </div>
  )
}

/**
 * Whether an element has scrolled up out of view, under the two bars at the
 * top of the page. Observed, not computed from scroll events.
 */
function useScrolledPast(ref: RefObject<HTMLElement | null>): boolean {
  const [gone, setGone] = useState(false)

  useEffect(() => {
    const element = ref.current
    if (!element) return
    // The application bar and this one cover about 104px of the viewport's top.
    const observer = new IntersectionObserver(([entry]) => setGone(entry ? !entry.isIntersecting : false), {
      rootMargin: '-104px 0px 0px 0px',
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [ref])

  return gone
}
