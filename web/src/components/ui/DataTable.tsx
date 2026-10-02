import {
  createContext,
  use,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type HTMLAttributes,
  type MouseEvent,
  type ReactNode,
  type Ref,
  type TdHTMLAttributes,
  type ThHTMLAttributes,
} from 'react'
import { Link, type LinkProps } from 'react-router-dom'
import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react'

import { Skeleton } from '@/components/ui/Skeleton'
import { Tooltip } from '@/components/ui/Tooltip'
import { cn } from '@/utils/cn'
import { nextSort, sortRows, type SortDirection, type SortState, type SortValue } from '@/utils/tableSort'

/**
 * The table.
 *
 * One way to draw a table, so that a column of numbers reads the same on every
 * screen: a real `<table>` with a caption and scoped headers, sentence-case
 * headers in one type size, numbers right-aligned in tabular figures, a header
 * that stays put, and three row heights.
 *
 * ## Two layers
 *
 * The parts — `Table`, `TableHead`, `ColumnHeader`, `TableBody`, `TableRow`,
 * `TableCell`, `RowHeaderCell`, `GroupHeaderRow`, `RowLink` — are the table's
 * vocabulary. Composing them directly is for a table whose body is not a flat
 * list: tier groups, memoised rows, an expanding detail row.
 *
 * `DataTable` is the ordinary case written once: columns as data, rows as
 * data, and sorting, loading and the empty state handled. It is built from the
 * parts and from nothing else, so the two cannot drift apart.
 *
 * ## Sticky header, and what scrolls
 *
 * `position: sticky` sticks to the nearest scrolling ancestor, and a wrapper
 * with `overflow-x: auto` is one — which is why the tables this replaces lost
 * their headers a screen down the page. So the table does not scroll sideways
 * unless it has to. Given a `minWidth`, it measures the room it has:
 *
 *   - enough room: nothing scrolls but the page, and the header sticks under
 *     the application bar;
 *   - not enough: the table becomes its own scroller in both directions, no
 *     taller than the screen, so the header stays at its top and the first
 *     column can stay at its left (`freezeFirstColumn`).
 *
 * The second is a spreadsheet's behaviour, and is meant for the tables that
 * genuinely need their columns on a phone. Nothing is hidden to make a table
 * fit; a column that matters on a desktop matters on a phone.
 *
 * A `Card` around a sticky table must clip with `overflow-clip`, not
 * `overflow-hidden`: `hidden` makes the card a scroll container, and the header
 * would stick to the card instead of the page.
 *
 * ## Rows that go somewhere
 *
 * A row that represents one thing — a player — holds one `RowLink`, in the
 * cell that names it. That link is the row's keyboard and screen-reader path:
 * one tab stop, announced as a link, opening in a new tab like any other. A
 * pointer gets more: a click anywhere on the row follows the same link, except
 * on a control of its own (a button, another link, a tooltip trigger) or while
 * selecting text. The row is a bigger target for the link, not a second one.
 */

export type TableDensity = 'compact' | 'default' | 'comfortable'

const ROW_HEIGHT: Record<TableDensity, string> = {
  compact: 'var(--spacing-row-compact)',
  default: 'var(--spacing-row)',
  comfortable: 'var(--spacing-row-comfortable)',
}

interface TableContextValue {
  /** The table is its own scroller right now (see "Sticky header"). */
  scrolls: boolean
  freezeFirstColumn: boolean
  stickyHeader: boolean
}

const TableContext = createContext<TableContextValue>({
  scrolls: false,
  freezeFirstColumn: false,
  stickyHeader: true,
})

/** Whether the table has less room than `minWidth`, re-measured as it resizes. */
function useNeedsScroll(minWidth: string | undefined) {
  const frameRef = useRef<HTMLDivElement>(null)
  const [scrolls, setScrolls] = useState(false)

  useLayoutEffect(() => {
    const frame = frameRef.current
    const table = frame?.querySelector('table')
    if (!frame || !table || !minWidth) {
      setScrolls(false)
      return
    }
    // The table's own computed `min-width` is the declared length in pixels,
    // whatever unit it was written in.
    const measure = () => setScrolls(frame.clientWidth < parseFloat(getComputedStyle(table).minWidth))
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(frame)
    return () => observer.disconnect()
  }, [minWidth])

  return [frameRef, scrolls] as const
}

