"""The matchup backtest: does correlation actually improve anything?

The question this module exists to answer is narrow and the answer is allowed to
be no. Phase 6B's brief is explicit that a correlated simulator must
*demonstrate* an improvement on held-out data, and that failing to is a result
to report rather than a problem to engineer around.

Constructing matchups that never happened
-----------------------------------------
There is no history of head-to-head fantasy matchups in this warehouse — no
rosters, no leagues, no users, and Phase 6A deliberately built the simulator
without them. So the matchups are **synthesised** from the panel: for each
evaluated week, players are drawn into ``standard_skill`` lineups and paired
against each other.

Three properties make that legitimate, and each is a deliberate choice rather
than a convenience:

**The draw uses no outcome information.** Lineups are assembled from projections
and eligibility only, by a generator seeded from ``(season, week, index)``. A
sampler that preferred, say, players who happened to score well would make both
arms look good and the comparison meaningless.

**The draw is realistic in the one dimension that matters here.** A fantasy
lineup is not a uniform sample of the player pool: managers start the players
they project highest, and — critically for this phase — some of them
deliberately stack a quarterback with his own receiver. A generator producing
only unrelated players would test the correlated model on precisely the case
where it makes no prediction. :data:`STACK_SHARE` of lineups are therefore built
around a QB and one of his own pass-catchers, which is the population where the
two models disagree most.

**Both arms see identical lineups and identical seeds.** The comparison is
paired at the matchup level, so a difference between the arms is the sampler and
nothing else. It also means the paired differences can be tested directly, which
:func:`Comparison.win_probability_delta` does.

What is scored
--------------
Two families, because they answer different questions.

*Did the win probability mean anything?* Brier score, log loss, ECE and
**maximum** calibration error over the realised winner. Maximum calibration
error is not optional here: independence is suspected of overconfidence, and ECE
is sample-weighted, so a model can be catastrophically wrong at 0.95 and score
well. Layer 3a already failed exactly that way — 94% stated, 17% delivered, ECE
0.006 — and :mod:`nflfp.predict.calibration` was written in response.

*Did the score distribution mean anything?* Interval coverage at 80% and 50%,
PIT calibration of the realised team total, and CRPS of the simulated total
against the realised one. Coverage is reported with mean interval width, because
coverage alone is gameable: a wide enough interval covers everything and says
nothing, and "correlation widens the intervals" is the outcome most likely to
look like an improvement while being one only if the width was earned.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from statistics import mean

from ..predict.calibration import (
    CalibrationBin,
    CoverageResult,
    calibration_report,
    expected_calibration_error,
    interval_coverage,
    max_calibration_error,
)
from ..predict.distribution import crps
from ..services.simulation import SCORING_PRECISION, SimulationInput, simulate
from .model import CorrelationMode, CorrelationModel
from .panel import Panel, PanelRow
from .sampler import RosterMember, build_sampler

logger = logging.getLogger(__name__)

#: Slots a synthesised lineup fills — ``standard_skill`` minus K and DST, which
#: is what the engine supports and therefore what can be evaluated.
LINEUP_SHAPE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("QB", ("QB",)),
    ("RB", ("RB",)),
    ("RB", ("RB",)),
    ("WR", ("WR",)),
    ("WR", ("WR",)),
    ("TE", ("TE",)),
    ("FLEX", ("RB", "WR", "TE")),
)

#: Projected points a player needs to be startable. Matches the estimation
#: floor, and for the same reason: this is the population a lineup draws from.
STARTABLE_FLOOR = 6.0

#: Share of synthesised lineups built around a QB and one of his own
#: pass-catchers. Not an estimate of how often real managers stack — nobody here
#: has that number — but a deliberate over-sampling of the case where the two
#: models make different predictions. Under-sampling it would test the candidate
#: mostly on lineups it says nothing about, and report "no difference" for the
#: wrong reason. The unstacked share is still the majority, so the headline
#: metrics remain dominated by ordinary lineups.
STACK_SHARE = 0.35

#: Share of synthesised lineups containing a player and an **opposing** player
#: from the same NFL game — a quarterback against a receiver, tight end or back
#: on the other sideline. Zero by default, which is what Phases 6B and 6C ran:
#: the parameter is short-circuited before it touches the generator's random
#: stream, so leaving it alone reproduces those reports draw for draw.
#:
#: Phase 6D raises it. The correlated structure gives an opposing pair the game
#: loading alone (``alpha_p·alpha_q``) against the same-team pair's
#: ``alpha_p·alpha_q + beta_p·beta_q``, so it is a genuinely different prediction
#: and deserves its own evaluated population rather than whatever share of it a
#: uniform draw happens to produce.
OPPONENT_SHARE = 0.0

#: Share of matchups where the two lineups' quarterbacks face each other. Also
#: zero by default and also short-circuited. This is the *cross-lineup*
#: dependence — it moves the score differential and the win probability while
#: leaving each side's own interval alone, which is the one effect a per-lineup
#: coverage number cannot see.
DUEL_SHARE = 0.0

#: Matchups synthesised per evaluated week.
MATCHUPS_PER_WEEK = 60

#: Iterations per simulated matchup. Below the product default because the
#: evaluation runs tens of thousands of matchups; the Monte Carlo error on a
#: single win probability is ~0.011 here, which averages out across matchups and
#: is far below the differences being looked for in aggregate.
EVALUATION_ITERATIONS = 2_000


@dataclass(frozen=True)
class MatchupOutcome:
    """One synthesised matchup, simulated one way, against what happened."""

    season: int
    week: int
    index: int
    arm: str
    #: Simulated probability that team A beat team B.
    win_probability: float
    #: Whether team A actually did. Ties are dropped before scoring.
    team_a_won: bool
    expected_a: float
    expected_b: float
    #: Sum of the stored calibrated means. The bias guard compares it against
    #: the simulated mean beside it: correlation may move the spread of a team
    #: total and must not move its centre.
    projection_sum_a: float
    projection_sum_b: float
    actual_a: float
    actual_b: float
    p10_a: float
    p25_a: float
    p75_a: float
    p90_a: float
    p10_b: float
    p25_b: float
    p75_b: float
    p90_b: float
    #: PIT of each realised team total within its own simulated distribution.
    pit_a: float
    pit_b: float
    crps_a: float
    crps_b: float
    #: Whether the two lineups shared any NFL game — where the arms differ most.
    shares_game: bool
    #: Whether either lineup contained a QB stacked with his own pass-catcher.
    stacked: bool


@dataclass
class ArmMetrics:
    """Everything one arm scored. Named for the report, not for a dashboard."""

    arm: str
    matchups: int = 0
    brier: float = 0.0
    log_loss: float = 0.0
    ece: float = 0.0
    max_calibration_error: float = 0.0
    calibration: list[CalibrationBin] = field(default_factory=list)
    coverage_80: CoverageResult | None = None
    coverage_50: CoverageResult | None = None
    mean_crps: float = 0.0
    #: Mean absolute gap between a team's simulated mean and the sum of its
    #: stored projections. The bias guard: a correlation model must not move a
    #: team total, only its spread.
    total_drift: float = 0.0
    mean_p10_p90_width: float = 0.0
    #: Share of win probabilities outside [0.05, 0.95] — the overconfidence
    #: counter, reported because that is the specific failure independence is
    #: accused of and the specific failure a bad correlation model would create.
    extreme_share: float = 0.0
    pit_bins: list[tuple[float, int, float]] = field(default_factory=list)

    def __str__(self) -> str:
        coverage_80 = self.coverage_80.observed if self.coverage_80 else float("nan")
        coverage_50 = self.coverage_50.observed if self.coverage_50 else float("nan")
        return (
            f"{self.arm:<14} n={self.matchups:>6,}  Brier={self.brier:.5f}  "
            f"logloss={self.log_loss:.5f}  ECE={self.ece:.4f}  "
            f"maxCE={self.max_calibration_error:.4f}  cov80={coverage_80:.4f}  "
            f"cov50={coverage_50:.4f}  width={self.mean_p10_p90_width:5.1f}  "
            f"CRPS={self.mean_crps:.4f}  drift={self.total_drift:.4f}  "
            f"extreme={self.extreme_share:.4f}"
        )


def score_arm(arm: str, outcomes: Sequence[MatchupOutcome]) -> ArmMetrics:
    """Reduce one arm's matchups to the decision metrics."""
    if not outcomes:
        return ArmMetrics(arm=arm)

    probabilities = [o.win_probability for o in outcomes]
    won = [o.team_a_won for o in outcomes]

    # Clamped only inside the logarithm. A simulation legitimately returns 0.000
    # when no iteration produced a win, and log(0) would make the metric
    # infinite for one matchup and hide every other difference. The clamp is one
    # over the iteration count, which is the smallest probability the sampler
    # can actually distinguish from zero.
    floor = 1.0 / EVALUATION_ITERATIONS
    log_loss = -mean(
        _log(max(floor, min(1.0 - floor, p))) if outcome
        else _log(max(floor, min(1.0 - floor, 1.0 - p)))
        for p, outcome in zip(probabilities, won)
    )

    report = calibration_report(probabilities, won)
    bounds_80 = [(o.p10_a, o.p90_a) for o in outcomes] + [
        (o.p10_b, o.p90_b) for o in outcomes
    ]
    bounds_50 = [(o.p25_a, o.p75_a) for o in outcomes] + [
        (o.p25_b, o.p75_b) for o in outcomes
    ]
    actuals = [o.actual_a for o in outcomes] + [o.actual_b for o in outcomes]

    pits = [o.pit_a for o in outcomes] + [o.pit_b for o in outcomes]
    counts = [0] * 10
    for value in pits:
        counts[min(int(value * 10), 9)] += 1

    return ArmMetrics(
        arm=arm,
        matchups=len(outcomes),
        brier=mean((p - float(o)) ** 2 for p, o in zip(probabilities, won)),
        log_loss=log_loss,
        ece=expected_calibration_error(report),
        max_calibration_error=max_calibration_error(report),
        calibration=report,
        coverage_80=interval_coverage(bounds_80, actuals, 0.80, "P10-P90"),
        coverage_50=interval_coverage(bounds_50, actuals, 0.50, "P25-P75"),
        mean_crps=mean([o.crps_a for o in outcomes] + [o.crps_b for o in outcomes]),
        total_drift=mean(
            [abs(o.expected_a - o.projection_sum_a) for o in outcomes]
            + [abs(o.expected_b - o.projection_sum_b) for o in outcomes]
        ),
        mean_p10_p90_width=mean(
            [o.p90_a - o.p10_a for o in outcomes] + [o.p90_b - o.p10_b for o in outcomes]
        ),
        extreme_share=sum(1 for p in probabilities if p < 0.05 or p > 0.95)
        / len(probabilities),
        pit_bins=[(i / 10, c, c / len(pits)) for i, c in enumerate(counts)],
    )


