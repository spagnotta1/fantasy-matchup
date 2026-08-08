"""Prediction engine CLI.

    python -m nflfp.predict models                       # registered models
    python -m nflfp.predict backtest baseline_l4         # walk-forward evaluation
    python -m nflfp.predict backtest baseline_l4 --seasons 2023 2024 2025
    python -m nflfp.predict compare                      # every model, side by side
    python -m nflfp.predict calibration baseline_l4      # are the probabilities honest?
"""

from __future__ import annotations

import argparse
import logging

from ..config import get_settings
from ..db import session_scope
from .backtest import compare as compare_results
from .backtest import run_backtest
from .calibration import calibration_report
from .dataset import load_rows
from .generate import generate_week, resolve_target_week
from .registry import available, get_model_factory

DEFAULT_TEST_SEASONS = (2019, 2020, 2021, 2022, 2023, 2024, 2025)


def _configure_logging() -> None:
    logging.basicConfig(
        level=get_settings().log_level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _load(seasons: list[int] | None) -> list[dict]:
    """Load completed player-weeks, including history before the test range.

    Training needs the seasons *before* the evaluation window, so this
    deliberately loads everything and lets the splitter decide what is visible
    at each point in time.
    """
    with session_scope() as session:
        return load_rows(session, completed_only=True)


def cmd_models(_: argparse.Namespace) -> int:
    for name in available():
        model = get_model_factory(name)()
        print(f"{name:<20} v{model.version:<8} {model.algorithm}")
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    rows = _load(args.seasons)
    result = run_backtest(
        get_model_factory(args.model),
        rows,
        test_seasons=args.seasons or DEFAULT_TEST_SEASONS,
        profile=args.profile,
    )
    print()
    print(result.report())
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    rows = _load(args.seasons)
    results = [
        run_backtest(
            get_model_factory(name),
            rows,
            test_seasons=args.seasons or DEFAULT_TEST_SEASONS,
            profile=args.profile,
            fit_distribution=False,
        )
        for name in available()
    ]
    print()
    print(compare_results(results))
    return 0


def cmd_calibration(args: argparse.Namespace) -> int:
    """Full held-out calibration analysis.

    Everything reported here comes from distributions fitted only on weeks
    earlier than the week they describe — see nflfp.predict.backtest.
    """
    rows = _load(args.seasons)
    result = run_backtest(
        get_model_factory(args.model),
        rows,
        test_seasons=args.seasons or DEFAULT_TEST_SEASONS,
        profile=args.profile,
    )
    print()
    print(result.report())

    scored = result.scored
    if not scored:
        print("\nno held-out distributions were produced (not enough residual history)")
        return 1

    for label, above in (("bust", False), ("boom", True)):
        probabilities = [
            p.distribution.boom_probability if above else p.distribution.bust_probability
            for p in scored
        ]
        outcomes = [
            (p.actual >= p.distribution.boom_threshold) if above
            else (p.actual <= p.distribution.bust_threshold)
            for p in scored
        ]
        print()
        print(f"{label} calibration curve (held out)")
        print(f"  {'bin':<12} {'n':>7} {'stated':>8} {'observed':>9} {'gap':>7}  reliable")
        for entry in calibration_report(probabilities, outcomes):
            print(
                f"  {entry.lower:.1f}-{entry.upper:.1f}    {entry.count:>7,} "
                f"{entry.mean_predicted:>8.3f} {entry.observed_rate:>9.3f} "
                f"{entry.error:>7.3f}  {'yes' if entry.reliable else 'NO (small)'}"
            )
    return 0


def cmd_project(args: argparse.Namespace) -> int:
    """Generate and persist projections for one upcoming week.

    The work itself lives in :func:`nflfp.predict.generate.generate_week`,
    which is the same function the scheduled job runs. A manual rerun after a
    failed Thursday job must produce exactly what the job would have produced,
    and that is only guaranteed if there is one implementation rather than two
    that look alike.
    """
    with session_scope() as session:
        if args.week is None:
            resolved = resolve_target_week(session, args.season)
            if resolved is None:
                print(
                    f"no upcoming games for season {args.season or 'current'}; "
                    "name a week explicitly with --week"
                )
                return 1
            season, week = resolved
        else:
            # A week without a season is the common case in-season ("project
            # week 12"), so the season defaults the same way every other
            # entry point resolves it rather than being required here.
            from ..sources import current_season

            season = args.season if args.season is not None else current_season()
            week = args.week

        result = generate_week(
            session,
            model_name=args.model,
            season=season,
            week=week,
            publish=args.publish,
            profile=args.profile,
        )
        if result.skipped:
            print(f"\nskipped: {result.skip_reason}")
            return 1
        session.commit()

    print(
        f"\nrun {result.model_run_id}: {result.projections_written} projection(s) "
        f"for {result.season} week {result.week}"
        f" ({'published' if result.published else 'not published'})"
    )
    print(f"  residual samples: {result.residual_samples:,}")
    if result.unprojected:
        print(f"  no distribution:  {result.unprojected}")
    if result.published:
        print(f"  cache epoch:      {result.cache_epoch}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nflfp.predict",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    # Shared options live on a parent parser rather than the root, so they can
    # be written *after* the subcommand. `backtest baseline_l4 --seasons 2024`
    # is the order anyone types; putting them on the root would silently reject
    # it with an unhelpful message.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", default="half_ppr", help="scoring profile to evaluate")
    common.add_argument("--seasons", type=int, nargs="+", default=None,
                        help="seasons to evaluate (default: 2019-2025)")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("models", parents=[common], help="list registered models").set_defaults(
        func=cmd_models
    )

    backtest = sub.add_parser("backtest", parents=[common], help="walk-forward evaluation")
    backtest.add_argument("model", choices=available())
    backtest.set_defaults(func=cmd_backtest)

    sub.add_parser("compare", parents=[common], help="all models side by side").set_defaults(
        func=cmd_compare
    )

    calibration = sub.add_parser(
        "calibration", parents=[common], help="probability honesty report"
    )
    calibration.add_argument("model", choices=available())
    calibration.set_defaults(func=cmd_calibration)

    project = sub.add_parser(
        "project", parents=[common], help="generate and persist a week's projections"
    )
    project.add_argument("model", choices=available())
    project.add_argument("--season", type=int, default=None,
                         help="season to project (default: the current league year)")
    project.add_argument("--week", type=int, default=None,
                         help="week to project (default: the upcoming slate)")
    project.add_argument("--publish", action="store_true",
                         help="make this run the live one for the week")
    project.set_defaults(func=cmd_project)

    args = parser.parse_args(argv)
    _configure_logging()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
