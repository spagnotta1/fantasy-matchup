"""ADP: the one warehouse dataset that is not nflverse.

Three properties, each of which fails silently if broken:

* **History survives.** The source serves only its latest drafting window, so
  a snapshot the warehouse drops is gone for good. The append publish must
  never delete by season -- in `refresh` *or* `full` mode.
* **A season's ADP is draft-day ADP.** Once a pre-kickoff window has been
  captured, the thin in-season trickle after it must not replace it.
* **An id is never guessed.** ADP carries names. A name two players share is
  left unmatched rather than attached to either.
"""

from __future__ import annotations

import duckdb
import pytest

from nflfp import pipeline, sources
from nflfp.transform import build_views, view_definitions

from .test_pipeline import _FakeCursor

ADP = sources.DATASETS_BY_NAME["adp"]


# ---------------------------------------------------------------------------
# manifest and URL resolution
# ---------------------------------------------------------------------------

class TestManifest:
    def test_adp_is_core_so_the_weekly_cron_carries_it(self):
        assert ADP.core

    def test_adp_appends_rather_than_swapping(self):
        assert ADP.refresh == "append"

    def test_unopened_seasons_are_missing_not_fetched(self, monkeypatch):
        """The API answers a season it has not opened with a 400. That is an
        unpublished season, reported as missing, exactly like an absent
        nflverse asset -- so a refresh for it fails loudly."""
        monkeypatch.setattr(sources, "_ffc_season_open", lambda y: y <= 2026)
        urls, missing = sources.resolve_urls(ADP, 2025, 2027)
        assert urls == [ADP.pattern.format(year=y) for y in (2025, 2026)]
        assert missing == [2027]

    def test_min_season_bounds_the_request(self, monkeypatch):
        asked: list[int] = []
        monkeypatch.setattr(
            sources, "_ffc_season_open", lambda y: asked.append(y) or True
        )
        sources.resolve_urls(ADP, 2010, 2016)
        assert min(asked) == ADP.min_season

    def test_parquet_datasets_still_read_parquet(self):
        sql = sources.select_sql(sources.DATASETS_BY_NAME["injuries"], ["u"])
        assert "read_parquet" in sql and "union_by_name" in sql

    def test_every_adp_row_carries_its_window_and_sample(self):
        """An ADP from 137 drafts and one from 8,470 are different numbers."""
        sql = sources.select_sql(ADP, ["u?year=2026"])
        for column in ("window_start", "window_end", "total_drafts", "season"):
            assert f"AS {column}" in sql


# ---------------------------------------------------------------------------
# append publish
# ---------------------------------------------------------------------------

class TestPublishAppend:
    def _patch(self, monkeypatch, exists: bool = True):
        monkeypatch.setattr(pipeline.pg, "table_exists", lambda cur, t: exists)
        monkeypatch.setattr(pipeline.pg, "columns", lambda cur, t: ["season", "adp"])
        monkeypatch.setattr(
            pipeline,
            "_staging_column_types",
            lambda cur, t: {"season": "integer", "adp": "double precision"},
        )

    def test_never_deletes_by_season(self, monkeypatch):
        """The failure this exists for: a season-wide delete would drop every
        earlier window of the current season, which cannot be fetched again."""
        self._patch(monkeypatch)
        cur = _FakeCursor(deleted=0, inserted=63)
        pipeline.publish_append(cur, ADP)
        deletes = [s for s in cur.statements if s.lstrip().startswith("DELETE")]
        assert len(deletes) == 1
        assert "window_start" in deletes[0] and "window_end" in deletes[0]
        assert "season = ANY" not in deletes[0]
        assert not any("DROP TABLE IF EXISTS raw_adp" in s for s in cur.statements)

    def test_a_new_window_is_appended(self, monkeypatch):
        self._patch(monkeypatch)
        note = pipeline.publish_append(_FakeCursor(deleted=0, inserted=63), ADP)
        assert note == "appended 63 rows"

    def test_refetching_a_window_replaces_it(self, monkeypatch):
        self._patch(monkeypatch)
        note = pipeline.publish_append(_FakeCursor(deleted=205, inserted=205), ADP)
        assert "replaced 205" in note

    def test_a_refetched_window_that_shrank_is_refused(self, monkeypatch):
        self._patch(monkeypatch)
        with pytest.raises(RuntimeError, match="refusing to publish"):
            pipeline.publish_append(_FakeCursor(deleted=205, inserted=20), ADP)

    def test_first_load_creates_the_table(self, monkeypatch):
        self._patch(monkeypatch, exists=False)
        cur = _FakeCursor()
        assert pipeline.publish_append(cur, ADP) == "created"
        assert cur.statements == ["ALTER TABLE stg_raw_adp RENAME TO raw_adp"]


