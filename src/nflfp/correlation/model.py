"""The fitted correlation structure, and the reasoning that chose its shape.

What the data said
------------------
Measured on 38,061 leakage-free player-weeks from 2019-2025, PIT-transformed
through each player's own published distribution and restricted to the startable
population a lineup actually draws from (projected >= 6.0 half-PPR points):

======================  =========  ======
pair                    correlation      n
======================  =========  ======
QB - WR, same team          +0.236   8,382
QB - TE, same team          +0.218   2,350
QB - QB, opposing           +0.143   2,279
QB - WR, opposing           +0.073   8,365
QB - RB, same team          +0.062   5,361
QB - TE, opposing           +0.061   2,332
WR - WR, opposing           +0.050   7,841
WR - TE, opposing           +0.046   4,437
QB - RB, opposing           +0.031   5,350
WR - WR, same team          +0.004   5,497
RB - WR, same team          -0.014   9,942
RB - RB, same team          -0.037   1,539
RB - RB, opposing           -0.039   3,214
======================  =========  ======

Three facts drive everything below.

**The signal is real and it is concentrated on the quarterback.** A QB and his
own pass-catchers move together at +0.22 to +0.26, stable in every one of the
seven seasons measured separately. That is not a subtle effect and it is exactly
the pair a fantasy manager deliberately assembles.

**There is a genuine game-level effect, and it is small.** Opposing
quarterbacks correlate +0.14 and opposing pass-catchers +0.05: two teams in a
shootout both score. It is an order of magnitude weaker than the same-team
effect, which is why a *game* factor alone would not have been enough.

**Pass-catchers on the same team do not move together.** WR-WR same-team is
+0.004 against +0.050 for the same pair on opposite teams — the same-team figure
is *lower*. Target competition cancels the shared offence almost exactly. This
is the fact that rules out the obvious model, and it is discussed below.

Why a latent-factor model and not a correlation matrix
------------------------------------------------------
A player-by-player matrix for fourteen players is 91 free parameters estimated
from the pairs that happen to be in one lineup, has to be repaired to positive
semi-definiteness after every fit, and costs a Cholesky factorisation per
simulated matchup. A two-factor model is eight parameters estimated from tens of
thousands of pairs, is positive semi-definite **by construction** because it is
built from independent normals, and samples in O(players) per iteration.

The structure, in full::

        game environment  G_g              one draw per game
                 |
        +--------+--------+
        |                 |
    team offence T_h   team offence T_a    one draw per team
        |                 |
      players           players            one draw per player

    z_i = alpha_p * G_g  +  beta_p * T_t  +  delta_p * e_i

with ``alpha_p^2 + beta_p^2 + delta_p^2 = 1``, so every ``z_i`` is a standard
normal and the marginal is untouched. The implied correlations are then

* same team:  ``alpha_p alpha_q + beta_p beta_q``
* opposing:   ``alpha_p alpha_q``
* different games: exactly zero.

Each is a statement someone can check against the table above, which is the
property a giant matrix does not have.

What this shape cannot represent, stated rather than discovered
---------------------------------------------------------------
A factor model gives two players at the *same* position identical loadings, so
their correlation is ``alpha_p^2 + beta_p^2`` and **cannot be negative**. Three
measured cells are therefore unreachable:

* ``WR-WR same team = +0.004`` — the model must predict at least ``alpha_WR^2``,
  and the fit lands high. This is the largest misfit and it is reported in
  :attr:`EstimationReport.residuals` rather than hidden.
* ``RB-RB opposing = -0.039`` — real game script: the leading team runs the
  clock out while the trailing team abandons the run. A single positive game
  factor cannot produce it.
* ``QB-QB same team = -0.357`` — two quarterbacks for one team in one week is a
  relief appearance, which is zero-sum by construction. It is excluded from the
  fit entirely (see :data:`EXCLUDED_CELLS`); it is not a fantasy lineup that can
  legally exist in the supported formats, and leaving it in would drag the
  quarterback loadings toward an artifact.

All three are small in absolute terms and all three are in the *conservative*
direction — the model slightly over-correlates pairs it cannot pull negative,
which widens intervals rather than narrowing them. That is the direction to err
in for a phase whose stated risk is overconfidence.

Whether any of this is an improvement is not decided here. It is decided by
:mod:`nflfp.correlation.evaluate` on held-out matchups.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

#: Bumped whenever the *shape* of the model or the estimation procedure changes,
#: not when a refit produces new numbers. A stored simulation naming version 1
#: must mean the same thing forever; the fitted values travel with the model in
#: ``fitted_through`` and ``estimation``.
CORRELATION_MODEL_VERSION = "1.0.0"

#: Positions the structure covers — the ones Layer 3b projects.
POSITIONS: tuple[str, ...] = ("QB", "RB", "WR", "TE")

#: Cells left out of the fit, with the reason. Excluding a cell is a modelling
#: claim and belongs in the source, not in a script that ran once.
EXCLUDED_CELLS: Mapping[tuple[str, str, str], str] = {
    ("QB", "QB", "same"): (
        "two quarterbacks on one team in one week is a relief appearance, which "
        "is zero-sum by construction (-0.357 measured) rather than a shared "
        "environment; no supported lineup format can contain the pair"
    ),
}


class CorrelationMode(str, Enum):
    """How a simulation drew its player outcomes.

    Travels into the API response, so the string values are a public contract.
    """

    #: Every player from their own uniform. The Phase 6A engine, unchanged.
    INDEPENDENT = "independent"
    #: Shared game and team factors, per :class:`CorrelationModel`.
    GAME_ENVIRONMENT = "game_environment"


@dataclass(frozen=True)
class PositionLoading:
    """How much of one position's outcome is shared, and with whom.

    Both loadings are non-negative. The sign is a gauge freedom in a factor
    model — flipping the sign of a factor and of every loading on it gives the
    same correlations — so fixing them non-negative removes an arbitrary choice.
    The cost is that the model cannot produce a negative correlation at all,
    which is the limitation named in the module docstring.
    """

    position: str
    #: Loading on the game environment. Drives correlation with *everyone* in
    #: the game, including opponents.
    game: float
    #: Additional loading on this team's offence. Drives the extra correlation
    #: teammates have over opponents.
    team: float

    def __post_init__(self) -> None:
        for name, value in (("game", self.game), ("team", self.team)):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{self.position}.{name} must be in [0, 1], got {value}")
        if self.game ** 2 + self.team ** 2 > 1.0 + 1e-9:
            raise ValueError(
                f"{self.position}: game^2 + team^2 = "
                f"{self.game ** 2 + self.team ** 2:.4f} exceeds 1, which would "
                "make the idiosyncratic variance negative and the marginal "
                "wider than the distribution it came from"
            )

    @property
    def idiosyncratic(self) -> float:
        """The player's own share. What is left once the factors are removed."""
        return math.sqrt(max(0.0, 1.0 - self.game ** 2 - self.team ** 2))

    @property
    def shared_variance(self) -> float:
        """Fraction of this position's variance explained by the two factors."""
        return self.game ** 2 + self.team ** 2


