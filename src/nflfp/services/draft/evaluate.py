"""Does any of this work? Measured against seasons that have actually happened.

The premise the rest of the package must not be allowed to assume: **that a
higher simulated roster value is a better team.** Simulated value is computed
from the same projections the strategy optimises, so a strategy that games those
projections would score brilliantly and draft badly. The only way to tell the
difference is to draft a season that has since been played and add up what the
roster really scored.

That is possible here, and it is possible *cleanly*, because of how the
projection runs are built. A published run for week 1 of season S is fitted only
on data strictly before week 1 of S — ``predict/generate.py`` asserts it row by
row — and the historical panel this package reads is bounded at S-1. So a draft
for season S sees exactly what a manager saw on draft day, and season S's actual
results exist only on the scoring side of the experiment. Nothing crosses.

What is measured
----------------
**Projection accuracy at season scale.** Correlation and bias of
``season_value`` against actual season points, per position. This is the number
that says whether a per-game rate times an availability estimate is a usable
season projection at all — and, separately, whether it is *equally* usable
across positions, which is what decides whether the draft board is tilted.

**Strategy value.** Four strategies draft the same seats against the same
opponents with the same seeds, and each resulting roster is scored on actual
points. Same board, same luck, different decisions: any difference is the
strategy. The baselines are the ones a sceptic would name — take the highest
projected total, take the highest per-game projection, take at random.

**Availability calibration.** The survival curves are fitted on drafts where
every seat is a consensus drafter, then used in drafts where one seat is not.
That gap is a real bias and it is measurable: bin the predicted probabilities
and compare them with how often the player was actually still there.

What cannot be measured, and is not
-----------------------------------
There is **no real draft data in this repository** — no ADP, no draft results,
no league histories. So the opponent model cannot be validated against how
people really draft, and no number in this module should be read as saying that
it is realistic. It says the strategy beats its baselines *against these
opponents*. Against different opponents the margin would differ, and the
direction of that difference is not knowable from anything on disk.
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .engine import (
    STRATEGIES,
    AvailabilityModel,
    DraftContext,
    simulate_draft,
    survival_table,
)
from .pool import DraftPlayer
from .settings import DraftSettings


@dataclass(frozen=True)
class ProjectionAccuracy:
    """How well a season value predicted an actual season, at one position."""

    position: str
    players: int
    correlation: float | None
    mean_projected: float
    mean_actual: float
    #: ``actual - projected``. Positive means the board under-rated the position
    #: as a whole, which matters far more than it sounds: value over replacement
    #: is a *between-position* comparison, so a position-specific bias moves
    #: every pick in the draft, not just that position's players.
    bias: float
    mean_absolute_error: float


def projection_accuracy(
    players: Sequence[DraftPlayer], actual_points: Mapping[str, float]
) -> tuple[ProjectionAccuracy, ...]:
    """Compare season value with what each player actually scored.

    Players with no actual row scored zero fantasy points that season — they did
    not play — and are included as zero rather than dropped. Dropping them would
    measure the projection only on players it got right about availability,
    which is the half of the estimate most likely to be wrong.
    """
    grouped: dict[str, list[tuple[float, float]]] = {}
    for player in players:
        grouped.setdefault(player.position, []).append(
            (player.season_value, float(actual_points.get(player.player_id, 0.0)))
        )

    results: list[ProjectionAccuracy] = []
    for position, pairs in sorted(grouped.items()):
        projected = [p for p, _ in pairs]
        actual = [a for _, a in pairs]
        results.append(
            ProjectionAccuracy(
                position=position,
                players=len(pairs),
                correlation=_correlation(projected, actual),
                mean_projected=statistics.fmean(projected),
                mean_actual=statistics.fmean(actual),
                bias=statistics.fmean(actual) - statistics.fmean(projected),
                mean_absolute_error=statistics.fmean(
                    [abs(a - p) for p, a in pairs]
                ),
            )
        )
    return tuple(results)


def _correlation(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    if len(xs) < 3:
        return None
    mean_x, mean_y = statistics.fmean(xs), statistics.fmean(ys)
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    dy = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if dx == 0 or dy == 0:
        return None
    return numerator / (dx * dy)


# ---------------------------------------------------------------------------
# Scoring a roster on what actually happened
# ---------------------------------------------------------------------------


def realised_starter_points(
    roster: Sequence[DraftPlayer],
    starters: Sequence[str],
    actual_points: Mapping[str, float],
) -> float:
    """Actual points scored by the lineup the *projections* would have started.

    The starting lineup is the one :func:`~nflfp.services.draft.engine.evaluate_roster`
    chose from projected value — a decision made at draft time — and only the
    scoring uses actuals. Choosing the lineup with hindsight instead would
    measure a manager who knew the season in advance, and would flatter every
    strategy that drafted a wide spread of outcomes.
    """
    del roster  # The starter ids already identify them; kept for call-site clarity.
    return sum(float(actual_points.get(player_id, 0.0)) for player_id in starters)


@dataclass(frozen=True)
class StrategyResult:
    """One strategy's realised performance over a batch of drafts."""

    strategy: str
    drafts: int
    mean_actual_points: float
    median_actual_points: float
    stdev: float
    mean_simulated_value: float

    @property
    def standard_error(self) -> float:
        return self.stdev / math.sqrt(max(1, self.drafts))


