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
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..cache import invalidate_all_sync
from .dataset import PRESEASON_TABLE, SOURCE_TABLE, load_rows
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

#: Smallest training set a week may be projected from. Below this the shrinkage
#: priors are fitted on noise, and the resulting board would carry the
#: authority of a model without the accuracy — the thing the frozen foundation
#: exists to prevent. Matches ``dataset.walk_forward``'s own floor so a
#: backfilled week and a backtested one cover the same ground.
MIN_TRAIN_ROWS = 500

#: Smallest sample the *residual* model may be fitted on. This is a separate
#: floor because it binds a season earlier than the one above: the held-out
#: distribution refits on everything before the *previous* season, so the first
#: two seasons in the warehouse have a full training set and no residual
#: history at all. Projecting them anyway would store point estimates whose
#: intervals came from a model fitted on nothing.
MIN_RESIDUAL_TRAIN_ROWS = 500


@dataclass
class FitCache:
    """Rows and residual fits shared across the weeks of one backfill.

    :func:`generate_week` reloads everything it needs on every call, which is
    right for the weekly job: it runs once, and a few seconds of redundant I/O
    is a good price for having no state to get wrong. A backfill calls it ~140
    times, where that redundancy is most of the wall clock and the reloaded
    inputs are identical every time.

    So this memoises the parts that provably do not vary within a season — the
    completed-week history, a season's feature rows, and the residual model's
    scored output — and nothing else. The backfill loop still calls the same
    :func:`generate_week`, so a backfilled week and a scheduled one come from
    one implementation rather than two that have to be kept in agreement.

    Hoisting the residual predictions is only sound because a model's
    ``predict`` is row-wise: it maps each row independently, so scoring a
    range once and filtering it per week yields exactly what scoring each
    week's sub-range separately would have. That is a property of
    :class:`~nflfp.predict.base.ComponentModel`, not an assumption about one
    model, and :func:`generate_week` with ``cache=None`` remains the
    definition this is checked against.
    """

    #: Completed player-weeks, all seasons. The training pool.
    history: list[dict] | None = None
    #: Season -> every feature row for it, completed or not.
    season_rows: dict[int, list[dict]] = field(default_factory=dict)
    #: (residual cutoff, profile) -> scored residuals, each tagged with the
    #: (season, week) it came from so a week can take the prefix it is
    #: entitled to.
    residuals: dict[
        tuple[tuple[int, int], str], list[tuple[tuple[int, int], str, float, float]]
    ] = field(default_factory=dict)


