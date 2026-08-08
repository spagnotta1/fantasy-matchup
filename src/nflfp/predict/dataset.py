"""Loading the model-ready dataset and splitting it without leaking the future.

Walk-forward, not random
------------------------
This module's reason to exist is one rule: **train only on weeks that had
already happened.** A random train/test split on time-series data lets a model
learn from week 12 to predict week 5. It does not error, it does not look wrong,
and it produces validation numbers that are simply fiction.

So :func:`walk_forward` yields splits where every training row strictly precedes
every test row, and :func:`assert_no_leakage` re-checks that on the actual rows
rather than trusting the loop that built them. It is the Layer 3 counterpart of
the lag rule that governs Layer 2's windows.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from .base import POSITIONS, FeatureRow

logger = logging.getLogger(__name__)

#: The engine's only input. Named once, here, so the boundary is greppable.
SOURCE_TABLE = "feat_training_dataset"


def load_rows(
    session: Session,
    *,
    seasons: Sequence[int] | None = None,
    positions: Sequence[str] = POSITIONS,
    completed_only: bool = False,
    upcoming_only: bool = False,
) -> list[dict]:
    """Read player-weeks from the feature table.

    Args:
        session: Open session.
        seasons: Restrict to these seasons; all if omitted.
        positions: Restrict to these positions.
        completed_only: Only rows with a realised outcome — the training set.
        upcoming_only: Only rows without one — what there is to project.

    Returns:
        Rows as plain dicts, ordered chronologically then by player, which makes
        every downstream operation deterministic.
    """
    if completed_only and upcoming_only:
        raise ValueError("completed_only and upcoming_only are mutually exclusive")

    clauses = ["position = ANY(:positions)"]
    params: dict[str, object] = {"positions": list(positions)}
    if seasons:
        clauses.append("season = ANY(:seasons)")
        params["seasons"] = list(seasons)
    if completed_only:
        clauses.append("fp_half_ppr_actual IS NOT NULL")
    if upcoming_only:
        clauses.append("fp_half_ppr_actual IS NULL")

    statement = text(
        f"SELECT * FROM {SOURCE_TABLE} WHERE {' AND '.join(clauses)} "
        "ORDER BY season, week, player_id"
    )
    rows = [dict(row) for row in session.execute(statement, params).mappings()]
    logger.info("loaded %d row(s) from %s", len(rows), SOURCE_TABLE)
    return rows


@dataclass(frozen=True)
class Split:
    """One walk-forward fold: everything before a week, and that week."""

    season: int
    week: int
    train: list[dict]
    test: list[dict]

    @property
    def label(self) -> str:
        return f"{self.season}w{self.week:02d}"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Split {self.label} train={len(self.train)} test={len(self.test)}>"


def _ordinal(row: FeatureRow) -> tuple[int, int]:
    return (int(row["season"]), int(row["week"]))


def walk_forward(
    rows: Sequence[dict],
    *,
    test_seasons: Sequence[int],
    min_train_rows: int = 500,
) -> Iterator[Split]:
    """Yield one split per (season, week) in `test_seasons`, in order.

    Training data is every row strictly earlier than the test week — including
    earlier seasons, which is what a real deployment would have.

    Args:
        rows: Completed player-weeks, any order.
        test_seasons: Seasons to evaluate.
        min_train_rows: Skip a week whose training set is too small to mean
            anything, rather than reporting a metric computed on noise.

    Yields:
        Splits in chronological order.
    """
    ordered = sorted(rows, key=lambda r: (_ordinal(r), str(r["player_id"])))
    weeks = sorted({_ordinal(r) for r in ordered if int(r["season"]) in set(test_seasons)})

    for season, week in weeks:
        cutoff = (season, week)
        train = [r for r in ordered if _ordinal(r) < cutoff]
        test = [r for r in ordered if _ordinal(r) == cutoff]
        if not test:
            continue
        if len(train) < min_train_rows:
            logger.debug("skipping %s%02d — only %d training rows", season, week, len(train))
            continue
        yield Split(season=season, week=week, train=train, test=test)


def assert_no_leakage(split: Split) -> None:
    """Verify a split really does keep the future out.

    Re-checks the rows themselves rather than trusting the code that built
    them. This is cheap and catches the one class of bug that would otherwise
    invalidate every number the backtest produces.

    Raises:
        ValueError: if any training row is not strictly earlier than every test
            row, or the test fold spans more than one week.
    """
    if not split.test:
        raise ValueError(f"{split.label}: empty test fold")

    test_weeks = {_ordinal(r) for r in split.test}
    if len(test_weeks) != 1:
        raise ValueError(f"{split.label}: test fold spans {len(test_weeks)} weeks")

    cutoff = next(iter(test_weeks))
    latest_train = max((_ordinal(r) for r in split.train), default=(0, 0))
    if latest_train >= cutoff:
        raise ValueError(
            f"{split.label}: training data reaches {latest_train}, "
            f"which is not before the test week {cutoff} — this is leakage"
        )


def split_by_position(rows: Sequence[dict]) -> dict[str, list[dict]]:
    """Group rows by position.

    Models are fitted per position: the drivers differ (target share is
    meaningless for a QB) and so do the outcome distributions — tight ends bust
    48.5% of the time against 10.1% for running backs, and one pooled residual
    distribution would describe neither.
    """
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(str(row["position"]), []).append(row)
    return grouped
