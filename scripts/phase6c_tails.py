"""Phase 6C: measure the outcome curve's tail factors at the lineup level.

Run from the repository root::

    python scripts/phase6c_tails.py

Reuses the Phase 6B panel in ``artifacts/`` — the same 38,061 leakage-free
player-weeks, rebuilt only with ``--rebuild-panel`` and a live warehouse. Nothing
here writes to the database, and nothing here changes a production constant: the
output is evidence, and promoting a candidate is a separate, manual decision.

Reproducing the report as it was published
------------------------------------------
``artifacts/phase6c_report.txt`` was produced when production shipped
``1.5 / 2.5``, and the "incumbent" arm throughout it is that pair. Production now
ships ``1.0 / 2.0`` — this phase's own recommendation, approved in Phase 6D — so
an unqualified re-run compares the *current* constants against the grid and
answers a different question than the report does.

Both are worth being able to ask, so the baseline is a parameter::

    python scripts/phase6c_tails.py --incumbent 1.5 2.5   # the published report
    python scripts/phase6c_tails.py                       # whatever ships today

The default is whatever ``distributions.py`` ships, because a script that
hard-coded 1.5 / 2.5 would quietly stop describing production the moment
production moved — which is exactly what it just did.

The order below is the order the argument has to be made in:

1. the incumbent configuration, reproduced and measured;
2. a grid, scored on the **tuning** seasons only;
3. the selection rule applied to that grid;
4. the same grid on **held-out** seasons, so the surface can be compared without
   the selection having seen it;
5. what the error is conditional on — projection size, lineup size, stacking;
6. the expected-score versus projection-sum gap;
7. correlation re-tested under both tail configurations;
8. performance.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

from nflfp.correlation.estimate import walk_forward_models
from nflfp.correlation.panel import PANEL_SEASONS, Panel, build_panel
from nflfp.evaluation.tails import (
    HELDOUT_SEASONS,
    TUNING_SEASONS,
    FactorResult,
    SweepResult,
    TailFactors,
    build_curve,
    correlated_sampler_factory,
    default_grid,
    paired_delta,
    player_metrics,
    run_sweep,
    startable_rows,
    weeks_with_models,
)
from nflfp.services.simulation import SimulationInput, simulate

ARTIFACTS = Path("artifacts")
PANEL_PATH = ARTIFACTS / "panel_half_ppr.jsonl"
REPORT_PATH = ARTIFACTS / "phase6c_report.txt"

DEFAULT_DATABASE_URL = "postgresql+psycopg://nflfp:nflfp@localhost:55432/nflfp"

#: Matchups synthesised per week. Two lineups each, so ~2,900 lineup
#: observations per period — the sample every cell of the grid is scored on.
MATCHUPS_PER_WEEK = 40

#: Draws per lineup. Below the product default deliberately: the Monte Carlo
#: error averages out across thousands of lineups, and every candidate sees the
#: *same* draws, so it cancels in the comparison rather than accumulating.
ITERATIONS = 2_000

#: Lineup shapes for the size sensitivity. The middle one is the shape every
#: other number in the report uses.
SHAPES: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "5-player": (
        ("QB", ("QB",)), ("RB", ("RB",)), ("WR", ("WR",)), ("WR", ("WR",)),
        ("TE", ("TE",)),
    ),
    "7-player": (
        ("QB", ("QB",)), ("RB", ("RB",)), ("RB", ("RB",)), ("WR", ("WR",)),
        ("WR", ("WR",)), ("TE", ("TE",)), ("FLEX", ("RB", "WR", "TE")),
    ),
    "9-player": (
        ("QB", ("QB",)), ("RB", ("RB",)), ("RB", ("RB",)), ("WR", ("WR",)),
        ("WR", ("WR",)), ("WR", ("WR",)), ("TE", ("TE",)),
        ("FLEX", ("RB", "WR", "TE")), ("FLEX", ("RB", "WR", "TE")),
    ),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild-panel", action="store_true")
    parser.add_argument("--matchups-per-week", type=int, default=MATCHUPS_PER_WEEK)
    parser.add_argument("--iterations", type=int, default=ITERATIONS)
    parser.add_argument(
        "--skip-correlation",
        action="store_true",
        help="omit the four-way tail x correlation comparison (the slow part)",
    )
    parser.add_argument(
        "--incumbent",
        type=float,
        nargs=2,
        metavar=("LOWER", "UPPER"),
        default=None,
        help=(
            "the baseline configuration to compare the grid against; defaults "
            "to the constants distributions.py ships. Pass 1.5 2.5 to reproduce "
            "artifacts/phase6c_report.txt as published."
        ),
    )
    parser.add_argument(
        "--database-url", default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    )
    arguments = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    # The report is UTF-8 on disk; a Windows console defaulting to cp1252 would
    # otherwise fail on the em dashes rather than merely render them oddly.
    if hasattr(sys.stdout, "reconfigure"):  # pragma: no cover - console only
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    lines: list[str] = []

    def emit(text: str = "") -> None:
        print(text, flush=True)
        lines.append(text)

    if arguments.rebuild_panel or not PANEL_PATH.exists():
        panel = build_panel(database_url=arguments.database_url, seasons=PANEL_SEASONS)
        panel.save(PANEL_PATH)
    else:
        panel = Panel.load(PANEL_PATH)

    incumbent = (
        TailFactors(*arguments.incumbent)
        if arguments.incumbent
        else TailFactors.incumbent()
    )
    grid = default_grid()
    if incumbent not in grid:
        # The baseline has to be a cell of the same experiment — same lineups,
        # same draws — or the comparison against it is unpaired and every
        # standard error below belongs to a different run.
        grid = tuple(sorted({*grid, incumbent}))

    emit("=" * 118)
    emit("PHASE 6C — LINEUP-LEVEL DISTRIBUTION TAIL RECALIBRATION")
    emit("=" * 118)
    emit(
        f"panel: {len(panel):,} leakage-free player-week(s), "
        f"{panel.profile} / {panel.model_name}"
    )
    shipped = TailFactors.incumbent()
    emit(f"baseline configuration: {incumbent}")
    if incumbent != shipped:
        emit(
            f"  NOTE: production ships {shipped}. This run was asked for a "
            f"different baseline, which is how the published"
        )
        emit(
            "  report — written when production shipped L=1.50/U=2.50 — is "
            "reproduced after the constants moved."
        )
    emit(
        f"grid: {len(grid)} cell(s), lower "
        f"{sorted({f.lower for f in grid})}, upper {sorted({f.upper for f in grid})}"
    )
    emit(f"tuning seasons  {list(TUNING_SEASONS)}   (candidate selection only)")
    emit(f"held-out seasons {list(HELDOUT_SEASONS)}   (never used for selection)")
    emit(
        f"{arguments.matchups_per_week} matchup(s)/week, "
        f"{arguments.iterations:,} draw(s)/lineup, identical lineups and draws "
        "across every cell"
    )

    # -- player level --------------------------------------------------------
    emit()
    emit("-" * 118)
    emit("1. PLAYER-LEVEL BASELINE — the frozen foundation, unchanged by this phase")
    emit("-" * 118)
    emit(
        "  knot coverage is the share of outcomes at or below each stored "
        "percentile; nominal is 0.10 0.25 0.50 0.75 0.90"
    )
    tuning_players = startable_rows(panel, TUNING_SEASONS)
    heldout_players = startable_rows(panel, HELDOUT_SEASONS)
    emit(
        f"  startable player-weeks: tuning {len(tuning_players):,}, "
        f"held-out {len(heldout_players):,}"
    )
    baseline_player = {
        "tuning": player_metrics(
            tuning_players, incumbent, label=f"tuning {incumbent}"
        ),
        "held-out": player_metrics(
            heldout_players, incumbent, label=f"held-out {incumbent}"
        ),
    }
    for metrics in baseline_player.values():
        emit("  " + str(metrics))
    emit("  CRPS by position (held-out, incumbent):")
    for position, count, score in baseline_player["held-out"].by_position:
        emit(f"    {position:<4} n={count:>6,}  CRPS={score:.4f}")

    # -- tuning sweep --------------------------------------------------------
    emit()
    emit("-" * 118)
    emit("2. TUNING SURFACE — every cell, same lineups, same draws")
    emit("-" * 118)
    tuning = run_sweep(
        panel,
        grid=grid,
        seasons=TUNING_SEASONS,
        period="tuning",
        matchups_per_week=arguments.matchups_per_week,
        iterations=arguments.iterations,
        progress=lambda text: print(text, flush=True),
    )
    emit(
        f"  {tuning.weeks} week(s), {tuning.matchups:,} matchup(s), "
        f"{tuning.lineups:,} lineup(s), {tuning.duration_seconds:.0f}s"
    )
    for block in _surface_blocks(tuning, incumbent):
        emit(block)

    candidate = tuning.best()
    emit()
    emit("  SELECTION RULE (declared before the surface was read):")
    emit("    primary   — lineup-total PIT divergence, rounded to 1e-4")
    emit("    tie-break — lineup CRPS")
    emit(f"  selected on tuning data: {candidate}")
    emit("  five best cells on tuning data:")
    for result in _ranked(tuning)[:5]:
        emit(
            f"    {str(result.factors):<18} PITdiv={result.lineup.pit_divergence:.4f}  "
            f"CRPS={result.lineup.crps:.4f}  cov80={result.lineup.coverage_80:.4f}  "
            f"cov90={result.lineup.coverage_90:.4f}"
        )
    emit("  neighbourhood of the selection (stability, not the argmin):")
    for result in _neighbourhood(tuning, candidate):
        emit(
            f"    {str(result.factors):<18} PITdiv={result.lineup.pit_divergence:.4f}  "
            f"CRPS={result.lineup.crps:.4f}  cov80={result.lineup.coverage_80:.4f}"
        )

    # -- held-out ------------------------------------------------------------
    emit()
    emit("-" * 118)
    emit("3. HELD-OUT SURFACE — the same grid on seasons the selection never saw")
    emit("-" * 118)
    heldout = run_sweep(
        panel,
        grid=grid,
        seasons=HELDOUT_SEASONS,
        period="held-out",
        matchups_per_week=arguments.matchups_per_week,
        iterations=arguments.iterations,
        strata=True,
        progress=lambda text: print(text, flush=True),
    )
    emit(
        f"  {heldout.weeks} week(s), {heldout.matchups:,} matchup(s), "
        f"{heldout.lineups:,} lineup(s), {heldout.duration_seconds:.0f}s"
    )
    for block in _surface_blocks(heldout, incumbent):
        emit(block)
    emit(f"  held-out argmin under the same rule: {heldout.best()}")
    emit(
        "  (reported for stability only — the recommendation is the tuning "
        "selection, whatever this says)"
    )

    # -- head to head --------------------------------------------------------
    emit()
    emit("-" * 118)
    emit("4. INCUMBENT VERSUS CANDIDATE")
    emit("-" * 118)
    candidate_player = {
        "tuning": player_metrics(
            tuning_players, candidate, label=f"tuning {candidate}"
        ),
        "held-out": player_metrics(
            heldout_players, candidate, label=f"held-out {candidate}"
        ),
    }
    for period, sweep in (("tuning", tuning), ("held-out", heldout)):
        emit()
        emit(f"  {period.upper()}")
        emit(
            _comparison_table(
                sweep.results[incumbent],
                sweep.results[candidate],
                baseline_player[period],
                candidate_player[period],
            )
        )

    emit()
    emit("  PAIRED DIFFERENCES ON HELD-OUT DATA — candidate minus incumbent")
    emit(
        "    same lineups, same draws, so each difference isolates the tail "
        "configuration"
    )
    paired = run_sweep(
        panel,
        grid=(incumbent, candidate),
        seasons=HELDOUT_SEASONS,
        period="held-out paired",
        matchups_per_week=arguments.matchups_per_week,
        iterations=arguments.iterations,
        collect_series=True,
    )
    # The paired run reproduces the grid's lineups and draws exactly; if it did
    # not, the standard errors below would belong to a different experiment
    # than the point estimates above.
    for factors in (incumbent, candidate):
        drift = abs(
            paired.results[factors].lineup.crps - heldout.results[factors].lineup.crps
        )
        if drift > 1e-9:
            raise AssertionError(
                f"the paired run did not reproduce the held-out sweep for "
                f"{factors}: CRPS differs by {drift:.2e}"
            )
    for metric, series, better in (
        ("lineup CRPS", "crps", "negative"),
        ("lineup 80% coverage", "inside_80", "toward nominal"),
        ("lineup 90% coverage", "inside_90", "toward nominal"),
        ("lineup PIT centrality", "pit_centrality", "toward 0.250"),
        ("lineup 80% width", "width_80", "context"),
    ):
        delta = paired_delta(
            f"{metric} [{better}]",
            paired.results[incumbent].lineup_series[series],
            paired.results[candidate].lineup_series[series],
        )
        emit("    " + str(delta))
    for metric, series, better in (
        ("win probability Brier", "brier", "negative"),
        ("score differential CRPS", "margin_crps", "negative"),
        ("differential 80% coverage", "margin_inside_80", "toward nominal"),
    ):
        delta = paired_delta(
            f"{metric} [{better}]",
            paired.results[incumbent].matchup_series[series],
            paired.results[candidate].matchup_series[series],
        )
        emit("    " + str(delta))

    emit()
    emit("  LINEUP-TOTAL PIT (held-out, 0.100 is calibrated)")
    incumbent_pit = heldout.results[incumbent].lineup.pit
    candidate_pit = heldout.results[candidate].lineup.pit
    for index, (first, second) in enumerate(zip(incumbent_pit, candidate_pit)):
        emit(
            f"    [{index / 10:.1f},{index / 10 + 0.1:.1f})   "
            f"incumbent {first:.4f}   candidate {second:.4f}"
        )

    emit()
    emit("  WIN PROBABILITY CALIBRATION (held-out; incumbent | candidate)")
    emit(
        f"    {'bin':<12}{'n':>8}{'stated':>9}{'actual':>9}"
        f"{'n':>10}{'stated':>9}{'actual':>9}"
    )
    by_bin = {b.lower: b for b in heldout.results[candidate].matchup.calibration}
    for first in heldout.results[incumbent].matchup.calibration:
        second = by_bin.get(first.lower)
        cells = (
            f"{second.count:>10,}{second.mean_predicted:>9.3f}"
            f"{second.observed_rate:>9.3f}"
            if second else " " * 28
        )
        emit(
            f"    {first.lower:.1f}-{first.upper:.1f}   {first.count:>8,}"
            f"{first.mean_predicted:>9.3f}{first.observed_rate:>9.3f}{cells}"
        )
    emit("    (max calibration error ignores bins under 30; read it, not ECE alone)")

    # -- shape of the error --------------------------------------------------
    emit()
    emit("-" * 118)
    emit("5. THE SHAPE OF THE ERROR — is one global pair of factors enough?")
    emit("-" * 118)
    emit("  held-out, by stratum")
    for label in sorted(heldout.results[incumbent].strata):
        first = heldout.results[incumbent].strata[label]
        second = heldout.results[candidate].strata[label]
        emit(f"    {label}")
        emit("      incumbent " + str(first))
        emit("      candidate " + str(second))

    emit()
    emit("  lineup size sensitivity (held-out, fresh draws per shape)")
    for name, shape in SHAPES.items():
        sized = run_sweep(
            panel,
            grid=(incumbent, candidate),
            seasons=HELDOUT_SEASONS,
            period=f"held-out {name}",
            matchups_per_week=max(10, arguments.matchups_per_week // 2),
            iterations=arguments.iterations,
            lineup_shape=shape,
            seed=20260901,
        )
        emit(f"    {name}")
        emit("      incumbent " + str(sized.results[incumbent].lineup))
        emit("      candidate " + str(sized.results[candidate].lineup))

    # -- the 4% gap ----------------------------------------------------------
    emit()
    emit("-" * 118)
    emit("6. EXPECTED SCORE VERSUS PROJECTION SUM — the Phase 6A gap, measured")
    emit("-" * 118)
    for period, sweep in (("tuning", tuning), ("held-out", heldout)):
        for label, factors in (("incumbent", incumbent), ("candidate", candidate)):
            metrics = sweep.results[factors].lineup
            emit(
                f"  {period:<9} {label:<10} {str(factors):<18} "
                f"simulated mean {metrics.mean_predicted:7.2f}  "
                f"projection sum {metrics.mean_predicted - metrics.mean_drift:7.2f}  "
                f"gap {metrics.mean_drift:+6.3f} ({metrics.mean_drift_share:+.2%})  "
                f"realised mean {metrics.mean_actual:7.2f}"
            )
    emit()
    emit("  player level, same question")
    for period, metrics in (
        ("tuning", baseline_player["tuning"]),
        ("held-out", baseline_player["held-out"]),
    ):
        emit(
            f"  {period:<9} incumbent  curve mean minus stored expected "
            f"{metrics.mean_drift:+.4f} ({metrics.mean_drift_share:+.2%})"
        )
    for period, metrics in (
        ("tuning", candidate_player["tuning"]),
        ("held-out", candidate_player["held-out"]),
    ):
        emit(
            f"  {period:<9} candidate  curve mean minus stored expected "
            f"{metrics.mean_drift:+.4f} ({metrics.mean_drift_share:+.2%})"
        )

    # -- correlation ---------------------------------------------------------
    if not arguments.skip_correlation:
        emit()
        emit("-" * 118)
        emit("7. CORRELATION, RE-TESTED UNDER BOTH TAIL CONFIGURATIONS")
        emit("-" * 118)
        emit(
            "  each arm's structure is refitted from the PIT of the marginals it "
            "is simulated with; a correlation is a property of the PIT, and the "
            "PIT moves when the tails do"
        )
        correlation_arms: dict[tuple[str, str], FactorResult] = {}
        for label, factors in (("incumbent", incumbent), ("candidate", candidate)):
            started = time.monotonic()
            models = dict(
                walk_forward_models(
                    panel, seasons=HELDOUT_SEASONS, factors=factors.as_pair()
                )
            )
            fitted = sum(1 for model in models.values() if model is not None)
            emit(
                f"  {label} {factors}: {fitted} of {len(models)} held-out week(s) "
                f"have a prior-fitted structure ({time.monotonic() - started:.0f}s)"
            )
            for mode_label, sampler_for in (
                ("independent", None),
                ("correlated", correlated_sampler_factory(models)),
            ):
                arm = run_sweep(
                    panel,
                    grid=(factors,),
                    seasons=HELDOUT_SEASONS,
                    period=f"{mode_label}/{label}",
                    matchups_per_week=arguments.matchups_per_week,
                    iterations=arguments.iterations,
                    sampler_for=sampler_for,
                    weeks_filter=weeks_with_models(models),
                    seed=20261001,
                )
                result = arm.results[factors]
                emit(f"    {mode_label:<12} {result.lineup}")
                emit(f"    {'':<12} {result.matchup}")
                correlation_arms[(label, mode_label)] = result

        # Stacked lineups only. The overall numbers are dominated by lineups
        # whose players share no game, where the two samplers agree by
        # construction; if correlation has become worth having once the tails
        # stop over-dispersing, this is the population it shows up in.
        emit()
        emit("  STACKED LINEUPS ONLY (every synthesised lineup is a QB stack)")
        for label, factors in (("incumbent", incumbent), ("candidate", candidate)):
            models = dict(
                walk_forward_models(
                    panel, seasons=HELDOUT_SEASONS, factors=factors.as_pair()
                )
            )
            for mode_label, sampler_for in (
                ("independent", None),
                ("correlated", correlated_sampler_factory(models)),
            ):
                arm = run_sweep(
                    panel,
                    grid=(factors,),
                    seasons=HELDOUT_SEASONS,
                    period=f"stacked {mode_label}/{label}",
                    matchups_per_week=arguments.matchups_per_week,
                    iterations=arguments.iterations,
                    stack_share=1.0,
                    sampler_for=sampler_for,
                    weeks_filter=weeks_with_models(models),
                    seed=20261101,
                )
                result = arm.results[factors]
                emit(f"    {label + '/' + mode_label:<26} {result.lineup}")
                emit(f"    {'':<26} {result.matchup}")

    # -- performance ---------------------------------------------------------
    emit()
    emit("-" * 118)
    emit("8. PERFORMANCE — recalibration must not cost anything")
    emit("-" * 118)
    emit("  fourteen players, one core, independent sampler")
    emit(f"  {'iterations':>12}  {'incumbent':>12}  {'candidate':>12}  {'ratio':>7}")
    for iterations in (1_000, 10_000, 25_000, 50_000):
        timings = []
        for factors in (incumbent, candidate):
            inputs = _benchmark_inputs(panel, factors)
            started = time.perf_counter()
            simulate(
                inputs[:7], inputs[7:], iterations=iterations, seed=20260101
            )
            timings.append(time.perf_counter() - started)
        emit(
            f"  {iterations:>12,}  {timings[0] * 1000:>10.1f} ms  "
            f"{timings[1] * 1000:>10.1f} ms  {timings[1] / timings[0]:>7.3f}"
        )

    emit()
    emit("=" * 118)
    emit("PHASE 6C — no production constant has been changed by this script.")
    emit(
        f"baseline {incumbent}; selected candidate {candidate}. "
        f"nflfp/services/distributions.py ships {shipped}."
    )
    emit("=" * 118)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nwrote {REPORT_PATH}")
    return 0


# ---------------------------------------------------------------------------
# Report helpers
# ---------------------------------------------------------------------------


def _ranked(sweep: SweepResult) -> list[FactorResult]:
    return sorted(
        sweep.results.values(),
        key=lambda r: (round(r.lineup.pit_divergence, 4), r.lineup.crps),
    )


def _neighbourhood(
    sweep: SweepResult, centre: TailFactors, step: float = 0.5
) -> list[FactorResult]:
    return [
        result
        for factors, result in sorted(sweep.results.items())
        if abs(factors.lower - centre.lower) <= step + 1e-9
        and abs(factors.upper - centre.upper) <= step + 1e-9
    ]


def _surface_blocks(sweep: SweepResult, incumbent: TailFactors) -> list[str]:
    """The two-dimensional surface, one table per metric.

    Printed as a grid rather than a ranked list on purpose: the question is
    whether there is a *region* of good performance, and a sorted list of 36
    numbers hides the shape that answers it.
    """
    metrics = (
        ("lineup PIT divergence (lower is flatter; primary)",
         lambda m: f"{m.pit_divergence:.4f}"),
        ("lineup CRPS (lower is better)", lambda m: f"{m.crps:7.4f}"),
        ("lineup 80% interval coverage (nominal 0.800)",
         lambda m: f"{m.coverage_80:.4f}"),
        ("lineup 90% interval coverage (nominal 0.900)",
         lambda m: f"{m.coverage_90:.4f}"),
        ("lineup P50 coverage (nominal 0.500)",
         lambda m: f"{m.knot_coverage[2]:.4f}"),
        ("simulated mean minus projection sum, as a share",
         lambda m: f"{m.mean_drift_share:+.3%}"),
    )
    lowers = sorted({f.lower for f in sweep.results})
    uppers = sorted({f.upper for f in sweep.results})

    blocks = []
    for title, render in metrics:
        rows = [f"  {title}   [* = incumbent]"]
        rows.append(
            "    lower\\upper" + "".join(f"{value:>10.2f}" for value in uppers)
        )
        for lower in lowers:
            cells = []
            for upper in uppers:
                factors = TailFactors(lower, upper)
                text = render(sweep.results[factors].lineup)
                cells.append(f"{text + ('*' if factors == incumbent else ''):>10}")
            rows.append(f"    {lower:>11.2f}" + "".join(cells))
        blocks.append("\n".join(rows))
    return blocks


def _comparison_table(
    incumbent: FactorResult,
    candidate: FactorResult,
    incumbent_player,
    candidate_player,
) -> str:
    """The table the decision is read off."""
    rows: list[tuple[str, float, float, str]] = [
        ("lineup P10 coverage (0.100)",
         incumbent.lineup.knot_coverage[0], candidate.lineup.knot_coverage[0], "{:.4f}"),
        ("lineup P25 coverage (0.250)",
         incumbent.lineup.knot_coverage[1], candidate.lineup.knot_coverage[1], "{:.4f}"),
        ("lineup P50 coverage (0.500)",
         incumbent.lineup.knot_coverage[2], candidate.lineup.knot_coverage[2], "{:.4f}"),
        ("lineup P75 coverage (0.750)",
         incumbent.lineup.knot_coverage[3], candidate.lineup.knot_coverage[3], "{:.4f}"),
        ("lineup P90 coverage (0.900)",
         incumbent.lineup.knot_coverage[4], candidate.lineup.knot_coverage[4], "{:.4f}"),
        ("80% interval coverage (0.800)",
         incumbent.lineup.coverage_80, candidate.lineup.coverage_80, "{:.4f}"),
        ("90% interval coverage (0.900)",
         incumbent.lineup.coverage_90, candidate.lineup.coverage_90, "{:.4f}"),
        ("mean 80% width",
         incumbent.lineup.mean_width_80, candidate.lineup.mean_width_80, "{:.2f}"),
        ("mean 90% width",
         incumbent.lineup.mean_width_90, candidate.lineup.mean_width_90, "{:.2f}"),
        ("lineup PIT divergence",
         incumbent.lineup.pit_divergence, candidate.lineup.pit_divergence, "{:.4f}"),
        ("lineup CRPS",
         incumbent.lineup.crps, candidate.lineup.crps, "{:.4f}"),
        ("player CRPS",
         incumbent_player.crps, candidate_player.crps, "{:.4f}"),
        ("player knot error",
         incumbent_player.knot_error, candidate_player.knot_error, "{:.4f}"),
        ("win probability Brier",
         incumbent.matchup.brier, candidate.matchup.brier, "{:.5f}"),
        ("win probability log loss",
         incumbent.matchup.log_loss, candidate.matchup.log_loss, "{:.5f}"),
        ("ECE", incumbent.matchup.ece, candidate.matchup.ece, "{:.4f}"),
        ("max calibration error",
         incumbent.matchup.max_calibration_error,
         candidate.matchup.max_calibration_error, "{:.4f}"),
        ("score differential CRPS",
         incumbent.matchup.margin_crps, candidate.matchup.margin_crps, "{:.4f}"),
        ("score differential 80% coverage",
         incumbent.matchup.margin_coverage_80,
         candidate.matchup.margin_coverage_80, "{:.4f}"),
        ("expected score minus projection sum",
         incumbent.lineup.mean_drift, candidate.lineup.mean_drift, "{:+.3f}"),
    ]
    out = [
        f"    {'metric':<38}{'incumbent':>12}{'candidate':>12}{'change':>12}",
        "    " + "-" * 74,
    ]
    for label, first, second, fmt in rows:
        out.append(
            f"    {label:<38}{fmt.format(first):>12}{fmt.format(second):>12}"
            f"{fmt.format(second - first):>12}"
        )
    return "\n".join(out)


def _benchmark_inputs(panel: Panel, factors: TailFactors) -> list[SimulationInput]:
    """Fourteen real rows, as the engine takes them."""
    rows = [row for row in panel.rows if row.expected >= 6.0][:14]
    return [
        SimulationInput(
            player_id=row.player_id, name=row.player_id, slot=row.position,
            position=row.position, team=row.team, game_id=row.game_id,
            curve=build_curve(row, factors), expected_points=row.expected,
            floor=row.p10, ceiling=row.p90,
        )
        for row in rows
    ]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