export interface TableProps extends Omit<HTMLAttributes<HTMLTableElement>, 'children'> {
  /**
   * What the table holds, for a screen reader's table list. Required: a page
   * of several tables is unnavigable when each announces as "table".
   */
  caption: string
  /** Appended to the caption: the current sort, a unit. */
  captionNote?: string
  density?: TableDensity
  /**
   * The narrowest the table can be before its columns stop being readable, as
   * a CSS length. Below it the table scrolls sideways instead of squeezing.
   * Leave it out for a table that fits everywhere.
   */
  minWidth?: string
  /** Keep the first column in view while the table scrolls sideways. */
  freezeFirstColumn?: boolean
  stickyHeader?: boolean
  /**
   * Where the header stops while the page scrolls, as a CSS length from the
   * top of the viewport. Defaults to just under the application bar; a page
   * with a sticky toolbar of its own adds that toolbar's height.
   */
  stickyTop?: string
  /**
   * `fixed` sizes columns from the header's widths alone, never from the
   * rows. The table then cannot be wider than its frame whatever a row holds,
   * and the one column without a width takes what is left. For a table whose
   * columns are known and whose first column should absorb the slack.
   */
  layout?: 'auto' | 'fixed'
  /** Rows are being replaced. Announced; the caller decides what to draw. */
  busy?: boolean
  /** Classes for the frame around the table, not the table itself. */
  className?: string
  children: ReactNode
  ref?: Ref<HTMLTableElement>
}

export function Table({
  caption,
  captionNote,
  density = 'default',
  minWidth,
  freezeFirstColumn = false,
  stickyHeader = true,
  stickyTop = 'calc(var(--spacing-shell-bar) + 1px)',
  layout = 'auto',
  busy = false,
  className,
  children,
  ref,
  style,
  ...props
}: TableProps) {
  const [frameRef, scrolls] = useNeedsScroll(minWidth)
  const context = useMemo(
    () => ({ scrolls, freezeFirstColumn, stickyHeader }),
    [scrolls, freezeFirstColumn, stickyHeader],
  )

  return (
    <TableContext value={context}>
      <div
        ref={frameRef}
        data-table-scrolls={scrolls || undefined}
        style={{ '--dt-sticky-top': stickyTop } as CSSProperties}
        className={cn(
          // `relative`, so anything visually hidden inside a cell (it is
          // absolutely positioned) is placed against this frame. Against an
          // ancestor outside it, such text escapes the frame's clipping and
          // makes the page as tall as the table the frame was meant to bound.
          'relative min-w-0',
          scrolls && 'overflow-auto overscroll-x-contain -outline-offset-2',
          // Bounded, so the header has a top to stick to: under the
          // application bar and clear of the phone's navigation bar.
          scrolls && stickyHeader && 'max-h-[calc(100dvh-8.5rem)]',
          className,
        )}
        // A region that scrolls must be reachable without a pointer, and a
        // table of plain numbers holds nothing else a keyboard can land on.
        {...(scrolls ? { tabIndex: 0, role: 'region', 'aria-label': `${caption}, scrollable table` } : {})}
      >
        <table
          ref={ref}
          aria-busy={busy || undefined}
          style={{ minWidth, '--dt-row': ROW_HEIGHT[density], ...style } as CSSProperties}
          className={cn(
            // `separate`, not `collapse`: a collapsed border belongs to the
            // table rather than the cell, and stays behind when a sticky cell
            // moves.
            'text-body text-ink w-full border-separate border-spacing-0',
            layout === 'fixed' && 'table-fixed',
            '[&>tbody:last-of-type>tr:last-child>*]:border-b-0',
          )}
          {...props}
        >
          <caption className="sr-only">
            {caption}
            {captionNote ? `, ${captionNote}` : ''}
          </caption>
          {children}
        </table>
      </div>
    </TableContext>
  )
}

export function TableHead({ children, ...props }: HTMLAttributes<HTMLTableSectionElement>) {
  return (
    <thead {...props}>
      <tr>{children}</tr>
    </thead>
  )
}

/** The frozen first column, shared by header and body cells. */
function frozenClasses({ scrolls, freezeFirstColumn }: TableContextValue, layer: string) {
  if (!freezeFirstColumn) return undefined
  return cn(
    'first:sticky first:left-0',
    layer,
    // The edge that says "columns pass under here", only while they can.
    scrolls && 'first:border-line-strong first:border-r',
  )
}

export interface ColumnHeaderProps extends Omit<ThHTMLAttributes<HTMLTableCellElement>, 'onClick'> {
  /** Right-aligned, over a column of numbers. */
  numeric?: boolean
  /**
   * `'asc'` or `'desc'` when the table is sorted by this column, `'none'`
   * when it could be. Leave it out for a column that does not sort.
   */
  sort?: SortDirection | 'none'
  onSort?: () => void
  /**
   * One plain sentence on what the column means. The header's own label is the
   * trigger — hover it, or focus it — so an explanation costs the column no
   * width and no icon.
   */
  tip?: ReactNode
}

