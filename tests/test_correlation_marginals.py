"""The guarantee that makes a correlation model safe to ship at all.

A correlated simulator is a dependency structure over distributions somebody
else measured. The moment it starts moving a player's expected points it has
stopped being that and become a second, unvalidated projection model — one that
would inherit none of Layer 3b's held-out guarantees while looking exactly like
it had.

So this file measures one property, four ways, on every position: the marginal
distribution of a player's simulated points is the same whether the run was
independent or correlated. Mean, median, P10, P90. Nothing here checks that the
correlation is *right* — that is
``tests/test_correlation_stress.py`` and the historical backtest — only that it
is confined to the joint distribution where it belongs.

Tolerances are Monte Carlo tolerances, derived rather than guessed. At 40,000
iterations the standard error on the mean of a distribution with an 8-point
standard deviation is 0.04 points, so a 0.25-point band is roughly six standard
errors: loose enough never to flake, tight enough that a real shift — the
smallest interesting one being a few percent of a player's projection — fails it
several times over.
"""

from __future__ import annotations

import random

import pytest

from nflfp.correlation import (
    CorrelationMode,
    CorrelationModel,
    PositionLoading,
    RosterMember,
    build_sampler,
)
from nflfp.correlation.model import CORRELATION_MODEL_VERSION, EstimationReport
from nflfp.services.distributions import OutcomeCurve
from nflfp.services.simulation import SimulationInput, simulate

#: Enough that the sampling error is far below the tolerance, few enough that
#: the file runs in a few seconds.
ITERATIONS = 40_000

#: Points. See the module docstring for the derivation.
MEAN_TOLERANCE = 0.25
PERCENTILE_TOLERANCE = 0.60


@pytest.fixture(scope="module")
def model() -> CorrelationModel:
    """A structure with deliberately *large* loadings.

    Roughly double the fitted values, because this file is testing that the
    marginal survives correlation and a weak structure would pass by not doing
    very much. If the marginal holds at these loadings it holds at the fitted
    ones.
    """
    return CorrelationModel(
        version=CORRELATION_MODEL_VERSION,
        mode=CorrelationMode.GAME_ENVIRONMENT,
        loadings={
            "QB": PositionLoading(position="QB", game=0.55, team=0.80),
            "RB": PositionLoading(position="RB", game=0.30, team=0.40),
            "WR": PositionLoading(position="WR", game=0.40, team=0.45),
            "TE": PositionLoading(position="TE", game=0.35, team=0.42),
        },
        estimation=EstimationReport(
            projection_floor=6.0, rows=0, pairs=0,
            through_season=2025, through_week=18,
        ),
    )


def curve_for(base: float) -> OutcomeCurve:
    """A right-skewed curve of roughly the shape Layer 3b publishes."""
    built = OutcomeCurve.from_percentiles(
        p10=base * 0.25, p25=base * 0.60, median=base * 0.92,
        p75=base * 1.35, p90=base * 1.95, expected=base,
    )
    assert built is not None
    return built


def player(index: int, position: str, base: float, team: str, game: str):
    return SimulationInput(
        player_id=f"p{index}", name=f"Player {index}", slot=position,
        position=position, team=team, game_id=game, curve=curve_for(base),
        expected_points=base, floor=base * 0.25, ceiling=base * 1.95,
    )


@pytest.fixture(scope="module")
def roster():
    """A matchup engineered so every correlation channel is live at once.

    Both lineups draw from the same two games, both contain a QB stacked with
    his own receivers, and the two sides face each other inside one game. If a
    sampler were going to disturb a marginal, this is where it would.
    """
    team_a = [
        player(0, "QB", 20.0, "KC", "G1"),
        player(1, "WR", 15.0, "KC", "G1"),
        player(2, "TE", 11.0, "KC", "G1"),
        player(3, "RB", 13.0, "BUF", "G1"),
        player(4, "WR", 9.0, "SF", "G2"),
        player(5, "RB", 7.5, "SF", "G2"),
        player(6, "WR", 12.0, "DAL", "G2"),
    ]
    team_b = [
        player(7, "QB", 18.0, "BUF", "G1"),
        player(8, "WR", 14.0, "BUF", "G1"),
        player(9, "TE", 8.0, "SF", "G2"),
        player(10, "RB", 16.0, "KC", "G1"),
        player(11, "WR", 10.0, "DAL", "G2"),
        player(12, "RB", 11.0, "DAL", "G2"),
        player(13, "TE", 9.5, "SF", "G2"),
    ]
    return team_a, team_b


def run(roster, mode, model, seed=4242):
    team_a, team_b = roster
    members = [
        RosterMember(position=p.position, team=p.team, game_id=p.game_id)
        for p in (*team_a, *team_b)
    ]
    sampler = build_sampler(
        members, mode=mode,
        model=None if mode is CorrelationMode.INDEPENDENT else model,
    )
    return simulate(
        team_a, team_b, iterations=ITERATIONS, seed=seed, sampler=sampler
    )