def compare_strategies(
    context: DraftContext,
    *,
    availability: AvailabilityModel,
    actual_points: Mapping[str, float],
    seats: Sequence[int],
    simulations: int,
    seed: int,
    strategies: Sequence[str] = STRATEGIES,
) -> tuple[StrategyResult, ...]:
    """Draft the same boards four ways and score each on the real season.

    Every strategy sees an identical sequence of opponent behaviour: the seed
    is keyed on ``(seed, seat, index)`` and not on the strategy, so simulation
    *i* of seat 4 presents the same board to all four. That is a paired
    comparison, and it removes almost all of the variance that would otherwise
    swamp a few points of difference between strategies.
    """
    index_by_id = context.index_by_id
    players = context.players
    results: list[StrategyResult] = []

    tables = {
        seat: survival_table(context, availability, context.order.picks_for(seat))
        for seat in seats
    }

    for strategy in strategies:
        realised: list[float] = []
        simulated: list[float] = []
        for seat in seats:
            for index in range(simulations):
                draft = simulate_draft(
                    context,
                    draft_position=seat,
                    availability=availability,
                    rng=random.Random(f"draft:{seed}:{seat}:{index}"),
                    survival_by_pick=tables[seat],
                    strategy=strategy,
                )
                roster = [players[index_by_id[p.player_id]] for p in draft.picks]
                realised.append(
                    realised_starter_points(roster, draft.starters, actual_points)
                )
                simulated.append(draft.starter_points)

        results.append(
            StrategyResult(
                strategy=strategy,
                drafts=len(realised),
                mean_actual_points=statistics.fmean(realised),
                median_actual_points=statistics.median(realised),
                stdev=statistics.pstdev(realised) if len(realised) > 1 else 0.0,
                mean_simulated_value=statistics.fmean(simulated),
            )
        )
    return tuple(results)


# ---------------------------------------------------------------------------
# Availability calibration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CalibrationBin:
    """One band of predicted availability against what was observed."""

    lower: float
    upper: float
    observations: int
    mean_predicted: float
    observed_rate: float

    @property
    def error(self) -> float:
        return self.observed_rate - self.mean_predicted


