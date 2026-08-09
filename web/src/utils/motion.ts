/**
 * Whether the user has asked for less motion.
 *
 * The stylesheet already neutralises CSS animations and transitions under
 * `prefers-reduced-motion`, but it cannot reach a scroll that JavaScript asks
 * for explicitly: `scrollIntoView({ behavior: 'smooth' })` smooth-scrolls
 * regardless of the computed `scroll-behavior`, because an explicit argument
 * beats the CSS property by specification. A page-length animated scroll is
 * exactly the kind of movement the setting exists to prevent, so the call site
 * has to ask.
 *
 * Read at call time rather than subscribed to — this answers "what should this
 * one interaction do", and the setting is not going to change mid-scroll.
 */
export function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/** The scroll behaviour to use for a deliberate, user-initiated scroll. */
export function scrollBehavior(): ScrollBehavior {
  return prefersReducedMotion() ? 'auto' : 'smooth'
}
