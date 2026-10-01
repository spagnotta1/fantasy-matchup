"""Grading thresholds — every user-visible label in the product.

These run without a database, which is the point: a wrong grade boundary is
invisible in production (every screen still renders) and changes what people
start. It deserves unit tests, not an integration test that happens to pass.
"""

from __future__ import annotations

import pytest

from nflfp.services import grading


class TestScoreFromRank:
    def test_toughest_defence_is_the_worst_matchup(self):
        # Rank 1 allows the fewest points, so it must score zero, not 100.
        # Getting this inverted produces a product that confidently tells
        # people to start players against the best defence in football.
        assert grading.score_from_rank(1) == 0.0

    def test_softest_defence_scores_100(self):
        assert grading.score_from_rank(32) == 100.0

    def test_is_a_uniform_percentile(self):
        scores = [grading.score_from_rank(r) for r in range(1, 33)]
        gaps = [b - a for a, b in zip(scores, scores[1:])]
        assert max(gaps) - min(gaps) < 1e-9

    @pytest.mark.parametrize("rank", [None, 0, 33, -1])
    def test_missing_or_impossible_ranks_return_none(self, rank):
        # Clamping a rank of 45 to 32 would silently hide a join bug in the
        # defensive views; returning None surfaces it as an ungraded matchup.
        assert grading.score_from_rank(rank) is None


class TestLetterGrade:
    def test_bands_cover_the_whole_range_without_gaps(self):
        bands = grading.grade_bands()
        assert bands[-1][1] == 0.0
        minimums = [minimum for _, minimum in bands]
        assert minimums == sorted(minimums, reverse=True)
        assert len(bands) == len(grading.GRADE_LADDER)

    def test_bands_are_uniform(self):
        minimums = [minimum for _, minimum in grading.grade_bands()]
        widths = [a - b for a, b in zip(minimums, minimums[1:])]
        # The bands are rounded to six decimals so the published thresholds are
        # stable strings; that rounding is the only source of the jitter here.
        assert max(widths) - min(widths) < 1e-5

    def test_extremes(self):
        assert grading.letter_grade(100.0) == "A+"
        assert grading.letter_grade(0.0) == "F"

    def test_every_rank_gets_a_grade(self):
        letters = [
            grading.letter_grade(grading.score_from_rank(rank))
            for rank in range(1, 33)
        ]
        assert all(letter in grading.GRADE_LADDER for letter in letters)
        # A percentile grade means no letter can monopolise the league.
        assert max(letters.count(letter) for letter in set(letters)) <= 4

    def test_grades_are_monotone_in_rank(self):
        letters = [
            grading.letter_grade(grading.score_from_rank(rank))
            for rank in range(1, 33)
        ]
        positions = [grading.GRADE_LADDER.index(letter) for letter in letters]
        assert positions == sorted(positions, reverse=True)

    def test_none_score_has_no_letter(self):
        assert grading.letter_grade(None) is None


class TestGradeMatchup:
    def test_grades_a_well_sampled_rank(self):
        grade = grading.grade_matchup(defense_rank=30, sample_games=4)
        assert grade.graded
        assert grade.letter in ("A+", "A")
        assert grade.is_favourable

    def test_withholds_a_grade_below_the_sample_floor(self):
        grade = grading.grade_matchup(defense_rank=1, sample_games=1)
        assert not grade.graded
        assert grade.letter is None
        assert grade.reason is not None and "1 game" in grade.reason
        # The rank is still returned, so a caller can show it as raw data.
        assert grade.defense_rank == 1

    def test_week_one_is_ungraded_rather_than_average(self):
        # No defensive history exists in week 1. Inventing a neutral C would be
        # a claim about 32 defences nobody has watched play yet.
        grade = grading.grade_matchup(defense_rank=None, sample_games=0)
        assert not grade.graded
        assert grade.score is None

    def test_a_stored_score_wins_over_the_rank(self):
        # If the engine ever computes its own matchup number it knows more than
        # this module can infer from a rank.
        grade = grading.grade_matchup(
            defense_rank=1, sample_games=8, stored_score=95.0
        )
        assert grade.graded and grade.score == 95.0 and grade.letter == "A+"

    def test_out_of_range_rank_is_reported_not_clamped(self):
        grade = grading.grade_matchup(defense_rank=99, sample_games=8)
        assert not grade.graded
        assert grade.reason is not None and "outside" in grade.reason


