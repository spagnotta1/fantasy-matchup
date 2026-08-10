import { forwardRef, type ButtonHTMLAttributes } from 'react'
import { Loader2 } from 'lucide-react'

import { cn } from '@/utils/cn'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'
export type ButtonSize = 'sm' | 'md' | 'lg'

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    'bg-accent text-on-accent hover:bg-accent-hover shadow-card disabled:hover:bg-accent',
  secondary:
    'bg-surface text-ink border border-line-input hover:bg-surface-hover hover:border-line-strong disabled:hover:bg-surface',
  ghost: 'text-ink-secondary hover:bg-surface-hover hover:text-ink disabled:hover:bg-transparent',
  danger:
    'bg-negative text-white hover:brightness-110 shadow-card disabled:hover:brightness-100',
}

const SIZES: Record<ButtonSize, string> = {
  /*
   * `sm` is for dense toolbars, and at 32px tall it is below the 44px touch
   * floor — which only matters on a device where the pointer is a finger. The
   * `pointer-coarse` variant grows it to 44 there and leaves the mouse layout
   * exactly as designed.
   *
   * Grown rather than given an invisible 44px overlay, which is the other
   * usual fix. These buttons sit in a row a few pixels apart, so overlays
   * would overlap each other, and the control they would overlap is "Clear
   * lineup" — a mis-tap that silently throws away fourteen slots. A control
   * that is physically as big as its hit area cannot lie about where it ends.
   */
  sm: 'h-8 pointer-coarse:h-11 px-3 pointer-coarse:px-3.5 text-xs gap-1.5 rounded-[var(--radius-control)]',
  md: 'h-10 pointer-coarse:h-11 px-4 text-sm gap-2 rounded-[var(--radius-control)]',
  lg: 'h-12 px-6 text-base gap-2.5 rounded-[var(--radius-control)]',
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  /** Shows a spinner and disables the button. Keeps the label for stable width. */
  loading?: boolean
  fullWidth?: boolean
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', loading = false, fullWidth, className, children, disabled, type = 'button', ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      // `aria-busy` rather than swapping the label: a screen reader user should
      // hear that the same action is in progress, not that it disappeared.
      aria-busy={loading || undefined}
      className={cn(
        'inline-flex items-center justify-center font-medium whitespace-nowrap',
        'transition-[background-color,border-color,color,box-shadow,transform] duration-150',
        'active:scale-[0.985] disabled:cursor-not-allowed disabled:opacity-55 disabled:active:scale-100',
        VARIANTS[variant],
        SIZES[size],
        fullWidth && 'w-full',
        className,
      )}
      {...props}
    >
      {loading && <Loader2 aria-hidden className="size-4 animate-spin" />}
      {children}
    </button>
  )
})
