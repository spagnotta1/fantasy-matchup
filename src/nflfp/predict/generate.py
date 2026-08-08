"""Generating and persisting one week's projections.

This is the function the scheduled job calls, and the function the CLI calls.
It used to be the body of ``python -m nflfp.predict project``, which meant the
weekly production run existed only as an argparse handler — a shape that
survives exactly until someone needs to invoke it from anywhere else, at which
point the choice is to shell out to a CLI from inside a worker or to copy the
logic. Both are how a scheduled projection and a manual one start disagreeing
about what they produce.

The train/serve rule, restated where it is executed
---------------------------------------------------
Everything is fitted on games that have already been played, and the target
week contributes nothing to its own projection. That is the same rule Layer 2's
feature windows obey and Layer 3's walk-forward harness enforces; here it is a
pair of ``<`` comparisons on ``(season, week)`` tuples, and
:func:`_assert_trained_before` re-checks it against the rows rather than
trusting the comprehension that built them.

Why publishing lives here
-------------------------
A publish is the one event that can make a cached response wrong, so the epoch
bump belongs on the same code path — not at each call site, where the second
caller forgets. The bump is best-effort: a projection run that did its work
must not report failure because Redis was restarting.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..cache import invalidate_all_sync
from .dataset import load_rows
from .distribution import ResidualDistribution
from .persist import (
    ProjectionBundle,
    create_model_run,
    data_snapshot,
    finish_run,
    persist_projections,
    publish_run,
)
from .registry import get_model_factory
from .scoring_bridge import score_components

logger = logging.getLogger(__name__)

#: Scoring profile whose residuals fit the distribution. The distribution is
#: fitted once and applied to every profile, because a residual is a property
#: of how wrong the *components* were; refitting per profile would be four
#: passes over the same errors expressed in different units.
DISTRIBUTION_PROFILE = "half_ppr"


@dataclass
class GenerationResult:
    """What a projection run produced, in a form a job log can store."""

    model_run_id: int | None
    model_name: str
    model_version: str
    season: int
    week: int
    projections_written: int = 0
    residual_samples: int = 0
    published: bool = False
    cache_epoch: int | None = None
    skipped: bool = False
    skip_reason: str = ""
    #: Players present in the target week but not projected, by reason.
    unprojected: dict[str, int] = field(default_factory=dict)

    def as_detail(self) -> dict:
        """JSON-serialisable summary for ``job_runs.detail``."""
        return {key: value for key, value in asdict(self).items() if value not in (None, {})}


def resolve_target_week(session: Session, season: int | None = None) -> tuple[int, int] | None:
    """The season and week a scheduled run should project.

    The upcoming slate — the earliest scheduled week with no result — which is
    the same definition :mod:`nflfp.services.catalog` resolves for a reader.
    The two must agree: a job that projects week 11 while every endpoint
    defaults to week 12 produces an empty board and no error anywhere.

    Returns:
        ``(season, week)``, or None when the season has no unplayed games —
        which in February is correct and not a failure.
    """
    from ..sources import current_season

    resolved_season = season if season is not None else current_season()
    week = session.execute(
        text("SELECT min(week) FROM upcoming_games WHERE season = :season"),
        {"season": resolved_season},
    ).scalar()
    if week is None:
        return None
    return resolved_season, int(week)


def generate_week(
    session: Session,
    *,
    model_name: str,
    season: int,
    week: int,
    publish: bool = False,
    profile: str = DISTRIBUTION_PROFILE,
) -> GenerationResult:
    """Fit, project, persist and optionally publish one week.

    Args:
        session: Open synchronous session. The caller owns the transaction —
            this function flushes but never commits, so a job that fails
            afterwards leaves no half-written run.
        model_name: A model registered in :mod:`nflfp.predict.registry`.
        season: Season to project.
        week: Week to project.
        publish: Make the run live for its ``(model, season, week)``, and retire
            the cache namespace.
        profile: Scoring profile whose residuals fit the distribution.

    Returns:
        A :class:`GenerationResult`. A week with no target rows returns
        ``skipped=True`` rather than raising: "the schedule has not been
        ingested yet" is an operational state a job should record and move on
        from, not a stack trace at 4am.

    Raises:
        KeyError: if `model_name` is not registered.
    """
    factory = get_model_factory(model_name)
    probe = factory()

    targets = [
        row
        for row in load_rows(session, seasons=[season])
        if int(row["week"]) == week
    ]
    if not targets:
        logger.warning("no feature rows for %s week %s", season, week)
        return GenerationResult(
            model_run_id=None,
            model_name=probe.name,
            model_version=probe.version,
            season=season,
            week=week,
            skipped=True,
            skip_reason=(
                f"no rows in feat_training_dataset for {season} week {week}; "
                "the warehouse or the feature views may not be built yet"
            ),
        )

    history = load_rows(session, completed_only=True)
    cutoff = (season, week)
    train = [row for row in history if (int(row["season"]), int(row["week"])) < cutoff]
    _assert_trained_before(train, cutoff)

    model = factory()
    model.fit(train)

    distribution, samples = _fit_distribution(
        factory, history, cutoff=cutoff, profile=profile
    )

    run = create_model_run(
        session,
        model_name=model.name,
        model_version=model.version,
        algorithm=model.algorithm,
        season=season,
        week=week,
        params=model.params(),
        snapshot=data_snapshot(session),
    )

    bundles, unprojected = _bundle(model, targets, distribution)
    written = persist_projections(session, run, bundles)
    finish_run(
        session,
        run,
        status="succeeded",
        metrics={
            "projections": written,
            "residual_samples": len(samples),
            "targets": len(targets),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    result = GenerationResult(
        model_run_id=run.id,
        model_name=model.name,
        model_version=model.version,
        season=season,
        week=week,
        projections_written=written,
        residual_samples=len(samples),
        unprojected=unprojected,
    )

    if publish:
        publish_run(session, run)
        result.published = True
        # After the flush, not before: bumping the epoch first would let a
        # reader repopulate the cache from the still-current published run and
        # then find that run superseded, leaving the stale body in the *new*
        # namespace where nothing will retire it.
        session.flush()
        result.cache_epoch = invalidate_all_sync()

    logger.info(
        "generated projections",
        extra={
            "model": model.name,
            "season": season,
            "week": week,
            "projections": written,
            "published": result.published,
        },
    )
    return result


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------


def _assert_trained_before(train: list[dict], cutoff: tuple[int, int]) -> None:
    """Re-check the leakage rule against the rows themselves.

    The same defence ``assert_no_leakage`` provides in the backtest, applied to
    the production path — which is the one that matters, and the one that would
    otherwise be the only place the rule is enforced by a comprehension nobody
    re-reads. A projection trained on its own week backtests fine and is
    worthless on Thursday.

    Raises:
        ValueError: if any training row is at or after the target week.
    """
    offenders = [
        row for row in train if (int(row["season"]), int(row["week"])) >= cutoff
    ]
    if offenders:
        raise ValueError(
            f"{len(offenders)} training row(s) at or after {cutoff}; "
            "the target week must contribute nothing to its own projection"
        )


def _fit_distribution(
    factory, history: list[dict], *, cutoff: tuple[int, int], profile: str
) -> tuple[ResidualDistribution, list[tuple[str, float, float]]]:
    """Fit the outcome distribution on genuinely held-out residuals.

    A model is refitted on everything before the *previous* season and run
    forward over the seasons since. Every residual is therefore out of fold
    twice — with respect to the model that produced it, and in the past
    relative to the week it describes — which is the property Layer 3b
    established and the reason the stated intervals cover what they claim.

    Fitting the distribution on the same predictions it will describe is the
    mistake phase 3a made: it understates width, and understated width is what
    produced a stated 94% boom probability that delivered 17%.
    """
    residual_cutoff = (cutoff[0] - 1, 1)
    residual_train = [
        row for row in history if (int(row["season"]), int(row["week"])) < residual_cutoff
    ]
    residual_eval = [
        row
        for row in history
        if residual_cutoff <= (int(row["season"]), int(row["week"])) < cutoff
    ]

    residual_model = factory()
    residual_model.fit(residual_train)

    samples: list[tuple[str, float, float]] = []
    for row, prediction in zip(residual_eval, residual_model.predict(residual_eval)):
        actual = row.get(f"fp_{profile}_actual")
        if actual is None:
            continue
        points = score_components(prediction.components, position=prediction.position)[profile]
        samples.append((prediction.position, points, float(actual)))

    return ResidualDistribution().fit(samples), samples


def _bundle(model, targets: list[dict], distribution: ResidualDistribution):
    """Score each target and attach a distribution per scoring profile.

    A player for whom no profile yields a distribution is **dropped, counted
    and reported** rather than stored with a point estimate and no interval.
    Layer 3b's whole claim is that the interval is the product; a row carrying
    a number with no honest spread would be indistinguishable in the API from
    one that has been measured.
    """
    bundles: list[ProjectionBundle] = []
    unprojected: dict[str, int] = {}

    for row, prediction in zip(targets, model.predict(targets)):
        points_by_profile = score_components(
            prediction.components, position=prediction.position
        )
        distributions = {}
        for scoring_profile, points in points_by_profile.items():
            try:
                distributions[scoring_profile] = distribution.apply(
                    prediction.position, points
                )
            except ValueError:
                continue
        if not distributions:
            key = f"no_distribution_{prediction.position}"
            unprojected[key] = unprojected.get(key, 0) + 1
            continue
        bundles.append(
            ProjectionBundle(
                prediction=prediction,
                distributions=distributions,
                context={
                    "game_id": row.get("game_id"),
                    "team": row.get("team"),
                    "opponent": row.get("opponent"),
                    "is_home": row.get("is_home"),
                },
            )
        )

    return bundles, unprojected
