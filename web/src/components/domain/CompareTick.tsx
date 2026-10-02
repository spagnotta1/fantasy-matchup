import { useState } from 'react'

import { Checkbox } from '@/components/ui/Checkbox'

/**
 * A row's tick box for the comparison.
 *
 * The box owns what it shows, and the URL catches up. The ticks live in the
 * address (`useCompareSelection`), and the router applies a change of address
 * as a transition: bound straight to it, a box stayed empty after the click
 * until a board of a hundred rows had re-rendered behind it. A tick box that
 * does not tick when pressed gets pressed again. So the press flips the box at
 * once, and the answer from the URL — this press, a Clear in the bar, a Back —
 * is taken whenever it changes.
 */
export function CompareTick({
  name,
  ticked,
  full,
  onToggle,
  className,
}: {
  /** The player's name, for the box's label. */
  name: string
  /** Whether the URL has this player ticked. */
  ticked: boolean
  /** Six are ticked: an unticked box cannot be. */
  full: boolean
  onToggle: () => void
  /** Classes for the hit area: the caller's cell. */
  className?: string
}) {
  const [shown, setShown] = useState(ticked)
  // Adjusted during render, not in an effect, so the box is never drawn for a
  // frame with an answer the URL has already replaced.
  const [answered, setAnswered] = useState(ticked)
  if (answered !== ticked) {
    setAnswered(ticked)
    setShown(ticked)
  }

  return (
    <Checkbox
      label={`Select ${name} to compare`}
      checked={shown}
      disabled={full && !shown}
      onChange={() => {
        setShown(!shown)
        onToggle()
      }}
      className={className}
    />
  )
}
