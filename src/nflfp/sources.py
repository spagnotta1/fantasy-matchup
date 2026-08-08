"""Declarative manifest of nflverse datasets, plus release-asset resolution.

nflverse publishes each dataset as parquet assets attached to a GitHub release,
one release *tag* per dataset family. Rather than hard-coding which years exist
(they change as seasons are played, and nflverse occasionally renames assets),
we ask the GitHub API which assets a tag actually has and intersect that with
what the manifest wants. A season that hasn't been published yet is skipped
with a warning instead of failing the build.
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
    """One nflverse dataset to land as a raw table."""

    name: str  # destination table name (prefixed raw_ on load)
    tag: str  # nflverse-data release tag
    pattern: str | None = None  # per-season asset pattern, "{year}" placeholder
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
    refresh: str = "by_season"


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


def resolve_urls(
    ds: Dataset, start_season: int, end_season: int
) -> tuple[list[str], list[int]]:
    """Return (urls, missing_seasons) for a dataset over a season window."""
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
