"""Persisting projections, with the lineage needed to reproduce them.

Reproducibility contract
------------------------
A stored projection must remain interpretable and reproducible after the model
that produced it has been superseded. That requires recording, per run:

* which model and version, and which algorithm family;
* which feature contract version (``FEATURE_VERSION``) — the feature vector in
  ``Projection.features`` is schema-less JSONB and is meaningless without it;
* which calibration method produced the distribution;
* the fitted parameters, so the model can be rebuilt from the code plus the row;
* a snapshot of the input data, so "the warehouse has since been refreshed" is
  a detectable explanation rather than a mystery.

**Nothing is ever overwritten.** A new model writes a new ``model_runs`` row and
a new set of projections. Publishing moves a flag; the previous run stays on
disk with its projections intact. That is what makes "what did we say in week 8,
and why?" answerable months later, and it is enforced by the partial unique
index rather than by convention.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..db.enums import ModelRunStatus
from ..db.models.projection import ModelRun, Projection, ProjectionPoints
from .base import ComponentPrediction
from .distribution import PointDistribution
from .features import FEATURE_VERSION
from .scoring_bridge import COMPONENT_TO_COLUMN

logger = logging.getLogger(__name__)

#: Identifies how a distribution was produced. Stored per row so that a
#: projection written today stays interpretable after the method changes.
CALIBRATION_METHOD = "heldout_residual_quantiles_v1"

#: Component -> the `projections` column that stores it.
_COMPONENT_COLUMNS = {
    "passing_yards": "proj_passing_yards",
    "passing_tds": "proj_passing_tds",
    "passing_interceptions": "proj_interceptions",
    "rushing_yards": "proj_rushing_yards",
    "rushing_tds": "proj_rushing_tds",
    "receptions": "proj_receptions",
    "receiving_yards": "proj_receiving_yards",
    "receiving_tds": "proj_receiving_tds",
}


@dataclass
class ProjectionBundle:
    """One player-week ready to persist: components plus a distribution per profile."""

    prediction: ComponentPrediction
    distributions: dict[str, PointDistribution]
    #: Extra context for `projections`, e.g. game_id, team, opponent.
    context: dict = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.context is None:
            self.context = {}


def data_snapshot(session: Session) -> dict:
    """Describe the warehouse state the projections were built from.

    Without this, a projection that cannot be reproduced is indistinguishable
    from a bug. With it, "the warehouse was refreshed on Tuesday" is a checkable
    explanation.
    """
    snapshot: dict = {"captured_at": datetime.now(timezone.utc).isoformat()}
    try:
        snapshot["last_pipeline_run"] = session.execute(
            text("SELECT max(run_id) FROM pipeline_runs WHERE status = 'ok'")
        ).scalar()
        snapshot["player_week_rows"] = session.execute(
            text("SELECT count(*) FROM feat_training_dataset")
        ).scalar()
    except Exception:  # pragma: no cover - warehouse may be partially built
        logger.warning("could not capture a full data snapshot", exc_info=True)
    return snapshot


def code_sha() -> str | None:
    """Current git commit, when the working tree is a repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return result.stdout.strip()[:40] or None
    except Exception:  # pragma: no cover - git may be absent
        return None


def create_model_run(
    session: Session,
    *,
    model_name: str,
    model_version: str,
    algorithm: str,
    season: int,
    week: int | None,
    params: dict | None = None,
    metrics: dict | None = None,
    snapshot: dict | None = None,
) -> ModelRun:
    """Open a ``model_runs`` row. Always a new row — never an update."""
    run = ModelRun(
        model_name=model_name,
        model_version=model_version,
        algorithm=algorithm,
        season=season,
        week=week,
        status=ModelRunStatus.RUNNING.value,
        feature_schema_version=FEATURE_VERSION,
        code_sha=code_sha(),
        params={**(params or {}), "data_snapshot": snapshot or {}},
        metrics=metrics,
        started_at=datetime.now(timezone.utc),
    )
    session.add(run)
    session.flush()
    logger.info("opened model run %d for %s w%s", run.id, season, week)
    return run


