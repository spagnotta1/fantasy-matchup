"""Fantasy rosters: retrieving a *named set* of players and declaring the gaps.

Why this is not just ``get_projections_for_players``
---------------------------------------------------
:func:`~nflfp.services.projections.get_projections_for_players` returns whatever
it found and says nothing about what it did not. That is the right contract for
a comparison screen, where the caller picked the players and can see which of
its own ids came back.

It is the wrong contract for a roster. A fantasy roster is a *fixed set of
starters whose points are summed*, and a player who silently fails to appear
does not make the sum slightly less complete — it removes their entire
contribution from the total. A ten-player roster missing a kicker and a bye-week
receiver produces a team score roughly twenty points light, and any head-to-head
probability computed from two such totals is wrong in a direction nobody can
see. Silence is the failure mode here, so this module makes absence explicit and
typed.

That matters most for the positions the engine does not project at all. QB, RB,
WR and TE are covered; K and DST are recognised, deliberately unprojected, and
documented with their blockers in :mod:`~nflfp.services.positions`. A real
fantasy roster contains both. So any total assembled from this data covers only
part of a lineup, and :class:`RosterProjections` reports exactly which part
rather than presenting a partial sum as a whole one.

Correlation
-----------
The other thing a roster needs and a single projection does not: knowing where
the independence assumption breaks. Combining nine players multiplies the
opportunities to get that wrong — a stacked QB and WR1 are strongly positively
correlated, and two backs in one committee are strongly negatively correlated.
:func:`correlation_groups` and :func:`lineup_caveats` surface the structure so a
caller can disclose it, weight for it, or refuse to combine.

Nothing here computes a team score or a win probability. That is the Matchup
Simulation Engine's job, and this module is the seam it will read from.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from . import assemble, positions, repository
from .catalog import resolve_scoring_profile, resolve_window
from .dto import PlayerProjection, SlateWindow
from .errors import InvalidRequest

logger = logging.getLogger(__name__)

#: Players a single roster request may name. Generous next to a starting lineup
#: (typically nine or ten) because deep benches, IR slots and best-ball rosters
#: are all legitimate, and bounded so one request cannot ask for a slate.
MAX_ROSTER_SIZE = 40


# ---------------------------------------------------------------------------
# Why a player is missing
# ---------------------------------------------------------------------------

#: Recognised position, deliberately not projected — K and DST today. The
#: distinguishing property is that **no amount of waiting fixes this**: the
#: projection is not late, it does not exist, and it will not exist until the
#: work in :data:`~nflfp.services.positions.POSITION_SUPPORT` is done.
UNPROJECTED_POSITION = "unprojected_position"

#: The id is not in the player dimension at all. Almost always a bad id from the
#: caller, so it is separated from the states that are the platform's own doing.
UNKNOWN_PLAYER = "unknown_player"

#: A real, projectable player with nothing published for this week. A bye, an
#: inactive roster status, or a run that has not been published yet. Unlike
#: :data:`UNPROJECTED_POSITION` this is transient, and a caller may reasonably
#: retry it later in the week.
NO_PROJECTION = "no_projection"


@dataclass(frozen=True)
class UnavailablePlayer:
    """A roster slot the projection layer cannot fill, and why.

    ``reason`` is a stable machine code for a caller that branches; ``detail``
    is the sentence a user reads. Both are required, because a code without
    prose sends the user to a support thread and prose without a code sends the
    client into string matching.
    """

    player_id: str
    reason: str
    detail: str
    name: str | None = None
    position: str | None = None

    @property
    def is_permanent(self) -> bool:
        """True when waiting will not produce a projection.

        The distinction a caller acts on: a bye week means "ask again next
        week", an unprojected position means "this will never arrive, design
        around it".
        """
        return self.reason in (UNPROJECTED_POSITION, UNKNOWN_PLAYER)


@dataclass(frozen=True)
class RosterProjections:
    """Every projection found for a roster, plus every gap left in it.

    The invariant worth stating: ``len(entries) + len(unavailable)`` equals the
    number of distinct player ids requested. Nothing is dropped quietly, which
    is the whole reason this type exists rather than a bare list.
    """

    season: int
    week: int
    scoring_profile: str
    entries: tuple[PlayerProjection, ...]
    unavailable: tuple[UnavailablePlayer, ...]
    requested: tuple[str, ...]

    @property
    def complete(self) -> bool:
        """Every requested player has a projection.

        A consumer that sums these into a team score should treat ``False`` as
        meaning the total is a **lower bound on a partial lineup**, not an
        estimate of the roster's score.
        """
        return not self.unavailable

    @property
    def covered_positions(self) -> tuple[str, ...]:
        """Positions actually represented in :attr:`entries`, sorted."""
        found = {
            entry.player.position
            for entry in self.entries
            if entry.player.position is not None
        }
        return tuple(sorted(found))

    @property
    def coverage_caveats(self) -> tuple[str, ...]:
        """Caveats a caller must show beside any total derived from this roster.

        Assembled here rather than at each call site so that "we are missing a
        kicker" cannot be reported by one screen and forgotten by another.
        """
        caveats: list[str] = []

        unprojected = [u for u in self.unavailable if u.reason == UNPROJECTED_POSITION]
        if unprojected:
            labels = sorted({u.position for u in unprojected if u.position})
            caveats.append(
                f"{len(unprojected)} roster slot(s) at {', '.join(labels)} are not "
                "projected by this engine, so any team total below covers only "
                "the remaining positions and is not comparable to a full lineup "
                "score."
            )

        transient = [u for u in self.unavailable if u.reason == NO_PROJECTION]
        if transient:
            names = ", ".join(u.name or u.player_id for u in transient)
            caveats.append(
                f"No published projection for {names} this week — a bye, an "
                "inactive designation, or a run that has not published yet. "
                "Their points are absent from any total, not zero."
            )

        unknown = [u for u in self.unavailable if u.reason == UNKNOWN_PLAYER]
        if unknown:
            caveats.append(
                f"{len(unknown)} requested id(s) are not in the player "
                "dimension and were ignored."
            )

        caveats.extend(lineup_caveats(self.entries))
        return tuple(caveats)


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


async def get_roster_projections(
    session: AsyncSession,
    *,
    player_ids: Sequence[str],
    season: int | None = None,
    week: int | None = None,
    scoring_profile: str | None = None,
    model_name: str | None = None,
) -> tuple[RosterProjections, SlateWindow]:
    """Projections for a fantasy roster, with every gap accounted for.

    Two queries, not one per player: the projections for the whole set, and the
    player dimension for whichever ids came back empty. The second is what turns
    "missing" into "missing *because*", and it only runs when something is
    actually missing.

    Args:
        session: Open async session.
        player_ids: The roster. Duplicates are collapsed, order is not
            significant, and the original request is echoed in
            :attr:`RosterProjections.requested`.
        season: Season, defaulting to the current league year.
        week: Week, defaulting to the upcoming slate.
        scoring_profile: League format, defaulting to the configured one.
        model_name: Pin to a specific model instead of whatever is published.

    Returns:
        The roster's projections and gaps, and the window it resolved to.

    Raises:
        InvalidRequest: for an empty roster, or one above
            :data:`MAX_ROSTER_SIZE`.
    """
    unique = _distinct(player_ids)
    if not unique:
        raise InvalidRequest("at least one player id is required", field="player_ids")
    if len(unique) > MAX_ROSTER_SIZE:
        raise InvalidRequest(
            f"a roster may name at most {MAX_ROSTER_SIZE} players, got {len(unique)}",
            field="player_ids",
        )

    window = await resolve_window(session, season=season, week=week)
    profile = resolve_scoring_profile(scoring_profile)

    rows = await repository.fetch_projections(
        session,
        season=window.season,
        week=window.week,
        scoring_profile=profile,
        player_ids=unique,
        model_name=model_name,
    )
    entries = [assemble.player_projection(row) for row in rows]

    found = {entry.player.player_id for entry in entries}
    missing = [player_id for player_id in unique if player_id not in found]
    unavailable = await _explain_missing(session, missing)

    if unavailable:
        logger.info(
            "roster for %sw%s: %d of %d projected, %d unavailable",
            window.season, window.week, len(entries), len(unique), len(unavailable),
        )

    return (
        RosterProjections(
            season=window.season,
            week=window.week,
            scoring_profile=profile,
            entries=tuple(entries),
            unavailable=tuple(unavailable),
            requested=tuple(unique),
        ),
        window,
    )


async def _explain_missing(
    session: AsyncSession, player_ids: Sequence[str]
) -> list[UnavailablePlayer]:
    """Attach a reason to each id that produced no projection.

    The dimension lookup is what separates "your kicker will never have a
    projection" from "your receiver is on bye". Both are absences; only one is
    worth waiting out, and a caller that cannot tell them apart will either
    retry forever or give up too early.
    """
    if not player_ids:
        return []

    dimension = await repository.fetch_player_dimensions(session, player_ids)
    explained: list[UnavailablePlayer] = []

    for player_id in player_ids:
        row = dimension.get(player_id)
        if row is None:
            explained.append(
                UnavailablePlayer(
                    player_id=player_id,
                    reason=UNKNOWN_PLAYER,
                    detail=(
                        f"No player with id {player_id} exists in the player "
                        "dimension."
                    ),
                )
            )
            continue

        name = row.get("display_name")
        position = (row.get("position") or "").strip().upper() or None
        support = positions.describe(position) if position else None

        if support is not None and not support.is_projected:
            explained.append(
                UnavailablePlayer(
                    player_id=player_id,
                    reason=UNPROJECTED_POSITION,
                    name=name,
                    position=position,
                    detail=(
                        f"{name or player_id} is a {support.label} "
                        f"({support.position}), which this engine does not "
                        f"project. {support.reason} Blocked on: "
                        + "; ".join(support.blocked_on)
                        + "."
                    ),
                )
            )
        elif support is None:
            # A recognised NFL player at a position the product has no opinion
            # about at all — an offensive lineman, a punter. Reported as
            # unprojected rather than as a transient gap, because no run will
            # ever cover them either.
            explained.append(
                UnavailablePlayer(
                    player_id=player_id,
                    reason=UNPROJECTED_POSITION,
                    name=name,
                    position=position,
                    detail=(
                        f"{name or player_id} plays "
                        f"{position or 'an unlisted position'}, which is not a "
                        "fantasy-scoring position this engine recognises; "
                        f"known positions are {list(positions.KNOWN_POSITIONS)}."
                    ),
                )
            )
        else:
            explained.append(
                UnavailablePlayer(
                    player_id=player_id,
                    reason=NO_PROJECTION,
                    name=name,
                    position=position,
                    detail=(
                        f"{name or player_id} is projectable but has nothing "
                        "published for this week — most often a bye, an "
                        "inactive roster status, or a run that has not "
                        "published yet."
                    ),
                )
            )

    return explained


def _distinct(player_ids: Sequence[str]) -> list[str]:
    """Normalise and de-duplicate, preserving first-seen order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in player_ids:
        player_id = str(raw).strip()
        if player_id and player_id not in seen:
            seen.add(player_id)
            ordered.append(player_id)
    return ordered


