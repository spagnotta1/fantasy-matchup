/**
 * Wire contracts, mirrored from `nflfp.api.schemas`.
 *
 * These are validators, not a second source of truth. The backend owns every
 * number in here; the job of this module is to fail loudly at the boundary when
 * a response is not the shape we compiled against, rather than to let an
 * `undefined` travel three components deep and surface as `NaN` on a projection
 * card.
 *
 * Two conventions, both taken from the API:
 *
 * - Almost every field is nullable. A null is a *state* in this API — an
 *   ungraded matchup, an unpublished week, a player on bye — and never an
 *   error. Optional-and-nullable is therefore the default, and the components
 *   that consume these types are expected to branch.
 * - `provenance` is carried on every block. It is not decoration: it says
 *   whether a number came from the model, was derived above it, or is context
 *   the model never consumed. The UI is required to keep those apart.
 */

import { z } from 'zod'

/** Nullable-and-optional, which is the API's default posture. */
const maybeNumber = z.number().nullish()
const maybeString = z.string().nullish()
const maybeBool = z.boolean().nullish()

export const provenanceSchema = z.enum(['model', 'derived', 'context', 'actual'])
export type Provenance = z.infer<typeof provenanceSchema>

// ---------------------------------------------------------------------------
// Envelope
// ---------------------------------------------------------------------------

export const slateWindowSchema = z.object({
  season: z.number(),
  week: z.number(),
  /** 'explicit' | 'upcoming' | 'latest_completed' — how the week was resolved. */
  resolution: z.string(),
  is_upcoming: z.boolean(),
})
export type SlateWindow = z.infer<typeof slateWindowSchema>

export const pageSchema = z.object({
  total: z.number(),
  limit: z.number(),
  offset: z.number(),
  returned: z.number(),
})
export type Page = z.infer<typeof pageSchema>

export const modelRefSchema = z.object({
  run_id: z.number(),
  model_name: z.string(),
  model_version: z.string(),
  algorithm: z.string(),
  feature_schema_version: z.number(),
  published_at: maybeString,
  code_sha: maybeString,
})
export type ModelRef = z.infer<typeof modelRefSchema>

export const metaSchema = z.object({
  window: slateWindowSchema.nullish(),
  scoring_profile: maybeString,
  page: pageSchema.nullish(),
  /** Null means nothing is published for the week. A flag, not an error. */
  model: modelRefSchema.nullish(),
  notices: z.array(z.string()).default([]),
})
export type ResponseMeta = z.infer<typeof metaSchema>

/** `{ data, meta }` — the shape of every response the API produces. */
export function envelope<T extends z.ZodTypeAny>(data: T) {
  return z.object({ data, meta: metaSchema.default({ notices: [] }) })
}

export type Envelope<T> = { data: T; meta: ResponseMeta }

export const errorBodySchema = z.object({
  code: z.string(),
  message: z.string(),
  field: maybeString,
  /** Operator action that fixes a recoverable state. Shown to operators only. */
  remedy: maybeString,
})
export type ErrorBody = z.infer<typeof errorBodySchema>

// ---------------------------------------------------------------------------
// Identity
// ---------------------------------------------------------------------------

export const playerSchema = z.object({
  player_id: z.string(),
  name: z.string(),
  position: maybeString,
  team: maybeString,
  jersey_number: z.number().nullish(),
  status: maybeString,
  headshot_url: maybeString,
  years_of_experience: z.number().nullish(),
  college: maybeString,
})
export type Player = z.infer<typeof playerSchema>

export const teamSchema = z.object({
  abbr: z.string(),
  name: maybeString,
  nickname: maybeString,
  conference: maybeString,
  division: maybeString,
  primary_color: maybeString,
  secondary_color: maybeString,
  logo_url: maybeString,
})
export type Team = z.infer<typeof teamSchema>

/**
 * A season the deployment has actually published, with its weeks.
 *
 * `/seasons` answers availability rather than history, so a selector built from
 * this can never offer a season whose every screen would be empty. The weeks
 * ride along, which is why the shell needs one request rather than one per
 * season to resolve which slate to open on.
 */
