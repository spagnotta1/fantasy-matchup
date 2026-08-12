"""The mock draft engine: pure, seeded, and free of everything above it.

:func:`simulate_draft` takes a context of plain dataclasses and a
:class:`random.Random`, and returns a dataclass. No session, no clock, no
global random state, no framework — the same shape
:func:`nflfp.services.simulation.simulate` has, for the same reasons: every
statistical property claimed here is unit-testable against a constructed pool,
and the async layer above can hand the whole thing to a worker thread without
the mathematics noticing.

Two stages, and why availability needs its own pass
---------------------------------------------------
The user's strategy depends on what will still be available at their next pick,
and what is available depends on what everybody drafts. Resolving that inside a
single pass would mean a nested simulation at every pick.

Instead the engine runs a **calibration stage** first: a batch of drafts in which
all seats use the opponent model, from which the distribution of each player's
selection point is recorded. That produces :class:`AvailabilityModel`, a
survival curve per player, which the **analysis stage** then reads when the
user's seat weighs waiting against taking.

Calibrating without the user's strategy in it is deliberate. One seat in twelve
barely moves the board, and a survival curve that already assumed the user's
strategy would be circular — the strategy would be optimising against its own
shadow. The residual bias is that the curves do not account for the user's own
seat behaving differently from a consensus drafter, which very slightly
overstates availability at the positions that seat favours. It is disclosed
rather than corrected.

The opponent model
------------------
Every simulated manager scores the board as ``consensus + need_bonus + noise``
and takes the best. The noise is Gumbel, which makes the selection exactly a
softmax sample over those scores — a standard, checkable construction rather
than "pick randomly from the top five", and one whose spread is a single
interpretable parameter. Nothing here is fitted to real draft data, because this
repository holds none; the parameters are stated assumptions and travel with
every response.

The user's strategy
-------------------
At each of the user's picks every plausible candidate is scored as::

    marginal_value(candidate)              what it adds to *this* roster
      - expected_best_available(position)  what waiting would still get you

which is value over next available. The subtraction is the whole strategy: a
candidate is worth taking now to the extent that the position will be worse
later. On the final pick there is no next pick, the expectation is zero by
construction, and the expression degenerates to raw marginal value on its own
rather than through a special case.

Determinism
-----------
Every draft derives its generator from ``(seed, draft_position, index)`` as a
string key, so simulation *n* of seat 4 is the same draft whether it was reached
by analysing seat 4 alone or by comparing all twelve seats. That is what makes
the comparison chart reproducible, and what stops a seat's rank depending on how
the user arrived at it.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .order import DraftOrder
from .pool import DraftPlayer, DraftPool
from .settings import DraftSettings
from .valuation import (
    CONSENSUS_HISTORY_WEIGHT,
    CONSENSUS_NOISE,
    NEED_BONUS,
    ReplacementLevel,
    Tier,
    bench_weight,
    build_tiers,
    consensus_scores,
    marginal_value_of,
    positional_scarcity,
    replacement_levels,
    roster_needs,
    value_over_replacement,
)

#: Candidates an opposing manager looks at. A real manager reads the top of
#: their board, not all 354 names, and bounding it is also what keeps the inner
#: loop affordable.
OPPONENT_HORIZON = 30

#: Candidates the user's seat evaluates in full. Wider than the opponent's,
#: because value over replacement reorders the board substantially against
#: consensus and the best available pick is regularly outside the consensus top
#: ten — which is the entire point of computing it.
USER_HORIZON = 60

#: Players scanned when grouping the board by position for the lookahead. Beyond
#: this the survival probability at the next pick is ~1 and the order statistic
#: has converged, so more work changes no decision.
LOOKAHEAD_HORIZON = 120

#: Drafts the calibration stage runs. Enough that a survival curve is smooth to
#: about a percentage point, and cheap because no seat does lookahead work in
#: this stage.
CALIBRATION_DRAFTS = 200

#: Strategies the user's seat can be made to follow.
#:
#: ``value_over_next_available`` is the product. The other three exist so that
#: the claim "this strategy is better" can be *measured* rather than asserted —
#: they are the baselines :mod:`nflfp.services.draft.evaluate` drafts against,
#: and they are implemented in the same engine, against the same opponents, with
#: the same seeds, so a difference between them is a difference in strategy and
#: not in anything else.
#:
#: All four obey roster legality and the depth cap. A baseline that produced an
#: illegal lineup would beat the others on points while being worth nothing, and
#: comparing against it would flatter the product for the wrong reason.
STRATEGIES: tuple[str, ...] = (
    "value_over_next_available",
    "highest_season_value",
    "highest_points_per_game",
    "random",
)

#: Players a roster may hold at one position over and above what it starts.
#: Without a cap a simulated manager occasionally assembles six tight ends,
#: which distorts the availability model more than it distorts that roster.
POSITION_DEPTH_ALLOWANCE = 2


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DraftContext:
    """Everything derived once and shared by every simulated draft.

    Building this per draft would recompute replacement levels, consensus
    scores and tiers ten thousand times over an unchanging pool. It is also the
    natural testing seam: a context can be constructed by hand from a handful of
    players, with no database and no pool builder.
    """

    pool: DraftPool
    settings: DraftSettings
    order: DraftOrder
    levels: Mapping[str, ReplacementLevel]
    consensus: Mapping[str, float]
    tiers: Mapping[str, tuple[Tier, ...]]
    season_games: int
    players: tuple[DraftPlayer, ...]
    depth_cap: Mapping[str, int]
    #: Parallel arrays over :attr:`players`, in the same order. The inner loops
    #: run on these rather than on the dataclasses: a draft touches a player's
    #: value and position tens of thousands of times, and an attribute lookup on
    #: a frozen dataclass is several times the cost of a list index. Nothing
    #: about the mathematics changes — these are the same numbers — and every
    #: result is rebuilt from :attr:`players` before it leaves the engine.
    values: tuple[float, ...] = ()
    positions: tuple[str, ...] = ()
    consensus_by_index: tuple[float, ...] = ()
    replacement: Mapping[str, float] = field(default_factory=dict)
    index_by_id: Mapping[str, int] = field(default_factory=dict)
    #: League shape flattened to lookups. ``DraftSettings.required`` walks a
    #: tuple of requirements and ``flex_eligible`` walks it again; both are
    #: called once per candidate per pick, which is tens of millions of tuple
    #: scans over a league configuration that never changes.
    required_by_position: Mapping[str, int] = field(default_factory=dict)
    flex_positions: frozenset[str] = frozenset()
    flex_slots: int = 0
    history_weight: float = CONSENSUS_HISTORY_WEIGHT
    noise: float = CONSENSUS_NOISE
    #: :attr:`noise` expressed in the consensus score's own units. The score is
    #: standardised, so this is very nearly :attr:`noise` itself; it is derived
    #: rather than assumed so the two stay in step if the standardisation ever
    #: changes, and stored rather than computed on demand because the inner loop
    #: reads it once per candidate.
    noise_scale: float = CONSENSUS_NOISE

    @classmethod
    def build(
        cls,
        pool: DraftPool,
        settings: DraftSettings,
        *,
        history_weight: float = CONSENSUS_HISTORY_WEIGHT,
        noise: float = CONSENSUS_NOISE,
    ) -> DraftContext:
        levels = replacement_levels(pool, settings)
        consensus = consensus_scores(pool, levels, history_weight=history_weight)
        order = DraftOrder.build(
            teams=settings.teams, rounds=settings.rounds, snake=settings.is_snake
        )
        tiers = {
            position: build_tiers(pool.by_position(position))
            for position in pool.positions
        }

        flex = settings.required("FLEX")
        depth_cap = {
            position: settings.required(position)
            + (flex if flex_eligible(position, settings) else 0)
            + POSITION_DEPTH_ALLOWANCE
            for position in pool.positions
        }

        # Ordered once by the board the opponents read, so no simulation sorts.
        ordered = tuple(
            sorted(pool.players, key=lambda p: (-consensus.get(p.player_id, 0.0), p.player_id))
        )

        scores = list(consensus.values())
        if len(scores) > 1:
            mean = sum(scores) / len(scores)
            variance = sum((s - mean) ** 2 for s in scores) / len(scores)
            noise_scale = noise * (math.sqrt(variance) or 1.0)
        else:
            noise_scale = noise
        return cls(
            pool=pool,
            settings=settings,
            order=order,
            levels=levels,
            consensus=consensus,
            tiers=tiers,
            season_games=pool.season_games,
            players=ordered,
            depth_cap=depth_cap,
            values=tuple(p.season_value for p in ordered),
            positions=tuple(p.position for p in ordered),
            consensus_by_index=tuple(
                consensus.get(p.player_id, 0.0) for p in ordered
            ),
            replacement={
                position: level.value for position, level in levels.items()
            },
            index_by_id={p.player_id: i for i, p in enumerate(ordered)},
            required_by_position={
                position: settings.required(position) for position in pool.positions
            },
            flex_positions=frozenset(
                position
                for position in pool.positions
                if flex_eligible(position, settings)
            ),
            flex_slots=flex,
            history_weight=history_weight,
            noise=noise,
            noise_scale=noise_scale,
        )

    def tier_of(self, player: DraftPlayer) -> Tier | None:
        for tier in self.tiers.get(player.position, ()):
            if player.player_id in tier.player_ids:
                return tier
        return None


def flex_eligible(position: str, settings: DraftSettings) -> bool:
    """Whether a position may fill this league's flex slot."""
    return any(
        requirement.slot == "FLEX" and requirement.accepts(position)
        for requirement in settings.roster
    )


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AvailabilityModel:
    """Per-player survival curves, aggregated over the calibration drafts.

    Attributes:
        drafts: Calibration drafts behind every number here.
        total_picks: Length of the draft the curves describe.
        survival: ``player_id -> tuple`` indexed by overall pick, giving the
            probability the player is still on the board **immediately before**
            that pick. Index 0 is unused so the tuple reads 1-based, matching
            every pick number the product shows.
        mean_pick: Mean selection point among the drafts in which the player was
            selected at all, or ``None`` for one never taken.
        selected_rate: Share of calibration drafts in which the player was taken
            at all — the honest denominator for ``mean_pick``, and the number
            that distinguishes "goes late" from "usually goes undrafted".
    """

    drafts: int
    total_picks: int
    survival: Mapping[str, tuple[float, ...]]
    mean_pick: Mapping[str, float | None]
    selected_rate: Mapping[str, float]

    def probability_available(self, player_id: str, overall: int | None) -> float:
        """Probability the player is on the board immediately before ``overall``.

        ``overall`` of ``None`` — there is no next pick — returns 0.0. A player
        cannot be available at a pick that does not exist, and returning zero
        makes the lookahead term vanish, which is the correct behaviour on the
        last selection of a draft rather than a case to special-case.
        """
        if overall is None:
            return 0.0
        curve = self.survival.get(player_id)
        if not curve:
            return 0.0
        return curve[overall] if overall < len(curve) else curve[-1]


