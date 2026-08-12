"""Mock Draft: what roster a draft position can plausibly build.

This package answers one question — *given a league and a draft slot, what
roster is this seat likely to be able to assemble, and which seat assembles the
strongest one?* — and it answers it by simulating drafts rather than by ranking
players.

It creates no projections. Like the Matchup Simulation Engine it is a
**consumer** of the frozen foundation: every point estimate it uses came out of
a published ``projection_points`` row, and nothing here refits, reweights or
second-guesses that number. What this package adds is everything the frozen
model has no opinion about — how many games a player is likely to be available
for, what a replacement-level player at each position is worth, what the other
eleven managers are likely to do, and what is likely to still be on the board
when your next pick comes round.

The season-value problem, stated plainly
----------------------------------------
The foundation projects **one week at a time** from a trailing four-game usage
window. Weeks 2-18 of an unplayed season are not projectable, because their
features require weeks 1-17 to have happened. So there is no season-long
projection in this system and none can be manufactured without building a
second, unvalidated model — which is exactly what the frozen-foundation rule
forbids.

The construction used instead keeps the two halves apart and labels both::

    season_value  =  expected_points_per_game   (model — the published board)
                  x  expected_games_played      (derived — historical availability)

The model supplies the rate and nothing else. History supplies availability,
volatility and trend — quantities the model does not estimate and never has.
The two are multiplied, never averaged, so no historical number is ever blended
into a projected one. :mod:`~nflfp.services.draft.valuation` carries the full
argument.

Where each piece lives
----------------------
::

    settings.py    DraftSettings, roster requirements — pure, validated pre-I/O
    order.py       snake ordering, pick numbers, whose turn it is — pure
    pool.py        DraftPlayer, and the retrieval that builds a pool from a session
    history.py     historical evidence: availability, consistency, trend — pure maths
    valuation.py   replacement level, scarcity, VOR, opportunity cost — pure
    engine.py      simulate_draft() — pure, seeded, no session and no globals
    aggregate.py   Monte Carlo aggregation over many drafts — pure
    service.py     the async orchestration: retrieve, then to_thread the maths

Only ``pool.py`` and ``service.py`` know what a database is. Everything that
decides anything is pure, seeded and unit-testable without Postgres, which is
the same split :mod:`nflfp.services.simulation` uses and for the same reason.

Nothing here is optimal in an absolute sense
--------------------------------------------
The engine finds the highest-value roster **under its own assumptions and the
data available to it**. Those assumptions — an opponent model that no ADP data
exists to validate, an availability model fitted on games played, a one-step
lookahead — are stated wherever a number is produced, and every simulated output
carries ``provenance: derived``.
"""

from __future__ import annotations

from .order import DraftOrder, DraftSlot
from .pool import DraftPlayer, DraftPool, HistoricalEvidence, HistoricalSeason
from .settings import (
    DEFAULT_ROSTER,
    DraftSettings,
    RosterRequirement,
    validate_settings,
)

__all__ = [
    "DEFAULT_ROSTER",
    "DraftOrder",
    "DraftPlayer",
    "DraftPool",
    "DraftSettings",
    "DraftSlot",
    "HistoricalEvidence",
    "HistoricalSeason",
    "RosterRequirement",
    "validate_settings",
]
