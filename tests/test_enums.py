"""Unit tests for :mod:`nflfp.db.enums`.

The interesting test here is the drift guard: :class:`ScoringProfile` and
:data:`nflfp.scoring.PROFILES` describe the same set of league formats from two
different angles, and nothing in the type system stops someone adding a format
to one and not the other. The symptom would be a ``CHECK`` constraint rejecting
projections for a profile the app believes it supports — at write time, in a
background job, hours before anyone noticed.
"""

from __future__ import annotations

from nflfp.db.enums import (
    Algorithm,
    ModelRunStatus,
    ScoringProfile,
    sql_in_list,
    values,
)
from nflfp.scoring import PROFILES

# Not a league format — a regression fixture that reproduces nflverse's own
# fantasy_points column. Publishing projections for it would be meaningless.
NON_LEAGUE_PROFILES = {"nflverse_parity"}


def test_scoring_profiles_match_scoring_module():
    assert set(values(ScoringProfile)) == set(PROFILES) - NON_LEAGUE_PROFILES


def test_enum_members_are_plain_strings():
    """SQLAlchemy and Pydantic both round-trip these as bare strings."""
    assert ScoringProfile.PPR == "ppr"
    assert str(ModelRunStatus.PUBLISHED) == "published"
    assert f"{Algorithm.XGBOOST}" == "xgboost"


def test_sql_in_list_renders_valid_sql():
    rendered = sql_in_list(ScoringProfile)
    assert rendered.startswith("(") and rendered.endswith(")")
    assert "'ppr'" in rendered
    # A one-element Python tuple renders as ('a',) — a SQL syntax error. The
    # helper exists to prevent exactly that, so assert the comma discipline.
    assert not rendered.endswith(",)")


def test_sql_in_list_escapes_quotes():
    from enum import Enum

    class Awkward(str, Enum):
        TRICKY = "o'brien"

    assert sql_in_list(Awkward) == "('o''brien')"


def test_model_run_statuses_cover_the_lifecycle():
    required = {"pending", "running", "succeeded", "failed", "published", "superseded"}
    assert required <= set(values(ModelRunStatus))
