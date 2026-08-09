"""Layer 4 — the business logic.

Every question the application can answer is answered here, and the API layer
above it is expected to contain no football at all: it validates a request,
calls one of these functions, and serialises the result. That is the rule the
brief states as "the API should communicate only with this layer", and it is
enforced by shape rather than by convention — nothing in this package imports
FastAPI, and nothing here raises an HTTP exception.

The six modules a caller uses
-----------------------------
:mod:`~nflfp.services.catalog`
    Seasons, weeks, teams, scoring profiles, and what "this week" means.
:mod:`~nflfp.services.projections`
    Weekly boards: the slate, position rankings, one player's week.
:mod:`~nflfp.services.players`
    Search, the player dimension, history and the assembled profile.
:mod:`~nflfp.services.matchups`
    A game from both sides, defensive rankings, a team's outlook.
:mod:`~nflfp.services.advice`
    Start/sit and comparison — the only place the app recommends rather than
    reports.
:mod:`~nflfp.services.rosters`
    A named set of players retrieved together, with every gap in it declared
    rather than dropped, plus the correlation structure of the resulting
    lineup. The seam the Matchup Simulation Engine reads from.
:mod:`~nflfp.services.simulation`
    The stateless Matchup Simulation Engine: two validated lineups in, two
    sampled score distributions and a win probability out. It consumes stored
    distributions and creates nothing — no model, no projection, no fitted
    uncertainty — and its output is ``derived`` provenance, never ``model``.

The five they should not need
-----------------------------
:mod:`~nflfp.services.repository` is the only module that writes SQL.
:mod:`~nflfp.services.assemble` turns rows into domain objects and is pure.
:mod:`~nflfp.services.grading` owns every display threshold in the product.
:mod:`~nflfp.services.distributions` reconstructs an outcome curve from stored
percentiles and answers probabilistic questions about it.
:mod:`~nflfp.services.lineup` owns the slot vocabulary and lineup validation —
the single place that knows a FLEX takes an RB, a WR or a TE.

That split is what makes the interesting parts testable without Postgres. Tier
boundaries, grade cutoffs, toss-up thresholds and the head-to-head integral are
all unit-tested against constructed inputs; only the SQL needs a database.

What this layer does not do
---------------------------
It never invokes a model. Projections are generated in advance by Layer 3 and
published by moving a flag, so a read path that called a model would be both
slow and unable to explain itself. It also never writes: every function here is
a read, which is what will make caching these results a configuration decision
in Layer 6 rather than an invalidation problem.
"""

from __future__ import annotations

from .dto import (
    Comparison,
    ComparisonEntry,
    GameContext,
    HistoricalWeek,
    InjuryContext,
    MatchupAnalysis,
    MatchupContext,
    ModelRef,
    PlayerProfile,
    PlayerProjection,
    PlayerRef,
    PointDistribution,
    PositionMatchup,
    ProjectedComponents,
    RankedProjection,
    Slate,
    SlateWindow,
    StartSitAdvice,
    TeamOutlook,
    TeamRef,
    TrendSummary,
    UsageOutlook,
    WeatherContext,
)
from .errors import (
    DataUnavailable,
    FeatureLayerUnavailable,
    InvalidRequest,
    NoProjectionsPublished,
    NotFound,
    ServiceError,
    UnknownScoringProfile,
)
from .grading import MatchupGrade
from .lineup import (
    LINEUP_SLOTS,
    STANDARD_FORMAT,
    Lineup,
    LineupEntry,
    LineupFormat,
    LineupSlot,
    validate_eligibility,
    validate_structure,
)
from .rosters import (
    CorrelationGroup,
    RosterProjections,
    UnavailablePlayer,
    correlation_groups,
    lineup_caveats,
)
from .simulation import (
    MatchupSimulation,
    SimulationAssumptions,
    TeamSimulation,
    simulate,
    simulate_matchup,
)

__all__ = [
    # errors — Layer 5 maps exactly these onto status codes
    "ServiceError",
    "NotFound",
    "InvalidRequest",
    "NoProjectionsPublished",
    "DataUnavailable",
    "FeatureLayerUnavailable",
    "UnknownScoringProfile",
    # domain objects
    "Comparison",
    "ComparisonEntry",
    "CorrelationGroup",
    "GameContext",
    "HistoricalWeek",
    "InjuryContext",
    "MatchupAnalysis",
    "MatchupContext",
    "MatchupGrade",
    "ModelRef",
    "PlayerProfile",
    "PlayerProjection",
    "PlayerRef",
    "PointDistribution",
    "PositionMatchup",
    "ProjectedComponents",
    "RankedProjection",
    "RosterProjections",
    "Slate",
    "SlateWindow",
    "StartSitAdvice",
    "TeamOutlook",
    "TeamRef",
    "TrendSummary",
    "UnavailablePlayer",
    "UsageOutlook",
    "WeatherContext",
    # lineup vocabulary — the single source of truth for slot eligibility
    "LINEUP_SLOTS",
    "STANDARD_FORMAT",
    "Lineup",
    "LineupEntry",
    "LineupFormat",
    "LineupSlot",
    "validate_eligibility",
    "validate_structure",
    # simulation
    "MatchupSimulation",
    "SimulationAssumptions",
    "TeamSimulation",
    "simulate",
    "simulate_matchup",
    # lineup-level helpers
    "correlation_groups",
    "lineup_caveats",
]