# ---------------------------------------------------------------------------
# Correlation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CorrelationGroup:
    """A set of roster players whose outcomes are not independent.

    ``kind`` is ``"team"`` for players sharing an offence and ``"game"`` for
    players sharing a game without sharing a team. The two are separated
    because they need opposite corrections: teammates in one offence divide a
    finite pool of plays, while opponents are linked through pace and game
    script.
    """

    kind: str
    key: str
    player_ids: tuple[str, ...]
    names: tuple[str, ...]


def correlation_groups(
    projections: Sequence[PlayerProjection],
) -> tuple[CorrelationGroup, ...]:
    """Group a lineup by the structure that breaks independence.

    Singletons are omitted — a player correlated with nobody else in the lineup
    is not a group, and returning them would bury the two entries a caller
    actually needs to act on.

    Team groups are emitted first, then game groups covering players who are in
    a shared game but on different teams. A player can appear in both, which is
    correct: their outcome is tied to their teammates one way and to their
    opponents another.
    """
    groups: list[CorrelationGroup] = []

    by_team: dict[str, list[PlayerProjection]] = {}
    for projection in projections:
        if projection.team:
            by_team.setdefault(projection.team, []).append(projection)
    for team, members in sorted(by_team.items()):
        if len(members) > 1:
            groups.append(_group("team", team, members))

    by_game: dict[str, list[PlayerProjection]] = {}
    for projection in projections:
        if projection.game_id:
            by_game.setdefault(projection.game_id, []).append(projection)
    for game_id, members in sorted(by_game.items()):
        # Only interesting when the game group says something the team group did
        # not — that is, when it spans both sidelines.
        teams = {m.team for m in members if m.team}
        if len(members) > 1 and len(teams) > 1:
            groups.append(_group("game", game_id, members))

    return tuple(groups)


