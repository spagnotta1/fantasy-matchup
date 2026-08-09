"""Job CLI.

    python -m nflfp.jobs list                 # registered jobs and cadences
    python -m nflfp.jobs run refresh_odds     # manual execution
    python -m nflfp.jobs run refresh_weather --horizon-days 3
    python -m nflfp.jobs run generate_projections --week 12 --publish
    python -m nflfp.jobs run generate_projections --model xgb --no-publish
    python -m nflfp.jobs run warm_cache
    python -m nflfp.jobs run invalidate_cache
    python -m nflfp.jobs run-all              # every scheduled job, in order
    python -m nflfp.jobs status               # recent run history
    python -m nflfp.jobs schedule             # Railway cron config
    python -m nflfp.jobs schedule --emit deploy/   # ...written as config files

Manual execution is a first-class path, not a debugging afterthought: the first
thing anyone does after a failed scheduled run is rerun it by hand, and that
needs to be one command that logs identically to the scheduled version.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from ..logging import configure_logging
from . import definitions  # noqa: F401  (registers the jobs)
from .registry import REGISTRY
from .runner import recent_runs, run_all, run_job


def cmd_list(_: argparse.Namespace) -> int:
    print(f"{'job':<22} {'schedule':<14} {'critical':<9} description")
    print("-" * 110)
    for job in REGISTRY.all():
        print(f"{job.name:<22} {job.schedule:<14} {str(job.critical):<9} {job.description}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    options: dict[str, object] = {}
    if args.horizon_days is not None:
        options["horizon_days"] = args.horizon_days
    if args.season is not None:
        options["season"] = args.season
    if args.week is not None:
        options["week"] = args.week
    if args.model is not None:
        options["model"] = args.model
    if args.publish is not None:
        options["publish"] = args.publish
    if args.datasets:
        options["datasets"] = args.datasets
    if args.seasons:
        options["seasons"] = args.seasons
    if getattr(args, "skip_existing", False):
        options["skip_existing"] = True
    run = run_job(args.name, options=options, trigger="manual")
    print(f"\n{run.job_name}: {run.status} — {run.records_written} record(s)")
    if run.detail:
        for key, value in run.detail.items():
            print(f"  {key}: {value}")
    if run.error:
        print(f"\n{run.error}", file=sys.stderr)
    return 0 if run.status in ("ok", "skipped") else 1


def cmd_run_all(_: argparse.Namespace) -> int:
    runs = run_all(trigger="manual")
    print()
    failed = 0
    for run in runs:
        marker = " " if run.status in ("ok", "skipped") else "!"
        print(f"{marker} {run.job_name:<20} {run.status:<8} {run.records_written:>8,} record(s)")
        failed += run.status == "failed"
    return 1 if failed else 0


def cmd_status(args: argparse.Namespace) -> int:
    runs = recent_runs(limit=args.limit, name=args.name)
    if not runs:
        print("no job runs recorded yet")
        return 0
    print(f"{'id':>5} {'job':<20} {'started':<20} {'took':<9} {'status':<8} {'trigger':<9} {'rows':>9}")
    print("-" * 92)
    for run in runs:
        took = f"{run.duration_seconds:.1f}s" if run.duration_seconds is not None else "-"
        print(
            f"{run.id:>5} {run.job_name:<20} {run.started_at:%Y-%m-%d %H:%M:%S}  "
            f"{took:<9} {run.status:<8} {run.trigger:<9} {run.records_written:>9,}"
        )
    return 0


def cmd_schedule(args: argparse.Namespace) -> int:
    """Show — or generate — the Railway config for the scheduled services.

    The registry stays the single source of truth for cadence. Without
    ``--emit`` this is a printed view of it; with ``--emit`` it writes one
    ``railway.<job>.json`` per job, which is what Railway's config-as-code
    expects and what stops a schedule living in two places that can disagree.
    Regenerating after a cadence change is the whole point: the deployed cron
    and the registry are then provably the same numbers.
    """
    scheduled = REGISTRY.scheduled()

    if not args.emit:
        print("Railway scheduled services (one service per job, same image):\n")
        for job in scheduled:
            print(f"  {job.name}")
            print(f"    Cron Schedule : {job.schedule}")
            print(f"    Start Command : python -m nflfp.jobs run {job.name}")
            print("    Restart Policy: NEVER")
            print(f"    # {job.description}\n")
        manual = [job for job in REGISTRY.all() if not job.is_scheduled]
        if manual:
            print("Not scheduled — run by hand when the situation calls for it:\n")
            for job in manual:
                print(f"  {job.name:<22} python -m nflfp.jobs run {job.name}")
                print(f"    # {job.description}\n")
        return 0

    target = pathlib.Path(args.emit)
    target.mkdir(parents=True, exist_ok=True)
    for job in scheduled:
        config = {
            "$schema": "https://railway.app/railway.schema.json",
            "build": {"builder": "DOCKERFILE", "dockerfilePath": "Dockerfile"},
            "deploy": {
                "startCommand": f"python -m nflfp.jobs run {job.name}",
                "cronSchedule": job.schedule,
                # A cron job that exits 0 is finished, not crashed. Any other
                # policy restarts it in a loop.
                "restartPolicyType": "NEVER",
            },
        }
        path = target / f"railway.{job.name.replace('_', '-')}.json"
        path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path}  ({job.schedule})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nflfp.jobs", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="show registered jobs").set_defaults(func=cmd_list)

    run_parser = sub.add_parser("run", help="execute one job")
    run_parser.add_argument("name", choices=REGISTRY.names())
    run_parser.add_argument("--horizon-days", type=int, default=None,
                            help="override how far ahead providers fetch")
    run_parser.add_argument("--season", type=int, default=None,
                            help="generate_projections: season (default: current)")
    run_parser.add_argument("--week", type=int, default=None,
                            help="generate_projections: week (default: the upcoming slate)")
    run_parser.add_argument("--model", default=None,
                            help="generate_projections / evaluate_model: model name")
    run_parser.add_argument("--datasets", nargs="+", default=None,
                            help="refresh_injuries: datasets to reload (default: injuries)")
    run_parser.add_argument("--seasons", type=int, nargs="+", default=None,
                            help="evaluate_model / backfill_projections: seasons to cover")
    run_parser.add_argument("--skip-existing", action="store_true",
                            help="backfill_projections: leave already-published weeks alone")
    publish = run_parser.add_mutually_exclusive_group()
    publish.add_argument("--publish", dest="publish", action="store_true", default=None,
                         help="generate_projections: make the run live")
    publish.add_argument("--no-publish", dest="publish", action="store_false",
                         help="generate and store without making the run live")
    run_parser.set_defaults(func=cmd_run)

    sub.add_parser("run-all", help="execute every job").set_defaults(func=cmd_run_all)

    status_parser = sub.add_parser("status", help="recent run history")
    status_parser.add_argument("--limit", type=int, default=20)
    status_parser.add_argument("--name", default=None, help="filter to one job")
    status_parser.set_defaults(func=cmd_status)

    schedule_parser = sub.add_parser("schedule", help="print or emit Railway cron config")
    schedule_parser.add_argument(
        "--emit",
        metavar="DIR",
        default=None,
        help="write one railway.<job>.json per scheduled job into DIR",
    )
    schedule_parser.set_defaults(func=cmd_schedule)

    args = parser.parse_args(argv)
    configure_logging()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