export function ColumnHeader({
  numeric = false,
  sort,
  onSort,
  tip,
  className,
  children,
  ...props
}: ColumnHeaderProps) {
  const context = use(TableContext)
  const tipId = useId()
  const sorted = sort === 'asc' || sort === 'desc'
  const SortIcon = sort === 'asc' ? ArrowUp : sort === 'desc' ? ArrowDown : ArrowUpDown

  // A dotted underline is the whole affordance for "this header explains
  // itself": the same mark the board uses under "Not graded".
  const label = tip ? (
    <span className="decoration-line-strong underline decoration-dotted underline-offset-4">{children}</span>
  ) : (
    children
  )

  const control =
    sort === undefined ? (
      label
    ) : (
      <button
        type="button"
        onClick={onSort}
        aria-describedby={tip ? tipId : undefined}
        className={cn(
          // As tall as the header, so the target is the whole cell height.
          'group/sort h-row-compact pointer-coarse:h-row relative -my-px inline-flex items-center gap-1 rounded-sm font-semibold transition-colors',
          numeric && 'flex-row-reverse',
          sorted ? 'text-ink' : 'hover:text-ink',
        )}
      >
        {label}
        {/* The sorted column's arrow takes its place in the header. An
            unsorted column's is a hint, shown on hover and focus and hung
            outside the label, so that six sortable columns do not each
            reserve 18px for a glyph that is usually invisible. On a board
            that width is the difference between a name fitting and not. */}
        <SortIcon
          aria-hidden
          className={cn(
            'size-3.5 shrink-0 transition-opacity',
            !sorted && 'absolute top-1/2 -translate-y-1/2 opacity-0 group-hover/sort:opacity-70 group-focus-visible/sort:opacity-70',
            !sorted && (numeric ? 'right-full mr-0.5' : 'left-full ml-0.5'),
          )}
        />
      </button>
    )

  return (
    <th
      scope="col"
      // Only on the sorted column, as the ARIA practices describe it. The
      // button inside is what says a column *can* be sorted.
      aria-sort={sort === 'asc' ? 'ascending' : sort === 'desc' ? 'descending' : undefined}
      className={cn(
        // 32px, and 40px where the pointer is a finger: a sort button is as
        // tall as its header, and 32px is a small thing to hit with a thumb.
        'bg-surface border-line-strong text-caption text-ink-muted h-row-compact pointer-coarse:h-row border-b px-2.5 align-middle font-semibold whitespace-nowrap',
        numeric ? 'text-right' : 'text-left',
        context.stickyHeader && 'sticky z-20',
        // Under the application bar when the page scrolls; at the top of the
        // table when the table does.
        context.stickyHeader && (context.scrolls ? 'top-0' : 'top-(--dt-sticky-top)'),
        frozenClasses(context, 'first:z-30'),
        className,
      )}
      {...props}
    >
      {tip ? (
        // One stop, not two: around a sort button the tooltip takes no tab
        // stop of its own, and focus on the button opens it.
        <Tooltip content={tip} focusable={sort === undefined} align={numeric ? 'end' : 'center'}>
          {control}
        </Tooltip>
      ) : (
        control
      )}
      {/* What the button is described by. `hidden`, so it is read as the
          button's description and not as part of the column's name, which a
          screen reader repeats on every cell. */}
      {tip && sort !== undefined && (
        <span id={tipId} hidden>
          {tip}
        </span>
      )}
    </th>
  )
}

/**
 * Follows the row's link when the row itself is clicked.
 *
 * A convenience for a pointer, layered on a real link: see "Rows that go
 * somewhere" above. It re-dispatches the click on the link rather than
 * navigating itself, so the router's own handling — and a modified click
 * opening a new tab — stay the link's business.
 */
function followRowLink(event: MouseEvent<HTMLTableSectionElement>) {
  if (event.defaultPrevented || event.button !== 0) return
  const target = event.target as HTMLElement
  const row = target.closest('tr')
  const link = row?.querySelector<HTMLAnchorElement>('a[data-row-link]')
  if (!row || !link) return
  // The row's own controls keep their own behaviour. `[tabindex]` covers
  // tooltip triggers, which a tap opens. Only controls *inside* the row count:
  // the page's `<main>` carries a tabindex too, and it contains every row.
  const control = target.closest('a, button, input, select, textarea, label, summary, [role="button"], [tabindex]')
  if (control && row.contains(control)) return
  // Dragging across a row to copy a name is not a click on it.
  if (window.getSelection()?.toString()) return

  link.dispatchEvent(
    new window.MouseEvent('click', {
      bubbles: true,
      cancelable: true,
      view: window,
      ctrlKey: event.ctrlKey,
      metaKey: event.metaKey,
      shiftKey: event.shiftKey,
      altKey: event.altKey,
    }),
  )
}

