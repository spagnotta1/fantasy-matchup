"""Strength of schedule: every remaining opponent, graded on current form.

The planning view behind "who has the easy run-in?" For one position it lays
out every team's remaining regular-season opponents and grades each with the
same function and the same trailing four-game window the weekly matchup grade
uses (:func:`~nflfp.services.grading.grade_matchup`).

The assumption, stated because it is the whole of the method
------------------------------------------------------------
There is no forecast of how a defence will play in week 15. Each opponent is
graded on its form *as of the selected week*, and that grade is applied to every
remaining meeting with it. Defences change over a season — injuries, scheme,
schedule — so a grade ten weeks out is current form carried forward, not a
prediction, and the response says so in ``meta.notices``.

It follows the grading rules exactly, including the one that matters most early
in a season: below three completed games a defence is not graded, and the cell
says so. A strength-of-schedule table in week 2 is therefore mostly withheld,
which is correct — softening it into a middle grade would be inventing a rank.

Provenance: ``derived``. Nothing here reaches the projection.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from . import assemble, grading, repository
from .catalog import resolve_window
from .dto import SlateWindow
from .positions import validate_positions

#: Weeks a "next few" summary covers: roughly the stretch a trade or a waiver
#: claim has to pay off in.
NEXT_WEEKS = 4

#: The weeks most fantasy leagues play their playoffs in. A convention, not a
#: rule — reported as its own figure so a league with a different bracket can
#: read the per-week cells instead.
PLAYOFF_WEEKS = (15, 16, 17)

NOTICE_CURRENT_FORM = (
    "Each opponent is graded on its last four games before this week, and that "
    "grade is used for every remaining matchup. It shows current form, not a "
    "forecast of how a defence will play later in the season."
)


@dataclass(frozen=True)
class ScheduleCell:
    """One team-week: the opponent and how soft it currently is, or a bye."""

    week: int
    opponent: str | None
    is_home: bool | None
    game_id: str | None
    grade: grading.MatchupGrade | None
    fp_allowed_l4: float | None

    @property
    def is_bye(self) -> bool:
        return self.opponent is None


@dataclass(frozen=True)
class TeamSchedule:
    team: str
    cells: tuple[ScheduleCell, ...]
    mean_score: float | None
    graded_games: int
    next_score: float | None
    playoff_score: float | None


@dataclass(frozen=True)
class ScheduleStrength:
    season: int
    from_week: int
    position: str
    weeks: tuple[int, ...]
    teams: tuple[TeamSchedule, ...]
    window: SlateWindow
    notices: tuple[str, ...]


def _mean(cells: Sequence[ScheduleCell]) -> float | None:
    scores = [
        c.grade.score for c in cells if c.grade is not None and c.grade.graded and c.grade.score is not None
    ]
    return sum(scores) / len(scores) if scores else None


def build_schedule(
    *,
    season: int,
    from_week: int,
    position: str,
    weeks: Sequence[int],
    schedule_rows: Sequence[Mapping[str, object]],
    form_rows: Sequence[Mapping[str, object]],
) -> tuple[tuple[int, ...], tuple[TeamSchedule, ...]]:
    """Lay every team's remaining weeks out as a grid. Pure.

    Teams are ordered softest remaining schedule first (highest mean score),
    with teams whose schedule cannot be graded at all last and alphabetical.
    """
    grades: dict[str, tuple[grading.MatchupGrade, float | None]] = {}
    for row in form_rows:
        if str(row.get("position")) != position:
            continue
        grades[str(row["defteam"])] = (
            grading.grade_matchup(
                defense_rank=assemble.as_int(row, "fp_allowed_rank"),
                sample_games=assemble.as_int(row, "games_in_window"),
            ),
            assemble.as_float(row, "fp_allowed_l4"),
        )

    remaining = tuple(w for w in weeks if w >= from_week)
    games: dict[str, dict[int, Mapping[str, object]]] = {}
    for row in schedule_rows:
        games.setdefault(str(row["team"]), {})[int(row["week"])] = row  # type: ignore[call-overload]

    teams: list[TeamSchedule] = []
    for team in sorted(games):
        cells: list[ScheduleCell] = []
        for week in remaining:
            game = games[team].get(week)
            if game is None:
                cells.append(ScheduleCell(week, None, None, None, None, None))
                continue
            opponent = str(game["opponent"])
            grade, fp_allowed = grades.get(
                opponent,
                (
                    grading.grade_matchup(defense_rank=None, sample_games=None),
                    None,
                ),
            )
            cells.append(
                ScheduleCell(
                    week=week,
                    opponent=opponent,
                    is_home=None if game.get("is_home") is None else bool(game["is_home"]),
                    game_id=str(game["game_id"]) if game.get("game_id") else None,
                    grade=grade,
                    fp_allowed_l4=fp_allowed,
                )
            )
        played = [c for c in cells if not c.is_bye]
        teams.append(
            TeamSchedule(
                team=team,
                cells=tuple(cells),
                mean_score=_mean(played),
                graded_games=sum(1 for c in played if c.grade is not None and c.grade.graded),
                next_score=_mean([c for c in played if c.week < from_week + NEXT_WEEKS]),
                playoff_score=_mean([c for c in played if c.week in PLAYOFF_WEEKS]),
            )
        )

    teams.sort(key=lambda t: (t.mean_score is None, -(t.mean_score or 0.0), t.team))
    return remaining, tuple(teams)


async def get_schedule_strength(
    session: AsyncSession,
    *,
    position: str,
    season: int | None = None,
    week: int | None = None,
) -> ScheduleStrength:
    """Every team's remaining schedule for one position, graded on current form.

    Raises:
        InvalidRequest: for a position that is not projected — K and DST have
            no defensive-form rows to grade against.
    """
    validated = validate_positions([position])
    wanted = (validated or (position.strip().upper(),))[0]

    window = await resolve_window(session, season=season, week=week)
    weeks = await repository.fetch_regular_season_weeks(session, season=window.season)
    schedule_rows = await repository.fetch_team_schedule(
        session, season=window.season, from_week=window.week
    )
    form_rows = await repository.fetch_defense_form(
        session, season=window.season, week=window.week, positions=[wanted]
    )
    remaining, teams = build_schedule(
        season=window.season,
        from_week=window.week,
        position=wanted,
        weeks=weeks,
        schedule_rows=schedule_rows,
        form_rows=form_rows,
    )

    notices = [NOTICE_CURRENT_FORM]
    if teams and all(t.graded_games == 0 for t in teams):
        notices.append(
            f"No defence has played {grading.MIN_GAMES_FOR_GRADE} games before week "
            f"{window.week}, so no opponent can be graded yet. Grades start from week "
            f"{grading.MIN_GAMES_FOR_GRADE + 1}."
        )
    if not remaining:
        notices.append(f"The {window.season} regular season has no weeks left from week {window.week}.")

    return ScheduleStrength(
        season=window.season,
        from_week=window.week,
        position=wanted,
        weeks=remaining,
        teams=teams,
        window=window,
        notices=tuple(notices),
    )
