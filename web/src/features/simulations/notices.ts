/**
 * Sorting the response's caveats into the lineup they are about.
 *
 * `meta.notices` on a simulation is not a general list. The engine labels the
 * ones that belong to a side — `"team_a: Kyle Pitts is listed Questionable."`,
 * `"team_b: George Kittle, Brock Purdy share an offence (SF)."` — and mixes them
 * with the ones that apply to the whole run, such as the independence
 * assumption. A real matchup produces a dozen, and rendered as one flat bullet
 * list the two that name *your* starters are indistinguishable from the boilerplate.
 *
 * So the prefix the API already writes is read, and nothing else is: the text is
 * passed through untouched, no notice is dropped, and one that carries no prefix
 * stays in the shared group rather than being guessed at. If the prefix ever
 * changes, every notice lands in "this run" and the screen is exactly as
 * informative as it was before.
 */

/** `team_a: …` / `team_b: …`, the labels the simulation service writes. */
const SIDE_PATTERN = /^team_(a|b):\s*/i

export interface NoticeGroup {
  key: 'a' | 'b' | 'run'
  title: string
  notices: string[]
}

export function groupNotices(
  notices: string[],
  labels: { a: string; b: string },
): NoticeGroup[] {
  const grouped: Record<'a' | 'b' | 'run', string[]> = { a: [], b: [], run: [] }

  for (const notice of notices) {
    const match = SIDE_PATTERN.exec(notice)
    const side = match?.[1]?.toLowerCase()
    if (side === 'a' || side === 'b') {
      // The prefix becomes the heading, so repeating it on every line would read
      // as "Your team — team_a: …".
      grouped[side].push(notice.replace(SIDE_PATTERN, ''))
    } else {
      grouped.run.push(notice)
    }
  }

  return [
    { key: 'a' as const, title: `${labels.a} — what to know`, notices: grouped.a },
    { key: 'b' as const, title: `${labels.b} — what to know`, notices: grouped.b },
    { key: 'run' as const, title: 'What this result depends on', notices: grouped.run },
  ].filter((group) => group.notices.length > 0)
}