@dataclass(frozen=True)
class CellEstimate:
    """One measured cell of the empirical correlation table."""

    position_a: str
    position_b: str
    #: ``"same"`` or ``"opp"`` — teammates or opponents within one game.
    relation: str
    n: int
    correlation: float

    @property
    def standard_error(self) -> float:
        """Approximate SE of a correlation, ``(1 - r^2) / sqrt(n)``.

        An **understatement**, and deliberately labelled as one: pairs drawn
        from the same game are not independent observations, so the effective
        sample size is below ``n``. It is reported to separate "measured at
        +0.24" from "measured at +0.03 and indistinguishable from zero", which
        it does adequately, not to support a significance test.
        """
        if self.n < 4:
            return float("nan")
        return (1.0 - self.correlation ** 2) / math.sqrt(self.n)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.position_a, self.position_b, self.relation)


@dataclass(frozen=True)
class EstimationReport:
    """What the fit saw and how well it reproduced it.

    Carried on the model rather than printed once, because the residuals are the
    honest part: a reader who wants to know whether to believe a simulated P90
    is entitled to see which cells the structure could not reach.
    """

    #: Projection floor the estimation sample was restricted to.
    projection_floor: float
    #: Player-weeks in the estimation sample.
    rows: int
    #: Pairs contributing to the fit.
    pairs: int
    #: Last week included. The leakage boundary, recorded on the artifact.
    through_season: int
    through_week: int
    cells: tuple[CellEstimate, ...] = ()
    #: ``(cell key, observed, fitted)`` for every cell, worst misfit first.
    residuals: tuple[tuple[str, float, float], ...] = ()
    #: n-weighted RMS gap between observed and fitted correlations.
    weighted_rmse: float = 0.0

    @property
    def through(self) -> tuple[int, int]:
        """The last week in the estimation sample — the leakage boundary itself."""
        return (self.through_season, self.through_week)

    def worst(self, count: int = 5) -> tuple[tuple[str, float, float], ...]:
        return self.residuals[:count]