def _log(value: float) -> float:
    from math import log

    return log(value)


# ---------------------------------------------------------------------------
# Synthesising lineups
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SyntheticMatchup:
    """Two lineups for one week, drawn without reference to any outcome."""

    season: int
    week: int
    index: int
    team_a: tuple[PanelRow, ...]
    team_b: tuple[PanelRow, ...]
    stacked: bool

    @property
    def shares_game(self) -> bool:
        games_a = {row.game_id for row in self.team_a if row.game_id}
        games_b = {row.game_id for row in self.team_b if row.game_id}
        return bool(games_a & games_b)

    @property
    def quarterbacks_duel(self) -> bool:
        """The two lineups' quarterbacks are on opposite sidelines of one game.

        Measured from the drawn rows rather than carried as a flag, so it is true
        of a matchup that came out this way by chance and not only of one
        :data:`DUEL_SHARE` asked for. The distinction matters: the population
        being reported on is the one that exists, not the one that was requested.
        """
        for a in self.team_a:
            if a.position != "QB" or not a.game_id:
                continue
            for b in self.team_b:
                if (
                    b.position == "QB"
                    and b.game_id == a.game_id
                    and b.team != a.team
                ):
                    return True
        return False


def synthesise_matchups(
    rows: Sequence[PanelRow],
    *,
    season: int,
    week: int,
    count: int = MATCHUPS_PER_WEEK,
    stack_share: float = STACK_SHARE,
    opponent_share: float = OPPONENT_SHARE,
    duel_share: float = DUEL_SHARE,
    shape: Sequence[tuple[str, tuple[str, ...]]] = LINEUP_SHAPE,
    seed: int,
) -> Iterator[SyntheticMatchup]:
    """Draw ``count`` matchups from one week's startable players.

    Sampling is **without replacement within a matchup** — one player cannot
    start for both managers in the same week, and letting them would cancel
    exactly the cross-lineup dependence this phase is trying to measure — and
    with replacement across matchups, since the weeks are small and drawing
    sixty disjoint fourteen-player lineups from one slate is not possible.

    ``shape`` is the slot list to fill and defaults to :data:`LINEUP_SHAPE`,
    which is what Phase 6B measured. Phase 6C varies it to ask whether the tail
    error grows with the number of curves being summed — a question that cannot
    be asked at all if the shape is a constant.

    ``opponent_share`` and ``duel_share`` are Phase 6D's, and both default to
    zero. Each is **short-circuited before it reaches the random stream**, so a
    caller leaving them alone gets the exact sequence of lineups Phases 6B and 6C
    drew — which is what keeps those two reports reproducible after this
    generator grew a third and fourth knob.
    """
    pool: dict[str, list[PanelRow]] = {}
    for row in rows:
        if row.expected >= STARTABLE_FLOOR:
            pool.setdefault(row.position, []).append(row)
    for position in pool:
        pool[position].sort(key=lambda r: r.player_id)

    if not all(pool.get(position) for position in ("QB", "RB", "WR", "TE")):
        return
    if len(pool["QB"]) < 2 or len(pool["RB"]) < 6 or len(pool["WR"]) < 6:
        return

    rng = random.Random(seed)
    for index in range(count):
        stacked = rng.random() < stack_share
        # `share > 0.0` first, so a zero share never advances the generator.
        opposing = opponent_share > 0.0 and rng.random() < opponent_share
        duelling = duel_share > 0.0 and rng.random() < duel_share
        taken: set[str] = set()
        lineup_a = _draw_lineup(
            pool, taken, rng, stack=stacked, oppose=opposing, shape=shape
        )
        anchor = (
            next((row for row in lineup_a if row.position == "QB"), None)
            if duelling and lineup_a is not None
            else None
        )
        lineup_b = _draw_lineup(
            pool, taken, rng, stack=stacked, oppose=opposing, shape=shape,
            duel_against=anchor,
        )
        # Both draws happen before either is checked: bailing out after the
        # first would leave the generator one call short and desynchronise every
        # later matchup from the sequence Phases 6B and 6C measured.
        if lineup_a is None or lineup_b is None:
            continue
        yield SyntheticMatchup(
            season=season, week=week, index=index,
            team_a=tuple(lineup_a), team_b=tuple(lineup_b), stacked=stacked,
        )


