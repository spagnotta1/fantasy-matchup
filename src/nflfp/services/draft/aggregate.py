"""Many drafts in, a few numbers out.

The rule this module exists to enforce: **a simulation batch produces
aggregates, never a transcript.** Ten thousand drafts of fifteen picks is
150,000 selections per seat and 1.8 million across a twelve-seat comparison, and
none of it is worth keeping — a user reads a distribution, a roster and a
handful of percentages. So the loop accumulates counts and sums, and the only
complete draft that survives is the one chosen for display.

How the displayed roster is chosen
----------------------------------
Not the best one. The best of ten thousand simulated drafts is the tail of a
distribution — it happened because the board fell kindly, and showing it as
"your roster" would promise an outcome the median seat will not get. The
displayed roster is the simulation whose roster value is **closest to the
median**, replayed once with its reasoning captured. Because every draft is
seeded from ``(seed, seat, index)``, replaying simulation *i* reproduces it
exactly, so the roster shown is genuinely one of the simulations summarised
beside it and not a fresh draft that happens to look similar.

The strategy findings are measured, not written
-----------------------------------------------
Every sentence in :class:`StrategyInsight` is produced from a number this module
computed — a share of simulations, a mean selection pick, a tier survival
probability. There is no template that fires on a hunch and no phrasing that
outruns its evidence: a finding that fails its threshold is simply not emitted.
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .engine import (
    AvailabilityModel,
    DraftContext,
    SimulatedDraft,
    simulate_draft,
    survival_table,
)
from .pool import DraftPlayer
from .valuation import Tier

#: A round-by-round positional lean is only reported when it holds in at least
#: this share of simulations. Below it the engine is genuinely undecided, and
#: saying "favours WR" about a 52/48 split would be inventing a strategy.
LEAN_THRESHOLD = 0.6

#: A position is described as deferrable only when its top surviving tier is
#: still there this often at the seat's next pick.
DEFER_THRESHOLD = 0.7

#: Players whose availability is reported back. The top of the board by season
#: value is where "can I wait?" is a real question; past it every answer is yes.
AVAILABILITY_REPORT_SIZE = 40


@dataclass(frozen=True)
class ValueDistribution:
    """Where a seat's roster value landed across the batch.

    Percentiles rather than a mean and a standard deviation, because the
    distribution is not symmetric — a seat can have a very good draft fall to it
    much more easily than a very bad one, since the strategy protects the
    downside and only luck supplies the upside.
    """

    mean: float
    median: float
    stdev: float
    p10: float
    p25: float
    p75: float
    p90: float
    minimum: float
    maximum: float

    #: Simulations behind these numbers. Carried on the distribution rather than
    #: alongside it, because it is what turns a standard deviation into a
    #: standard error and the two must never be separated.
    observations: int = 1

    @classmethod
    def of(cls, values: Sequence[float]) -> ValueDistribution:
        ordered = sorted(values)
        if not ordered:
            return cls(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0)
        return cls(
            mean=statistics.fmean(ordered),
            median=_percentile(ordered, 0.50),
            stdev=statistics.pstdev(ordered) if len(ordered) > 1 else 0.0,
            p10=_percentile(ordered, 0.10),
            p25=_percentile(ordered, 0.25),
            p75=_percentile(ordered, 0.75),
            p90=_percentile(ordered, 0.90),
            minimum=ordered[0],
            maximum=ordered[-1],
            observations=len(ordered),
        )

    @property
    def standard_error(self) -> float:
        """Monte Carlo error on the mean — the honest width of the headline.

        Reported so that a chart showing seat 4 at 867.4 and seat 5 at 864.1 can
        say whether that gap is a finding or a rounding of noise.
        """
        return self.stdev / math.sqrt(max(1, self.observations))


@dataclass(frozen=True)
class RoundPositionShare:
    """How often a seat spent a given round on a given position."""

    round_number: int
    position: str
    share: float


@dataclass(frozen=True)
class PositionStrength:
    """Mean starting value a seat assembled at one position."""

    position: str
    mean_starter_points: float
    mean_value_over_replacement: float
    mean_starters: float


@dataclass(frozen=True)
class PlayerAvailability:
    """What the calibration says about one player's chances of surviving.

    Attributes:
        first_pick_probability: Available when the seat first picks.
        next_pick_probability: Available at the seat's next pick after the one
            they are most often taken around.
        drafted_before_next_pick: The complement, stated explicitly because it
            is the number a user actually acts on.
        mean_selection_pick: Where the player typically goes, among the drafts
            in which they went at all.
        selected_rate: How often they were drafted at all.
    """

    player_id: str
    name: str
    position: str
    season_value: float
    first_pick_probability: float
    next_pick_probability: float
    drafted_before_next_pick: float
    mean_selection_pick: float | None
    selected_rate: float
    reference_pick: int
    next_reference_pick: int | None


@dataclass(frozen=True)
class StrategyInsight:
    """One measured finding about how this seat's drafts go.

    ``kind`` is a stable code a client can style or filter on; ``headline`` and
    ``detail`` are the prose, and both are assembled from ``evidence``, which
    carries the numbers so a UI can show them beside the sentence rather than
    asking the reader to trust it.
    """

    kind: str
    headline: str
    detail: str
    evidence: Mapping[str, float | int | str | None]


@dataclass(frozen=True)
class SeatAnalysis:
    """Everything the product says about one draft position."""

    draft_position: int
    simulations: int
    roster_value: ValueDistribution
    starter_points: ValueDistribution
    round_positions: tuple[RoundPositionShare, ...]
    position_strength: tuple[PositionStrength, ...]
    representative: SimulatedDraft
    representative_index: int
    insights: tuple[StrategyInsight, ...]
    availability: tuple[PlayerAvailability, ...]
    picks: tuple[int, ...]
    waits: tuple[int, ...]


def analyse_seat(
    context: DraftContext,
    *,
    draft_position: int,
    availability: AvailabilityModel,
    simulations: int,
    seed: int,
    with_insights: bool = True,
) -> SeatAnalysis:
    """Simulate a seat many times and summarise what it builds.

    Args:
        context: Shared draft context.
        draft_position: The seat, 1-based.
        availability: Survival curves from the calibration stage.
        simulations: Drafts to run.
        seed: Batch seed. Each draft's generator is derived from it together
            with the seat and the index, so seat 4's simulation 17 is the same
            draft in a single-seat analysis and in a full comparison.
        with_insights: Compute the strategy findings and the availability
            report. Off when a comparison only needs each seat's distribution,
            which is most of the work saved in a twelve-seat run.

    Returns:
        The seat's analysis, including one replayed draft with full reasoning.
    """
    roster_values: list[float] = []
    starter_points: list[float] = []
    round_counts: dict[tuple[int, str], int] = {}
    position_points: dict[str, float] = {}
    position_vor: dict[str, float] = {}
    position_starters: dict[str, int] = {}

    picks = context.order.picks_for(draft_position)
    survival = survival_table(context, availability, picks)

    for index in range(simulations):
        result = simulate_draft(
            context,
            draft_position=draft_position,
            availability=availability,
            rng=_generator(seed, draft_position, index),
            survival_by_pick=survival,
        )
        roster_values.append(result.roster_value)
        starter_points.append(result.starter_points)

        for pick in result.picks:
            key = (pick.round_number, pick.position)
            round_counts[key] = round_counts.get(key, 0) + 1

        starters = set(result.starters)
        for pick in result.picks:
            if pick.player_id in starters:
                position_points[pick.position] = (
                    position_points.get(pick.position, 0.0) + pick.season_value
                )
                position_vor[pick.position] = (
                    position_vor.get(pick.position, 0.0) + pick.value_over_replacement
                )
                position_starters[pick.position] = (
                    position_starters.get(pick.position, 0) + 1
                )

    # Replay the median simulation with its reasoning captured. Seeded per
    # index, so this is the same draft that produced the value being matched —
    # verified by a test that asserts the replay's roster value equals it.
    median_index = _index_of_median(roster_values)
    representative = simulate_draft(
        context,
        draft_position=draft_position,
        availability=availability,
        rng=_generator(seed, draft_position, median_index),
        capture_rationale=True,
        survival_by_pick=survival,
    )

    waits = context.order.wait_lengths(draft_position)

    return SeatAnalysis(
        draft_position=draft_position,
        simulations=simulations,
        roster_value=ValueDistribution.of(roster_values),
        starter_points=ValueDistribution.of(starter_points),
        round_positions=_round_shares(round_counts, simulations),
        position_strength=_position_strength(
            position_points, position_vor, position_starters, simulations
        ),
        representative=representative,
        representative_index=median_index,
        insights=(
            strategy_insights(
                context,
                availability=availability,
                round_counts=round_counts,
                simulations=simulations,
                picks=picks,
            )
            if with_insights
            else ()
        ),
        availability=(
            availability_report(context, availability, picks=picks)
            if with_insights
            else ()
        ),
        picks=picks,
        waits=waits,
    )


def _generator(seed: int, draft_position: int, index: int) -> random.Random:
    """A private generator for one simulated draft.

    Keyed on all three of seed, seat and index so that no two drafts in a
    comparison share a stream, and so that a seat's simulation *i* is the same
    draft however the request reached it. A string key rather than arithmetic on
    the three, because arithmetic on small integers collides — seat 2 index 100
    and seat 1 index 200 would be the same draft under ``seed + seat * index``.
    """
    return random.Random(f"draft:{seed}:{draft_position}:{index}")


def _index_of_median(values: Sequence[float]) -> int:
    """Index of the simulation nearest the median roster value."""
    median = _percentile(sorted(values), 0.50)
    best_index, best_gap = 0, math.inf
    for index, value in enumerate(values):
        gap = abs(value - median)
        if gap < best_gap:
            best_index, best_gap = index, gap
    return best_index


def _percentile(ordered: Sequence[float], probability: float) -> float:
    """Linear-interpolated percentile of an already-sorted sequence."""
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[int(position)]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _round_shares(
    counts: Mapping[tuple[int, str], int], simulations: int
) -> tuple[RoundPositionShare, ...]:
    shares = [
        RoundPositionShare(
            round_number=round_number, position=position, share=count / simulations
        )
        for (round_number, position), count in counts.items()
    ]
    shares.sort(key=lambda s: (s.round_number, -s.share, s.position))
    return tuple(shares)


def _position_strength(
    points: Mapping[str, float],
    vor: Mapping[str, float],
    starters: Mapping[str, int],
    simulations: int,
) -> tuple[PositionStrength, ...]:
    entries = [
        PositionStrength(
            position=position,
            mean_starter_points=total / simulations,
            mean_value_over_replacement=vor.get(position, 0.0) / simulations,
            mean_starters=starters.get(position, 0) / simulations,
        )
        for position, total in points.items()
    ]
    entries.sort(key=lambda e: -e.mean_starter_points)
    return tuple(entries)


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


def availability_report(
    context: DraftContext,
    availability: AvailabilityModel,
    *,
    picks: Sequence[int],
    size: int = AVAILABILITY_REPORT_SIZE,
) -> tuple[PlayerAvailability, ...]:
    """Per-player survival at this seat's own picks.

    Anchored on the seat's picks rather than on arbitrary pick numbers, because
    "72% available" is meaningless without saying *when*. Each player is
    reported against the seat's first pick and against the pick after the one
    they would most plausibly be considered at.
    """
    if not picks:
        return ()

    first = picks[0]
    ranked = sorted(context.players, key=lambda p: -p.season_value)[:size]

    report: list[PlayerAvailability] = []
    for player in ranked:
        # Anchor on the last seat pick that comes *before* the player typically
        # goes. That is the pick at which the user is genuinely deciding whether
        # to take them — after they have gone the question is moot — and the
        # following pick is the one the user would be waiting for. Anchoring on
        # the first pick after their mean instead reports every early-round
        # player as 0% available, which is true and useless.
        mean_pick = availability.mean_pick.get(player.player_id)
        anchor = first
        if mean_pick is not None:
            earlier = [pick for pick in picks if pick <= mean_pick]
            anchor = earlier[-1] if earlier else first
        following = next((pick for pick in picks if pick > anchor), None)

        at_next = availability.probability_available(player.player_id, following)
        report.append(
            PlayerAvailability(
                player_id=player.player_id,
                name=player.name,
                position=player.position,
                season_value=player.season_value,
                first_pick_probability=availability.probability_available(
                    player.player_id, first
                ),
                next_pick_probability=at_next,
                drafted_before_next_pick=1.0 - at_next if following else 1.0,
                mean_selection_pick=mean_pick,
                selected_rate=availability.selected_rate.get(player.player_id, 0.0),
                reference_pick=anchor,
                next_reference_pick=following,
            )
        )
    return tuple(report)


def tier_survival(
    availability: AvailabilityModel, tier: Tier, overall: int | None
) -> float:
    """Probability at least one member of a tier is still on the board.

    ``1 - prod(1 - p_i)``, which assumes the members survive independently. They
    do not — managers choosing between them are choosing from the same tier — so
    this reads slightly high. It is used only for the "you can wait" finding,
    where reading high is the direction that would produce a wrong
    recommendation, which is why the threshold on it is set well above a coin
    flip.
    """
    if overall is None:
        return 0.0
    gone = 1.0
    for player_id in tier.player_ids:
        gone *= 1.0 - availability.probability_available(player_id, overall)
    return 1.0 - gone


# ---------------------------------------------------------------------------
# Strategy findings
# ---------------------------------------------------------------------------


def strategy_insights(
    context: DraftContext,
    *,
    availability: AvailabilityModel,
    round_counts: Mapping[tuple[int, str], int],
    simulations: int,
    picks: Sequence[int],
) -> tuple[StrategyInsight, ...]:
    """Findings the simulations actually support, and nothing else."""
    insights: list[StrategyInsight] = []
    insights.extend(_early_lean(round_counts, simulations))
    insights.extend(_tier_cliffs(context, availability))
    insights.extend(_deferrable(context, availability, picks))
    insights.extend(_urgent(context, availability, picks))
    return tuple(insights)


def _early_lean(
    round_counts: Mapping[tuple[int, str], int], simulations: int
) -> list[StrategyInsight]:
    """Which position the seat's first two rounds usually go to."""
    early: dict[str, int] = {}
    for (round_number, position), count in round_counts.items():
        if round_number <= 2:
            early[position] = early.get(position, 0) + count
    if not early:
        return []

    total = sum(early.values())
    position, count = max(early.items(), key=lambda item: item[1])
    share = count / total
    if share < LEAN_THRESHOLD:
        ordered = sorted(early.items(), key=lambda item: -item[1])[:2]
        return [
            StrategyInsight(
                kind="early_balanced",
                headline="No single position dominates your first two rounds.",
                detail=(
                    f"Across {simulations:,} simulations the first two picks went "
                    f"{ordered[0][0]} {ordered[0][1] / total:.0%} of the time and "
                    f"{ordered[1][0]} {ordered[1][1] / total:.0%} — the board at "
                    "this seat decides it, not a standing preference."
                ),
                evidence={
                    "top_position": ordered[0][0],
                    "top_share": ordered[0][1] / total,
                    "second_position": ordered[1][0],
                    "second_share": ordered[1][1] / total,
                    "simulations": simulations,
                },
            )
        ]

    return [
        StrategyInsight(
            kind="early_lean",
            headline=f"Simulated drafts from this seat favour {position} in rounds 1-2.",
            detail=(
                f"{share:.0%} of the first two selections across {simulations:,} "
                f"simulations went to {position}. That is what the value-over-"
                "replacement calculation produced at this seat, not a rule the "
                "engine was given."
            ),
            evidence={"position": position, "share": share, "simulations": simulations},
        )
    ]