export const seasonSchema = z.object({
  season: z.number(),
  /** Ascending, never empty. */
  published_weeks: z.array(z.number()),
  latest_published_week: z.number(),
})
export type Season = z.infer<typeof seasonSchema>

// ---------------------------------------------------------------------------
// provenance: model
// ---------------------------------------------------------------------------

export const pointsSchema = z.object({
  /**
   * The calibrated mean, and the documented headline. It is null on runs
   * written before the distribution layer existed — see `headlinePoints`,
   * which applies the backend's own fallback rather than inventing one.
   */
  expected: maybeNumber,
  /** Raw model output. Conditionally biased by construction; never display it. */
  predicted: z.number(),
  floor: maybeNumber,
  p25: maybeNumber,
  median: maybeNumber,
  p75: maybeNumber,
  ceiling: maybeNumber,
  standard_deviation: maybeNumber,
  /** 0-1: how much information the model had, not how good the player is. */
  confidence: maybeNumber,
  confidence_label: z.string(),
  boom_probability: maybeNumber,
  bust_probability: maybeNumber,
  boom_threshold: maybeNumber,
  bust_threshold: maybeNumber,
  shape: z.string(),
  extrapolated: z.boolean(),
  samples: z.number().nullish(),
  calibration_method: maybeString,
})
export type Points = z.infer<typeof pointsSchema>

export const componentsSchema = z.object({
  targets: maybeNumber,
  receptions: maybeNumber,
  carries: maybeNumber,
  pass_attempts: maybeNumber,
  passing_yards: maybeNumber,
  passing_tds: maybeNumber,
  interceptions: maybeNumber,
  rushing_yards: maybeNumber,
  rushing_tds: maybeNumber,
  receiving_yards: maybeNumber,
  receiving_tds: maybeNumber,
})
export type Components = z.infer<typeof componentsSchema>

export const predictionSchema = z.object({
  provenance: provenanceSchema,
  scoring_profile: z.string(),
  points: pointsSchema,
  components: componentsSchema,
  model: modelRefSchema.nullish(),
})
export type Prediction = z.infer<typeof predictionSchema>

// ---------------------------------------------------------------------------
// provenance: derived
// ---------------------------------------------------------------------------

export const matchupGradeSchema = z.object({
  /** Branch on this. False means render "not enough data", never a neutral C. */
  graded: z.boolean(),
  score: maybeNumber,
  letter: maybeString,
  defense_rank: z.number().nullish(),
  sample_games: z.number().nullish(),
  reason: maybeString,
})
export type MatchupGrade = z.infer<typeof matchupGradeSchema>

export const matchupSchema = z.object({
  provenance: provenanceSchema,
  source: z.string(),
  applied_to_projection: z.boolean(),
  opponent: maybeString,
  is_home: maybeBool,
  grade: matchupGradeSchema,
  fp_allowed_vs_position_l4: maybeNumber,
  targets_allowed_l4: maybeNumber,
  carries_allowed_l4: maybeNumber,
  defense_rank_overall: z.number().nullish(),
  opponent_pace_l4: maybeNumber,
})
export type Matchup = z.infer<typeof matchupSchema>

export const usageSchema = z.object({
  provenance: provenanceSchema,
  snap_pct_l4: maybeNumber,
  target_share_l4: maybeNumber,
  targets_l4: maybeNumber,
  carries_l4: maybeNumber,
  receptions_l4: maybeNumber,
  opportunities_l4: maybeNumber,
  air_yards_share_l4: maybeNumber,
  wopr_l4: maybeNumber,
  snap_pct_trend: maybeNumber,
  target_share_trend: maybeNumber,
  snap_pct_season: maybeNumber,
  games_played_season: z.number().nullish(),
  games_in_window: z.number().nullish(),
  fp_l4: maybeNumber,
  fp_season: maybeNumber,
  fp_volatility_l4: maybeNumber,
})
export type Usage = z.infer<typeof usageSchema>

// ---------------------------------------------------------------------------
// provenance: context
// ---------------------------------------------------------------------------

