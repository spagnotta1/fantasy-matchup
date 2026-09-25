"""Where the draft pool and the draft market disagree.

The mock draft's opponents do not draft from ADP (see
:mod:`~nflfp.services.draft.valuation`): presenting a model's board as ADP would
be the most misleading thing that feature could do. This module is the one place
the two are put side by side on purpose, and it keeps them labelled:

* ``season_value`` — the pool's per-game rate times expected games — is
  ``derived``, from a ``model`` number (the published week 1 expectation).
* ADP is **observed**: the market's average draft slot. It is ``context`` in
  this API's vocabulary — real, and consumed by no model.

The comparison that is fair, and the one that is not
----------------------------------------------------
Ranks are compared **within position** and **only among players who have
both**. Two tempting alternatives are both wrong:

* Overall rank against ADP flags every quarterback as a bargain, because season
  value does not price positional scarcity and the market does. That is a
  statement about replacement level, not about any player.
* Ranking the market over *all* its entries while ranking the pool over its own
  players misaligns the two lists by every rookie. The pool has no rookies — the
  model has no usage window for them — while the market drafts them early, so a
  veteran who is WR14 in the market is WR12 among the players the pool can
  value. Every veteran would look like a value by exactly the number of rookies
  ahead of him.

So the gap is ``market_rank - value_rank`` inside the players both lists hold:
positive means the pool values a player above where the market takes him. The
rookies and unmatched names are returned separately, with the reason each is
missing, rather than dropped.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .pool import DraftPlayer

#: Below this many drafts the ADP window is a thin sample, and the board says so.
THIN_MARKET = 500


@dataclass(frozen=True)
class ValueEntry:
    player: DraftPlayer
    adp: float
    adp_formatted: str | None
    adp_high: float | None
    adp_low: float | None
    adp_stdev: float | None
    market_rank: int
    value_rank: int

    @property
    def rank_gap(self) -> int:
        """Market rank minus value rank, within position: positive is a value."""
        return self.market_rank - self.value_rank


@dataclass(frozen=True)
class MarketOnly:
    """An ADP entry the pool cannot value, and why."""

    name: str
    position: str
    team: str | None
    adp: float
    reason: str


@dataclass(frozen=True)
class MarketWindow:
    total_drafts: int | None
    teams: int | None
    window_start: str | None
    window_end: str | None
    is_preseason: bool | None


@dataclass(frozen=True)
class ValueBoard:
    entries: tuple[ValueEntry, ...]
    unpriced: tuple[DraftPlayer, ...]
    market_only: tuple[MarketOnly, ...]
    market: MarketWindow | None


#: Why an ADP entry has no pool entry, in the words a manager needs.
REASONS = {
    "matched": "no projection — no prior usage window (usually a rookie)",
    "ambiguous": "name matched more than one player, so no projection was attached",
    "unmatched": "name did not match any player in the warehouse",
}


def _float(value: object) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]


def build_value_board(
    players: Sequence[DraftPlayer],
    adp_rows: Sequence[Mapping[str, object]],
    *,
    unpriced_limit: int = 25,
) -> ValueBoard:
    """Join the pool to the market and rank both within position. Pure."""
    by_id = {p.player.player_id: p for p in players}

    matched: list[tuple[DraftPlayer, Mapping[str, object]]] = []
    market_only: list[MarketOnly] = []
    seen: set[str] = set()
    for row in adp_rows:
        player_id = row.get("player_id")
        adp = _float(row.get("adp"))
        if adp is None:
            continue
        pool_player = by_id.get(str(player_id)) if player_id else None
        if pool_player is not None and str(player_id) not in seen:
            seen.add(str(player_id))
            matched.append((pool_player, row))
            continue
        status = str(row.get("match_status") or ("matched" if player_id else "unmatched"))
        market_only.append(
            MarketOnly(
                name=str(row.get("adp_name") or "Unknown"),
                position=str(row.get("position") or ""),
                team=(str(row["team"]) if row.get("team") else None),
                adp=adp,
                reason=REASONS.get(status, REASONS["unmatched"]),
            )
        )

    entries: list[ValueEntry] = []
    for position in sorted({p.position for p, _ in matched}):
        group = [(p, row) for p, row in matched if p.position == position]
        by_market = sorted(group, key=lambda pr: (_float(pr[1].get("adp")) or 0.0, pr[0].player.player_id))
        by_value = sorted(group, key=lambda pr: (-pr[0].season_value, pr[0].player.player_id))
        market_rank = {p.player.player_id: i + 1 for i, (p, _) in enumerate(by_market)}
        value_rank = {p.player.player_id: i + 1 for i, (p, _) in enumerate(by_value)}
        for p, row in group:
            entries.append(
                ValueEntry(
                    player=p,
                    adp=float(row["adp"]),  # type: ignore[arg-type]
                    adp_formatted=(str(row["adp_formatted"]) if row.get("adp_formatted") else None),
                    adp_high=_float(row.get("high")),
                    adp_low=_float(row.get("low")),
                    adp_stdev=_float(row.get("stdev")),
                    market_rank=market_rank[p.player.player_id],
                    value_rank=value_rank[p.player.player_id],
                )
            )
    entries.sort(key=lambda e: (e.adp, e.player.player.player_id))

    unpriced = tuple(p for p in players if p.player.player_id not in seen)[:unpriced_limit]

    first = adp_rows[0] if adp_rows else None
    market = (
        MarketWindow(
            total_drafts=(int(first["total_drafts"]) if first.get("total_drafts") is not None else None),  # type: ignore[call-overload]
            teams=(int(first["teams"]) if first.get("teams") is not None else None),  # type: ignore[call-overload]
            window_start=(str(first["window_start"]) if first.get("window_start") else None),
            window_end=(str(first["window_end"]) if first.get("window_end") else None),
            is_preseason=(None if first.get("is_preseason") is None else bool(first["is_preseason"])),
        )
        if first is not None
        else None
    )
    return ValueBoard(
        entries=tuple(entries),
        unpriced=unpriced,
        market_only=tuple(sorted(market_only, key=lambda m: m.adp)),
        market=market,
    )


def market_notices(board: ValueBoard, season: int) -> list[str]:
    """What a reader must know about the market side before trusting a gap."""
    notices = [
        "ADP is the market's observed average draft slot. It is shown beside the "
        "pool's season value and is not an input to any projection or to the mock "
        "draft's opponents.",
        "Ranks are compared within position, among players who have both an ADP and "
        "a projection; the gap is market rank minus value rank.",
    ]
    if board.market is None:
        notices.append(f"No ADP has been loaded for {season}, so there is no market to compare against.")
        return notices
    drafts = board.market.total_drafts
    if drafts is not None and drafts < THIN_MARKET:
        notices.append(
            f"The {season} ADP window covers only {drafts} drafts. Treat its ordering "
            "as a thin sample, not a settled market."
        )
    if board.market.is_preseason is False:
        notices.append(
            "No pre-kickoff ADP window was captured for this season, so the latest "
            "window stands in — an in-season market, not the draft-day one."
        )
    return notices