def _slot_for(position: str) -> tuple[str, tuple[str, ...]]:
    """The dedicated slot a position fills. FLEX is deliberately not returned.

    An anchored pair has to land in a slot that exists whatever else the lineup
    does; taking a FLEX for it would make the rest of the draw depend on which
    anchor was picked, and the anchored and unanchored populations would then
    differ by more than the anchor.
    """
    return (position, (position,))


def _draw_lineup(
    pool: dict[str, list[PanelRow]],
    taken: set[str],
    rng: random.Random,
    *,
    stack: bool,
    oppose: bool = False,
    duel_against: PanelRow | None = None,
    shape: Sequence[tuple[str, tuple[str, ...]]] = LINEUP_SHAPE,
) -> list[PanelRow] | None:
    """Fill the slots, optionally around one or more anchored pairs.

    Three anchors, applied in this order and each one optional:

    ``stack``
        A quarterback and one of his **own** pass-catchers. Phase 6B's, and the
        pair the correlated structure predicts most strongly (+0.24).
    ``duel_against``
        The quarterback facing a given player — the *cross-lineup* anchor, drawn
        into team B so the two managers' totals depend on one afternoon.
    ``oppose``
        A quarterback and a skill player on the **other** sideline of his game.
        Under the fitted structure this pair shares the game factor and not the
        team factor, so it is a strictly weaker prediction than ``stack`` and a
        separate one.

    Each anchor consumes the generator only when it is asked for and only when a
    qualifying pair exists, and each falls through to the ordinary draw when it
    cannot be satisfied — a week whose slate has no eligible pair yields an
    ordinary lineup rather than no lineup at all.
    """
    chosen: list[PanelRow] = []
    slots = list(shape)

    if duel_against is not None and duel_against.game_id and ("QB", ("QB",)) in slots:
        rivals = [
            row
            for row in pool.get("QB", ())
            if row.player_id not in taken
            and row.game_id == duel_against.game_id
            and row.team != duel_against.team
        ]
        if rivals:
            rival = rivals[rng.randrange(len(rivals))]
            chosen.append(rival)
            taken.add(rival.player_id)
            slots.remove(("QB", ("QB",)))

    # A shape with no dedicated QB or receiver slot cannot hold a stack. Checked
    # rather than assumed, because the slot list is a parameter now.
    if stack and ("QB", ("QB",)) in slots:
        partners: list[tuple[PanelRow, PanelRow]] = []
        for quarterback in pool.get("QB", ()):
            if quarterback.player_id in taken:
                continue
            for position in ("WR", "TE"):
                for catcher in pool.get(position, ()):
                    if (
                        catcher.player_id not in taken
                        and catcher.team == quarterback.team
                        and catcher.game_id == quarterback.game_id
                    ):
                        partners.append((quarterback, catcher))
        partners = [
            pair for pair in partners
            if (
                ("WR", ("WR",)) if pair[1].position == "WR" else ("TE", ("TE",))
            ) in slots
        ]
        if partners:
            quarterback, catcher = partners[rng.randrange(len(partners))]
            catcher_slot = (
                ("WR", ("WR",)) if catcher.position == "WR" else ("TE", ("TE",))
            )
            chosen.extend((quarterback, catcher))
            taken.update({quarterback.player_id, catcher.player_id})
            slots.remove(("QB", ("QB",)))
            slots.remove(catcher_slot)

    if oppose:
        # The quarterback may already be on the roster from the stack or the
        # duel; if so the opposing player is drawn against *that* one, so a
        # lineup can legitimately carry a stack and an opposing pair at once.
        placed = next((row for row in chosen if row.position == "QB"), None)
        quarterbacks = (
            [placed]
            if placed is not None
            else [
                row for row in pool.get("QB", ())
                if row.player_id not in taken
            ]
            if ("QB", ("QB",)) in slots
            else []
        )
        rivals: list[tuple[PanelRow, PanelRow, tuple[str, tuple[str, ...]]]] = []
        for quarterback in quarterbacks:
            if not quarterback.game_id:
                continue
            for position in ("WR", "TE", "RB"):
                slot = _slot_for(position)
                if slot not in slots:
                    continue
                for foe in pool.get(position, ()):
                    if (
                        foe.player_id not in taken
                        and foe.game_id == quarterback.game_id
                        and foe.team != quarterback.team
                    ):
                        rivals.append((quarterback, foe, slot))
        if rivals:
            quarterback, foe, slot = rivals[rng.randrange(len(rivals))]
            if placed is None:
                chosen.append(quarterback)
                taken.add(quarterback.player_id)
                slots.remove(("QB", ("QB",)))
            chosen.append(foe)
            taken.add(foe.player_id)
            slots.remove(slot)

    for _, eligible in slots:
        candidates = [
            row
            for position in eligible
            for row in pool.get(position, ())
            if row.player_id not in taken
        ]
        if not candidates:
            return None
        pick = candidates[rng.randrange(len(candidates))]
        taken.add(pick.player_id)
        chosen.append(pick)
    return chosen


