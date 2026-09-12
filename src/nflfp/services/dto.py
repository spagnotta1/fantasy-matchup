"""The business layer's vocabulary.

These are plain frozen dataclasses, not Pydantic models, and that is a
deliberate boundary rather than an oversight. The service layer must be usable
from a worker, a notebook and a CLI as well as from FastAPI; a layer whose
return types are web-framework response models is a layer that has quietly
merged with the transport. Layer 5 owns the Pydantic schemas and the mapping
onto them, which also means the wire format can gain a field, rename one for
the frontend, or version itself without any of that reaching the football.

Everything here is immutable. A projection is a statement about a moment, and
handing callers something they can mutate invites a bug where one endpoint's
rounding leaks into another's cache.

Provenance is a first-class field, not a footnote
-------------------------------------------------
Several structures carry ``source`` or ``applied_to_projection``. Those exist
because the honest answer to "what does the weather do to this projection?" is
currently *nothing* — Layer 3b measured market and weather features against the
residual of the baseline, found correlations of -0.039 to 0.021, and excluded
them. Reporting a fabricated "weather impact: -8%" would be worse than useless.
Reporting the observed conditions, clearly labelled as context the model did not
use, is both true and still what a user wants to see.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from .distributions import OutcomeCurve
from .grading import MatchupGrade

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlayerRef:
    """Enough of a player to render a row without a second lookup."""

    player_id: str
    name: str
    position: str | None = None
    team: str | None = None
    jersey_number: int | None = None
    status: str | None = None
    headshot_url: str | None = None
    years_of_experience: int | None = None
    college: str | None = None


@dataclass(frozen=True)
class TeamRef:
    """A team, with the branding fields the UI needs."""

    abbr: str
    name: str | None = None
    nickname: str | None = None
    conference: str | None = None
    division: str | None = None
    primary_color: str | None = None
    secondary_color: str | None = None
    logo_url: str | None = None


@dataclass(frozen=True)
class ModelRef:
    """Which model run produced a projection.

    Carried on every projection the API returns. Without it, "why did this
    change on Thursday?" is unanswerable, and the whole point of keeping
    superseded runs on disk is to make it answerable.
    """

    run_id: int
    model_name: str
    model_version: str
    algorithm: str
    feature_schema_version: int
    published_at: datetime | None = None
    code_sha: str | None = None


# ---------------------------------------------------------------------------
# The projection itself
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PointDistribution:
    """A projected fantasy-point distribution under one scoring format.

    ``expected`` is the headline number, not ``predicted``. The two are stored
    separately on purpose: ``predicted`` is the model's raw output and is
    conditionally biased by construction, because shrinkage trades bias for
    variance; ``expected`` is the mean of the held-out distribution and is the
    calibrated one, measured within +/-0.1 points of conditional bias in every
    projection band with a usable sample.
    """

    scoring_profile: str
    expected: float | None
    predicted: float
    floor: float | None = None
    p25: float | None = None
    median: float | None = None
    p75: float | None = None
    ceiling: float | None = None
    standard_deviation: float | None = None
    confidence: float | None = None
    confidence_label: str = "unknown"
    boom_probability: float | None = None
    bust_probability: float | None = None
    boom_threshold: float | None = None
    bust_threshold: float | None = None
    #: ``"steady"`` or ``"volatile"`` — see :func:`~nflfp.services.grading.outcome_shape`.
    shape: str = "unknown"
    extrapolated: bool = False
    samples: int | None = None
    calibration_method: str | None = None

    @property
    def headline(self) -> float | None:
        """The number to show. Falls back to the raw output only if the
        calibrated mean is absent, which happens for runs written before the
        distribution layer existed."""
        return self.expected if self.expected is not None else self.predicted

    def curve(self) -> OutcomeCurve | None:
        """The reconstructed outcome curve for this distribution.

        Every probabilistic question in the product — tier boundaries, start/sit
        odds, and any future lineup simulation — is asked of a curve rather than
        of a point estimate, so the translation from stored percentiles to curve
        happens here and nowhere else. It lived in two places before and the two
        had already drifted: one propagated ``extrapolated`` and ``samples`` and
        the other silently dropped them, which meant the same projection was
        honest about its own thinness in the start/sit path and quietly
        confident in the tiering path.

        Returns:
            The curve, or ``None`` when fewer than three percentiles are stored.
            A missing distribution is a normal state, not an error; see
            :meth:`~nflfp.services.distributions.OutcomeCurve.from_percentiles`.
        """
        return OutcomeCurve.from_percentiles(
            p10=self.floor,
            p25=self.p25,
            median=self.median,
            p75=self.p75,
            p90=self.ceiling,
            expected=self.expected,
            extrapolated=self.extrapolated,
            samples=self.samples,
        )


@dataclass(frozen=True)
class ProjectedComponents:
    """Projected opportunity and production, before any scoring rules apply.

    This is what the model actually predicts. "8.4 targets" is explainable in a
    way "14.2 points" is not, and keeping components separate is what lets one
    model serve every scoring format.
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