const contextBlock = {
  provenance: provenanceSchema,
  /** The field that matters: false means the projection does NOT account for this. */
  applied_to_projection: z.boolean(),
  unapplied_reason: maybeString,
  multiplier: maybeNumber,
}

export const gameContextSchema = z.object({
  ...contextBlock,
  multiplier: maybeNumber.optional(),
  game_id: maybeString,
  season: z.number(),
  week: z.number(),
  team: maybeString,
  opponent: maybeString,
  is_home: maybeBool,
  gameday: maybeString,
  team_spread: maybeNumber,
  total_line: maybeNumber,
  implied_team_total: maybeNumber,
  implied_opponent_total: maybeNumber,
  spread_movement: maybeNumber,
  spread_source: maybeString,
  odds_book: maybeString,
  odds_captured_at: maybeString,
  rest_days: z.number().nullish(),
  rest_advantage: z.number().nullish(),
  divisional: maybeBool,
})
export type GameContext = z.infer<typeof gameContextSchema>

export const weatherSchema = z.object({
  ...contextBlock,
  is_indoor: maybeBool,
  temperature_f: maybeNumber,
  wind_mph: maybeNumber,
  wind_gust_mph: maybeNumber,
  precipitation_probability: maybeNumber,
  snowfall_in: maybeNumber,
  roof_uncertain: z.boolean().default(false),
  source: maybeString,
  captured_at: maybeString,
  /** A conditions flag for the UI, not a projection adjustment. */
  is_adverse: z.boolean(),
})
export type Weather = z.infer<typeof weatherSchema>

export const injurySchema = z.object({
  ...contextBlock,
  report_status: maybeString,
  practice_status: maybeString,
  detail: maybeString,
  will_not_play: z.boolean(),
  is_questionable_or_worse: z.boolean(),
})
export type Injury = z.infer<typeof injurySchema>

export const contextSchema = z.object({
  provenance: provenanceSchema,
  game: gameContextSchema.nullish(),
  weather: weatherSchema.nullish(),
  injury: injurySchema.nullish(),
})
export type PlayerContext = z.infer<typeof contextSchema>

// ---------------------------------------------------------------------------
// The projection
// ---------------------------------------------------------------------------

export const projectionSchema = z.object({
  player: playerSchema,
  season: z.number(),
  week: z.number(),
  team: maybeString,
  opponent: maybeString,
  is_home: maybeBool,
  game_id: maybeString,
  prediction: predictionSchema,
  usage: usageSchema,
  matchup: matchupSchema.nullish(),
  context: contextSchema,
})
export type Projection = z.infer<typeof projectionSchema>

export const rankedProjectionSchema = z.object({
  rank: z.number(),
  positional_rank: z.number(),
  /** Adjacent players share a tier while the lower can still outscore the higher. */
  tier: z.number(),
  projection: projectionSchema,
})
export type RankedProjection = z.infer<typeof rankedProjectionSchema>

// ---------------------------------------------------------------------------
// History
// ---------------------------------------------------------------------------

export const historicalWeekSchema = z.object({
  provenance: provenanceSchema,
  season: z.number(),
  week: z.number(),
  team: maybeString,
  opponent: maybeString,
  is_home: maybeBool,
  actual_points: maybeNumber,
  projected_points: maybeNumber,
  error: maybeNumber,
  snap_pct: maybeNumber,
  targets: maybeNumber,
  carries: maybeNumber,
  receptions: maybeNumber,
  receiving_yards: maybeNumber,
  rushing_yards: maybeNumber,
  passing_yards: maybeNumber,
  total_tds: maybeNumber,
  injury_report_status: maybeString,
})
export type HistoricalWeek = z.infer<typeof historicalWeekSchema>

export const trendSchema = z.object({
  games: z.number(),
  mean_points: maybeNumber,
  median_points: maybeNumber,
  standard_deviation: maybeNumber,
  boom_rate: maybeNumber,
  bust_rate: maybeNumber,
  mean_absolute_error: maybeNumber,
  bias: maybeNumber,
  /** Accuracy figures cover only these weeks. */
  graded_games: z.number(),
})
export type Trend = z.infer<typeof trendSchema>

