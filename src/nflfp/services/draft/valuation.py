"""What a player is worth *in a draft*, which is not what they are worth.

The single idea this module exists to express: **a projection is a number about
a player, and a draft value is a number about a player, a position, a league and
a moment.** Two hundred and forty points at wide receiver and two hundred and
twenty-five at running back are not comparable quantities, because the receiver
you could have had instead is much better than the back you could have had
instead. Everything below is machinery for making them comparable.

Four quantities, built on each other
------------------------------------
**Replacement level** — what the *worst starter* at a position is worth once
every team has filled its lineup. In a twelve-team league starting two backs and
one flex, roughly the 30th-best back is the last one anybody starts, so the
31st is free. That number is the zero point for the position.

**Value over replacement** — season value minus replacement level. This is the
number that makes positions comparable, and it is why a quarterback who
out-scores every running back is nonetheless not the first pick: the
twelfth-best quarterback is nearly as good as the best one, so drafting the best
one buys very little.

**Marginal roster value** — value over replacement, adjusted for what the roster
already holds. The third running back on a roster that starts two is not worth
their full surplus, because most weeks they do not play. What they *are* worth
is derived from the availability estimates already on the roster, not from a
constant: a backfield projected to miss a fifth of its games makes its backup
meaningfully more valuable than one projected to miss a tenth.

**Value over next available** — marginal value now, minus the marginal value of
what this position is likely to still offer at your next pick. This is the term
that answers "can I wait?", and it is the reason the engine will sometimes pass
on the highest-value player on the board. Taking a receiver who will still have
a near-equal replacement in two rounds, over a back whose tier ends in four
picks, is not a compromise — it is a higher expected roster.

The opponent model, and what it is not
--------------------------------------
:func:`consensus_scores` produces the board the eleven other managers draft
from. It is **not ADP**. This repository holds no average-draft-position data of
any kind, and inventing a number and calling it ADP would be the single most
misleading thing this feature could do, because ADP is the one input a user
would assume was observed.

What it is instead: a stated behavioural model, that real managers rank roughly
by value over replacement but overweight what a player did last season relative
to what a model projects. :data:`CONSENSUS_HISTORY_WEIGHT` is that overweighting
and it is an **assumption, not a measurement** — there is nothing in this
repository to fit it against. It is exposed as a request parameter so that the
sensitivity of any conclusion to it can be checked, and every response says
which value produced it.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .pool import DraftPlayer, DraftPool
from .settings import DraftSettings

#: How much the simulated opposing managers weight last season's actual finish
#: against value over replacement, 0-1. **Assumed, not fitted** — see the module
#: docstring. 0.35 places the modelled manager between a pure projection reader
#: and a pure last-season reader, closer to the projection.
CONSENSUS_HISTORY_WEIGHT = 0.35

#: Spread of the noise the opponent model adds, in units of the consensus score's
#: own standard deviation. Zero would make every simulated draft identical and
#: every availability percentage 0% or 100%; large values would make the board
#: random and availability uninformative. 0.35 produces a distribution in which
#: a player's actual selection point varies by roughly half a round at the top
#: and more than a round in the middle, which is the shape a real draft has.
#: Also an assumption; also a request parameter.
CONSENSUS_NOISE = 0.35

#: How strongly a simulated manager prefers a position they still need. Applied
#: as a bonus in units of the consensus score's standard deviation. Without it
#: opposing rosters end up with six receivers and no quarterback, which would
#: leave quarterbacks available far later than they are in any real draft and so
#: would corrupt the availability model the user's strategy reads.
NEED_BONUS = 0.6

#: Bench weight is derived per roster from the availability of the starters it
#: would back up, then clamped. The floor keeps a bench pick from scoring zero —
#: a backup has some value even behind an iron man; the ceiling stops a roster
#: of fragile starters from valuing depth above starters.
MIN_BENCH_WEIGHT = 0.05
MAX_BENCH_WEIGHT = 0.60


# ---------------------------------------------------------------------------
# Replacement level
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplacementLevel:
    """The zero point for one position under one league configuration.

    Attributes:
        position: Position code.
        starters: How many players at this position the league starts in total,
            counting the share of flex slots allocated to it.
        value: Season value of the first player *past* that count — the best
            player nobody has to start, and therefore the value a roster gets
            for free.
        player_id: Who that player is, so the number can be shown with a name
            beside it rather than asserted.
        flex_share: How many of the ``starters`` came from flex allocation.
    """

    position: str
    starters: int
    value: float
    player_id: str | None
    flex_share: int


def replacement_levels(
    pool: DraftPool, settings: DraftSettings
) -> dict[str, ReplacementLevel]:
    """Compute the replacement level for every draftable position.

    Dedicated slots are counted directly: ``teams x required(position)``. Flex
    slots are then **allocated by auction rather than by assumption** — each flex
    slot in turn goes to whichever eligible position currently offers the most
    valuable next player. That is the allocation a league of rational managers
    produces, and deriving it means a receiver-heavy or a back-heavy player pool
    moves the replacement levels on its own, which a fixed "flex is 60% running
    back" rule could not.

    Args:
        pool: The draft pool, whose players are already ordered by season value.
        settings: League configuration.

    Returns:
        One :class:`ReplacementLevel` per position present in the pool.
    """
    ranked: dict[str, list[DraftPlayer]] = {}
    for player in pool.players:
        ranked.setdefault(player.position, []).append(player)
    for players in ranked.values():
        players.sort(key=lambda p: -p.season_value)

    counts = {
        position: settings.teams * settings.required(position) for position in ranked
    }

    flex_slots = settings.teams * settings.required("FLEX")
    flex_positions = tuple(
        position
        for position in ranked
        if any(
            requirement.slot == "FLEX" and requirement.accepts(position)
            for requirement in settings.roster
        )
    )
    flex_share = dict.fromkeys(ranked, 0)

    for _ in range(flex_slots):
        best_position: str | None = None
        best_value = -math.inf
        for position in flex_positions:
            index = counts.get(position, 0)
            players = ranked[position]
            if index >= len(players):
                continue
            if players[index].season_value > best_value:
                best_value = players[index].season_value
                best_position = position
        if best_position is None:
            break
        counts[best_position] = counts.get(best_position, 0) + 1
        flex_share[best_position] += 1

    levels: dict[str, ReplacementLevel] = {}
    for position, players in ranked.items():
        index = counts.get(position, 0)
        if index < len(players):
            replacement = players[index]
            value, player_id = replacement.season_value, replacement.player_id
        elif players:
            # The league starts more of this position than the pool holds. The
            # last player in the pool is the honest floor: everything below them
            # is undrafted, and pretending replacement is zero would inflate
            # every surplus at the position.
            value, player_id = players[-1].season_value, players[-1].player_id
        else:
            value, player_id = 0.0, None
        levels[position] = ReplacementLevel(
            position=position,
            starters=index,
            value=value,
            player_id=player_id,
            flex_share=flex_share.get(position, 0),
        )
    return levels


def value_over_replacement(
    player: DraftPlayer, levels: Mapping[str, ReplacementLevel]
) -> float:
    """Season value above the position's replacement level.

    Not floored at zero. A negative surplus is real information — it says this
    player would not start in this league — and clipping it would make every
    undraftable player look identical to the last startable one.
    """
    level = levels.get(player.position)
    return player.season_value - (level.value if level else 0.0)


# ---------------------------------------------------------------------------
# The opponent's board
# ---------------------------------------------------------------------------


def consensus_scores(
    pool: DraftPool,
    levels: Mapping[str, ReplacementLevel],
    *,
    history_weight: float = CONSENSUS_HISTORY_WEIGHT,
) -> dict[str, float]:
    """The board the simulated opposing managers draft from.

    A standardised blend of value over replacement and last completed season's
    actual points. Both are standardised across the whole pool before blending,
    so the weight means what it says: at ``history_weight = 0.35``, roughly a
    third of a simulated manager's ranking is last year's box score.

    Blending a projection with a historical actual is exactly what the *value*
    side of this package refuses to do — and it is the right thing to do here,
    because this is not a value estimate. It is a model of what other people
    will do, and other people demonstrably over-weight last season. The two uses
    are kept in separate functions so the distinction cannot erode.

    Players with no completed season contribute a neutral historical component
    rather than a zero, because "no history" is not evidence of a bad season and
    scoring it as one would make every second-year player fall implausibly far.
    """
    if not pool.players:
        return {}

    vor = {p.player_id: value_over_replacement(p, levels) for p in pool.players}
    history = {
        p.player_id: p.historical.prior_season_points
        for p in pool.players
    }

    vor_z = _standardise(vor)
    observed = {pid: value for pid, value in history.items() if value is not None}
    history_z = _standardise(observed)

    weight = min(1.0, max(0.0, history_weight))
    return {
        player_id: (1.0 - weight) * vor_z[player_id]
        + weight * history_z.get(player_id, 0.0)
        for player_id in vor_z
    }


def _standardise(values: Mapping[str, float]) -> dict[str, float]:
    """Z-score a mapping, returning zeros when there is no spread to divide by."""
    if not values:
        return {}
    numbers = list(values.values())
    mean = statistics.fmean(numbers)
    spread = statistics.pstdev(numbers) if len(numbers) > 1 else 0.0
    if spread <= 1e-9:
        return dict.fromkeys(values, 0.0)
    return {key: (value - mean) / spread for key, value in values.items()}


# ---------------------------------------------------------------------------
# Roster context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RosterNeeds:
    """What a partially-drafted roster still has to fill.

    Attributes:
        open_dedicated: Position-specific starting slots still empty.
        open_flex: Flex slots still empty.
        counts: Players held, by position.
        picks_remaining: Selections this roster still makes.
    """

    open_dedicated: Mapping[str, int]
    open_flex: int
    counts: Mapping[str, int]
    picks_remaining: int

    @property
    def open_starters(self) -> int:
        return sum(self.open_dedicated.values()) + self.open_flex

    @property
    def must_fill_starters(self) -> bool:
        """Every remaining pick is needed to complete the starting lineup.

        Once this is true the engine stops optimising and starts satisfying: a
        roster that finishes without a quarterback is not a roster, and the
        comparison between draft positions is meaningless if some seats produce
        illegal lineups.
        """
        return self.picks_remaining <= self.open_starters


def roster_needs(
    roster: Sequence[DraftPlayer], settings: DraftSettings, picks_remaining: int
) -> RosterNeeds:
    """Work out what a roster still needs.

    Dedicated slots are filled first and greedily by position, then flex. That
    ordering matters: a roster holding three receivers in a league starting two
    plus a flex has filled WR, WR and FLEX, and needs a back — not a fourth
    receiver for its "open" flex.
    """
    counts: dict[str, int] = {}
    for player in roster:
        counts[player.position] = counts.get(player.position, 0) + 1

    open_dedicated: dict[str, int] = {}
    spare: dict[str, int] = dict(counts)
    for requirement in settings.roster:
        if requirement.slot == "FLEX":
            continue
        position = requirement.slot
        held = spare.get(position, 0)
        used = min(held, requirement.count)
        spare[position] = held - used
        if requirement.count - used > 0:
            open_dedicated[position] = requirement.count - used

    flex_required = settings.required("FLEX")
    flex_eligible_spare = sum(
        count
        for position, count in spare.items()
        if any(r.slot == "FLEX" and r.accepts(position) for r in settings.roster)
    )
    open_flex = max(0, flex_required - flex_eligible_spare)

    return RosterNeeds(
        open_dedicated=open_dedicated,
        open_flex=open_flex,
        counts=counts,
        picks_remaining=picks_remaining,
    )


def bench_weight(
    roster: Sequence[DraftPlayer], position: str, season_games: int
) -> float:
    """How much of a surplus a bench player at ``position`` actually delivers.

    Derived from the roster rather than assumed: a bench player earns their
    surplus in the weeks the starters ahead of them are unavailable, so the
    weight is the mean *unavailability* already estimated for the players held
    at that position. A backfield of two 15.5-game starters yields ~0.09; one
    carrying a 12-game injury history yields ~0.25, and the engine will reach
    for depth accordingly — which is the behaviour a fantasy manager would
    recognise, produced by the data rather than by a rule about handcuffs.

    Clamped, because the estimate degrades at the extremes: an empty position
    would give 1.0 (it is not a bench pick at all — that case is handled as a
    starter before this is called) and a perfectly durable pair would give 0.0
    (a backup is never worth literally nothing).
    """
    held = [p for p in roster if p.position == position]
    if not held or season_games <= 0:
        return MAX_BENCH_WEIGHT
    unavailability = statistics.fmean(
        [max(0.0, 1.0 - p.expected_games / season_games) for p in held]
    )
    return min(MAX_BENCH_WEIGHT, max(MIN_BENCH_WEIGHT, unavailability))


def marginal_value(
    candidate: DraftPlayer,
    roster: Sequence[DraftPlayer],
    needs: RosterNeeds,
    levels: Mapping[str, ReplacementLevel],
    settings: DraftSettings,
    season_games: int,
    bench_weights: Mapping[str, float] | None = None,
) -> tuple[float, str]:
    """What adding this player is worth to *this* roster, and which slot it fills.

    Args:
        candidate: The player being considered.
        roster: What the seat already holds.
        needs: The seat's open slots, from :func:`roster_needs`.
        levels: Replacement levels by position.
        settings: League configuration.
        season_games: Regular-season games, for the bench weighting.
        bench_weights: Precomputed :func:`bench_weight` per position. Purely an
            optimisation for the inner loop, where the weight is the same for
            every candidate at a position and recomputing it per candidate is
            most of the cost of a pick. Omitting it computes the same number.

    Returns:
        ``(value, slot)`` where ``slot`` is ``"starter"``, ``"flex"`` or
        ``"bench"`` — returned rather than inferred so the explanation can name
        it instead of reverse-engineering it from the number.
    """
    surplus = value_over_replacement(candidate, levels)
    flex_ok = any(
        requirement.slot == "FLEX" and requirement.accepts(candidate.position)
        for requirement in settings.roster
    )
    weight = (
        bench_weights.get(candidate.position)
        if bench_weights is not None
        else None
    )
    if weight is None:
        weight = bench_weight(roster, candidate.position, season_games)

    held = [p for p in roster if p.position == candidate.position]
    weakest = min((p.season_value for p in held), default=None)

    return marginal_value_of(
        season_value=candidate.season_value,
        surplus=surplus,
        open_dedicated=needs.open_dedicated.get(candidate.position, 0),
        open_flex=needs.open_flex,
        flex_eligible=flex_ok,
        bench_weight=weight,
        weakest_held_value=weakest,
    )


def marginal_value_of(
    *,
    season_value: float,
    surplus: float,
    open_dedicated: int,
    open_flex: int,
    flex_eligible: bool,
    bench_weight: float,
    weakest_held_value: float | None,
) -> tuple[float, str]:
    """The arithmetic behind :func:`marginal_value`, over scalars only.

    Split out so the engine's inner loop can call it with values it has already
    precomputed per position, instead of rebuilding a roster slice and re-deriving
    flex eligibility for every one of the sixty candidates it scores at every
    pick. Both entry points run *this* function, so the fast path and the
    readable path cannot produce different numbers — which is asserted by a test
    that drives the pair over the same inputs.
    """
    if open_dedicated > 0:
        return surplus, "starter"
    if open_flex > 0 and flex_eligible:
        return surplus, "flex"

    # A bench pick can still be an upgrade: a roster whose starting tight end is
    # replacement-level gains the whole difference by drafting a better one, and
    # the surplus above the *worst held starter* is what it gains. Taking the
    # larger of that and the discounted insurance value is what stops the engine
    # refusing to improve a position it has nominally filled.
    #
    # Neither term is floored at zero, and that is load-bearing rather than
    # tidy. Flooring makes every below-replacement candidate score exactly 0.0,
    # at which point the late rounds are decided entirely by the iteration order
    # and the engine drafts a third quarterback because quarterbacks sort first.
    # Letting both terms go negative keeps the ordering meaningful all the way
    # down the board: the least-bad bench player wins, which is the right answer
    # and the one a manager would give.
    upgrade = (
        -math.inf if weakest_held_value is None else season_value - weakest_held_value
    )
    return max(surplus * bench_weight, upgrade), "bench"


# ---------------------------------------------------------------------------
# Opportunity cost
# ---------------------------------------------------------------------------


def expected_best_available(
    candidates: Sequence[DraftPlayer],
    values: Mapping[str, float],
    survival: Mapping[str, float],
) -> tuple[float, str | None]:
    """Expected value of the best of ``candidates`` still on the board later.

    The order statistic, computed exactly rather than sampled::

        E[best] = sum_i  value_i * P(i survives) * prod_{j<i} (1 - P(j survives))

    over candidates sorted by value descending. Each term is "player *i* is the
    best one left", which requires *i* to survive and everyone better than *i*
    to be gone. It is one pass, it is deterministic, and it does not need the
    engine to run a nested simulation inside every pick.

    The independence assumption is real and worth naming: two receivers in the
    same tier are competing for the same managers' picks, so one surviving makes
    the other slightly *less* likely to. The error pushes the expectation up a
    little, which makes the engine marginally more willing to wait. It is
    disclosed with the result rather than corrected, because correcting it would
    need a joint model this package has no way to validate.

    Returns:
        ``(expected_value, most_likely_player_id)``. The second element is the
        single likeliest "best left" and is what an explanation names when it
        says who you would probably get instead.
    """
    ordered = sorted(candidates, key=lambda p: -values.get(p.player_id, 0.0))
    expected = 0.0
    gone = 1.0
    best_term = 0.0
    best_player: str | None = None

    for player in ordered:
        probability = survival.get(player.player_id, 0.0)
        term = gone * probability
        expected += term * values.get(player.player_id, 0.0)
        if term > best_term:
            best_term = term
            best_player = player.player_id
        gone *= 1.0 - probability
        if gone < 1e-6:
            break

    return expected, best_player


# ---------------------------------------------------------------------------
# Scarcity and tiers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Tier:
    """A run of players on one position's board with no meaningful gap inside it."""

    position: str
    index: int
    player_ids: tuple[str, ...]
    top_value: float
    bottom_value: float

    @property
    def size(self) -> int:
        return len(self.player_ids)