def _to_inputs(rows: Sequence[PanelRow]) -> list[SimulationInput]:
    """Panel rows as the simulation engine's inputs. No new numbers."""
    prepared = []
    for row in rows:
        curve = row.curve()
        prepared.append(
            SimulationInput(
                player_id=row.player_id, name=row.player_id, slot=row.position,
                position=row.position, team=row.team, game_id=row.game_id,
                curve=curve, expected_points=row.expected,
                floor=row.p10, ceiling=row.p90,
            )
        )
    return prepared


# ---------------------------------------------------------------------------
# The backtest
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PairedTest:
    """A paired comparison of the two arms on one metric.

    The arms see identical lineups, identical realised outcomes and identical
    seeds, so the per-matchup difference is the sampler and nothing else. That
    pairing removes the variance from "some matchups are harder to call than
    others", which dominates the metric's level and would otherwise swamp a
    difference this small.

    Unpaired, the standard error on a Brier score across 4,320 matchups is about
    0.004 — eight times the difference being looked for, which would make the
    comparison unable to distinguish a real improvement from noise in either
    direction.
    """

    metric: str
    n: int
    #: Mean of ``correlated - independent``. Negative favours the candidate.
    delta: float
    standard_error: float

    @property
    def t_statistic(self) -> float:
        return self.delta / self.standard_error if self.standard_error else 0.0

    @property
    def significant(self) -> bool:
        """Two standard errors from zero. Not a hypothesis test, a sanity gate."""
        return abs(self.t_statistic) >= 2.0

    def __str__(self) -> str:
        verdict = "significant" if self.significant else "indistinguishable from zero"
        return (
            f"{self.metric:<12} delta={self.delta:+.6f}  se={self.standard_error:.6f}  "
            f"t={self.t_statistic:+.2f}  n={self.n:,}  ({verdict})"
        )


