"""Wire format. Pydantic lives here and nowhere below it.

The business layer returns frozen dataclasses; this module turns them into
response models. The extra hop buys two things worth more than the code it
costs: the service layer stays usable from a worker or a notebook, and the wire
format can be renamed, versioned or reshaped for a frontend without any of that
reaching the football.

The response shape follows :mod:`nflfp.api.provenance`. A projection is not a
flat bag of numbers — it is three labelled blocks:

``prediction``  what the frozen model produced
``matchup``     what was derived above the model
``context``     what was observed but not used

A client that wants "the number" reads ``prediction.points.expected``. A client
that wants to be honest with its users renders the other two beside it with
their labels intact.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from ..services import dto
from ..services.grading import MatchupGrade
from .provenance import Provenance

T = TypeVar("T")


class Schema(BaseModel):
    """Base for every response model.

    ``from_attributes`` so a dataclass can be validated directly where the
    field names already line up, and ``populate_by_name`` so an alias can be
    introduced later without breaking existing clients.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


class SlateWindowOut(Schema):
    """Which season and week a request resolved to, and how."""

    season: int
    week: int
    resolution: str = Field(
        description=(
            "'explicit' when the caller named a week; 'upcoming' when it "
            "defaulted to the next unplayed week; 'latest_completed' once the "
            "season is over."
        )
    )
    is_upcoming: bool


class PageOut(Schema):
    """Pagination metadata."""

    total: int = Field(description="Matching rows before limit/offset.")
    limit: int
    offset: int
    returned: int


class MetaOut(Schema):
    """Everything about a response that is not the answer itself."""

    window: SlateWindowOut | None = None
    scoring_profile: str | None = None
    page: PageOut | None = None
    model: "ModelRefOut | None" = Field(
        default=None,
        description=(
            "The published run behind every model-provenance number in this "
            "response. Null means nothing is published for the week — the "
            "flag to branch on, distinct from an error."
        ),
    )
    notices: list[str] = Field(
        default_factory=list,
        description=(
            "Non-fatal things a client should surface: an unpublished week, a "
            "matchup that could not be graded, a correlation caveat."
        ),
    )


class Envelope(Schema, Generic[T]):
    """Uniform response wrapper.

    Every endpoint returns ``{"data": ..., "meta": ...}``. A client writes one
    unwrap and one error handler, and adding pagination or a notice to an
    endpoint later is not a breaking change.
    """

    data: T
    meta: MetaOut = Field(default_factory=MetaOut)


class ErrorOut(Schema):
    """Error body. One shape for every failure the API produces."""

    code: str = Field(description="Stable machine-readable code, e.g. 'not_found'.")
    message: str
    field: str | None = Field(
        default=None, description="Request field at fault, when there is one."
    )
    remedy: str | None = Field(
        default=None,
        description="Operator action that fixes this, for recoverable states.",
    )


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


class PlayerOut(Schema):
    player_id: str
    name: str
    position: str | None = None
    team: str | None = None
    jersey_number: int | None = None
    status: str | None = None
    headshot_url: str | None = None
    years_of_experience: int | None = None
    college: str | None = None


class TeamOut(Schema):
    abbr: str
    name: str | None = None
    nickname: str | None = None
    conference: str | None = None
    division: str | None = None
    primary_color: str | None = None
    secondary_color: str | None = None
    logo_url: str | None = None


class SeasonOut(Schema):
    """A season that has something to show, and the weeks it has it for.

    Build a season picker from this. It lists what is *published*, not what the
    warehouse holds — those differ by about twenty-five seasons on a normal
    install, and every one of the difference is a selection that produces an
    empty screen.
    """

    season: int
    published_weeks: list[int] = Field(
        description="Weeks of this season with a published run, ascending. Never empty."
    )
    latest_published_week: int = Field(
        description="The newest published week — what a picker should open on."
    )


class ModelRefOut(Schema):
    """Lineage. Travels with every projection, deliberately."""

    run_id: int
    model_name: str
    model_version: str
    algorithm: str
    feature_schema_version: int
    published_at: datetime | None = None
    code_sha: str | None = None


# ---------------------------------------------------------------------------
# provenance: model
# ---------------------------------------------------------------------------


class PointsOut(Schema):
    """The projected fantasy-point distribution.

    ``expected`` is the headline. ``predicted`` is the model's raw output, kept
    for lineage; it is conditionally biased by construction because shrinkage
    trades bias for variance, and a client should not display it as the number.
    """

    expected: float | None = Field(description="Calibrated mean. Use this one.")
    predicted: float = Field(
        description="Raw model output, before distribution calibration. Lineage only."
    )
    floor: float | None = Field(default=None, description="P10")
    p25: float | None = None
    median: float | None = Field(default=None, description="P50")
    p75: float | None = None
    ceiling: float | None = Field(default=None, description="P90")
    standard_deviation: float | None = None
    confidence: float | None = Field(
        default=None,
        description=(
            "0-1. How much information the model had — not how good the "
            "projection is. A confidently-projected bad player is still bad."
        ),
    )
    confidence_label: str = Field(description="high | moderate | low | very_low | unknown")
    boom_probability: float | None = None
    bust_probability: float | None = None
    boom_threshold: float | None = None
    bust_threshold: float | None = None
    shape: str = Field(description="steady | volatile | unknown")
    extrapolated: bool = Field(
        description=(
            "True when the projection exceeded anything seen while fitting the "
            "residual distribution, so its interval is an extrapolation."
        )
    )
    samples: int | None = Field(
        default=None,
        description=(
            "Held-out residuals behind this distribution. A wide interval from "
            "40 observations is not the same claim as one from 4,000."
        ),
    )
    calibration_method: str | None = None