@dataclass(frozen=True)
class UsageOutlook:
    """Recent workload — the trailing four-game usage the projection rests on.

    Every window here ends at the *previous* week. That is the same lag rule the
    feature layer enforces, restated at the presentation boundary so nobody
    reading these numbers mistakes them for this week's snap count.
    """

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


@dataclass(frozen=True)
class MatchupContext:
    """The defensive matchup, as both a rank and a magnitude.

    The grade is a *percentile* — by construction about 2.5 defences hold each
    letter every week — so it answers "how does this matchup rank?" and not
    "how much is it worth?". ``fp_allowed_vs_position_l4`` answers the second
    question, in points, and the two are returned together because either alone
    is misleading.
    """

    opponent: str | None
    is_home: bool | None
    grade: MatchupGrade
    fp_allowed_vs_position_l4: float | None = None
    targets_allowed_l4: float | None = None
    carries_allowed_l4: float | None = None
    defense_rank_overall: int | None = None
    opponent_pace_l4: float | None = None


@dataclass(frozen=True)
class GameContext:
    """Schedule and market context for the game a projection sits in.

    ``spread_source`` distinguishes a live market capture from nflverse's
    settled closing line. They are different objects — one is what the market
    thinks now, the other is what it thought at kickoff of a game already
    played — and conflating them is exactly the train/serve mismatch Layer 3b
    measured and then avoided by excluding market features entirely.
    """

    game_id: str | None
    season: int
    week: int
    team: str | None
    opponent: str | None
    is_home: bool | None
    kickoff: datetime | None = None
    gameday: date | None = None
    team_spread: float | None = None
    total_line: float | None = None
    implied_team_total: float | None = None
    implied_opponent_total: float | None = None
    spread_movement: float | None = None
    spread_source: str | None = None
    odds_book: str | None = None
    odds_captured_at: datetime | None = None
    rest_days: int | None = None
    rest_advantage: int | None = None
    divisional: bool | None = None
    #: The market is reported, never applied. Correlation with the baseline's
    #: residual measured -0.039 to +0.021 across positions over 2019-2025.
    applied_to_projection: bool = False
    unapplied_reason: str | None = None


@dataclass(frozen=True)
class WeatherContext:
    """Forecast conditions for the game.

    ``applied_to_projection`` is ``False`` today and will stay that way until a
    weather feature demonstrably beats the baseline. History carries observed
    temperature and wind while upcoming games carry a forecast; a model trained
    on one and served the other is being fed two different distributions.

    The extension point is real, not rhetorical. ``projections`` already has a
    ``weather_multiplier`` column. When the engine begins writing it,
    :attr:`multiplier` carries the value and ``applied_to_projection`` becomes
    ``True`` on its own — no schema change, no client change, no edit to this
    file. Until then it is ``None``, and the API says so explicitly rather than
    reporting a fabricated adjustment.
    """

    is_indoor: bool | None = None
    temperature_f: float | None = None
    wind_mph: float | None = None
    wind_gust_mph: float | None = None
    precipitation_probability: float | None = None
    snowfall_in: float | None = None
    roof_uncertain: bool = False
    source: str | None = None
    captured_at: datetime | None = None
    #: Multiplicative adjustment the engine applied, or ``None`` if it did not.
    multiplier: float | None = None
    applied_to_projection: bool = False
    #: Why the adjustment was not applied. ``None`` once it is.
    unapplied_reason: str | None = None

    @property
    def is_adverse(self) -> bool:
        """A conditions flag for the UI, not a projection adjustment.

        20+ mph wind is the threshold at which passing games measurably suffer;
        it is surfaced so a user can apply their own judgement, which is the
        honest division of labour when the model does not use it.
        """
        if self.is_indoor:
            return False
        return (self.wind_mph or 0) >= 20 or (self.precipitation_probability or 0) >= 0.6


