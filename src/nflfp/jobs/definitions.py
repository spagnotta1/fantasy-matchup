"""The registered jobs.

Cadence reasoning, since these numbers are choices and not defaults:

``refresh_odds`` — hourly during the week
    The market is the fastest-moving input there is. A Saturday injury
    designation moves a total by two points, and that movement is itself a
    feature. Hourly is cheap: one request per NFL week, ~17 games returned.

``refresh_weather`` — every six hours
    Forecast models publish roughly four times a day; polling faster returns
    the same numbers. Six hours also means a Sunday-morning run catches the
    final pre-kickoff revision, which is the one that matters.

``build_features`` — daily, after the nflverse refresh
    A full rebuild is ~6 seconds against ten seasons, so there is no reason to
    be clever about incrementality yet. It runs after the warehouse load
    because every feature reads ``raw_*``.

``refresh_features`` — hourly, chained after the provider jobs
    Concurrent refresh, so readers are never blocked. This is what propagates a
    new odds snapshot into ``feat_training_dataset`` without a full rebuild.

``generate_projections`` — Tuesday afternoon, after the feature build
    The expensive one, and the reason Layer 6 exists as a layer. Fitting a
    model over ten seasons and writing a slate is minutes of work; doing it
    inside a request would hold a connection for the duration and time out
    long before it finished. It runs *after* ``build_features`` on purpose —
    projecting from feature views that still describe last week produces a
    board that is confidently about the wrong games.

``warm_cache`` — chained after a publish, and hourly thereafter
    The first request after a publish pays for a full slate assembly. Warming
    moves that cost off a user and onto a job, which is the entire argument for
    doing it at all.
"""

from __future__ import annotations

import logging

from sqlalchemy import text

from ..cache import invalidate_all_sync
from ..config import get_settings
from ..etl import ingest_odds, ingest_weather, upcoming_games
from ..features import build_features, refresh_features
from ..providers import get_odds_provider, get_weather_provider
from .registry import MANUAL, REGISTRY, Job, JobContext, JobOutcome

logger = logging.getLogger(__name__)


def _horizon(context: JobContext) -> int:
    return int(
        context.options.get("horizon_days") or get_settings().provider_horizon_days
    )


def refresh_odds(context: JobContext) -> JobOutcome:
    """Capture the current betting market for every upcoming game."""
    games = upcoming_games(context.session, horizon_days=_horizon(context))
    if not games:
        return JobOutcome(skipped=True, skip_reason="no upcoming games in range")
    result = ingest_odds(context.session, get_odds_provider(), games)
    return JobOutcome(records=result.written, detail=result.as_detail())


def refresh_weather(context: JobContext) -> JobOutcome:
    """Capture the current forecast for every upcoming outdoor game."""
    games = upcoming_games(context.session, horizon_days=_horizon(context))
    if not games:
        return JobOutcome(skipped=True, skip_reason="no upcoming games in range")
    result = ingest_weather(context.session, get_weather_provider(), games)
    return JobOutcome(records=result.written, detail=result.as_detail())


def build_features_job(context: JobContext) -> JobOutcome:
    """Drop and rebuild every feature view."""
    result = build_features(context.session)
    return JobOutcome(records=result.total_rows, detail=result.as_detail())


def refresh_features_job(context: JobContext) -> JobOutcome:
    """Refresh feature views in place, without blocking readers."""
    result = refresh_features(context.session)
    return JobOutcome(records=result.total_rows, detail=result.as_detail())


def refresh_injuries(context: JobContext) -> JobOutcome:
    """Reload the current season's injury report.

    Injuries ride the weekly nflverse load like everything else, and weekly is
    the wrong cadence for them. A practice report lands Wednesday, Thursday and
    Friday, and a designation flips on Saturday — by which time the Tuesday
    load is four days stale and the API is reporting a hard caveat that has
    since been lifted, or missing one that has since been added.

    This reloads that one dataset daily. It is `by_season`, so the cost is one
    parquet file and a partitioned delete/insert rather than a full rebuild —
    which is why a dedicated job is affordable at this cadence and a whole
    pipeline refresh is not.

    Options:
        ``datasets``: override which datasets to reload. ``depth_charts`` is
            the other one that moves during a week, and is a reasonable pairing
            when a starter goes down; it is `full`-refresh, so it is not in the
            default set.
    """
    from ..pipeline import run as run_pipeline
    from ..sources import DATASETS_BY_NAME, DEFAULT_END_SEASON, DEFAULT_START_SEASON
    from ..sources import current_season

    names = context.options.get("datasets") or ["injuries"]
    unknown = [name for name in names if name not in DATASETS_BY_NAME]
    if unknown:
        raise KeyError(f"unknown dataset(s) {unknown}; known: {sorted(DATASETS_BY_NAME)}")

    season = int(context.options.get("season") or current_season())
    exit_code = run_pipeline(
        "refresh",
        DEFAULT_START_SEASON,
        DEFAULT_END_SEASON,
        [season],
        [DATASETS_BY_NAME[name] for name in names],
    )
    if exit_code != 0:
        # The pipeline records its own failure in `pipeline_runs` and returns
        # non-zero rather than raising. Re-raising here is what puts it in the
        # job log too — a load failure that only appears in one of two run
        # logs is a load failure somebody misses.
        raise RuntimeError(
            f"pipeline refresh of {names} failed; see pipeline_runs for the detail"
        )

    rows = context.session.execute(
        text(
            "SELECT rows_loaded FROM pipeline_runs "
            "WHERE status = 'ok' ORDER BY run_id DESC LIMIT 1"
        )
    ).scalar()
    return JobOutcome(
        records=int(rows or 0), detail={"datasets": names, "season": season}
    )


