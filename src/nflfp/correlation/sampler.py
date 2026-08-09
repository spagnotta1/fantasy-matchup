"""Drawing one iteration's uniforms, independently or jointly.

The one thing a sampler may not do
----------------------------------
Both samplers produce a **uniform per player**, and the simulation engine turns
each uniform into points with ``curve.quantile(u)`` — unchanged from Phase 6A.
That is not an implementation detail, it is the safety property of the whole
phase: if every player's uniform is marginally ``U(0,1)``, then every player's
simulated points are marginally distributed exactly as Layer 3b published them,
whatever the sampler did to make them depend on each other.

So a correlation model can change the joint distribution and *cannot* change a
marginal. A bug that shifted a player's expected points would be a bug in the
sampler's marginals, and ``tests/test_correlation_marginals.py`` measures
precisely that, at the mean, the median, P10 and P90.

The Gaussian copula
-------------------
Chosen over the alternatives on the six criteria the phase set out:

**It preserves the stored marginals exactly.** Draw correlated standard normals
``z``, push each through its own normal CDF to get ``u = Phi(z)``, then through
the player's own quantile function. The middle step is a monotone map of a
standard normal, so ``u`` is exactly uniform by construction, not approximately
so. A method that sampled points directly — perturbing a projection, mixing two
draws, resampling residuals jointly — would have to *prove* it left the marginal
alone, and would generally not.

**It composes with a latent-factor structure**, so a correlated draw is
``O(players + games + teams)`` per iteration with no matrix and no Cholesky
factorisation. An empirical copula over historical joint outcomes was the main
alternative and was rejected here: the pairs available for any specific pair of
positions in any specific game are in the low thousands, so an empirical joint
would be resampling a handful of past afternoons rather than describing a
distribution — and it could not extrapolate to a lineup shape that has not
occurred.

**It is interpretable and it is checkable.** The parameter it consumes is a
correlation of normal scores, which is exactly the quantity
:mod:`nflfp.correlation.estimate` measures from the panel. Nothing is translated
between the fit and the sampler, so there is no conversion step to get wrong.

What it assumes, and where that bites
-------------------------------------
A Gaussian copula has **no tail dependence**: it makes two players slightly less
likely to have their ceiling weeks together than a real shared blowout would.
For a quarterback and his top receiver, whose genuinely spectacular weeks are the
same afternoon, this understates the top corner of the joint distribution.

The direction is the acceptable one — it errs toward the independent baseline
rather than past it — and fixing it needs a t-copula, whose degrees-of-freedom
parameter this panel cannot identify from four figures' worth of same-team pairs.
It is recorded as a limitation rather than papered over.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .model import CorrelationMode, CorrelationModel


@runtime_checkable
class Sampler(Protocol):
    """One iteration's worth of uniforms, one per player.

    Bound to a specific roster at construction, because both implementations
    want per-player work done once rather than 10,000 times. Deliberately *not*
    given the curves: a sampler that could see a player's distribution could
    accidentally start depending on it, and the marginal guarantee above rests
    on it not being able to.
    """

    #: What this sampler is, for the response's provenance block.
    mode: CorrelationMode
    #: Fitted structure behind it, or ``None`` for the independent sampler.
    model_version: str | None

    def draw(self, rng: random.Random) -> list[float]:
        """One uniform per player, in the order the roster was given."""
        ...


@dataclass(frozen=True)
class IndependentSampler:
    """Phase 6A's sampler, unchanged, behind the new interface.

    Retained rather than expressed as a correlated sampler with zero loadings,
    for two reasons. It is the production implementation until something beats
    it on held-out data, so it should not acquire a dependency on a model that
    has not passed. And it is the **baseline**: a comparison in which both arms
    run the candidate's code cannot detect a bug in the candidate's code.

    The draw order — every player in roster order, team A before team B — is the
    order the Phase 6A engine used, so a simulation run through this sampler
    reproduces a stored Phase 6A result bit for bit. A test pins that.
    """

    count: int
    mode: CorrelationMode = CorrelationMode.INDEPENDENT
    model_version: str | None = None

    def draw(self, rng: random.Random) -> list[float]:
        uniform = rng.random
        return [uniform() for _ in range(self.count)]


@dataclass(frozen=True)
class CorrelatedSampler:
    """Latent game and team factors, pushed through a Gaussian copula.

    Per iteration: one standard normal per **game**, one per **team**, one per
    **player**, combined as ``z = alpha*G + beta*T + delta*e`` and mapped with
    ``Phi``. Since ``alpha^2 + beta^2 + delta^2 = 1`` and the three draws are
    independent, ``z`` is standard normal and ``Phi(z)`` is exactly uniform.

    The loadings are frozen into flat lists at construction. A per-player
    dictionary lookup would be 140,000 of them in a default request, and the
    engine's cost is already dominated by per-iteration Python.
    """

    #: Index into the per-iteration game factors, one entry per player.
    game_of: tuple[int, ...]
    #: Index into the per-iteration team factors, one entry per player.
    team_of: tuple[int, ...]
    game_loading: tuple[float, ...]
    team_loading: tuple[float, ...]
    own_loading: tuple[float, ...]
    game_count: int
    team_count: int
    mode: CorrelationMode = CorrelationMode.GAME_ENVIRONMENT
    model_version: str | None = None

    def draw(self, rng: random.Random) -> list[float]:
        gauss = rng.gauss
        games = [gauss(0.0, 1.0) for _ in range(self.game_count)]
        teams = [gauss(0.0, 1.0) for _ in range(self.team_count)]
        erf = math.erf
        root_two = 1.4142135623730951
        return [
            0.5 * (1.0 + erf(
                (alpha * games[game] + beta * teams[team] + delta * gauss(0.0, 1.0))
                / root_two
            ))
            for game, team, alpha, beta, delta in zip(
                self.game_of, self.team_of,
                self.game_loading, self.team_loading, self.own_loading,
            )
        ]


@dataclass(frozen=True)
class RosterMember:
    """The only three things a sampler needs to know about a player.

    A deliberately tiny structure rather than
    :class:`~nflfp.services.simulation.SimulationInput`, so this package does not
    import the service layer and the dependency runs one way: simulation knows
    about correlation, correlation knows nothing about simulation.
    """

    position: str | None
    team: str | None
    game_id: str | None


def build_sampler(
    members: Sequence[RosterMember],
    *,
    mode: CorrelationMode,
    model: CorrelationModel | None = None,
) -> Sampler:
    """Prepare a sampler for one roster.

    Args:
        members: Every player in the simulation — **both lineups together**.
            This is the part that is easy to get wrong. Two lineups holding
            players from the same game are correlated *with each other*, which
            moves the win probability rather than only the intervals, so the two
            sides have to be sampled from one joint draw. Sampling each side
            against its own factors would model the two managers as watching
            different afternoons.
        mode: Which sampler to build.
        model: Required for :attr:`CorrelationMode.GAME_ENVIRONMENT`.

    Raises:
        ValueError: for a correlated mode with no model. Falling back to
            independence would silently answer a different question than the one
            the caller asked, and the caller has no way to see that happen.
    """
    if mode is CorrelationMode.INDEPENDENT:
        return IndependentSampler(count=len(members))
    if model is None:
        raise ValueError(
            f"correlation_mode {mode.value!r} needs a fitted correlation model; "
            "refusing to fall back to independence, which would report a "
            "correlated simulation that was not one"
        )

    games: dict[str, int] = {}
    teams: dict[str, int] = {}
    game_of: list[int] = []
    team_of: list[int] = []
    game_loading: list[float] = []
    team_loading: list[float] = []
    own_loading: list[float] = []

    for index, member in enumerate(members):
        loading = model.loading(member.position)
        # A player with no game is given a private factor rather than being
        # pooled with every other unknown. Sharing a factor across unrelated
        # players would invent correlation out of a missing column, which is
        # exactly the failure mode this phase exists to avoid.
        game_key = member.game_id or f"__no_game__{index}"
        team_key = (
            f"{game_key}::{member.team}" if member.team else f"__no_team__{index}"
        )
        game_of.append(games.setdefault(game_key, len(games)))
        team_of.append(teams.setdefault(team_key, len(teams)))
        game_loading.append(loading.game)
        team_loading.append(loading.team)
        own_loading.append(loading.idiosyncratic)

    return CorrelatedSampler(
        game_of=tuple(game_of),
        team_of=tuple(team_of),
        game_loading=tuple(game_loading),
        team_loading=tuple(team_loading),
        own_loading=tuple(own_loading),
        game_count=len(games),
        team_count=len(teams),
        model_version=model.version,
    )