def _tier_cliffs(
    context: DraftContext, availability: AvailabilityModel
) -> list[StrategyInsight]:
    """Where a position's board falls away, in pick numbers.

    A cliff is reported for the largest value gap in each position's top tiers,
    located by the mean selection pick of the players either side of it. Both
    halves matter: a gap nobody reaches is not a cliff, and a gap that empties
    in round two is the most actionable thing on the screen.
    """
    insights: list[StrategyInsight] = []
    teams = context.settings.teams

    for position, tiers in context.tiers.items():
        if len(tiers) < 2:
            continue
        top, following = tiers[0], tiers[1]
        drop = top.bottom_value - following.top_value
        if drop <= 0:
            continue

        last_picks = [
            availability.mean_pick.get(player_id)
            for player_id in top.player_ids
        ]
        observed = [pick for pick in last_picks if pick is not None]
        if not observed:
            continue
        empties_at = max(observed)
        if empties_at > context.order.total_picks:
            continue

        insights.append(
            StrategyInsight(
                kind="tier_cliff",
                headline=(
                    f"{position} value falls {drop:.0f} points after the top "
                    f"{top.size}."
                ),
                detail=(
                    f"The top {position} tier holds {top.size} player(s) and is "
                    f"typically gone by pick {empties_at:.0f} (round "
                    f"{math.ceil(empties_at / teams)}). The next tier starts "
                    f"{drop:.0f} season points lower, so waiting past that pick "
                    f"costs roughly that much at {position}."
                ),
                evidence={
                    "position": position,
                    "drop": drop,
                    "tier_size": top.size,
                    "empties_at_pick": empties_at,
                    "empties_in_round": math.ceil(empties_at / teams),
                },
            )
        )

    insights.sort(key=lambda i: -float(i.evidence.get("drop") or 0))
    return insights[:3]