class ComponentsOut(Schema):
    """Projected opportunity and production, before scoring rules apply.

    What the model actually predicts. "8.4 targets" is explainable in a way
    "14.2 points" is not, and it is why one model serves every league format.
    """

    targets: float | None = None
    receptions: float | None = None
    carries: float | None = None
    pass_attempts: float | None = None
    passing_yards: float | None = None
    passing_tds: float | None = None
    interceptions: float | None = None
    rushing_yards: float | None = None
    rushing_tds: float | None = None
    receiving_yards: float | None = None
    receiving_tds: float | None = None


class PredictionOut(Schema):
    """Everything the frozen model produced. Provenance: ``model``."""

    provenance: Provenance = Provenance.MODEL
    scoring_profile: str
    points: PointsOut
    components: ComponentsOut
    model: ModelRefOut | None = None


# ---------------------------------------------------------------------------
# provenance: derived
# ---------------------------------------------------------------------------


class MatchupGradeOut(Schema):
    """A defensive matchup as a percentile, a letter, and a caveat.

    ``graded`` is the field to branch on. When it is false the letter and score
    are null and ``reason`` says why — render "not enough data", never a
    neutral C.
    """

    graded: bool
    score: float | None = Field(
        default=None, description="0-100 percentile. 100 = softest matchup."
    )
    letter: str | None = None
    defense_rank: int | None = Field(
        default=None, description="1-32 against this position. 1 = toughest."
    )
    sample_games: int | None = None
    reason: str | None = None


class MatchupOut(Schema):
    """Opponent strength, computed above the model. Provenance: ``derived``.

    The grade is a **rank percentile**: about 2.5 defences hold each letter
    every week, so an "A" means "top few matchups this week" and not
    "unusually good in absolute terms". ``fp_allowed_vs_position_l4`` carries
    the magnitude claim, in points. Either alone misleads.
    """

    provenance: Provenance = Provenance.DERIVED
    source: str = Field(
        default="feat_defense_position",
        description=(
            "Trailing four completed games before this week, ranked within "
            "position. Never includes the week being projected."
        ),
    )
    applied_to_projection: bool = Field(
        default=False,
        description=(
            "False under the frozen foundation: the model does not consume a "
            "matchup feature. This is analysis presented beside the "
            "projection, not an adjustment to it."
        ),
    )
    opponent: str | None = None
    is_home: bool | None = None
    grade: MatchupGradeOut
    fp_allowed_vs_position_l4: float | None = None
    targets_allowed_l4: float | None = None
    carries_allowed_l4: float | None = None
    defense_rank_overall: int | None = None
    opponent_pace_l4: float | None = None


class UsageOut(Schema):
    """Trailing four-game workload. Provenance: ``derived``.

    Every window ends at the *previous* week. These are the model's inputs
    restated for a reader, not this week's snap count — which does not exist
    yet on a Thursday.
    """

    provenance: Provenance = Provenance.DERIVED
    snap_pct_l4: float | None = None
    target_share_l4: float | None = None
    targets_l4: float | None = None
    carries_l4: float | None = None
    receptions_l4: float | None = None
    opportunities_l4: float | None = None
    air_yards_share_l4: float | None = None
    wopr_l4: float | None = None
    snap_pct_trend: float | None = None
    target_share_trend: float | None = None
    snap_pct_season: float | None = None
    games_played_season: int | None = None
    games_in_window: int | None = None
    fp_l4: float | None = None
    fp_season: float | None = None
    fp_volatility_l4: float | None = None


# ---------------------------------------------------------------------------
# provenance: context
# ---------------------------------------------------------------------------


class ContextBlock(Schema):
    """Base for observed facts the model may or may not consume.

    ``applied_to_projection`` is the field that matters. It is ``False``
    throughout under the frozen foundation, and it becomes ``True`` on its own
    the moment the engine writes a corresponding multiplier — the same field a
    client is already rendering starts meaning something different, with no
    schema change on either side.
    """

    provenance: Provenance = Provenance.CONTEXT
    applied_to_projection: bool
    unapplied_reason: str | None = Field(
        default=None,
        description="Why this is not an input to the projection. Null once it is.",
    )
    multiplier: float | None = Field(
        default=None,
        description=(
            "The adjustment the engine applied, when it applied one. Null "
            "under the frozen foundation."
        ),
    )


class GameContextOut(ContextBlock):
    """Schedule and betting market. Provenance: ``context``."""

    multiplier: float | None = Field(default=None, exclude=True)
    game_id: str | None = None
    season: int
    week: int
    team: str | None = None
    opponent: str | None = None
    is_home: bool | None = None
    gameday: date | None = None
    team_spread: float | None = Field(
        default=None, description="Points this team is favoured by (sign-normalised)."
    )
    total_line: float | None = None
    implied_team_total: float | None = None
    implied_opponent_total: float | None = None
    spread_movement: float | None = None
    spread_source: str | None = Field(
        default=None,
        description=(
            "'market' for a live capture, 'nflverse_close' for a settled "
            "closing line. Different objects; do not average them."
        ),
    )
    odds_book: str | None = None
    odds_captured_at: datetime | None = None
    rest_days: int | None = None
    rest_advantage: int | None = None
    divisional: bool | None = None


