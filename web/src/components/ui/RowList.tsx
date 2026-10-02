import type { CSSProperties, HTMLAttributes, LiHTMLAttributes, ReactNode, Ref } from 'react'
import { Link, type LinkProps } from 'react-router-dom'

import { cn } from '@/utils/cn'

/**
 * The row list: what a table of players becomes where there is no room for its
 * columns.
 *
 * A table that scrolls sideways on a phone keeps the name in view and shows
 * one other column at a time, so the two numbers a page exists to set side by
 * side — live points and the projection, a designation and the number it
 * qualifies — are never on screen together. The list puts every column of a
 * row on a few short lines instead: who and the row's headline number on the
 * first, the rest under them. Nothing the table shows is left out.
 *
 * It began as the board's phone drawing (`ProjectionList`), and these are that
 * list's parts, so the board and every other screen that folds its table draw
 * the same row:
 *
 *   - `RowList`        the frame, and the one line that says what the
 *                      right-hand number is, since a list has no header row
 *   - `RowListGroup`   a headed section: a tier, a designation, a position
 *   - `RowListRows`    the rows of one group, or of the whole list
 *   - `RowListItem`    one row, which is one link
 *   - `RowListTitle`   the name, then what places the player, then any caveat
 *   - `RowListLine`    a further line under the name
 *
 * A list and not a table. Lines of a row are not a grid of columns, and a
 * `<table>` laid out this way would announce cells that are not in the column
 * their header names.
 *
 * ## One link per row
 *
 * The whole row is the link to the player, as on the board, and it holds no
 * second link: a team abbreviation that is a link in the table is plain text
 * here. A 13px link inside a row that is itself a link is a target a thumb
 * misses in both directions.
 *
 * ## When
 *
 * `useRowList` (`hooks/useRowList`) measures the room a table has and says
 * which to draw. The board keeps its own rule, a table from 948px.
 */

export function RowList({
  label = 'Player',
  value,
  note,
  lead = '1.5rem',
  className,
  children,
  ref,
}: {
  /** What the left of each row holds. */
  label?: string
  /** What the right-hand number of each row is: "Projected points". */
  value: string
  /** One line on how to read a mark the rows draw, where a table's header had a tip. */
  note?: ReactNode
  /** The width of each row's leading slot, as a CSS length: a rank, a headshot. */
  lead?: string
  className?: string
  children: ReactNode
  ref?: Ref<HTMLDivElement>
}) {
  return (
    // A query container, so a line can fold by the list's own width.
    <div
      ref={ref}
      data-row-list=""
      className={cn('@container', className)}
      style={{ '--row-lead': lead } as CSSProperties}
    >
      <p className="border-line-strong text-caption text-ink-muted flex justify-between border-b px-3 py-2 font-semibold">
        <span>{label}</span>
        <span>{value}</span>
      </p>
      {note && <p className="border-line text-ink-muted text-chip border-b px-3 py-1.5">{note}</p>}
      {children}
    </div>
  )
}

export function RowListGroup({
  id,
  as: Heading = 'h3',
  heading,
  note,
  children,
}: {
  /** The heading's id, unique on the page: the section is named by it. */
  id: string
  /** Heading level. The one the document outline needs under the heading above the list. */
  as?: 'h2' | 'h3'
  heading: ReactNode
  /** Said after the heading in a lighter voice: "15 players". */
  note?: ReactNode
  children: ReactNode
}) {
  return (
    <section aria-labelledby={id} className="border-line border-b last:border-b-0">
      <Heading
        id={id}
        className="bg-surface-sunken border-line text-caption text-ink-secondary border-b px-3 py-1 font-semibold"
      >
        {heading}
        {note && <span className="text-ink-muted ml-2 font-normal">{note}</span>}
      </Heading>
      {children}
    </section>
  )
}

export function RowListRows({ className, ...props }: HTMLAttributes<HTMLUListElement>) {
  return <ul className={cn('divide-line divide-y', className)} {...props} />
}

export interface RowListItemProps extends LiHTMLAttributes<HTMLLIElement> {
  /** Where the row goes. */
  to: LinkProps['to']
  /**
   * This row belongs to a set the reader marked: a player on their own roster.
   * A tint only, so the row must also say so in words.
   */
  highlighted?: boolean
  ref?: Ref<HTMLLIElement>
}

/**
 * One row. Its children are laid on a three-column grid — the leading slot,
 * the title, the headline number — and each `RowListLine` after them takes a
 * line of its own under the title.
 */
export function RowListItem({ to, highlighted = false, className, children, ...props }: RowListItemProps) {
  return (
    <li
      className={cn(
        // Published as `--row-rest`, so an animation that flashes the row
        // (a score crossing the line to gain) settles back on the tint.
        highlighted &&
          'bg-(--row-rest) [--row-rest:color-mix(in_oklch,var(--color-accent-soft)_40%,var(--color-surface))]',
        className,
      )}
      {...props}
    >
      <Link
        to={to}
        className="hover:bg-surface-hover focus-visible:outline-focus grid grid-cols-[var(--row-lead,1.5rem)_minmax(0,1fr)_auto] items-center gap-x-2 gap-y-1 px-3 py-2 transition-colors focus-visible:-outline-offset-2"
      >
        {children}
      </Link>
    </li>
  )
}

export function RowListTitle({
  name,
  meta,
  children,
}: {
  name: ReactNode
  /** Position, team, opponent: one unbroken grey run after the name. */
  meta?: ReactNode
  /** Caveats and marks after the meta: an injury designation, "My team". */
  children?: ReactNode
}) {
  return (
    <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
      <span className="text-ink text-body truncate font-semibold">{name}</span>
      {meta && <span className="text-ink-muted text-chip whitespace-nowrap">{meta}</span>}
      {children}
    </span>
  )
}

export function RowListLine({ className, ...props }: HTMLAttributes<HTMLSpanElement>) {
  return <span className={cn('col-span-2 col-start-2 flex items-center gap-2', className)} {...props} />
}
