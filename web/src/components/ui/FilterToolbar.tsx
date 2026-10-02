import { createContext, use, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { Search, X } from 'lucide-react'

import { IconButton } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { SegmentedControl, type SegmentOption } from '@/components/ui/SegmentedControl'
import { Select } from '@/components/ui/Select'
import { useElementSize } from '@/hooks/useElementSize'
import { cn } from '@/utils/cn'

/**
 * The filter toolbar.
 *
 * One way to lay out the controls that decide which rows a table holds, so a
 * reader who has filtered one screen knows how to filter the next. It is
 * layout and behaviour only. It owns no state: every page already keeps its
 * filters in the URL through `useUrlState`, and the controls here are handed a
 * value and a setter like any other.
 *
 *   - `FilterToolbar`  the row: a named group that wraps, with the result
 *                      count at its trailing edge
 *   - `FilterSearch`   the search box with its clear button
 *   - `FilterChoice`   a short set of exclusive choices: position, direction
 *   - `FilterChip`     a filter that was set somewhere else on the page (a
 *                      game picked from the ticker), with the way to drop it
 *
 * A `Select` goes in as it is.
 *
 * ## One height
 *
 * Every control is 32px, and 44px where the pointer is a finger. The segmented
 * control and the buttons grow on their own; a search box and a select are told
 * to here, so a toolbar on a phone is one height and not two.
 *
 * ## Narrow screens
 *
 * The row wraps between controls and never inside one. A segmented control
 * whose options do not fit the toolbar's own width — "Out & doubtful,
 * Questionable, Practice only" on a phone — is drawn as a select instead,
 * which opens the platform's picker. That is decided by measuring the control
 * against the room it has, not by the width of the window: the sidebar takes
 * 240px of a laptop, and a toolbar inside a card has less room again.
 */

/** The toolbar's measured width in pixels. Zero outside a toolbar, or before it is measured. */
const ToolbarWidth = createContext(0)

export function FilterToolbar({
  label,
  summary,
  className,
  children,
}: {
  /** What the controls filter, for a screen reader: "Filter players". */
  label: string
  /**
   * How many rows the filters leave: "12 of 214 players". Announced when it
   * changes, so a filter that empties the table says so.
   */
  summary?: ReactNode
  className?: string
  children: ReactNode
}) {
  const [ref, size] = useElementSize<HTMLDivElement>()

  return (
    <ToolbarWidth value={size.width}>
      <div
        ref={ref}
        role="group"
        aria-label={label}
        className={cn(
          'mb-4 flex flex-wrap items-center gap-x-3 gap-y-2',
          'pointer-coarse:[&_input[type=search]]:h-touch pointer-coarse:[&_select]:h-touch',
          className,
        )}
      >
        {children}
        {summary !== undefined && (
          <p className="text-ink-muted text-detail ml-auto" aria-live="polite">
            {summary}
          </p>
        )}
      </div>
    </ToolbarWidth>
  )
}

export function FilterSearch({
  label,
  value,
  onChange,
  onClear,
  placeholder,
  className,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  /** Defaults to `onChange('')`. A page that debounces its URL passes its own. */
  onClear?: () => void
  placeholder?: string
  className?: string
}) {
  return (
    <Input
      label={label}
      hideLabel
      size="sm"
      type="search"
      placeholder={placeholder}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      icon={<Search />}
      // Takes the room there is, up to the length of a name and a team.
      className={cn('max-w-72 min-w-0 flex-1 basis-56', className)}
      trailing={
        value ? (
          <IconButton size="xs" label="Clear search" onClick={onClear ?? (() => onChange(''))}>
            <X />
          </IconButton>
        ) : undefined
      }
    />
  )
}

export function FilterChoice<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  /** The accessible name of the group, and the prefix of each option when drawn as a select. */
  label: string
  value: T
  options: SegmentOption<T>[]
  onChange: (value: T) => void
}) {
  const room = use(ToolbarWidth)
  const ref = useRef<HTMLDivElement>(null)
  // The width the segmented control wants, remembered for the options it was
  // measured with: once it is drawn as a select there is nothing to measure.
  const signature = options.map((option) => option.label).join('|')
  const [measured, setMeasured] = useState<{ signature: string; width: number } | null>(null)
  const wanted = measured?.signature === signature ? measured.width : null
  const collapsed = wanted !== null && room > 0 && wanted > room

  useLayoutEffect(() => {
    const element = ref.current
    if (!element) return
    const measure = () => {
      const width = Math.ceil(element.getBoundingClientRect().width)
      setMeasured((current) =>
        current?.signature === signature && current.width === width ? current : { signature, width },
      )
    }
    measure()
    // The web font arriving changes every label's width.
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [signature, collapsed])

  if (collapsed) {
    return (
      <Select
        label={label}
        hideLabel
        size="sm"
        value={value}
        onChange={(event) => onChange(event.target.value as T)}
        className="w-full"
        // The closed select shows one option and nothing else, and two filters
        // on one page can both read "All".
        options={options.map((option) => ({ value: option.value, label: `${label}: ${option.label}` }))}
      />
    )
  }

  return (
    // `shrink-0`, so what is measured is the width it wants and not the width
    // a flex row squeezed it to.
    <div ref={ref} className="inline-flex shrink-0">
      <SegmentedControl label={label} value={value} options={options} onChange={onChange} />
    </div>
  )
}

/**
 * A filter the toolbar did not set, shown where the other filters are.
 *
 * Squared like a control, not a pill: a pill is a status or a provenance
 * label, and this is something to press.
 */
export function FilterChip({
  children,
  removeLabel,
  onRemove,
}: {
  children: ReactNode
  /** What pressing the ✕ does, in words: "Show every game". */
  removeLabel: string
  onRemove: () => void
}) {
  return (
    <span className="bg-accent-soft text-accent-text rounded-control text-detail h-control-sm pointer-coarse:h-touch inline-flex items-center gap-1 pr-0.5 pl-2.5 font-medium whitespace-nowrap">
      {children}
      <IconButton size="xs" className="text-current" label={removeLabel} onClick={onRemove}>
        <X />
      </IconButton>
    </span>
  )
}
