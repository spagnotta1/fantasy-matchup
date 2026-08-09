"""Does the correlated sampler behave the way the football says it should?

Marginal preservation says the candidate is *safe*. These tests say it is doing
the thing it claims to do, and — more usefully — that it stops doing it in the
cases where it should. Each one is a directional statement someone could have
made before the model was fitted, checked against the sampler's realised joint
distribution rather than against its parameters, because a structure can be
right on paper and wired up wrong.

The measurements are of **realised fantasy points**, not of the latent normals.
A Gaussian copula's correlation parameter is not the correlation of the outcomes
it produces — the monotone map through each player's skewed quantile function
shrinks it — so testing the parameter would be testing arithmetic already
covered by the estimator's own unit tests. Testing the points is testing what a
user gets.

One case in the brief is not testable here and is recorded rather than skipped
silently: **RB against the opposing defence**. There is no team-defence
projection in this system, for the reasons in
:mod:`nflfp.services.positions`, so a DST cannot enter a simulation and the pair
cannot be constructed. :class:`TestOpposingDefenceIsNotSimulable` states that
directly.
"""

from __future__ import annotations

import math
import random
from statistics import mean

import pytest

from nflfp.correlation import (
    CorrelationMode,
    CorrelationModel,
    IndependentSampler,
    PositionLoading,
    RosterMember,
    build_sampler,
)
from nflfp.correlation.model import (
    CORRELATION_MODEL_VERSION,
    NULL_MODEL,
    EstimationReport,
)
from nflfp.services import positions
from nflfp.services.distributions import OutcomeCurve
from nflfp.services.simulation import SimulationInput, simulate

ITERATIONS = 30_000


@pytest.fixture(scope="module")
def fitted() -> CorrelationModel:
    """The structure this phase actually fitted, to three decimals.

    Hard-coded rather than loaded from ``artifacts/``: a unit test that reads a
    generated file fails on a clean checkout, and pinning the values here means
    a refit that moves them has to be an explicit decision rather than a silent
    change in what the tests are asserting.

    The quarterback's team loading is *derived* from its game loading rather
    than typed out, because it is the anchor — ``beta_QB = sqrt(1 -
    alpha_QB^2)`` by construction, see
    :func:`nflfp.correlation.estimate._anchor`. Typing the rounded value would
    put it a ulp outside the unit disc and fail the variance check for
    arithmetic reasons.
    """
    quarterback_game = 0.399
    return CorrelationModel(
        version=CORRELATION_MODEL_VERSION,
        mode=CorrelationMode.GAME_ENVIRONMENT,
        loadings={
            "QB": PositionLoading(
                position="QB",
                game=quarterback_game,
                team=math.sqrt(1.0 - quarterback_game ** 2),
            ),
            "RB": PositionLoading(position="RB", game=0.028, team=0.044),
            "WR": PositionLoading(position="WR", game=0.176, team=0.162),
            "TE": PositionLoading(position="TE", game=0.132, team=0.166),
        },
        estimation=EstimationReport(
            projection_floor=6.0, rows=18_209, pairs=87_491,
            through_season=2025, through_week=18,
        ),
    )


def curve_for(base: float) -> OutcomeCurve:
    built = OutcomeCurve.from_percentiles(
        p10=base * 0.25, p25=base * 0.60, median=base * 0.92,
        p75=base * 1.35, p90=base * 1.95, expected=base,
    )
    assert built is not None
    return built


def player(name: str, position: str, base: float, team: str, game: str):
    return SimulationInput(
        player_id=name, name=name, slot=position, position=position,
        team=team, game_id=game, curve=curve_for(base),
        expected_points=base, floor=base * 0.25, ceiling=base * 1.95,
    )


def realised_correlation(players, model, *, seed=31337, iterations=ITERATIONS):
    """Pearson correlation of simulated **points**, pair by pair."""
    members = [
        RosterMember(position=p.position, team=p.team, game_id=p.game_id)
        for p in players
    ]
    sampler = build_sampler(
        members, mode=CorrelationMode.GAME_ENVIRONMENT, model=model
    )
    rng = random.Random(seed)
    quantiles = [p.curve.quantile for p in players]
    columns: list[list[float]] = [[] for _ in players]
    for _ in range(iterations):
        uniforms = sampler.draw(rng)
        for index, quantile in enumerate(quantiles):
            columns[index].append(quantile(uniforms[index]))

    def pearson(xs, ys):
        mx, my = mean(xs), mean(ys)
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        dx = sum((x - mx) ** 2 for x in xs) ** 0.5
        dy = sum((y - my) ** 2 for y in ys) ** 0.5
        return num / (dx * dy) if dx and dy else 0.0

    return {
        (players[i].player_id, players[j].player_id): pearson(columns[i], columns[j])
        for i in range(len(players))
        for j in range(i + 1, len(players))
    }


