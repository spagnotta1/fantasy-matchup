/**
 * Fixtures for unit tests.
 *
 * Built through the real Zod contracts, so a fixture cannot describe a
 * response the API could not send: if the contract gains a required field,
 * these fail to parse and the tests say so, instead of passing against a shape
 * that no longer exists.
 */

import {
  matchupSimulationSchema,
  projectionSchema,
  rankedProjectionSchema,
  type MatchupSimulation,
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

/**
 * A finished simulation: two seven-player lineups, your team a 59% favourite.
 *
 * The position totals are round on purpose (QB 20.3 v 19.3, RB 52.5 v 35.5,
 * WR 32.7 v 44.8, TE 10.9 v 9.7), so a test can state a gap without a
 * calculator, and they add up to the two expected scores.
 */
export function makeSimulation(
  options: { win?: number; tie?: number; mode?: string } = {},
): MatchupSimulation {
  const { win = 0.5899, tie = 0.0001, mode = 'independent' } = options
  const player = (id: string, slot: string, position: string, mean: number) => ({
    provenance: 'model',
    player_id: id,
    name: id,
    slot,
    position,
    team: 'DET',
    game_id: '2026_04_DET_CAR',
    expected_points: mean - 0.2,
    floor: mean - 8,
    ceiling: mean + 12,
    simulated_mean: mean,
  })

  return matchupSimulationSchema.parse({
    season: 2026,
    week: 4,
    scoring_profile: 'half_ppr',
    simulation: {
      provenance: 'derived',
      iterations: 10000,
      seed: 7,
      sampling_method: 'inverse_transform',
      correlation_mode: mode,
      lineup_format: 'standard_skill',
    },
    team_a: {
      provenance: 'derived',
      expected_score: 116.4,
      median_score: 115.3,
      p10: 88.9,
      p25: 101,
      p75: 130,
      p90: 145.5,
      win_probability: win,
      loss_probability: 1 - win - tie,
      tie_probability: tie,
      projection_sum: 114.7,
      players: [
        player('a-qb', 'QB', 'QB', 20.3),
        player('a-rb1', 'RB', 'RB', 19.5),
        player('a-rb2', 'RB', 'RB', 17.5),
        player('a-wr1', 'WR', 'WR', 17.2),
        player('a-wr2', 'WR', 'WR', 15.5),
        player('a-te', 'TE', 'TE', 10.9),
        player('a-flex', 'FLEX', 'RB', 15.5),
      ],
    },
    team_b: {
      provenance: 'derived',
      expected_score: 109.3,
      median_score: 108.1,
      p10: 83,
      p25: 95,
      p75: 122,
      p90: 137.6,
      win_probability: 1 - win - tie,
      loss_probability: win,
      tie_probability: tie,
      projection_sum: 107.8,
      players: [
        player('b-qb', 'QB', 'QB', 19.3),
        player('b-rb1', 'RB', 'RB', 18.5),
        player('b-rb2', 'RB', 'RB', 17),
        player('b-wr1', 'WR', 'WR', 16),
        player('b-wr2', 'WR', 'WR', 14.7),
        player('b-te', 'TE', 'TE', 9.7),
        player('b-flex', 'FLEX', 'WR', 14.1),
      ],
    },
    score_differential: 7.1,
    median_differential: 7.2,
    assumptions: {
      provenance: 'derived',
      player_independence: mode === 'independent',
      correlation_mode: mode,
      kicker_projection_available: false,
      defense_projection_available: false,
      injury_adjustment_applied: false,
      matchup_adjustment_applied: false,
      weather_adjustment_applied: false,
      notes: [],
    },
  })
}
