import { Link } from 'react-router-dom'
import { Compass } from 'lucide-react'

import { EmptyState } from '@/components/feedback/States'
import { Card } from '@/components/ui/Card'
import { useDocumentTitle } from '@/app/page-title'

export default function NotFoundPage() {
  useDocumentTitle('Page not found')

  return (
    <Card>
      <EmptyState
        icon={<Compass aria-hidden className="size-5" />}
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
