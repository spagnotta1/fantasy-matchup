import { Link } from 'react-router-dom'

import { EmptyState } from '@/components/feedback/States'
import { Card } from '@/components/ui/Card'
import { useDocumentTitle } from '@/app/page-title'

/**
 * A pass thrown to where no page is.
 *
 * The same field as every range strip — yard lines every five, the yellow line
 * — with the ball sailing past the end of it. Decoration only; the heading and
 * the sentence under it say what happened in plain words.
 */
function OutOfBounds() {
  return (
    <svg aria-hidden viewBox="0 0 120 40" className="h-16 w-48">
      <rect x="0" y="8" width="92" height="24" rx="4" fill="var(--color-field)" />
      {[15, 30, 45, 60, 75].map((x) => (
        <line key={x} x1={x} y1="8" x2={x} y2="32" stroke="var(--color-field-line)" strokeWidth="1" />
      ))}
      <rect x="58" y="8" width="3" height="24" fill="var(--color-line-to-gain)" />
      <path d="M10 26 Q60 -8 104 18" fill="none" stroke="var(--color-ink-muted)" strokeWidth="1.2" strokeDasharray="3 3" />
      <ellipse cx="108" cy="21" rx="8" ry="5" transform="rotate(28 108 21)" fill="var(--color-ink)" />
      <path d="M105 19.5l6 3" stroke="var(--color-surface)" strokeWidth="1" strokeLinecap="round" />
    </svg>
  )
}

export default function NotFoundPage() {
  useDocumentTitle('Page not found')

  return (
    <Card>
      <EmptyState
        illustration={<OutOfBounds />}
        eyebrow="Incomplete pass"
        // The only heading on this route, so it is the page's h1.
        titleAs="h1"
        title="This page doesn't exist"
        description="The link may be out of date, or the address may have a typo in it."
        action={
          <Link
            to="/"
            className="bg-accent text-on-accent hover:bg-accent-hover inline-flex h-10 items-center rounded-[var(--radius-control)] px-4 text-sm font-medium transition-colors"
          >
            Back to this week
          </Link>
        }
      />
    </Card>
  )
}
