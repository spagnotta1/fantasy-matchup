import { useEffect, useState } from 'react'
import { Check, Link2 } from 'lucide-react'

import { Button } from '@/components/ui/Button'

/**
 * Copy the current matchup's address.
 *
 * The page mirrors both lineups into the query string as they are built, so the
 * link this copies is simply where the user already is — there is nothing to
 * encode here and no state to serialise. That is the point: the shareable thing
 * and the thing on screen cannot drift apart, because they are the same URL.
 *
 * The clipboard write can fail — an insecure origin, a browser that refuses
 * without a user gesture it recognises — so failure falls back to selecting the
 * address rather than silently doing nothing.
 */
export function ShareMatchup() {
  const [copied, setCopied] = useState(false)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    if (!copied) return
    const timer = setTimeout(() => setCopied(false), 2000)
    return () => clearTimeout(timer)
  }, [copied])

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href)
      setFailed(false)
      setCopied(true)
    } catch {
      setFailed(true)
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <Button size="sm" variant="secondary" onClick={() => void onCopy()}>
        {copied ? (
          <Check aria-hidden className="size-3.5" />
        ) : (
          <Link2 aria-hidden className="size-3.5" />
        )}
        {copied ? 'Link copied' : 'Copy link'}
      </Button>
      <span aria-live="polite" className="text-ink-muted text-xs">
        {failed
          ? 'Copying was blocked — the address bar holds this matchup.'
          : copied
            ? 'Both lineups and the run settings are in the link.'
            : ''}
      </span>
    </div>
  )
}
