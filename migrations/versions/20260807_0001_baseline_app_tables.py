"""Baseline: adopt the ETL run log, add prediction-engine tables.

Revision ID: 0001_app_baseline
Revises:
Created: 2026-08-07

This is the first migration against a database that already contains data. It
therefore has to be an *adoption*, not a creation:

* ``pipeline_runs`` / ``pipeline_run_datasets`` already exist on any warehouse
  the pipeline has ever run against, created imperatively by
  ``nflfp.warehouse.ensure_run_log``. Recreating them would fail; ignoring them
  would leave them permanently outside version control. So they are created
  only if absent, and from that point Alembic owns their shape.
* ``raw_*`` tables and the derived views are untouched and always will be —
  see ``migrations/env.py``.

Everything below runs inside one transaction (Postgres has transactional DDL),
so a failure part-way through leaves the schema exactly as it was.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_app_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Enum values are inlined rather than imported from nflfp.db.enums. A migration
# is a historical record: it must keep producing the schema it produced on the
# day it was written, even after the application's enums have moved on.
MODEL_RUN_STATUSES = ("pending", "running", "succeeded", "failed", "published", "superseded")
SCORING_PROFILES = ("standard", "half_ppr", "ppr", "ppr_te_premium")


def _in_list(values: Sequence[str]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    _create_run_log_if_absent()
    _create_model_runs()
    _create_projections()
    _create_projection_points()


def downgrade() -> None:
    op.drop_table("projection_points")
    op.drop_table("projections")
    op.drop_table("model_runs")
    # pipeline_runs / pipeline_run_datasets are intentionally NOT dropped.
    # They predate this migration on existing databases and hold operational
    # history the ETL keeps writing regardless of schema version. A schema
    # rollback should not destroy an audit trail.


# ---------------------------------------------------------------------------
# ETL run log (adopted)
# ---------------------------------------------------------------------------

# Byte-for-byte the DDL in nflfp.warehouse.RUN_LOG_DDL, inlined rather than
# imported. A migration is a historical record: it must keep producing the
# schema it produced on the day it was written, and importing live application
# code would silently change that. `tests/test_migrations.py` asserts the two
# stay in agreement.
#
# `IF NOT EXISTS` rather than runtime introspection, so `alembic upgrade head
# --sql` emits reviewable DDL instead of failing on a MockConnection.
RUN_LOG_DDL = """
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id       BIGSERIAL PRIMARY KEY,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    mode         TEXT    NOT NULL,
    seasons      TEXT,
    status       TEXT    NOT NULL DEFAULT 'running',
    rows_loaded  BIGINT  NOT NULL DEFAULT 0,
    error        TEXT
);

CREATE TABLE IF NOT EXISTS pipeline_run_datasets (
    run_id       BIGINT  NOT NULL REFERENCES pipeline_runs(run_id) ON DELETE CASCADE,
    dataset      TEXT    NOT NULL,
    action       TEXT    NOT NULL,
    rows_loaded  BIGINT  NOT NULL DEFAULT 0,
    duration_ms  INTEGER NOT NULL DEFAULT 0,
    error        TEXT,
    PRIMARY KEY (run_id, dataset)
);

