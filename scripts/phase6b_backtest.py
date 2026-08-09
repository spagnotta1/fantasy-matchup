"""Phase 6B: fit the correlation structure and score it against the baseline.

Run from the repository root::

    python scripts/phase6b_backtest.py

Rebuilds nothing it does not have to. The panel is the expensive input — a
walk-forward pass over seven seasons of the frozen prediction foundation — so it
is cached in ``artifacts/`` and reused unless ``--rebuild-panel`` is given.

Everything this prints is the evidence behind
``docs/simulation-readiness.md``. The numbers in that document should be
reproducible by running this script and reading the output.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from nflfp.correlation.estimate import estimate, walk_forward_models
from nflfp.correlation.evaluate import (
    EVALUATION_ITERATIONS,
    MATCHUPS_PER_WEEK,
    run_comparison,
)
from nflfp.correlation.panel import (
    EVALUATION_SEASONS,
    PANEL_SEASONS,
    Panel,
    build_panel,
    pit_uniformity,
    score_panel,
)

ARTIFACTS = Path("artifacts")
PANEL_PATH = ARTIFACTS / "panel_half_ppr.jsonl"
MODEL_PATH = ARTIFACTS / "correlation_model_half_ppr.json"
REPORT_PATH = ARTIFACTS / "phase6b_report.txt"

DEFAULT_DATABASE_URL = "postgresql+psycopg://nflfp:nflfp@localhost:55432/nflfp"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild-panel", action="store_true")
    parser.add_argument("--matchups-per-week", type=int, default=MATCHUPS_PER_WEEK)
    parser.add_argument("--iterations", type=int, default=EVALUATION_ITERATIONS)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL),
    )
    arguments = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    lines: list[str] = []

    def emit(text: str = "") -> None:
        print(text)
        lines.append(text)

    if arguments.rebuild_panel or not PANEL_PATH.exists():
        panel = build_panel(
            database_url=arguments.database_url, seasons=PANEL_SEASONS
        )
        panel.save(PANEL_PATH)
    else:
        panel = Panel.load(PANEL_PATH)

    emit("=" * 118)
    emit("PHASE 6B — CORRELATED MATCHUP SIMULATION")
    emit("=" * 118)
    emit(
        f"panel: {len(panel):,} leakage-free player-week(s), seasons "
        f"{min(r.season for r in panel.rows)}-{max(r.season for r in panel.rows)}, "
        f"{panel.profile} / {panel.model_name}"
    )

    emit()
    emit("MARGINAL CALIBRATION — PIT of the panel's own outcomes (0.100 is flat)")
    emit("  A correlation estimated from these inherits whatever is wrong here.")
    scores = score_panel(panel)
    startable = [s for s in scores if s.row.expected >= 6.0]
    for (lower, _, all_share), (_, _, top_share) in zip(
        pit_uniformity(scores), pit_uniformity(startable)
    ):
        emit(
            f"  [{lower:.1f},{lower + 0.1:.1f})   all {all_share:.4f}   "
            f"startable {top_share:.4f}"
        )

    emit()
    emit("FULL-SAMPLE FIT (for reporting only — the evaluation refits weekly)")
    full = estimate(panel)
    for line in full.describe().splitlines():
        emit(line)
    full.save(MODEL_PATH)
    emit(f"  saved to {MODEL_PATH}")

    emit()
    emit("RESIDUALS, worst first — cells the structure could not reach")
    for cell, observed, fitted in full.estimation.residuals[:8]:
        emit(
            f"  {cell:<16} observed {observed:+.4f}   fitted {fitted:+.4f}   "
            f"gap {observed - fitted:+.4f}"
        )

    emit()
    emit(f"WALK-FORWARD EVALUATION — seasons {list(EVALUATION_SEASONS)}")
    models = dict(walk_forward_models(panel, seasons=EVALUATION_SEASONS))
    fitted = sum(1 for model in models.values() if model is not None)
    emit(f"  {fitted} of {len(models)} evaluated week(s) have a prior-fitted structure")

    comparison = run_comparison(
        panel,
        models=models,
        seasons=EVALUATION_SEASONS,
        matchups_per_week=arguments.matchups_per_week,
        iterations=arguments.iterations,
    )
    emit()
    for line in comparison.report().splitlines():
        emit(line)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nreport written to {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
