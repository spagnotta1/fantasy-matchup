"""Prediction-engine output: lineage, projections, and per-format points.

Why three tables and not one
---------------------------
A projection has two independent axes. Its *components* (targets, carries,
yards, touchdowns, snap share) are facts about football and do not depend on
league rules. Its *points* — predicted, floor, median, ceiling, boom, bust —
exist once per scoring format.

Flattening those together would store roughly thirty component columns four
times over for a single player-week, and would make "add TE-premium scoring" a
data migration. Splitting them means a new format is a handful of extra rows in
one narrow table, and the component projection stays exactly one row.

The third table, :class:`ModelRun`, is lineage: which model, which version,
which parameters, which metrics produced this. Without it, "why did this
projection change on Thursday?" is unanswerable, and unanswerable is not an
acceptable property of a system people make lineup decisions with.

Publishing
----------
Projections are generated in advance and read by the API; the API never invokes
a model. A run becomes visible by moving to ``published``, and a partial unique
index allows only one published run per ``(model_name, season, week)``. So a
rollout is a one-row ``UPDATE`` inside a transaction, instantly reversible, with
the previous run still on disk. No blue/green table swap, no cache stampede.

Warehouse references
--------------------
``player_id``, ``game_id`` and ``team`` are nflverse natural keys carried
without foreign keys — see :mod:`nflfp.db.base` for why constraints pointing
into the weekly-swapped warehouse cannot exist.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base, TimestampMixin
from ..enums import Algorithm, ModelRunStatus, ScoringProfile, sql_in_list

# JSONB on Postgres, plain JSON elsewhere. Only Postgres is supported in
# production; the fallback keeps the models importable under SQLite for fast
# unit tests that never touch a real server.
JSONType = JSON().with_variant(JSONB(), "postgresql")


class ModelRun(Base, TimestampMixin):
    """One execution of the prediction engine.

    Every projection row points at the run that produced it, so a model can be
    evaluated, compared against its predecessor, or rolled back without
    touching the projections themselves.
    """

    __tablename__ = "model_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    model_name: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        doc="Registered model identifier, e.g. 'weekly_points'. Stable across versions.",
    )
    model_version: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        doc="Version of that model, e.g. '2.1.0'. Bumped whenever output changes.",
    )
    algorithm: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=Algorithm.BASELINE.value,
        doc="Estimator family; see nflfp.db.enums.Algorithm.",
    )

    season: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    week: Mapped[int | None] = mapped_column(
        SmallInteger,
        nullable=True,
        doc="Null for runs that are not week-scoped, such as a training job.",
    )

    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=ModelRunStatus.PENDING.value,
        doc="See nflfp.db.enums.ModelRunStatus. Only 'published' is read by the API.",
    )

    feature_schema_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        doc=(
            "Version of the feature contract used. Because Projection.features "
            "is schema-less JSONB, this integer is what makes a stored feature "
            "vector interpretable after the feature set has moved on."
        ),
    )
    code_sha: Mapped[str | None] = mapped_column(
        String(40), nullable=True, doc="Git commit of the code that produced this run."
    )

    params: Mapped[dict | None] = mapped_column(
        JSONType, nullable=True, doc="Hyperparameters and configuration."
    )
    metrics: Mapped[dict | None] = mapped_column(
        JSONType,
        nullable=True,
        doc="Backtest/validation metrics, e.g. {'mae': 4.1, 'spearman': 0.62}.",
    )

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)

    projections: Mapped[list["Projection"]] = relationship(
        back_populates="model_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(
            "status IN " + sql_in_list(ModelRunStatus),
            name="status_known",
        ),
        CheckConstraint("season BETWEEN 1999 AND 2200", name="season_plausible"),
        CheckConstraint("week IS NULL OR week BETWEEN 1 AND 25", name="week_plausible"),
        CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="finished_after_started",
        ),
        # At most one published run per model per week. Partial, so the many
        # superseded and failed runs are unconstrained.
        Index(
            "uq_model_runs_published",
            "model_name",
            "season",
            "week",
            unique=True,
            postgresql_where=text("status = 'published'"),
        ),
        Index("ix_model_runs_season_week_status", "season", "week", "status"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<ModelRun id={self.id} {self.model_name}@{self.model_version} "
            f"{self.season}w{self.week} {self.status}>"
        )


class Projection(Base, TimestampMixin):
    """A scoring-agnostic projection for one player in one week.

    Holds projected *opportunity* and *production* components plus the context
    scalars that explain them. Fantasy points live in
    :class:`ProjectionPoints`, one row per scoring format.

    The impact fields (``matchup_score``, ``injury_multiplier``,
    ``weather_multiplier``) are stored as numbers, not as the letter grades and
    prose the UI shows. Presentation is derived in the business layer so that
    the thresholds behind "A-" exist in exactly one place and can be changed
    without a backfill.
    """

    __tablename__ = "projections"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    model_run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("model_runs.id", ondelete="CASCADE"),
        nullable=False,
    )

    # ---- identity (nflverse natural keys; see module docstring) -----------
    player_id: Mapped[str] = mapped_column(String(32), nullable=False, doc="gsis_id")
    season: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    week: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    game_id: Mapped[str | None] = mapped_column(String(32))
    team: Mapped[str | None] = mapped_column(String(8))
    opponent: Mapped[str | None] = mapped_column(String(8))
    position: Mapped[str | None] = mapped_column(String(8))
    is_home: Mapped[bool | None] = mapped_column(Boolean)

    # ---- projected usage --------------------------------------------------
    # Usage is the signal: snap share correlates 0.62-0.71 with weekly points
    # and persists year over year at 0.63-0.73, while efficiency does not
    # (0.16-0.23). Projecting opportunity explicitly, rather than points
    # directly, is what makes that structure usable.
    proj_snap_pct: Mapped[float | None] = mapped_column(Float, doc="0-1 fraction")
    proj_target_share: Mapped[float | None] = mapped_column(Float, doc="0-1 fraction")
    proj_rush_share: Mapped[float | None] = mapped_column(Float, doc="0-1 fraction")
    proj_redzone_touches: Mapped[float | None] = mapped_column(Float)
    proj_team_plays: Mapped[float | None] = mapped_column(Float, doc="pace proxy")

    proj_targets: Mapped[float | None] = mapped_column(Float)
    proj_receptions: Mapped[float | None] = mapped_column(Float)
    proj_carries: Mapped[float | None] = mapped_column(Float)
    proj_pass_attempts: Mapped[float | None] = mapped_column(Float)

    # ---- projected production --------------------------------------------
    proj_passing_yards: Mapped[float | None] = mapped_column(Float)
    proj_passing_tds: Mapped[float | None] = mapped_column(Float)
    proj_interceptions: Mapped[float | None] = mapped_column(Float)
    proj_rushing_yards: Mapped[float | None] = mapped_column(Float)
    proj_rushing_tds: Mapped[float | None] = mapped_column(Float)
    proj_receiving_yards: Mapped[float | None] = mapped_column(Float)
    proj_receiving_tds: Mapped[float | None] = mapped_column(Float)

    # ---- context and adjustments -----------------------------------------
    matchup_score: Mapped[float | None] = mapped_column(
        Float,
        doc="0-100, higher is a better matchup. The UI's letter grade derives from this.",
    )
    defense_rank_vs_position: Mapped[int | None] = mapped_column(
        SmallInteger, doc="1-32, 1 = toughest defence against this position."
    )
    injury_multiplier: Mapped[float | None] = mapped_column(
        Float, doc="Applied to projected usage. 1.0 = healthy, 0.0 = ruled out."
    )
    weather_multiplier: Mapped[float | None] = mapped_column(
        Float, doc="1.0 = neutral conditions."
    )
    vegas_implied_total: Mapped[float | None] = mapped_column(
        Float, doc="Implied points for this player's team, from the market."
    )
    team_spread: Mapped[float | None] = mapped_column(
        Float, doc="Points this team is favoured by (already sign-normalised)."
    )

    features: Mapped[dict | None] = mapped_column(
        JSONType,
        nullable=True,
        doc=(
            "The exact feature vector fed to the model. JSONB rather than columns "
            "so that adding a feature is a model change, not a migration; "
            "ModelRun.feature_schema_version is what keeps it interpretable."
        ),
    )

    model_run: Mapped[ModelRun] = relationship(back_populates="projections")
    points: Mapped[list["ProjectionPoints"]] = relationship(
        back_populates="projection",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "model_run_id", "player_id", "season", "week", name="uq_projections_identity"
        ),
        CheckConstraint("week BETWEEN 1 AND 25", name="week_plausible"),
        CheckConstraint("season BETWEEN 1999 AND 2200", name="season_plausible"),
        CheckConstraint(
            "proj_snap_pct IS NULL OR proj_snap_pct BETWEEN 0 AND 1",
            name="snap_pct_fraction",
        ),
        CheckConstraint(
            "proj_target_share IS NULL OR proj_target_share BETWEEN 0 AND 1",
            name="target_share_fraction",
        ),
        CheckConstraint(
            "matchup_score IS NULL OR matchup_score BETWEEN 0 AND 100",
            name="matchup_score_range",
        ),
        CheckConstraint(
            "defense_rank_vs_position IS NULL OR defense_rank_vs_position BETWEEN 1 AND 32",
            name="defense_rank_range",
        ),
        CheckConstraint(
            "injury_multiplier IS NULL OR injury_multiplier BETWEEN 0 AND 1",
            name="injury_multiplier_range",
        ),
        # Weekly rankings and position boards: the dominant read pattern.
        Index("ix_projections_slate", "season", "week", "position"),
        # A player's projection history, newest first.
        Index("ix_projections_player_history", "player_id", "season", "week"),
        Index("ix_projections_game", "game_id"),
        Index("ix_projections_team_slate", "team", "season", "week"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<Projection id={self.id} player={self.player_id} "
            f"{self.season}w{self.week} run={self.model_run_id}>"
        )


class ProjectionPoints(Base):
    """Fantasy-point distribution for one projection under one scoring format.

    Weekly *distributions* are the point of this table, not the point estimate.
    Position shapes differ enough to change lineup decisions on their own: over
    2024-25 at 50%+ snaps, tight ends finish under five points 48.5% of the
    time and wide receivers 37.2%, against 10.1% for running backs. A single
    projected number cannot express that; floor/median/ceiling plus explicit
    boom and bust probabilities can.

    ``boom_threshold`` and ``bust_threshold`` are stored alongside the
    probabilities because those probabilities are meaningless without them, and
    the thresholds are position-dependent. Storing them is not duplication —
    it is the unit on the measurement.
    """

    __tablename__ = "projection_points"

    projection_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("projections.id", ondelete="CASCADE"),
        primary_key=True,
    )
    scoring_profile: Mapped[str] = mapped_column(String(32), primary_key=True)

    predicted_points: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        doc=(
            "The model's raw output, before distribution calibration. Kept for "
            "lineage and debugging; it is conditionally biased by construction "
            "because shrinkage trades bias for variance."
        ),
    )
    expected_points: Mapped[float | None] = mapped_column(
        Float,
        doc=(
            "Mean of the held-out outcome distribution — the calibrated "
            "expectation. **This is the headline number** and what a simulator "
            "should use. Measured conditional bias within +/-0.15 points across "
            "every projection band up to 20."
        ),
    )
    floor_points: Mapped[float | None] = mapped_column(Float, doc="P10")
    p25_points: Mapped[float | None] = mapped_column(Float, doc="P25")
    median_points: Mapped[float | None] = mapped_column(Float, doc="P50")
    p75_points: Mapped[float | None] = mapped_column(Float, doc="P75")
    ceiling_points: Mapped[float | None] = mapped_column(Float, doc="P90")
    standard_deviation: Mapped[float | None] = mapped_column(
        Float, doc="SD of the held-out outcome distribution."
    )

    confidence: Mapped[float | None] = mapped_column(
        Float, doc="0-1. How much information the model had, not how good it is."
    )
    boom_probability: Mapped[float | None] = mapped_column(
        Float, doc="P(points >= boom_threshold)"
    )
    bust_probability: Mapped[float | None] = mapped_column(
        Float, doc="P(points <= bust_threshold)"
    )
    boom_threshold: Mapped[float | None] = mapped_column(Float)
    bust_threshold: Mapped[float | None] = mapped_column(Float)

    calibration_method: Mapped[str | None] = mapped_column(
        String(48),
        doc=(
            "How the distribution was produced, e.g. "
            "'heldout_residual_quantiles_v1'. Stored per row so a projection "
            "stays interpretable after the method changes."
        ),
    )
    distribution_samples: Mapped[int | None] = mapped_column(
        Integer,
        doc="Held-out residuals behind this distribution. The honesty flag: a "
            "wide interval from 40 observations is not the same claim as one "
            "from 4,000.",
    )
    extrapolated: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        doc="True when the projection exceeded anything seen when fitting.",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    projection: Mapped[Projection] = relationship(back_populates="points")

    __table_args__ = (
        CheckConstraint(
            "scoring_profile IN " + sql_in_list(ScoringProfile),
            name="scoring_profile_known",
        ),
        # Percentiles must be ordered end to end: P10 <= P25 <= P50 <= P75 <= P90.
        # A model emitting a ceiling below its floor is broken, and it should
        # fail at write time rather than reach a start/sit screen.
        CheckConstraint(
            "floor_points IS NULL OR p25_points IS NULL OR floor_points <= p25_points",
            name="p10_le_p25",
        ),
        CheckConstraint(
            "p25_points IS NULL OR median_points IS NULL OR p25_points <= median_points",
            name="p25_le_p50",
        ),
        CheckConstraint(
            "median_points IS NULL OR p75_points IS NULL OR median_points <= p75_points",
            name="p50_le_p75",
        ),
        CheckConstraint(
            "p75_points IS NULL OR ceiling_points IS NULL OR p75_points <= ceiling_points",
            name="p75_le_p90",
        ),
        # The P10 <= P50 <= P90 chain is *also* asserted directly, not just via
        # P25 and P75. Each link is NULL-permissive, so with the quartiles absent
        # the chained constraints all evaluate to NULL and a reversed
        # floor/median/ceiling would slip through. These two close that gap for
        # any writer that supplies only the three-point summary.
        CheckConstraint(
            "floor_points IS NULL OR median_points IS NULL OR floor_points <= median_points",
            name="floor_le_median",
        ),
        CheckConstraint(
            "median_points IS NULL OR ceiling_points IS NULL OR median_points <= ceiling_points",
            name="median_le_ceiling",
        ),
        CheckConstraint(
            "standard_deviation IS NULL OR standard_deviation >= 0",
            name="standard_deviation_non_negative",
        ),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_range"
        ),
        CheckConstraint(
            "boom_probability IS NULL OR boom_probability BETWEEN 0 AND 1",
            name="boom_probability_range",
        ),
        CheckConstraint(
            "bust_probability IS NULL OR bust_probability BETWEEN 0 AND 1",
            name="bust_probability_range",
        ),
        # Rankings sort by points within a format; this index serves that
        # directly and avoids a sort over the whole slate.
        Index(
            "ix_projection_points_ranking",
            "scoring_profile",
            text("predicted_points DESC"),
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<ProjectionPoints projection={self.projection_id} "
            f"{self.scoring_profile} {self.predicted_points:.1f}>"
        )
