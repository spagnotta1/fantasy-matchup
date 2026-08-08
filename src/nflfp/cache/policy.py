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
    CacheRule("/api/v1/seasons", 900, "the warehouse gains a season once a year"),
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
