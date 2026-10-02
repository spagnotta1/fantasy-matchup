import type { InputHTMLAttributes } from 'react'
import { Check } from 'lucide-react'

import { cn } from '@/utils/cn'

export interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'size'> {
  /**
   * What ticking it does, for a screen reader: "Select Derrick Henry to
   * compare". Not drawn. A box in a table row has no room for words, and the
   * row it sits in says whose it is to someone who can see it.
   */
  label: string
  /** Classes for the hit area around the box, not the box. */
  className?: string
}

/**
 * A tick box with no visible label, for a row of a table or a list.
 *
 * A real `<input type="checkbox">`, so it is a tab stop, Space toggles it and
 * it is announced with its state. The box is 16px; the hit area is the
 * `<label>` around it, which the caller sizes — a table cell fills it, so a
 * press that just misses the box still ticks it and does not follow the row's
 * link (`TableBody` leaves a `label` alone).
 */
export function Checkbox({ label, className, disabled, ...props }: CheckboxProps) {
  return (
    <label
      className={cn(
        'inline-flex items-center justify-center',
        disabled ? 'cursor-not-allowed' : 'cursor-pointer',
        className,
      )}
    >
      <span className="relative inline-flex size-4">
        <input
          type="checkbox"
          aria-label={label}
          disabled={disabled}
          className="peer border-line-input bg-surface checked:border-accent checked:bg-accent rounded-chip size-4 cursor-[inherit] appearance-none border transition-colors disabled:opacity-50"
          {...props}
        />
        <Check
          aria-hidden
          strokeWidth={3.5}
          className="text-on-accent pointer-events-none absolute inset-0.5 hidden size-3 peer-checked:block"
        />
      </span>
    </label>
  )
}