def calibrate_availability(
    context: DraftContext, *, drafts: int = CALIBRATION_DRAFTS, seed: int
) -> AvailabilityModel:
    """Estimate when each player leaves the board.

    Runs ``drafts`` complete drafts in which every seat uses the opponent model
    and accumulates, per player, the pick at which they were taken. Only counts
    survive the loop — no draft, no pick list, no per-event record — which is
    what stops a large request materialising a million rows in order to display
    twelve numbers.
    """
    total = context.order.total_picks
    selections: dict[str, list[int]] = {
        player.player_id: [0] * (total + 2) for player in context.players
    }
    pick_sum: dict[str, int] = dict.fromkeys(selections, 0)
    pick_count: dict[str, int] = dict.fromkeys(selections, 0)

    for index in range(drafts):
        rng = random.Random(f"calibration:{seed}:{index}")
        for player_id, overall in _consensus_draft(context, rng).items():
            pick_sum[player_id] += overall
            pick_count[player_id] += 1
            # One increment at the selection point. The cumulative sum below
            # turns that into a survival curve without touching every pick.
            selections[player_id][overall] += 1

    survival: dict[str, tuple[float, ...]] = {}
    mean_pick: dict[str, float | None] = {}
    selected_rate: dict[str, float] = {}
    for player_id, counts in selections.items():
        curve = [1.0] * (total + 2)
        gone = 0
        for overall in range(1, total + 2):
            curve[overall] = 1.0 - gone / drafts
            gone += counts[overall]
        survival[player_id] = tuple(curve)
        taken = pick_count[player_id]
        mean_pick[player_id] = (pick_sum[player_id] / taken) if taken else None
        selected_rate[player_id] = taken / drafts

    return AvailabilityModel(
        drafts=drafts,
        total_picks=total,
        survival=survival,
        mean_pick=mean_pick,
        selected_rate=selected_rate,
    )