class WeatherOut(ContextBlock):
    """Forecast conditions. Provenance: ``context``."""

    is_indoor: bool | None = None
    temperature_f: float | None = None
    wind_mph: float | None = None
    wind_gust_mph: float | None = None
    precipitation_probability: float | None = None
    snowfall_in: float | None = None
    roof_uncertain: bool = False
    source: str | None = Field(
        default=None, description="'forecast' | 'nflverse_observed' | 'none'"
    )
    captured_at: datetime | None = None
    is_adverse: bool = Field(
        description=(
            "A conditions flag for the UI, not a projection adjustment. True "
            "at 20+ mph wind or 60%+ precipitation probability, outdoors."
        )
    )


class InjuryOut(ContextBlock):
    """Official injury report. Provenance: ``context``.

    A designation of Out means the projection describes a player who will not
    take the field. It is reported rather than applied, because zeroing the
    number here would destroy the distinction between "projected zero" and
    "not playing".
    """

    report_status: str | None = None
    practice_status: str | None = None
    detail: str | None = None
    will_not_play: bool
    is_questionable_or_worse: bool


class ContextOut(Schema):
    """Everything observed but not consumed by the frozen model."""

    provenance: Provenance = Provenance.CONTEXT
    game: GameContextOut | None = None
    weather: WeatherOut | None = None
    injury: InjuryOut | None = None


# ---------------------------------------------------------------------------
# The projection
# ---------------------------------------------------------------------------


class ProjectionOut(Schema):
    """One player-week, with its three kinds of number kept apart."""

    player: PlayerOut
    season: int
    week: int
    team: str | None = None
    opponent: str | None = None
    is_home: bool | None = None
    game_id: str | None = None

    prediction: PredictionOut
    usage: UsageOut
    matchup: MatchupOut | None = None
    context: ContextOut


class RankedProjectionOut(Schema):
    """A projection with its place on a board.

    ``tier`` is derived from the distributions: adjacent players share a tier
    while the lower still has a realistic chance of outscoring the higher. A
    rank of 14 versus 15 is usually noise; a tier boundary between them is a
    decision point.
    """

    rank: int
    positional_rank: int
    tier: int
    projection: ProjectionOut


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


class HistoricalWeekOut(Schema):
    """A completed week. Provenance: ``actual`` for the outcome."""

    provenance: Provenance = Provenance.ACTUAL
    season: int
    week: int
    team: str | None = None
    opponent: str | None = None
    is_home: bool | None = None
    actual_points: float | None = None
    projected_points: float | None = Field(
        default=None,
        description=(
            "What was stored for this week at the time, not a regeneration. "
            "Null when no published run covered it."
        ),
    )
    error: float | None = Field(default=None, description="projected - actual")
    snap_pct: float | None = None
    targets: float | None = None
    carries: float | None = None
    receptions: float | None = None
    receiving_yards: float | None = None
    rushing_yards: float | None = None
    passing_yards: float | None = None
    total_tds: float | None = None
    injury_report_status: str | None = None


class TrendOut(Schema):
    """Form and per-player accuracy over recent weeks."""

    games: int
    mean_points: float | None = None
    median_points: float | None = None
    standard_deviation: float | None = None
    boom_rate: float | None = None
    bust_rate: float | None = None
    mean_absolute_error: float | None = None
    bias: float | None = None
    graded_games: int = Field(
        description=(
            "Weeks that carried a stored projection. Accuracy figures cover "
            "only these; averaging error over ungraded weeks would report a "
            "better model than exists."
        )
    )


class PlayerProfileOut(Schema):
    player: PlayerOut
    scoring_profile: str
    current: ProjectionOut | None = Field(
        default=None,
        description=(
            "Null is normal: a bye week, or a run not yet published. The "
            "profile still renders."
        ),
    )
    history: list[HistoricalWeekOut]
    trend: TrendOut


# ---------------------------------------------------------------------------
# Advice
# ---------------------------------------------------------------------------


class ComparisonEntryOut(Schema):
    projection: ProjectionOut
    expected: float | None = None
    floor: float | None = None
    ceiling: float | None = None
    win_probability: float | None = None


class StartSitOut(Schema):
    """A head-to-head call, or an explicit refusal to make one.

    ``verdict`` is ``clear``, ``lean`` or ``toss_up``, and ``recommended`` is
    null for a toss-up. That is a real answer: stating a preference between two
    players separated by less than the model's own error would be false
    precision.
    """

    a: ComparisonEntryOut
    b: ComparisonEntryOut
    win_probability: float = Field(
        description=(
            "P(a outscores b), integrated over both stored distributions under "
            "an independence assumption. See caveats for when that assumption "
            "does not hold."
        )
    )
    expected_margin: float
    verdict: str
    recommended: str | None = Field(
        default=None, description="player_id, or null for a toss-up."
    )
    rationale: list[str]
    caveats: list[str] = Field(
        description=(
            "Availability designations, correlation between players sharing a "
            "game, and extrapolated intervals. Surface these."
        )
    )


class ComparisonOut(Schema):
    season: int
    week: int
    scoring_profile: str
    entries: list[ComparisonEntryOut]
    head_to_head: list[StartSitOut]


# ---------------------------------------------------------------------------
# Matchups and teams
# ---------------------------------------------------------------------------


