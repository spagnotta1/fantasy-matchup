"""Declarative manifest of warehouse datasets, plus source resolution.

nflverse publishes each dataset as parquet assets attached to a GitHub release,
one release *tag* per dataset family. Rather than hard-coding which years exist
(they change as seasons are played, and nflverse occasionally renames assets),
we ask the GitHub API which assets a tag actually has and intersect that with
what the manifest wants. A season that hasn't been published yet is skipped
with a warning instead of failing the build.

One dataset is not nflverse: ``adp`` comes from Fantasy Football Calculator's
public ADP API as JSON, one request per season. It has no asset listing, so
:func:`ffc_seasons_available` asks each season directly; the API answers a
season it has not opened with HTTP 400 "Invalid year", which is the same
"not published yet" an absent nflverse asset means.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

RELEASE_BASE = "https://github.com/nflverse/nflverse-data/releases/download"
API_BASE = "https://api.github.com/repos/nflverse/nflverse-data/releases/tags"

#: Fantasy Football Calculator ADP: 12-team PPR, every position, one season.
#: The response is the most recent drafting window for that season -- for a
#: past season, the final week of its preseason; for the current one, the last
#: week or so, which thins out once the season starts.
FFC_ADP_URL = (
    "https://fantasyfootballcalculator.com/api/v1/adp/ppr"
    "?teams=12&year={year}&position=all"
)

# Default modelling window. 2016+ gives ~10 seasons, which is deep enough for
# stable per-player priors without dragging in a materially different league
# (pre-2016 passing/pace environments don't transfer well).
DEFAULT_START_SEASON = 2016
DEFAULT_END_SEASON = 2026


def current_season(today: date | None = None) -> int:
    """The NFL season a given date belongs to.

    The league year rolls over in March, so anything from March onward belongs
    to that calendar year's season and Jan/Feb still belong to the previous one
    (the playoffs of the season that started the prior autumn).
    """
    d = today or date.today()
    return d.year if d.month >= 3 else d.year - 1


@dataclass(frozen=True)
class Dataset:
    """One dataset to land as a raw table."""

    name: str  # destination table name (prefixed raw_ on load)
    tag: str  # nflverse-data release tag
    pattern: str | None = None  # per-season asset pattern (or URL), "{year}" placeholder
    files: tuple[str, ...] = ()  # explicit assets (for un-partitioned datasets)
    min_season: int | None = None  # earliest season this dataset exists for
    description: str = ""
    core: bool = True  # core = pulled by default; extras need --all
    # How a weekly refresh updates this table:
    #   "by_season" — reload only the current season's file(s) and replace those
    #                 rows. Requires a trustworthy `season` column.
    #   "full"      — always reload everything. Correct for single-file datasets
    #                 (schedules, players) and for depth_charts, whose 2025+
    #                 files dropped the season column entirely.
    #   "append"    — add each newly fetched snapshot, replacing only a snapshot
    #                 fetched before with the same window; never delete by
    #                 season, in either mode. For sources that serve only their
    #                 latest window, where a swap would destroy history that
    #                 cannot be fetched again (adp).
    refresh: str = "by_season"
    # "nflverse" (parquet release assets) or "ffc" (Fantasy Football
    # Calculator JSON). Decides how URLs resolve and how staging reads them.
    source: str = "nflverse"


DATASETS: tuple[Dataset, ...] = (
    # ---- core: everything the baseline projection model needs -------------
    Dataset(
        name="player_week",
        tag="stats_player",
        pattern="stats_player_week_{year}.parquet",
        description="Weekly per-player box score + EPA/share metrics (the target variable lives here)",
    ),
    Dataset(
        name="schedules",
        tag="schedules",
        files=("games.parquet",),
        refresh="full",
        description="Game-level context: home/away, spread, total, roof, surface, temp, wind, rest days",
    ),
    Dataset(
        name="players",
        tag="players",
        files=("players.parquet",),
        refresh="full",
        description="Player dimension: ids across systems, position, draft, physicals",
    ),
    Dataset(
        name="rosters",
        tag="rosters",
        pattern="roster_{year}.parquet",
        description="Season rosters (team affiliation, depth position, status)",
    ),
    Dataset(
        name="snap_counts",
        tag="snap_counts",
        pattern="snap_counts_{year}.parquet",
        min_season=2012,
        description="Weekly offensive/defensive/ST snap counts and shares — the usage backbone",
    ),
    Dataset(
        name="depth_charts",
        tag="depth_charts",
        pattern="depth_charts_{year}.parquet",
        # nflverse dropped the season column from the 2025+ depth chart files,
        # so rows can't be reliably deleted by season. Cheap enough to reload
        # whole (~4s), which is why this is "full" rather than "by_season".
        refresh="full",
        description="Weekly depth chart position, incl. the upcoming season",
    ),
    Dataset(
        name="injuries",
        tag="injuries",
        pattern="injuries_{year}.parquet",
        min_season=2009,
        description="Weekly injury report: practice status and game designation",
    ),
    Dataset(
        name="teams",
        tag="teams",
        files=("teams_colors_logos.parquet",),
        refresh="full",
        description="Team dimension: abbreviations, names, colors, logos (for the UI later)",
    ),
    Dataset(
        name="adp",
        tag="ffc",
        pattern=FFC_ADP_URL,
        min_season=2015,
        refresh="append",
        source="ffc",
        description=(
            "Average draft position, 12-team PPR (Fantasy Football Calculator). "
            "Observed market context, not a model input"
        ),
    ),
    # ---- extras: heavier, opt in with --all -------------------------------
    Dataset(
        name="pbp",
        tag="pbp",
        pattern="play_by_play_{year}.parquet",
        core=False,
        description="Full play-by-play w/ EPA, WP, air yards (~50k rows & 380 cols per season)",
    ),
    Dataset(
        name="ngs_passing",
        tag="nextgen_stats",
        files=("ngs_passing.parquet",),
        refresh="full",
        core=False,
        description="Next Gen Stats passing (time to throw, aggressiveness, xComp)",
    ),
    Dataset(
        name="ngs_receiving",
        tag="nextgen_stats",
        files=("ngs_receiving.parquet",),
        refresh="full",
        core=False,
        description="Next Gen Stats receiving (separation, cushion, YAC over expected)",
    ),
    Dataset(
        name="ngs_rushing",
        tag="nextgen_stats",
        files=("ngs_rushing.parquet",),
        refresh="full",
        core=False,
        description="Next Gen Stats rushing (8-in-box rate, rush yards over expected)",
    ),
    Dataset(
        name="pfr_rec",
        tag="pfr_advstats",
        pattern="advstats_week_rec_{year}.parquet",
        min_season=2018,
        core=False,
        description="PFR advanced weekly receiving (broken tackles, drops, contested)",
    ),
    Dataset(
        name="pfr_rush",
        tag="pfr_advstats",
        pattern="advstats_week_rush_{year}.parquet",
        min_season=2018,
        core=False,
        description="PFR advanced weekly rushing (yards before/after contact)",
    ),
    Dataset(
        name="pfr_pass",
        tag="pfr_advstats",
        pattern="advstats_week_pass_{year}.parquet",
        min_season=2018,
        core=False,
        description="PFR advanced weekly passing (pressure, blitz, bad throws)",
    ),
    Dataset(
        name="ftn_charting",
        tag="ftn_charting",
        pattern="ftn_charting_{year}.parquet",
        min_season=2022,
        core=False,
        description="FTN charting: play action, motion, screens, defenders in box",
    ),
)

DATASETS_BY_NAME = {d.name: d for d in DATASETS}


@lru_cache(maxsize=None)
def release_assets(tag: str) -> frozenset[str]:
    """Asset filenames attached to an nflverse-data release tag."""
    req = urllib.request.Request(
        f"{API_BASE}/{tag}",
        headers={"User-Agent": "nfl-fantasy-ingest", "Accept": "application/vnd.github+json"},
    )
    # Optional: lifts the anonymous GitHub rate limit from 60 to 5000 req/hr.
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:  # pragma: no cover - network dependent
        raise RuntimeError(
            f"Could not list nflverse release '{tag}' ({exc.code}). "
            "If this is a 403, set GITHUB_TOKEN to raise the rate limit."
        ) from exc
    return frozenset(a["name"] for a in payload.get("assets", []))


def _ffc_season_open(year: int) -> bool:
    """True if Fantasy Football Calculator serves ADP for `year`.

    A 400 is the API's "Invalid year" -- a season it has not opened -- and
    counts as unpublished. Anything else that fails is an outage and raises,
    so a dead API cannot pass for a quiet offseason.
    """
    req = urllib.request.Request(
        FFC_ADP_URL.format(year=year), headers={"User-Agent": "nfl-fantasy-ingest"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:  # pragma: no cover - network dependent
        if exc.code == 400:
            return False
        raise RuntimeError(
            f"Fantasy Football Calculator ADP for {year} failed ({exc.code})"
        ) from exc
    if payload.get("status") != "Success":  # pragma: no cover - network dependent
        raise RuntimeError(
            f"Fantasy Football Calculator ADP for {year}: {payload.get('errors')}"
        )
    return True


def ffc_seasons_available(start_season: int, end_season: int) -> list[int]:
    """Seasons in the window the FFC ADP API will answer."""
    return [y for y in range(start_season, end_season + 1) if _ffc_season_open(y)]


def resolve_urls(
    ds: Dataset, start_season: int, end_season: int
) -> tuple[list[str], list[int]]:
    """Return (urls, missing_seasons) for a dataset over a season window."""
    if ds.source == "ffc":
        lo = max(start_season, ds.min_season or start_season)
        open_ = set(ffc_seasons_available(lo, end_season))
        urls = [ds.pattern.format(year=y) for y in sorted(open_)]
        missing = [y for y in range(lo, end_season + 1) if y not in open_]
        return urls, missing

    available = release_assets(ds.tag)

    if ds.pattern is None:
        urls = [f"{RELEASE_BASE}/{ds.tag}/{f}" for f in ds.files if f in available]
        missing = [] if urls else [-1]
        return urls, missing

    lo = max(start_season, ds.min_season or start_season)
    urls, missing = [], []
    for year in range(lo, end_season + 1):
        fname = ds.pattern.format(year=year)
        if fname in available:
            urls.append(f"{RELEASE_BASE}/{ds.tag}/{fname}")
        else:
            missing.append(year)
    return urls, missing


def select_sql(ds: Dataset, urls: list[str]) -> str:
    """The SELECT that stages `urls` for `ds`, in DuckDB SQL.

    Shared by the Postgres pipeline and the local DuckDB build so both land the
    same columns.
    """
    url_list = ", ".join(f"'{u}'" for u in urls)
    if ds.source != "ffc":
        # union_by_name absorbs nflverse's schema drift across seasons; without
        # it a multi-year read fails whenever any season has a different column
        # set.
        return f"SELECT * FROM read_parquet([{url_list}], union_by_name = true)"

    # One row per (season, drafting window, player). The season comes from the
    # request URL: the response does not repeat it. The window and draft count
    # travel with every row, because an ADP from 137 drafts and one from 8,470
    # are not the same kind of number and must not be read as one.
    return f"""
    SELECT
        CAST(regexp_extract(j.filename, 'year=([0-9]+)', 1) AS INTEGER) AS season,
        CAST(j.meta.teams AS INTEGER)        AS teams,
        CAST(j.meta.rounds AS INTEGER)       AS rounds,
        CAST(j.meta.total_drafts AS INTEGER) AS total_drafts,
        CAST(j.meta.start_date AS DATE)      AS window_start,
        CAST(j.meta.end_date AS DATE)        AS window_end,
        CAST(p.player_id AS INTEGER)         AS ffc_player_id,
        p.name                               AS name,
        p.position                           AS position,
        p.team                               AS team,
        CAST(p.adp AS DOUBLE)                AS adp,
        p.adp_formatted                      AS adp_formatted,
        CAST(p.times_drafted AS INTEGER)     AS times_drafted,
        CAST(p.high AS INTEGER)              AS high,
        CAST(p.low AS INTEGER)               AS low,
        CAST(p.stdev AS DOUBLE)              AS stdev,
        CAST(p.bye AS INTEGER)               AS bye,
        CAST(current_timestamp AS TIMESTAMP) AS fetched_at
    FROM read_json([{url_list}], filename = true) AS j,
         unnest(j.players) AS t(p)
    """