def paired_test(
    metric: str,
    independent: Sequence[MatchupOutcome],
    correlated: Sequence[MatchupOutcome],
    score,
) -> PairedTest:
    """Paired mean difference and its standard error for one per-matchup score."""
    by_key = {(o.season, o.week, o.index): o for o in correlated}
    differences = [
        score(by_key[key]) - score(base)
        for base in independent
        if (key := (base.season, base.week, base.index)) in by_key
    ]
    n = len(differences)
    if n < 2:
        return PairedTest(metric=metric, n=n, delta=0.0, standard_error=0.0)
    average = mean(differences)
    variance = sum((d - average) ** 2 for d in differences) / (n - 1)
    return PairedTest(
        metric=metric, n=n, delta=average,
        standard_error=(variance / n) ** 0.5,
    )


@dataclass
class Comparison:
    """Both arms, scored on identical matchups."""

    independent: ArmMetrics
    correlated: ArmMetrics
    weeks: int
    duration_seconds: float
    #: Paired per-matchup differences, with standard errors. The numbers the
    #: accept/reject decision is actually made on.
    paired: tuple[PairedTest, ...] = ()
    #: Metrics restricted to matchups where the two lineups shared an NFL game.
    independent_shared: ArmMetrics | None = None
    correlated_shared: ArmMetrics | None = None
    #: Metrics restricted to matchups containing a QB stack.
    independent_stacked: ArmMetrics | None = None
    correlated_stacked: ArmMetrics | None = None

    @property
    def brier_delta(self) -> float:
        """Correlated minus independent. **Negative is an improvement.**"""
        return self.correlated.brier - self.independent.brier

    @property
    def log_loss_delta(self) -> float:
        return self.correlated.log_loss - self.independent.log_loss

    def report(self) -> str:
        lines = [
            f"matchup backtest — {self.weeks} week(s), "
            f"{self.independent.matchups:,} matchup(s) per arm, "
            f"{self.duration_seconds:.1f}s",
            "=" * 118,
            "ALL MATCHUPS",
            "  " + str(self.independent),
            "  " + str(self.correlated),
            f"  Brier delta {self.brier_delta:+.6f}   "
            f"log loss delta {self.log_loss_delta:+.6f}   "
            "(negative favours the correlated candidate)",
        ]
        if self.paired:
            lines += [
                "",
                "PAIRED DIFFERENCES — correlated minus independent, same lineups "
                "and seeds",
            ]
            lines.extend("  " + str(test) for test in self.paired)
        for label, pair in (
            ("SHARED-GAME MATCHUPS", (self.independent_shared, self.correlated_shared)),
            ("STACKED LINEUPS", (self.independent_stacked, self.correlated_stacked)),
        ):
            first, second = pair
            if first is None or second is None:
                continue
            lines += ["", label, "  " + str(first), "  " + str(second)]

        lines += ["", "WIN PROBABILITY CALIBRATION (independent | correlated)"]
        lines.append(
            f"  {'bin':<12}{'n':>8}{'stated':>9}{'actual':>9}"
            f"{'n':>10}{'stated':>9}{'actual':>9}"
        )
        by_bin = {b.lower: b for b in self.correlated.calibration}
        for first in self.independent.calibration:
            second = by_bin.get(first.lower)
            cells = (
                f"{second.count:>10,}{second.mean_predicted:>9.3f}"
                f"{second.observed_rate:>9.3f}"
                if second else " " * 28
            )
            lines.append(
                f"  {first.lower:.1f}-{first.upper:.1f}   {first.count:>8,}"
                f"{first.mean_predicted:>9.3f}{first.observed_rate:>9.3f}{cells}"
            )
        lines.append(
            "  (max calibration error ignores bins under 30; read it, not ECE alone)"
        )

        lines += ["", "TEAM TOTAL PIT (10 bins, 0.100 is calibrated)"]
        for (lower, _, first), (_, _, second) in zip(
            self.independent.pit_bins, self.correlated.pit_bins
        ):
            lines.append(
                f"  [{lower:.1f},{lower + 0.1:.1f})   independent {first:.4f}   "
                f"correlated {second:.4f}"
            )
        return "\n".join(lines)