#: A gap is a tier boundary when it stands this many standard deviations above
#: the mean gap on the position's board. Relative rather than absolute, for the
#: reason the existing weekly tiering gives: a fixed points gap produces
#: enormous tiers at the top of a board and singletons at the bottom, purely
#: because value is spread unevenly down a position.
#:
#: Measured against the mean-and-spread of the gaps rather than a multiple of
#: their median, which was the first thing tried and which cut every position
#: into singletons at the top — the gaps between the best few players at a
#: position are always several times the median gap, so a median rule finds a
#: "cliff" between the first and second player on every board and says nothing.
TIER_GAP_SIGMA = 1.0


def build_tiers(players: Sequence[DraftPlayer], *, limit: int = 60) -> tuple[Tier, ...]:
    """Split one position's board into tiers at its unusually large gaps.

    The weekly product tiers players by ``P(lower beats upper)`` over their
    stored distributions, which is a better method and is not available here:
    those distributions describe a *week*, and there is no stored season-long
    distribution to integrate. So this is a gap rule on season value, and it is
    labelled a gap rule wherever it surfaces rather than borrowing the
    probabilistic claim the weekly tiers can make.
    """
    ranked = sorted(players, key=lambda p: -p.season_value)[:limit]
    if len(ranked) < 3:
        return (
            (
                Tier(
                    position=ranked[0].position,
                    index=1,
                    player_ids=tuple(p.player_id for p in ranked),
                    top_value=ranked[0].season_value,
                    bottom_value=ranked[-1].season_value,
                ),
            )
            if ranked
            else ()
        )

    gaps = [
        ranked[i].season_value - ranked[i + 1].season_value for i in range(len(ranked) - 1)
    ]
    mean_gap = statistics.fmean(gaps)
    spread = statistics.pstdev(gaps) if len(gaps) > 1 else 0.0
    threshold = mean_gap + TIER_GAP_SIGMA * spread

    tiers: list[Tier] = []
    current: list[DraftPlayer] = [ranked[0]]
    for index, gap in enumerate(gaps):
        if spread > 0 and gap > threshold:
            tiers.append(_tier(current, len(tiers) + 1))
            current = []
        current.append(ranked[index + 1])
    if current:
        tiers.append(_tier(current, len(tiers) + 1))
    return tuple(tiers)