@dataclass(frozen=True)
class InjuryContext:
    """The player's official injury designation for this week.

    The report is a *fact about availability*, published before kickoff, and is
    reported verbatim. The projection does not apply an injury multiplier — the
    engine has no fitted one — so ``applied_to_projection`` is ``False`` and a
    designation of "Out" means the projection describes a player who will not
    play. Layer 5 surfaces that prominently; silently zeroing the projection
    here would destroy the distinction between "projected zero" and "not
    playing".

    As with :class:`WeatherContext`, the extension point is wired rather than
    promised: ``projections.injury_multiplier`` exists, and the moment the
    engine writes it, :attr:`multiplier` carries it and
    ``applied_to_projection`` flips on its own.
    """

    report_status: str | None = None
    practice_status: str | None = None
    detail: str | None = None
    #: Multiplier the engine applied to projected usage (1.0 healthy, 0.0 out),
    #: or ``None`` if it applied none.
    multiplier: float | None = None
    applied_to_projection: bool = False
    #: Why the adjustment was not applied. ``None`` once it is.
    unapplied_reason: str | None = None

    @property
    def is_questionable_or_worse(self) -> bool:
        status = (self.report_status or "").strip().lower()
        return status in {"questionable", "doubtful", "out"}

    @property
    def will_not_play(self) -> bool:
        return (self.report_status or "").strip().lower() == "out"


@dataclass(frozen=True)
class PlayerProjection:
    """One player's projection for one week, with everything needed to judge it.

    This is the business layer's central return type. An endpoint that needs
    less returns a projection of this onto a narrower schema; an endpoint never
    needs more, which is the property that keeps the API from growing its own
    queries.
    """

    player: PlayerRef
    season: int
    week: int
    team: str | None
    opponent: str | None
    is_home: bool | None
    game_id: str | None
    points: PointDistribution
    components: ProjectedComponents = field(default_factory=ProjectedComponents)
    usage: UsageOutlook = field(default_factory=UsageOutlook)
    matchup: MatchupContext | None = None
    game: GameContext | None = None
    weather: WeatherContext | None = None
    injury: InjuryContext | None = None
    model: ModelRef | None = None
    #: Provenance ``actual``: what the player scored, for a week already
    #: played. ``None`` for a week with no result yet — never a stand-in zero.
    actual_points: float | None = None

    # -- correlation ---------------------------------------------------------
    # Every probabilistic combination in this codebase assumes independence, and
    # these two predicates are how a caller finds out where that assumption is
    # false. They live on the projection because they are facts about a *pair of
    # projections* and nothing else; keeping them private inside the start/sit
    # module made them invisible to any other consumer that combines players,
    # which is precisely the consumer most exposed to getting correlation wrong.

    def shares_game_with(self, other: "PlayerProjection") -> bool:
        """Both players are in the same NFL game.

        Their outcomes are correlated: game script, pace and weather are shared
        inputs, and one player's production can suppress the other's directly
        when they are on opposite sides.
        """
        return self.game_id is not None and self.game_id == other.game_id

    def is_teammate_of(self, other: "PlayerProjection") -> bool:
        """Both players are on the same NFL team.

        The strongest correlation available: teammates divide a single set of
        plays, so their projections are competing for the same finite pool of
        targets and carries. Treating two receivers in one offence as
        independent overstates both the ceiling and the floor of their sum.
        """
        return self.team is not None and self.team == other.team


# ---------------------------------------------------------------------------
# Rankings and slates
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RankedProjection:
    """A projection with its place in a board.

    ``tier`` is not a decoration. It is derived from the distributions: two
    adjacent players sit in the same tier while the lower one still has a
    realistic chance of outscoring the higher one. A rank of 14 versus 15 is
    usually noise; a tier boundary between them is a real decision point.
    """

    rank: int
    positional_rank: int
    tier: int
    projection: PlayerProjection


@dataclass(frozen=True)
class Slate:
    """A week's board.

    ``model`` is ``None`` and ``entries`` empty when nothing is published for
    the week. That is a legitimate answer, and it is distinguishable from "the
    week does not exist", which raises instead.
    """

    season: int
    week: int
    scoring_profile: str
    entries: tuple[RankedProjection, ...]
    model: ModelRef | None = None
    total: int = 0
    positions: tuple[str, ...] = ()

    def __len__(self) -> int:
        return len(self.entries)


@dataclass(frozen=True)
class SlateWindow:
    """Which season and week a request resolved to, and how.

    Returned alongside anything that accepted a defaulted week, so a client
    never has to guess whether it is looking at the upcoming slate or the last
    completed one.
    """

    season: int
    week: int
    #: ``"explicit"``, ``"upcoming"`` or ``"latest_completed"``.
    resolution: str
    is_upcoming: bool