def run_comparison(
    panel: Panel,
    *,
    models: dict[tuple[int, int], CorrelationModel | None],
    seasons: Sequence[int],
    matchups_per_week: int = MATCHUPS_PER_WEEK,
    iterations: int = EVALUATION_ITERATIONS,
    seed: int = 20260601,
) -> Comparison:
    """Simulate every synthesised matchup both ways and score both arms.

    Args:
        panel: The historical panel.
        models: ``(season, week) -> model`` from
            :func:`~nflfp.correlation.estimate.walk_forward_models`. A week whose
            model is ``None`` is skipped entirely rather than falling back to a
            later fit — the whole point of the mapping is that each week's
            structure was fitted before that week.
        seasons: Seasons to evaluate.
        matchups_per_week: Synthesised matchups per week.
        iterations: Monte Carlo iterations per matchup per arm.
        seed: Base seed. Both arms use the *same* per-matchup seed, so the two
            arms differ only by their sampler.
    """
    started = time.monotonic()
    independent: list[MatchupOutcome] = []
    correlated: list[MatchupOutcome] = []
    weeks = 0

    for season, week in panel.weeks(seasons):
        model = models.get((season, week))
        if model is None:
            logger.debug("%dw%02d: no fitted structure yet, skipped", season, week)
            continue
        rows = panel.week(season, week)
        matchups = list(
            synthesise_matchups(
                rows, season=season, week=week,
                count=matchups_per_week, seed=seed + season * 100 + week,
            )
        )
        if not matchups:
            continue
        weeks += 1

        for matchup in matchups:
            matchup_seed = seed + hash((season, week, matchup.index)) % 1_000_003
            for arm, mode in (
                ("independent", CorrelationMode.INDEPENDENT),
                ("correlated", CorrelationMode.GAME_ENVIRONMENT),
            ):
                outcome = _simulate_one(
                    matchup, arm=arm, mode=mode, model=model,
                    iterations=iterations, seed=matchup_seed,
                )
                if outcome is not None:
                    (independent if arm == "independent" else correlated).append(outcome)

        if weeks % 10 == 0:
            logger.info("evaluated %d week(s), %d matchup(s)", weeks, len(independent))

    comparison = Comparison(
        independent=score_arm("independent", independent),
        correlated=score_arm("correlated", correlated),
        weeks=weeks,
        duration_seconds=time.monotonic() - started,
    )
    comparison.independent_shared = score_arm(
        "independent/shared", [o for o in independent if o.shares_game]
    )
    comparison.correlated_shared = score_arm(
        "correlated/shared", [o for o in correlated if o.shares_game]
    )
    comparison.independent_stacked = score_arm(
        "independent/stack", [o for o in independent if o.stacked]
    )
    comparison.correlated_stacked = score_arm(
        "correlated/stack", [o for o in correlated if o.stacked]
    )
    comparison.paired = tuple(
        paired_test(metric, independent, correlated, score)
        for metric, score in (
            ("brier", lambda o: (o.win_probability - float(o.team_a_won)) ** 2),
            ("crps", lambda o: (o.crps_a + o.crps_b) / 2.0),
            (
                "cov80_gap",
                # +1 when the realised total sits inside the stated 80% band.
                # Its paired mean is the coverage difference, and its standard
                # error says whether that difference means anything.
                lambda o: (
                    (o.p10_a <= o.actual_a <= o.p90_a)
                    + (o.p10_b <= o.actual_b <= o.p90_b)
                ) / 2.0,
            ),
            ("width", lambda o: ((o.p90_a - o.p10_a) + (o.p90_b - o.p10_b)) / 2.0),
        )
    )
    return comparison