class PositionMatchupOut(Schema):
    """How a defence has handled one position. Provenance: ``derived``."""

    provenance: Provenance = Provenance.DERIVED
    position: str
    grade: MatchupGradeOut
    fp_allowed_l4: float | None = None
    targets_allowed_l4: float | None = None
    carries_allowed_l4: float | None = None
    yards_allowed_l4: float | None = None


class MatchupAnalysisOut(Schema):
    game_id: str | None = None
    season: int
    week: int
    home: TeamOut
    away: TeamOut
    context: ContextOut
    defense: dict[str, list[PositionMatchupOut]] = Field(
        description="Keyed by defending team abbreviation."
    )
    top_projections: list[RankedProjectionOut]


class GameOut(Schema):
    game_id: str
    season: int
    week: int
    gameday: date | None = None
    home_team: str
    away_team: str
    home_score: int | None = None
    away_score: int | None = None
    home_spread: float | None = None
    total_line: float | None = None
    is_upcoming: bool


class WeekOut(Schema):
    """A week's schedule plus whether a board has been generated for it.

    The two counts and the flag exist because an empty projections list is
    ambiguous on its own: a bye-heavy week, an unbuilt warehouse and a
    projection job that has not run all return the same empty array.
    """

    season: int
    week: int
    games: list[GameOut]
    game_count: int
    completed_games: int
    upcoming_games: int
    projections_published: bool = Field(
        description=(
            "Whether a model run is published for this week. The flag to "
            "branch on before rendering an empty board as an error."
        )
    )
    projection_count: int = Field(
        description=(
            "Projections the published run holds. Zero with "
            "`projections_published: true` is a real state — the job "
            "succeeded and produced nothing — and is worth surfacing."
        )
    )
    model: "ModelRefOut | None" = None


class TeamOutlookOut(Schema):
    team: TeamOut
    season: int
    week: int
    scoring_profile: str
    context: ContextOut
    players: list[RankedProjectionOut]
    projected_points: float | None = Field(
        default=None,
        description=(
            "Sum of calibrated expectations for projected skill players. NOT a "
            "projected team score: no kickers, no defensive scoring, and in "
            "fantasy points rather than real ones."
        ),
    )


# ---------------------------------------------------------------------------
# Matchup simulation
# ---------------------------------------------------------------------------


class LineupEntryIn(Schema):
    """One player assigned to one slot."""

    player_id: str = Field(description="gsis id.", min_length=1, max_length=64)
    slot: str = Field(
        description=(
            "QB, RB, WR, TE or FLEX. FLEX accepts RB/WR/TE. K and DST are "
            "recognised and refused with a reason — see /meta/lineup-slots."
        ),
        min_length=1,
        max_length=16,
    )


class SimulationIn(Schema):
    """A matchup simulation request.

    Stateless: nothing here is stored, and the result is returned inline. Both
    lineups must satisfy the same format — a simulation compares two totals, and
    two lineups of different sizes do not produce comparable ones.
    """

    season: int | None = Field(
        default=None,
        ge=1999,
        le=2200,
        description="Defaults to the current league year.",
    )
    week: int | None = Field(
        default=None,
        ge=1,
        le=22,
        description="Defaults to the upcoming slate.",
    )
    scoring_profile: str | None = Field(
        default=None,
        description=(
            "standard, half_ppr, ppr, ppr_te_premium. Defaults to the "
            "configured profile; an unknown value is refused rather than "
            "silently defaulted."
        ),
    )
    simulation_count: int = Field(
        default=10_000,
        ge=100,
        le=50_000,
        description=(
            "Monte Carlo draws. The upper bound is a transport limit, not a "
            "statistical one: the endpoint holds a worker for the whole run, "
            "and a larger simulation belongs in a background job."
        ),
    )
    seed: int | None = Field(
        default=None,
        ge=0,
        le=2**31 - 1,
        description=(
            "Reproducibility seed. Omitting it does **not** randomise the "
            "result — a fixed default is used and echoed back, so a user "
            "refreshing the page does not watch their win probability wander."
        ),
    )
    correlation_mode: str = Field(
        default="independent",
        description=(
            "How player outcomes are drawn.\n\n"
            "`independent` (default, **production**): every player from their "
            "own uniform. Teammates share an offence and opposing players share "
            "game script, so the intervals are too narrow and the win "
            "probability sits further from 50% than the evidence supports.\n\n"
            "`game_environment` (**experimental**): players in the same game "
            "share a fitted game factor and teammates additionally share their "
            "offence's factor. Each player's own distribution is unchanged — "
            "correlation moves the joint distribution, not the marginals. Not "
            "the default, because it has not been shown to outperform the "
            "independent baseline on held-out matchups; see "
            "docs/simulation-readiness.md for exactly what was and was not "
            "measured."
        ),
    )
    team_a: list[LineupEntryIn] = Field(min_length=1, max_length=20)
    team_b: list[LineupEntryIn] = Field(min_length=1, max_length=20)


