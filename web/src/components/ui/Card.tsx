import type { HTMLAttributes, ReactNode } from 'react'

import { cn } from '@/utils/cn'

/**
 * The single container primitive.
 *
 * Every panel in the product is one of these. That is the point: one border
 * radius, one border colour, one shadow, so the interface reads as one system
 * rather than as a collection of screens built on different weeks.
 */
export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        'bg-surface border-line rounded-[var(--radius-card)] border shadow-card',
        className,
      )}
      {...props}
    />
  )
}

// `title` is omitted from the div attributes and redeclared: the DOM's `title`
// is a tooltip string, and this one is the rendered heading.
interface CardHeaderProps extends Omit<HTMLAttributes<HTMLDivElement>, 'title'> {
  title: ReactNode
  /** One line of context under the title. Optional, and usually worth it. */
  description?: ReactNode
  /** Right-aligned controls: a filter, a link, a segmented toggle. */
  action?: ReactNode
  /** Heading level. Pick the one the document outline needs, not the size you want. */
  as?: 'h2' | 'h3' | 'h4'
}

export function CardHeader({
  title,
  description,
  action,
  as: Heading = 'h2',
  className,
  ...props
}: CardHeaderProps) {
  return (
    <div
      className={cn(
        'border-line flex flex-wrap items-start justify-between gap-3 border-b px-5 py-4',
        className,
      )}
      {...props}
    >
      <div className="min-w-0">
        <Heading className="text-ink text-sm font-semibold tracking-tight">{title}</Heading>
        {description && (
          <p className="text-ink-muted mt-1 text-xs leading-relaxed">{description}</p>
        )}
      </div>
      {action && <div className="flex shrink-0 items-center gap-2">{action}</div>}
    </div>
  )
}

export function CardBody({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('p-5', className)} {...props} />
}

export function CardFooter({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('border-line text-ink-muted border-t px-5 py-3 text-xs', className)}
      {...props}
    />
  )
}