class TestRangeEvidence:
    @staticmethod
    def _evidence(**overrides):
        arguments = {
            "has_range": True,
            "games_in_window": 4,
            "position": "QB",
            "scoring_profile": "half_ppr",
        }
        return grading.range_evidence(**{**arguments, **overrides})

    def test_a_range_with_a_full_window_carries_no_caveat(self):
        evidence = self._evidence()
        assert evidence.label == "established" and evidence.note is None

    def test_unknown_without_a_range(self):
        evidence = self._evidence(has_range=False, games_in_window=1)
        assert evidence.label == "unknown" and evidence.note is None

    def test_a_short_history_is_caveated_with_what_was_measured(self):
        evidence = self._evidence(games_in_window=1)
        assert evidence.label == "thin_history"
        # The number on screen is the measurement, not an adjective for it.
        assert evidence.note.startswith("Only 1 recent game to go on.")
        assert "QBs with fewer than 4" in evidence.note
        assert "72 in 100" in evidence.note and "instead of 80" in evidence.note

    @pytest.mark.parametrize(
        "games,opening", [(0, "No recent games"), (2, "Only 2 recent games"), (3, "Only 3")]
    )
    def test_every_window_short_of_four_games_is_a_short_history(self, games, opening):
        evidence = self._evidence(games_in_window=games)
        assert evidence.label == "thin_history" and evidence.note.startswith(opening)

    @pytest.mark.parametrize(
        "profile,position",
        [("half_ppr", "RB"), ("half_ppr", "TE"), ("ppr", "WR"), ("standard", "WR")],
    )
    def test_a_cell_that_measured_calibrated_is_not_caveated(self, profile, position):
        # Short-history RB/TE/WR ranges hold 0.777-0.817 outside standard-scoring
        # running backs: inside the backtest's tolerance. Caveating them would
        # overstate a limitation, which is the failure this label replaced.
        evidence = self._evidence(
            games_in_window=1, position=position, scoring_profile=profile
        )
        assert evidence.label == "established" and evidence.note is None

    def test_standard_scoring_running_backs_are_the_other_measured_cell(self):
        evidence = self._evidence(games_in_window=2, position="RB", scoring_profile="standard")
        assert evidence.label == "thin_history" and "75 in 100" in evidence.note

    def test_an_unmeasured_profile_is_not_given_a_borrowed_caveat(self):
        # ppr_te_premium has no recorded outcomes to backtest against. Absent a
        # measurement there is no caveat; one is not carried over from PPR.
        evidence = self._evidence(games_in_window=1, scoring_profile="ppr_te_premium")
        assert evidence.label == "established"

    def test_an_absent_usage_row_is_not_a_short_history(self):
        # None means the join found nothing. That is missing data, and missing
        # data is not reported as a measured weakness.
        assert self._evidence(games_in_window=None).label == "established"

    def test_extrapolation_outranks_a_short_history(self):
        # A range nobody has observed at this level is the weaker claim.
        evidence = self._evidence(extrapolated=True, games_in_window=1)
        assert evidence.label == "extrapolated" and evidence.note

    def test_the_caveat_matches_the_frozen_record(self):
        # The business layer restates these rather than importing the prediction
        # engine, so this is the test that stops the caveat a user reads from
        # drifting away from the measurement that justifies it.
        from nflfp.predict import foundation

        assert grading.THIN_HISTORY_COVERAGE == foundation.undercovered_short_history()
        assert grading.FULL_WINDOW_GAMES == foundation.FULL_WINDOW_GAMES
        assert grading.RANGE_NOMINAL_COVERAGE == foundation.VALIDATION.nominal_p10_p90


class TestStartSitVerdict:
    def test_a_coin_flip_is_a_toss_up(self):
        assert grading.start_sit_verdict(0.50) == "toss_up"

    def test_symmetric_about_a_half(self):
        assert grading.start_sit_verdict(0.30) == grading.start_sit_verdict(0.70)

    def test_a_small_edge_is_still_a_toss_up(self):
        # 54/46 is well inside the model's own error bar. Naming a starter here
        # is the false precision this threshold exists to prevent.
        assert grading.start_sit_verdict(0.54) == "toss_up"

    def test_a_clear_edge_is_stated(self):
        assert grading.start_sit_verdict(0.75) == "clear"

    def test_thresholds_are_ordered(self):
        assert grading.START_SIT_DECISIVE < grading.START_SIT_CLEAR

    @pytest.mark.parametrize("probability", [-0.1, 1.1])
    def test_rejects_impossible_probabilities(self, probability):
        with pytest.raises(ValueError):
            grading.start_sit_verdict(probability)


class TestOutcomeShape:
    def test_wide_relative_spread_is_volatile(self):
        assert grading.outcome_shape(p25=2.0, median=8.0, p75=18.0) == "volatile"

    def test_tight_relative_spread_is_steady(self):
        assert grading.outcome_shape(p25=12.0, median=15.0, p75=18.0) == "steady"

    def test_a_zero_median_is_all_variance(self):
        assert grading.outcome_shape(p25=0.0, median=0.0, p75=4.0) == "volatile"

    def test_missing_quartiles_are_unknown(self):
        assert grading.outcome_shape(p25=None, median=8.0, p75=18.0) == "unknown"
