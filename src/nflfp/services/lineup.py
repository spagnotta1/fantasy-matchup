"""Fantasy lineup slots: the vocabulary, and what a legal lineup looks like.

Why this is a registry and not a set of ``if`` statements
--------------------------------------------------------
"Can a tight end go in the FLEX?" is a league-rules question that a simulation
engine, a request validator, an API schema and a future roster editor all need
the same answer to. Written inline, it becomes four answers that agree until the
first superflex league arrives. So the rules live here as data, exactly as
:mod:`nflfp.services.positions` holds the answer to "is this position
projected?", and every consumer reads them rather than restating them.

Two levels, deliberately separated
----------------------------------
:class:`LineupSlot` is the **vocabulary**: what a slot is called and which
positions may fill it. :class:`LineupFormat` is a **league's shape**: how many
of each slot a starting lineup has. Keeping them apart is what makes a
superflex league a new :class:`LineupFormat` rather than an edit to the meaning
of FLEX, and what makes adding a slot (``OP``, ``WR/TE``) a new
:class:`LineupSlot` that every existing format ignores.

Unsupported slots are declared, not omitted
-------------------------------------------
K and DST are in :data:`LINEUP_SLOTS`. They are recognised slots in every real
fantasy league, and leaving them out would make a request naming one fail with
"unknown slot 'K'" — an answer that reads like a typo when the truth is that the
engine has no kicker model. Their eligibility points at positions the projection
layer declares as ``planned``, and :func:`validate_structure` refuses them with
the reason and the blockers :data:`~nflfp.services.positions.POSITION_SUPPORT`
already carries.

That is also the extension path, and it is mechanical: ship a kicker model, flip
``K`` to ``projected`` in the position registry, add it to
:data:`STANDARD_FORMAT`, and nothing in this module, the simulation engine, the
router or the schema changes.

Validation happens in two passes
--------------------------------
:func:`validate_structure` is **pure and local** — slot names, counts,
duplicates, unsupported slots. It runs before any database round-trip, because a
request naming two quarterbacks is rejectable without knowing what week it is,
and spending a query to resolve a window we are about to discard is both slower
and, when the database is down, a 500 where a 422 was correct.

:func:`validate_eligibility` is the second pass and needs the player dimension,
because "is this player eligible for FLEX?" cannot be answered from a player id.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from .errors import InvalidRequest
from .positions import KNOWN_POSITIONS, describe

# ---------------------------------------------------------------------------
# The vocabulary
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LineupSlot:
    """One roster slot and the positions that may fill it.

    Attributes:
        slot: The code a request carries, e.g. ``"FLEX"``. Uppercase.
        label: What a user sees.
        eligible_positions: Positions permitted in this slot, in the order they
            should be listed to a user. A single-position slot names one; FLEX
            names three.
        description: Why the slot exists, for the capability endpoint.
    """

    slot: str
    label: str
    eligible_positions: tuple[str, ...]
    description: str = ""

    def accepts(self, position: str | None) -> bool:
        """Whether a player at ``position`` may fill this slot."""
        if position is None:
            return False
        return position.strip().upper() in self.eligible_positions

    @property
    def is_supported(self) -> bool:
        """Every position this slot accepts has a published projection model.

        Derived from the position registry rather than stated here, so a slot
        cannot claim to be supported after the position behind it is withdrawn,
        and becomes supported on its own the day a model ships.
        """
        return all(
            (support := describe(position)) is not None and support.is_projected
            for position in self.eligible_positions
        )

    @property
    def unsupported_positions(self) -> tuple[str, ...]:
        """The positions in this slot that are not projected, in order."""
        return tuple(
            position
            for position in self.eligible_positions
            if (support := describe(position)) is None or not support.is_projected
        )


#: Every slot the application recognises. The single source of truth for slot
#: eligibility; nothing else in the codebase may spell out "RB, WR or TE".
LINEUP_SLOTS: tuple[LineupSlot, ...] = (
    LineupSlot("QB", "Quarterback", ("QB",), "One quarterback."),
    LineupSlot("RB", "Running Back", ("RB",), "One running back."),
    LineupSlot("WR", "Wide Receiver", ("WR",), "One wide receiver."),
    LineupSlot("TE", "Tight End", ("TE",), "One tight end."),
    LineupSlot(
        "FLEX",
        "Flex",
        ("RB", "WR", "TE"),
        "A running back, wide receiver or tight end. Quarterbacks are excluded; "
        "a format that admits one is a superflex league and is a separate "
        "LineupFormat rather than a change to this slot.",
    ),
    # Recognised, deliberately unfillable. See the module docstring: refusing
    # these with "unknown slot" would misrepresent a missing model as a typo.
    LineupSlot(
        "K",
        "Kicker",
        ("K",),
        "Recognised but not simulable: no kicker model exists. See "
        "/meta/positions for what it is blocked on.",
    ),
    LineupSlot(
        "DST",
        "Team Defense",
        ("DST",),
        "Recognised but not simulable: no team-defence model exists. See "
        "/meta/positions for what it is blocked on.",
    ),
)

_BY_SLOT: dict[str, LineupSlot] = {entry.slot: entry for entry in LINEUP_SLOTS}

#: Slots a lineup may actually be built from today. Derived, never listed twice.
SUPPORTED_SLOTS: tuple[str, ...] = tuple(
    entry.slot for entry in LINEUP_SLOTS if entry.is_supported
)

#: Everything the vocabulary recognises, supported or not.
KNOWN_SLOTS: tuple[str, ...] = tuple(entry.slot for entry in LINEUP_SLOTS)


def slot(code: str) -> LineupSlot | None:
    """Look up a slot, or ``None`` if the code is not recognised."""
    return _BY_SLOT.get(code.strip().upper())


# ---------------------------------------------------------------------------
# A league's shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SlotRequirement:
    """How many of one slot a format starts."""

    slot: str
    count: int


@dataclass(frozen=True)
class LineupFormat:
    """The starting lineup a league requires.

    Counts are exact rather than a range. A simulation compares two team
    *totals*, and two lineups of different sizes do not produce comparable
    totals — a nine-player roster beats an eight-player roster for reasons that
    have nothing to do with the players in it.
    """

    name: str
    label: str
    requirements: tuple[SlotRequirement, ...]
    description: str = ""

    @property
    def size(self) -> int:
        """Players a legal lineup holds."""
        return sum(requirement.count for requirement in self.requirements)

    @property
    def slots(self) -> tuple[str, ...]:
        return tuple(requirement.slot for requirement in self.requirements)

    def required(self, slot_code: str) -> int:
        for requirement in self.requirements:
            if requirement.slot == slot_code:
                return requirement.count
        return 0


#: The format Phase 6A simulates: the projectable subset of a standard lineup.
#:
#: A real league also starts a K and a DST. They are **absent by construction**,
#: not forgotten — including them would require inventing two distributions the
#: platform has never measured, and the honest alternative is a format that says
#: what it covers. :data:`nflfp.services.simulation.MatchupSimulation` carries
#: the disclosure to the response.
STANDARD_FORMAT = LineupFormat(
    name="standard_skill",
    label="Standard skill lineup (QB/RB/RB/WR/WR/TE/FLEX)",
    requirements=(
        SlotRequirement("QB", 1),
        SlotRequirement("RB", 2),
        SlotRequirement("WR", 2),
        SlotRequirement("TE", 1),
        SlotRequirement("FLEX", 1),
    ),
    description=(
        "The projectable positions of a standard lineup. A real league also "
        "starts a kicker and a team defence; neither is projected, so neither "
        "is in this format and any score produced from it covers seven of a "
        "typical nine starters."
    ),
)

#: Formats a caller may name. One today; the tuple exists so adding superflex
#: is a data change and so the capability endpoint has something to serve.
LINEUP_FORMATS: tuple[LineupFormat, ...] = (STANDARD_FORMAT,)

_BY_FORMAT = {entry.name: entry for entry in LINEUP_FORMATS}


def lineup_format(name: str | None) -> LineupFormat:
    """Resolve a format by name, defaulting to :data:`STANDARD_FORMAT`."""
    if name is None:
        return STANDARD_FORMAT
    found = _BY_FORMAT.get(name.strip().lower())
    if found is None:
        raise InvalidRequest(
            f"unknown lineup format {name!r}; known formats are "
            f"{list(_BY_FORMAT)}",
            field="lineup_format",
        )
    return found


# ---------------------------------------------------------------------------
# A submitted lineup
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LineupEntry:
    """One player assigned to one slot, as submitted."""

    player_id: str
    slot: str


@dataclass(frozen=True)
class Lineup:
    """A structurally valid lineup, before the player dimension is consulted.

    "Structurally valid" is the honest name: the slots are legal and complete
    and the ids are distinct, but nothing here knows whether the player in the
    TE slot is a tight end. That takes a query, and
    :func:`validate_eligibility` is where it is checked.
    """

    side: str
    entries: tuple[LineupEntry, ...]
    format: LineupFormat

    @property
    def player_ids(self) -> tuple[str, ...]:
        return tuple(entry.player_id for entry in self.entries)

    def slot_of(self, player_id: str) -> str | None:
        for entry in self.entries:
            if entry.player_id == player_id:
                return entry.slot
        return None


def validate_structure(
    entries: Iterable[Mapping[str, object] | LineupEntry],
    *,
    side: str,
    format: LineupFormat = STANDARD_FORMAT,
) -> Lineup:
    """Check everything about a lineup that needs no database.

    Args:
        entries: The submitted lineup. Each item is a :class:`LineupEntry` or a
            mapping with ``player_id`` and ``slot`` keys.
        side: ``"team_a"`` or ``"team_b"``. Used only to say *which* lineup is
            wrong, which is the first thing a caller with two of them needs.
        format: The league shape to check against.

    Returns:
        The normalised lineup.

    Raises:
        InvalidRequest: for an unknown slot, an unsupported slot (K, DST), a
            blank or duplicated player id, or a slot count that does not match
            the format. The message always names the side.
    """
    normalised: list[LineupEntry] = []
    seen: set[str] = set()

    for index, raw in enumerate(entries):
        if isinstance(raw, LineupEntry):
            player_id, slot_code = raw.player_id, raw.slot
        else:
            player_id = str(raw.get("player_id") or "")
            slot_code = str(raw.get("slot") or "")

        player_id = player_id.strip()
        if not player_id:
            raise InvalidRequest(
                f"{side}[{index}] has no player id", field=f"{side}.player_id"
            )

        entry_slot = slot(slot_code)
        if entry_slot is None:
            raise InvalidRequest(
                f"{side}[{index}] names an unknown slot {slot_code!r}; known "
                f"slots are {list(KNOWN_SLOTS)}",
                field=f"{side}.slot",
            )

        if not entry_slot.is_supported:
            raise InvalidRequest(
                _unsupported_slot_message(side, entry_slot), field=f"{side}.slot"
            )

        if player_id in seen:
            # A player cannot start twice. Collapsing the duplicate would be
            # worse than refusing it: the lineup would silently lose a slot and
            # the team total would come out a starter light with no signal.
            raise InvalidRequest(
                f"{side} names player {player_id} more than once; a player "
                "cannot fill two slots",
                field=f"{side}.player_id",
            )
        seen.add(player_id)

        normalised.append(LineupEntry(player_id=player_id, slot=entry_slot.slot))

    _check_counts(normalised, side=side, format=format)
    return Lineup(side=side, entries=tuple(normalised), format=format)


def _check_counts(
    entries: Sequence[LineupEntry], *, side: str, format: LineupFormat
) -> None:
    """Every slot in the format is filled exactly the required number of times."""
    counted: dict[str, int] = {}
    for entry in entries:
        counted[entry.slot] = counted.get(entry.slot, 0) + 1

    for requirement in format.requirements:
        found = counted.pop(requirement.slot, 0)
        if found != requirement.count:
            raise InvalidRequest(
                f"{side} must start exactly {requirement.count} "
                f"{requirement.slot} slot(s), found {found}. The "
                f"{format.label} requires "
                + ", ".join(
                    f"{r.count}x{r.slot}" for r in format.requirements
                )
                + ".",
                field=f"{side}.slot",
            )

    if counted:
        extra = sorted(counted)
        raise InvalidRequest(
            f"{side} names slot(s) {extra} that the {format.label} does not "
            f"start; it requires "
            + ", ".join(f"{r.count}x{r.slot}" for r in format.requirements)
            + ".",
            field=f"{side}.slot",
        )


def _unsupported_slot_message(side: str, entry_slot: LineupSlot) -> str:
    """Explain a recognised-but-unfillable slot using the position registry.

    The reason and the blockers are read from
    :data:`~nflfp.services.positions.POSITION_SUPPORT` rather than restated, so
    the answer to "why can't I simulate my kicker?" is the same sentence the
    projections endpoint gives and cannot drift from it.
    """
    parts = [
        f"{side} names the {entry_slot.label} ({entry_slot.slot}) slot, which "
        f"this engine cannot simulate."
    ]
    for position in entry_slot.unsupported_positions:
        support = describe(position)
        if support is None:
            parts.append(
                f"{position} is not a fantasy-scoring position this engine "
                f"recognises; known positions are {list(KNOWN_POSITIONS)}."
            )
            continue
        parts.append(
            f"{support.label} ({support.position}) is recognised but not "
            f"projected. {support.reason} Blocked on: "
            + "; ".join(support.blocked_on)
            + "."
        )
    parts.append(
        "Simulate the projectable slots "
        f"({', '.join(SUPPORTED_SLOTS)}) and add the missing positions by hand, "
        "or drop them from both lineups so the comparison stays symmetric."
    )
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Eligibility, once positions are known
# ---------------------------------------------------------------------------


def validate_eligibility(
    lineup: Lineup, positions_by_player: Mapping[str, str | None]
) -> None:
    """Check each player is eligible for the slot they were assigned.

    Args:
        lineup: A structurally valid lineup.
        positions_by_player: Player id to position, from the projection or the
            player dimension. A missing key is treated as an unknown position
            and refused — the caller is expected to have resolved availability
            already, and guessing here would put a kicker in a FLEX.

    Raises:
        InvalidRequest: naming the player, their position, the slot and what
            the slot accepts. All four, because "invalid FLEX" without them
            sends the user to trial and error.
    """
    for entry in lineup.entries:
        entry_slot = _BY_SLOT[entry.slot]
        position = positions_by_player.get(entry.player_id)
        normalised = position.strip().upper() if position else None

        if entry_slot.accepts(normalised):
            continue

        support = describe(normalised) if normalised else None
        if support is not None and not support.is_projected:
            # A kicker submitted in a FLEX. Refused for the same reason as a K
            # slot, and with the same explanation, because it is the same gap
            # wearing a different label.
            raise InvalidRequest(
                f"{lineup.side}: {entry.player_id} is a {support.label} "
                f"({support.position}) and cannot fill the {entry_slot.label} "
                f"({entry_slot.slot}) slot. {support.reason} Blocked on: "
                + "; ".join(support.blocked_on)
                + ".",
                field=f"{lineup.side}.slot",
            )

        raise InvalidRequest(
            f"{lineup.side}: {entry.player_id} plays "
            f"{normalised or 'an unknown position'} and cannot fill the "
            f"{entry_slot.label} ({entry_slot.slot}) slot, which accepts "
            f"{list(entry_slot.eligible_positions)}.",
            field=f"{lineup.side}.slot",
        )


# ---------------------------------------------------------------------------
# Capability listing
# ---------------------------------------------------------------------------


def slot_summary() -> list[dict]:
    """A JSON-serialisable slot listing, served at ``/meta/lineup-slots``.

    A client builds its lineup editor from this rather than from a hard-coded
    eligibility map, which is what makes shipping a kicker model — or a
    superflex format — a server-side data change and no client change at all.
    """
    return [
        {
            "slot": entry.slot,
            "label": entry.label,
            "eligible_positions": list(entry.eligible_positions),
            "supported": entry.is_supported,
            "unsupported_positions": list(entry.unsupported_positions),
            "description": entry.description,
        }
        for entry in LINEUP_SLOTS
    ]


def format_summary() -> list[dict]:
    """A JSON-serialisable listing of the lineup formats a caller may name."""
    return [
        {
            "name": entry.name,
            "label": entry.label,
            "size": entry.size,
            "requirements": [
                {"slot": r.slot, "count": r.count} for r in entry.requirements
            ],
            "description": entry.description,
        }
        for entry in LINEUP_FORMATS
    ]
