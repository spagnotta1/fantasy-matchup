import { cn } from '@/utils/cn'

/*
 * How a button looks, apart from what it is. `Button.tsx` holds the four
 * components; this holds the one class builder they share, in its own module so
 * the component file exports only components (which is what keeps fast refresh
 * working on it).
 */

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'link'
/** `md` 40px for a page's primary action, `sm` 32px for toolbars, `xs` 28px inside table rows. */
export type ButtonSize = 'md' | 'sm' | 'xs'

const VARIANTS: Record<ButtonVariant, string> = {
  primary: 'bg-accent text-on-accent not-disabled:hover:bg-accent-hover',
  secondary:
    'bg-surface text-ink border border-line-input not-disabled:hover:bg-surface-hover not-disabled:hover:border-line-strong',
  // The quiet one: a toolbar action that should not compete with the data.
  ghost: 'text-ink-secondary not-disabled:hover:bg-surface-hover not-disabled:hover:text-ink',
  // Both colours are tokens. This used to set literal white lettering, which
  // the dark theme's light red fill cannot carry.
  danger: 'bg-danger text-on-danger not-disabled:hover:bg-danger-hover',
  // An action set in running text or under a list row: no box, so no height.
  link: 'text-accent-text min-h-6 underline-offset-2 not-disabled:hover:underline',
}

/*
 * Touch.
 *
 * `md` and `sm` grow to 44px where the pointer is a finger, and are grown
 * rather than given an invisible overlay. They sit in rows a few pixels apart,
 * so overlays would overlap each other, and the control they would overlap is
 * "Clear lineup" — a mis-tap that silently throws away fourteen slots. A
 * control that is physically as big as its hit area cannot lie about where it
 * ends.
 *
 * `xs` is the exception, and for the opposite reason. It lives inside table
 * rows, where growing it to 44px would make every row 44px and undo the
 * density the row height was chosen for. So it keeps its 28px and takes a
 * larger hit area instead: 40px tall — a default row, so it never reaches into
 * the row above or below — and 16px wider than it looks.
 */
const HEIGHTS: Record<ButtonSize, string> = {
  md: 'h-control pointer-coarse:h-touch',
  sm: 'h-control-sm pointer-coarse:h-touch',
  xs: "h-control-xs pointer-coarse:after:absolute pointer-coarse:after:-inset-x-2 pointer-coarse:after:-inset-y-1.5 pointer-coarse:after:content-['']",
}

const PADDING: Record<ButtonSize, string> = {
  md: 'px-4',
  sm: 'px-3 pointer-coarse:px-3.5',
  xs: 'px-2.5',
}

const SQUARE: Record<ButtonSize, string> = {
  md: 'w-control pointer-coarse:w-touch',
  sm: 'w-control-sm pointer-coarse:w-touch',
  xs: 'w-control-xs',
}

const TEXT: Record<ButtonSize, string> = {
  md: 'text-body gap-2 [&_svg]:size-4',
  sm: 'text-detail gap-1.5 [&_svg]:size-[0.9375rem]',
  xs: 'text-caption gap-1 [&_svg]:size-3.5',
}

interface ButtonStyle {
  variant?: ButtonVariant
  size?: ButtonSize
  fullWidth?: boolean
  /** One glyph and nothing else: square, no horizontal padding. */
  square?: boolean
  className?: string
}

/** The one place a button's appearance is decided. */
export function buttonClasses({
  variant = 'secondary',
  size = 'md',
  fullWidth = false,
  square = false,
  className,
}: ButtonStyle = {}): string {
  const boxed = variant !== 'link'
  return cn(
    'relative inline-flex shrink-0 items-center justify-center font-medium whitespace-nowrap',
    'rounded-control [&_svg]:shrink-0',
    'transition-[background-color,border-color,color,transform] duration-150',
    'disabled:cursor-not-allowed disabled:opacity-55 aria-disabled:cursor-not-allowed aria-disabled:opacity-55',
    TEXT[size],
    boxed && 'not-disabled:active:scale-[0.985]',
    boxed && HEIGHTS[size],
    boxed && (square ? SQUARE[size] : PADDING[size]),
    VARIANTS[variant],
    fullWidth && 'w-full',
    className,
  )
}