def _consensus_draft(context: DraftContext, rng: random.Random) -> dict[str, int]:
    """One draft in which every seat uses the opponent model.

    Returns ``player_id -> overall pick``. Calibration is all this serves, so it
    records nothing else.
    """
    players = context.players
    positions = context.positions
    available = list(range(len(players)))
    counts: list[dict[str, int]] = [{} for _ in range(context.settings.teams + 1)]
    taken: dict[str, int] = {}

    for slot in context.order:
        at = _opponent_choice(context, available, counts[slot.team], rng)
        if at is None:
            continue
        index = available.pop(at)
        position = positions[index]
        held = counts[slot.team]
        held[position] = held.get(position, 0) + 1
        taken[players[index].player_id] = slot.overall
    return taken


def _opponent_choice(
    context: DraftContext,
    available: Sequence[int],
    held: Mapping[str, int],
    rng: random.Random,
) -> int | None:
    """Offset **into ``available``** of a simulated opposing manager's selection.

    The return is a position in the availability list rather than a player
    index, so the caller can ``pop`` it in one operation; the two are different
    numbers and confusing them would draft the wrong player without failing.

    Gumbel-max: adding ``-log(-log(u))`` to each score and taking the maximum
    draws exactly from the softmax over those scores. That is one uniform per
    candidate and no normalisation, and — unlike "shuffle the top five" — it has
    a stated distribution that a test can check.
    """
    scale = context.noise_scale
    consensus = context.consensus_by_index
    positions = context.positions
    depth_cap = context.depth_cap
    required = context.required_by_position
    flex_positions = context.flex_positions
    flex_slots = context.flex_slots
    log = math.log
    uniform = rng.random

    best_at: int | None = None
    best_score = -math.inf
    considered = 0

    for at in range(len(available)):
        if considered >= OPPONENT_HORIZON:
            break
        index = available[at]
        position = positions[index]
        cap = depth_cap.get(position)
        if cap is not None and held.get(position, 0) >= cap:
            continue
        considered += 1

        score = consensus[index] + _need_bonus(
            position, held, required, flex_positions, flex_slots
        )
        # Guard the log against a uniform of exactly 0.0, which random() can
        # return. Without it one draft in ~2^53 raises instead of drafting.
        draw = uniform() or 1e-12
        score += scale * -log(-log(draw))

        if score > best_score:
            best_score = score
            best_at = at

    if best_at is None and available:
        # Every candidate inside the horizon was capped out at its position.
        # A pick is never forfeited: a manager whose board is exhausted takes
        # the best player left regardless of depth, because a skipped selection
        # would leave a player on the board who should not be there and would
        # inflate everyone else's availability for the rest of the draft.
        return _relaxed_choice(available, positions, depth_cap, held)

    return best_at


