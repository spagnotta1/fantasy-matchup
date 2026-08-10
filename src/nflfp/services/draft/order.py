"""Whose turn it is, and when your next turn comes.

A snake draft's ordering is three lines of arithmetic and is still worth its own
module, because *every* interesting quantity in this package is a function of
it. "How long do I wait?" is the whole reason seat 1 and seat 6 build different
rosters: seat 1 waits 22 picks between its first and second selection in a
twelve-team league and seat 6 waits 12, so seat 1 must assume two more tiers
will be gone and seat 6 must not. Getting the parity of a round wrong would not
crash anything — it would quietly produce a plausible, wrong answer about which
seat is best, which is the single number this feature exists to report.

So the ordering is built once, as data, and every consumer reads it. Nothing
else in the package computes ``round % 2``.

Overall pick numbers are 1-based, because that is what a draft board shows and
what a user will read back to us in a bug report. Team numbers are 1-based for
the same reason: "draft position 4" is the fourth seat, not the fifth.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class DraftSlot:
    """One selection in a draft, located three ways.

    Attributes:
        overall: 1-based pick number across the whole draft.
        round_number: 1-based round.
        pick_in_round: 1-based position within the round. Under a snake this is
            *not* the team number in even rounds, which is exactly the confusion
            this field exists to keep out of the rest of the package.
        team: 1-based seat making the selection.
    """

    overall: int
    round_number: int
    pick_in_round: int
    team: int


@dataclass(frozen=True)
class DraftOrder:
    """The full sequence of selections for one league configuration.

    Built once per simulation batch and shared across every simulated draft in
    it — the ordering does not depend on the seed, the pool or anything a
    simulation discovers, so rebuilding it per draft would be ten thousand
    identical lists.
    """

    teams: int
    rounds: int
    snake: bool
    slots: tuple[DraftSlot, ...]

    @classmethod
    def build(cls, *, teams: int, rounds: int, snake: bool = True) -> DraftOrder:
        """Construct the ordering for a league.

        Args:
            teams: League size.
            rounds: Rounds in the draft.
            snake: Reverse every even round. ``False`` is a linear draft, in
                which seat 1 picks first in every round.
        """
        slots: list[DraftSlot] = []
        overall = 0
        for round_number in range(1, rounds + 1):
            reversed_round = snake and round_number % 2 == 0
            seats = range(teams, 0, -1) if reversed_round else range(1, teams + 1)
            for pick_in_round, team in enumerate(seats, start=1):
                overall += 1
                slots.append(
                    DraftSlot(
                        overall=overall,
                        round_number=round_number,
                        pick_in_round=pick_in_round,
                        team=team,
                    )
                )
        return cls(teams=teams, rounds=rounds, snake=snake, slots=tuple(slots))

    @property
    def total_picks(self) -> int:
        return len(self.slots)

    def __iter__(self) -> Iterator[DraftSlot]:
        return iter(self.slots)

    def slot(self, overall: int) -> DraftSlot:
        """The selection at a 1-based overall pick number."""
        return self.slots[overall - 1]

    def picks_for(self, team: int) -> tuple[int, ...]:
        """Every overall pick number a seat owns, in order.

        This is the sequence the whole valuation hangs off: the gap between
        consecutive entries is how many players leave the board before the seat
        chooses again.
        """
        return tuple(slot.overall for slot in self.slots if slot.team == team)

    def next_pick_after(self, team: int, overall: int) -> int | None:
        """The seat's next selection after ``overall``, or ``None`` if it has none.

        ``None`` is the final round's answer and is a real case rather than an
        edge case: on the last pick there is no future to trade against, so the
        valuation drops its lookahead term entirely and takes the best player
        left. Returning ``None`` rather than ``total_picks + 1`` is what makes
        that a branch a reader can see.
        """
        for slot in self.slots:
            if slot.team == team and slot.overall > overall:
                return slot.overall
        return None

    def wait_lengths(self, team: int) -> tuple[int, ...]:
        """Picks that elapse between each of a seat's selections and its next.

        The seat-asymmetry number, exposed because it explains the result. In a
        twelve-team snake, seat 1 gets ``(22, 2, 22, 2, ...)`` and seat 6 gets
        ``(12, 12, ...)`` — the same total wait distributed completely
        differently, which is why the two seats want different strategies rather
        than the same strategy applied later.
        """
        picks = self.picks_for(team)
        return tuple(later - earlier for earlier, later in zip(picks, picks[1:]))


def summarise_waits(order: DraftOrder) -> dict[int, tuple[int, ...]]:
    """Every seat's wait pattern, for the comparison view's explanatory copy."""
    return {team: order.wait_lengths(team) for team in range(1, order.teams + 1)}


def positions_of(slots: Sequence[DraftSlot], team: int) -> tuple[int, ...]:
    """Overall pick numbers belonging to ``team`` within an arbitrary slice."""
    return tuple(slot.overall for slot in slots if slot.team == team)