# ---------------------------------------------------------------------------
# the player_adp view
# ---------------------------------------------------------------------------

_ADP_COLUMNS = (
    "season INTEGER, teams INTEGER, rounds INTEGER, total_drafts INTEGER, "
    "window_start DATE, window_end DATE, ffc_player_id INTEGER, name VARCHAR, "
    "position VARCHAR, team VARCHAR, adp DOUBLE, adp_formatted VARCHAR, "
    "times_drafted INTEGER, high INTEGER, low INTEGER, stdev DOUBLE, "
    "bye INTEGER, fetched_at TIMESTAMP"
)


def _adp(con, season, start, end, drafts, rows):
    for ffc_id, name, position, team, adp in rows:
        con.execute(
            "INSERT INTO raw_adp VALUES (?, 12, 15, ?, ?, ?, ?, ?, ?, ?, ?, "
            "NULL, NULL, NULL, NULL, NULL, NULL, NULL)",
            [season, drafts, start, end, ffc_id, name, position, team, adp],
        )


@pytest.fixture
def warehouse():
    con = duckdb.connect()
    con.execute(f"CREATE TABLE raw_adp ({_ADP_COLUMNS})")
    con.execute(
        "CREATE TABLE raw_rosters (season INTEGER, gsis_id VARCHAR, "
        "full_name VARCHAR, football_name VARCHAR, last_name VARCHAR, "
        "position VARCHAR, team VARCHAR)"
    )
    con.execute(
        "CREATE TABLE raw_players (gsis_id VARCHAR, display_name VARCHAR, "
        "position VARCHAR)"
    )
    con.execute(
        "CREATE TABLE raw_schedules (season INTEGER, game_type VARCHAR, "
        "gameday VARCHAR)"
    )
    con.execute("INSERT INTO raw_schedules VALUES (2026, 'REG', '2026-09-10')")
    con.executemany(
        "INSERT INTO raw_rosters VALUES (2026, ?, ?, ?, ?, ?, ?)",
        [
            ("00-1", "Kenneth Walker III", "Kenneth", "Walker", "RB", "KC"),
            ("00-2", "D.J. Moore", "DJ", "Moore", "WR", "CHI"),
            ("00-3", "Marquise Brown", "Marquise", "Brown", "WR", "KC"),
            # Two Mike Williamses at WR, on different teams.
            ("00-4", "Mike Williams", "Mike", "Williams", "WR", "LAC"),
            ("00-5", "Mike Williams", "Mike", "Williams", "WR", "NYJ"),
            # And two at the same team: team cannot split them.
            ("00-6", "Chris Jones", "Chris", "Jones", "WR", "DAL"),
            ("00-7", "Chris Jones", "Chris", "Jones", "WR", "DAL"),
            ("00-8", "Puka Nacua", "Puka", "Nacua", "WR", "LA"),
        ],
    )
    con.execute("INSERT INTO raw_players VALUES ('00-9', 'Stefon Diggs', 'WR')")
    yield con
    con.close()


def _view(con):
    # Only player_adp: the stub schedule is enough for a kickoff date, not for
    # the game_team view a full build would also attempt.
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    body = dict(view_definitions(tables))["player_adp"]
    con.execute(f"CREATE OR REPLACE VIEW player_adp AS {body}")
    return {
        r[0]: r[1:]
        for r in con.execute(
            "SELECT adp_name, player_id, match_status, adp_round, is_preseason, "
            "total_drafts FROM player_adp"
        ).fetchall()
    }


