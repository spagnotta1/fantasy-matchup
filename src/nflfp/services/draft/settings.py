"""A league's draft configuration, and what makes one incoherent.

This is the draft counterpart to :mod:`nflfp.services.lineup`, and it borrows
that module's two-level split deliberately: :class:`RosterRequirement` reuses
:class:`~nflfp.services.lineup.LineupSlot` for eligibility rather than restating
"a FLEX takes RB, WR or TE". A superflex league is a different set of
requirements, not a different meaning of FLEX, and the moment a kicker model
ships ``K`` becomes draftable here with no edit to this file.

Validation is pure and runs before any database round-trip, for the same reason
lineup validation does: a fifteen-round draft for a roster needing seventeen
players is rejectable without knowing what season it is, and spending a query to
resolve a window we are about to discard is slower and, when Postgres is down, a
500 where a 422 was correct.

Two constraints are worth explaining rather than only enforcing.

**Rounds must cover the starting requirement.** A draft too short to fill the
lineup produces rosters that cannot be compared to each other — the simulation
would be answering "which seat drafts the best eleven of the thirteen players it
needs", which is not the question. So the floor is the starter count, and
anything above it is bench.

**The pool must be able to fill every seat.** ``teams x rounds`` players get
drafted. If the projected pool is smaller than that, the last rounds draft
nobody and every seat's roster value is understated by a different amount
depending on where its late picks fell. That is checked against the real pool in
:mod:`~nflfp.services.draft.pool`, not here, because it needs one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from ..errors import InvalidRequest
from ..lineup import LineupSlot, slot as lookup_slot
from ..positions import describe

#: League sizes a draft may be configured for. Four is the smallest that makes a
#: snake ordering meaningful; twenty is past the point where the player pool
#: supports a fifteen-round draft at every seat.
MIN_TEAMS = 4
MAX_TEAMS = 20

#: Rounds a draft may run. The ceiling is a guard on simulation cost, not a
#: league rule: teams x rounds x simulations is the engine's inner loop.
MIN_ROUNDS = 1
MAX_ROUNDS = 25

#: Simulated drafts a request may ask for. The floor is where the availability
#: percentages stop being noise; the ceiling is a CPU budget, and
#: :mod:`~nflfp.services.draft.service` reports the wall time it actually took.
MIN_SIMULATIONS = 50
MAX_SIMULATIONS = 10_000
DEFAULT_SIMULATIONS = 1_000

#: Used when a caller names no seed. Fixed rather than entropy, so an unseeded
#: request is still reproducible and a user refreshing the page sees the same
#: draft — the same contract :mod:`nflfp.services.simulation` makes.
DEFAULT_SEED = 20260101

#: Bounds on the opponent model's two assumed parameters. They are exposed as
#: request fields precisely because they are assumptions — a conclusion that
#: survives moving them is worth more than one that does not — and bounded
#: because the extremes are not opinions but broken models: zero noise makes
#: every simulated draft identical and every availability percentage 0 or 100,
#: and a history weight of 1 makes the opposing managers ignore projections
#: entirely.
CONSENSUS_BOUNDS: dict[str, tuple[float, float]] = {
    "history_weight": (0.0, 0.8),
    "noise": (0.05, 1.5),
}

#: Draft formats. ``snake`` reverses each round; ``linear`` does not. Linear is
#: included because it is a real league setting and because it is the control
#: case that makes the seat-comparison chart interpretable — under a linear
#: draft seat 1 should dominate, and a comparison that does not show that has a
#: bug in its ordering.
DRAFT_FORMATS: tuple[str, ...] = ("snake", "linear")


@dataclass(frozen=True)
class RosterRequirement:
    """How many of one slot a league starts.

    ``slot`` is a code from :data:`~nflfp.services.lineup.LINEUP_SLOTS`; the
    eligibility behind it is read from there rather than repeated.
    """

    slot: str
    count: int

    @property
    def definition(self) -> LineupSlot | None:
        return lookup_slot(self.slot)

    def accepts(self, position: str | None) -> bool:
        definition = self.definition
        return definition is not None and definition.accepts(position)


#: The shape the product opens on: a conventional 1QB/2RB/2WR/1TE/1FLEX league.
#: Kickers and defences are absent, not forgotten — see
#: :func:`validate_settings`.
DEFAULT_ROSTER: tuple[RosterRequirement, ...] = (
    RosterRequirement("QB", 1),
    RosterRequirement("RB", 2),
    RosterRequirement("WR", 2),
    RosterRequirement("TE", 1),
    RosterRequirement("FLEX", 1),
)


@dataclass(frozen=True)
class DraftSettings:
    """Everything about a league that changes what the draft looks like.

    Attributes:
        teams: Managers in the league.
        rounds: Picks each manager makes.
        roster: Starting-lineup requirements. Bench depth is
            ``rounds - starters`` and is not enumerated, because a bench slot
            imposes no eligibility constraint.
        scoring_profile: Resolved league format. Set by the service layer from
            :func:`~nflfp.services.catalog.resolve_scoring_profile`, never
            defaulted here — this module must not know what the deployment's
            default format is.
        draft_format: ``"snake"`` or ``"linear"``.
        season: The season being drafted for.
        simulations: Monte Carlo draft count.
        seed: Reproducibility seed.
    """

    teams: int
    rounds: int
    scoring_profile: str
    season: int
    roster: tuple[RosterRequirement, ...] = DEFAULT_ROSTER
    draft_format: str = "snake"
    simulations: int = DEFAULT_SIMULATIONS
    seed: int = DEFAULT_SEED

    @property
    def starters(self) -> int:
        """Players a legal starting lineup holds."""
        return sum(requirement.count for requirement in self.roster)

    @property
    def bench(self) -> int:
        """Rounds beyond the starting requirement."""
        return self.rounds - self.starters

    @property
    def total_picks(self) -> int:
        return self.teams * self.rounds

    @property
    def is_snake(self) -> bool:
        return self.draft_format == "snake"

    def required(self, slot_code: str) -> int:
        for requirement in self.roster:
            if requirement.slot == slot_code:
                return requirement.count
        return 0

    @property
    def draftable_positions(self) -> tuple[str, ...]:
        """Positions any slot in this roster accepts, deduplicated and ordered.

        Derived from the slot registry, so a league that starts no tight end
        still lists TE — the FLEX accepts one, and a draft that refused to
        consider tight ends because no TE slot exists would be wrong.
        """
        seen: list[str] = []
        for requirement in self.roster:
            definition = requirement.definition
            if definition is None:
                continue
            for position in definition.eligible_positions:
                if position not in seen:
                    seen.append(position)
        return tuple(seen)


def validate_settings(
    *,
    teams: int,
    rounds: int,
    scoring_profile: str,
    season: int,
    roster: Sequence[object] | None = None,
    draft_format: str = "snake",
    simulations: int = DEFAULT_SIMULATIONS,
    seed: int | None = None,
) -> DraftSettings:
    """Build a validated :class:`DraftSettings`, or explain the refusal.

    Args:
        teams: League size.
        rounds: Rounds in the draft.
        scoring_profile: Already-resolved league format.
        season: Season being drafted.
        roster: Slot requirements as ``{"slot": str, "count": int}`` mappings or
            :class:`RosterRequirement` instances. ``None`` uses
            :data:`DEFAULT_ROSTER`.
        draft_format: ``"snake"`` or ``"linear"``.
        simulations: Monte Carlo count.
        seed: Reproducibility seed; ``None`` uses :data:`DEFAULT_SEED`.

    Returns:
        The validated settings.

    Raises:
        InvalidRequest: with the field at fault. Unprojected slots are refused
            with the reason and blockers from the position registry rather than
            with "unknown slot", because a kicker slot is not a typo — it is a
            model this engine does not have.
    """
    if not MIN_TEAMS <= teams <= MAX_TEAMS:
        raise InvalidRequest(
            f"teams must be between {MIN_TEAMS} and {MAX_TEAMS}, got {teams}",
            field="teams",
        )
    if not MIN_ROUNDS <= rounds <= MAX_ROUNDS:
        raise InvalidRequest(
            f"rounds must be between {MIN_ROUNDS} and {MAX_ROUNDS}, got {rounds}",
            field="rounds",
        )
    if draft_format not in DRAFT_FORMATS:
        raise InvalidRequest(
            f"unknown draft_format {draft_format!r}; expected one of "
            f"{list(DRAFT_FORMATS)}",
            field="draft_format",
        )
    if not MIN_SIMULATIONS <= simulations <= MAX_SIMULATIONS:
        raise InvalidRequest(
            f"simulations must be between {MIN_SIMULATIONS} and "
            f"{MAX_SIMULATIONS}, got {simulations}",
            field="simulations",
        )

    requirements = _normalise_roster(roster)
    starters = sum(requirement.count for requirement in requirements)
    if rounds < starters:
        raise InvalidRequest(
            f"a {rounds}-round draft cannot fill a {starters}-player starting "
            "lineup. Rosters from a draft too short to start a legal lineup are "
            "not comparable to each other, so this is refused rather than "
            "simulated.",
            field="rounds",
        )

    return DraftSettings(
        teams=int(teams),
        rounds=int(rounds),
        scoring_profile=scoring_profile,
        season=int(season),
        roster=requirements,
        draft_format=draft_format,
        simulations=int(simulations),
        seed=DEFAULT_SEED if seed is None else int(seed),
    )


def validate_draft_position(position: int, settings: DraftSettings) -> int:
    """Check a seat number against the league size."""
    if not 1 <= position <= settings.teams:
        raise InvalidRequest(
            f"draft_position must be between 1 and {settings.teams} for a "
            f"{settings.teams}-team league, got {position}",
            field="draft_position",
        )
    return int(position)


def _normalise_roster(roster: Sequence[object] | None) -> tuple[RosterRequirement, ...]:
    """Coerce, validate and order a roster specification.

    Ordering follows :data:`~nflfp.services.lineup.LINEUP_SLOTS` rather than the
    request, so two callers who list the same slots in a different order produce
    the same settings — and therefore the same cache key and the same seeded
    draft.
    """
    if roster is None:
        return DEFAULT_ROSTER

    parsed: dict[str, int] = {}
    for entry in roster:
        code, count = _unpack(entry)

        definition = lookup_slot(code)
        if definition is None:
            raise InvalidRequest(
                f"unknown roster slot {code!r}; known slots are "
                f"{list(_known_slots())}",
                field="roster",
            )
        if count < 0:
            raise InvalidRequest(
                f"roster slot {code} cannot have a negative count", field="roster"
            )
        if count == 0:
            continue

        unsupported = definition.unsupported_positions
        if unsupported:
            support = describe(unsupported[0])
            detail = ""
            if support is not None:
                detail = (
                    f" {support.reason} Blocked on: "
                    + "; ".join(support.blocked_on)
                    + "."
                )
            raise InvalidRequest(
                f"roster slot {definition.slot} ({definition.label}) cannot be "
                "drafted: this engine publishes no projection for "
                f"{', '.join(unsupported)}, and drafting a position with no "
                "projected value would put an invented number into every roster "
                "total." + detail + " Configure a roster without this slot, or "
                "see /meta/positions for what it is blocked on.",
                field="roster",
            )

        parsed[definition.slot] = parsed.get(definition.slot, 0) + count

    if not parsed:
        raise InvalidRequest(
            "a roster must require at least one starting slot", field="roster"
        )

    ordered = tuple(
        RosterRequirement(code, parsed[code]) for code in _known_slots() if code in parsed
    )
    total = sum(requirement.count for requirement in ordered)
    if total > MAX_ROUNDS:
        raise InvalidRequest(
            f"a starting lineup of {total} players exceeds the {MAX_ROUNDS}-round "
            "maximum, so no legal draft could fill it",
            field="roster",
        )
    return ordered


def _unpack(entry: object) -> tuple[str, int]:
    """Read one roster entry from a mapping, a dataclass or a pair."""
    if isinstance(entry, RosterRequirement):
        return entry.slot, entry.count
    if isinstance(entry, dict):
        raw_slot = entry.get("slot")
        raw_count = entry.get("count")
    else:
        raw_slot = getattr(entry, "slot", None)
        raw_count = getattr(entry, "count", None)

    if raw_slot is None or raw_count is None:
        raise InvalidRequest(
            "each roster entry needs a 'slot' and a 'count'", field="roster"
        )
    try:
        count = int(raw_count)
    except (TypeError, ValueError):
        raise InvalidRequest(
            f"roster slot {raw_slot!r} has a non-numeric count {raw_count!r}",
            field="roster",
        ) from None
    return str(raw_slot).strip().upper(), count


def _known_slots() -> tuple[str, ...]:
    from ..lineup import KNOWN_SLOTS

    return KNOWN_SLOTS


@dataclass(frozen=True)
class DraftLimits:
    """Bounds a client builds its configuration form from.

    Served by ``GET /mock-draft/config`` so the form's own validation and the
    server's cannot drift apart, which is the same reason ``/meta/positions``
    exists.
    """

    min_teams: int = MIN_TEAMS
    max_teams: int = MAX_TEAMS
    min_rounds: int = MIN_ROUNDS
    max_rounds: int = MAX_ROUNDS
    min_simulations: int = MIN_SIMULATIONS
    max_simulations: int = MAX_SIMULATIONS
    default_simulations: int = DEFAULT_SIMULATIONS
    default_seed: int = DEFAULT_SEED
    draft_formats: tuple[str, ...] = DRAFT_FORMATS
    default_roster: tuple[RosterRequirement, ...] = field(default=DEFAULT_ROSTER)
