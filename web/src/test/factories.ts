/**
 * Fixtures for unit tests.
 *
 * Built through the real Zod contracts, so a fixture cannot describe a
 * response the API could not send: if the contract gains a required field,
 * these fail to parse and the tests say so, instead of passing against a shape
 * that no longer exists.
 */

import {
  projectionSchema,
  rankedProjectionSchema,
  type Projection,
  type RankedProjection,
} from '@/api/schemas'

export interface ProjectionOptions {
  id?: string
  name?: string
  position?: string
  team?: string
  /** The calibrated mean. `null` builds an uncalibrated projection. */
  expected?: number | null
  predicted?: number
  floor?: number | null
  p25?: number | null
  median?: number | null
  p75?: number | null
  ceiling?: number | null
  boom?: number | null
  bust?: number | null
  /** A matchup letter; omitted means ungraded. */
  grade?: string
  status?: string
}

export function makeProjection(options: ProjectionOptions = {}): Projection {
  const {
    id = 'p1',
    name = id,
    position = 'RB',
    team = 'DET',
    predicted = 12,
    expected = predicted,
    median = predicted - 0.5,
    floor = median === null ? null : median - 6,
    p25 = median === null ? null : median - 3,
    p75 = median === null ? null : median + 3,
    ceiling = median === null ? null : median + 10,
    boom = 0.2,
    bust = 0.1,
    grade,
    status = 'ACT',
  } = options

  return projectionSchema.parse({
    player: { player_id: id, name, position, team, status },
    season: 2026,
    week: 4,
    team,
    opponent: 'CAR',
    is_home: false,
    game_id: `2026_04_${team}_CAR`,
    prediction: {
      provenance: 'model',
      scoring_profile: 'half_ppr',
      points: {
        expected,
        predicted,
        floor,
        p25,
        median,
        p75,
        ceiling,
        evidence: 'established',
        boom_probability: boom,
        bust_probability: bust,
        boom_threshold: 20,
        bust_threshold: 5,
        shape: 'steady',
        extrapolated: false,
      },
      components: {},
    },
    usage: { provenance: 'derived' },
    matchup: grade
      ? {
          provenance: 'derived',
          source: 'defense_form',
          applied_to_projection: false,
          grade: { graded: true, letter: grade, score: 0.5, defense_rank: 16, sample_games: 4 },
        }
      : null,
    context: { provenance: 'context' },
  })
}

export function makeEntry(
  rank: number,
  options: ProjectionOptions & { tier?: number; positionalRank?: number } = {},
): RankedProjection {
  const { tier = 1, positionalRank = rank, ...projection } = options
  return rankedProjectionSchema.parse({
    rank,
    positional_rank: positionalRank,
    tier,
    projection: makeProjection({ id: `p${rank}`, ...projection }),
  })
}

/**
 * A board whose range widths are shared across groups of players, as a
 * published run's are: `groups` distinct widths spread over `count` players.
 */
export function sharedRangeBoard(count: number, groups: number, options: ProjectionOptions = {}): Projection[] {
  return Array.from({ length: count }, (_, index) => {
    const median = 6 + index * 0.1
    return makeProjection({
      id: `s${index}`,
      median,
      // The width above the median is one of `groups` values, whoever the player is.
      ceiling: median + 10 + (index % groups),
      ...options,
    })
  })
}

/** A board where every player has their own range width. */
export function perPlayerRangeBoard(count: number, options: ProjectionOptions = {}): Projection[] {
  return Array.from({ length: count }, (_, index) => {
    const median = 6 + index * 0.1
    return makeProjection({ id: `u${index}`, median, ceiling: median + 8 + index * 0.37, ...options })
  })
}
