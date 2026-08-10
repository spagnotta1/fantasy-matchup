"""A synthetic draft pool, built by hand.

The draft engine's interesting behaviour — snake ordering, replacement level,
opportunity cost, tier structure, seeding — is arithmetic on a sequence of
dataclasses. A test that needs a 1.8-million-row warehouse and a published model
run to check that seat 1 and seat 12 pick in the right order is a test nobody
runs, so the unit suite constructs its own board.

The board is deliberately *shaped* rather than random: running backs have a
steep top and a cliff, receivers are deep and flat, quarterbacks are flat
throughout, and tight ends have one outlier. Those are the four shapes the
valuation is supposed to tell apart, and a uniform board would let a broken
replacement-level calculation pass.
"""

from __future__ import annotations

from nflfp.services.draft.history import HistoricalEvidence, HistoricalSeason
from nflfp.services.draft.pool import DraftPlayer, DraftPool
from nflfp.services.dto import PlayerRef

SEASON = 2025
SEASON_GAMES = 17


def make_player(
    player_id: str,
    position: str,
    season_value: float,
    *,
    name: str | None = None,
    team: str = "AAA",
    expected_games: float = 15.0,
    seasons: tuple[HistoricalSeason, ...] = (),
    basis: str = "player_history",
    consistency: str | None = "Moderate",
    trend: str | None = "steady",
) -> DraftPlayer:
    """One draftable player whose season value is stated rather than derived.

    ``season_value`` is set directly and ``projected_points_per_game`` derived
    from it, which is backwards from production and right for a test: the
    quantity every assertion is about is the season value, and deriving it from
    a rate would mean every expected number in the suite carried a rounding.
    """
    return DraftPlayer(
        player=PlayerRef(player_id=player_id, name=name or player_id, position=position),
        position=position,
        team=team,
        projected_points_per_game=season_value / expected_games,
        expected_games=expected_games,
        season_value=season_value,
        floor_per_game=season_value / expected_games * 0.5,
        ceiling_per_game=season_value / expected_games * 1.6,
        historical=HistoricalEvidence(
            seasons=seasons,
            expected_games=expected_games,
            availability_rate=expected_games / SEASON_GAMES if seasons else None,
            availability_basis=basis,
            seasons_observed=len(seasons),
            consistency_percentile=0.5 if consistency else None,
            consistency_label=consistency,
            trend=trend,
            trend_detail="fixture" if trend else None,
        ),
    )


def season(year: int, points: float, games: int = 16) -> HistoricalSeason:
    return HistoricalSeason(
        season=year,
        games_played=games,
        team_games=SEASON_GAMES,
        total_points=points,
        points_per_game=points / games,
        weekly_stdev=points / games * 0.4,
        position_rank=1,
        position_percentile=0.9,
    )


#: Value curves per position, chosen for their shapes rather than their realism.
_SHAPES: dict[str, list[float]] = {
    # Steep top, then a cliff after six: the position where waiting is expensive.
    "RB": [320, 300, 285, 272, 262, 254, 205, 200, 196, 192, 188, 184, 180, 176,
           172, 168, 164, 160, 156, 152, 148, 144, 140, 136, 132, 128, 124, 120,
           116, 112, 108, 104, 100, 96, 92, 88, 84, 80, 76, 72],
    # Deep and flat: the position where waiting is cheap.
    "WR": [300, 294, 288, 283, 278, 273, 268, 263, 258, 253, 248, 243, 238, 233,
           228, 223, 218, 213, 208, 203, 198, 193, 188, 183, 178, 173, 168, 163,
           158, 153, 148, 143, 138, 133, 128, 123, 118, 113, 108, 103, 98, 93,
           88, 83, 78, 73, 68, 63, 58, 53],
    # Flat throughout: high raw totals, almost no surplus over replacement.
    "QB": [330, 326, 322, 318, 314, 310, 306, 302, 298, 294, 290, 286, 282, 278,
           274, 270, 266, 262, 258, 254],
    # One outlier, then a long flat tail.
    "TE": [230, 170, 165, 160, 156, 152, 148, 144, 140, 136, 132, 128, 124, 120,
           116, 112, 108, 104, 100, 96],
}


#: How deep each position's board runs once the shaped head is extended. The
#: total must exceed ``teams x rounds`` for the largest league the suite drafts,
#: because a pool that runs out mid-draft is a *different* scenario — a real one,
#: with its own notice and its own test — and it should not be the accidental
#: condition under which every other assertion runs.
_DEPTH: dict[str, int] = {"RB": 64, "WR": 84, "QB": 34, "TE": 44}


def _extend(values: list[float], depth: int) -> list[float]:
    """Continue a value curve to ``depth`` entries at its final slope."""
    extended = list(values)
    step = (
        extended[-2] - extended[-1] if len(extended) >= 2 else 4.0
    ) or 4.0
    while len(extended) < depth:
        extended.append(max(1.0, extended[-1] - step))
    return extended


def build_pool(
    *,
    shapes: dict[str, list[float]] | None = None,
    with_history: bool = True,
    season_games: int = SEASON_GAMES,
    draft_season: int = SEASON,
) -> DraftPool:
    """A complete synthetic pool, ordered by season value."""
    curves = shapes or {
        position: _extend(values, _DEPTH[position])
        for position, values in _SHAPES.items()
    }
    players: list[DraftPlayer] = []
    for position, values in curves.items():
        for index, value in enumerate(values, start=1):
            history = (
                (
                    season(draft_season - 1, value * 0.95),
                    season(draft_season - 2, value * 0.9),
                )
                if with_history
                else ()
            )
            players.append(
                make_player(
                    f"{position}{index}",
                    position,
                    float(value),
                    name=f"{position} Player {index}",
                    team=f"T{index % 8}",
                    expected_games=15.0,
                    seasons=history,
                    basis="player_history" if with_history else "position_prior",
                )
            )

    players.sort(key=lambda p: (-p.season_value, p.player_id))
    return DraftPool(
        players=tuple(players),
        season=draft_season,
        board_week=1,
        scoring_profile="ppr",
        model=None,
        season_games=season_games,
        availability_priors={},
        history_seasons=(draft_season - 2, draft_season - 1) if with_history else (),
        notices=("fixture pool",),
    )