def evaluate_model(context: JobContext) -> JobOutcome:
    """Re-measure the live model against the criteria it was frozen under.

    Retraining happens every week inside ``generate_projections`` — the model
    is refitted from scratch on everything before the target week, so there is
    no separate "retrain" step to schedule. What there is no separate step for
    is **checking that the retrained model still behaves**, and that is the
    gap this fills.

    A model whose accuracy drifts does not announce itself. Projections keep
    being produced, intervals keep being stated, and the first signal is a user
    noticing the numbers are wrong. So this runs the same walk-forward harness
    the foundation was frozen on and checks the result against
    :data:`~nflfp.predict.foundation.ACCEPTANCE` — the incumbent held to the
    bar a challenger would have to clear.

    It **does not publish, unpublish or change anything.** A drifting model is
    an operator decision, not something a cron should act on: the honest
    response to "coverage has slipped" is a human looking at why, and an
    automated rollback would hide the drift by reverting to a model that has
    the same problem a week earlier.

    Failure here therefore means "the check could not run". Failing the
    criteria is a successful run with ``passed: false`` in the detail, which is
    what makes it queryable in the job log rather than buried in an exception.
    """
    from ..predict.backtest import run_backtest
    from ..predict.dataset import load_rows
    from ..predict.foundation import FROZEN_MODEL, meets_acceptance
    from ..predict.registry import get_model_factory

    settings = get_settings()
    model_name = context.options.get("model") or settings.projection_model
    seasons = context.options.get("seasons") or _recent_seasons(
        int(context.options.get("evaluation_seasons") or 3)
    )

    rows = load_rows(context.session, completed_only=True)
    if not rows:
        return JobOutcome(
            skipped=True,
            skip_reason="feat_training_dataset is empty; run build_features first",
        )

    result = run_backtest(
        get_model_factory(model_name), rows, test_seasons=seasons, profile="half_ppr"
    )
    if not result.scored:
        return JobOutcome(
            skipped=True,
            skip_reason="no held-out distributions were produced; not enough residual history",
        )

    coverage_80 = next(
        (entry.observed for entry in result.coverage if entry.nominal == 0.80), None
    )
    reliable = [entry for entry in result.ranges if entry.reliable]
    passed, reasons = meets_acceptance(
        coverage_p10_p90=coverage_80 if coverage_80 is not None else 0.0,
        max_calibration_error=max(result.calibration_max.values(), default=1.0),
        max_conditional_bias=max((abs(entry.bias) for entry in reliable), default=0.0),
        crps=result.mean_crps if result.mean_crps is not None else float("inf"),
        mae_by_position={
            position: metrics.mae for position, metrics in result.by_position.items()
        },
        walk_forward=result.walk_forward,
    )

    detail = {
        "model": model_name,
        "is_frozen_foundation": model_name == FROZEN_MODEL,
        "seasons": list(seasons),
        "passed": passed,
        "failures": list(reasons),
        "metrics": result.as_metrics(),
    }
    if passed:
        logger.info("%s still meets its acceptance criteria", model_name)
    else:
        # WARNING, not an exception. The run succeeded; the model is the thing
        # that needs looking at, and an alert on a failed *job* would say the
        # evaluation broke rather than that the model drifted.
        logger.warning(
            "%s no longer meets its acceptance criteria: %s", model_name, "; ".join(reasons)
        )
    return JobOutcome(records=len(result.scored), detail=detail)


def _recent_seasons(count: int) -> list[int]:
    """The last `count` seasons, for a rolling re-measurement.

    Deliberately not the full validation window. The frozen record covers
    2019-2025 and is a fixed historical measurement; this job asks a different
    question — "is it still behaving *now*?" — and a seven-season average would
    dilute a recent drift below the tolerance that is supposed to catch it.
    """
    from ..sources import current_season

    latest = current_season()
    return list(range(latest - count, latest))


