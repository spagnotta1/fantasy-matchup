import type { ButtonHTMLAttributes, MouseEvent, ReactNode, Ref } from 'react'
import { Link, type LinkProps } from 'react-router-dom'
import { Loader2 } from 'lucide-react'

import { buttonClasses, type ButtonSize, type ButtonVariant } from './buttonStyles'

export type { ButtonSize, ButtonVariant }

/**
 * Buttons, links that look like buttons, and icon buttons.
 *
 * Four components over one class builder, rather than one component with an
 * `asLink` and an `iconOnly` switch. The switches read well in a sentence and
 * badly in a type: a link has no `disabled` and no `loading`, an icon button
 * has no visible label and so must be given one, and a single props object
 * that admits every combination admits the wrong ones too. Each of these takes
 * exactly what its element can do:
 *
 *   - `Button`          a `<button>`
 *   - `ButtonLink`      a router `<Link>` drawn as a button
 *   - `IconButton`      a square `<button>` holding one glyph; `label` required
 *   - `IconButtonLink`  the same, navigating
 *
 * What they share is `buttonClasses` (`buttonStyles.ts`), so hover, focus,
 * press and disabled are written once and a link cannot drift from the button
 * beside it.
 */

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  fullWidth?: boolean
  /**
   * A glyph set before the label.
   *
   * A glyph passed as a child works too. Passing it here is what lets a
   * loading button put the spinner where the glyph was, so the label does not
   * move.
   */
  icon?: ReactNode
  /**
   * The action is in progress. Shows a spinner in place of the icon and
   * refuses further presses, without changing width.
   */
  loading?: boolean
  ref?: Ref<HTMLButtonElement>
}

export function Button({
  variant,
  size,
  fullWidth,
  icon,
  loading = false,
  className,
  children,
  type = 'button',
  onClick,
  ref,
  ...props
}: ButtonProps) {
  const spinner = <Loader2 aria-hidden className="animate-spin" />
  // No icon to stand in for: the spinner takes the label's place, and the
  // label stays in the layout (and in the accessible name) to hold the width.
  const overlay = loading && !icon

  return (
    <button
      ref={ref}
      type={type}
      // `aria-busy` rather than swapping the label: a screen reader user should
      // hear that the same action is in progress, not that it disappeared.
      aria-busy={loading || undefined}
      // Not the `disabled` attribute. A button that disables itself while it
      // works drops keyboard focus on the floor, and the person who pressed it
      // has to find their place again when it finishes.
      aria-disabled={loading || undefined}
      onClick={loading ? swallow : onClick}
      className={buttonClasses({ variant, size, fullWidth, className })}
      {...props}
    >
      {overlay ? (
        <>
          <span aria-hidden className="absolute inset-0 flex items-center justify-center">
            {spinner}
          </span>
          <span className="inline-flex items-center gap-[inherit] opacity-0">{children}</span>
        </>
      ) : (
        <>
          {loading ? spinner : icon}
          {children}
        </>
      )}
    </button>
  )
}

/** Also stops a submit button from submitting: the click is the submission. */
function swallow(event: MouseEvent) {
  event.preventDefault()
}

export interface ButtonLinkProps extends LinkProps {
  variant?: ButtonVariant
  size?: ButtonSize
  fullWidth?: boolean
  icon?: ReactNode
  ref?: Ref<HTMLAnchorElement>
}

/**
 * A link drawn as a button. Navigation stays navigation: it opens in a new
 * tab, shows its address on hover and is announced as a link. There is no
 * `disabled` — a link that cannot be followed should not be rendered as one.
 */
export function ButtonLink({ variant, size, fullWidth, icon, className, children, ...props }: ButtonLinkProps) {
  return (
    <Link className={buttonClasses({ variant, size, fullWidth, className })} {...props}>
      {icon}
      {children}
    </Link>
  )
}

interface IconOnly {
  /**
   * What the control does, in words. It is the accessible name and the hover
   * title. Required, because a glyph is a guess: this is the only text an
   * icon button has.
   */
  label: string
  /** The glyph. Hidden from assistive technology; `label` speaks for it. */
  children: ReactNode
}

export interface IconButtonProps
  extends Omit<ButtonProps, 'icon' | 'fullWidth' | 'children' | 'aria-label'>, IconOnly {}

export function IconButton({
  label,
  variant = 'ghost',
  size = 'sm',
  loading = false,
  className,
  children,
  type = 'button',
  onClick,
  ref,
  ...props
}: IconButtonProps) {
  return (
    <button
      ref={ref}
      type={type}
      aria-label={label}
      title={label}
      aria-busy={loading || undefined}
      aria-disabled={loading || undefined}
      onClick={loading ? swallow : onClick}
      className={buttonClasses({ variant, size, square: true, className })}
      {...props}
    >
      <span aria-hidden className="contents">
        {loading ? <Loader2 className="animate-spin" /> : children}
      </span>
    </button>
  )
}

export interface IconButtonLinkProps
  extends Omit<ButtonLinkProps, 'icon' | 'fullWidth' | 'children' | 'aria-label'>, IconOnly {}

export function IconButtonLink({
  label,
  variant = 'ghost',
  size = 'sm',
  className,
  children,
  ...props
}: IconButtonLinkProps) {
  return (
    <Link
      aria-label={label}
      title={label}
      className={buttonClasses({ variant, size, square: true, className })}
      {...props}
    >
      <span aria-hidden className="contents">
        {children}
      </span>
    </Link>
  )
}
