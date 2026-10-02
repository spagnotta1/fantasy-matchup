import { forwardRef, useId, type InputHTMLAttributes, type ReactNode } from 'react'

import { cn } from '@/utils/cn'

// The DOM's `size` is a character count nobody here uses; this one is the
// control height, the same word `Select` and `Button` use for it.
export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> {
  label: string
  /** `md` 40px in a form, `sm` 32px in a toolbar. */
  size?: 'sm' | 'md'
  hideLabel?: boolean
  hint?: string
  /** Error text. Presence also sets `aria-invalid`. */
  error?: string | null
  icon?: ReactNode
  /** Rendered at the trailing edge: a clear button, a shortcut hint, a spinner. */
  trailing?: ReactNode
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, hideLabel, hint, error, icon, trailing, size = 'md', className, id, type = 'text', ...props },
  ref,
) {
  const generatedId = useId()
  const inputId = id ?? generatedId
  const hintId = hint ? `${inputId}-hint` : undefined
  const errorId = error ? `${inputId}-error` : undefined

  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      <label
        htmlFor={inputId}
        className={cn('text-ink-secondary text-caption font-medium', hideLabel && 'sr-only')}
      >
        {label}
      </label>
      <div className="relative">
        {icon && (
          <span
            aria-hidden
            className={cn(
              'text-ink-muted pointer-events-none absolute top-1/2 flex -translate-y-1/2 items-center',
              size === 'sm' ? 'left-2.5 [&_svg]:size-3.5' : 'left-3',
            )}
          >
            {icon}
          </span>
        )}
        <input
          ref={ref}
          id={inputId}
          type={type}
          aria-invalid={error ? true : undefined}
          aria-describedby={cn(errorId, hintId) || undefined}
          className={cn(
            'bg-surface border-line-input text-ink placeholder:text-ink-muted rounded-control w-full border',
            'transition-colors hover:border-line-strong disabled:cursor-not-allowed disabled:opacity-55',
            size === 'sm' ? 'h-control-sm text-detail' : 'h-control text-body',
            icon ? (size === 'sm' ? 'pl-8' : 'pl-9') : size === 'sm' ? 'pl-2.5' : 'pl-3',
            trailing ? 'pr-10' : size === 'sm' ? 'pr-2.5' : 'pr-3',
            error && 'border-negative',
          )}
          {...props}
        />
        {trailing && (
          <span
            className={cn(
              'absolute top-1/2 flex -translate-y-1/2 items-center',
              size === 'sm' ? 'right-0.5' : 'right-2',
            )}
          >
            {trailing}
          </span>
        )}
      </div>
      {error ? (
        <p id={errorId} className="text-negative-text text-detail" role="alert">
          {error}
        </p>
      ) : (
        hint && (
          <p id={hintId} className="text-ink-muted text-detail">
            {hint}
          </p>
        )
      )}
    </div>
  )
})