def _tier(players: Sequence[DraftPlayer], index: int) -> Tier:
    return Tier(
        position=players[0].position,
        index=index,
        player_ids=tuple(p.player_id for p in players),
        top_value=players[0].season_value,
        bottom_value=players[-1].season_value,
    )


def positional_scarcity(
    available: Sequence[DraftPlayer], levels: Mapping[str, ReplacementLevel]
) -> dict[str, float]:
    """How steeply value falls away at each position, right now.

    Defined as the drop from the best available player to the fifth-best
    available at the position, expressed as a fraction of the best one's surplus
    over replacement. A position where the top five are interchangeable scores
    near zero; one where the best player is alone above a cliff scores near one.

    Five is a draft's natural horizon rather than an arbitrary window: in a
    twelve-team league a manager waiting one round sees roughly a round and a
    half of picks, and five players at one position is about what leaves the
    board in that time.
    """
    grouped: dict[str, list[DraftPlayer]] = {}
    for player in available:
        grouped.setdefault(player.position, []).append(player)

    scarcity: dict[str, float] = {}
    for position, players in grouped.items():
        players.sort(key=lambda p: -p.season_value)
        level = levels.get(position)
        floor = level.value if level else 0.0
        best_surplus = players[0].season_value - floor
        if best_surplus <= 0:
            scarcity[position] = 0.0
            continue
        depth = players[min(4, len(players) - 1)]
        scarcity[position] = max(
            0.0, min(1.0, (players[0].season_value - depth.season_value) / best_surplus)
        )
    return scarcity
