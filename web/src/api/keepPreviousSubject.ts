/**
 * Hold the previous answer on screen while the next one loads — but only when
 * it is the *same subject* being re-requested.
 *
 * Changing the week, the scoring profile or a filter produces a new cache key,
 * and the default behaviour for a new key is to fall back to the pending state:
 * the content vanishes, a skeleton flashes for as long as the request takes,
 * and it comes back. On screens whose whole purpose is comparing rows, that
 * wipe is the single most disruptive thing the UI does — and the slate
 * selectors in the header change the key on every screen at once.
 *
 * Keeping the previous answer is only honest while it still describes the thing
 * the page claims to be showing. Re-requesting the same board under a different
 * week is fine: the reader sees last week's numbers dim for a moment under a
 * visible busy state. Switching from the RB board to the WR board is not — the
 * heading would say WR over a screenful of running backs. So each caller
 * declares its subject, and previous data survives only while that is
 * unchanged.
 *
 * Pair it with `<Refreshing>`, which is what makes the retained data visibly
 * stale rather than silently wrong.
 *
 * Usage — the subject must be passed to both `meta` and this function, because
 * one records what the *current* query is about and the other reads what the
 * previous one was about:
 *
 * ```ts
 * const subject = position ?? ''
 * useQuery({
 *   queryKey: …,
 *   meta: { subject },
 *   placeholderData: keepPreviousSubject(subject),
 * })
 * ```
 */
export function keepPreviousSubject(subject: unknown) {
  const encoded = JSON.stringify(subject ?? null)

  // Generic on the *returned* function, not the factory: the data type is only
  // knowable at the point the result is assigned to a query's `placeholderData`,
  // and there is nothing at the call site for TypeScript to infer it from. The
  // query argument is typed structurally, on just the field this reads, so it
  // stays assignable whatever the query's own type parameters are.
  return <TData,>(
    previous: TData | undefined,
    previousQuery: { meta?: Record<string, unknown> } | undefined,
  ): TData | undefined => {
    if (previous === undefined) return undefined
    return JSON.stringify(previousQuery?.meta?.subject ?? null) === encoded ? previous : undefined
  }
}