def _relaxed_choice(
    available: Sequence[int],
    positions: Sequence[str],
    depth_cap: Mapping[str, int],
    held: Mapping[str, int],
) -> int:
    """The best remaining player when every constraint has been exhausted.

    Prefers an uncapped position if one exists anywhere in the pool — not just
    inside the horizon — and only then ignores the cap entirely. Returns an
    offset into ``available``, which is never empty at this point.
    """
    for at, index in enumerate(available):
        position = positions[index]
        cap = depth_cap.get(position)
        if cap is None or held.get(position, 0) < cap:
            return at
    return 0


def _need_bonus(
    position: str,
    held: Mapping[str, int],
    required: Mapping[str, int],
    flex_positions: frozenset[str],
    flex_slots: int,
) -> float:
    """How much a simulated manager favours a position they still need.

    Full bonus for an unfilled dedicated slot, half for a position that could
    still fill an open flex, nothing once both are covered. Without this,
    opposing rosters finish with six receivers and no quarterback, and
    quarterbacks then survive far later than they do in any real draft — which
    would corrupt the availability curves the user's strategy reads.

    Takes flattened lookups rather than the settings object because it runs once
    per candidate per pick: at ten thousand simulations that is tens of millions
    of calls, and walking a tuple of requirements inside each of them is most of
    the cost of the opponent model.
    """
    if held.get(position, 0) < required.get(position, 0):
        return NEED_BONUS

    if flex_slots and position in flex_positions:
        spare = 0
        for pos, count in held.items():
            if pos in flex_positions:
                spare += max(0, count - required.get(pos, 0))
        if spare < flex_slots:
            return NEED_BONUS / 2
    return 0.0


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PickRationale:
    """Why the engine took this player, in the numbers that decided it.

    Every field is read straight off the calculation that produced the pick.
    Nothing is generated, restated or embellished: the sentence a user reads is
    assembled from these, so it cannot drift from what the engine did.
    """

    marginal_value: float
    slot: str
    survival_at_next_pick: float
    expected_next_best_value: float
    value_over_next_available: float
    next_best_player_id: str | None
    next_best_player_name: str | None
    next_pick_overall: int | None
    scarcity: float
    tier_index: int | None
    tier_size: int | None
    tier_remaining: int | None
    runner_up_id: str | None
    runner_up_name: str | None
    runner_up_margin: float | None


