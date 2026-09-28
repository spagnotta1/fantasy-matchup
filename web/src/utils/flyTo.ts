import { prefersReducedMotion } from '@/utils/motion'

/**
 * Send a copy of `source` flying into the navigation item for `to`.
 *
 * The "added to my team" moment: the headshot lifts off the page and lands on
 * My team, so the reader sees where the player went rather than trusting a
 * button that changed its label. Pure ornament — the roster is already saved
 * before this starts — so it is skipped under reduced motion, when the source
 * or target is not on screen, and silently if anything about it fails.
 *
 * The target is whichever copy of the nav item is actually laid out: the
 * sidebar on a desktop, the bottom bar on a phone. Both carry `data-nav`.
 */
export function flyTo(source: Element | null, to: string): Promise<void> {
  if (!source || prefersReducedMotion()) return Promise.resolve()
  const target = [...document.querySelectorAll(`[data-nav="${to}"]`)].find(
    (element) => element.getBoundingClientRect().width > 0,
  )
  if (!target) return Promise.resolve()

  const from = source.getBoundingClientRect()
  const end = target.getBoundingClientRect()
  const clone = source.cloneNode(true) as HTMLElement
  Object.assign(clone.style, {
    position: 'fixed',
    left: `${from.left}px`,
    top: `${from.top}px`,
    width: `${from.width}px`,
    height: `${from.height}px`,
    margin: '0',
    zIndex: '60',
    pointerEvents: 'none',
  })
  clone.setAttribute('aria-hidden', 'true')
  document.body.appendChild(clone)

  const dx = end.left + end.width / 2 - (from.left + from.width / 2)
  const dy = end.top + end.height / 2 - (from.top + from.height / 2)
  const scale = Math.min(24 / from.width, 1)

  const flight = clone.animate(
    [
      { transform: 'translate(0, 0) scale(1)', opacity: 1 },
      { transform: `translate(${dx * 0.5}px, ${dy * 0.5 - 60}px) scale(${(1 + scale) / 2})`, opacity: 1, offset: 0.55 },
      { transform: `translate(${dx}px, ${dy}px) scale(${scale})`, opacity: 0.2 },
    ],
    { duration: 650, easing: 'cubic-bezier(0.5, 0, 0.3, 1)' },
  )
  return flight.finished.then(
    () => clone.remove(),
    () => clone.remove(),
  )
}
