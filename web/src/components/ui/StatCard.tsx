import type { ReactNode } from 'react'

import { cn } from '@/utils/cn'

interface StatCardProps {
  label: string
  value: ReactNode
  /** A unit or qualifier set next to the value, in smaller type. */
  unit?: string
  /** One line under the value: the range, the sample, the caveat. */
  detail?: ReactNode
  /** Rendered at the top right — usually a provenance chip or a grade. */
  badge?: ReactNode
  emphasis?: 'default' | 'primary'
  className?: string
}

/**
 * A single headline number with its context attached.
 *
 * The `detail` slot is not optional in spirit. A bare "25.4" is a claim; "25.4,
 * range 18.2–38.7" is information. Every stat in this product should carry the
 * thing that makes it interpretable.
 */
export function StatCard({
  label,
  value,
  unit,
  detail,
  badge,
  emphasis = 'default',
  className,
}: StatCardProps) {
  return (
    <div
      className={cn(
        'rounded-[var(--radius-card)] border p-4',
        emphasis === 'primary'
          ? 'bg-accent-soft border-transparent'
          : 'bg-surface border-line shadow-card',
        className,
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <p
          className={cn(
            'text-xs font-medium tracking-wide uppercase',
            emphasis === 'primary' ? 'text-accent-text' : 'text-ink-muted',
          )}
        >
          {label}
        </p>
        {badge}
      </div>
      <p className="mt-2 flex items-baseline gap-1">
        <span
          className={cn(
            'tnum text-2xl leading-none font-semibold tracking-tight',
            emphasis === 'primary' ? 'text-accent-text' : 'text-ink',
          )}
        >
          {value}
        </span>
        {unit && <span className="text-ink-muted text-xs font-medium">{unit}</span>}
      </p>
      {detail && <p className="text-ink-muted mt-2 text-xs leading-relaxed">{detail}</p>}
    </div>
  )
}