@dataclass(frozen=True)
class SeasonAvailability:
    """A season a client may actually offer, and the weeks it can offer in it.

    *Availability* is published projections, not schedule. A season the
    warehouse holds games for but no run has ever covered has nothing to show,
    and putting it in a picker promises a product the deployment cannot deliver
    — the user selects it, every screen comes back empty, and the application
    looks broken rather than unpublished.
    """

    season: int
    #: Ascending. Never empty: a season with no published week is not available.
    published_weeks: tuple[int, ...]

    @property
    def latest_published_week(self) -> int:
        """The newest week with a board — what a picker should open on."""
        return self.published_weeks[-1]


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HistoricalWeek:
    """What a player actually did in a completed week, beside what was projected.

    The projection is included only when a published run covered that week, and
    is read from the row that was stored at the time rather than regenerated.
    Regenerating it with today's model would answer a different and much less
    interesting question than "were we right?".
    """

    season: int
    week: int
    team: str | None
    opponent: str | None
    is_home: bool | None
    actual_points: float | None
    projected_points: float | None = None
    error: float | None = None
    snap_pct: float | None = None
    targets: float | None = None
    carries: float | None = None
    receptions: float | None = None
    receiving_yards: float | None = None
    rushing_yards: float | None = None
    passing_yards: float | None = None
    total_tds: float | None = None
    injury_report_status: str | None = None


@dataclass(frozen=True)
class TrendSummary:
    """Aggregate accuracy and form over a player's recent history."""

    games: int
    mean_points: float | None = None
    median_points: float | None = None
    standard_deviation: float | None = None
    boom_rate: float | None = None
    bust_rate: float | None = None
    mean_absolute_error: float | None = None
    bias: float | None = None
    graded_games: int = 0


@dataclass(frozen=True)
class PlayerProfile:
    """Everything the player page needs, assembled in one call."""

    player: PlayerRef
    scoring_profile: str
    current: PlayerProjection | None
    history: tuple[HistoricalWeek, ...]
    trend: TrendSummary
    window: SlateWindow


# ---------------------------------------------------------------------------
# Advice
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ComparisonEntry:
    """One side of a comparison, with the numbers the verdict was built from."""

    projection: PlayerProjection
    expected: float | None
    floor: float | None
    ceiling: float | None
    win_probability: float | None = None


@dataclass(frozen=True)
class StartSitAdvice:
    """A head-to-head recommendation and the reasoning behind it.

    ``verdict`` is ``"clear"``, ``"lean"`` or ``"toss_up"`` and ``recommended``
    names the player, or is ``None`` for a toss-up. A toss-up is a real answer:
    stating a preference between two players separated by less noise than the
    model's own error bar would be false precision.
    """

    a: ComparisonEntry
    b: ComparisonEntry
    win_probability: float
    expected_margin: float
    verdict: str
    recommended: str | None
    rationale: tuple[str, ...] = ()
    caveats: tuple[str, ...] = ()


@dataclass(frozen=True)
class Comparison:
    """An n-way comparison table, ranked by expected points."""

    season: int
    week: int
    scoring_profile: str
    entries: tuple[ComparisonEntry, ...]
    #: Pairwise start/sit calls between consecutive entries, best-first.
    head_to_head: tuple[StartSitAdvice, ...] = ()


# ---------------------------------------------------------------------------
# Teams and matchups
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TeamOutlook:
    """A team's week: the game, the market, and its projected skill players."""

    team: TeamRef
    season: int
    week: int
    game: GameContext | None
    weather: WeatherContext | None
    players: tuple[RankedProjection, ...]
    projected_points: float | None = None
    scoring_profile: str = ""


@dataclass(frozen=True)
class PositionMatchup:
    """How a defence has handled one position lately."""

    position: str
    grade: MatchupGrade
    fp_allowed_l4: float | None = None
    targets_allowed_l4: float | None = None
    carries_allowed_l4: float | None = None
    yards_allowed_l4: float | None = None


@dataclass(frozen=True)
class MatchupAnalysis:
    """A single game viewed from both sides.

    Built from the defensive rolling views, so every number is a trailing
    average ending at the previous week and is available before kickoff.
    """

    game_id: str | None
    season: int
    week: int
    home: TeamRef
    away: TeamRef
    game: GameContext | None
    weather: WeatherContext | None
    #: Keyed by defending team abbreviation.
    defense: dict[str, tuple[PositionMatchup, ...]] = field(default_factory=dict)
    top_projections: tuple[RankedProjection, ...] = ()