def _deferrable(
    context: DraftContext, availability: AvailabilityModel, picks: Sequence[int]
) -> list[StrategyInsight]:
    """Positions whose useful tier survives to a later pick often enough to wait."""
    if len(picks) < 2:
        return []

    insights: list[StrategyInsight] = []
    for position, tiers in context.tiers.items():
        if not tiers:
            continue
        for target in picks[1:4]:
            survival = tier_survival(availability, tiers[0], target)
            if survival >= DEFER_THRESHOLD:
                insights.append(
                    StrategyInsight(
                        kind="deferrable",
                        headline=f"{position} can usually be deferred.",
                        detail=(
                            f"At least one of the top {tiers[0].size} {position}"
                            f"(s) is still on the board at your pick {target} in "
                            f"{survival:.0%} of simulated drafts, so spending an "
                            "earlier pick there buys less than it appears to."
                        ),
                        evidence={
                            "position": position,
                            "pick": target,
                            "probability": survival,
                            "tier_size": tiers[0].size,
                        },
                    )
                )
                break
    return insights[:2]


def _urgent(
    context: DraftContext, availability: AvailabilityModel, picks: Sequence[int]
) -> list[StrategyInsight]:
    """Positions whose useful tier is usually gone before the seat picks again."""
    if len(picks) < 2:
        return []

    first, second = picks[0], picks[1]
    insights: list[StrategyInsight] = []
    for position, tiers in context.tiers.items():
        if not tiers:
            continue
        now = tier_survival(availability, tiers[0], first)
        later = tier_survival(availability, tiers[0], second)
        if now >= 0.5 and later <= 1 - DEFER_THRESHOLD:
            insights.append(
                StrategyInsight(
                    kind="urgent",
                    headline=f"The top {position} tier rarely survives your wait.",
                    detail=(
                        f"It is available at pick {first} in {now:.0%} of "
                        f"simulations and at pick {second} in only {later:.0%}. "
                        f"{second - first} picks elapse between them at this "
                        "seat, which is where the tier goes."
                    ),
                    evidence={
                        "position": position,
                        "first_pick": first,
                        "second_pick": second,
                        "probability_now": now,
                        "probability_later": later,
                    },
                )
            )
    insights.sort(key=lambda i: float(i.evidence.get("probability_now") or 0), reverse=True)
    return insights[:2]