export function TableBody({ onClick, ...props }: HTMLAttributes<HTMLTableSectionElement>) {
  return (
    <tbody
      onClick={(event) => {
        onClick?.(event)
        followRowLink(event)
      }}
      {...props}
    />
  )
}

export interface TableRowProps extends HTMLAttributes<HTMLTableRowElement> {
  /**
   * This row is the one in question — the player whose page is open, the pick
   * under discussion. Marked visually and with `aria-current`. A selection the
   * reader *makes* (a checkbox to compare) carries its state in its own
   * control instead.
   */
  selected?: boolean
  /**
   * This row belongs to a set the reader marked — a player on their own
   * roster, in a table of everyone. A tint only, so the row must also say so
   * in words: a tint is not a meaning to someone who cannot see it. Several
   * rows may carry it, which is why it is not `selected`.
   */
  highlighted?: boolean
  ref?: Ref<HTMLTableRowElement>
}

export function TableRow({ selected = false, highlighted = false, className, ...props }: TableRowProps) {
  return (
    <tr
      data-selected={selected || undefined}
      data-highlighted={highlighted || undefined}
      aria-current={selected || undefined}
      className={cn(
        // Opaque, and its colour published as `--row-rest`: a frozen cell
        // inherits it, and the scroll rule in `index.css` restores it.
        'transition-colors has-[a[data-row-link]]:cursor-pointer',
        selected
          ? 'bg-accent-soft [--row-rest:var(--color-accent-soft)]'
          : highlighted
            ? // Mixed rather than translucent, so it stays opaque under a
              // frozen cell.
              'hover:bg-surface-hover focus-within:bg-surface-hover bg-(--row-rest) [--row-rest:color-mix(in_oklch,var(--color-accent-soft)_40%,var(--color-surface))]'
            : 'bg-surface hover:bg-surface-hover focus-within:bg-surface-hover [--row-rest:var(--color-surface)]',
        className,
      )}
      {...props}
    />
  )
}

interface CellStyle {
  /** Right-aligned tabular figures, so digits line up down the column. */
  numeric?: boolean
}

function cellClasses(context: TableContextValue, numeric: boolean, className: string | undefined) {
  return cn(
    'border-line h-(--dt-row) border-b px-2.5 py-1 align-middle',
    numeric && 'tnum text-right',
    // `inherit`, so a frozen cell is opaque in the row's own colour — hover,
    // selected or at rest — and scrolled columns do not show through it.
    frozenClasses(context, 'first:z-10 first:bg-inherit'),
    className,
  )
}

export function TableCell({
  numeric = false,
  className,
  ...props
}: TdHTMLAttributes<HTMLTableCellElement> & CellStyle) {
  return <td className={cellClasses(use(TableContext), numeric, className)} {...props} />
}

/**
 * The cell that names its row: a `<th scope="row">`, so a screen reader moving
 * down a numeric column hears whose number it is.
 */
export function RowHeaderCell({ className, ...props }: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      scope="row"
      className={cellClasses(use(TableContext), false, cn('text-left font-normal', className))}
      {...props}
    />
  )
}

/**
 * A heading inside the body: "Tier 3". Give each group its own `TableBody` and
 * open it with one of these; the `rowgroup` scope is what makes it an announced
 * heading for the rows under it rather than a decorative stripe.
 */
export function GroupHeaderRow({ colSpan, children }: { colSpan: number; children: ReactNode }) {
  return (
    <tr className="bg-surface-sunken">
      <th
        scope="rowgroup"
        colSpan={colSpan}
        className="border-line text-caption text-ink-secondary border-b px-2.5 py-1 text-left font-semibold"
      >
        {/* The cell spans every column, so in a table that scrolls sideways
            its words would scroll away with the first of them. Held at the
            left edge, the heading stays readable wherever the reader is. */}
        <span className="sticky left-2.5 inline-block">{children}</span>
      </th>
    </tr>
  )
}

/**
 * The link a row is about. One per row, in the cell that names it.
 * `TableBody` extends its target to the whole row for a pointer.
 */
export function RowLink({ className, ...props }: LinkProps) {
  return (
    <Link
      data-row-link=""
      className={cn('text-ink hover:text-accent-text rounded-sm font-medium transition-colors', className)}
      {...props}
    />
  )
}