class SimulatedPlayerOut(Schema):
    """One lineup slot and what it contributed. Provenance: ``model``.

    The point estimates are read from the stored distribution, not produced by
    the simulation. ``simulated_mean`` is the exception and is labelled as such:
    it is the mean of this player's own draws, and its agreement with
    ``expected_points`` is the cheapest check that the sampler drew from the
    distribution it was handed.
    """

    provenance: Provenance = Provenance.MODEL
    player_id: str
    name: str
    slot: str
    position: str | None = None
    team: str | None = None
    game_id: str | None = None
    expected_points: float | None = Field(
        default=None, description="Calibrated mean from the published run."
    )
    floor: float | None = Field(default=None, description="P10")
    ceiling: float | None = Field(default=None, description="P90")
    simulated_mean: float = Field(
        description="Derived: the mean of this player's sampled outcomes."
    )


class TeamSimulationOut(Schema):
    """One team's simulated week. Provenance: ``derived``.

    Every number here is a statistic of the sampled totals — a calculation
    performed **above** the model, not an output of it. That distinction is the
    reason this block is not labelled ``model`` despite consuming model
    predictions exclusively.

    ``projection_sum`` is the one exception and is called out in its own
    description: it is the sum of the stored calibrated means.
    """

    provenance: Provenance = Provenance.DERIVED
    expected_score: float = Field(description="Mean of the simulated team totals.")
    median_score: float = Field(description="P50")
    p10: float
    p25: float
    p75: float
    p90: float
    win_probability: float
    loss_probability: float
    tie_probability: float = Field(
        description=(
            "Totals are rounded to two decimals before comparison, the way a "
            "fantasy platform scores. Reconstructed distributions are "
            "continuous while real scoring is not, so this is a lower bound on "
            "the true tie rate rather than an estimate of it."
        )
    )
    projection_sum: float = Field(
        description=(
            "Model provenance: the sum of the stored calibrated means. Kept "
            "beside expected_score because the two agreeing is the check that "
            "the sampler drew from the stored distributions."
        )
    )
    players: list[SimulatedPlayerOut]


class SimulationRunOut(Schema):
    """How the simulation was run. Provenance: ``derived``."""

    provenance: Provenance = Provenance.DERIVED
    iterations: int
    seed: int = Field(
        description=(
            "Always present, including when the request named none. The same "
            "lineups against the same published run with the same seed produce "
            "the same numbers."
        )
    )
    sampling_method: str = Field(
        description=(
            "How an outcome was drawn. `inverse_transform_from_stored_"
            "percentiles`: u ~ U(0,1), then the stored quantile function at u. "
            "No parametric family is fitted at any point."
        )
    )
    correlation_mode: str = Field(
        description=(
            "`independent` or `game_environment`. The mode that actually ran, "
            "read from the sampler rather than echoed from the request, so a "
            "response can never describe a correlated simulation that was not "
            "one."
        )
    )
    correlation_model_version: str | None = Field(
        default=None,
        description=(
            "Version of the fitted correlation structure, when one was used. "
            "Null under `independent`. With `seed`, `iterations` and `model` "
            "this is the fourth thing needed to reproduce a correlated result."
        ),
    )
    lineup_format: str
    model: ModelRefOut | None = Field(
        default=None,
        description=(
            "The published run the sampled distributions came from. With "
            "`seed` and `iterations` this is what makes a result reproducible "
            "after a model rollout."
        ),
    )


class SimulationAssumptionsOut(Schema):
    """What the engine assumed. Provenance: ``derived``.

    Served as fields rather than prose so a client can render a banner without
    string-matching a caveat, and so the day a kicker model ships
    `kicker_projection_available` flips on its own with no schema change.
    """

    provenance: Provenance = Provenance.DERIVED
    player_independence: bool = Field(
        description=(
            "True: outcomes were drawn independently. The single largest known "
            "error in this result. Teammates share an offence and opposing "
            "players share game script, so the intervals are too narrow and the "
            "win probability is further from 50% than the evidence supports.\n\n"
            "False: a fitted correlation structure was applied. Derived from "
            "`simulation.correlation_mode` rather than stored beside it, so the "
            "flag and the sampler cannot disagree."
        )
    )
    correlation_mode: str = Field(
        description="Mirrors `simulation.correlation_mode`."
    )
    correlation_model_version: str | None = Field(
        default=None,
        description="Mirrors `simulation.correlation_model_version`.",
    )
    kicker_projection_available: bool
    defense_projection_available: bool
    injury_adjustment_applied: bool
    matchup_adjustment_applied: bool = Field(
        description=(
            "False. matchup_score is NULL in the projection model; the matchup "
            "grade is derived above the model and is not an input to it."
        )
    )
    weather_adjustment_applied: bool
    notes: list[str] = Field(
        description="One sentence per assumption currently costing accuracy."
    )


class MatchupSimulationOut(Schema):
    """The result of one simulated matchup.

    Nothing here is persisted. Re-running the same request reproduces it, which
    is the property that makes storing it a later product decision rather than a
    prerequisite.
    """

    season: int
    week: int
    scoring_profile: str
    simulation: SimulationRunOut
    team_a: TeamSimulationOut
    team_b: TeamSimulationOut
    score_differential: float = Field(
        description="Mean of (team_a total - team_b total). Positive favours A."
    )
    median_differential: float = Field(
        description=(
            "Median sampled margin. Differs from score_differential whenever "
            "one lineup is more volatile than the other."
        )
    )
    assumptions: SimulationAssumptionsOut


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------


class LineupSlotOut(Schema):
    """One roster slot and the positions that may fill it.

    Build a lineup editor from this rather than from a hard-coded eligibility
    map. `supported: false` slots are recognised and refused with a reason;
    `/meta/positions` says what each is blocked on.
    """

    slot: str
    label: str
    eligible_positions: list[str]
    supported: bool
    unsupported_positions: list[str] = Field(default_factory=list)
    description: str = ""