# ---------------------------------------------------------------------------
# Comparing seats
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeatSummary:
    """One row of the draft-position comparison."""

    draft_position: int
    roster_value: ValueDistribution
    starter_points: ValueDistribution
    percentile: float
    is_best: bool


@dataclass(frozen=True)
class DraftComparison:
    """Every seat, ranked, with the caveat that decides how it should be read."""

    seats: tuple[SeatSummary, ...]
    best_position: int
    simulations: int
    #: Difference between the best and worst seat's mean roster value.
    spread: float
    #: Whether that spread exceeds the Monte Carlo error on the two means it is
    #: computed from. When it does not, the ranking is noise and the product
    #: says so instead of drawing an arrow at a winner.
    spread_is_resolvable: bool


def compare_seats(analyses: Sequence[SeatAnalysis]) -> DraftComparison:
    """Rank seats and state whether the ranking is separable from noise.

    The percentile is each seat's mean roster value ranked **among the seats**,
    not among rosters — twelve observations, so it is a ranking and is presented
    as one. A percentile against the pooled distribution of every simulated
    roster would be a larger, more impressive number describing something the
    user did not ask about.
    """
    ordered = sorted(analyses, key=lambda a: -a.roster_value.mean)
    best = ordered[0]
    worst = ordered[-1]
    spread = best.roster_value.mean - worst.roster_value.mean

    n = len(ordered)
    ranks = {a.draft_position: index for index, a in enumerate(ordered)}

    seats = tuple(
        SeatSummary(
            draft_position=analysis.draft_position,
            roster_value=analysis.roster_value,
            starter_points=analysis.starter_points,
            percentile=(
                1.0 if n == 1 else 1.0 - ranks[analysis.draft_position] / (n - 1)
            ),
            is_best=analysis.draft_position == best.draft_position,
        )
        for analysis in sorted(analyses, key=lambda a: a.draft_position)
    )

    combined_error = math.sqrt(
        best.roster_value.standard_error ** 2 + worst.roster_value.standard_error ** 2
    )
    return DraftComparison(
        seats=seats,
        best_position=best.draft_position,
        simulations=best.simulations,
        spread=spread,
        spread_is_resolvable=spread > 2 * combined_error,
    )


