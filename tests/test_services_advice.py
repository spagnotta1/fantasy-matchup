"""Start/sit — the only place the app recommends rather than reports.

Every test here guards against a specific way a recommendation engine goes
quietly wrong: manufacturing precision from a half-point gap, treating a mean
as a verdict, assuming independence between teammates, or ranking a player who
has been ruled out.
"""

from __future__ import annotations

import pytest

from nflfp.services import advice, grading
from nflfp.services.dto import InjuryContext, PlayerProjection, PlayerRef, PointDistribution
from nflfp.services.errors import InvalidRequest


def player(
    player_id: str,
    *,
    expected: float,
    floor: float | None = None,
    ceiling: float | None = None,
    spread: float = 6.0,
    team: str = "KC",
    game_id: str | None = "2025_10_KC_BUF",
    injury: InjuryContext | None = None,
    extrapolated: bool = False,
) -> PlayerProjection:
    return PlayerProjection(
        player=PlayerRef(player_id=player_id, name=player_id.upper(), position="WR", team=team),
        season=2025,
        week=10,
        team=team,
        opponent="BUF",
        is_home=True,
        game_id=game_id,
        points=PointDistribution(
            scoring_profile="half_ppr",
            expected=expected,
            predicted=expected,
            floor=floor if floor is not None else max(0.0, expected - spread),
            p25=max(0.0, expected - spread / 2),
            median=expected - 0.4,
            p75=expected + spread / 2,
            ceiling=ceiling if ceiling is not None else expected + spread * 1.6,
            extrapolated=extrapolated,
        ),
        injury=injury,
    )


class TestVerdicts:
    def test_a_half_point_gap_is_a_toss_up(self):
        # The failure this module exists to prevent: "start A, 12.4 vs 11.8"
        # states an edge smaller than the model's own mean absolute error.
        result = advice.start_sit(player("a", expected=12.4), player("b", expected=11.8))
        assert result.verdict == "toss_up"
        assert result.recommended is None

    def test_a_large_gap_produces_a_clear_call(self):
        result = advice.start_sit(
            player("stud", expected=21.0, spread=4.0),
            player("bench", expected=5.0, spread=4.0),
        )
        assert result.verdict == "clear"
        assert result.recommended == "stud"

    def test_the_win_probability_is_reported_from_a_s_perspective(self):
        result = advice.start_sit(
            player("weak", expected=5.0, spread=4.0),
            player("strong", expected=21.0, spread=4.0),
        )
        assert result.win_probability < 0.5
        assert result.recommended == "strong"

    def test_entries_carry_complementary_win_probabilities(self):
        result = advice.start_sit(player("a", expected=15.0), player("b", expected=9.0))
        assert result.a.win_probability is not None and result.b.win_probability is not None
        assert result.a.win_probability + result.b.win_probability == pytest.approx(1.0)

    def test_the_verdict_agrees_with_the_shared_threshold(self):
        result = advice.start_sit(player("a", expected=16.0), player("b", expected=10.0))
        assert result.verdict == grading.start_sit_verdict(result.win_probability)


class TestHonesty:
    def test_a_player_cannot_be_compared_with_themselves(self):
        with pytest.raises(InvalidRequest):
            advice.start_sit(player("a", expected=10.0), player("a", expected=10.0))

    def test_a_missing_distribution_is_refused_not_guessed(self):
        thin = PlayerProjection(
            player=PlayerRef(player_id="thin", name="THIN", position="WR"),
            season=2025,
            week=10,
            team="KC",
            opponent="BUF",
            is_home=True,
            game_id=None,
            points=PointDistribution(
                scoring_profile="half_ppr", expected=11.0, predicted=11.0
            ),
        )
        with pytest.raises(InvalidRequest, match="distribution"):
            advice.start_sit(player("a", expected=10.0), thin)

    def test_teammates_get_a_correlation_caveat(self):
        result = advice.start_sit(
            player("a", expected=14.0, team="KC"),
            player("b", expected=9.0, team="KC"),
        )
        assert any("share an offence" in caveat for caveat in result.caveats)

    def test_opponents_get_a_correlation_caveat(self):
        result = advice.start_sit(
            player("a", expected=14.0, team="KC", game_id="2025_10_KC_BUF"),
            player("b", expected=9.0, team="BUF", game_id="2025_10_KC_BUF"),
        )
        assert any("correlated" in caveat for caveat in result.caveats)

    def test_players_in_different_games_get_no_correlation_caveat(self):
        result = advice.start_sit(
            player("a", expected=14.0, team="KC", game_id="2025_10_KC_BUF"),
            player("b", expected=9.0, team="SF", game_id="2025_10_SF_SEA"),
        )
        assert not any("correlated" in caveat for caveat in result.caveats)

    def test_a_ruled_out_player_is_flagged_above_the_statistics(self):
        # The engine has no fitted injury adjustment, so a projection for a
        # player listed OUT is a number about someone who will not play.
        result = advice.start_sit(
            player("a", expected=14.0, injury=InjuryContext(report_status="Out")),
            player("b", expected=9.0, game_id="2025_10_SF_SEA", team="SF"),
        )
        assert any("OUT" in caveat for caveat in result.caveats)

    def test_a_questionable_designation_is_surfaced(self):
        result = advice.start_sit(
            player("a", expected=14.0, injury=InjuryContext(report_status="Questionable")),
            player("b", expected=9.0, game_id="2025_10_SF_SEA", team="SF"),
        )
        assert any("Questionable" in caveat for caveat in result.caveats)

    def test_extrapolated_intervals_are_disclosed(self):
        result = advice.start_sit(
            player("a", expected=34.0, extrapolated=True),
            player("b", expected=9.0, game_id="2025_10_SF_SEA", team="SF"),
        )
        assert any("extrapolation" in caveat for caveat in result.caveats)


class TestRationale:
    def test_always_states_the_probability_and_the_margin(self):
        result = advice.start_sit(player("a", expected=15.0), player("b", expected=10.0))
        assert result.rationale
        assert "%" in result.rationale[0]

    def test_reports_a_floor_advantage(self):
        result = advice.start_sit(
            player("safe", expected=12.0, floor=9.0, ceiling=16.0),
            player("risky", expected=12.0, floor=1.0, ceiling=30.0),
        )
        assert any("higher floor" in line for line in result.rationale)

    def test_reports_a_ceiling_advantage(self):
        result = advice.start_sit(
            player("safe", expected=12.0, floor=9.0, ceiling=16.0),
            player("risky", expected=12.0, floor=1.0, ceiling=30.0),
        )
        assert any("higher ceiling" in line for line in result.rationale)

    def test_calls_out_a_mean_versus_odds_disagreement(self):
        # A higher projection carried by a long ceiling rather than by the
        # typical week. A points-only comparison gets this backwards.
        spiky = player("spiky", expected=11.0, floor=0.0, ceiling=45.0, spread=10.0)
        steady = player("steady", expected=10.0, floor=7.0, ceiling=13.0, spread=3.0)
        result = advice.start_sit(spiky, steady)
        assert result.expected_margin > 0
        if result.win_probability < 0.5:
            assert any("more likely to win the week" in line for line in result.rationale)