def generate_projections(context: JobContext) -> JobOutcome:
    """Fit the frozen model and publish a slate for the upcoming week.

    Options:
        ``model``: override the configured model. Present so a challenger can
            be run beside the incumbent without publishing — pair it with
            ``publish=False``.
        ``season`` / ``week``: project a specific week. Omitted, the job
            resolves the upcoming slate exactly as the API does, so the week a
            reader defaults to is the week that was projected.
        ``publish``: override :attr:`Settings.job_publish_projections`.

    An offseason run finds no upcoming games and skips. That is recorded as
    ``skipped`` with a reason rather than as a failure, because a job that
    reports failure every day from February to August trains everyone to
    ignore its alerts.
    """
    from ..predict.generate import generate_week, resolve_target_week

    settings = get_settings()
    options = context.options
    model_name = options.get("model") or settings.projection_model
    publish = options.get("publish")
    if publish is None:
        publish = settings.job_publish_projections

    week = options.get("week")
    season = options.get("season")
    if week is None:
        resolved = resolve_target_week(context.session, season)
        if resolved is None:
            return JobOutcome(
                skipped=True,
                skip_reason=(
                    f"no unplayed games for season {season or 'current'}; "
                    "nothing to project"
                ),
            )
        season, week = resolved
    elif season is None:
        from ..sources import current_season

        season = current_season()

    result = generate_week(
        context.session,
        model_name=model_name,
        season=int(season),
        week=int(week),
        publish=bool(publish),
    )
    if result.skipped:
        return JobOutcome(skipped=True, skip_reason=result.skip_reason)
    return JobOutcome(records=result.projections_written, detail=result.as_detail())


def backfill_projections(context: JobContext) -> JobOutcome:
    """Publish a board for every week the feature layer can support.

    ``generate_projections`` produces one week per firing, which means a fresh
    deployment offers exactly one week in its selectors no matter how many
    seasons the warehouse holds — the product looks like it has one week of
    data because, in the only sense the API measures, it does. This walks the
    same generator over the whole history so availability matches the
    warehouse.

    Options:
        ``model``: override the configured model.
        ``seasons``: restrict to specific seasons; every season with feature
            rows if omitted.
        ``skip_existing``: leave already-published weeks alone, which is what
            makes a rerun cheap after a new season lands.
        ``publish``: override :attr:`Settings.job_publish_projections`.

    Registered as :data:`MANUAL`. This is a catch-up operation, not a cadence:
    once the history is published, the weekly job keeps it current, and a cron
    that reprojected ten seasons every week would spend an hour rewriting rows
    that cannot have changed.
    """
    from ..predict.generate import generate_backfill

    settings = get_settings()
    options = context.options
    model_name = options.get("model") or settings.projection_model
    publish = options.get("publish")
    if publish is None:
        publish = settings.job_publish_projections

    seasons = options.get("seasons")

    result = generate_backfill(
        context.session,
        model_name=model_name,
        seasons=[int(season) for season in seasons] if seasons else None,
        publish=bool(publish),
        skip_existing=bool(options.get("skip_existing", False)),
        commit_each=True,
    )

    if not result.generated:
        return JobOutcome(
            skipped=True,
            skip_reason=(
                "no week was eligible for projection; "
                f"{len(result.skipped)} skipped"
            ),
            detail=result.as_detail(),
        )
    return JobOutcome(records=result.projections_written, detail=result.as_detail())


def invalidate_cache(context: JobContext) -> JobOutcome:
    """Retire the cache namespace by hand.

    Publishing does this automatically. This job exists for the case that
    automation cannot cover: a warehouse correction that changes what an
    already-published run's projections *join against* — a fixed injury
    designation, a corrected opponent — without producing a new run. The
    invalidation event is real, but there is no publish to hang it on.
    """
    epoch = invalidate_all_sync()
    if epoch is None:
        return JobOutcome(
            skipped=True,
            skip_reason="cache backend unreachable or not configured; nothing to invalidate",
        )
    return JobOutcome(records=1, detail={"cache_epoch": epoch})


def warm_cache(context: JobContext) -> JobOutcome:
    """Pre-render the pages a client requests on load.

    Warming drives the **real ASGI application** in-process rather than
    re-implementing the render path. That is not laziness — a warmer that
    builds its own body is a second serialiser, and the first time a schema
    changes it starts populating the cache with something the API would never
    produce, which is undetectable from the outside because the responses look
    fine. Going through the app means a warmed body is by construction the body
    a user would have received.

    The warmer holds its own database session through the app's normal
    dependency rather than the job's, because the app's session is async. The
    job's session is left untouched.
    """
    import asyncio

    settings = get_settings()
    paths = context.options.get("paths") or list(_warmable_paths())
    try:
        warmed, failed = asyncio.run(_warm(paths, settings))
    except RuntimeError:  # pragma: no cover - only inside a running loop
        return JobOutcome(skipped=True, skip_reason="already inside an event loop")

    if not warmed and failed:
        # Every path failing is a broken API, not a cold cache, and the batch
        # should say so rather than reporting a quiet zero.
        raise RuntimeError(f"cache warm failed for every path: {failed}")
    return JobOutcome(records=len(warmed), detail={"warmed": warmed, "failed": failed})