@dataclass(frozen=True)
class SimulatedPick:
    """One selection made by the user's seat in one simulated draft."""

    overall: int
    round_number: int
    player_id: str
    name: str
    position: str
    team: str | None
    season_value: float
    projected_points_per_game: float
    expected_games: float
    value_over_replacement: float
    rationale: PickRationale | None = None


@dataclass(frozen=True)
class SimulatedDraft:
    """The outcome of one simulated draft from one seat.

    Attributes:
        picks: The user's selections, in order.
        roster_value: Total value over replacement of the *starting* lineup.
            The comparison number: it is what the roster is worth above what any
            seat could have assembled from undrafted players.
        starter_points: Projected season points of the starting lineup. The
            headline number, and deliberately separate from ``roster_value`` —
            they rank seats differently and both are worth seeing.
        bench_value: Value over replacement held on the bench.
        starters: Player ids assigned to starting slots.
    """

    picks: tuple[SimulatedPick, ...]
    roster_value: float
    starter_points: float
    bench_value: float
    starters: tuple[str, ...]


def simulate_draft(
    context: DraftContext,
    *,
    draft_position: int,
    availability: AvailabilityModel,
    rng: random.Random,
    capture_rationale: bool = False,
    survival_by_pick: Mapping[int, Sequence[float]] | None = None,
    strategy: str = "value_over_next_available",
) -> SimulatedDraft:
    """Run one complete draft and return what the user's seat ended up with.

    Args:
        context: The shared, precomputed draft context.
        draft_position: The user's 1-based seat.
        availability: Survival curves from :func:`calibrate_availability`.
        rng: A private generator. Never the global one, and never shared between
            drafts — see the module docstring on determinism.
        capture_rationale: Record the full reasoning for each of the user's
            picks. Off during the Monte Carlo, because ten thousand drafts of
            rationale is a great deal of memory to build a median from, and on
            for the single representative draft that is replayed for display.
        survival_by_pick: Survival probabilities already flattened to a list per
            player index, keyed by the seat's own pick numbers. A pure
            optimisation — :func:`survival_table` builds it once per seat rather
            than once per draft, and it is derived from ``availability`` alone,
            so omitting it changes the timing and nothing else.

    Returns:
        The seat's roster and its value.
    """
    settings = context.settings
    positions = context.positions
    players = context.players
    if survival_by_pick is None:
        survival_by_pick = survival_table(
            context, availability, context.order.picks_for(draft_position)
        )

    available = list(range(len(players)))
    counts: list[dict[str, int]] = [{} for _ in range(settings.teams + 1)]
    roster: list[DraftPlayer] = []
    picks: list[SimulatedPick] = []

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

        picks_remaining = settings.rounds - len(roster)
        choice = _user_choice(
            context,
            available,
            roster,
            availability=availability,
            survival_by_pick=survival_by_pick,
            picks_remaining=picks_remaining,
            overall=slot.overall,
            draft_position=draft_position,
            capture_rationale=capture_rationale,
            strategy=strategy,
            rng=rng,
        )
        if choice is None:
            continue
        at, rationale = choice
        index = available.pop(at)
        player = players[index]
        roster.append(player)
        held[player.position] = held.get(player.position, 0) + 1
        picks.append(
            SimulatedPick(
                overall=slot.overall,
                round_number=slot.round_number,
                player_id=player.player_id,
                name=player.name,
                position=player.position,
                team=player.team,
                season_value=player.season_value,
                projected_points_per_game=player.projected_points_per_game,
                expected_games=player.expected_games,
                value_over_replacement=value_over_replacement(player, context.levels),
                rationale=rationale,
            )
        )

    starters, starter_points, roster_value = evaluate_roster(roster, context)
    bench_value = sum(
        value_over_replacement(p, context.levels)
        for p in roster
        if p.player_id not in starters
    )
    return SimulatedDraft(
        picks=tuple(picks),
        roster_value=roster_value,
        starter_points=starter_points,
        bench_value=bench_value,
        starters=starters,
    )