def _ordinal(row: dict) -> tuple[int, int]:
    return (int(row["season"]), int(row["week"]))


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
    cache: FitCache | None = None,
    invalidate: bool = True,
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
        cache: Optional :class:`FitCache` shared across the weeks of a
            backfill. ``None`` — the weekly job's path — loads everything
            fresh and is the behaviour every other path is defined against.
        invalidate: Whether a publish also retires the cache namespace. Only a
            backfill sets this ``False``, because bumping the epoch once per
            week for a hundred weeks retires namespaces nobody ever read; it
            bumps once when the whole run lands.

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

    targets = [row for row in _season_rows(session, season, cache) if int(row["week"]) == week]
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
                f"no rows in {SOURCE_TABLE} or {PRESEASON_TABLE} for {season} "
                f"week {week}; the warehouse or the feature views may not be "
                "built yet. A season that has not started can only be "
                f"projected for week 1, and only from {PRESEASON_TABLE}, which "
                "needs that season's schedule and rosters ingested."
            ),
        )

    history = _history(session, cache)
    cutoff = (season, week)
    train = [row for row in history if _ordinal(row) < cutoff]
    _assert_trained_before(train, cutoff)

    model = factory()
    model.fit(train)

    distribution, samples = _fit_distribution(
        factory, history, cutoff=cutoff, profile=profile, cache=cache
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
        if invalidate:
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
# backfill
# ---------------------------------------------------------------------------


@dataclass
class BackfillWeek:
    """One week a backfill produced or refused, and why."""

    season: int
    week: int
    projections: int = 0
    published: bool = False
    model_run_id: int | None = None
    skipped: bool = False
    skip_reason: str = ""

    @property
    def label(self) -> str:
        return f"{self.season}w{self.week:02d}"


@dataclass
class BackfillResult:
    """What a backfill covered, in a form a job log can store."""

    model_name: str
    model_version: str
    weeks: list[BackfillWeek] = field(default_factory=list)
    cache_epoch: int | None = None

    @property
    def generated(self) -> list[BackfillWeek]:
        return [entry for entry in self.weeks if not entry.skipped]

    @property
    def skipped(self) -> list[BackfillWeek]:
        return [entry for entry in self.weeks if entry.skipped]

    @property
    def projections_written(self) -> int:
        return sum(entry.projections for entry in self.generated)

    @property
    def seasons_covered(self) -> list[int]:
        return sorted({entry.season for entry in self.generated})

    def as_detail(self) -> dict:
        """JSON-serialisable summary for ``job_runs.detail``.

        Skips are summarised by reason rather than listed one per week. A
        hundred weeks refused for the same reason is one fact, and burying it
        in a hundred rows is how it stops being read.
        """
        reasons: dict[str, int] = {}
        for entry in self.skipped:
            reasons[entry.skip_reason] = reasons.get(entry.skip_reason, 0) + 1
        detail = {
            "model": self.model_name,
            "model_version": self.model_version,
            "weeks_generated": len(self.generated),
            "weeks_skipped": len(self.skipped),
            "projections": self.projections_written,
            "seasons": self.seasons_covered,
        }
        if reasons:
            detail["skipped_because"] = reasons
        if self.cache_epoch is not None:
            detail["cache_epoch"] = self.cache_epoch
        return detail


def available_weeks(
    session: Session, seasons: Sequence[int] | None = None
) -> list[tuple[int, int]]:
    """Every ``(season, week)`` the feature layer can project, chronologically.

    Read from ``feat_training_dataset`` rather than from the schedule, because
    what a week can be projected from is the feature layer's coverage, not the
    warehouse's. The two differ: the warehouse holds playoff weeks 19-22, and
    the feature layer stops at the fantasy regular season, which is the right
    scope and not a gap.
    """
    params: dict[str, object] = {}
    where = ""
    if seasons:
        where = "WHERE season = ANY(:seasons)"
        params["seasons"] = list(seasons)
    rows = session.execute(
        text(
            f"SELECT DISTINCT season, week FROM {SOURCE_TABLE} {where} "
            "ORDER BY season, week"
        ),
        params,
    )
    return [(int(season), int(week)) for season, week in rows]


def published_weeks(session: Session, model_name: str) -> set[tuple[int, int]]:
    """Weeks that already have a live board for this model."""
    rows = session.execute(
        text(
            "SELECT season, week FROM model_runs "
            "WHERE model_name = :model AND status = 'published'"
        ),
        {"model": model_name},
    )
    return {(int(season), int(week)) for season, week in rows}


def generate_backfill(
    session: Session,
    *,
    model_name: str,
    seasons: Sequence[int] | None = None,
    publish: bool = True,
    profile: str = DISTRIBUTION_PROFILE,
    skip_existing: bool = False,
    min_train_rows: int = MIN_TRAIN_ROWS,
    min_residual_train_rows: int = MIN_RESIDUAL_TRAIN_ROWS,
    commit_each: bool = False,
    on_week: Callable[[BackfillWeek], None] | None = None,
) -> BackfillResult:
    """Project and publish every week the feature layer can support.

    The weekly job produces one board a week, which means a fresh deployment
    can offer a user exactly one week to look at no matter how much history the
    warehouse holds. This walks the same generator over every week instead, so
    the season and week selectors — which are built from *published runs*, and
    correctly so — describe the whole warehouse rather than the last cron
    firing.

    Every week goes through :func:`generate_week` unchanged. A backfilled board
    is therefore the same object the Tuesday job would have written for that
    week, fitted on the same training set with the same leakage check, and the
    numbers behind a 2019 slate reconcile with a 2025 one because there is one
    implementation rather than a historical importer beside a live one.

    Args:
        session: Open synchronous session.
        model_name: A model registered in :mod:`nflfp.predict.registry`.
        seasons: Restrict to these seasons; every season with feature rows if
            omitted.
        publish: Make each run live. A backfill that does not publish stores
            boards no picker will ever offer, so this defaults ``True`` — the
            opposite of :func:`generate_week`, where the caller is usually
            evaluating a challenger.
        profile: Scoring profile whose residuals fit the distribution.
        skip_existing: Leave weeks that already have a published run alone.
            The way to extend a backfill after adding a season without
            reprojecting what is already there.
        min_train_rows: Refuse a week with less training data than this.
        min_residual_train_rows: Refuse a week whose *residual* model would be
            fitted on less than this. Binds a season earlier than the above.
        commit_each: Commit after each week. A backfill is minutes of work and
            every week it produces is independently valid, so losing 130 good
            boards because the 131st failed is a worse trade than a long
            transaction avoids.
        on_week: Called after each week, for progress reporting. A backfill is
            long enough that silence reads as a hang.

    Returns:
        A :class:`BackfillResult` listing every week generated and every week
        refused with its reason. Weeks are **refused, never approximated**: the
        first seasons in the warehouse have no prior season for the residual
        model to learn from, and a board whose interval came from a model
        fitted on nothing is exactly what Layer 3b exists to prevent.
    """
    factory = get_model_factory(model_name)
    probe = factory()
    result = BackfillResult(model_name=probe.name, model_version=probe.version)

    cache = FitCache()
    history = _history(session, cache)
    already = published_weeks(session, probe.name) if skip_existing else set()

    # Counting rows against a cutoff is a scan of the history per week, which
    # is cheap next to a fit but silly to repeat: one sorted pass gives every
    # cutoff its training-set size by bisection instead.
    ordinals = sorted(_ordinal(row) for row in history)

    def rows_before(cutoff: tuple[int, int]) -> int:
        from bisect import bisect_left

        return bisect_left(ordinals, cutoff)

    published_any = False

    for season, week in available_weeks(session, seasons):
        cutoff = (season, week)
        entry = BackfillWeek(season=season, week=week)

        if cutoff in already:
            entry.skipped = True
            entry.skip_reason = "already published"
        elif rows_before(cutoff) < min_train_rows:
            entry.skipped = True
            entry.skip_reason = (
                f"only {rows_before(cutoff)} training row(s) before this week; "
                f"{min_train_rows} required"
            )
        elif rows_before((season - 1, 1)) < min_residual_train_rows:
            entry.skipped = True
            entry.skip_reason = (
                "not enough history before the previous season to fit a "
                "held-out residual distribution; the interval would be "
                "unmeasured"
            )
        else:
            generated = generate_week(
                session,
                model_name=model_name,
                season=season,
                week=week,
                publish=publish,
                profile=profile,
                cache=cache,
                invalidate=False,
            )
            if generated.skipped:
                entry.skipped = True
                entry.skip_reason = generated.skip_reason
            else:
                entry.projections = generated.projections_written
                entry.published = generated.published
                entry.model_run_id = generated.model_run_id
                published_any = published_any or generated.published
                if commit_each:
                    session.commit()

        result.weeks.append(entry)
        if on_week is not None:
            on_week(entry)

    # One epoch bump for the whole backfill. Every published week retires the
    # same namespace, so doing it per week would retire namespaces that no
    # reader had time to populate and cost a Redis round trip each.
    if published_any:
        if commit_each:
            session.commit()
        else:
            session.flush()
        result.cache_epoch = invalidate_all_sync()

    logger.info(
        "backfill complete",
        extra={
            "model": probe.name,
            "weeks_generated": len(result.generated),
            "weeks_skipped": len(result.skipped),
            "projections": result.projections_written,
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


def _history(session: Session, cache: FitCache | None) -> list[dict]:
    """Completed player-weeks, loaded once per backfill."""
    if cache is None:
        return load_rows(session, completed_only=True)
    if cache.history is None:
        cache.history = load_rows(session, completed_only=True)
    return cache.history


def _season_rows(session: Session, season: int, cache: FitCache | None) -> list[dict]:
    """Every feature row for a season, loaded once per backfill.

    A season nobody has played yet has no rows in ``feat_training_dataset`` —
    that table is built from recorded production, and there is none. Such a
    season falls back to :data:`~nflfp.predict.dataset.PRESEASON_TABLE`, which
    carries the same columns for week 1 built from the previous season's usage
    window and the coming season's schedule.

    The fallback is only ever reached when the primary table is empty for the
    season, so a season in progress is never served preseason rows, and a
    preseason row can never displace a real one.
    """
    if cache is not None and season in cache.season_rows:
        return cache.season_rows[season]

    rows = load_rows(session, seasons=[season])
    if not rows:
        rows = load_rows(session, seasons=[season], source=PRESEASON_TABLE)
        if rows:
            logger.info(
                "%s has no rows in %s; projecting its week 1 from %s (%d row(s))",
                season, SOURCE_TABLE, PRESEASON_TABLE, len(rows),
            )
    if cache is not None:
        cache.season_rows[season] = rows
    return rows


def _fit_distribution(
    factory,
    history: list[dict],
    *,
    cutoff: tuple[int, int],
    profile: str,
    cache: FitCache | None = None,
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
    key = (residual_cutoff, profile)

    if cache is not None and key in cache.residuals:
        scored = cache.residuals[key]
    else:
        # Uncached, the eval range stops at the target week — the single-week
        # job should not predict rows it will discard. Cached, it runs to the
        # end of the target season, because every week of that season shares
        # this residual cutoff and will take a prefix of the same list.
        upper = (cutoff[0] + 1, 1) if cache is not None else cutoff

        residual_train = [row for row in history if _ordinal(row) < residual_cutoff]
        residual_eval = [
            row for row in history if residual_cutoff <= _ordinal(row) < upper
        ]

        residual_model = factory()
        residual_model.fit(residual_train)

        scored = []
        for row, prediction in zip(residual_eval, residual_model.predict(residual_eval)):
            actual = row.get(f"fp_{profile}_actual")
            if actual is None:
                continue
            points = score_components(
                prediction.components, position=prediction.position
            )[profile]
            scored.append((_ordinal(row), prediction.position, points, float(actual)))

        if cache is not None:
            cache.residuals[key] = scored

    samples = [
        (position, points, actual)
        for ordinal, position, points, actual in scored
        if ordinal < cutoff
    ]

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
