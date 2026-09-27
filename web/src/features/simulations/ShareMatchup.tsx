import { useEffect, useState } from 'react'
import { Check, ImageDown, Link2 } from 'lucide-react'

import { Button } from '@/components/ui/Button'
import { drawShareCard, shareOrDownload } from '@/features/simulations/shareCard'
import type { MatchupSimulation } from '@/api/schemas'

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
    <div className="flex flex-col items-start gap-1 sm:items-end">
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
          ? 'Copying was blocked — copy the page address instead to share this matchup.'
          : copied
            ? 'The link includes both lineups and your settings.'
            : ''}
      </span>
    </div>
  )
}

/**
 * Save or share the result as an image (see `shareCard.ts`).
 *
 * Beside "Copy link" rather than instead of it: the link reproduces the run,
 * the picture is what people actually drop into a group chat.
 */
export function ShareImage({
  result,
  labelA,
  labelB,
}: {
  result: MatchupSimulation
  labelA: string
  labelB: string
}) {
  const [state, setState] = useState<'idle' | 'working' | 'done' | 'failed'>('idle')

  const onShare = async () => {
    setState('working')
    try {
      const blob = await drawShareCard(result, { a: labelA, b: labelB })
      await shareOrDownload(blob, `matchup-week-${result.week}.png`, window.location.href)
      setState('done')
    } catch {
      setState('failed')
    }
  }

  return (
    <div className="flex flex-col items-start gap-1 sm:items-end">
      <Button size="sm" variant="secondary" onClick={() => void onShare()} disabled={state === 'working'}>
        <ImageDown aria-hidden className="size-3.5" />
        Share image
      </Button>
      <span aria-live="polite" className="text-ink-muted text-xs">
        {state === 'failed' ? 'The image could not be made in this browser — copy the link instead.' : ''}
      </span>
    </div>
  )
}
