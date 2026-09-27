"""Judge a challenger model against the frozen foundation, the only way that counts.

Runs the incumbent and the challenger through the same walk-forward harness,
over the same seasons, from one load of the same rows, and checks both against
``ACCEPTANCE`` with the same reduction the scheduled drift check uses
(``nflfp.predict.backtest.acceptance_inputs``).

    python scripts/challenger_eval.py lightgbm_components
    python scripts/challenger_eval.py lightgbm_components --seasons 2023 2024 2025

The incumbent is run too, not read from ``VALIDATION``. If the harness no longer
reproduces the frozen record, that is the first thing to know, and a challenger
compared against a stale number has been compared to nothing.

Writes artifacts/challenger_<model>_report.txt and _metrics.json and prints the
report. Exit status is 0 whether or not the challenger passes: failing the bar
is a result, not an error.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nflfp.db import session_scope  # noqa: E402
from nflfp.predict.backtest import acceptance_inputs, run_backtest  # noqa: E402
from nflfp.predict.dataset import load_rows  # noqa: E402
from nflfp.predict.foundation import (  # noqa: E402
    FROZEN_MODEL,
    VALIDATION,
    VALIDATION_SEASONS,
    meets_acceptance,
)
from nflfp.predict.registry import get_model_factory  # noqa: E402


def _headline(result) -> dict:
    inputs = acceptance_inputs(result)
    return {
        "coverage_p10_p90": round(inputs["coverage_p10_p90"], 4),
        "coverage_p25_p75": next(
            (round(c.observed, 4) for c in result.coverage if c.nominal == 0.50), None
        ),
        "width_p10_p90": next(
            (round(c.mean_width, 3) for c in result.coverage if c.nominal == 0.80), None
        ),
        "crps": round(inputs["crps"], 4),
        "max_calibration_error": round(inputs["max_calibration_error"], 4),
        "max_conditional_bias": round(inputs["max_conditional_bias"], 4),
        "mae_by_position": {k: round(v, 4) for k, v in sorted(inputs["mae_by_position"].items())},
    }


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

    # "Beats baseline_l4" is judged against the baseline on these seasons, not
    # the recorded 2023-25 bar: earlier seasons are harder for every model.
    baseline = run_backtest(
        get_model_factory("baseline_l4"), rows, test_seasons=args.seasons,
        profile=args.profile, fit_distribution=False,
    )
    baseline_mae = {p: round(m.mae, 4) for p, m in sorted(baseline.by_position.items())}

    lines: list[str] = []
    verdicts: dict[str, dict] = {}
    for name in (FROZEN_MODEL, args.challenger):
        result = run_backtest(
            get_model_factory(name), rows, test_seasons=args.seasons, profile=args.profile
        )
        passed, reasons = meets_acceptance(**acceptance_inputs(result, baseline))
        verdicts[name] = {
            "passed": passed,
            "failures": list(reasons),
            "headline": _headline(result),
            "metrics": result.as_metrics(),
        }
        lines += [
            result.report(),
            "",
            f"ACCEPTANCE: {'PASS' if passed else 'FAIL'}",
            *(f"  - {reason}" for reason in reasons),
            "",
            "",
        ]

    incumbent = verdicts[FROZEN_MODEL]["headline"]
    challenger = verdicts[args.challenger]["headline"]
    lines += [
        f"HEAD TO HEAD — seasons {args.seasons[0]}-{args.seasons[-1]}, {args.profile}",
        "=" * 88,
        f"  {'':<24}{FROZEN_MODEL:>18}{args.challenger:>26}",
    ]
    for key in ("crps", "coverage_p10_p90", "coverage_p25_p75", "width_p10_p90",
                "max_calibration_error", "max_conditional_bias"):
        lines.append(f"  {key:<24}{incumbent[key]!s:>18}{challenger[key]!s:>26}")
    for position in sorted(incumbent["mae_by_position"]):
        lines.append(
            f"  {'MAE ' + position:<24}{incumbent['mae_by_position'][position]!s:>18}"
            f"{challenger['mae_by_position'].get(position)!s:>26}"
            f"   (baseline_l4 {baseline_mae.get(position)})"
        )
    if tuple(args.seasons) == VALIDATION_SEASONS:
        lines.append(
            f"\n  frozen record CRPS {VALIDATION.crps}; this run reproduced "
            f"{incumbent['crps']} for {FROZEN_MODEL}"
        )
    lines.append(f"\n  total {time.monotonic() - started:.0f}s")

    report = "\n".join(lines)
    print(report)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"challenger_{args.challenger}_report.txt").write_text(report, encoding="utf-8")
    (out / f"challenger_{args.challenger}_metrics.json").write_text(
        json.dumps(
            {
                "seasons": args.seasons,
                "profile": args.profile,
                "baseline_l4_mae": baseline_mae,
                **verdicts,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
