/**
 * Drive the real frontend API layer against the real backend.
 *
 * Loads the actual `src/api/*.ts` modules through Vite's SSR loader — so the
 * Zod schemas, the envelope validation and the error mapping exercised here are
 * byte-for-byte the ones the browser runs — and calls every endpoint the
 * product uses against a live server. A `contract` error means the frontend
 * compiled against a response shape the backend does not produce.
 */

import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

import { createServer } from 'vite'

const BASE = process.env.API_BASE ?? 'http://127.0.0.1:8010'
const WEB_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')

const server = await createServer({
  root: WEB_ROOT,
  configFile: resolve(WEB_ROOT, 'vite.config.ts'),
  server: { middlewareMode: true },
  appType: 'custom',
  logLevel: 'error',
  define: {
    'import.meta.env.VITE_API_BASE_URL': JSON.stringify(BASE),
  },
})

const load = (p) => server.ssrLoadModule(p)

const meta = await load('/src/api/meta.ts')
const projections = await load('/src/api/projections.ts')
const players = await load('/src/api/players.ts')
const matchups = await load('/src/api/matchups.ts')
const advice = await load('/src/api/advice.ts')
const simulations = await load('/src/api/simulations.ts')

const results = []
async function check(name, fn) {
  try {
    const value = await fn()
    results.push({ name, ok: true, note: summarise(value) })
    return value
  } catch (error) {
    results.push({
      name,
      ok: false,
      note: `${error?.kind ?? error?.name ?? 'error'}: ${error?.message ?? error}`,
    })
    return undefined
  }
}

/** Passes when the call is refused as `invalid`, and fails when it succeeds. */
async function expectRefusal(name, fn) {
  try {
    await fn()
    results.push({ name, ok: false, note: 'expected a refusal, got a result' })
  } catch (error) {
    const refused = error?.kind === 'invalid'
    results.push({
      name,
      ok: refused,
      note: refused
        ? `refused: ${String(error.message).split('.')[0]}.`
        : `wrong failure kind: ${error?.kind ?? error}`,
    })
  }
}

function summarise(value) {
  if (value === undefined || value === null) return 'null'
  if (Array.isArray(value)) return `${value.length} items`
  if (Array.isArray(value?.data)) return `${value.data.length} rows`
  if (value?.data && typeof value.data === 'object') return 'object'
  if (typeof value === 'object') return Object.keys(value).slice(0, 4).join(',')
  return String(value)
}

// ---- catalog -------------------------------------------------------------
await check('health', () => meta.getHealth())
const seasons = await check('seasons', () => meta.getSeasons())
await check('scoringProfiles', () => meta.getScoringProfiles())
await check('positions', () => meta.getPositions())
await check('lineupSlots', () => meta.getLineupSlots())
await check('model foundation', () => meta.getModelFoundation())
await check('provenance legend', () => meta.getProvenanceLegend())
await check('cache policy', () => meta.getCachePolicy())
await check('teams', () => meta.getTeams())

// Taken from the catalog rather than hard-coded, which is the point of the
// endpoint: a check pinned to 2025 starts failing on a database that has moved
// on, and would have been reporting on an unpublished week before it did.
const season = seasons?.[0]?.season ?? 2025
const week = seasons?.[0]?.latest_published_week ?? 18
// The single-season endpoint has its own client function, so it is exercised
// here too — and it must agree with what `/seasons` said.
const weeks = await check(`weeks(${season})`, () => meta.getPublishedWeeks(season))
if (weeks && String(weeks) !== String(seasons?.[0]?.published_weeks ?? weeks)) {
  results.push({
    name: 'week lists agree',
    ok: false,
    note: `/seasons says ${seasons?.[0]?.published_weeks} and /seasons/${season}/weeks says ${weeks}`,
  })
}
const slate = { season, week, scoringProfile: 'half_ppr' }

// ---- boards --------------------------------------------------------------
const board = await check('projections board', () =>
  projections.getBoard({ ...slate, limit: 500 }),
)
for (const pos of ['QB', 'RB', 'WR', 'TE']) {
  await check(`rankings/${pos}`, () => projections.getPositionRankings(pos, { ...slate, limit: 500 }))
}

