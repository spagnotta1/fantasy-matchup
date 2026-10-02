import type { HTMLAttributes, ReactNode } from 'react'

import { cn } from '@/utils/cn'

/**
 * The single container primitive.
 *
 * Every panel in the product is one of these. That is the point: one border
 * radius and one border colour, so the interface reads as one system rather
 * than as a collection of screens built on different weeks.
 *
 * A hairline and no shadow. Elevation is kept for what actually sits above the
 * page — overlays, and the one panel a screen may lift (`shadow-raised`) — so
 * that when something is raised it means something.
 */
export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        'bg-surface border-line-strong rounded-card border',
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
        <Heading className="text-ink text-section">{title}</Heading>
        {description && (
          <p className="text-ink-muted text-detail mt-1">{description}</p>
        )}
      </div>
      {/* Capped at the header's width and allowed to wrap: a long action —
          a badge beside a primary link — otherwise ran off a phone-width card
          and was clipped by it. */}
      {action && (
        <div className="flex max-w-full shrink-0 flex-wrap items-center gap-2">{action}</div>
      )}
    </div>
  )
}

export function CardBody({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('p-5', className)} {...props} />
}

export function CardFooter({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('border-line text-ink-muted border-t px-5 py-3 text-detail', className)}
      {...props}
    />
  )
}
