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
# Meta
# ---------------------------------------------------------------------------


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
            "Cache backend state: `ok`, `degraded`, or `disabled`. A degraded "
            "cache never degrades overall status — the read path behind it is "
            "the query that was fast enough to ship before it existed."
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


MetaOut.model_rebuild()
WeekOut.model_rebuild()
