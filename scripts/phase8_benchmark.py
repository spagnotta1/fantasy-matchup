"""Phase 8 — how long a mock draft actually takes.

Measures the two costs a request is made of, separately, because they scale
differently: the **calibration** stage is a fixed batch that does not grow with
the requested simulation count, and the **analysis** stage is linear in it. A
single number for "a draft request" would hide that the first thousand
simulations cost more than the second thousand.

    python scripts/phase8_benchmark.py --seasons 2025

Measures before optimising, which is the point: the per-request cap in
``services/draft/service.py`` is a promise about latency, and a promise nothing
measures decays the first time the inner loop gains a line.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nflfp.db.engine import async_session_scope  # noqa: E402
from nflfp.services.draft import aggregate, pool as pool_module  # noqa: E402
from nflfp.services.draft.engine import (  # noqa: E402
    CALIBRATION_DRAFTS,
    DraftContext,
    calibrate_availability,
)
from nflfp.services.draft.service import MAX_TOTAL_DRAFTS  # noqa: E402
from nflfp.services.draft.settings import validate_settings  # noqa: E402

COUNTS = (100, 1_000, 5_000, 10_000)


async def main(season: int, teams: int, rounds: int, profile: str, seed: int) -> int:
    settings = validate_settings(
        teams=teams, rounds=rounds, scoring_profile=profile, season=season, seed=seed
    )

    started = time.perf_counter()
    async with async_session_scope() as session:
        pool = await pool_module.build_pool(session, settings)
    retrieval = time.perf_counter() - started

    started = time.perf_counter()
    context = DraftContext.build(pool, settings)
    build = time.perf_counter() - started

    started = time.perf_counter()
    availability = calibrate_availability(context, seed=seed)
    calibration = time.perf_counter() - started

    print("=" * 72)
    print("PHASE 8 — MOCK DRAFT PERFORMANCE")
    print("=" * 72)
    print(
        f"{teams}-team {profile}, {rounds} rounds, {season} board "
        f"({len(pool.players)} players)"
    )
    print()
    print("Fixed costs, paid once per request regardless of simulation count")
    print(f"  pool retrieval (3 queries)        {retrieval * 1000:8.0f} ms")
    print(f"  context build (levels, tiers)     {build * 1000:8.0f} ms")
    print(
        f"  availability calibration          {calibration * 1000:8.0f} ms"
        f"   ({CALIBRATION_DRAFTS} drafts)"
    )
    print()

    print("Analysis stage — one seat")
    print(f"  {'simulations':>12}{'seconds':>10}{'ms/draft':>10}{'total*':>10}")
    per_draft = None
    for count in COUNTS:
        started = time.perf_counter()
        aggregate.analyse_seat(
            context,
            draft_position=4,
            availability=availability,
            simulations=count,
            seed=seed,
        )
        elapsed = time.perf_counter() - started
        per_draft = elapsed / count
        total = calibration + retrieval + build + elapsed
        print(f"  {count:>12,}{elapsed:>10.2f}{per_draft * 1000:>10.2f}{total:>10.2f}")
    print("  *total includes the fixed costs above")
    print()

    print(f"Comparison — all {teams} seats, sharing one pool and one calibration")
    print(f"  {'per seat':>12}{'total drafts':>14}{'seconds':>10}")
    for count in (50, 100, 250):
        if count * teams > MAX_TOTAL_DRAFTS:
            continue
        started = time.perf_counter()
        for seat in range(1, teams + 1):
            aggregate.analyse_seat(
                context,
                draft_position=seat,
                availability=availability,
                simulations=count,
                seed=seed,
            )
        elapsed = time.perf_counter() - started
        print(f"  {count:>12,}{count * teams:>14,}{elapsed:>10.2f}")
    print()

    if per_draft:
        budget = MAX_TOTAL_DRAFTS * per_draft
        print(
            f"Per-request cap is {MAX_TOTAL_DRAFTS:,} drafts, which at "
            f"{per_draft * 1000:.2f} ms/draft is about {budget:.0f}s of worker time."
        )
    print(
        "The whole analysis stage runs in a worker thread via asyncio.to_thread, "
        "so none of it occupies the event loop."
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=2025)
    parser.add_argument("--teams", type=int, default=12)
    parser.add_argument("--rounds", type=int, default=15)
    parser.add_argument("--profile", default="ppr")
    parser.add_argument("--seed", type=int, default=20260101)
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(main(args.season, args.teams, args.rounds, args.profile, args.seed))
    )