def survival_table(
    context: DraftContext,
    availability: AvailabilityModel,
    picks: Sequence[int],
) -> dict[int, tuple[float, ...]]:
    """Flatten the survival curves to one list per player index, per seat pick.

    A seat has at most twenty-five picks and the pool has a few hundred players,
    so this is a few thousand floats built once and read by every simulation.
    Reading ``availability.survival[player_id][pick]`` inside the loop instead is
    a dict lookup and a tuple index per candidate per pick per draft, which at
    ten thousand drafts is tens of millions of hash lookups for numbers that
    never change.
    """
    table: dict[int, tuple[float, ...]] = {}
    for pick in picks:
        table[pick] = tuple(
            availability.probability_available(player.player_id, pick)
            for player in context.players
        )
    return table


def _user_choice(
    context: DraftContext,
    available: Sequence[int],
    roster: Sequence[DraftPlayer],
    *,
    availability: AvailabilityModel,
    survival_by_pick: Mapping[int, Sequence[float]],
    picks_remaining: int,
    overall: int,
    draft_position: int,
    capture_rationale: bool,
    strategy: str = "value_over_next_available",
    rng: random.Random | None = None,
) -> tuple[int, PickRationale | None] | None:
    """Offset into ``available`` of the user's selection, and why.

    Three things are computed **once per pick** rather than once per candidate,
    and together they are the difference between the engine being usable at ten
    thousand simulations and not:

    * the expected value of waiting, which depends only on the position;
    * the bench weight, which depends only on the roster and the position;
    * the positional scarcity, which is needed only when a rationale is being
      captured — that is, on one draft out of every batch.
    """
    settings = context.settings
    players = context.players
    positions = context.positions
    values = context.values
    replacement = context.replacement

    needs = roster_needs(roster, settings, picks_remaining)
    next_pick = context.order.next_pick_after(draft_position, overall)
    survival = survival_by_pick.get(next_pick) if next_pick is not None else None

    horizon = available[:LOOKAHEAD_HORIZON]
    by_position: dict[str, list[int]] = {}
    for index in horizon:
        by_position.setdefault(positions[index], []).append(index)

    # Once the draft is short enough that every remaining pick is needed to
    # complete a legal lineup, the engine stops optimising and starts
    # satisfying. A roster that finishes without a quarterback is not a roster,
    # and comparing seats whose lineups are illegal compares nothing.
    required_positions: set[str] | None = None
    if needs.must_fill_starters and needs.open_starters > 0:
        required_positions = set(needs.open_dedicated)
        if needs.open_flex > 0:
            required_positions |= {
                position
                for position in by_position
                if flex_eligible(position, settings)
            }

    next_best: dict[str, tuple[float, int | None]] = {}
    for position, indices in by_position.items():
        next_best[position] = _expected_best(indices, values, survival)

    # Everything that varies by position but not by candidate, computed once.
    # The loop below scores up to sixty candidates and each of these would
    # otherwise be rebuilt for every one of them.
    held_counts: dict[str, int] = {}
    weakest_held: dict[str, float] = {}
    for player in roster:
        position = player.position
        held_counts[position] = held_counts.get(position, 0) + 1
        current = weakest_held.get(position)
        if current is None or player.season_value < current:
            weakest_held[position] = player.season_value

    bench_weights = {
        position: bench_weight(roster, position, context.season_games)
        for position in by_position
    }
    open_dedicated = needs.open_dedicated
    open_flex = needs.open_flex

    best_at: int | None = None
    best_score = -math.inf
    best_detail: tuple[int, float, str, float, int | None] | None = None
    runner_up: tuple[int, float] | None = None

    considered = 0
    for at in range(len(available)):
        if considered >= USER_HORIZON:
            break
        index = available[at]
        position = positions[index]

        cap = context.depth_cap.get(position)
        if cap is not None and held_counts.get(position, 0) >= cap:
            continue
        if required_positions is not None and position not in required_positions:
            continue
        considered += 1

        floor = replacement.get(position, 0.0)
        value, slot = marginal_value_of(
            season_value=values[index],
            surplus=values[index] - floor,
            open_dedicated=open_dedicated.get(position, 0),
            open_flex=open_flex,
            flex_eligible=position in context.flex_positions,
            bench_weight=bench_weights.get(position, 0.0),
            weakest_held_value=weakest_held.get(position),
        )
        expected_later, later_index = next_best.get(position, (0.0, None))

        if strategy == "value_over_next_available":
            # The lookahead is in season-value units; the marginal value is a
            # surplus over replacement. Subtracting the replacement level from
            # the expectation puts both on the same scale before differencing.
            score = value - max(0.0, expected_later - floor)
        elif strategy == "highest_season_value":
            score = values[index]
        elif strategy == "highest_points_per_game":
            score = players[index].projected_points_per_game
        elif strategy == "random":
            # A uniform draw per legal candidate, so the winner is uniform over
            # them. Drawn from the draft's own generator, which makes the random
            # baseline as reproducible as the strategy it is a control for.
            score = rng.random() if rng is not None else 0.0
        else:
            raise ValueError(
                f"unknown draft strategy {strategy!r}; expected one of "
                f"{list(STRATEGIES)}"
            )

        if score > best_score:
            if best_detail is not None:
                runner_up = (best_detail[0], best_score)
            best_score = score
            best_at = at
            best_detail = (index, value, slot, expected_later, later_index)
        elif runner_up is None or score > runner_up[1]:
            runner_up = (index, score)

    if best_at is None or best_detail is None:
        # Nothing inside the horizon was both legal and eligible — late in a
        # deep draft every top-scoring candidate can be capped out at its
        # position, and when the lineup must be completed the eligible set can
        # be empty inside the window. The seat still picks: forfeiting would
        # leave it short of a legal lineup and make its roster incomparable to
        # every other seat's, which is the one thing the comparison cannot
        # survive.
        if not available:
            return None
        # Completing the lineup comes first: scan the *whole* board for a
        # position that is still required before relaxing anything else. Only
        # when no such player exists anywhere does the depth cap give way.
        if required_positions:
            for at, index in enumerate(available):
                if positions[index] in required_positions:
                    return at, None
        return (
            _relaxed_choice(available, positions, context.depth_cap, held_counts),
            None,
        )

    rationale = None
    if capture_rationale:
        index, value, slot, expected_later, later_index = best_detail
        player = players[index]
        tier = context.tier_of(player)
        remaining = None
        if tier is not None:
            live = {players[i].player_id for i in by_position.get(player.position, ())}
            remaining = sum(1 for pid in tier.player_ids if pid in live)
        scarcity = positional_scarcity(
            [players[i] for i in horizon], context.levels
        )
        rationale = PickRationale(
            marginal_value=value,
            slot=slot,
            survival_at_next_pick=(
                survival[index] if survival is not None else 0.0
            ),
            expected_next_best_value=expected_later,
            value_over_next_available=best_score,
            next_best_player_id=(
                players[later_index].player_id if later_index is not None else None
            ),
            next_best_player_name=(
                players[later_index].name if later_index is not None else None
            ),
            next_pick_overall=next_pick,
            scarcity=scarcity.get(player.position, 0.0),
            tier_index=tier.index if tier else None,
            tier_size=tier.size if tier else None,
            tier_remaining=remaining,
            runner_up_id=players[runner_up[0]].player_id if runner_up else None,
            runner_up_name=players[runner_up[0]].name if runner_up else None,
            runner_up_margin=(best_score - runner_up[1]) if runner_up else None,
        )

    return best_at, rationale


