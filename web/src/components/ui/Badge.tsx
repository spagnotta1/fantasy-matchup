import type { HTMLAttributes, ReactNode } from 'react'

import { cn } from '@/utils/cn'

export type BadgeTone = 'neutral' | 'accent' | 'positive' | 'negative' | 'caution' | 'info'

const TONES: Record<BadgeTone, string> = {
  neutral: 'bg-surface-sunken text-ink-secondary border-line',
  accent: 'bg-accent-soft text-accent-text border-transparent',
  positive: 'bg-positive-soft text-positive-text border-transparent',
  negative: 'bg-negative-soft text-negative-text border-transparent',
  caution: 'bg-caution-soft text-caution-text border-transparent',
  info: 'bg-info-soft text-info-text border-transparent',
}

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone
  size?: 'sm' | 'md'
  /**
   * A glyph rendered before the label.
   *
   * Not decoration. Tone is carried by colour, and colour alone is not a
   * signal — an icon or a sign in the label is what makes a badge readable to
   * someone who cannot distinguish the hues.
   */
  icon?: ReactNode
}

export function Badge({ tone = 'neutral', size = 'sm', icon, className, children, ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full border font-medium whitespace-nowrap',
        size === 'sm' ? 'px-2 py-0.5 text-[0.6875rem]' : 'px-2.5 py-1 text-xs',
        TONES[tone],
        className,
      )}
      {...props}
    >
      {icon && <span aria-hidden className="flex shrink-0 items-center">{icon}</span>}
      {children}
    </span>
  )
}
