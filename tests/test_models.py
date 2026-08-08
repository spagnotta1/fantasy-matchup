"""Schema tests for the ORM models.

Split into two halves:

* metadata assertions that need no database — the ownership boundary, the
  indexes the read path depends on, the absence of foreign keys into the
  warehouse;
* integration tests that insert real rows, because a ``CHECK`` constraint that
  has never been exercised against Postgres is only a comment.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from nflfp.db import ModelRun, Projection, ProjectionPoints
from nflfp.db.base import metadata
from nflfp.db.enums import Algorithm, ModelRunStatus, ScoringProfile

from .conftest import requires_db

APP_TABLES = {
    # prediction engine output (Layer 1)
    "model_runs",
    "projections",
    "projection_points",
    # ETL bookkeeping
    "pipeline_runs",
    "pipeline_run_datasets",
    "job_runs",
    # external provider snapshots (Layer 2)
    "weather_forecasts",
    "odds_snapshots",
}


# ---------------------------------------------------------------------------
# metadata — no database required
# ---------------------------------------------------------------------------

def test_metadata_contains_only_application_tables():
    """The ownership boundary, asserted.

    If a warehouse table is ever mapped here, Alembic autogenerate becomes
    capable of dropping it.
    """
    assert set(metadata.tables) == APP_TABLES


def test_no_warehouse_tables_mapped():
    for name in metadata.tables:
        assert not name.startswith(("raw_", "stg_")), name
        assert name not in {"player_week", "game_team", "upcoming_games"}


def test_no_foreign_keys_point_into_the_warehouse():
    """FKs into weekly-swapped tables would either block the swap or be
    destroyed by the CASCADE that performs it."""
    for table in metadata.tables.values():
        for fk in table.foreign_keys:
            assert fk.column.table.name in APP_TABLES, (
                f"{table.name} references {fk.column.table.name}, "
                "which this application does not own"
            )


def test_projection_carries_warehouse_keys_without_constraints():
    projections = metadata.tables["projections"]
    for column in ("player_id", "game_id", "team"):
        assert column in projections.c
        assert not projections.c[column].foreign_keys


@pytest.mark.parametrize(
    "table, index_name",
    [
        ("projections", "ix_projections_slate"),
        ("projections", "ix_projections_player_history"),
        ("model_runs", "uq_model_runs_published"),
        ("projection_points", "ix_projection_points_ranking"),
    ],
)
def test_read_path_indexes_exist(table, index_name):
    """These back the dominant queries: weekly rankings, a player's history,
    and resolving the currently published run."""
    assert index_name in {ix.name for ix in metadata.tables[table].indexes}


def test_publish_index_is_partial_and_unique():
    """One published run per model per week; failed runs unconstrained."""
    index = next(
        ix for ix in metadata.tables["model_runs"].indexes
        if ix.name == "uq_model_runs_published"
    )
    assert index.unique is True
    where = index.dialect_options["postgresql"].get("where")
    assert where is not None and "published" in str(where)


def test_points_are_separated_from_components():
    """The normalisation that stops ~30 component columns being stored once per
    scoring format."""
    projections = metadata.tables["projections"]
    points = metadata.tables["projection_points"]

    assert "scoring_profile" not in projections.c
    assert "predicted_points" not in projections.c
    assert "scoring_profile" in points.c
    assert "proj_targets" not in points.c
    assert list(points.primary_key.columns.keys()) == ["projection_id", "scoring_profile"]


def test_cascade_deletes_are_declared():
    """Deleting a model run must not strand its projections."""
    for table, column in (("projections", "model_run_id"), ("projection_points", "projection_id")):
        fk = next(iter(metadata.tables[table].c[column].foreign_keys))
        assert fk.ondelete == "CASCADE"


# ---------------------------------------------------------------------------
# integration — real Postgres
# ---------------------------------------------------------------------------

def _run(**overrides) -> ModelRun:
    defaults = dict(
        model_name="weekly_points",
        model_version="0.1.0",
        algorithm=Algorithm.BASELINE.value,
        season=2026,
        week=1,
        status=ModelRunStatus.SUCCEEDED.value,
        feature_schema_version=1,
    )
    defaults.update(overrides)
    return ModelRun(**defaults)


def _projection(run: ModelRun, **overrides) -> Projection:
    defaults = dict(
        model_run=run,
        player_id="00-0034796",
        season=2026,
        week=1,
        team="BUF",
        opponent="NYJ",
        position="WR",
    )
    defaults.update(overrides)
    return Projection(**defaults)


@requires_db
@pytest.mark.integration
class TestPersistence:
    def test_round_trip_with_points_for_every_profile(self, db_session):
        run = _run()
        projection = _projection(run, proj_targets=8.4, proj_snap_pct=0.82)
        for profile in ScoringProfile:
            projection.points.append(
                ProjectionPoints(
                    scoring_profile=profile.value,
                    predicted_points=14.2,
                    floor_points=5.1,
                    median_points=13.4,
                    ceiling_points=27.9,
                    confidence=0.68,
                    boom_probability=0.24,
                    bust_probability=0.19,
                    boom_threshold=20.0,
                    bust_threshold=5.0,
                )
            )
        db_session.add(run)
        db_session.commit()

        loaded = db_session.get(Projection, projection.id)
        assert loaded is not None
        assert len(loaded.points) == len(ScoringProfile)
        assert loaded.proj_snap_pct == pytest.approx(0.82)

    def test_features_jsonb_round_trips(self, db_session):
        run = _run()
        payload = {"snap_pct_l4": 0.81, "opp_dvoa_rank": 27, "is_dome": True}
        db_session.add(_projection(run, features=payload))
        db_session.commit()

        stored = db_session.query(Projection).one()
        assert stored.features == payload

    def test_only_one_published_run_per_week(self, db_session):
        """The publish interlock. Two live runs would make the API's answer
        depend on row order."""
        db_session.add(_run(status=ModelRunStatus.PUBLISHED.value))
        db_session.commit()

        db_session.add(_run(model_version="0.2.0", status=ModelRunStatus.PUBLISHED.value))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_superseded_runs_are_unconstrained(self, db_session):
        """Only the partial index is unique — history must accumulate freely."""
        for version in ("0.1.0", "0.2.0", "0.3.0"):
            db_session.add(
                _run(model_version=version, status=ModelRunStatus.SUPERSEDED.value)
            )
        db_session.commit()
        assert db_session.query(ModelRun).count() == 3

    def test_duplicate_player_within_a_run_rejected(self, db_session):
        run = _run()
        db_session.add_all([_projection(run), _projection(run)])
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_unordered_quantiles_rejected(self, db_session):
        """A ceiling below the floor is a broken model, and it should fail at
        write time rather than reach a start/sit screen."""
        run = _run()
        projection = _projection(run)
        projection.points.append(
            ProjectionPoints(
                scoring_profile=ScoringProfile.PPR.value,
                predicted_points=12.0,
                floor_points=18.0,
                median_points=12.0,
                ceiling_points=6.0,
            )
        )
        db_session.add(run)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_unknown_scoring_profile_rejected(self, db_session):
        run = _run()
        projection = _projection(run)
        projection.points.append(
            ProjectionPoints(scoring_profile="superflex", predicted_points=12.0)
        )
        db_session.add(run)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    @pytest.mark.parametrize(
        "field, value",
        [
            ("proj_snap_pct", 1.4),
            ("proj_target_share", -0.1),
            ("matchup_score", 140.0),
            ("defense_rank_vs_position", 33),
            ("injury_multiplier", 2.0),
            ("week", 40),
        ],
    )
    def test_implausible_values_rejected(self, db_session, field, value):
        db_session.add(_projection(_run(), **{field: value}))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_probabilities_must_be_probabilities(self, db_session):
        run = _run()
        projection = _projection(run)
        projection.points.append(
            ProjectionPoints(
                scoring_profile=ScoringProfile.PPR.value,
                predicted_points=12.0,
                boom_probability=1.7,
            )
        )
        db_session.add(run)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_deleting_a_run_cascades(self, db_session):
        run = _run()
        projection = _projection(run)
        projection.points.append(
            ProjectionPoints(
                scoring_profile=ScoringProfile.HALF_PPR.value, predicted_points=9.9
            )
        )
        db_session.add(run)
        db_session.commit()

        db_session.delete(run)
        db_session.commit()

        assert db_session.query(Projection).count() == 0
        assert db_session.query(ProjectionPoints).count() == 0

    def test_timestamps_are_set_by_the_database(self, db_session):
        """Rows are also written by workers and by ad-hoc SQL; a timestamp that
        only appears when the ORM is in the call path is worse than none."""
        run = _run()
        db_session.add(run)
        db_session.commit()
        assert run.created_at is not None
        assert run.created_at.tzinfo is not None