// K and DST are *expected* to be refused. The API recognises both positions and
// declines to project them, with a reason — that refusal is a documented part
// of the contract, not an outage, and the frontend renders it as its own state
// rather than as an error. A silent success here would be the real failure.
for (const pos of ['K', 'DST']) {
  await expectRefusal(`rankings/${pos} refused`, () =>
    projections.getPositionRankings(pos, { ...slate, limit: 500 }),
  )
}

// ---- players -------------------------------------------------------------
const first = board?.data?.[0]?.projection?.player?.player_id
const second = board?.data?.[1]?.projection?.player?.player_id
if (first) {
  await check('player detail', () => players.getPlayer(first))
  await check('player profile', () => players.getPlayerProfile(first, slate))
  await check('player history', () => players.getPlayerHistory(first, { scoringProfile: 'half_ppr' }))
  await check('projection by player', () => projections.getProjection(first, slate))
}
await check('search "all"', () => players.searchPlayers('all', { limit: 5 }))

// ---- matchups ------------------------------------------------------------
await check('week schedule', () => matchups.getWeek(week, season))
const games = await check('games', () => matchups.getGames({ season, week }))
const gameId = games?.data?.[0]?.game_id
if (gameId) await check('matchup analysis', () => matchups.getMatchup(gameId, slate))
await check('defense rankings RB', () => matchups.getDefenseRankings({ season, week, position: 'RB' }))
const team = board?.data?.[0]?.projection?.team
if (team) await check('team outlook', () => matchups.getTeamOutlook(team, slate))

// ---- advice --------------------------------------------------------------
if (first && second) {
  await check('compare', () => advice.comparePlayers([first, second], slate))
  await check('start-sit', () => advice.getStartSit(first, second, slate))
}

// ---- simulation ----------------------------------------------------------
// The lineup composition is built with the *application's own* parser, not a
// hardcoded slot list. The API serves the composition as prose in
// `meta.notices` rather than as structured data, and this client parses it —
// so this is the one integration point that can break without either side
// changing its schema. Running the real parser against the live notice is the
// only thing that catches that.
const lineupFormat = await load('/src/features/simulations/lineupFormat.ts')
const slotCatalog = await meta.getLineupSlots()
const formats = lineupFormat.parseLineupFormats(slotCatalog.formats)
const format = lineupFormat.resolveFormat(formats, slotCatalog.slots)

results.push({
  name: 'lineup format parsed',
  ok: formats.length > 0,
  note:
    formats.length > 0
      ? `${format.label} — ${format.size} starters`
      : 'notice did not parse; builder would fall back',
})

const ELIGIBLE = Object.fromEntries(slotCatalog.slots.map((s) => [s.slot, s.eligible_positions]))

function buildLineup(pool, used) {
  const lineup = []
  for (const requirement of format.requirements) {
    for (let i = 0; i < requirement.count; i += 1) {
      const eligible = ELIGIBLE[requirement.slot] ?? []
      const pick = pool.find(
        (entry) =>
          eligible.includes(entry.projection.player.position) &&
          !used.has(entry.projection.player.player_id),
      )
      if (!pick) return null
      used.add(pick.projection.player.player_id)
      lineup.push({ player_id: pick.projection.player.player_id, slot: requirement.slot })
    }
  }
  return lineup
}

