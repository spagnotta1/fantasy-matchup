"""Which responses are cached, and for how long.

One table, read top to bottom, first match wins. Caching is **opt-in**: a path
with no rule is not cached. That is the safe default for a table somebody will
edit while adding an endpoint — forgetting to add a rule costs latency, whereas
a blanket default would silently cache the next endpoint that returns something
per-user.

Why the TTLs are minutes and not hours
--------------------------------------
A published run never changes, so in principle a slate could be cached until
the next publish and invalidated by the epoch bump. The TTLs are short anyway,
for one reason: **the default week resolves forward**. A request without
``?week=`` means "the week being decided", and that answer rolls over when the
first game of a slate kicks off — an event no publish accompanies. A five
minute ceiling bounds how long a board can claim to be about last week.

Everything that resolves against a live market moves too. Odds refresh hourly
and feed ``context.game``, so a slate held for an hour would show a stale
implied total beside a fresh projection, which is worse than showing neither.

``/meta/*`` is the exception in the other direction: it is derived from frozen
constants and a registry, changes on deploy, and is fetched by every client on
load.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Requests carrying these headers are never served from, or written to, the
#: cache. ``Authorization`` is here before authentication exists on purpose:
#: the day a principal becomes non-anonymous, a shared cache keyed only on the
#: URL would serve one user's response to another. That must be impossible by
#: construction rather than remembered during a later review.
PRIVATE_REQUEST_HEADERS = ("authorization", "cookie")


@dataclass(frozen=True)
class CacheRule:
    """A path prefix and how long its responses stay fresh."""

    prefix: str
    ttl_seconds: int
    reason: str


#: Ordered. More specific prefixes must come first.
RULES: tuple[CacheRule, ...] = (
    # Health is a liveness signal. A cached one reports the state of the
    # database as it was five minutes ago, which is not a health check.
    CacheRule("/api/v1/health", 0, "liveness must never be cached"),
    CacheRule(
        "/api/v1/meta",
        3600,
        "derived from frozen constants and the position registry; changes on deploy",
    ),
    CacheRule(
        "/api/v1/seasons",
        900,
        "published availability, which gains a week when the weekly job publishes",
    ),
    # Must precede the bare "/api/v1/teams" rule below: a team's outlook is
    # not the branding lookup — it carries this week's projected points, odds
    # and weather, the same live-market category the matchups rules bound to
    # five minutes. Left to fall through to the branding rule, it would serve
    # up to an hour of stale odds/projections after a correction or a week
    # rollover.
    CacheRule("/api/v1/teams/", 300, "reads the slate plus live market/weather context"),
    CacheRule("/api/v1/teams", 3600, "branding dimension, effectively static"),
    CacheRule("/api/v1/games", 600, "the schedule moves only for flexed kickoffs"),
    CacheRule(
        "/api/v1/weeks",
        300,
        "carries projections_published, which flips the moment a run publishes",
    ),
    CacheRule("/api/v1/projections", 300, "bounded by forward week resolution"),
    CacheRule("/api/v1/rankings", 300, "same board, filtered"),
    CacheRule("/api/v1/defense-rankings", 300, "aggregate over the same slate"),
    CacheRule("/api/v1/matchups", 300, "reads the slate plus defensive form"),
    # A ~46,000-row aggregate that changes only when a game completes or a run
    # publishes; the publish half is covered by the epoch, so the TTL bounds
    # how long a finished game waits to be graded.
    CacheRule("/api/v1/track-record", 900, "historical aggregate; grows as games complete"),
    CacheRule("/api/v1/schedule-strength", 300, "defensive form as of a week, like the matchups"),
    # One upstream read a minute however many people are watching. Shorter
    # would be "more live" and would make the public endpoint pay per viewer.
    CacheRule("/api/v1/live", 60, "in-game box scores; bounds the upstream to one read a minute"),
    CacheRule(
        "/api/v1/mock-draft/value-board",
        900,
        "the week 1 pool and a draft-day ADP snapshot; both change only on publish or ingest",
    ),
    # Listed with a TTL of zero so the table answers the question rather than
    # leaving it to the reader. `POST` never reaches the cache anyway — the
    # middleware handles `GET` only — and a simulation's inputs are two whole
    # lineups, so the hit rate on a keyed body would be near zero even if it
    # could be cached. It is also cheap to recompute and deterministic, which
    # is what makes recomputing the right answer.
    CacheRule("/api/v1/simulations", 0, "POST with a unique body; cheap and deterministic"),
    CacheRule("/api/v1/start-sit", 300, "deterministic over two stored distributions"),
    CacheRule("/api/v1/compare", 300, "deterministic over up to six distributions"),
    CacheRule("/api/v1/players", 300, "profile and history join the published run"),
    CacheRule(
        "/api/v1/search",
        60,
        "cheap query, high cardinality of terms — short TTL keeps the keyspace bounded",
    ),
)


def ttl_for(path: str) -> int:
    """Seconds a response for `path` may be cached. ``0`` means never.

    Args:
        path: Request path, without query string.
    """
    for rule in RULES:
        if path.startswith(rule.prefix):
            return rule.ttl_seconds
    return 0


def rule_for(path: str) -> CacheRule | None:
    """The matching rule, for diagnostics and the docs endpoint."""
    for rule in RULES:
        if path.startswith(rule.prefix):
            return rule
    return None


def warmable_paths() -> tuple[str, ...]:
    """Paths worth pre-rendering after a publish.

    Kept here rather than in the job because "which pages matter" is the same
    question this table already answers. These are the three requests a client
    makes on load, and the ones whose cold cost is a full slate assembly.
    """
    return (
        "/api/v1/projections",
        "/api/v1/rankings/QB",
        "/api/v1/rankings/RB",
        "/api/v1/rankings/WR",
        "/api/v1/rankings/TE",
        "/api/v1/defense-rankings",
        "/api/v1/meta/model",
        "/api/v1/meta/positions",
    )


#: The web client's board size. The warmer must request exactly what the client
#: does — a cache key covers the whole normalised query string, so a board
#: warmed at the default page size is a different entry from the one a browser
#: asks for. Kept in step with ``FULL_SLATE_LIMIT`` in ``web/src/hooks``.
CLIENT_BOARD_LIMIT = 1000


def slate_paths(
    *,
    season: int,
    week: int,
    scoring_profiles: tuple[str, ...],
    positions: tuple[str, ...],
) -> tuple[str, ...]:
    """The requests the web client makes for its opening slate.

    :func:`warmable_paths` warms bare paths, and a bare path resolves the
    *API's* default week and the default page size — neither of which is what
    the client asks for. The client opens on the newest week with a published
    board and names season, week, scoring profile and limit explicitly, so a
    warm of the bare path populated a cache entry no browser ever read.

    These are the client's own requests for that slate: every scoring profile's
    board, position boards and track record, plus the profile-independent
    schedule, defence and strength-of-schedule reads. Parameter order does not
    matter — keys are normalised — but every parameter does.
    """
    slate = f"season={season}&week={week}"
    paths: list[str] = [
        f"/api/v1/weeks/{week}?season={season}",
        f"/api/v1/games?{slate}",
        f"/api/v1/defense-rankings?{slate}",
    ]
    for position in positions:
        paths.append(f"/api/v1/defense-rankings?{slate}&position={position}")
        paths.append(f"/api/v1/schedule-strength?{slate}&position={position}")
    for profile in scoring_profiles:
        board = f"{slate}&scoring_profile={profile}&limit={CLIENT_BOARD_LIMIT}"
        paths.append(f"/api/v1/projections?{board}")
        for position in positions:
            paths.append(f"/api/v1/rankings/{position}?{board}")
        paths.append(f"/api/v1/track-record?scoring_profile={profile}")
    return tuple(paths)
