import type { RefObject } from 'react'

import { useElementSize } from '@/hooks/useElementSize'

/**
 * The room, in pixels, under which a table of players is drawn as a list: a
 * frozen player column and two columns of numbers. With less than that a table
 * shows one column at a time beside the name. See `components/ui/RowList`.
 */
export const ROW_LIST_BELOW = 480

/**
 * Whether the element has too little room for a table, measured and kept
 * current. The element's own width, not the window's: the sidebar takes 240px
 * of a laptop, and a card beside another has less room again.
 *
 * False until the element has been measured, which is before the first paint.
 * Put the ref on an element that is there for as long as the component is:
 * what is measured is the element the ref held when the component mounted.
 */
export function useRowList<T extends HTMLElement>(): [RefObject<T | null>, boolean] {
  const [ref, size] = useElementSize<T>()
  return [ref, size.width > 0 && size.width < ROW_LIST_BELOW]
}