def _expected_best(
    indices: Sequence[int],
    values: Sequence[float],
    survival: Sequence[float] | None,
) -> tuple[float, int | None]:
    """Index-based form of :func:`~nflfp.services.draft.valuation.expected_best_available`.

    Identical mathematics — the order statistic over the survival probabilities
    — expressed over parallel arrays rather than dataclasses so it can run in
    the inner loop. The dataclass form is kept as the readable definition and is
    what the unit tests exercise; a test asserts the two agree.

    ``indices`` arrives already ordered by consensus, not by value, so it is
    sorted here. The list is at most a few dozen entries per position.
    """
    if survival is None or not indices:
        return 0.0, None

    ordered = sorted(indices, key=lambda i: -values[i])
    expected = 0.0
    gone = 1.0
    best_term = 0.0
    best_index: int | None = None

    for index in ordered:
        probability = survival[index]
        term = gone * probability
        expected += term * values[index]
        if term > best_term:
            best_term = term
            best_index = index
        gone *= 1.0 - probability
        if gone < 1e-6:
            break

    return expected, best_index


def evaluate_roster(
    roster: Sequence[DraftPlayer], context: DraftContext
) -> tuple[tuple[str, ...], float, float]:
    """Assign a roster to its starting slots and score it.

    Greedy is exact here, not an approximation: the flex slot accepts a superset
    of every dedicated slot's positions, so filling dedicated slots first with
    the best player at each position can never strand a better flex option than
    it gained. With a slot vocabulary whose eligibility sets overlapped
    partially this would need an assignment algorithm, and
    :mod:`~nflfp.services.lineup` is where such a slot would be declared.

    Returns:
        ``(starter_ids, starter_points, starter_value_over_replacement)``.
    """
    settings = context.settings
    remaining = sorted(roster, key=lambda p: -p.season_value)
    starters: list[DraftPlayer] = []

    for requirement in settings.roster:
        if requirement.slot == "FLEX":
            continue
        chosen = 0
        for player in list(remaining):
            if chosen >= requirement.count:
                break
            if player.position == requirement.slot:
                starters.append(player)
                remaining.remove(player)
                chosen += 1

    flex_required = settings.required("FLEX")
    chosen = 0
    for player in list(remaining):
        if chosen >= flex_required:
            break
        if flex_eligible(player.position, settings):
            starters.append(player)
            remaining.remove(player)
            chosen += 1

    points = sum(player.season_value for player in starters)
    value = sum(value_over_replacement(player, context.levels) for player in starters)
    return tuple(player.player_id for player in starters), points, value