export const playerProfileSchema = z.object({
  player: playerSchema,
  scoring_profile: z.string(),
  current: projectionSchema.nullish(),
  history: z.array(historicalWeekSchema),
  trend: trendSchema,
})
export type PlayerProfile = z.infer<typeof playerProfileSchema>

// ---------------------------------------------------------------------------
// Advice
// ---------------------------------------------------------------------------

export const comparisonEntrySchema = z.object({
  projection: projectionSchema,
  expected: maybeNumber,
  floor: maybeNumber,
  ceiling: maybeNumber,
  win_probability: maybeNumber,
})
export type ComparisonEntry = z.infer<typeof comparisonEntrySchema>

export const startSitSchema = z.object({
  a: comparisonEntrySchema,
  b: comparisonEntrySchema,
  win_probability: z.number(),
  expected_margin: z.number(),
  /** 'clear' | 'lean' | 'toss_up'. A toss-up is a real answer. */
  verdict: z.string(),
  /** Null for a toss-up. Do not paper over it. */
  recommended: maybeString,
  rationale: z.array(z.string()),
  caveats: z.array(z.string()),
})
export type StartSit = z.infer<typeof startSitSchema>

export const comparisonSchema = z.object({
  season: z.number(),
  week: z.number(),
  scoring_profile: z.string(),
  entries: z.array(comparisonEntrySchema),
  head_to_head: z.array(startSitSchema),
})
export type Comparison = z.infer<typeof comparisonSchema>

// ---------------------------------------------------------------------------
// Matchups and teams
// ---------------------------------------------------------------------------

export const positionMatchupSchema = z.object({
  provenance: provenanceSchema,
  position: z.string(),
  grade: matchupGradeSchema,
  fp_allowed_l4: maybeNumber,
  targets_allowed_l4: maybeNumber,
  carries_allowed_l4: maybeNumber,
  yards_allowed_l4: maybeNumber,
})
export type PositionMatchup = z.infer<typeof positionMatchupSchema>

export const matchupAnalysisSchema = z.object({
  game_id: maybeString,
  season: z.number(),
  week: z.number(),
  home: teamSchema,
  away: teamSchema,
  context: contextSchema,
  /** Keyed by *defending* team abbreviation. */
  defense: z.record(z.string(), z.array(positionMatchupSchema)),
  top_projections: z.array(rankedProjectionSchema),
})
export type MatchupAnalysis = z.infer<typeof matchupAnalysisSchema>

export const gameSchema = z.object({
  game_id: z.string(),
  season: z.number(),
  week: z.number(),
  gameday: maybeString,
  home_team: z.string(),
  away_team: z.string(),
  home_score: z.number().nullish(),
  away_score: z.number().nullish(),
  home_spread: maybeNumber,
  total_line: maybeNumber,
  is_upcoming: z.boolean(),
})
export type Game = z.infer<typeof gameSchema>

export const weekSchema = z.object({
  season: z.number(),
  week: z.number(),
  games: z.array(gameSchema),
  game_count: z.number(),
  completed_games: z.number(),
  upcoming_games: z.number(),
  /** The flag to branch on before rendering an empty board as an error. */
  projections_published: z.boolean(),
  projection_count: z.number(),
  model: modelRefSchema.nullish(),
})
export type Week = z.infer<typeof weekSchema>

export const teamOutlookSchema = z.object({
  team: teamSchema,
  season: z.number(),
  week: z.number(),
  scoring_profile: z.string(),
  context: contextSchema,
  players: z.array(rankedProjectionSchema),
  /** NOT a projected team score: skill positions only, in fantasy points. */
  projected_points: maybeNumber,
})
export type TeamOutlook = z.infer<typeof teamOutlookSchema>

// ---------------------------------------------------------------------------
// Simulation
// ---------------------------------------------------------------------------

