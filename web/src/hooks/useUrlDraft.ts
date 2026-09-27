import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Local, immediate state for a text field whose value is kept in the URL.
 *
 * Binding a text input straight to `useUrlState` makes every keystroke a router
 * navigation. React Router 7 runs navigations inside `startTransition`, so the
 * input's new value is not committed with the keystroke: React restores the
 * DOM to the previous URL value, and the next key lands on stale text. Under a
 * 4x CPU throttle, typing "justin jefferson" into the rankings search left
 * "jtin jefferson" in the box and matched nobody. Each navigation also
 * re-renders the whole shell, and `useDeferredValue` cannot help, because
 * inside a transition it returns the new value immediately.
 *
 * So the field owns its text and the URL follows once typing pauses. The URL
 * remains the source of truth for everything outside the field: a change that
 * arrives from elsewhere (Back/Forward, a "Clear filters" button) is adopted
 * into the draft.
 *
 * `commit` is the URL writer. Pass `{ immediate: true }` to the returned setter
 * to write through now, e.g. for a clear button, so a pending debounced write
 * cannot land afterwards and resurrect the old text.
 */
export function useUrlDraft(
  value: string,
  commit: (value: string) => void,
  delayMs = 250,
): [string, (next: string, options?: { immediate?: boolean }) => void] {
  const [draft, setDraftState] = useState(value)
  // The last value this hook wrote to (or adopted from) the URL. It tells an
  // external URL change apart from the echo of our own write.
  const synced = useRef(value)

  // `commit` is typically rebuilt on every URL change (React Router's
  // `setSearchParams` depends on the current params), so the timer reads it
  // through a ref rather than restarting whenever it changes.
  const commitRef = useRef(commit)
  useEffect(() => {
    commitRef.current = commit
  }, [commit])

  // URL → field.
  useEffect(() => {
    if (value === synced.current) return
    synced.current = value
    setDraftState(value)
  }, [value])

  // Field → URL, after a pause.
  useEffect(() => {
    if (draft === synced.current) return
    const id = window.setTimeout(() => {
      synced.current = draft
      commitRef.current(draft)
    }, delayMs)
    return () => window.clearTimeout(id)
  }, [draft, delayMs])

  const setDraft = useCallback((next: string, options?: { immediate?: boolean }) => {
    setDraftState(next)
    if (options?.immediate && next !== synced.current) {
      synced.current = next
      commitRef.current(next)
    }
  }, [])

  return [draft, setDraft]
}
