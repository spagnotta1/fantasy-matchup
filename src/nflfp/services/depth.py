"""A team's offensive depth chart for a week.

Provenance: ``context``. The depth chart is observed — the team's own listing —
and the frozen model does not read it: it projects from usage, the snaps and
targets a player actually got, which is what a depth chart is a noisy forecast
of. It is shown for the question usage cannot answer on its own: who is next
in line when a starter is out.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from . import repository
from .catalog import resolve_window
from .dto import SlateWindow

DEPTH_UNAPPLIED_REASON = (
    "The model projects from how much a player has actually played (snaps "
    "and targets), not from the depth chart. The depth chart is shown so you "
    "can see who is next in line."
)


@dataclass(frozen=True)
class DepthEntry:
    depth: int
    player_id: str | None
    name: str


@dataclass(frozen=True)
class DepthChart:
    team: str
    season: int
    week: int
    as_of: str | None
    positions: Mapping[str, tuple[DepthEntry, ...]]
    window: SlateWindow


def group_depth(rows: Sequence[Mapping[str, object]]) -> dict[str, tuple[DepthEntry, ...]]:
    """Rows into positions in lineup order, each in depth order. Pure."""
    grouped: dict[str, list[DepthEntry]] = {position: [] for position in repository.DEPTH_POSITIONS}
    for row in rows:
        position = str(row["position"])
        if position not in grouped:
            continue
        grouped[position].append(
            DepthEntry(
                depth=int(row["depth"]),  # type: ignore[call-overload]
                player_id=(str(row["player_id"]) if row.get("player_id") else None),
                name=str(row.get("player_name") or "Unknown"),
            )
        )
    return {
        position: tuple(sorted(entries, key=lambda e: e.depth))
        for position, entries in grouped.items()
    }


async def get_depth_chart(
    session: AsyncSession,
    *,
    team: str,
    season: int | None = None,
    week: int | None = None,
) -> DepthChart:
    """The team's offensive depth chart going into the resolved week."""
    window = await resolve_window(session, season=season, week=week)
    abbr = team.strip().upper()
    rows = await repository.fetch_depth_chart(
        session, team=abbr, season=window.season, week=window.week
    )
    return DepthChart(
        team=abbr,
        season=window.season,
        week=window.week,
        as_of=str(rows[0]["as_of"]) if rows else None,
        positions=group_depth(rows),
        window=window,
    )