export const simulatedPlayerSchema = z.object({
  provenance: provenanceSchema,
  player_id: z.string(),
  name: z.string(),
  slot: z.string(),
  position: maybeString,
  team: maybeString,
  game_id: maybeString,
  expected_points: maybeNumber,
  floor: maybeNumber,
  ceiling: maybeNumber,
  simulated_mean: z.number(),
})
export type SimulatedPlayer = z.infer<typeof simulatedPlayerSchema>

export const teamSimulationSchema = z.object({
  provenance: provenanceSchema,
  expected_score: z.number(),
  median_score: z.number(),
  p10: z.number(),
  p25: z.number(),
  p75: z.number(),
  p90: z.number(),
  win_probability: z.number(),
  loss_probability: z.number(),
  tie_probability: z.number(),
  projection_sum: z.number(),
  players: z.array(simulatedPlayerSchema),
})
export type TeamSimulation = z.infer<typeof teamSimulationSchema>

export const simulationRunSchema = z.object({
  provenance: provenanceSchema,
  iterations: z.number(),
  seed: z.number(),
  sampling_method: z.string(),
  correlation_mode: z.string(),
  correlation_model_version: maybeString,
  lineup_format: z.string(),
  model: modelRefSchema.nullish(),
})
export type SimulationRun = z.infer<typeof simulationRunSchema>

export const simulationAssumptionsSchema = z.object({
  provenance: provenanceSchema,
  /** True is the single largest known error in the result. Surface it. */
  player_independence: z.boolean(),
  correlation_mode: z.string(),
  correlation_model_version: maybeString,
  kicker_projection_available: z.boolean(),
  defense_projection_available: z.boolean(),
  injury_adjustment_applied: z.boolean(),
  matchup_adjustment_applied: z.boolean(),
  weather_adjustment_applied: z.boolean(),
  notes: z.array(z.string()),
})
export type SimulationAssumptions = z.infer<typeof simulationAssumptionsSchema>

export const matchupSimulationSchema = z.object({
  season: z.number(),
  week: z.number(),
  scoring_profile: z.string(),
  simulation: simulationRunSchema,
  team_a: teamSimulationSchema,
  team_b: teamSimulationSchema,
  score_differential: z.number(),
  median_differential: z.number(),
  assumptions: simulationAssumptionsSchema,
})
export type MatchupSimulation = z.infer<typeof matchupSimulationSchema>

export interface LineupEntry {
  player_id: string
  slot: string
}

export interface SimulationRequest {
  season?: number | null
  week?: number | null
  scoring_profile?: string | null
  simulation_count?: number
  seed?: number | null
  correlation_mode?: string
  team_a: LineupEntry[]
  team_b: LineupEntry[]
}

// ---------------------------------------------------------------------------
// Meta
// ---------------------------------------------------------------------------

export const lineupSlotSchema = z.object({
  slot: z.string(),
  label: z.string(),
  eligible_positions: z.array(z.string()),
  /** False slots are recognised and refused with a reason — K and DST today. */
  supported: z.boolean(),
  unsupported_positions: z.array(z.string()).default([]),
  description: z.string().default(''),
})
export type LineupSlot = z.infer<typeof lineupSlotSchema>

export const positionSupportSchema = z.object({
  position: z.string(),
  label: z.string(),
  /** 'projected' | 'planned'. Build position filters from this, not a constant. */
  status: z.string(),
  projected: z.boolean(),
  reason: maybeString,
  blocked_on: z.array(z.string()).default([]),
})
export type PositionSupport = z.infer<typeof positionSupportSchema>

export const healthSchema = z.object({
  status: z.string(),
  environment: z.string(),
  version: z.string(),
  database: maybeBool,
  cache: maybeString,
  checks: z.record(z.string(), z.string()).default({}),
})
export type Health = z.infer<typeof healthSchema>

export const cacheRuleSchema = z.object({
  prefix: z.string(),
  ttl_seconds: z.number(),
  cached: z.boolean(),
  reason: z.string(),
})
export type CacheRule = z.infer<typeof cacheRuleSchema>

export const provenanceLegendSchema = z.record(z.string(), z.string())
export type ProvenanceLegend = z.infer<typeof provenanceLegendSchema>