class LineupFormatOut(Schema):
    """A league's starting lineup shape."""

    name: str
    label: str
    size: int
    requirements: list[dict]
    description: str = ""


class PositionSupportOut(Schema):
    """What the application can currently say about one position.

    A client builds its position filter from this rather than a hard-coded
    list, which is what makes shipping a kicker model a server-side data change
    and no client change at all.
    """

    position: str
    label: str
    status: str = Field(description="projected | planned")
    projected: bool
    reason: str | None = None
    blocked_on: list[str] = Field(default_factory=list)


class HealthOut(Schema):
    """The shape all three health endpoints return.

    One schema rather than three, so a dashboard parses one thing. Liveness
    simply leaves the dependency fields at their defaults — it answers "is this
    process running", and a liveness probe that consults the database restarts
    a perfectly healthy container every time Postgres fails over.
    """

    status: str = Field(description="ok | degraded")
    environment: str
    version: str
    database: bool | None = Field(
        default=None,
        description="Postgres reachable. Null when the check was not performed.",
    )
    cache: str | None = Field(
        default=None,
        description=(
            "Cache backend state: `ok`, `degraded`, `disabled` or "
            "`misconfigured`. A degraded cache never degrades overall status — "
            "the read path behind it is the query that was fast enough to ship "
            "before it existed.\n\n"
            "`disabled` means no cache was asked for. `misconfigured` means one "
            "was — `CACHE_BACKEND=redis` — and `REDIS_URL` is unset, so every "
            "cached endpoint is recomputing on every request. Both serve "
            "correct responses and neither fails readiness; they are separated "
            "because the second is a variable somebody forgot and reads as "
            "\"the app is slow\"."
        ),
    )
    checks: dict[str, str] = Field(
        default_factory=dict,
        description="Per-dependency detail, for an operator reading this directly.",
    )


def matchup_grade_out(grade: MatchupGrade) -> MatchupGradeOut:
    """Map a grade, which is a dataclass rather than a row."""
    return MatchupGradeOut(
        graded=grade.graded,
        score=grade.score,
        letter=grade.letter,
        defense_rank=grade.defense_rank,
        sample_games=grade.sample_games,
        reason=grade.reason,
    )


def slate_window_out(window: dto.SlateWindow) -> SlateWindowOut:
    return SlateWindowOut(
        season=window.season,
        week=window.week,
        resolution=window.resolution,
        is_upcoming=window.is_upcoming,
    )


# ---------------------------------------------------------------------------
# Mock draft
# ---------------------------------------------------------------------------
#
# Every simulated number below is `derived`, without exception. A draft outcome
# is a calculation performed above the model, over a pool the model never ranked
# and against opponents the model knows nothing about; labelling any of it
# `model` would extend the foundation's measured guarantees to numbers that were
# never measured against a held-out residual.
#
# Three provenances appear in one player card and the split is the point:
# `projected_points_per_game` is `model`, the completed seasons beside it are
# `actual`, and everything computed from either — expected games, season value,
# draft value, availability — is `derived`.


class RosterSlotIn(Schema):
    """One starting-lineup requirement."""

    slot: str = Field(description="A slot code from GET /meta/lineup-slots.")
    count: int = Field(ge=0, le=10, description="How many the league starts.")


class DraftSettingsIn(Schema):
    """League configuration for a mock draft.

    Everything a draft needs and nothing it does not: there is no user, no saved
    league and no persistence, so the whole configuration travels on the request
    and the response is reproducible from it plus the published run and the seed.
    """

    season: int = Field(
        ge=1999,
        le=2200,
        description=(
            "Season being drafted. Must have a published week 1 board — "
            "`GET /mock-draft/config` lists the seasons that do. The board is "
            "read as a per-game rate; the season itself is never used."
        ),
    )
    teams: int = Field(default=12, ge=4, le=20)
    rounds: int = Field(default=15, ge=1, le=25)
    scoring_profile: str | None = Field(
        default=None,
        description=(
            "standard, half_ppr, ppr, ppr_te_premium. Defaults to the "
            "configured profile; an unknown value is refused rather than "
            "silently defaulted."
        ),
    )
    draft_format: str = Field(
        default="snake",
        description="`snake` reverses every even round; `linear` does not.",
    )
    roster: list[RosterSlotIn] | None = Field(
        default=None,
        description=(
            "Starting-lineup requirements. Defaults to QB1/RB2/WR2/TE1/FLEX1. "
            "A K or DST slot is **refused**, with the reason and the blockers: "
            "no validated projection exists for either, and drafting a position "
            "with no projected value would put an invented number into every "
            "roster total."
        ),
    )
    simulations: int | None = Field(
        default=None,
        ge=50,
        le=10_000,
        description=(
            "Simulated drafts. A comparison runs this many for each seat, and "
            "the request is refused if the total exceeds what one worker should "
            "hold. `meta` reports the wall time it actually took."
        ),
    )
    seed: int | None = Field(
        default=None,
        ge=0,
        le=2**31 - 1,
        description=(
            "Reproducibility seed. Omitting it does **not** randomise the "
            "result — a fixed default is used and echoed back."
        ),
    )
    history_weight: float | None = Field(
        default=None,
        ge=0.0,
        le=0.8,
        description=(
            "How much the simulated opposing managers weight last completed "
            "season's actual points against value over replacement. **An "
            "assumption, not a measurement**: this repository holds no "
            "average-draft-position data to fit it against. Exposed so a "
            "conclusion's sensitivity to it can be checked."
        ),
    )
    noise: float | None = Field(
        default=None,
        ge=0.05,
        le=1.5,
        description=(
            "Spread of the randomness in opposing managers' selections, in "
            "units of the consensus score. Also an assumption. Zero would make "
            "every simulated draft identical and every availability percentage "
            "0% or 100%."
        ),
    )


