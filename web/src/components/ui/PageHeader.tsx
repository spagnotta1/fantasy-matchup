import type { ReactNode } from 'react'

import { useDocumentTitle } from '@/app/page-title'

/**
 * The heading block every page opens with.
 *
 * One `<h1>` per page, in one place, so the document outline is correct without
 * each page remembering to build it. The `question` line is a product
 * convention rather than decoration: every screen here should state the fantasy
 * question it answers, because a screen that cannot is a screen that is showing
 * data for its own sake.
 *
 * It also names the document. The browser tab and the screen-reader
 * announcement should say what the `<h1>` says, and the reliable way to keep
 * three copies of a page's name in agreement is to have one.
 */
export function PageHeader({
  title,
  question,
  action,
  /**
   * Overrides the tab/announcement name. For a heading that is short because it
   * sits under an obvious context — "Week 14" reads fine above the dashboard
   * and badly as a bare tab title.
   */
  documentTitle,
}: {
  title: string
  question?: string
  action?: ReactNode
  documentTitle?: string
}) {
  useDocumentTitle(documentTitle ?? title)

  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-ink text-xl font-semibold tracking-tight sm:text-2xl">{title}</h1>
        {question && (
          <p className="text-ink-secondary mt-1 max-w-2xl text-sm leading-relaxed">{question}</p>
        )}
      </div>
      {action && <div className="flex shrink-0 items-center gap-2">{action}</div>}
    </div>
  )
}