/* ------------------------------------------------------------------------- */

export interface DataTableColumn<T> {
  /** Stable id: the React key, and the sort key in a URL. */
  id: string
  /** Sentence case. Plain text, because it is also read out. */
  header: string
  cell: (row: T, index: number) => ReactNode
  numeric?: boolean
  /** Renders the cell as the row's header. Use it on the column that names the row. */
  rowHeader?: boolean
  /** What the column sorts on. Its presence is what makes the column sortable. */
  sortValue?: (row: T) => SortValue
  /** Which way a first press sorts. Defaults to largest-first for numbers, A to Z otherwise. */
  sortFirst?: SortDirection
  tip?: ReactNode
  /** A CSS width for the column, when its content should not decide. */
  width?: string
  /** Classes for the column's header and body cells alike. */
  className?: string
}

export interface DataTableProps<T> extends Omit<TableProps, 'children' | 'busy' | 'captionNote'> {
  columns: DataTableColumn<T>[]
  rows: readonly T[]
  rowKey: (row: T) => string
  /** The current sort. Owned by the caller, so it can live in the URL. */
  sort?: SortState | null
  onSortChange?: (next: SortState) => void
  isSelected?: (row: T) => boolean
  /**
   * No rows yet. Draws placeholder rows of the real height under the real
   * header, so nothing moves when the data arrives.
   */
  loading?: boolean
  /** How many placeholder rows. */
  loadingRows?: number
  /** Shown in place of rows when there are none. Say why, and the way out. */
  empty?: ReactNode
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  sort,
  onSortChange,
  isSelected,
  loading = false,
  loadingRows = 8,
  empty,
  caption,
  ...table
}: DataTableProps<T>) {
  const sortColumn = sort ? columns.find((column) => column.id === sort.key && column.sortValue) : undefined
  const sortBy = sortColumn?.sortValue
  const direction = sort?.direction
  const sorted = useMemo(
    () => (sortBy && direction ? sortRows(rows, sortBy, direction) : rows),
    [rows, sortBy, direction],
  )

  return (
    <Table
      caption={caption}
      // Spoken as well as drawn: an arrow in a header says nothing to someone
      // who cannot see it, and `aria-sort` is not read by every screen reader.
      captionNote={
        sortColumn && sort
          ? `sorted by ${sortColumn.header.toLowerCase()}, ${sort.direction === 'asc' ? 'ascending' : 'descending'}`
          : undefined
      }
      busy={loading}
      {...table}
    >
      <TableHead>
        {columns.map((column) => {
          const sortable = column.sortValue !== undefined && onSortChange !== undefined
          const first = column.sortFirst ?? (column.numeric ? 'desc' : 'asc')
          return (
            <ColumnHeader
              key={column.id}
              numeric={column.numeric}
              tip={column.tip}
              sort={sortable ? (sort?.key === column.id ? sort.direction : 'none') : undefined}
              onSort={sortable ? () => onSortChange(nextSort(sort, column.id, first)) : undefined}
              style={column.width ? { width: column.width } : undefined}
              className={column.className}
            >
              {column.header}
            </ColumnHeader>
          )
        })}
      </TableHead>

      <TableBody>
        {loading ? (
          Array.from({ length: loadingRows }, (_, rowIndex) => (
            <TableRow key={rowIndex}>
              {columns.map((column, columnIndex) => (
                <TableCell key={column.id} numeric={column.numeric} className={column.className}>
                  <Skeleton
                    className={cn(
                      'h-3.5',
                      column.numeric ? 'ml-auto w-10' : columnIndex === 0 ? 'w-8' : 'w-32 max-w-full',
                    )}
                  />
                  {rowIndex === 0 && columnIndex === 0 && <span className="sr-only">Loading</span>}
                </TableCell>
              ))}
            </TableRow>
          ))
        ) : sorted.length === 0 ? (
          <tr>
            <td colSpan={columns.length}>
              {empty ?? <p className="text-ink-muted text-detail px-2.5 py-8 text-center">Nothing to show.</p>}
            </td>
          </tr>
        ) : (
          sorted.map((row, index) => (
            <TableRow key={rowKey(row)} selected={isSelected?.(row)}>
              {columns.map((column) =>
                column.rowHeader ? (
                  <RowHeaderCell key={column.id} className={column.className}>
                    {column.cell(row, index)}
                  </RowHeaderCell>
                ) : (
                  <TableCell key={column.id} numeric={column.numeric} className={column.className}>
                    {column.cell(row, index)}
                  </TableCell>
                ),
              )}
            </TableRow>
          ))
        )}
      </TableBody>
    </Table>
  )
}
