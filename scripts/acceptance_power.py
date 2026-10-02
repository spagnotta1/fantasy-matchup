"""How much of the conditional-bias acceptance criterion is signal?

``ACCEPTANCE.max_conditional_bias`` limits the absolute bias of the calibrated
expectation in every projection band with a usable sample. A band's bias is a
mean over a few hundred noisy outcomes at the top of the range, so it has a
standard error — and a criterion whose limit is smaller than that error fails
well-calibrated models and passes badly-calibrated ones at close to the same
rate. This script measures that, on the real walk-forward predictions:

    python scripts/acceptance_power.py lightgbm_components

For the frozen model and the challenger it reports each reliable band's bias
with a bootstrap standard error, and the share of resamples in which the model
would clear the limit. The bootstrap resamples **weeks** with replacement, not
player-weeks: outcomes inside a week share a slate, and a quarterback's big day
is his receivers' big day, so the week is the independent unit.

It changes nothing about how a challenger is judged. ``challenger_eval.py`` is
still the verdict; this is the error bar on one line of it.

Writes artifacts/acceptance_power_report.txt and prints it. Seeded, so two runs
print the same numbers.
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nflfp.db import session_scope  # noqa: E402
from nflfp.predict.backtest import BacktestResult, run_backtest  # noqa: E402
from nflfp.predict.calibration import MIN_BIN_FOR_MAX, PROJECTION_BANDS  # noqa: E402
from nflfp.predict.dataset import load_rows  # noqa: E402
from nflfp.predict.foundation import (  # noqa: E402
    ACCEPTANCE,
    FROZEN_MODEL,
    VALIDATION_SEASONS,
)
from nflfp.predict.registry import get_model_factory  # noqa: E402

DRAWS = 5_000
SEED = 20261001


def _band_label(low: float, high: float) -> str:
    return f"{low:.0f}-{high:.0f}" if high != float("inf") else f"{low:.0f}+"


def weekly_band_sums(result: BacktestResult) -> list[list[tuple[int, float]]]:
    """Per week, per projection band: (count, summed expected-minus-actual).

    Bands are assigned on the calibrated expectation, exactly as
    ``by_projection_range`` assigns them, so resampling these reproduces the
    statistic the acceptance check reads.
    """
    weeks: dict[tuple[int, int], list[list[float]]] = defaultdict(
        lambda: [[0, 0.0] for _ in PROJECTION_BANDS]
    )
    for prediction in result.scored:
        expected = prediction.distribution.expected_points
        for index, (low, high) in enumerate(PROJECTION_BANDS):
            if low <= expected < high:
                cell = weeks[(prediction.season, prediction.week)][index]
                cell[0] += 1
                cell[1] += expected - prediction.actual
                break
    return [[(int(n), total) for n, total in weeks[key]] for key in sorted(weeks)]


def bootstrap(
    weekly: list[list[tuple[int, float]]], *, draws: int = DRAWS, seed: int = SEED
) -> tuple[float, list[float | None]]:
    """Share of week-resamples clearing the limit, and each band's standard error."""
    rng = random.Random(seed)
    bands = len(PROJECTION_BANDS)
    cleared = 0
    samples: list[list[float]] = [[] for _ in range(bands)]
    for _ in range(draws):
        counts = [0] * bands
        totals = [0.0] * bands
        for _ in range(len(weekly)):
            for index, (n, total) in enumerate(weekly[rng.randrange(len(weekly))]):
                counts[index] += n
                totals[index] += total
        worst = 0.0
        for index in range(bands):
            if counts[index] >= MIN_BIN_FOR_MAX:
                bias = totals[index] / counts[index]
                samples[index].append(bias)
                worst = max(worst, abs(bias))
        cleared += worst <= ACCEPTANCE.max_conditional_bias

    errors: list[float | None] = []
    for values in samples:
        if len(values) < draws // 2:
            errors.append(None)  # the band is too sparse to be reliable in most resamples
            continue
        centre = sum(values) / len(values)
        errors.append((sum((v - centre) ** 2 for v in values) / (len(values) - 1)) ** 0.5)
    return cleared / draws, errors


def section(result: BacktestResult) -> list[str]:
    rate, errors = bootstrap(weekly_band_sums(result))
    measured = {entry.label: entry for entry in result.ranges}
    limit = ACCEPTANCE.max_conditional_bias
    lines = [f"{result.model_name} v{result.model_version}", "-" * 78]
    for (low, high), error in zip(PROJECTION_BANDS, errors):
        entry = measured.get(_band_label(low, high))
        if entry is None or not entry.reliable or error is None:
            continue
        resolvable = "" if error <= limit / 2 else "   <- error exceeds half the limit"
        lines.append(
            f"  {entry.label:<7} n={entry.n:>6,}  bias={entry.bias:+.2f}  "
            f"se={error:.2f}  ({abs(entry.bias) / error:.1f} se from zero){resolvable}"
        )
    lines += [
        f"  clears |bias| <= {limit:.2f} in {rate:.1%} of {DRAWS:,} week-resamples",
        "",
    ]
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("challenger")
    parser.add_argument("--seasons", type=int, nargs="+", default=list(VALIDATION_SEASONS))
    parser.add_argument("--profile", default="half_ppr")
    parser.add_argument("--out-dir", default="artifacts")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")

    started = time.monotonic()
    with session_scope() as session:
        rows = load_rows(session, completed_only=True)

    lines = [
        "CONDITIONAL-BIAS CRITERION — sampling error on the real walk-forward predictions",
        "=" * 78,
        f"seasons {args.seasons[0]}-{args.seasons[-1]}, {args.profile}; "
        f"bias is calibrated expectation minus actual, per projection band",
        f"standard errors from {DRAWS:,} resamples of whole weeks, seed {SEED}",
        "",
    ]
    for name in (FROZEN_MODEL, args.challenger):
        result = run_backtest(
            get_model_factory(name), rows, test_seasons=args.seasons, profile=args.profile
        )
        lines += section(result)
    lines.append(f"total {time.monotonic() - started:.0f}s")

    report = "\n".join(lines)
    print(report)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "acceptance_power_report.txt").write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