CREATE INDEX IF NOT EXISTS pipeline_runs_started_idx ON pipeline_runs (started_at DESC);
"""


def _create_run_log_if_absent() -> None:
    """Bring the ETL run log under version control without disturbing it."""
    op.execute(RUN_LOG_DDL)


# ---------------------------------------------------------------------------
# prediction engine
# ---------------------------------------------------------------------------

def _create_model_runs() -> None:
    op.create_table(
        "model_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("model_name", sa.String(length=64), nullable=False),
        sa.Column("model_version", sa.String(length=32), nullable=False),
        sa.Column("algorithm", sa.String(length=32), nullable=False),
        sa.Column("season", sa.SmallInteger(), nullable=False),
        sa.Column("week", sa.SmallInteger(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("feature_schema_version", sa.Integer(), nullable=False),
        sa.Column("code_sha", sa.String(length=40), nullable=True),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"status IN {_in_list(MODEL_RUN_STATUSES)}", name="status_known"
        ),
        sa.CheckConstraint(
            "season BETWEEN 1999 AND 2200", name="season_plausible"
        ),
        sa.CheckConstraint(
            "week IS NULL OR week BETWEEN 1 AND 25", name="week_plausible"
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at",
            name="finished_after_started",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model_runs"),
    )

    # The publish interlock: at most one live run per model per week. Partial,
    # so failed and superseded runs accumulate freely for comparison.
    op.create_index(
        "uq_model_runs_published",
        "model_runs",
        ["model_name", "season", "week"],
        unique=True,
        postgresql_where=sa.text("status = 'published'"),
    )
    op.create_index(
        "ix_model_runs_season_week_status", "model_runs", ["season", "week", "status"]
    )


def _create_projections() -> None:
    op.create_table(
        "projections",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("model_run_id", sa.BigInteger(), nullable=False),
        # identity — nflverse natural keys, deliberately unconstrained
        sa.Column("player_id", sa.String(length=32), nullable=False),
        sa.Column("season", sa.SmallInteger(), nullable=False),
        sa.Column("week", sa.SmallInteger(), nullable=False),
        sa.Column("game_id", sa.String(length=32), nullable=True),
        sa.Column("team", sa.String(length=8), nullable=True),
        sa.Column("opponent", sa.String(length=8), nullable=True),
        sa.Column("position", sa.String(length=8), nullable=True),
        sa.Column("is_home", sa.Boolean(), nullable=True),
        # projected usage
        sa.Column("proj_snap_pct", sa.Float(), nullable=True),
        sa.Column("proj_target_share", sa.Float(), nullable=True),
        sa.Column("proj_rush_share", sa.Float(), nullable=True),
        sa.Column("proj_redzone_touches", sa.Float(), nullable=True),
        sa.Column("proj_team_plays", sa.Float(), nullable=True),
        sa.Column("proj_targets", sa.Float(), nullable=True),
        sa.Column("proj_receptions", sa.Float(), nullable=True),
        sa.Column("proj_carries", sa.Float(), nullable=True),
        sa.Column("proj_pass_attempts", sa.Float(), nullable=True),
        # projected production
        sa.Column("proj_passing_yards", sa.Float(), nullable=True),
        sa.Column("proj_passing_tds", sa.Float(), nullable=True),
        sa.Column("proj_interceptions", sa.Float(), nullable=True),
        sa.Column("proj_rushing_yards", sa.Float(), nullable=True),
        sa.Column("proj_rushing_tds", sa.Float(), nullable=True),
        sa.Column("proj_receiving_yards", sa.Float(), nullable=True),
        sa.Column("proj_receiving_tds", sa.Float(), nullable=True),
        # context and adjustments
        sa.Column("matchup_score", sa.Float(), nullable=True),
        sa.Column("defense_rank_vs_position", sa.SmallInteger(), nullable=True),
        sa.Column("injury_multiplier", sa.Float(), nullable=True),
        sa.Column("weather_multiplier", sa.Float(), nullable=True),
        sa.Column("vegas_implied_total", sa.Float(), nullable=True),
        sa.Column("team_spread", sa.Float(), nullable=True),
        sa.Column("features", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("week BETWEEN 1 AND 25", name="week_plausible"),
        sa.CheckConstraint(
            "season BETWEEN 1999 AND 2200", name="season_plausible"
        ),
        sa.CheckConstraint(
            "proj_snap_pct IS NULL OR proj_snap_pct BETWEEN 0 AND 1",
            name="snap_pct_fraction",
        ),
        sa.CheckConstraint(
            "proj_target_share IS NULL OR proj_target_share BETWEEN 0 AND 1",
            name="target_share_fraction",
        ),
        sa.CheckConstraint(
            "matchup_score IS NULL OR matchup_score BETWEEN 0 AND 100",
            name="matchup_score_range",
        ),
        sa.CheckConstraint(
            "defense_rank_vs_position IS NULL OR defense_rank_vs_position BETWEEN 1 AND 32",
            name="defense_rank_range",
        ),
        sa.CheckConstraint(
            "injury_multiplier IS NULL OR injury_multiplier BETWEEN 0 AND 1",
            name="injury_multiplier_range",
        ),
        sa.ForeignKeyConstraint(
            ["model_run_id"],
            ["model_runs.id"],
            name="fk_projections_model_run_id_model_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_projections"),
        sa.UniqueConstraint(
            "model_run_id", "player_id", "season", "week", name="uq_projections_identity"
        ),
    )

    op.create_index("ix_projections_slate", "projections", ["season", "week", "position"])
    op.create_index(
        "ix_projections_player_history", "projections", ["player_id", "season", "week"]
    )
    op.create_index("ix_projections_game", "projections", ["game_id"])
    op.create_index("ix_projections_team_slate", "projections", ["team", "season", "week"])


def _create_projection_points() -> None:
    op.create_table(
        "projection_points",
        sa.Column("projection_id", sa.BigInteger(), nullable=False),
        sa.Column("scoring_profile", sa.String(length=32), nullable=False),
        sa.Column("predicted_points", sa.Float(), nullable=False),
        sa.Column("floor_points", sa.Float(), nullable=True),
        sa.Column("median_points", sa.Float(), nullable=True),
        sa.Column("ceiling_points", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("boom_probability", sa.Float(), nullable=True),
        sa.Column("bust_probability", sa.Float(), nullable=True),
        sa.Column("boom_threshold", sa.Float(), nullable=True),
        sa.Column("bust_threshold", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"scoring_profile IN {_in_list(SCORING_PROFILES)}",
            name="scoring_profile_known",
        ),
        sa.CheckConstraint(
            "floor_points IS NULL OR median_points IS NULL OR floor_points <= median_points",
            name="floor_le_median",
        ),
        sa.CheckConstraint(
            "median_points IS NULL OR ceiling_points IS NULL "
            "OR median_points <= ceiling_points",
            name="median_le_ceiling",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1",
            name="confidence_range",
        ),
        sa.CheckConstraint(
            "boom_probability IS NULL OR boom_probability BETWEEN 0 AND 1",
            name="boom_probability_range",
        ),
        sa.CheckConstraint(
            "bust_probability IS NULL OR bust_probability BETWEEN 0 AND 1",
            name="bust_probability_range",
        ),
        sa.ForeignKeyConstraint(
            ["projection_id"],
            ["projections.id"],
            name="fk_projection_points_projection_id_projections",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "projection_id", "scoring_profile", name="pk_projection_points"
        ),
    )

    op.create_index(
        "ix_projection_points_ranking",
        "projection_points",
        ["scoring_profile", sa.text("predicted_points DESC")],
    )