class DraftAnalysisIn(DraftSettingsIn):
    """A request to analyse one draft position."""

    draft_position: int = Field(
        ge=1, le=20, description="The seat to analyse, 1-based."
    )


class HistoricalSeasonOut(Schema):
    """One completed season of actual production. `provenance: actual`."""

    season: int
    games_played: int
    team_games: int
    total_points: float
    points_per_game: float
    weekly_stdev: float | None = None
    position_rank: int | None = None
    position_percentile: float | None = None


class HistoricalEvidenceOut(Schema):
    """What history says about a player, and how firmly.

    `provenance: derived` for every band and estimate here; the `seasons` inside
    it are `actual`. The two are separated because one is a recorded fact and
    the other is an inference from it.
    """

    provenance: Provenance = Provenance.DERIVED
    seasons: list[HistoricalSeasonOut] = Field(default_factory=list)
    seasons_observed: int
    expected_games: float = Field(
        description=(
            "Estimated games available, shrunk toward a position prior. Counts "
            "weeks in which the player recorded a stat line, so it cannot "
            "separate an injury from a healthy scratch or a growing role."
        )
    )
    availability_rate: float | None = Field(
        default=None,
        description=(
            "The player's own unshrunk rate. Null when they have no completed "
            "season, in which case the estimate is the prior alone."
        ),
    )
    availability_basis: str = Field(
        description="`player_history` or `position_prior`."
    )
    consistency_percentile: float | None = None
    consistency_label: str | None = Field(
        default=None,
        description=(
            "High/Moderate/Low, banded **within position among this board**. "
            "Always a relative claim, never an absolute one."
        ),
    )
    trend: str | None = Field(
        default=None, description="rising / steady / declining, or null below two seasons."
    )
    trend_detail: str | None = None


class DraftPlayerOut(Schema):
    """A draftable player, with each number's origin kept apart."""

    player_id: str
    name: str
    position: str
    team: str | None = None
    projected_points_per_game: float = Field(
        description="`provenance: model` — the published week 1 expected points."
    )
    expected_games: float = Field(description="`provenance: derived`.")
    season_value: float = Field(
        description=(
            "`provenance: derived` — points per game times expected games. A "
            "draft-day rate, not a forecast of how the season unfolds."
        )
    )
    value_over_replacement: float | None = None
    floor_per_game: float | None = Field(
        default=None,
        description=(
            "Published P10 for that week. A **weekly** percentile: it is not "
            "multiplied by a season and must not be presented as a season floor."
        ),
    )
    ceiling_per_game: float | None = None
    extrapolated: bool = False
    historical: HistoricalEvidenceOut | None = None


class PickRationaleOut(Schema):
    """The numbers that decided a pick.

    Not prose about a pick — the actual values the engine compared. `explanation`
    is assembled from them mechanically, so it cannot describe a calculation
    that did not happen.
    """

    explanation: str
    slot: str = Field(description="starter / flex / bench.")
    marginal_value: float
    value_over_next_available: float
    expected_next_best_value: float
    next_best_player_id: str | None = None
    next_best_player_name: str | None = None
    next_pick_overall: int | None = None
    survival_at_next_pick: float
    scarcity: float
    tier_index: int | None = None
    tier_size: int | None = None
    tier_remaining: int | None = None
    runner_up_id: str | None = None
    runner_up_name: str | None = None
    runner_up_margin: float | None = None


class SimulatedPickOut(Schema):
    """One selection in the representative simulated draft."""

    overall: int
    round_number: int
    player_id: str
    name: str
    position: str
    team: str | None = None
    season_value: float
    projected_points_per_game: float
    expected_games: float
    value_over_replacement: float
    is_starter: bool
    rationale: PickRationaleOut | None = None
    historical: HistoricalEvidenceOut | None = None


class ValueDistributionOut(Schema):
    """Where a quantity landed across the simulations. `provenance: derived`."""

    mean: float
    median: float
    stdev: float
    p10: float
    p25: float
    p75: float
    p90: float
    minimum: float
    maximum: float
    observations: int
    standard_error: float = Field(
        description=(
            "Monte Carlo error on the mean. The number that says whether a gap "
            "between two draft positions is a finding or a rounding of noise."
        )
    )


class RoundPositionShareOut(Schema):
    """How often a round went to a position."""

    round_number: int
    position: str
    share: float


class PositionStrengthOut(Schema):
    """Mean starting value assembled at one position."""

    position: str
    mean_starter_points: float
    mean_value_over_replacement: float
    mean_starters: float


class PlayerAvailabilityOut(Schema):
    """How likely a player is to survive to one of this seat's picks."""

    player_id: str
    name: str
    position: str
    season_value: float
    reference_pick: int
    next_reference_pick: int | None = None
    first_pick_probability: float
    next_pick_probability: float
    drafted_before_next_pick: float
    mean_selection_pick: float | None = None
    selected_rate: float = Field(
        description=(
            "Share of calibration drafts in which the player was drafted at "
            "all — the denominator that separates 'goes late' from 'usually "
            "goes undrafted'."
        )
    )