def _warmable_paths() -> tuple[str, ...]:
    from ..cache import warmable_paths

    return warmable_paths()


async def _warm(paths: list[str], settings) -> tuple[list[str], dict[str, str]]:
    """Request each path through the ASGI app, populating the cache."""
    from httpx import ASGITransport, AsyncClient

    from ..api.main import create_app

    app = create_app(settings)
    warmed: list[str] = []
    failed: dict[str, str] = {}

    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://warm") as client:
            for path in paths:
                try:
                    response = await client.get(path, timeout=60.0)
                except Exception as exc:  # a warm failure must not fail a batch
                    failed[path] = repr(exc)
                    continue
                if response.status_code == 200:
                    warmed.append(path)
                else:
                    failed[path] = f"HTTP {response.status_code}"
    finally:
        # ASGITransport does not run the lifespan, so nothing else will close
        # the async pool this opened. In `run-all` the process outlives this
        # job, and a leaked pool holds Postgres connections that the API needs.
        from ..db.engine import dispose_async_engine

        await dispose_async_engine()
    return warmed, failed


REGISTRY.register(
    Job(
        name="refresh_odds",
        func=refresh_odds,
        schedule="15 * * * *",
        description="Capture current spreads, totals and moneylines for upcoming games.",
    )
)

REGISTRY.register(
    Job(
        name="refresh_weather",
        func=refresh_weather,
        schedule="30 */6 * * *",
        description="Capture forecast conditions for upcoming outdoor games.",
    )
)

REGISTRY.register(
    Job(
        name="build_features",
        func=build_features_job,
        schedule="0 13 * * 2",
        description="Rebuild all feature views. Runs after the weekly nflverse load.",
        critical=True,
    )
)

REGISTRY.register(
    Job(
        name="refresh_features",
        func=refresh_features_job,
        schedule="45 * * * *",
        description="Concurrently refresh feature views so new snapshots propagate.",
    )
)

REGISTRY.register(
    Job(
        name="refresh_injuries",
        func=refresh_injuries,
        # Daily at 11:00 UTC — before the Tuesday warehouse load rather than
        # after, so on the one day both run this is the cheap no-op and the
        # full refresh is authoritative.
        schedule="0 11 * * *",
        description="Reload the current season's injury report, which moves all week.",
    )
)

REGISTRY.register(
    Job(
        name="generate_projections",
        func=generate_projections,
        # Tuesday 14:00 UTC: after the 12:00 nflverse load and the 13:00
        # feature build, and three days before the first Thursday kickoff, so
        # a failure has a working day of slack before anyone needs the board.
        schedule="0 14 * * 2",
        description="Fit the frozen model and publish the upcoming week's slate.",
        # Critical: everything a user sees is downstream of this. A silent
        # failure means an empty board on Thursday, which the API renders
        # correctly and unhelpfully as "projections coming soon".
        critical=True,
    )
)

REGISTRY.register(
    Job(
        name="backfill_projections",
        func=backfill_projections,
        # Manual, for the same reason invalidate_cache is: this is a catch-up
        # run, not a cadence. Once the history is published the weekly job
        # keeps it current, and a cron would spend an hour a week rewriting
        # boards for seasons that ended years ago.
        schedule=MANUAL,
        description="Publish a board for every week the feature layer supports.",
    )
)

REGISTRY.register(
    Job(
        name="warm_cache",
        func=warm_cache,
        # Twenty minutes after the projection job, which is comfortably longer
        # than the run takes, and hourly through the week so a natural
        # expiry is refilled by a job rather than by a user's request.
        schedule="20 * * * *",
        description="Pre-render the boards a client requests on load.",
    )
)

REGISTRY.register(
    Job(
        name="evaluate_model",
        func=evaluate_model,
        # Wednesday, the day after a projection run. Not before one: the point
        # is to measure what was just published, and a check that runs first
        # reports on last week's model.
        schedule="0 16 * * 3",
        description="Re-measure the live model against its frozen acceptance criteria.",
    )
)

REGISTRY.register(
    Job(
        name="invalidate_cache",
        func=invalidate_cache,
        # Never on a schedule. A publish already invalidates; this exists for
        # a manual correction that has no publish to hang itself on, and a
        # cron that periodically threw the cache away would be a slow leak of
        # the benefit it exists to provide.
        schedule="manual",
        description="Retire the cache namespace by hand after a data correction.",
    )
)
