"""Phase 8E — does the draft strategy actually build a better team?

Drafts seasons that have since been played, then scores the resulting rosters on
what really happened. Every input is bounded at the draft date: the week 1
projection run for season S was fitted only on data before it, and the
historical panel stops at S-1.

    python scripts/phase8e_evaluate.py --seasons 2021 2022 2023 2024 2025

Writes a report to artifacts/phase8e_report.txt and prints it.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

if sys.platform == "win32":  # psycopg's async driver refuses ProactorEventLoop
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nflfp.db.engine import async_session_scope  # noqa: E402
from nflfp.services import repository  # noqa: E402
from nflfp.services.draft import evaluate, pool as pool_module  # noqa: E402
from nflfp.services.draft.engine import (  # noqa: E402
    DraftContext,
    calibrate_availability,
)
from nflfp.services.draft.settings import validate_settings  # noqa: E402

DEFAULT_SEASONS = (2020, 2021, 2022, 2023, 2024, 2025)


async def actual_season_points(session, season: int, profile: str) -> dict[str, float]:
    """Real regular-season fantasy points for one season.

    Deliberately fetched with ``before_season = season + 1`` and one season of
    lookback, which is the same query the draft uses — pointed one season
    forward. The leakage guard in ``history`` is *not* applied to it, and must
    not be: this is the answer sheet, and it is only ever read after the draft
    has been simulated.
    """
    rows = await repository.fetch_season_totals(
        session,
        before_season=season + 1,
        seasons_back=1,
        scoring_profile=profile,
    )
    return {
        str(row["player_id"]): float(row["total_points"] or 0.0)
        for row in rows
        if int(row["season"]) == season
    }


async def run(seasons, teams, rounds, profile, simulations, seats, seed) -> str:
    lines: list[str] = []

    def emit(text: str = "") -> None:
        lines.append(text)
        print(text)

    emit("=" * 78)
    emit("PHASE 8E — MOCK DRAFT EVALUATION")
    emit("=" * 78)
    emit(
        f"{teams}-team {profile} league, {rounds} rounds, {simulations} simulations "
        f"per seat, seats {list(seats)}, seed {seed}"
    )
    emit()
    emit(
        "Every draft below is decided with information available before week 1 of "
        "its season. Scoring uses that season's actual results, which the engine "
        "never sees."
    )
    emit()

    accuracy_rows: list[tuple[int, evaluate.ProjectionAccuracy]] = []
    strategy_rows: list[tuple[int, evaluate.StrategyResult]] = []
    calibration_summaries: list[tuple[int, dict[str, float]]] = []

    for season in seasons:
        settings = validate_settings(
            teams=teams,
            rounds=rounds,
            scoring_profile=profile,
            season=season,
            simulations=simulations,
            seed=seed,
        )
        async with async_session_scope() as session:
            try:
                pool = await pool_module.build_pool(session, settings)
            except Exception as error:  # noqa: BLE001 — reported, not raised
                emit(f"{season}: skipped — {error}")
                emit()
                continue
            actuals = await actual_season_points(session, season, profile)

        if not actuals:
            emit(f"{season}: skipped — no completed season to score against")
            emit()
            continue

        started = time.perf_counter()
        context = DraftContext.build(pool, settings)
        availability = calibrate_availability(context, seed=seed)

        emit("-" * 78)
        emit(f"SEASON {season}   pool={len(pool.players)} players")
        emit("-" * 78)

        emit()
        emit("Projection accuracy — season value vs actual season points")
        emit(f"  {'pos':<5}{'n':>5}{'corr':>8}{'proj':>9}{'actual':>9}{'bias':>9}{'MAE':>8}")
        for entry in evaluate.projection_accuracy(pool.players, actuals):
            accuracy_rows.append((season, entry))
            corr = "n/a" if entry.correlation is None else f"{entry.correlation:.3f}"
            emit(
                f"  {entry.position:<5}{entry.players:>5}{corr:>8}"
                f"{entry.mean_projected:>9.1f}{entry.mean_actual:>9.1f}"
                f"{entry.bias:>9.1f}{entry.mean_absolute_error:>8.1f}"
            )

        emit()
        emit("Strategy comparison — actual points scored by the drafted starting lineup")
        results = evaluate.compare_strategies(
            context,
            availability=availability,
            actual_points=actuals,
            seats=seats,
            simulations=simulations,
            seed=seed,
        )
        baseline = next(
            r for r in results if r.strategy == "value_over_next_available"
        )
        emit(f"  {'strategy':<28}{'drafts':>8}{'actual':>10}{'se':>7}{'vs VONA':>10}")
        for result in results:
            strategy_rows.append((season, result))
            delta = result.mean_actual_points - baseline.mean_actual_points
            emit(
                f"  {result.strategy:<28}{result.drafts:>8}"
                f"{result.mean_actual_points:>10.1f}{result.standard_error:>7.1f}"
                f"{delta:>+10.1f}"
            )

        emit()
        emit("Availability calibration — predicted vs observed, user-strategy drafts")
        bins = evaluate.availability_calibration(
            context,
            availability=availability,
            seat=seats[0],
            simulations=min(50, simulations),
            seed=seed,
        )
        summary = evaluate.summarise_calibration(bins)
        calibration_summaries.append((season, summary))
        emit(f"  {'band':<12}{'n':>9}{'predicted':>11}{'observed':>10}{'error':>9}")
        for entry in bins:
            emit(
                f"  {entry.lower:.1f}-{entry.upper:.1f}   {entry.observations:>9,}"
                f"{entry.mean_predicted:>11.3f}{entry.observed_rate:>10.3f}"
                f"{entry.error:>+9.3f}"
            )
        emit(
            f"  ECE {summary['expected_calibration_error']:.3f}   "
            f"max {summary['max_calibration_error']:.3f}"
        )
        emit(f"  ({time.perf_counter() - started:.1f}s)")
        emit()

    emit("=" * 78)
    emit("ACROSS SEASONS")
    emit("=" * 78)

    if strategy_rows:
        emit()
        emit("Mean actual points by strategy, pooled")
        by_strategy: dict[str, list[float]] = {}
        for _, result in strategy_rows:
            by_strategy.setdefault(result.strategy, []).append(
                result.mean_actual_points
            )
        vona = statistics.fmean(by_strategy.get("value_over_next_available", [0.0]))
        for strategy, values in by_strategy.items():
            mean = statistics.fmean(values)
            emit(
                f"  {strategy:<28}{mean:>10.1f}{mean - vona:>+10.1f}  "
                f"({len(values)} season(s))"
            )

    if accuracy_rows:
        emit()
        emit("Positional bias, pooled — actual minus projected season points")
        by_position: dict[str, list[float]] = {}
        for _, entry in accuracy_rows:
            by_position.setdefault(entry.position, []).append(entry.bias)
        for position, biases in sorted(by_position.items()):
            emit(
                f"  {position:<5}{statistics.fmean(biases):>+9.1f}  "
                f"({len(biases)} season(s))"
            )

    if calibration_summaries:
        emit()
        ece = statistics.fmean(
            [s["expected_calibration_error"] for _, s in calibration_summaries]
        )
        worst = max(s["max_calibration_error"] for _, s in calibration_summaries)
        emit(f"Availability ECE {ece:.3f}, worst band {worst:.3f}")

    emit()
    emit("LIMITATION: there is no real draft or ADP data in this repository, so the")
    emit("opponent model is unvalidated. These results say the strategy beats its")
    emit("baselines against these simulated opponents, not against real drafters.")
    emit()

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seasons", type=int, nargs="+", default=list(DEFAULT_SEASONS))
    parser.add_argument("--teams", type=int, default=12)
    parser.add_argument("--rounds", type=int, default=15)
    parser.add_argument("--profile", default="ppr")
    parser.add_argument("--simulations", type=int, default=100)
    parser.add_argument("--seats", type=int, nargs="+", default=[1, 4, 8, 12])
    parser.add_argument("--seed", type=int, default=20260101)
    parser.add_argument("--out", default="artifacts/phase8e_report.txt")
    args = parser.parse_args()

    report = asyncio.run(
        run(
            args.seasons,
            args.teams,
            args.rounds,
            args.profile,
            args.simulations,
            args.seats,
            args.seed,
        )
    )
    destination = Path(args.out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(report, encoding="utf-8")
    print(f"wrote {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
