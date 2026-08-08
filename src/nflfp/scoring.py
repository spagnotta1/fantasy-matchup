"""League scoring rules, rendered to SQL over the raw_player_week columns.

nflverse ships `fantasy_points` (standard) and `fantasy_points_ppr`, but those
are fixed. Fantasy leagues aren't — so we recompute from the components. That
means one place to change when you find out your league does TE premium or
6-point passing TDs, and it keeps the target variable honest.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class ScoringRules:
    name: str = "half_ppr"

    pass_yd: float = 0.04
    pass_td: float = 4.0
    interception: float = -2.0
    pass_2pt: float = 2.0

    rush_yd: float = 0.1
    rush_td: float = 6.0
    rush_2pt: float = 2.0

    reception: float = 0.5
    rec_yd: float = 0.1
    rec_td: float = 6.0
    rec_2pt: float = 2.0

    fumble_lost: float = -2.0
    special_teams_td: float = 6.0

    # True  -> every fumble lost counts, including on punt/kick returns. This is
    #          what ESPN/Sleeper/Yahoo actually do, so it's the default.
    # False -> only offensive fumbles (sack/rush/receiving), which is how
    #          nflverse's own `fantasy_points` column is computed. Affects ~0.2%
    #          of player-weeks, essentially all of them return men and DBs.
    count_return_fumbles: bool = True

    # Position premiums, applied per reception on top of `reception`.
    te_premium: float = 0.0

    # Yardage milestone bonuses (0 disables).
    bonus_pass_300: float = 0.0
    bonus_rush_100: float = 0.0
    bonus_rec_100: float = 0.0


PROFILES: dict[str, ScoringRules] = {
    "standard": ScoringRules(name="standard", reception=0.0),
    "half_ppr": ScoringRules(name="half_ppr", reception=0.5),
    "ppr": ScoringRules(name="ppr", reception=1.0),
    "ppr_te_premium": ScoringRules(name="ppr_te_premium", reception=1.0, te_premium=0.5),
    # Not a league format — a regression test. Reproduces nflverse's own
    # `fantasy_points` exactly, so `explore --probe scoring_check` proves the
    # rest of the scoring maths is right rather than merely plausible.
    "nflverse_parity": ScoringRules(
        name="nflverse_parity", reception=0.0, count_return_fumbles=False
    ),
}


def points_expression(r: ScoringRules, alias: str = "") -> str:
    """SQL scalar expression computing fantasy points for one player-week row.

    `alias` qualifies every column reference. Pass the stats table's alias
    whenever this is embedded in a join — `position` in particular also exists
    on the players and snap-count tables and is otherwise ambiguous.
    """
    q = f"{alias}." if alias else ""

    def _n(col: str) -> str:
        """Null-safe, alias-qualified numeric column reference."""
        return f"COALESCE({q}{col}, 0)"

    fumbles = (
        _n("fumbles_lost_total")
        if r.count_return_fumbles
        else f"({_n('sack_fumbles_lost')} + {_n('rushing_fumbles_lost')}"
        f" + {_n('receiving_fumbles_lost')})"
    )

    terms = [
        f"{_n('passing_yards')} * {r.pass_yd}",
        f"{_n('passing_tds')} * {r.pass_td}",
        f"{_n('passing_interceptions')} * {r.interception}",
        f"{_n('passing_2pt_conversions')} * {r.pass_2pt}",
        f"{_n('rushing_yards')} * {r.rush_yd}",
        f"{_n('rushing_tds')} * {r.rush_td}",
        f"{_n('rushing_2pt_conversions')} * {r.rush_2pt}",
        f"{_n('receptions')} * {r.reception}",
        f"{_n('receiving_yards')} * {r.rec_yd}",
        f"{_n('receiving_tds')} * {r.rec_td}",
        f"{_n('receiving_2pt_conversions')} * {r.rec_2pt}",
        f"{fumbles} * {r.fumble_lost}",
        f"{_n('special_teams_tds')} * {r.special_teams_td}",
    ]
    if r.te_premium:
        terms.append(
            f"CASE WHEN {q}position = 'TE' THEN {_n('receptions')} * {r.te_premium} ELSE 0 END"
        )
    for col, threshold, bonus in (
        ("passing_yards", 300, r.bonus_pass_300),
        ("rushing_yards", 100, r.bonus_rush_100),
        ("receiving_yards", 100, r.bonus_rec_100),
    ):
        if bonus:
            terms.append(f"CASE WHEN {_n(col)} >= {threshold} THEN {bonus} ELSE 0 END")

    return "(\n        " + "\n      + ".join(terms) + "\n    )"


#: Component names :func:`points_for` understands. These are the stat columns a
#: projection produces, and they deliberately match the ``raw_player_week``
#: column names so the SQL and Python paths score the same thing.
COMPONENT_FIELDS: tuple[str, ...] = (
    "passing_yards",
    "passing_tds",
    "passing_interceptions",
    "passing_2pt_conversions",
    "rushing_yards",
    "rushing_tds",
    "rushing_2pt_conversions",
    "receptions",
    "receiving_yards",
    "receiving_tds",
    "receiving_2pt_conversions",
    "fumbles_lost_total",
    "sack_fumbles_lost",
    "rushing_fumbles_lost",
    "receiving_fumbles_lost",
    "special_teams_tds",
)


def points_for(
    components: dict[str, float | None],
    rules: ScoringRules,
    position: str | None = None,
) -> float:
    """Fantasy points for a set of stat components, in Python.

    The second renderer of :class:`ScoringRules`. :func:`points_expression`
    renders the same rules to SQL for scoring *history*; this evaluates them for
    scoring *projections*, where the components are predicted floats that never
    touch a database.

    Two renderers of one definition is a real risk — they can drift, and a
    projection scored differently from the history it was trained on is a bug
    that shows up only as mediocre accuracy. ``tests/test_scoring.py`` therefore
    evaluates both over real player-weeks and asserts they agree exactly.

    Args:
        components: Stat values keyed by :data:`COMPONENT_FIELDS`. Missing and
            ``None`` entries count as zero, matching the SQL's ``COALESCE``.
        rules: The league profile to score under.
        position: Needed only when ``rules.te_premium`` is set.

    Returns:
        Fantasy points.

    Example:
        >>> points_for({"receptions": 6, "receiving_yards": 80}, PROFILES["ppr"])
        14.0
    """
    def n(field: str) -> float:
        value = components.get(field)
        return 0.0 if value is None else float(value)

    if rules.count_return_fumbles:
        fumbles = n("fumbles_lost_total")
    else:
        fumbles = (
            n("sack_fumbles_lost")
            + n("rushing_fumbles_lost")
            + n("receiving_fumbles_lost")
        )

    total = (
        n("passing_yards") * rules.pass_yd
        + n("passing_tds") * rules.pass_td
        + n("passing_interceptions") * rules.interception
        + n("passing_2pt_conversions") * rules.pass_2pt
        + n("rushing_yards") * rules.rush_yd
        + n("rushing_tds") * rules.rush_td
        + n("rushing_2pt_conversions") * rules.rush_2pt
        + n("receptions") * rules.reception
        + n("receiving_yards") * rules.rec_yd
        + n("receiving_tds") * rules.rec_td
        + n("receiving_2pt_conversions") * rules.rec_2pt
        + fumbles * rules.fumble_lost
        + n("special_teams_tds") * rules.special_teams_td
    )

    if rules.te_premium and position == "TE":
        total += n("receptions") * rules.te_premium

    # Milestone bonuses. Applied to *expected* yardage when scoring a
    # projection, which is an approximation: E[bonus] is really
    # P(yards >= threshold) * bonus, and a player projected for 99 yards has a
    # meaningful chance of clearing 100. The distribution layer is where that
    # gets done properly; with every profile's bonuses currently 0.0 this
    # branch is inert, and the approximation is noted rather than hidden.
    for field, threshold, bonus in (
        ("passing_yards", 300, rules.bonus_pass_300),
        ("rushing_yards", 100, rules.bonus_rush_100),
        ("receiving_yards", 100, rules.bonus_rec_100),
    ):
        if bonus and n(field) >= threshold:
            total += bonus

    return total


def describe(r: ScoringRules) -> str:
    return ", ".join(f"{k}={v}" for k, v in asdict(r).items() if k != "name" and v)
