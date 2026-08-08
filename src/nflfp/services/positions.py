"""Which positions the application projects, and what it says about the rest.

The engine projects QB, RB, WR and TE. Kickers and team defences are not
oversights — they score under rules the component model does not express (a
kicker's output is distance-bucketed field goals; a DST's is sacks, takeaways
and points allowed, none of which are player-week facts), and neither has a
feature in ``feat_training_dataset``.

The point of this module is that being unsupported is **declared data rather
than a raised exception scattered through the layer**. A request for kickers
gets a specific, honest answer — "planned, here is why, here is what it needs"
— and adding K or DST later is a change to :data:`POSITION_SUPPORT` plus a
model, with no edit to a router, a schema or a validator.

That extension path is exercised by the tests: they iterate this registry
rather than hard-coding four strings, so a fifth entry is picked up
automatically and any endpoint that would have ignored it fails.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import InvalidRequest


@dataclass(frozen=True)
class PositionSupport:
    """What the application can currently say about one position."""

    position: str
    label: str
    #: ``"projected"`` — a published model covers it.
    #: ``"planned"`` — recognised, deliberately not projected yet.
    status: str
    #: Why, in a sentence a user can read. Required for ``planned``.
    reason: str | None = None
    #: What it would take. Required for ``planned``; this is the roadmap entry.
    blocked_on: tuple[str, ...] = ()

    @property
    def is_projected(self) -> bool:
        return self.status == "projected"


POSITION_SUPPORT: tuple[PositionSupport, ...] = (
    PositionSupport("QB", "Quarterback", "projected"),
    PositionSupport("RB", "Running Back", "projected"),
    PositionSupport("WR", "Wide Receiver", "projected"),
    PositionSupport("TE", "Tight End", "projected"),
    PositionSupport(
        "K",
        "Kicker",
        "planned",
        reason=(
            "Kicker scoring is distance-bucketed field goals and extra points. "
            "The component model projects targets, carries, yards and "
            "touchdowns, none of which describe a kicker, and the feature layer "
            "carries no kicking usage."
        ),
        blocked_on=(
            "a kicking component vocabulary (attempts and makes by distance band)",
            "team field-goal opportunity features, which need raw_pbp",
            "its own residual distribution — kicker outcomes are discrete and "
            "low-count, so the continuous quantile approach does not transfer",
        ),
    ),
    PositionSupport(
        "DST",
        "Team Defense",
        "planned",
        reason=(
            "A team defence is not a player-week row. Its scoring comes from "
            "sacks, takeaways, return touchdowns and points allowed, which are "
            "properties of a game rather than of a player."
        ),
        blocked_on=(
            "a team-week fact table; feat_defense_game is the natural base and "
            "already aggregates most of the inputs",
            "opponent offensive-line and turnover-propensity features",
            "a discrete outcome model — DST scoring is dominated by rare, "
            "high-value events and is poorly described by residual quantiles "
            "fitted on continuous production",
        ),
    ),
)

_BY_POSITION = {entry.position: entry for entry in POSITION_SUPPORT}

#: Positions a published model covers. Derived, never written out twice.
PROJECTED_POSITIONS: tuple[str, ...] = tuple(
    entry.position for entry in POSITION_SUPPORT if entry.is_projected
)

#: Everything the application recognises, projected or not.
KNOWN_POSITIONS: tuple[str, ...] = tuple(entry.position for entry in POSITION_SUPPORT)


def describe(position: str) -> PositionSupport | None:
    """Look up one position's support status, or ``None`` if unrecognised."""
    return _BY_POSITION.get(position.strip().upper())


def validate_positions(positions: object) -> tuple[str, ...] | None:
    """Normalise and check a position filter.

    Args:
        positions: An iterable of position codes, or ``None`` for no filter.

    Returns:
        The normalised tuple, or ``None`` when no filter was requested.

    Raises:
        InvalidRequest: for an unrecognised position, or for one that is
            recognised but not yet projected. The message carries the reason
            and what it is blocked on, so the answer to "why can't I see
            kickers?" arrives with the error rather than requiring a support
            thread.
    """
    if not positions:
        return None

    normalised = tuple(str(p).strip().upper() for p in positions)  # type: ignore[union-attr]

    unknown = [p for p in normalised if p not in _BY_POSITION]
    if unknown:
        raise InvalidRequest(
            f"unrecognised position(s) {unknown}; known positions are "
            f"{list(KNOWN_POSITIONS)}",
            field="positions",
        )

    planned = [_BY_POSITION[p] for p in normalised if not _BY_POSITION[p].is_projected]
    if planned:
        entry = planned[0]
        raise InvalidRequest(
            f"{entry.label} ({entry.position}) is recognised but not projected "
            f"yet. {entry.reason} Blocked on: "
            + "; ".join(entry.blocked_on)
            + ".",
            field="positions",
        )

    return normalised


def support_summary() -> list[dict]:
    """A JSON-serialisable capability listing.

    Served at ``/meta/positions``. A client builds its position filter from
    this rather than from a hard-coded list, which is what makes shipping a
    kicker model a data change on the server and no change at all on the
    client.
    """
    return [
        {
            "position": entry.position,
            "label": entry.label,
            "status": entry.status,
            "projected": entry.is_projected,
            "reason": entry.reason,
            "blocked_on": list(entry.blocked_on),
        }
        for entry in POSITION_SUPPORT
    ]