def explain_pick(pick_position: str, name: str, rationale: object) -> str:
    """Assemble the sentence a user reads from the numbers that produced the pick.

    Deliberately mechanical. Every clause is guarded on the value it describes,
    so a pick with no meaningful scarcity does not get a scarcity clause and a
    pick with no next selection does not get a waiting clause. The result reads
    a little plainly, which is the correct trade against a fluent sentence that
    is not derived from the calculation.
    """
    from .engine import PickRationale

    if not isinstance(rationale, PickRationale):
        return ""

    clauses: list[str] = []

    if rationale.slot == "starter":
        clauses.append(
            f"Fills a starting {pick_position} slot, worth "
            f"{rationale.marginal_value:.0f} points above a replacement-level "
            f"{pick_position}"
        )
    elif rationale.slot == "flex":
        clauses.append(
            f"Fills the flex, worth {rationale.marginal_value:.0f} points above "
            f"a replacement-level {pick_position}"
        )
    else:
        clauses.append(
            f"Adds {rationale.marginal_value:.0f} points of depth behind an "
            f"already-filled {pick_position}"
        )

    if rationale.next_pick_overall is not None:
        if rationale.survival_at_next_pick < 0.35:
            clauses.append(
                f"and survives to your next pick (#{rationale.next_pick_overall}) "
                f"in only {rationale.survival_at_next_pick:.0%} of simulations"
            )
        elif rationale.survival_at_next_pick > 0.65:
            clauses.append(
                f"and would still be there at #{rationale.next_pick_overall} in "
                f"{rationale.survival_at_next_pick:.0%} of simulations, so this "
                "is a value call rather than a scarcity one"
            )
        if rationale.next_best_player_name:
            clauses.append(
                f"waiting on {pick_position} would most likely leave "
                f"{rationale.next_best_player_name} at roughly "
                f"{rationale.expected_next_best_value:.0f} season points, a "
                f"{rationale.value_over_next_available:.0f}-point difference"
            )

    if rationale.tier_index is not None and rationale.tier_remaining is not None:
        clauses.append(
            f"tier {rationale.tier_index} at {pick_position} has "
            f"{rationale.tier_remaining} player(s) left"
        )

    if rationale.runner_up_name and rationale.runner_up_margin is not None:
        clauses.append(
            f"chosen over {rationale.runner_up_name} by "
            f"{rationale.runner_up_margin:.0f} points of draft value"
        )

    return f"{name}: " + "; ".join(clauses) + "."
