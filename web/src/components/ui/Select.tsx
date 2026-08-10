import { forwardRef, useId, type SelectHTMLAttributes } from 'react'
import { ChevronDown } from 'lucide-react'

import { cn } from '@/utils/cn'

export interface SelectOption {
  value: string
  label: string
  disabled?: boolean
}

export interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'size'> {
  /**
   * The accessible name. Rendered visibly unless `hideLabel` is set — a
   * selector with only a placeholder is unusable with a screen reader and
   * ambiguous with one.
   */
  label: string
  hideLabel?: boolean
  options: SelectOption[]
  hint?: string
  size?: 'sm' | 'md'
}

/**
 * A native `<select>`, on purpose.
 *
 * A custom listbox would need keyboard handling, focus trapping and typeahead
 * rebuilt from scratch, and on mobile it would replace a platform picker people
 * already know with something worse. The visual treatment is ours; the
 * behaviour is the browser's.
 */
export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { label, hideLabel, options, hint, size = 'md', className, id, ...props },
  ref,
) {
  const generatedId = useId()
  const selectId = id ?? generatedId
  const hintId = hint ? `${selectId}-hint` : undefined

  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <label
        htmlFor={selectId}
        className={cn(
          'text-ink-secondary text-xs font-medium',
          hideLabel && 'sr-only',
        )}
      >
        {label}
      </label>
      <div className="relative">
        <select
          ref={ref}
          id={selectId}
          aria-describedby={hintId}
          className={cn(
            'bg-surface border-line-input text-ink w-full appearance-none rounded-[var(--radius-control)] border',
            'pr-9 font-medium transition-colors',
            'hover:border-line-strong disabled:cursor-not-allowed disabled:opacity-55',
            size === 'sm' ? 'h-8 pl-2.5 text-xs' : 'h-10 pl-3 text-sm',
          )}
          {...props}
        >
          {options.map((option) => (
            <option key={option.value} value={option.value} disabled={option.disabled}>
              {option.label}
            </option>
          ))}
        </select>
        <ChevronDown
          aria-hidden
          className="text-ink-muted pointer-events-none absolute top-1/2 right-2.5 size-4 -translate-y-1/2"
        />
      </div>
      {hint && (
        <p id={hintId} className="text-ink-muted text-xs">
          {hint}
        </p>
      )}
    </div>
  )
})
