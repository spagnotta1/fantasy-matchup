import { useSyncExternalStore } from 'react'

/**
 * Whether the command palette is open, shared by whatever opens it.
 *
 * A module-level store rather than context: the palette is opened from the
 * header button, from a global shortcut and from nowhere else, and none of
 * those need to re-render when it changes — only the palette itself subscribes.
 */
let open = false
const listeners = new Set<() => void>()

function emit() {
  for (const listener of listeners) listener()
}

export function openCommandPalette() {
  if (open) return
  open = true
  emit()
}

export function closeCommandPalette() {
  if (!open) return
  open = false
  emit()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useCommandPaletteOpen(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => open,
    () => false,
  )
}