let simulation
if (board?.data?.length) {
  const used = new Set()
  const teamA = buildLineup(board.data, used)
  const teamB = buildLineup(board.data, used)

  if (teamA && teamB) {
    simulation = await check('simulation run', () =>
      simulations.runSimulation({
        season,
        week,
        scoring_profile: 'half_ppr',
        simulation_count: 2000,
        seed: 42,
        team_a: teamA,
        team_b: teamB,
      }),
    )

    // The same seed and lineups must reproduce the same numbers exactly — the
    // product tells the user so on the simulation settings panel.
    if (simulation) {
      const repeat = await check('simulation reproducible', () =>
        simulations.runSimulation({
          season,
          week,
          scoring_profile: 'half_ppr',
          simulation_count: 2000,
          seed: 42,
          team_a: teamA,
          team_b: teamB,
        }),
      )
      const same =
        repeat?.data?.simulation?.win_probability_a === simulation.data.simulation.win_probability_a
      results.push({
        name: 'seed determinism',
        ok: Boolean(same),
        note: same ? 'identical win probability' : 'same seed produced a different result',
      })
    }
    // The refusal the builder now pre-empts. A starter with no published
    // projection makes the whole matchup unanswerable — a team total is a sum,
    // so the engine refuses rather than returning a total that is quietly light.
    // The pre-flight check in `availability.ts` decides the same thing from the
    // board, and this is what proves the two agree: the player it flags is the
    // player the API refuses, and if the API ever stopped refusing, blocking the
    // run in the UI would become a bug rather than a courtesy.
    // `/players/search` searches the player *dimension*, which holds everyone
    // who has ever played — so a common surname reliably returns someone with no
    // board this week. That is exactly the mistake a user makes in the builder.
    const candidates = await players.searchPlayers('smith', { limit: 25 })
    const projectedIds = new Set(board.data.map((entry) => entry.projection.player.player_id))
    const offBoard = candidates.find(
      (player) => !projectedIds.has(player.player_id) && player.position === 'QB',
    )

    if (teamA && teamB && offBoard) {
      const spoiled = [{ ...teamA[0], player_id: offBoard.player_id }, ...teamA.slice(1)]
      await expectRefusal('unprojectable starter refused', () =>
        simulations.runSimulation({
          season,
          week,
          scoring_profile: 'half_ppr',
          simulation_count: 500,
          team_a: spoiled,
          team_b: teamB,
        }),
      )

      // …and the client-side check reaches the same verdict from the board
      // alone, which is what lets the row say so before the run.
      const availability = await load('/src/features/simulations/availability.ts')
      const index = availability.indexBoard(board.data, { total: board.data.length }, false)
      const readiness = availability.lineupReadiness(
        spoiled.map((entry, i) => ({
          key: String(i),
          slot: entry.slot,
          player: { player_id: entry.player_id, name: offBoard.name, position: offBoard.position },
        })),
        index,
        availability.projectedPositions(await meta.getPositions()),
        week,
      )
      results.push({
        name: 'pre-flight agrees',
        ok: !readiness.runnable && readiness.problems.length === 1,
        note: readiness.problems[0]
          ? `flagged ${readiness.problems[0].slot}: ${readiness.problems[0].reason}`
          : 'client would have allowed a lineup the API refuses',
      })
    }
  } else {
    results.push({ name: 'simulation run', ok: false, note: 'could not build two full lineups' })
  }
}

// ---- the workflow's own helpers -----------------------------------------
// Pure, but load-bearing: a matchup that does not survive its own URL cannot be
// shared or reloaded, and notices that do not sort into a side are the flat list
// they were before.
{
  const share = await load('/src/features/simulations/shareLink.ts')
  const entries = [
    { slot: 'QB', player_id: '00-0036971' },
    { slot: 'FLEX', player_id: '00-0033280' },
  ]
  const roundTripped = share.decodeLineup(share.encodeLineup(entries))
  results.push({
    name: 'share link round-trips',
    ok: JSON.stringify(roundTripped) === JSON.stringify(entries),
    note: share.encodeLineup(entries),
  })

  const notices = await load('/src/features/simulations/notices.ts')
  const grouped = notices.groupNotices(
    ['team_a: Kyle Pitts is listed Questionable.', 'Player outcomes were drawn independently.'],
    { a: 'Your team', b: 'Opponent' },
  )
  const sideGroup = grouped.find((group) => group.key === 'a')
  results.push({
    name: 'notices grouped by side',
    ok:
      grouped.length === 2 &&
      sideGroup?.notices[0] === 'Kyle Pitts is listed Questionable.',
    note: grouped.map((group) => `${group.key}:${group.notices.length}`).join(' '),
  })
}

// ---- report --------------------------------------------------------------
console.log('\n=== CONTRACT CHECK ===')
let failed = 0
for (const r of results) {
  if (!r.ok) failed += 1
  console.log(`${r.ok ? 'PASS' : 'FAIL'}  ${r.name.padEnd(26)} ${r.note}`)
}
console.log(`\n${results.length - failed} passed, ${failed} failed`)

await server.close()
process.exit(failed > 0 ? 1 : 0)