def persist_projections(
    session: Session, run: ModelRun, bundles: Sequence[ProjectionBundle]
) -> int:
    """Write projections and their per-profile distributions.

    Returns:
        Number of projections written.
    """
    for bundle in bundles:
        prediction = bundle.prediction
        projection = Projection(
            model_run_id=run.id,
            player_id=prediction.player_id,
            season=prediction.season,
            week=prediction.week,
            position=prediction.position,
            features=prediction.explain,
            **{
                column: prediction.components.get(component)
                for component, column in _COMPONENT_COLUMNS.items()
            },
            **{
                key: value
                for key, value in bundle.context.items()
                if key in {"game_id", "team", "opponent", "is_home"}
            },
        )
        for profile, band in bundle.distributions.items():
            projection.points.append(
                ProjectionPoints(
                    scoring_profile=profile,
                    predicted_points=band.predicted_points,
                    expected_points=band.expected_points,
                    floor_points=band.p10,
                    p25_points=band.p25,
                    median_points=band.p50,
                    p75_points=band.p75,
                    ceiling_points=band.p90,
                    standard_deviation=band.standard_deviation,
                    confidence=band.confidence,
                    boom_probability=band.boom_probability,
                    bust_probability=band.bust_probability,
                    boom_threshold=band.boom_threshold,
                    bust_threshold=band.bust_threshold,
                    calibration_method=CALIBRATION_METHOD,
                    distribution_samples=band.sample_size,
                    extrapolated=band.extrapolated,
                )
            )
        session.add(projection)

    session.flush()
    logger.info("persisted %d projection(s) for run %d", len(bundles), run.id)
    return len(bundles)


def finish_run(
    session: Session, run: ModelRun, *, status: str, metrics: dict | None = None
) -> None:
    """Close a run without publishing it."""
    run.status = status
    run.finished_at = datetime.now(timezone.utc)
    if metrics is not None:
        run.metrics = metrics
    session.flush()


def publish_run(session: Session, run: ModelRun) -> ModelRun:
    """Make a run the live one for its (model, season, week).

    Supersedes whatever was published before, inside one transaction. The
    partial unique index guarantees at most one published run, so this either
    swaps cleanly or fails — it cannot leave two live runs.

    The superseded run's projections are **not** deleted. That is what allows
    "what did we say last Thursday?" to be answered after a model change.
    """
    previous = session.scalars(
        select(ModelRun).where(
            ModelRun.model_name == run.model_name,
            ModelRun.season == run.season,
            ModelRun.week == run.week,
            ModelRun.status == ModelRunStatus.PUBLISHED.value,
            ModelRun.id != run.id,
        )
    ).all()
    for stale in previous:
        stale.status = ModelRunStatus.SUPERSEDED.value
        logger.info("superseded model run %d", stale.id)

    run.status = ModelRunStatus.PUBLISHED.value
    run.published_at = datetime.now(timezone.utc)
    if run.finished_at is None:
        run.finished_at = run.published_at
    session.flush()
    logger.info("published model run %d", run.id)
    return run


def published_run(
    session: Session, *, model_name: str, season: int, week: int
) -> ModelRun | None:
    """The live run for a week, or None."""
    return session.scalars(
        select(ModelRun).where(
            ModelRun.model_name == model_name,
            ModelRun.season == season,
            ModelRun.week == week,
            ModelRun.status == ModelRunStatus.PUBLISHED.value,
        )
    ).first()


def load_distribution(
    session: Session,
    *,
    player_id: str,
    season: int,
    week: int,
    scoring_profile: str,
    model_name: str | None = None,
) -> ProjectionPoints | None:
    """The published outcome distribution for one player-week.

    **This is the interface the Monte Carlo simulation engine will call.** It
    returns a full distribution — percentiles and standard deviation — so a
    simulator never reconstructs one from ``expected +/- some percentage``.

    Args:
        session: Open session.
        player_id: nflverse gsis id.
        season: Season.
        week: Week.
        scoring_profile: League format.
        model_name: Restrict to one model; otherwise any published run.

    Returns:
        The stored distribution, or None if nothing is published for that week.
    """
    statement = (
        select(ProjectionPoints)
        .join(Projection, Projection.id == ProjectionPoints.projection_id)
        .join(ModelRun, ModelRun.id == Projection.model_run_id)
        .where(
            Projection.player_id == player_id,
            Projection.season == season,
            Projection.week == week,
            ProjectionPoints.scoring_profile == scoring_profile,
            ModelRun.status == ModelRunStatus.PUBLISHED.value,
        )
    )
    if model_name:
        statement = statement.where(ModelRun.model_name == model_name)
    return session.scalars(statement).first()


def projection_count(session: Session, run: ModelRun) -> int:
    """How many projections a run produced."""
    return session.scalar(
        select(func.count()).select_from(Projection).where(Projection.model_run_id == run.id)
    ) or 0


def component_columns() -> dict[str, str]:
    """The component -> column mapping, exposed for tests."""
    return dict(_COMPONENT_COLUMNS)
