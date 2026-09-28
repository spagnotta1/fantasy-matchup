import { useLayoutEffect, useRef, useState, type CSSProperties, type RefObject } from 'react'

/**
 * The position of a group's active item, for one indicator that slides
 * between items instead of one that blinks out here and in over there.
 *
 * The container marks its active child with `data-active="true"` and must be
 * the positioned ancestor (`relative`) the indicator is drawn inside. Measured
 * before paint, and again whenever the container resizes, so a web font
 * arriving or a label changing never leaves the indicator short.
 *
 * The first placement does not animate — sliding in from the left edge on page
 * load is movement nobody caused. Every later one does, and the reduced-motion
 * rule flattens the transition like every other.
 */
export function useSlidingIndicator<T extends HTMLElement>(
  activeKey: unknown,
): [RefObject<T | null>, CSSProperties | null] {
  const ref = useRef<T>(null)
  const [style, setStyle] = useState<CSSProperties | null>(null)
  const placed = useRef(false)

  useLayoutEffect(() => {
    const container = ref.current
    if (!container) return
    const measure = () => {
      const active = container.querySelector<HTMLElement>('[data-active="true"]')
      if (!active) {
        setStyle(null)
        return
      }
      setStyle({
        left: active.offsetLeft,
        top: active.offsetTop,
        width: active.offsetWidth,
        height: active.offsetHeight,
        transition: placed.current
          ? 'left 220ms cubic-bezier(0.16, 1, 0.3, 1), width 220ms cubic-bezier(0.16, 1, 0.3, 1)'
          : 'none',
      })
      placed.current = true
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(container)
    return () => observer.disconnect()
  }, [activeKey])

  return [ref, style]
}
