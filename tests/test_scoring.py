"""Tests for league scoring, including the two-renderer parity guard.

:class:`~nflfp.scoring.ScoringRules` is rendered twice: to SQL by
``points_expression`` for scoring history, and to Python by ``points_for`` for
scoring projections. Two renderers of one definition can drift, and a projection
scored differently from the history the model was trained on is a bug that never
raises — it just shows up as accuracy nobody can explain.

So the important test here evaluates both over real player-weeks and asserts
they agree exactly.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from nflfp.scoring import (
    COMPONENT_FIELDS,
    PROFILES,
    ScoringRules,
    points_expression,
    points_for,
)

from .conftest import requires_db


# ---------------------------------------------------------------------------
# unit
# ---------------------------------------------------------------------------

class TestPointsFor:
    def test_ppr_reception_scoring(self):
        components = {"receptions": 6, "receiving_yards": 80}
        assert points_for(components, PROFILES["ppr"]) == pytest.approx(14.0)
        assert points_for(components, PROFILES["half_ppr"]) == pytest.approx(11.0)
        assert points_for(components, PROFILES["standard"]) == pytest.approx(8.0)

    def test_passing_line(self):
        components = {
            "passing_yards": 300,
            "passing_tds": 3,
            "passing_interceptions": 1,
        }
        # 300*0.04 + 3*4 - 1*2
        assert points_for(components, PROFILES["ppr"]) == pytest.approx(22.0)

    def test_missing_and_none_components_are_zero(self):
        """Matches the SQL's COALESCE — a projection need not supply every field."""
        assert points_for({}, PROFILES["ppr"]) == 0.0
        assert points_for({"receiving_yards": None}, PROFILES["ppr"]) == 0.0

    def test_te_premium_applies_only_to_tight_ends(self):
        components = {"receptions": 5, "receiving_yards": 50}
        rules = PROFILES["ppr_te_premium"]
        assert points_for(components, rules, position="TE") == pytest.approx(12.5)
        assert points_for(components, rules, position="WR") == pytest.approx(10.0)

    def test_return_fumbles_toggle(self):
        """nflverse's own scoring ignores return fumbles; ESPN/Sleeper/Yahoo do not."""
        components = {"fumbles_lost_total": 1, "rushing_fumbles_lost": 0}
        assert points_for(components, PROFILES["ppr"]) == pytest.approx(-2.0)
        assert points_for(components, PROFILES["nflverse_parity"]) == pytest.approx(0.0)

    def test_milestone_bonus_when_configured(self):
        rules = ScoringRules(name="bonus", reception=0.0, bonus_rec_100=3.0)
        assert points_for({"receiving_yards": 100}, rules) == pytest.approx(13.0)
        assert points_for({"receiving_yards": 99}, rules) == pytest.approx(9.9)

    def test_component_fields_are_all_recognised(self):
        """Every declared field must actually affect scoring under some profile,
        or it is a name a projection will set and nothing will read."""
        for field in COMPONENT_FIELDS:
            scores = {
                points_for({field: 10}, rules, position="TE")
                for rules in PROFILES.values()
            }
            assert scores != {0.0}, f"{field} affects no scoring profile"


# ---------------------------------------------------------------------------
# the parity guard
# ---------------------------------------------------------------------------

@requires_db
@pytest.mark.integration
@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_python_and_sql_renderers_agree(pg_engine, profile):
    """Score real player-weeks both ways and require exact agreement.

    This is what stops the SQL and Python paths drifting. It runs over every
    scoring profile, including ``nflverse_parity``, whose SQL form is already
    verified at 0.0 difference against nflverse's own ``fantasy_points``.
    """
    rules = PROFILES[profile]
    columns = ", ".join(f'"{field}"' for field in COMPONENT_FIELDS)

    with pg_engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT position, {columns},
                       {points_expression(rules)} AS sql_points
                FROM raw_player_week
                WHERE season >= 2022 AND position IN ('QB','RB','WR','TE')
                ORDER BY player_id, season, week
                LIMIT 20000
                """
            )
        ).mappings().all()

    assert rows, "no player-weeks to compare"
    for row in rows:
        components = {field: row[field] for field in COMPONENT_FIELDS}
        python_points = points_for(components, rules, position=row["position"])
        assert python_points == pytest.approx(float(row["sql_points"]), abs=1e-9), (
            f"{profile}: python {python_points} != sql {row['sql_points']}"
        )