@dataclass(frozen=True)
class CorrelationModel:
    """A fitted dependency structure over Layer 3b's marginals.

    Holds no projection and no distribution. Handed a pair of positions and
    whether they share a team, it returns a correlation; that is the whole of
    its interface to the sampler.
    """

    version: str
    mode: CorrelationMode
    loadings: Mapping[str, PositionLoading]
    estimation: EstimationReport
    profile: str = "half_ppr"
    model_name: str = "shrinkage_eb"

    def loading(self, position: str | None) -> PositionLoading:
        """The loading for a position, defaulting to fully idiosyncratic.

        An unrecognised or missing position gets zero on both factors, which
        makes it independent of everything. That is the only safe default: a
        position the fit never saw has no measured relationship to anything, and
        inventing one is precisely what this phase exists to avoid.
        """
        if position is None:
            return PositionLoading(position="UNKNOWN", game=0.0, team=0.0)
        return self.loadings.get(
            position, PositionLoading(position=position, game=0.0, team=0.0)
        )

    def correlation(
        self, position_a: str | None, position_b: str | None, *, same_team: bool
    ) -> float:
        """Implied correlation between two players in the same game.

        Callers wanting the cross-game answer do not need this: it is zero, and
        the sampler expresses that by giving different games independent
        factors rather than by consulting a matrix.
        """
        a = self.loading(position_a)
        b = self.loading(position_b)
        shared = a.game * b.game
        if same_team:
            shared += a.team * b.team
        return shared

    def describe(self) -> str:
        """The fitted structure as a table, for a report or a log line."""
        lines = [
            f"correlation model {self.version} ({self.mode.value}), "
            f"{self.profile} / {self.model_name}",
            f"  fitted on {self.estimation.rows:,} player-week(s), "
            f"{self.estimation.pairs:,} pair(s), through "
            f"{self.estimation.through_season}w{self.estimation.through_week:02d}, "
            f"projection floor {self.estimation.projection_floor:.1f}",
            f"  {'position':<10}{'game':>8}{'team':>8}{'own':>8}{'shared':>9}",
        ]
        for position in POSITIONS:
            loading = self.loading(position)
            lines.append(
                f"  {position:<10}{loading.game:>8.3f}{loading.team:>8.3f}"
                f"{loading.idiosyncratic:>8.3f}{loading.shared_variance:>9.3f}"
            )
        lines.append(f"  weighted RMSE {self.estimation.weighted_rmse:.4f}")
        lines.append("  implied correlations (observed in brackets):")
        observed = {c.key: c.correlation for c in self.estimation.cells}
        for index, position_a in enumerate(POSITIONS):
            for position_b in POSITIONS[index:]:
                for relation, same in (("same", True), ("opp", False)):
                    key = (position_a, position_b, relation)
                    if key in EXCLUDED_CELLS:
                        continue
                    fitted = self.correlation(position_a, position_b, same_team=same)
                    seen = observed.get(key)
                    seen_text = f"[{seen:+.3f}]" if seen is not None else "[  --  ]"
                    lines.append(
                        f"    {position_a}-{position_b} {relation:<5} "
                        f"{fitted:+.3f} {seen_text}"
                    )
        return "\n".join(lines)

    # -- persistence --------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "mode": self.mode.value,
            "profile": self.profile,
            "model_name": self.model_name,
            "loadings": {
                position: {"game": loading.game, "team": loading.team}
                for position, loading in sorted(self.loadings.items())
            },
            "estimation": asdict(self.estimation),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "CorrelationModel":
        estimation = dict(payload["estimation"])  # type: ignore[arg-type]
        cells = tuple(
            CellEstimate(**cell) for cell in estimation.pop("cells", ())  # type: ignore[arg-type]
        )
        residuals = tuple(
            (key, float(observed), float(fitted))
            for key, observed, fitted in estimation.pop("residuals", ())  # type: ignore[misc]
        )
        return cls(
            version=str(payload["version"]),
            mode=CorrelationMode(payload["mode"]),
            profile=str(payload.get("profile", "half_ppr")),
            model_name=str(payload.get("model_name", "shrinkage_eb")),
            loadings={
                position: PositionLoading(
                    position=position, game=float(v["game"]), team=float(v["team"])
                )
                for position, v in payload["loadings"].items()  # type: ignore[union-attr]
            },
            estimation=EstimationReport(cells=cells, residuals=residuals, **estimation),  # type: ignore[arg-type]
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "CorrelationModel":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


#: An explicitly null structure. Every correlation is zero, so a
#: :class:`~nflfp.correlation.sampler.CorrelatedSampler` built on it reproduces
#: the independent sampler. Used by the stress tests, which need "correlation
#: switched off" to be a *model* rather than a different code path.
NULL_MODEL = CorrelationModel(
    version=CORRELATION_MODEL_VERSION,
    mode=CorrelationMode.GAME_ENVIRONMENT,
    loadings={
        position: PositionLoading(position=position, game=0.0, team=0.0)
        for position in POSITIONS
    },
    estimation=EstimationReport(
        projection_floor=0.0, rows=0, pairs=0, through_season=0, through_week=0
    ),
)