def _simulate_one(
    matchup: SyntheticMatchup,
    *,
    arm: str,
    mode: CorrelationMode,
    model: CorrelationModel,
    iterations: int,
    seed: int,
) -> MatchupOutcome | None:
    """Run one matchup one way and score it against the realised totals."""
    inputs_a = _to_inputs(matchup.team_a)
    inputs_b = _to_inputs(matchup.team_b)
    members = [
        RosterMember(position=row.position, team=row.team, game_id=row.game_id)
        for row in (*matchup.team_a, *matchup.team_b)
    ]
    sampler = build_sampler(
        members, mode=mode, model=(None if mode is CorrelationMode.INDEPENDENT else model)
    )
    result_a, result_b, _, _ = simulate(
        inputs_a, inputs_b, iterations=iterations, seed=seed, sampler=sampler
    )

    actual_a = sum(row.actual for row in matchup.team_a)
    actual_b = sum(row.actual for row in matchup.team_b)
    if round(actual_a, SCORING_PRECISION) == round(actual_b, SCORING_PRECISION):
        # A realised tie has no winner to score a win probability against.
        return None

    totals_a, totals_b = _resample_totals(
        inputs_a, inputs_b, sampler=sampler, iterations=iterations, seed=seed
    )
    return MatchupOutcome(
        season=matchup.season, week=matchup.week, index=matchup.index, arm=arm,
        win_probability=result_a.win_probability,
        team_a_won=actual_a > actual_b,
        expected_a=result_a.expected_score, expected_b=result_b.expected_score,
        actual_a=actual_a, actual_b=actual_b,
        p10_a=result_a.p10, p25_a=result_a.p25,
        p75_a=result_a.p75, p90_a=result_a.p90,
        p10_b=result_b.p10, p25_b=result_b.p25,
        p75_b=result_b.p75, p90_b=result_b.p90,
        pit_a=_pit_of_total(totals_a, actual_a),
        pit_b=_pit_of_total(totals_b, actual_b),
        crps_a=crps(totals_a, actual_a), crps_b=crps(totals_b, actual_b),
        shares_game=matchup.shares_game, stacked=matchup.stacked,
        projection_sum_a=sum(row.expected for row in matchup.team_a),
        projection_sum_b=sum(row.expected for row in matchup.team_b),
    )


