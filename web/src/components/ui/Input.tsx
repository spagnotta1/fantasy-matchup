import { forwardRef, useId, type InputHTMLAttributes, type ReactNode } from 'react'

import { cn } from '@/utils/cn'

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string
  hideLabel?: boolean
  hint?: string
  /** Error text. Presence also sets `aria-invalid`. */
  error?: string | null
  icon?: ReactNode
  /** Rendered at the trailing edge: a clear button, a shortcut hint, a spinner. */
  trailing?: ReactNode
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, hideLabel, hint, error, icon, trailing, className, id, type = 'text', ...props },
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
        className={cn('text-ink-secondary text-xs font-medium', hideLabel && 'sr-only')}
      >
        {label}
      </label>
      <div className="relative">
        {icon && (
          <span
            aria-hidden
            className="text-ink-muted pointer-events-none absolute top-1/2 left-3 flex -translate-y-1/2 items-center"
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
            'bg-surface border-line text-ink placeholder:text-ink-muted h-10 w-full rounded-[var(--radius-control)] border text-sm',
            'transition-colors hover:border-line-strong disabled:cursor-not-allowed disabled:opacity-55',
            icon ? 'pl-9' : 'pl-3',
            trailing ? 'pr-10' : 'pr-3',
            error && 'border-negative',
          )}
          {...props}
        />
        {trailing && (
          <span className="absolute top-1/2 right-2 flex -translate-y-1/2 items-center">
            {trailing}
          </span>
        )}
      </div>
      {error ? (
        <p id={errorId} className="text-negative-text text-xs" role="alert">
          {error}
        </p>
      ) : (
        hint && (
          <p id={hintId} className="text-ink-muted text-xs">
            {hint}
          </p>
        )
      )}
    </div>
  )
})