class TestSameTeamStack:
    """QB + WR + WR from one offence."""

    def test_a_quarterback_moves_with_his_own_receivers(self, fitted):
        stack = [
            player("QB", "QB", 20.0, "KC", "G1"),
            player("WR1", "WR", 14.0, "KC", "G1"),
            player("WR2", "WR", 10.0, "KC", "G1"),
        ]
        correlations = realised_correlation(stack, fitted)
        assert correlations[("QB", "WR1")] > 0.08
        assert correlations[("QB", "WR2")] > 0.08

    def test_the_stack_is_stronger_than_the_same_pair_split_across_teams(
        self, fitted
    ):
        # The claim the model makes and the estimate measured: sharing an
        # offence is worth more than sharing a game.
        together = realised_correlation(
            [
                player("QB", "QB", 20.0, "KC", "G1"),
                player("WR1", "WR", 14.0, "KC", "G1"),
            ],
            fitted,
        )[("QB", "WR1")]
        apart = realised_correlation(
            [
                player("QB", "QB", 20.0, "KC", "G1"),
                player("WR1", "WR", 14.0, "BUF", "G1"),
            ],
            fitted,
        )[("QB", "WR1")]
        assert together > apart > 0.0

    def test_stacking_widens_the_team_interval(self, fitted):
        stack = [
            player("QB", "QB", 20.0, "KC", "G1"),
            player("WR1", "WR", 14.0, "KC", "G1"),
            player("TE1", "TE", 10.0, "KC", "G1"),
        ]
        spread = [
            player("QB", "QB", 20.0, "KC", "G1"),
            player("WR1", "WR", 14.0, "SF", "G2"),
            player("TE1", "TE", 10.0, "DAL", "G3"),
        ]
        opponent = [player("X", "RB", 40.0, "NYJ", "G9")]

        widths = []
        for lineup in (spread, stack):
            members = [
                RosterMember(position=p.position, team=p.team, game_id=p.game_id)
                for p in (*lineup, *opponent)
            ]
            sampler = build_sampler(
                members, mode=CorrelationMode.GAME_ENVIRONMENT, model=fitted
            )
            result, _, _, _ = simulate(
                lineup, opponent, iterations=ITERATIONS, seed=8, sampler=sampler
            )
            widths.append(result.p90 - result.p10)

        spread_width, stack_width = widths
        assert stack_width > spread_width, (
            "a stacked lineup must have a wider outcome interval than the same "
            "three projections spread across three games — that is the entire "
            "practical consequence of modelling correlation"
        )


class TestOpposingPlayers:
    """Two players in one game on opposite teams."""

    def test_opposing_quarterbacks_move_together(self, fitted):
        pair = [
            player("QB_H", "QB", 20.0, "KC", "G1"),
            player("QB_A", "QB", 19.0, "BUF", "G1"),
        ]
        correlation = realised_correlation(pair, fitted)[("QB_H", "QB_A")]
        # Positive: a shootout scores both. Modest: it is a game effect, an
        # order of magnitude weaker than sharing an offence.
        assert 0.02 < correlation < 0.20

    def test_a_quarterback_and_an_opposing_receiver_are_weakly_positive(self, fitted):
        pair = [
            player("QB_H", "QB", 20.0, "KC", "G1"),
            player("WR_A", "WR", 14.0, "BUF", "G1"),
        ]
        correlation = realised_correlation(pair, fitted)[("QB_H", "WR_A")]
        assert 0.0 < correlation < 0.10

    def test_opposing_is_weaker_than_teammate_for_every_pass_catcher(self, fitted):
        for position in ("WR", "TE"):
            same = realised_correlation(
                [
                    player("QB", "QB", 20.0, "KC", "G1"),
                    player("P", position, 12.0, "KC", "G1"),
                ],
                fitted,
            )[("QB", "P")]
            opposing = realised_correlation(
                [
                    player("QB", "QB", 20.0, "KC", "G1"),
                    player("P", position, 12.0, "BUF", "G1"),
                ],
                fitted,
            )[("QB", "P")]
            assert same > opposing, position


class TestUnrelatedPlayers:
    """The case that must come out at zero, and the one most easily got wrong."""

    def test_players_in_different_games_are_independent(self, fitted):
        pair = [
            player("A", "QB", 20.0, "KC", "G1"),
            player("B", "QB", 19.0, "SF", "G2"),
        ]
        correlation = realised_correlation(pair, fitted)[("A", "B")]
        assert abs(correlation) < 0.02

    def test_players_with_no_game_do_not_share_a_factor(self, fitted):
        # Two players with a missing game_id must not be pooled into one
        # "unknown" game. That would manufacture correlation out of a null
        # column, which is the exact failure this phase exists to avoid.
        pair = [
            player("A", "QB", 20.0, "KC", None),
            player("B", "QB", 19.0, "SF", None),
        ]
        correlation = realised_correlation(pair, fitted)[("A", "B")]
        assert abs(correlation) < 0.02

    def test_two_running_backs_are_near_independent_by_measurement(self, fitted):
        # Not a design choice: the panel measured RB loadings near zero, and the
        # sampler should therefore reproduce near-independence for the pair.
        pair = [
            player("RB1", "RB", 14.0, "KC", "G1"),
            player("RB2", "RB", 12.0, "BUF", "G1"),
        ]
        correlation = realised_correlation(pair, fitted)[("RB1", "RB2")]
        assert abs(correlation) < 0.03