def _resample_totals(
    team_a: Sequence[SimulationInput],
    team_b: Sequence[SimulationInput],
    *,
    sampler,
    iterations: int,
    seed: int,
) -> tuple[list[float], list[float]]:
    """The sorted team totals, which :func:`simulate` summarises and discards.

    CRPS and the PIT of a realised total both need the whole sample, not five
    percentiles. Re-running the draws with the same seed reproduces exactly the
    sample :func:`simulate` used, which is cheaper than changing that function's
    return type to carry 20,000 floats out of every production request for the
    benefit of a backtest.
    """
    rng = random.Random(seed)
    draw = sampler.draw
    quantiles_a = [player.curve.quantile for player in team_a]
    quantiles_b = [player.curve.quantile for player in team_b]
    split = len(team_a)
    totals_a, totals_b = [], []
    for _ in range(iterations):
        uniforms = draw(rng)
        totals_a.append(sum(q(uniforms[i]) for i, q in enumerate(quantiles_a)))
        totals_b.append(sum(q(uniforms[split + i]) for i, q in enumerate(quantiles_b)))
    totals_a.sort()
    totals_b.sort()
    return totals_a, totals_b


def _pit_of_total(sorted_totals: Sequence[float], actual: float) -> float:
    """Where a realised team total fell within its simulated distribution.

    Under a well-calibrated simulator this is uniform across matchups, which is
    the single most direct test of whether a *team-level* distribution is right —
    coverage only checks two thresholds, this checks the whole shape.
    """
    low, high = 0, len(sorted_totals)
    while low < high:
        middle = (low + high) // 2
        if sorted_totals[middle] < actual:
            low = middle + 1
        else:
            high = middle
    return min(0.9999, max(0.0001, low / len(sorted_totals)))