class StrategyInsightOut(Schema):
    """A finding the simulations support, with the numbers behind it."""

    kind: str
    headline: str
    detail: str
    evidence: dict[str, float | int | str | None] = Field(default_factory=dict)


class ReplacementLevelOut(Schema):
    """The zero point for one position under this league."""

    position: str
    starters: int
    value: float
    player_id: str | None = None
    flex_share: int


class DraftPoolOut(Schema):
    """What the board was built from."""

    provenance: Provenance = Provenance.DERIVED
    players: int
    positions: list[str]
    season: int
    board_week: int
    season_games: int
    history_seasons: list[int]
    players_without_history: int
    replacement: list[ReplacementLevelOut] = Field(default_factory=list)


class SeatAnalysisOut(Schema):
    """Everything the product says about one draft position."""

    provenance: Provenance = Provenance.DERIVED
    draft_position: int
    simulations: int
    roster_value: ValueDistributionOut
    starter_points: ValueDistributionOut
    picks: list[int]
    waits: list[int] = Field(
        description=(
            "Picks that elapse between each selection and the next. The seat "
            "asymmetry itself: seat 1 waits 22 then 2 in a twelve-team snake, "
            "seat 6 waits 12 every time."
        )
    )
    representative_index: int = Field(
        description=(
            "Which simulation the roster below is. The one whose roster value "
            "is closest to the **median**, never the best — the best of ten "
            "thousand drafts is a tail event, not a plan."
        )
    )
    roster: list[SimulatedPickOut] = Field(default_factory=list)
    round_positions: list[RoundPositionShareOut] = Field(default_factory=list)
    position_strength: list[PositionStrengthOut] = Field(default_factory=list)
    insights: list[StrategyInsightOut] = Field(default_factory=list)
    availability: list[PlayerAvailabilityOut] = Field(default_factory=list)


class DraftMethodologyOut(Schema):
    """How the answer was produced, in the response that carries it."""

    calibration_drafts: int
    history_weight: float
    noise: float
    elapsed_seconds: float
    seed: int
    simulations: int
    strategy: str = "value_over_next_available"


class DraftAnalysisOut(Schema):
    """One draft position, analysed."""

    settings: "DraftSettingsOut"
    seat: SeatAnalysisOut
    pool: DraftPoolOut
    methodology: DraftMethodologyOut


class DraftSettingsOut(Schema):
    """The configuration that produced a result, echoed for reproducibility."""

    season: int
    teams: int
    rounds: int
    scoring_profile: str
    draft_format: str
    roster: list[RosterSlotIn]
    starters: int
    bench: int
    simulations: int
    seed: int


class SeatSummaryOut(Schema):
    """One row of the draft-position comparison."""

    draft_position: int
    roster_value: ValueDistributionOut
    starter_points: ValueDistributionOut
    percentile: float = Field(
        description=(
            "Rank among the **seats**, not among rosters. Twelve observations, "
            "presented as the ranking it is."
        )
    )
    is_best: bool


class DraftComparisonOut(Schema):
    """Every seat, ranked, and whether the ranking survives its own noise."""

    provenance: Provenance = Provenance.DERIVED
    settings: DraftSettingsOut
    seats: list[SeatSummaryOut]
    best_position: int = Field(
        description=(
            "The seat with the highest simulated mean roster value. Highest "
            "simulated value under these assumptions — not the best seat in any "
            "absolute sense, and not a prediction."
        )
    )
    spread: float
    spread_is_resolvable: bool = Field(
        description=(
            "Whether the best-to-worst gap exceeds the Monte Carlo error on the "
            "two means it is computed from. When false the ranking is noise and "
            "must not be presented as a recommendation."
        )
    )
    detail: list[SeatAnalysisOut] = Field(
        default_factory=list,
        description="Per-seat detail, so a client can inspect any seat's roster.",
    )
    pool: DraftPoolOut
    methodology: DraftMethodologyOut


class DraftLimitsOut(Schema):
    """Bounds a client builds its configuration form from.

    Served so the form's validation and the server's cannot drift apart — the
    same reason `/meta/positions` exists.
    """

    min_teams: int
    max_teams: int
    min_rounds: int
    max_rounds: int
    min_simulations: int
    max_simulations: int
    default_simulations: int
    max_total_drafts: int
    default_seed: int
    draft_formats: list[str]
    default_roster: list[RosterSlotIn]
    scoring_profiles: list[str]


class DraftConfigOut(Schema):
    """Everything a client needs to build a valid draft request."""

    limits: DraftLimitsOut
    draftable_seasons: list[int] = Field(
        description=(
            "Seasons with a published week 1 board. A season with a schedule "
            "but no board cannot be drafted, and offering it would produce an "
            "empty screen with no explanation."
        )
    )
    draftable_positions: list[str]
    unavailable_positions: list[dict] = Field(
        default_factory=list,
        description=(
            "Positions recognised but not draftable, each with the reason and "
            "what it is blocked on. Straight from the position registry."
        ),
    )


MetaOut.model_rebuild()
WeekOut.model_rebuild()
DraftAnalysisOut.model_rebuild()
DraftComparisonOut.model_rebuild()