def availability_calibration(
    context: DraftContext,
    *,
    availability: AvailabilityModel,
    seat: int,
    simulations: int,
    seed: int,
    bins: int = 10,
) -> tuple[CalibrationBin, ...]:
    """Check the survival curves against drafts the user's strategy took part in.

    The curves are fitted with every seat playing the opponent model, then read
    during drafts where one seat plays something else. This is the measurement
    of that gap: for each of the seat's picks, take the predicted availability
    of every player and record whether they were in fact still on the board.

    A well-calibrated curve puts the observed rate inside each predicted band.
    Systematic error at the top of the range would mean the strategy is
    over-estimating how long players survive and therefore waiting too often —
    the specific failure mode worth catching, because it is invisible in the
    simulated roster value, which would be computed under the same wrong belief.
    """
    picks = set(context.order.picks_for(seat))
    table = survival_table(context, availability, sorted(picks))
    buckets: list[list[tuple[float, bool]]] = [[] for _ in range(bins)]

    for index in range(simulations):
        observed = _availability_trace(
            context,
            draft_position=seat,
            availability=availability,
            rng=random.Random(f"draft:{seed}:{seat}:{index}"),
            table=table,
        )
        for pick, still_available in observed.items():
            predicted = table[pick]
            for player_index, present in enumerate(still_available):
                probability = predicted[player_index]
                bucket = min(bins - 1, int(probability * bins))
                buckets[bucket].append((probability, present))

    results: list[CalibrationBin] = []
    for bucket_index, entries in enumerate(buckets):
        if not entries:
            continue
        results.append(
            CalibrationBin(
                lower=bucket_index / bins,
                upper=(bucket_index + 1) / bins,
                observations=len(entries),
                mean_predicted=statistics.fmean([p for p, _ in entries]),
                observed_rate=statistics.fmean(
                    [1.0 if present else 0.0 for _, present in entries]
                ),
            )
        )
    return tuple(results)


def _availability_trace(
    context: DraftContext,
    *,
    draft_position: int,
    availability: AvailabilityModel,
    rng: random.Random,
    table: Mapping[int, Sequence[float]],
) -> dict[int, list[bool]]:
    """Which players were still on the board at each of one seat's picks.

    A re-implementation of the draft loop rather than a hook inside it: the
    engine's job is to draft, and threading an observer through its inner loop
    would put test scaffolding on the path every production request takes. The
    duplication is bounded — it is the opponent loop and nothing else — and the
    two are held together by using the same ``_opponent_choice`` and the same
    seeded generator.
    """
    from .engine import _opponent_choice, _user_choice  # local: private, and cyclic

    settings = context.settings
    positions = context.positions
    players = context.players
    available = list(range(len(players)))
    counts: list[dict[str, int]] = [{} for _ in range(settings.teams + 1)]
    roster: list[DraftPlayer] = []
    trace: dict[int, list[bool]] = {}

    for slot in context.order:
        held = counts[slot.team]
        if slot.team != draft_position:
            at = _opponent_choice(context, available, held, rng)
            if at is None:
                continue
            index = available.pop(at)
            position = positions[index]
            held[position] = held.get(position, 0) + 1
            continue

        if slot.overall in table:
            live = set(available)
            trace[slot.overall] = [i in live for i in range(len(players))]

        choice = _user_choice(
            context,
            available,
            roster,
            availability=availability,
            survival_by_pick=table,
            picks_remaining=settings.rounds - len(roster),
            overall=slot.overall,
            draft_position=draft_position,
            capture_rationale=False,
            rng=rng,
        )
        if choice is None:
            continue
        index = available.pop(choice[0])
        player = players[index]
        roster.append(player)
        held[player.position] = held.get(player.position, 0) + 1

    return trace


def summarise_calibration(bins: Sequence[CalibrationBin]) -> dict[str, float]:
    """Expected and maximum calibration error, weighted by observation count.

    The same two summaries Layer 3b reports for its boom/bust probabilities, so
    a number here is comparable to a number there rather than being a private
    metric this module invented.
    """
    total = sum(entry.observations for entry in bins)
    if not total:
        return {"expected_calibration_error": 0.0, "max_calibration_error": 0.0}
    return {
        "expected_calibration_error": sum(
            entry.observations * abs(entry.error) for entry in bins
        )
        / total,
        "max_calibration_error": max(abs(entry.error) for entry in bins),
    }
