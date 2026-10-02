import { useLayoutEffect, useRef, useState, type RefObject } from 'react'

export interface ElementSize {
  /** Rendered width in pixels. Zero until the element has been measured. */
  width: number
  height: number
}

/**
 * An element's rendered size in pixels, kept current as it changes.
 *
 * For the cases CSS cannot express. Something sticky has to stop under
 * something else sticky whose height is not fixed: the board's toolbar wraps
 * onto a second line on a narrow screen, and the table header under it has to
 * stop below wherever the toolbar actually ends. And a component has to
 * *choose what to render* by the room it has, which a container query can
 * restyle but cannot do.
 *
 * Measured in a layout effect, so the first measurement lands before the
 * first paint and nothing is drawn at the wrong size.
 */
export function useElementSize<T extends HTMLElement>(): [RefObject<T | null>, ElementSize] {
  const ref = useRef<T>(null)
  const [size, setSize] = useState<ElementSize>({ width: 0, height: 0 })

  useLayoutEffect(() => {
    const element = ref.current
    if (!element) return
    // The border box: what the element occupies, padding and border included.
    const measure = () => {
      const box = element.getBoundingClientRect()
      const next = { width: Math.round(box.width), height: Math.round(box.height) }
      setSize((current) => (current.width === next.width && current.height === next.height ? current : next))
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  return [ref, size]
}
