import { useId } from 'react'

import { cn } from '@/utils/cn'

export interface SegmentOption<T extends string> {
  value: T
  label: string
  /** Optional glyph. The label always stays — an icon-only toggle is a guess. */
  icon?: React.ReactNode
}

interface SegmentedControlProps<T extends string> {
  label: string
  value: T
  options: SegmentOption<T>[]
  onChange: (value: T) => void
  size?: 'sm' | 'md'
  className?: string
}

/**
 * A small set of mutually exclusive choices — table vs card view, a position
 * filter.
 *
 * Built as a radio group rather than buttons: the semantics are exactly a radio
 * group's, which buys arrow-key navigation and the correct screen-reader
 * announcement ("2 of 4 selected") for free.
 */
export function SegmentedControl<T extends string>({
  label,
  value,
  options,
  onChange,
  size = 'md',
  className,
}: SegmentedControlProps<T>) {
  const name = useId()

  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={cn(
        'bg-surface-sunken border-line inline-flex items-center gap-0.5 rounded-[var(--radius-control)] border p-0.5',
        className,
      )}
    >
      {options.map((option) => {
        const selected = option.value === value
        return (
          <label
            key={option.value}
            className={cn(
              'relative inline-flex cursor-pointer items-center justify-center gap-1.5 rounded-[calc(var(--radius-control)-2px)] font-medium transition-colors',
              size === 'sm' ? 'h-7 px-2.5 text-xs' : 'h-8 px-3 text-sm',
              selected
                ? 'bg-surface text-ink shadow-card'
                : 'text-ink-muted hover:text-ink-secondary',
              'focus-within:outline-focus focus-within:outline-2 focus-within:outline-offset-2',
            )}
          >
            <input
              type="radio"
              name={name}
              value={option.value}
              checked={selected}
              onChange={() => onChange(option.value)}
              className="sr-only"
            />
            {option.icon && <span aria-hidden className="flex items-center">{option.icon}</span>}
            {option.label}
          </label>
        )
      })}
    </div>
  )
}
