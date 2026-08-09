"""Phase 6D: should the correlated sampler become the production default?

The question, and why it is being asked again
---------------------------------------------
Phase 6B fitted a correlation structure, scored it against independence on
held-out matchups, and rejected it. Phase 6C then found that the rejection was
entangled with a second error: the outcome curve's tail factors over-dispersed a
seven-player sum, so the independent simulator's team-total interval was already
*too wide*, and correlation — which under this structure only ever adds variance
— was being scored for pushing a too-wide interval wider. Under the recalibrated
factors approved in Phase 6D the same comparison points the other way on stacked
lineups: 80% coverage moves from 0.783 onto 0.802 rather than from 0.822 up to
0.837.

That is a reason to re-open the question, not an answer to it. Phase 6C measured
correlation as a side-experiment on a grid it had already spent its statistical
power on. This module measures it as the primary question, on the marginals that
now ship, with the populations where the structure makes a *different*
prediction separated out rather than averaged into a headline.

What this module adds over Phase 6C's harness
---------------------------------------------
:mod:`nflfp.evaluation.tails` already scores a configuration against realised
outcomes, and Phase 6D reuses it whole — same panel, same leakage boundary, same
synthesised matchups, same metrics. Three things were missing.

**Lineups are classified by what they are, not by what was requested.**
:func:`classify` reads the drawn rows. A lineup asked for as a stack that the
week's slate could not supply is not counted as one, and a lineup that came out
stacked by chance is. The flag the generator carries answers "what did we ask
for"; a promotion decision needs "what did we measure".

**The populations are separated the way the structure predicts.** The fitted
model gives a same-team pair ``alpha_p*alpha_q + beta_p*beta_q`` and an opposing
pair ``alpha_p*alpha_q`` alone — a weaker and genuinely different claim — and
players in different games exactly zero. Averaging those three into one number
dilutes a real effect on a third of the sample with a guaranteed null on the
rest, which is how Phase 6B came to report "no difference" for a population that
was mostly not being asked about.

**Marginal preservation is measured against a Monte Carlo control.**
:func:`marginal_comparison` compares each player's simulated percentiles under
the two samplers — and also under the *same* sampler at a different seed. The
second number is the yardstick: a correlated-versus-independent difference only
means something if it is larger than the difference two identical samplers
produce from sampling noise alone, and without the control there is no way to
say whether 0.3 points is a violation or a rounding error.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import mean

from ..correlation.evaluate import SyntheticMatchup
from ..correlation.model import CorrelationMode, CorrelationModel
from ..correlation.panel import PanelRow
from ..correlation.sampler import RosterMember, build_sampler
from .tails import PROJECTION_BANDS, LineupDraws, TailFactors, build_curve, percentile

#: Positions that catch passes from their own quarterback. The same-team stack
#: is defined against these and not against running backs: the measured QB-RB
#: same-team correlation is +0.062 against +0.218 to +0.236 for QB-WR and QB-TE,
#: so pooling them would put the population's defining effect in the noise.
RECEIVING_POSITIONS: tuple[str, ...] = ("WR", "TE")


@dataclass(frozen=True)
class LineupComposition:
    """What one drawn lineup actually contains, in the terms the model predicts.

    Read off the rows rather than off the generator's flags, so a lineup counts
    as stacked when it holds a stack and not when one was requested.
    """

    #: ``(QB position, teammate position)`` pairs sharing a team — the pairs the
    #: team factor acts on.
    same_team_pairs: tuple[tuple[str, str], ...]
    #: ``(position, position)`` pairs in one game on opposite sidelines — the
    #: pairs only the game factor acts on.
    opposing_pairs: tuple[tuple[str, str], ...]
    #: The stack's shape, as a manager would name it: ``QB+WR``, ``QB+WR+TE``.
    #: Empty when the lineup holds no quarterback-to-own-receiver pair.
    stack_shape: str

    @property
    def has_same_team_stack(self) -> bool:
        return bool(self.stack_shape)

    @property
    def has_opposing_pair(self) -> bool:
        return bool(self.opposing_pairs)

    @property
    def is_unrelated(self) -> bool:
        """No two players share a game at all.

        The population the correlated sampler makes **no** prediction about:
        under this structure two players in different games have correlation
        exactly zero, so the two arms should agree to Monte Carlo noise. It is
        reported for exactly that reason — it is the control that says whether a
        difference seen elsewhere is the model or the harness.
        """
        return not self.same_team_pairs and not self.opposing_pairs


def classify(rows: Sequence[PanelRow]) -> LineupComposition:
    """Describe a lineup by the dependencies the fitted structure gives it."""
    same_team: list[tuple[str, str]] = []
    opposing: list[tuple[str, str]] = []
    for index, first in enumerate(rows):
        for second in rows[index + 1:]:
            if not first.game_id or first.game_id != second.game_id:
                continue
            pair = (first.position, second.position)
            if first.team == second.team:
                same_team.append(pair)
            else:
                opposing.append(pair)

    quarterbacks = [row for row in rows if row.position == "QB"]
    catchers = sorted(
        row.position
        for quarterback in quarterbacks
        for row in rows
        if row.position in RECEIVING_POSITIONS
        and row.team == quarterback.team
        and row.game_id == quarterback.game_id
    )
    return LineupComposition(
        same_team_pairs=tuple(same_team),
        opposing_pairs=tuple(opposing),
        stack_shape="+".join(("QB", *catchers)) if catchers else "",
    )


def composition_keys(
    draws: LineupDraws, matchup: SyntheticMatchup
) -> tuple[str, ...]:
    """Which reported populations one lineup belongs to.

    A ``strata_keys`` for :func:`nflfp.evaluation.tails.run_sweep`. The buckets
    **overlap on purpose** — a lineup can hold both a stack and an opposing pair,
    and forcing it into one would report a mixed population under whichever label
    won the tie. Every lineup lands in exactly one projection band and in as many
    composition buckets as describe it.
    """
    composition = classify(draws.rows)
    band = next(
        f"projection {low:.0f}-{high:.0f}"
        for low, high in PROJECTION_BANDS
        if low <= draws.projection_sum < high
    )
    keys = [band]

    if composition.is_unrelated:
        keys.append("unstacked (no shared game)")
    if composition.has_same_team_stack:
        keys.append("same-team stack")
        keys.append(f"  stack shape {composition.stack_shape}")
    if composition.has_opposing_pair:
        keys.append("opposing pair")
        for first, second in sorted({
            tuple(sorted(pair)) for pair in composition.opposing_pairs
        }):
            keys.append(f"  opposing {first}-{second}")
    if not composition.has_same_team_stack and not composition.is_unrelated:
        # Shares a game with somebody, but holds no quarterback-to-own-receiver
        # pair. Reported separately so "same-team stack" means the thing the
        # +0.24 cell measured and not "any two players who share an afternoon".
        keys.append("related, no QB stack")
    return tuple(keys)


# ---------------------------------------------------------------------------
# Marginal preservation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MarginalDrift:
    """How far one sampler moved a player's own distribution against another.

    Every figure is in fantasy points and is a **maximum** across players and
    stored knots, not a mean. A mean would hide the one player the sampler broke
    among the hundred it left alone, which is the only failure mode this
    measurement exists to catch.
    """

    label: str
    players: int
    #: Largest |P10/P25/P50/P75/P90 difference| over every player and knot.
    max_knot_drift: float
    #: Mean of the same, for scale.
    mean_knot_drift: float
    #: Largest |mean difference| over players.
    max_mean_drift: float
    #: The same maxima as a share of the player's own P10-P90 width, which is
    #: what makes a quarterback's 0.4 points comparable to a tight end's.
    max_knot_drift_share: float

    def __str__(self) -> str:
        return (
            f"{self.label:<34} players={self.players:>5,}  "
            f"maxKnot={self.max_knot_drift:6.3f} pts "
            f"({self.max_knot_drift_share:6.2%} of width)  "
            f"meanKnot={self.mean_knot_drift:6.3f}  "
            f"maxMean={self.max_mean_drift:6.3f}"
        )


def _simulate_players(
    rows: Sequence[PanelRow],
    *,
    mode: CorrelationMode,
    model: CorrelationModel | None,
    iterations: int,
    seed: int,
    factors: TailFactors | None,
) -> list[list[float]]:
    """Each player's own sampled points, sorted. One list per player."""
    members = [
        RosterMember(position=row.position, team=row.team, game_id=row.game_id)
        for row in rows
    ]
    sampler = build_sampler(members, mode=mode, model=model)
    quantiles = [
        (build_curve(row, factors) if factors else row.curve()).quantile
        for row in rows
    ]
    rng = random.Random(seed)
    samples: list[list[float]] = [[] for _ in rows]
    for _ in range(iterations):
        uniforms = sampler.draw(rng)
        for index, quantile in enumerate(quantiles):
            samples[index].append(quantile(uniforms[index]))
    for column in samples:
        column.sort()
    return samples