class TestPlayerAdpView:
    def test_draft_day_window_beats_a_later_in_season_one(self, warehouse):
        _adp(warehouse, 2026, "2026-08-30", "2026-09-06", 5000, [
            (1, "Kenneth Walker", "RB", "KC", 20.0),
        ])
        _adp(warehouse, 2026, "2026-09-12", "2026-09-19", 137, [
            (1, "Kenneth Walker", "RB", "KC", 40.0),
        ])
        row = _view(warehouse)["Kenneth Walker"]
        assert row[3] is True and row[4] == 5000

    def test_before_any_pre_kickoff_window_the_latest_stands_in_flagged(self, warehouse):
        _adp(warehouse, 2026, "2026-09-12", "2026-09-19", 137, [
            (1, "Kenneth Walker", "RB", "KC", 40.0),
        ])
        row = _view(warehouse)["Kenneth Walker"]
        assert row[3] is False, "an in-season window must say it is one"

    def test_suffix_and_punctuation_do_not_block_a_match(self, warehouse):
        _adp(warehouse, 2026, "2026-08-30", "2026-09-06", 5000, [
            (1, "Kenneth Walker", "RB", "KC", 20.0),
            (2, "DJ Moore", "WR", "CHI", 30.0),
        ])
        view = _view(warehouse)
        assert view["Kenneth Walker"][:2] == ("00-1", "matched")
        assert view["DJ Moore"][:2] == ("00-2", "matched")

    def test_rams_team_code_is_translated(self, warehouse):
        _adp(warehouse, 2026, "2026-08-30", "2026-09-06", 5000, [
            (8, "Puka Nacua", "WR", "LAR", 5.0),
        ])
        assert _view(warehouse)["Puka Nacua"][:2] == ("00-8", "matched")

    def test_a_nickname_matches_by_surname_team_and_position(self, warehouse):
        _adp(warehouse, 2026, "2026-08-30", "2026-09-06", 5000, [
            (3, "Hollywood Brown", "WR", "KC", 90.0),
        ])
        assert _view(warehouse)["Hollywood Brown"][:2] == ("00-3", "matched")

    def test_team_splits_a_shared_name(self, warehouse):
        _adp(warehouse, 2026, "2026-08-30", "2026-09-06", 5000, [
            (4, "Mike Williams", "WR", "NYJ", 100.0),
        ])
        assert _view(warehouse)["Mike Williams"][:2] == ("00-5", "matched")

    def test_a_tie_team_cannot_split_is_ambiguous_not_guessed(self, warehouse):
        _adp(warehouse, 2026, "2026-08-30", "2026-09-06", 5000, [
            (6, "Chris Jones", "WR", "DAL", 150.0),
        ])
        assert _view(warehouse)["Chris Jones"][:2] == (None, "ambiguous")

    def test_an_unrostered_player_falls_back_to_the_player_dimension(self, warehouse):
        _adp(warehouse, 2026, "2026-08-30", "2026-09-06", 5000, [
            (9, "Stefon Diggs", "WR", "FA", 85.0),
        ])
        assert _view(warehouse)["Stefon Diggs"][:2] == ("00-9", "matched")

    def test_nobody_by_that_name_is_unmatched(self, warehouse):
        _adp(warehouse, 2026, "2026-08-30", "2026-09-06", 5000, [
            (10, "Nobody Atall", "WR", "DAL", 150.0),
        ])
        assert _view(warehouse)["Nobody Atall"][:2] == (None, "unmatched")

    def test_kickers_and_defenses_are_not_applicable(self, warehouse):
        _adp(warehouse, 2026, "2026-08-30", "2026-09-06", 5000, [
            (11, "Chiefs Defense", "DEF", "KC", 120.0),
            (12, "Some Kicker", "PK", "KC", 140.0),
        ])
        view = _view(warehouse)
        assert view["Chiefs Defense"][:2] == (None, "not_applicable")
        assert view["Some Kicker"][:2] == (None, "not_applicable")

    @pytest.mark.parametrize("adp, expected", [(1.0, 1), (12.0, 1), (12.1, 2), (36.0, 3)])
    def test_round_is_the_ceiling_of_adp_over_teams(self, warehouse, adp, expected):
        _adp(warehouse, 2026, "2026-08-30", "2026-09-06", 5000, [
            (1, "Kenneth Walker", "RB", "KC", adp),
        ])
        assert _view(warehouse)["Kenneth Walker"][2] == expected

    def test_no_adp_table_builds_no_view(self):
        con = duckdb.connect()
        con.execute("CREATE TABLE raw_rosters (season INTEGER)")
        assert "player_adp" not in build_views(con)