def _group(kind: str, key: str, members: Sequence[PlayerProjection]) -> CorrelationGroup:
    ordered = sorted(members, key=lambda p: p.player.player_id)
    return CorrelationGroup(
        kind=kind,
        key=key,
        player_ids=tuple(p.player.player_id for p in ordered),
        names=tuple(p.player.name for p in ordered),
    )


def lineup_caveats(projections: Sequence[PlayerProjection]) -> tuple[str, ...]:
    """Disclosures owed by anything that sums these projections.

    The existing head-to-head path discloses correlation for a *pair*
    (:func:`~nflfp.services.advice.start_sit`). A lineup is the same problem
    with more pairs and a larger consequence: summing nine independent-assumed
    curves understates the variance of a stacked roster and overstates it for a
    committee backfield, so a floor and a ceiling built that way are both too
    tight.

    Stating that is not the fix. The fix is a correlated simulation, and it is
    named as such in ``docs/simulation-readiness.md``. Until it exists, a caller
    that sums these curves is obliged to carry these strings.
    """
    caveats: list[str] = []
    for group in correlation_groups(projections):
        listed = ", ".join(group.names)
        if group.kind == "team":
            caveats.append(
                f"{listed} share an offence ({group.key}). Their outcomes are "
                "positively correlated through team plays and negatively "
                "correlated through target competition; any total that treats "
                "them as independent will understate how much this lineup's "
                "weeks move together."
            )
        else:
            caveats.append(
                f"{listed} are in the same game ({group.key}). Pace and game "
                "script are shared inputs, so their outcomes are correlated "
                "and an independent sum will report an interval that is too "
                "narrow."
            )
    return tuple(caveats)