class TestDegenerateCases:
    """Where the correlated engine must collapse onto the independent one."""

    def test_a_single_player_per_side_is_effectively_identical(self, fitted):
        team_a = [player("A", "QB", 20.0, "KC", "G1")]
        team_b = [player("B", "RB", 19.0, "SF", "G2")]
        results = {}
        for label, mode in (
            ("independent", CorrelationMode.INDEPENDENT),
            ("correlated", CorrelationMode.GAME_ENVIRONMENT),
        ):
            members = [
                RosterMember(position=p.position, team=p.team, game_id=p.game_id)
                for p in (*team_a, *team_b)
            ]
            sampler = build_sampler(
                members, mode=mode,
                model=None if mode is CorrelationMode.INDEPENDENT else fitted,
            )
            results[label] = simulate(
                team_a, team_b, iterations=ITERATIONS, seed=5, sampler=sampler
            )

        base, candidate = results["independent"], results["correlated"]
        # With one player a side and no shared game there is nothing to
        # correlate, so the two engines are answering an identical question and
        # differ only by Monte Carlo noise.
        assert candidate[0].win_probability == pytest.approx(
            base[0].win_probability, abs=0.02
        )
        assert candidate[0].expected_score == pytest.approx(
            base[0].expected_score, abs=0.4
        )
        assert candidate[0].p90 == pytest.approx(base[0].p90, abs=1.0)

    def test_a_null_structure_reproduces_independence(self):
        # NULL_MODEL exists so that "correlation switched off" is a *model*
        # rather than a different code path. If this drifts, the correlated
        # sampler has acquired behaviour its loadings do not explain.
        players = [
            player("A", "QB", 20.0, "KC", "G1"),
            player("B", "WR", 14.0, "KC", "G1"),
        ]
        correlation = realised_correlation(players, NULL_MODEL)[("A", "B")]
        assert abs(correlation) < 0.02

    def test_evenly_matched_lineups_sit_at_a_coin_flip(self, fitted):
        # Two lineups of identical projections in *different* games. Correlation
        # must not introduce a systematic edge for either side; if it did, the
        # sampler would be favouring whichever side it happened to draw first.
        team_a = [
            player("A1", "QB", 20.0, "KC", "G1"),
            player("A2", "WR", 14.0, "KC", "G1"),
            player("A3", "RB", 11.0, "KC", "G1"),
        ]
        team_b = [
            player("B1", "QB", 20.0, "SF", "G2"),
            player("B2", "WR", 14.0, "SF", "G2"),
            player("B3", "RB", 11.0, "SF", "G2"),
        ]
        members = [
            RosterMember(position=p.position, team=p.team, game_id=p.game_id)
            for p in (*team_a, *team_b)
        ]
        sampler = build_sampler(
            members, mode=CorrelationMode.GAME_ENVIRONMENT, model=fitted
        )
        result_a, result_b, mean_margin, _ = simulate(
            team_a, team_b, iterations=ITERATIONS, seed=11, sampler=sampler
        )
        assert result_a.win_probability == pytest.approx(0.50, abs=0.02)
        assert mean_margin == pytest.approx(0.0, abs=1.0)

    def test_a_correlated_mode_without_a_model_is_refused(self):
        # Falling back to independence would report a correlated simulation that
        # was not one, and the caller would have no way to see it happen.
        with pytest.raises(ValueError, match="needs a fitted correlation model"):
            build_sampler(
                [RosterMember(position="QB", team="KC", game_id="G1")],
                mode=CorrelationMode.GAME_ENVIRONMENT,
                model=None,
            )

    def test_a_sampler_built_for_a_different_roster_is_refused(self, fitted):
        from nflfp.services.errors import InvalidRequest

        team_a = [player("A", "QB", 20.0, "KC", "G1")]
        team_b = [player("B", "RB", 19.0, "SF", "G2")]
        with pytest.raises(InvalidRequest, match="different roster"):
            simulate(
                team_a, team_b, iterations=100, seed=1,
                sampler=IndependentSampler(count=9),
            )


class TestOpposingDefenceIsNotSimulable:
    """The brief's RB-vs-defence case, recorded rather than quietly skipped."""

    def test_team_defence_has_no_projection_so_the_pair_cannot_be_built(self):
        support = positions.describe("DST")
        assert support is not None
        assert not support.is_projected, (
            "a team-defence projection now exists, so the RB-vs-opposing-defence "
            "relationship has become measurable and this phase's correlation "
            "estimate should be extended to cover it"
        )

    def test_the_structure_covers_only_the_projected_positions(self, fitted):
        assert set(fitted.loadings) == {"QB", "RB", "WR", "TE"}
        # An unknown position is fully idiosyncratic rather than assigned a
        # neighbouring position's loadings. Guessing would be inventing a
        # correlation for a position nothing was measured on.
        unknown = fitted.loading("DST")
        assert unknown.game == 0.0
        assert unknown.team == 0.0
        assert unknown.idiosyncratic == 1.0