class TestPerPlayerMeans:
    """The expected points of every individual player, both ways."""

    def test_every_player_keeps_their_simulated_mean(self, roster, model):
        independent = run(roster, CorrelationMode.INDEPENDENT, model)
        correlated = run(roster, CorrelationMode.GAME_ENVIRONMENT, model)

        for side in (0, 1):
            for base, candidate in zip(
                independent[side].players, correlated[side].players
            ):
                assert base.player_id == candidate.player_id
                assert candidate.simulated_mean == pytest.approx(
                    base.simulated_mean, abs=MEAN_TOLERANCE
                ), (
                    f"{base.player_id} ({base.position}) shifted from "
                    f"{base.simulated_mean:.3f} to {candidate.simulated_mean:.3f} "
                    "under correlation — the sampler is changing a marginal, "
                    "which makes it a projection model rather than a "
                    "dependency structure"
                )

    def test_a_players_mean_still_tracks_their_stored_projection(self, roster, model):
        # Not exact: distributions.py extends the upper tail 2.5x against 1.5x
        # on the lower, so the reconstruction sits a few percent above the
        # stored mean. That gap is Phase 6A's and is unchanged here — which is
        # the point. It must not *grow* under correlation.
        independent = run(roster, CorrelationMode.INDEPENDENT, model)
        correlated = run(roster, CorrelationMode.GAME_ENVIRONMENT, model)
        for side in (0, 1):
            for base, candidate in zip(
                independent[side].players, correlated[side].players
            ):
                assert base.expected_points is not None
                independent_gap = base.simulated_mean - base.expected_points
                correlated_gap = candidate.simulated_mean - base.expected_points
                assert correlated_gap == pytest.approx(
                    independent_gap, abs=MEAN_TOLERANCE
                )


class TestPerPlayerQuantiles:
    """Mean-preservation is necessary and not sufficient — check the shape."""

    @pytest.mark.parametrize("probability", [0.10, 0.50, 0.90])
    def test_marginal_quantiles_survive_correlation(
        self, roster, model, probability
    ):
        team_a, team_b = roster
        members = [
            RosterMember(position=p.position, team=p.team, game_id=p.game_id)
            for p in (*team_a, *team_b)
        ]
        samples = {}
        for label, mode in (
            ("independent", CorrelationMode.INDEPENDENT),
            ("correlated", CorrelationMode.GAME_ENVIRONMENT),
        ):
            sampler = build_sampler(
                members, mode=mode,
                model=None if mode is CorrelationMode.INDEPENDENT else model,
            )
            rng = random.Random(99)
            columns: list[list[float]] = [[] for _ in members]
            quantiles = [p.curve.quantile for p in (*team_a, *team_b)]
            for _ in range(ITERATIONS):
                uniforms = sampler.draw(rng)
                for index, quantile in enumerate(quantiles):
                    columns[index].append(quantile(uniforms[index]))
            for column in columns:
                column.sort()
            samples[label] = columns

        for index, (base, candidate) in enumerate(
            zip(samples["independent"], samples["correlated"])
        ):
            position = int(probability * (ITERATIONS - 1))
            assert candidate[position] == pytest.approx(
                base[position], abs=PERCENTILE_TOLERANCE
            ), (
                f"player {index} P{int(probability * 100)} moved from "
                f"{base[position]:.3f} to {candidate[position]:.3f}"
            )


class TestUniformity:
    """The property everything above rests on, checked at the source."""

    def test_correlated_uniforms_are_marginally_uniform(self, roster, model):
        team_a, team_b = roster
        members = [
            RosterMember(position=p.position, team=p.team, game_id=p.game_id)
            for p in (*team_a, *team_b)
        ]
        sampler = build_sampler(
            members, mode=CorrelationMode.GAME_ENVIRONMENT, model=model
        )
        rng = random.Random(7)
        histograms = [[0] * 10 for _ in members]
        for _ in range(ITERATIONS):
            for index, value in enumerate(sampler.draw(rng)):
                assert 0.0 <= value <= 1.0
                histograms[index][min(int(value * 10), 9)] += 1

        # Each bin should hold a tenth. Binomial SD at n=40,000, p=0.1 is 60
        # counts, i.e. 0.0015 in share terms; the band below is over six of
        # those, so it catches a systematically warped marginal and not noise.
        for index, histogram in enumerate(histograms):
            for bin_index, count in enumerate(histogram):
                share = count / ITERATIONS
                assert share == pytest.approx(0.10, abs=0.01), (
                    f"player {index} bin {bin_index} holds {share:.4f} of the "
                    "draws; a correlated uniform must still be uniform"
                )


class TestTeamTotalsMoveOnlyInSpread:
    """Correlation is allowed to widen a team total. It is not allowed to move it."""

    def test_the_centre_holds_and_the_spread_grows(self, roster, model):
        independent = run(roster, CorrelationMode.INDEPENDENT, model)
        correlated = run(roster, CorrelationMode.GAME_ENVIRONMENT, model)

        for side in (0, 1):
            base, candidate = independent[side], correlated[side]
            assert candidate.expected_score == pytest.approx(
                base.expected_score, abs=1.0
            ), "a correlated team total must not drift from the independent one"
            # Positive loadings can only add covariance, so the interval must
            # widen. A correlated run that came out *narrower* would mean the
            # factors were subtracting variance, which this structure cannot do.
            assert (candidate.p90 - candidate.p10) > (base.p90 - base.p10)