def _drift(
    label: str,
    first: Sequence[Sequence[float]],
    second: Sequence[Sequence[float]],
    rows: Sequence[PanelRow],
) -> MarginalDrift:
    knots = (0.10, 0.25, 0.50, 0.75, 0.90)
    worst = 0.0
    worst_share = 0.0
    worst_mean = 0.0
    total = 0.0
    count = 0
    for a, b, row in zip(first, second, rows):
        width = max(1e-9, row.p90 - row.p10)
        for probability in knots:
            gap = abs(percentile(a, probability) - percentile(b, probability))
            total += gap
            count += 1
            if gap > worst:
                worst = gap
            worst_share = max(worst_share, gap / width)
        worst_mean = max(
            worst_mean, abs(sum(a) / len(a) - sum(b) / len(b))
        )
    return MarginalDrift(
        label=label,
        players=len(rows),
        max_knot_drift=worst,
        mean_knot_drift=total / max(1, count),
        max_mean_drift=worst_mean,
        max_knot_drift_share=worst_share,
    )


def marginal_comparison(
    matchups: Sequence[SyntheticMatchup],
    *,
    model: CorrelationModel,
    iterations: int = 20_000,
    seed: int = 20261201,
    factors: TailFactors | None = None,
) -> tuple[MarginalDrift, MarginalDrift]:
    """Correlated versus independent marginals, and the Monte Carlo control.

    Returns ``(correlated_vs_independent, independent_vs_independent)``. The
    second is the same sampler run at a different seed, and it is the number the
    first has to be read against: any two Monte Carlo estimates of a P90 from
    20,000 draws differ, and a comparison that reports only the first figure
    cannot distinguish "correlation moved a marginal" from "this is what
    sampling a percentile costs".

    The algebra says the first figure must be zero in expectation —
    :class:`~nflfp.correlation.sampler.CorrelatedSampler` returns ``Phi(z)`` for
    a standard normal ``z``, which is exactly uniform — so this is a check on the
    implementation, not on the theory.
    """
    against_independent: list[MarginalDrift] = []
    against_itself: list[MarginalDrift] = []
    for matchup in matchups:
        rows = (*matchup.team_a, *matchup.team_b)
        independent = _simulate_players(
            rows, mode=CorrelationMode.INDEPENDENT, model=None,
            iterations=iterations, seed=seed, factors=factors,
        )
        correlated = _simulate_players(
            rows, mode=CorrelationMode.GAME_ENVIRONMENT, model=model,
            iterations=iterations, seed=seed, factors=factors,
        )
        control = _simulate_players(
            rows, mode=CorrelationMode.INDEPENDENT, model=None,
            iterations=iterations, seed=seed + 977, factors=factors,
        )
        against_independent.append(
            _drift("correlated vs independent", independent, correlated, rows)
        )
        against_itself.append(
            _drift("independent vs itself (control)", independent, control, rows)
        )

    def reduce(parts: Sequence[MarginalDrift], label: str) -> MarginalDrift:
        return MarginalDrift(
            label=label,
            players=sum(part.players for part in parts),
            max_knot_drift=max(part.max_knot_drift for part in parts),
            mean_knot_drift=mean(part.mean_knot_drift for part in parts),
            max_mean_drift=max(part.max_mean_drift for part in parts),
            max_knot_drift_share=max(part.max_knot_drift_share for part in parts),
        )

    return (
        reduce(against_independent, "correlated vs independent"),
        reduce(against_itself, "independent vs itself (control)"),
    )
