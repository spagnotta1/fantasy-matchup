"""Phase 6D: should the correlated sampler become the production default?

Run from the repository root::

    python scripts/phase6d_correlation.py

Reuses the Phase 6B panel in ``artifacts/`` — the same 38,061 leakage-free
player-weeks — and writes ``artifacts/phase6d_report.txt``. Nothing here writes
to the database and nothing here changes a production default: the output is
evidence, and promoting the correlated sampler is a separate, manual decision.

Why the question is open again
------------------------------
Phase 6B rejected correlation. Phase 6C then found the rejection was entangled
with the tail factors: the independent simulator's team-total interval was
already too wide, and correlation only ever adds variance under this structure,
so it was being scored for making a too-wide interval worse. Those factors were
recalibrated to ``1.0 / 2.0`` and approved, so the comparison is entitled to be
run again — this time as the primary question rather than as a side-experiment,
and on the marginals that now ship.

The order below is the order the argument has to be made in:

1. the two production candidates, head to head on all held-out matchups;
2. the paired differences, which is where the decision is actually made;
3. the populations the structure makes different predictions about — same-team
   stacks, opposing pairs, quarterback duels, and lineups sharing no game at all;
4. stability: does correlation damage anything it was not meant to touch;
5. marginal preservation, against a Monte Carlo control;
6. team-level expected score against the projection sum;
7. performance, including end-to-end HTTP.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

from nflfp.correlation.estimate import walk_forward_models
from nflfp.correlation.evaluate import SyntheticMatchup, synthesise_matchups
from nflfp.correlation.model import CorrelationMode
from nflfp.correlation.panel import PANEL_SEASONS, Panel, build_panel
from nflfp.correlation.sampler import RosterMember, build_sampler
from nflfp.evaluation.promotion import composition_keys, marginal_comparison
from nflfp.evaluation.tails import (
    HELDOUT_SEASONS,
    FactorResult,
    TailFactors,
    build_curve,
    correlated_sampler_factory,
    paired_delta,
    run_sweep,
    weeks_with_models,
)
from nflfp.services.distributions import LOWER_TAIL_FACTOR, UPPER_TAIL_FACTOR
from nflfp.services.simulation import SimulationInput, simulate

ARTIFACTS = Path("artifacts")
PANEL_PATH = ARTIFACTS / "panel_half_ppr.jsonl"
REPORT_PATH = ARTIFACTS / "phase6d_report.txt"

DEFAULT_DATABASE_URL = "postgresql+psycopg://nflfp:nflfp@localhost:55432/nflfp"

#: Matchups synthesised per week — the Phase 6C figure, so the two reports'
#: samples are the same size and their numbers are comparable.
MATCHUPS_PER_WEEK = 40

#: Draws per lineup. Below the product default deliberately: the Monte Carlo
#: error averages out across thousands of lineups, and both arms see the same
#: lineups, so it cancels in the comparison rather than accumulating.
ITERATIONS = 2_000

RULE = "-" * 118


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild-panel", action="store_true")
    parser.add_argument("--matchups-per-week", type=int, default=MATCHUPS_PER_WEEK)
    parser.add_argument("--iterations", type=int, default=ITERATIONS)
    parser.add_argument(
        "--skip-http",
        action="store_true",
        help="omit the end-to-end HTTP latency measurement, which needs a warehouse",
    )
    parser.add_argument(
        "--database-url", default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    )
    arguments = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
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

    production = TailFactors.incumbent()

    emit("=" * 118)
    emit("PHASE 6D — CORRELATION PROMOTION VALIDATION")
    emit("=" * 118)
    emit(
        f"panel: {len(panel):,} leakage-free player-week(s), "
        f"{panel.profile} / {panel.model_name}"
    )
    emit(
        f"production tail factors: {production}   "
        f"(approved in Phase 6C; distributions.py ships "
        f"{LOWER_TAIL_FACTOR} / {UPPER_TAIL_FACTOR})"
    )
    emit(f"held-out seasons {list(HELDOUT_SEASONS)}")
    emit(
        f"{arguments.matchups_per_week} matchup(s)/week, "
        f"{arguments.iterations:,} draw(s)/lineup"
    )
    emit(
        "both arms see identical lineups and identical realised outcomes; they "
        "differ by the sampler and by nothing else"
    )
    emit()
    emit(
        "  THE COMPARISON IS 1.0/2.0 + independent  vs  1.0/2.0 + correlated. "
        "The old tail factors"
    )
    emit(
        "  do not appear below: they were superseded, and re-litigating them "
        "would spend the sample"
    )
    emit("  on a configuration nothing can now ship.")

    # -- the fitted structure ------------------------------------------------
    emit()
    emit(RULE)
    emit("0. THE FITTED STRUCTURE, RE-ESTIMATED THROUGH THE MARGINALS THAT SHIP")
    emit(RULE)
    emit(
        "  a correlation is a property of the PIT and the PIT moved when the "
        "tails did, so the Phase 6B"
    )
    emit(
        "  fit is not reused; each held-out week's structure is fitted on weeks "
        "strictly before it"
    )
    started = time.monotonic()
    models = dict(walk_forward_models(panel, seasons=HELDOUT_SEASONS))
    fitted = sum(1 for model in models.values() if model is not None)
    emit(
        f"  {fitted} of {len(models)} held-out week(s) have a prior-fitted "
        f"structure ({time.monotonic() - started:.0f}s)"
    )
    latest = next(
        model for _, model in sorted(models.items(), reverse=True) if model is not None
    )
    emit(f"  most recent fit: version {latest.version}")
    emit(f"  {'position':<10}{'game':>9}{'team':>9}{'own':>9}{'shared var':>13}")
    for position in ("QB", "RB", "WR", "TE"):
        loading = latest.loading(position)
        shared = loading.game ** 2 + loading.team ** 2
        emit(
            f"  {position:<10}{loading.game:>9.3f}{loading.team:>9.3f}"
            f"{loading.idiosyncratic:>9.3f}{shared:>13.3f}"
        )

    keep = weeks_with_models(models)
    correlated_for = correlated_sampler_factory(models)

    def arms(
        label: str,
        *,
        seed: int,
        stack_share: float = 0.35,
        opponent_share: float = 0.0,
        duel_share: float = 0.0,
        matchup_filter=None,
        matchups_per_week: int | None = None,
        strata: bool = False,
    ) -> dict[str, FactorResult]:
        """Both samplers over one population, on identical lineups."""
        out: dict[str, FactorResult] = {}
        for mode, sampler_for in (
            ("independent", None),
            ("correlated", correlated_for),
        ):
            sweep = run_sweep(
                panel,
                grid=(production,),
                seasons=HELDOUT_SEASONS,
                period=f"{label}/{mode}",
                matchups_per_week=matchups_per_week or arguments.matchups_per_week,
                iterations=arguments.iterations,
                stack_share=stack_share,
                opponent_share=opponent_share,
                duel_share=duel_share,
                sampler_for=sampler_for,
                weeks_filter=keep,
                matchup_filter=matchup_filter,
                strata=strata,
                strata_keys=composition_keys,
                collect_series=True,
                seed=seed,
            )
            out[mode] = sweep.results[production]
        # The pairing is the whole basis of every standard error below. Both
        # arms draw from the same seed, so they see the same lineups in the same
        # order and a realised tie is dropped from both; if the counts ever
        # disagree, the series are not aligned and the deltas are meaningless.
        if out["independent"].lineup.n != out["correlated"].lineup.n:
            raise AssertionError(
                f"{label}: arms scored {out['independent'].lineup.n} and "
                f"{out['correlated'].lineup.n} lineups; not paired"
            )
        return out

    def deltas(label: str, both: dict[str, FactorResult]) -> None:
        """Correlated minus independent, per observation."""
        if both["independent"].lineup.n < 2:
            emit("    PAIRED DIFFERENCES — too few observations to test")
            return
        emit(f"    PAIRED DIFFERENCES — {label}, correlated minus independent")
        for metric, series, better in (
            ("lineup CRPS", "crps", "negative"),
            ("lineup 80% coverage", "inside_80", "toward 0.800"),
            ("lineup 90% coverage", "inside_90", "toward 0.900"),
            ("lineup PIT centrality", "pit_centrality", "toward 0.250"),
            ("lineup 80% width", "width_80", "context"),
        ):
            emit("      " + str(paired_delta(
                f"{metric} [{better}]",
                both["independent"].lineup_series[series],
                both["correlated"].lineup_series[series],
            )))
        for metric, series, better in (
            ("win probability Brier", "brier", "negative"),
            ("score differential CRPS", "margin_crps", "negative"),
            ("differential 80% coverage", "margin_inside_80", "toward 0.800"),
        ):
            emit("      " + str(paired_delta(
                f"{metric} [{better}]",
                both["independent"].matchup_series[series],
                both["correlated"].matchup_series[series],
            )))

    def head_to_head(both: dict[str, FactorResult]) -> str:
        first, second = both["independent"], both["correlated"]
        if not first.lineup.n:
            return "    no matchup in this population survived the filter"
        rows: list[tuple[str, float, float, str]] = [
            ("80% interval coverage (0.800)",
             first.lineup.coverage_80, second.lineup.coverage_80, "{:.4f}"),
            ("90% interval coverage (0.900)",
             first.lineup.coverage_90, second.lineup.coverage_90, "{:.4f}"),
            ("lineup CRPS",
             first.lineup.crps, second.lineup.crps, "{:.4f}"),
            ("score differential CRPS",
             first.matchup.margin_crps, second.matchup.margin_crps, "{:.4f}"),
            ("lineup PIT divergence",
             first.lineup.pit_divergence, second.lineup.pit_divergence, "{:.4f}"),
            ("max calibration error",
             first.matchup.max_calibration_error,
             second.matchup.max_calibration_error, "{:.4f}"),
            ("--- secondary ---", 0.0, 0.0, ""),
            ("win probability Brier",
             first.matchup.brier, second.matchup.brier, "{:.5f}"),
            ("win probability log loss",
             first.matchup.log_loss, second.matchup.log_loss, "{:.5f}"),
            ("ECE", first.matchup.ece, second.matchup.ece, "{:.4f}"),
            ("--- context ---", 0.0, 0.0, ""),
            ("lineup P50 coverage (0.500)",
             first.lineup.knot_coverage[2], second.lineup.knot_coverage[2], "{:.4f}"),
            ("mean 80% width",
             first.lineup.mean_width_80, second.lineup.mean_width_80, "{:.2f}"),
            ("differential 80% coverage (0.800)",
             first.matchup.margin_coverage_80,
             second.matchup.margin_coverage_80, "{:.4f}"),
            ("win probs outside [0.05,0.95]",
             first.matchup.extreme_share, second.matchup.extreme_share, "{:.4f}"),
            ("expected score minus projection sum",
             first.lineup.mean_drift, second.lineup.mean_drift, "{:+.3f}"),
        ]
        out = [
            f"    {'metric':<38}{'independent':>13}{'correlated':>13}{'delta':>13}",
            "    " + "-" * 77,
        ]
        for label, a, b, fmt in rows:
            if not fmt:
                out.append(f"    {label}")
                continue
            out.append(
                f"    {label:<38}{fmt.format(a):>13}{fmt.format(b):>13}"
                f"{fmt.format(b - a):>13}"
            )
        return "\n".join(out)

    # -- 1. all lineups ------------------------------------------------------
    emit()
    emit(RULE)
    emit("1. ALL HELD-OUT MATCHUPS — the two production candidates")
    emit(RULE)
    started = time.monotonic()
    overall = arms("all", seed=20261201, strata=True)
    emit(
        f"  {overall['independent'].lineup.n:,} lineup(s), "
        f"{overall['independent'].matchup.n:,} matchup(s), "
        f"{time.monotonic() - started:.0f}s"
    )
    emit("  " + str(overall["independent"].lineup))
    emit("  " + str(overall["correlated"].lineup))
    emit("  " + str(overall["independent"].matchup))
    emit("  " + str(overall["correlated"].matchup))
    emit()
    emit(head_to_head(overall))
    emit()
    deltas("all lineups", overall)

    emit()
    emit("  LINEUP-TOTAL PIT (held-out, 0.100 is calibrated)")
    for index, (first, second) in enumerate(
        zip(overall["independent"].lineup.pit, overall["correlated"].lineup.pit)
    ):
        emit(
            f"    [{index / 10:.1f},{index / 10 + 0.1:.1f})   "
            f"independent {first:.4f}   correlated {second:.4f}"
        )

    emit()
    emit("  WIN PROBABILITY CALIBRATION (independent | correlated)")
    emit(
        f"    {'bin':<12}{'n':>8}{'stated':>9}{'actual':>9}"
        f"{'n':>10}{'stated':>9}{'actual':>9}"
    )
    by_bin = {b.lower: b for b in overall["correlated"].matchup.calibration}
    for first in overall["independent"].matchup.calibration:
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

    # -- 2. populations, at the lineup level ---------------------------------
    emit()
    emit(RULE)
    emit("2. BY POPULATION — lineup-level, from the strata of the run above")
    emit(RULE)
    emit(
        "  every lineup is classified by what it holds, not by what the "
        "generator was asked for"
    )
    emit(
        "  nominal cov80 = 0.800, cov90 = 0.900; buckets overlap where a lineup "
        "is more than one thing"
    )
    for label in sorted(overall["independent"].strata):
        first = overall["independent"].strata[label]
        second = overall["correlated"].strata.get(label)
        if second is None or first.n < 30:
            continue
        emit(f"    {label}  (n={first.n:,})")
        emit(
            f"      independent  cov80={first.coverage_80:.4f}  "
            f"cov90={first.coverage_90:.4f}  CRPS={first.crps:.4f}  "
            f"PITdiv={first.pit_divergence:.4f}  width={first.mean_width_80:5.1f}  "
            f"drift={first.mean_drift:+.3f}"
        )
        emit(
            f"      correlated   cov80={second.coverage_80:.4f}  "
            f"cov90={second.coverage_90:.4f}  CRPS={second.crps:.4f}  "
            f"PITdiv={second.pit_divergence:.4f}  width={second.mean_width_80:5.1f}  "
            f"drift={second.mean_drift:+.3f}"
        )

    # -- 3. populations, with the full metric set ----------------------------
    emit()
    emit(RULE)
    emit("3. BY POPULATION — dedicated sweeps, so win probability is measurable too")
    emit(RULE)
    emit(
        "  a stratum of the run above carries lineup metrics only; Brier and "
        "maximum calibration error"
    )
    emit(
        "  are matchup-level, so each population below is drawn deliberately "
        "and scored end to end"
    )

    populations: dict[str, dict[str, FactorResult]] = {}
    for label, kwargs in (
        (
            "same-team stacks (every lineup is a QB stack)",
            dict(seed=20261301, stack_share=1.0),
        ),
        (
            "opposing pairs (every lineup holds a QB and an opposing skill player)",
            dict(seed=20261401, stack_share=0.0, opponent_share=1.0),
        ),
        (
            "quarterback duels (the two lineups' QBs face each other)",
            dict(
                seed=20261501, stack_share=0.0, duel_share=1.0,
                matchup_filter=lambda m: m.quarterbacks_duel,
            ),
        ),
        (
            "unstacked lineups (no two players in one lineup share a game)",
            dict(
                seed=20261601, stack_share=0.0,
                matchup_filter=_no_shared_game,
                # A lineup of fourteen startable players drawn from a sixteen
                # game slate almost always contains *some* shared game, so this
                # population is a few percent of an ordinary draw. The generator
                # is run four times harder and the rest thrown away, which costs
                # a cheap draw per rejected matchup and no simulation at all.
                matchups_per_week=arguments.matchups_per_week * 4,
            ),
        ),
    ):
        emit()
        emit(f"  {label}")
        started = time.monotonic()
        both = arms(label, **kwargs)  # type: ignore[arg-type]
        populations[label] = both
        emit(
            f"    {both['independent'].lineup.n:,} lineup(s), "
            f"{both['independent'].matchup.n:,} matchup(s), "
            f"{time.monotonic() - started:.0f}s"
        )
        emit(head_to_head(both))
        emit()
        deltas(label, both)

    # -- 4. marginal preservation --------------------------------------------
    emit()
    emit(RULE)
    emit("4. MARGINAL PRESERVATION — correlation must change the joint, not a player")
    emit(RULE)
    emit(
        "  each player's own simulated percentiles under the two samplers, and "
        "— as the yardstick —"
    )
    emit(
        "  under the SAME sampler at a different seed. The second row is what "
        "Monte Carlo alone costs;"
    )
    emit("  the first row only means something if it is larger.")
    sample_matchups = _sample_matchups(panel, models, count=12)
    started = time.monotonic()
    against, control = marginal_comparison(
        sample_matchups, model=latest, iterations=20_000
    )
    emit(f"  {len(sample_matchups)} matchup(s), 20,000 draws each, "
         f"{time.monotonic() - started:.0f}s")
    emit("    " + str(against))
    emit("    " + str(control))

    # -- 5. team-level expectation -------------------------------------------
    emit()
    emit(RULE)
    emit("5. TEAM-LEVEL EXPECTED SCORE VERSUS PROJECTION SUM")
    emit(RULE)
    emit(
        "  exact equality is not required and is not wanted — a right-skewed "
        "reconstruction puts its"
    )
    emit(
        "  mean above the sum of its medians. What is required is that the two "
        "samplers agree: a"
    )
    emit("  correlation model may move a total's spread and may not move its centre.")
    emit(
        f"    {'population':<62}{'independent':>13}{'correlated':>13}{'delta':>10}"
    )
    for label, both in (("all lineups", overall), *populations.items()):
        first = both["independent"].lineup
        second = both["correlated"].lineup
        emit(
            f"    {label[:60]:<62}{first.mean_drift:>+13.4f}"
            f"{second.mean_drift:>+13.4f}{second.mean_drift - first.mean_drift:>+10.4f}"
        )
    emit()
    plain = overall["independent"].lineup
    joint = overall["correlated"].lineup
    emit(
        f"    all lineups: simulated mean {plain.mean_predicted:.2f} "
        f"(independent) / {joint.mean_predicted:.2f} (correlated) "
        f"against projection sum {plain.mean_predicted - plain.mean_drift:.2f}"
    )
    emit(
        f"    the gap is {overall['independent'].lineup.mean_drift_share:+.2%} and "
        f"{overall['correlated'].lineup.mean_drift_share:+.2%}; it is a property of "
        "reconstructing a"
    )
    emit(
        "    right-skewed distribution from five percentiles, not of the "
        "sampler, and Phase 6C left it open"
    )
    emit("    as a foundation question deliberately.")

    # -- 6. performance ------------------------------------------------------
    emit()
    emit(RULE)
    emit("6. PERFORMANCE")
    emit(RULE)
    emit("  fourteen players, one core, in-process")
    emit(
        f"  {'iterations':>12}  {'independent':>13}  {'correlated':>13}  {'ratio':>7}"
    )
    benchmark = _benchmark_inputs(panel, production)
    members = [
        RosterMember(position=p.position, team=p.team, game_id=p.game_id)
        for p in benchmark
    ]
    for iterations in (1_000, 10_000, 25_000, 50_000):
        timings = []
        for mode, model in (
            (CorrelationMode.INDEPENDENT, None),
            (CorrelationMode.GAME_ENVIRONMENT, latest),
        ):
            sampler = build_sampler(members, mode=mode, model=model)
            started = time.perf_counter()
            simulate(
                benchmark[:7], benchmark[7:], iterations=iterations,
                seed=20260101, sampler=sampler,
            )
            timings.append(time.perf_counter() - started)
        emit(
            f"  {iterations:>12,}  {timings[0] * 1000:>11.1f} ms  "
            f"{timings[1] * 1000:>11.1f} ms  {timings[1] / timings[0]:>7.2f}x"
        )

    if not arguments.skip_http:
        emit()
        emit("  end to end through the ASGI app against Postgres, 10,000 iterations")
        try:
            for mode, elapsed in _http_latency(arguments.database_url):
                emit(f"    {mode:<20} {elapsed * 1000:>8.1f} ms")
        except Exception as error:  # pragma: no cover - environment dependent
            emit(f"    unavailable: {type(error).__name__}: {error}")
            emit("    (re-run with a seeded warehouse, or pass --skip-http)")

    emit()
    emit("=" * 118)
    emit("PHASE 6D — no production default has been changed by this script.")
    emit("The correlated sampler remains behind correlation_mode: game_environment.")
    emit("The decision is recorded in docs/simulation-readiness.md.")
    emit("=" * 118)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nwrote {REPORT_PATH}")
    return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _no_shared_game(matchup: SyntheticMatchup) -> bool:
    """Neither lineup contains two players from one NFL game.

    The control population, and the strongest single test in the report: under
    this structure two players in different games have correlation **exactly
    zero**, so each side's own interval must come out the same in both arms. If
    it does not, the differences measured everywhere else are the harness rather
    than the model.

    Only the *within-lineup* condition is imposed. Requiring the two lineups to
    share no game with each other as well would cut the population to a fraction
    of a percent — fourteen players over a sixteen-game slate collide somewhere
    almost always — and it is not needed: cross-lineup dependence moves the
    margin and the win probability, and leaves each side's own coverage alone.
    That is exactly the split the quarterback-duel population isolates.
    """
    for lineup in (matchup.team_a, matchup.team_b):
        games = [row.game_id for row in lineup if row.game_id]
        if len(set(games)) != len(games):
            return False
    return True


def _sample_matchups(
    panel: Panel, models: dict, count: int
) -> list[SyntheticMatchup]:
    """A handful of real held-out matchups for the marginal check.

    Stacked and opposing on purpose: a marginal is hardest to preserve where the
    loadings are largest, so checking it on lineups of unrelated players would
    be checking the independent sampler twice.
    """
    out: list[SyntheticMatchup] = []
    for season, week in panel.weeks(HELDOUT_SEASONS):
        if models.get((season, week)) is None:
            continue
        out.extend(
            synthesise_matchups(
                panel.week(season, week), season=season, week=week, count=2,
                stack_share=1.0, opponent_share=1.0,
                seed=20261701 + season * 100 + week,
            )
        )
        if len(out) >= count:
            break
    return out[:count]


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


def _http_latency(database_url: str) -> list[tuple[str, float]]:
    """Time a default-shaped request through the real app, both modes.

    In-process ASGI, so this is the application's latency and not the network's
    — which is the number a bound on synchronous CPU work is about, and the same
    way the Phase 6A figure in the readiness document was produced.
    """
    import asyncio

    os.environ.setdefault("DATABASE_URL", database_url)
    from httpx import ASGITransport, AsyncClient

    from nflfp.api.main import API_PREFIX, create_app

    if sys.platform == "win32":  # pragma: no cover - platform specific
        # psycopg's async mode cannot run on the Proactor loop asyncio picks by
        # default on Windows. Uvicorn selects the selector loop for the same
        # reason, so this makes the measurement match how the app is served.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    async def run() -> list[tuple[str, float]]:
        app = create_app()
        transport = ASGITransport(app=app)
        results: list[tuple[str, float]] = []
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            body = _http_body()
            for mode in ("independent", "game_environment"):
                payload = {**body, "correlation_mode": mode}
                # One warm request first: the first call pays for the connection
                # pool and the slate-window resolution, which are not what this
                # measurement is about.
                warm = await client.post(f"{API_PREFIX}/simulations", json=payload)
                if warm.status_code != 200:
                    raise RuntimeError(
                        f"{mode}: HTTP {warm.status_code} {warm.text[:300]}"
                    )
                started = time.perf_counter()
                await client.post(f"{API_PREFIX}/simulations", json=payload)
                results.append((mode, time.perf_counter() - started))
        return results

    return asyncio.run(run())


def _http_body() -> dict:
    """A default-shaped request built from the published run in the warehouse."""
    import re

    import psycopg

    from nflfp import pg

    # The application reads a SQLAlchemy URL and may carry a `+driver` in its
    # scheme; libpq does not understand one. Dropped here rather than asking the
    # operator to export the same database under two spellings.
    raw_dsn = re.sub(r"^([a-z]+)\+[a-z0-9]+://", r"\1://", pg.dsn())

    slots = ("QB", "RB", "RB", "WR", "WR", "TE", "FLEX")
    wanted = {"QB": 2, "RB": 6, "WR": 6, "TE": 2}
    picked: dict[str, list[str]] = {}
    with psycopg.connect(raw_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT pr.position, pr.player_id, pr.season, pr.week
            FROM projections AS pr
            JOIN projection_points AS pp ON pp.projection_id = pr.id
            WHERE pp.scoring_profile = 'half_ppr'
              AND pp.floor_points IS NOT NULL
              AND pp.median_points IS NOT NULL
              AND pp.ceiling_points IS NOT NULL
            ORDER BY pp.median_points DESC
            """
        )
        season = week = None
        for position, player_id, row_season, row_week in cur.fetchall():
            season, week = row_season, row_week
            if position in wanted and len(picked.get(position, [])) < wanted[position]:
                picked.setdefault(position, []).append(player_id)
    if any(len(picked.get(p, [])) < n for p, n in wanted.items()):
        raise RuntimeError("the warehouse does not hold enough projected starters")

    def lineup(offset: int) -> list[dict]:
        pool = {p: list(ids) for p, ids in picked.items()}
        take = {"QB": offset, "RB": offset * 3, "WR": offset * 3, "TE": offset}
        out = []
        for slot in slots:
            position = "RB" if slot == "FLEX" else slot
            index = take[position]
            take[position] += 1
            out.append({"player_id": pool[position][index], "slot": slot})
        return out

    return {
        "season": season,
        "week": week,
        "scoring_profile": "half_ppr",
        "simulation_count": 10_000,
        "seed": 42,
        "team_a": lineup(0),
        "team_b": lineup(1),
    }


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
