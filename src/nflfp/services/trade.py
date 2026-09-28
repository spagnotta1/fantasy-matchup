"""Trade values: what a player is worth from here to the end of the season.

The trade analyzer needs one number per player that can be *added up*: two
players for one has to come out right. Projected points cannot do that. Two
twelve-point receivers do not replace one twenty-four-point receiver, because a
lineup has a fixed number of slots and the waiver wire refills the rest for
free. What does add up is value over replacement, and the draft engine already
computes it (:mod:`~nflfp.services.draft.valuation`). This module reads the
same machinery at the current week instead of week 1.

How a value is built, and what each half is
-------------------------------------------
::

    rest_of_season  =  expected_points          provenance: model    (this week's published run)
                    x  games_left               the schedule         (counting this week)
                    x  availability             provenance: derived  (historical, shrunk to position)

    trade_value     =  max(rest_of_season - replacement_level, 0)

The model supplies the rate and nothing else, exactly as in the draft pool: the
rate and the history are multiplied, never blended. It is a **rate carried
forward**, not a rest-of-season forecast: there is no such model here, and
the frozen-foundation rule forbids inventing one. Injuries, role changes and
trades from this week on are not in it, and every response says so.

Replacement level is the **waiver wire**, not the last starter. The draft
board zeroes at the worst starter because a draft is a competition for starting
slots; a trade is not, and at that level everyone past the eighty-fourth player
in a twelve-team league is worth nothing, so most real trades — two bench
receivers for a flex back — would compare zero with zero. The zero point here
is the best player nobody has rostered. Starting depth per position comes from
:func:`~nflfp.services.draft.valuation.replacement_levels` (dedicated slots,
flex by auction), and the bench is shared out in the same proportions: a
fifteen-player roster that starts seven holds each position at fifteen-sevenths
of its starting depth. For the default league that is about 26 quarterbacks,
69 backs, 60 receivers and 26 tight ends rostered, which is close to what real
leagues carry. The proportional bench is an **assumption**, stated in the
notices, not a measurement.

The trade value is floored at zero because a player below the waiver wire is
worth what the waiver wire gives away. That floor is the difference from the
draft board, which keeps negative surpluses: in a draft a negative surplus ranks
the undraftable, whereas in a trade it would let a throw-in *reduce* a side's
worth.

A team on bye has no row on this week's board. Its players are valued from their
most recent published projection this season and say which week it came from.
A player absent this week for any other reason — released, no longer on a
depth chart — has no value and is not listed; a client shows that beside him
rather than a zero.

Provenance: ``derived``. Nothing here reaches the projection.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from . import assemble, repository
from .catalog import resolve_scoring_profile, resolve_window
from .draft import pool as pool_module
from .draft.settings import DraftSettings, validate_settings
from .draft.pool import DraftPlayer
from .draft.valuation import ReplacementLevel, replacement_levels
from .dto import ModelRef, PlayerRef, SlateWindow

#: League size the values open on. A request field, bounded by the draft
#: settings' own limits, because replacement level moves with it.
DEFAULT_TEAMS = 12

#: Players on each roster, bench included. Sets how deep the waiver-wire
#: replacement level sits.
ROSTER_SIZE = 15

#: How far back a bye-week team's players look for their most recent
#: published projection. Byes are single weeks; the extra weeks cover a player
#: who was also absent the week before his bye.
BYE_LOOKBACK_WEEKS = 3


@dataclass(frozen=True)
class TradeValue:
    """One player's rest-of-season worth, with each factor kept apart.

    Attributes:
        player: Player reference.
        position: Normalised position code.
        team: Team abbreviation on the board the rate came from.
        rate: ``expected_points`` for :attr:`rate_week` — ``provenance: model``.
        rate_week: The week whose published projection supplied the rate.
        on_bye: The player's team has no game in the requested week, so the rate
            is from an earlier week.
        games_left: Regular-season games the team plays from the requested week
            on, counting it.
        availability: Share of games the player is expected to be available
            for — ``provenance: derived``.
        availability_basis: ``"player_history"`` or ``"position_prior"``.
        expected_games: ``games_left * availability``.
        rest_of_season: ``rate * expected_games``.
        value_over_replacement: ``rest_of_season`` minus the position's
            replacement level. Negative below replacement.
        trade_value: ``value_over_replacement`` floored at zero.
        overall_rank: 1-based, by trade value across positions.
        position_rank: 1-based, by rest-of-season points within position.
    """

    player: PlayerRef
    position: str
    team: str | None
    rate: float
    rate_week: int
    on_bye: bool
    games_left: int
    availability: float
    availability_basis: str
    expected_games: float
    rest_of_season: float
    value_over_replacement: float
    trade_value: float
    overall_rank: int
    position_rank: int


@dataclass(frozen=True)
class TradeValues:
    """Every valued player for one week and league size, plus its disclosures."""

    season: int
    week: int
    scoring_profile: str
    teams: int
    remaining_weeks: tuple[int, ...]
    values: tuple[TradeValue, ...]
    replacement: Mapping[str, ReplacementLevel]
    replacement_names: Mapping[str, str]
    model: ModelRef | None
    window: SlateWindow
    notices: tuple[str, ...]


def build_trade_values(
    *,
    board_rows: Sequence[Mapping[str, object]],
    bye_rows: Sequence[Mapping[str, object]],
    panel_rows: Sequence[Mapping[str, object]],
    game_counts: Mapping[int, int],
    schedule_rows: Sequence[Mapping[str, object]],
    settings: DraftSettings,
    week: int,
) -> tuple[tuple[TradeValue, ...], dict[str, ReplacementLevel], dict[str, str]]:
    """Value every player on the board. Pure, so the arithmetic is testable.

    Args:
        board_rows: The requested week's published projections.
        bye_rows: Earlier weeks' projections for teams on bye this week, most
            recent week first. Only a player's first row is used.
        panel_rows: Completed-season totals before this season, for availability.
        game_counts: Regular-season games per team, by season.
        schedule_rows: ``game_team`` rows from ``week`` on.
        settings: League configuration; supplies teams and the roster.
        week: The requested week.

    Returns:
        ``(values, replacement levels, replacement player names)``, values
        ordered by trade value.
    """
    season = settings.season
    games_left: dict[str, int] = {}
    for row in schedule_rows:
        team = str(row.get("team"))
        games_left[team] = games_left.get(team, 0) + 1

    seen = {str(row.get("player_id")) for row in board_rows}
    rate_weeks: dict[str, int] = {player_id: week for player_id in seen}
    rows: list[Mapping[str, object]] = list(board_rows)
    for row in bye_rows:
        player_id = str(row.get("player_id"))
        if player_id in seen:
            continue
        seen.add(player_id)
        rows.append(row)
        rate_weeks[player_id] = int(row.get("week") or week)  # type: ignore[call-overload]

    season_games = game_counts.get(season) or max(game_counts.values(), default=17)
    pool = pool_module.assemble_pool(
        board_rows=rows,
        panel_rows=panel_rows,
        game_counts=game_counts,
        season=season,
        season_games=season_games,
        scoring_profile=settings.scoring_profile,
    )

    carried = []
    for player in pool.players:
        availability = player.expected_games / season_games if season_games else 0.0
        expected = games_left.get(player.team or "", 0) * availability
        carried.append(
            dataclasses.replace(
                player,
                expected_games=expected,
                season_value=player.projected_points_per_game * expected,
            )
        )
    carried.sort(key=lambda p: (-p.season_value, p.player_id))
    starting = replacement_levels(dataclasses.replace(pool, players=tuple(carried)), settings)
    levels = waiver_levels(carried, starting, settings)
    names = {p.player_id: p.name for p in carried}

    position_ranks: dict[str, int] = {}
    counters: dict[str, int] = {}
    for player in carried:
        counters[player.position] = counters.get(player.position, 0) + 1
        position_ranks[player.player_id] = counters[player.position]

    def surplus(player: DraftPlayer) -> float:
        level = levels.get(player.position)
        return player.season_value - (level.value if level else 0.0)

    ordered = sorted(carried, key=lambda p: (-surplus(p), p.player_id))
    values = tuple(
        TradeValue(
            player=player.player,
            position=player.position,
            team=player.team,
            rate=player.projected_points_per_game,
            rate_week=rate_weeks.get(player.player_id, week),
            on_bye=rate_weeks.get(player.player_id, week) != week,
            games_left=games_left.get(player.team or "", 0),
            availability=(
                player.historical.expected_games / season_games if season_games else 0.0
            ),
            availability_basis=player.historical.availability_basis,
            expected_games=player.expected_games,
            rest_of_season=player.season_value,
            value_over_replacement=surplus(player),
            trade_value=max(surplus(player), 0.0),
            overall_rank=index + 1,
            position_rank=position_ranks[player.player_id],
        )
        for index, player in enumerate(ordered)
    )
    replacement_names = {
        position: names[level.player_id]
        for position, level in levels.items()
        if level.player_id in names
    }
    return values, levels, replacement_names


def waiver_levels(
    players: Sequence[DraftPlayer],
    starting: Mapping[str, ReplacementLevel],
    settings: DraftSettings,
) -> dict[str, ReplacementLevel]:
    """The best player nobody has rostered, per position.

    Each position's starting depth is scaled by ``rounds / starters`` — the
    bench shared out in the same proportions as the lineup. A position deeper
    than the pool falls back to its last player, as
    :func:`~nflfp.services.draft.valuation.replacement_levels` does.

    Args:
        players: Every valued player, best rest-of-season value first.
        starting: Starter-level replacement, which supplies the depth and the
            flex allocation.
        settings: League configuration; ``rounds`` is the roster size.
    """
    ranked: dict[str, list[DraftPlayer]] = {}
    for player in players:
        ranked.setdefault(player.position, []).append(player)

    scale = settings.rounds / settings.starters if settings.starters else 1.0
    levels: dict[str, ReplacementLevel] = {}
    for position, pool in ranked.items():
        start = starting.get(position)
        depth = round((start.starters if start else 0) * scale)
        replacement = pool[depth] if depth < len(pool) else pool[-1]
        levels[position] = ReplacementLevel(
            position=position,
            starters=depth,
            value=replacement.season_value,
            player_id=replacement.player_id,
            flex_share=start.flex_share if start else 0,
        )
    return levels


async def get_trade_values(
    session: AsyncSession,
    *,
    season: int | None = None,
    week: int | None = None,
    scoring_profile: str | None = None,
    teams: int = DEFAULT_TEAMS,
) -> TradeValues:
    """Rest-of-season trade values for every projected player.

    An unpublished week is an empty list with a notice, not an error — the same
    contract as the board it is built from.

    Raises:
        InvalidRequest: for a league size outside the draft settings' bounds.
    """
    window = await resolve_window(session, season=season, week=week)
    profile = resolve_scoring_profile(scoring_profile)
    settings = validate_settings(
        teams=teams, rounds=ROSTER_SIZE, scoring_profile=profile, season=window.season
    )
    positions = settings.draftable_positions

    board_rows = await repository.fetch_projections(
        session,
        season=window.season,
        week=window.week,
        scoring_profile=profile,
        positions=positions,
    )
    weeks = await repository.fetch_regular_season_weeks(session, season=window.season)
    remaining = tuple(w for w in weeks if w >= window.week)
    if not board_rows:
        return TradeValues(
            season=window.season,
            week=window.week,
            scoring_profile=profile,
            teams=teams,
            remaining_weeks=remaining,
            values=(),
            replacement={},
            replacement_names={},
            model=None,
            window=window,
            notices=(
                f"No projections are published for {window.season} week "
                f"{window.week}, so there are no trade values to show yet.",
            ),
        )

    schedule_rows = await repository.fetch_team_schedule(
        session, season=window.season, from_week=window.week
    )
    playing = {str(r.get("team")) for r in schedule_rows if r.get("week") == window.week}
    all_teams = {str(r.get("team")) for r in schedule_rows}
    on_bye = sorted(all_teams - playing)

    bye_rows: list[dict] = []
    if on_bye:
        for back in range(window.week - 1, max(window.week - 1 - BYE_LOOKBACK_WEEKS, 0), -1):
            bye_rows.extend(
                await repository.fetch_projections(
                    session,
                    season=window.season,
                    week=back,
                    scoring_profile=profile,
                    positions=positions,
                    teams=on_bye,
                )
            )

    panel = await repository.fetch_season_totals(
        session,
        before_season=window.season,
        seasons_back=pool_module.PANEL_SEASONS,
        scoring_profile=profile,
        positions=positions,
    )
    game_counts = await repository.fetch_season_game_counts(session)

    values, levels, names = build_trade_values(
        board_rows=board_rows,
        bye_rows=bye_rows,
        panel_rows=panel,
        game_counts=game_counts,
        schedule_rows=schedule_rows,
        settings=settings,
        week=window.week,
    )
    return TradeValues(
        season=window.season,
        week=window.week,
        scoring_profile=profile,
        teams=teams,
        remaining_weeks=remaining,
        values=values,
        replacement=levels,
        replacement_names=names,
        model=assemble.model_ref(board_rows[0]),
        window=window,
        notices=_notices(values, settings, window.week, on_bye),
    )


def _notices(
    values: Sequence[TradeValue],
    settings: DraftSettings,
    week: int,
    on_bye: Sequence[str],
) -> tuple[str, ...]:
    """Disclosures owed by anything that renders these values."""
    roster = ", ".join(f"{r.count} {r.slot}" for r in settings.roster)
    notices = [
        f"Trade value is rest-of-season points above replacement. Each player's "
        f"week {week} projection is used as a per-game rate, multiplied by the games "
        "their team has left (counting this week) and by the share of games they "
        "have usually been available for. It is a rate carried forward, not a "
        "forecast: injuries, role changes and trades from here on are not in it.",
        f"Replacement level is the best player at each position still on the "
        f"waiver wire in a {settings.teams}-team league starting {roster} with "
        f"{settings.rounds}-player rosters. Benches are assumed to hold positions "
        "in the same proportions as the starting lineup. A player below that "
        "level is valued at zero, because the waiver wire offers the same for "
        "free.",
        "Availability is based on each player's past seasons, pulled toward the "
        "typical figure for their position. It does not know about a current "
        "injury: an injured player's value assumes they play at their usual rate.",
        "The values do not know your roster. A player worth a lot here is worth "
        "less to a team that could not start them.",
    ]
    carried = [v for v in values if v.on_bye]
    if carried:
        weeks = sorted({v.rate_week for v in carried})
        from_weeks = " or ".join(str(w) for w in weeks)
        notices.append(
            f"{len(on_bye)} teams are on bye in week {week} ({', '.join(on_bye)}). "
            f"Their {len(carried)} players are valued from their week {from_weeks} "
            "projection."
        )
    return tuple(notices)
