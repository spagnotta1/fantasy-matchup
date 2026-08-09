"""Phase 6D: the instrument the promotion decision is read off.

Three things are pinned here, in descending order of how badly a mistake would
hurt.

**The Phase 6B and 6C draw stream is frozen.** Those two reports are the
baseline the correlation decision is argued against, and both are claimed to be
reproducible. The matchup generator grew two parameters in Phase 6D, and the
whole design of that change is that a caller who does not pass them gets the
exact sequence of lineups the earlier phases drew.
:class:`TestTheOlderPhasesStillDrawWhatTheyDrew` is the guard, and it is a
digest rather than a spot check because "mostly the same lineups" would be a
silently different experiment.

**A lineup is classified by what it holds.** The generator's ``stacked`` flag
says what was *asked for*; a week whose slate has no eligible pair yields an
ordinary lineup under that flag. A promotion decision that read the flag would
be reporting a diluted population under a label that says otherwise.

**The two arms stay paired.** Every standard error in the Phase 6D report is a
paired difference, which is only meaningful if both arms scored the same lineups
in the same order. The filters and stratifiers this phase adds are the things
that could break that, so they are tested for it directly.
"""

from __future__ import annotations

import hashlib

import pytest

from nflfp.correlation.evaluate import (
    LINEUP_SHAPE,
    SyntheticMatchup,
    synthesise_matchups,
)
from nflfp.correlation.model import (
    CORRELATION_MODEL_VERSION,
    CorrelationMode,
    CorrelationModel,
    EstimationReport,
    PositionLoading,
)
from nflfp.correlation.panel import Panel, PanelRow
from nflfp.evaluation.promotion import (
    LineupComposition,
    classify,
    composition_keys,
    marginal_comparison,
)
from nflfp.evaluation.tails import TailFactors, draw_lineup, run_sweep

#: The Phase 6B and 6C matchup generator, exactly as those reports ran it.
LEGACY_CALL = {"count": 12, "stack_share": 0.35}


def row(
    player_id: str,
    position: str,
    team: str,
    game_id: str,
    *,
    base: float = 12.0,
    actual: float = 9.0,
    season: int = 2024,
    week: int = 5,
) -> PanelRow:
    return PanelRow(
        player_id=player_id, season=season, week=week, position=position,
        team=team, opponent="XX", game_id=game_id,
        expected=base,
        p10=base * 0.25, p25=base * 0.60, p50=base * 0.92,
        p75=base * 1.35, p90=base * 1.95,
        samples=300, extrapolated=False, actual=actual,
    )


def slate(season: int = 2024, week: int = 5) -> list[PanelRow]:
    """Eight teams over four games, deep enough to fill two lineups.

    Every game has both sidelines represented at every position, so a stack, an
    opposing pair and a quarterback duel are all drawable — a pool that could
    not supply one of them would let a test pass by never exercising it.
    """
    rows: list[PanelRow] = []
    counter = 0
    for game in range(4):
        game_id = f"{season}_{week:02d}_G{game}"
        for side in ("H", "A"):
            team = f"T{game}{side}"
            for position, count in (("QB", 1), ("RB", 3), ("WR", 3), ("TE", 2)):
                for index in range(count):
                    counter += 1
                    rows.append(
                        row(
                            f"00-{counter:07d}", position, team, game_id,
                            base=8.0 + (counter % 7) * 2.0,
                            actual=3.0 + (counter % 11) * 1.7,
                            season=season, week=week,
                        )
                    )
    return rows


def digest_of(matchups) -> str:
    sha = hashlib.sha256()
    for matchup in matchups:
        sha.update(
            f"{matchup.index}|{matchup.stacked}|"
            f"{[r.player_id for r in matchup.team_a]}|"
            f"{[r.player_id for r in matchup.team_b]}\n".encode()
        )
    return sha.hexdigest()


class TestTheOlderPhasesStillDrawWhatTheyDrew:
    """``opponent_share`` and ``duel_share`` must not perturb a default call."""

    def test_the_default_draw_has_a_fixed_digest(self):
        # Recorded from the generator as Phases 6B and 6C ran it, and verified
        # against the real panel at the time Phase 6D added the two parameters:
        # 1,440 held-out matchups hashed identically before and after. If this
        # fails, artifacts/phase6b_report.txt and artifacts/phase6c_report.txt
        # are no longer reproducible from this code, which is a bigger problem
        # than whatever change caused it.
        drawn = list(
            synthesise_matchups(slate(), season=2024, week=5, seed=7, **LEGACY_CALL)
        )
        assert len(drawn) == 12
        assert digest_of(drawn) == (
            "54bdfe2ba60ee4c302352d49d14235a979dc43bda08cf807be93d591a02a1435"
        )

    def test_passing_the_new_shares_as_zero_changes_nothing(self):
        # The parameters are short-circuited before they reach the generator, so
        # "absent" and "zero" have to be the same draw and not merely the same
        # intent.
        plain = list(
            synthesise_matchups(slate(), season=2024, week=5, seed=7, **LEGACY_CALL)
        )
        explicit = list(
            synthesise_matchups(
                slate(), season=2024, week=5, seed=7,
                opponent_share=0.0, duel_share=0.0, **LEGACY_CALL,
            )
        )
        assert digest_of(plain) == digest_of(explicit)

    def test_a_non_zero_share_does_change_the_draw(self):
        # The complement of the test above: if the parameter were inert, the
        # guard would be guarding nothing.
        plain = list(
            synthesise_matchups(slate(), season=2024, week=5, seed=7, **LEGACY_CALL)
        )
        opposing = list(
            synthesise_matchups(
                slate(), season=2024, week=5, seed=7,
                opponent_share=1.0, **LEGACY_CALL,
            )
        )
        assert digest_of(plain) != digest_of(opposing)


class TestTheGeneratorBuildsWhatItWasAskedFor:
    def test_a_full_opponent_share_puts_an_opposing_pair_in_every_lineup(self):
        drawn = list(
            synthesise_matchups(
                slate(), season=2024, week=5, seed=11, count=20,
                stack_share=0.0, opponent_share=1.0,
            )
        )
        assert drawn
        for matchup in drawn:
            for lineup in (matchup.team_a, matchup.team_b):
                assert classify(lineup).has_opposing_pair

    def test_a_full_duel_share_faces_the_two_quarterbacks(self):
        drawn = list(
            synthesise_matchups(
                slate(), season=2024, week=5, seed=13, count=20,
                stack_share=0.0, duel_share=1.0,
            )
        )
        assert drawn
        assert all(matchup.quarterbacks_duel for matchup in drawn)

    def test_a_full_stack_share_still_stacks(self):
        drawn = list(
            synthesise_matchups(
                slate(), season=2024, week=5, seed=17, count=20, stack_share=1.0,
            )
        )
        assert drawn
        for matchup in drawn:
            for lineup in (matchup.team_a, matchup.team_b):
                assert classify(lineup).has_same_team_stack

    def test_a_stack_and_an_opposing_pair_can_coexist(self):
        drawn = list(
            synthesise_matchups(
                slate(), season=2024, week=5, seed=19, count=20,
                stack_share=1.0, opponent_share=1.0,
            )
        )
        assert drawn
        assert any(
            classify(matchup.team_a).has_same_team_stack
            and classify(matchup.team_a).has_opposing_pair
            for matchup in drawn
        )

    def test_no_player_starts_for_both_managers(self):
        # Sampling is without replacement within a matchup. Letting a player
        # appear twice would cancel exactly the cross-lineup dependence the duel
        # population exists to measure.
        for shares in (
            {"stack_share": 1.0},
            {"stack_share": 0.0, "opponent_share": 1.0},
            {"stack_share": 0.0, "duel_share": 1.0},
        ):
            for matchup in synthesise_matchups(
                slate(), season=2024, week=5, seed=23, count=20, **shares
            ):
                ids = [r.player_id for r in (*matchup.team_a, *matchup.team_b)]
                assert len(ids) == len(set(ids))

    def test_every_lineup_still_fills_the_shape(self):
        for shares in (
            {"stack_share": 1.0, "opponent_share": 1.0},
            {"stack_share": 0.0, "opponent_share": 1.0, "duel_share": 1.0},
        ):
            for matchup in synthesise_matchups(
                slate(), season=2024, week=5, seed=29, count=20, **shares
            ):
                for lineup in (matchup.team_a, matchup.team_b):
                    assert len(lineup) == len(LINEUP_SHAPE)
                    assert sum(1 for r in lineup if r.position == "QB") == 1


class TestClassify:
    def test_a_quarterback_and_his_own_receiver_is_a_stack(self):
        composition = classify([
            row("a", "QB", "KC", "G1"),
            row("b", "WR", "KC", "G1"),
            row("c", "RB", "SF", "G9"),
        ])
        assert composition.stack_shape == "QB+WR"
        assert composition.has_same_team_stack
        assert not composition.has_opposing_pair

    def test_the_shape_names_every_catcher(self):
        composition = classify([
            row("a", "QB", "KC", "G1"),
            row("b", "WR", "KC", "G1"),
            row("c", "TE", "KC", "G1"),
        ])
        assert composition.stack_shape == "QB+TE+WR"

    def test_a_running_back_does_not_make_a_stack(self):
        # QB-RB same-team is +0.062 against +0.22 for QB-WR. Pooling them would
        # put the population's defining effect inside its own noise.
        composition = classify([
            row("a", "QB", "KC", "G1"),
            row("b", "RB", "KC", "G1"),
        ])
        assert not composition.has_same_team_stack
        assert composition.same_team_pairs == (("QB", "RB"),)

    def test_opposite_sidelines_of_one_game_is_an_opposing_pair(self):
        composition = classify([
            row("a", "QB", "KC", "G1"),
            row("b", "WR", "MIN", "G1"),
        ])
        assert composition.has_opposing_pair
        assert composition.opposing_pairs == (("QB", "WR"),)
        assert not composition.has_same_team_stack

    def test_different_games_are_unrelated(self):
        composition = classify([
            row("a", "QB", "KC", "G1"),
            row("b", "WR", "MIN", "G2"),
            row("c", "TE", "SF", "G3"),
        ])
        assert composition.is_unrelated
        assert composition == LineupComposition((), (), "")

    def test_a_missing_game_id_relates_a_player_to_nobody(self):
        # A player with no game must not be pooled with every other unknown;
        # that would invent correlation out of a missing column.
        composition = classify([
            PanelRow(
                player_id="a", season=2024, week=1, position="QB", team="KC",
                opponent=None, game_id=None, expected=10.0, p10=1.0, p25=4.0,
                p50=9.0, p75=14.0, p90=20.0, samples=100, extrapolated=False,
                actual=8.0,
            ),
            row("b", "WR", "KC", "G1"),
        ])
        assert composition.is_unrelated


class TestCompositionKeys:
    def _matchup(self, stacked: bool = False) -> SyntheticMatchup:
        """A matchup whose flag can be set independently of its rows.

        The stratifier is supposed to ignore the flag, so the fixture has to be
        able to lie about it.
        """
        drawn = list(
            synthesise_matchups(slate(), season=2024, week=5, seed=3, count=1)
        )
        first = drawn[0]
        return SyntheticMatchup(
            season=first.season, week=first.week, index=first.index,
            team_a=first.team_a, team_b=first.team_b, stacked=stacked,
        )

    def test_a_lineup_lands_in_exactly_one_projection_band(self):
        matchup = self._matchup()
        draws = draw_lineup(matchup.team_a, [[0.5] * 14], range(7))
        bands = [k for k in composition_keys(draws, matchup) if k.startswith("projection")]
        assert len(bands) == 1

    def test_the_buckets_overlap_when_the_lineup_is_two_things(self):
        rows = (
            row("a", "QB", "KC", "G1"), row("b", "WR", "KC", "G1"),
            row("c", "TE", "MIN", "G1"), row("d", "RB", "SF", "G2"),
        )
        matchup = self._matchup()
        draws = draw_lineup(rows, [[0.5] * 14], range(4))
        keys = composition_keys(draws, matchup)
        assert "same-team stack" in keys
        assert "opposing pair" in keys
        assert "unstacked (no shared game)" not in keys

    def test_an_unrelated_lineup_says_so(self):
        rows = (
            row("a", "QB", "KC", "G1"), row("b", "WR", "SF", "G2"),
            row("c", "TE", "BUF", "G3"),
        )
        matchup = self._matchup()
        draws = draw_lineup(rows, [[0.5] * 14], range(3))
        keys = composition_keys(draws, matchup)
        assert "unstacked (no shared game)" in keys
        assert "same-team stack" not in keys
        assert "opposing pair" not in keys

    def test_it_reads_the_lineup_and_not_the_generator_s_flag(self):
        # The point of the classifier. A matchup carrying stacked=True whose
        # lineup holds no stack must not be counted as a stack — which is the
        # case a week with no eligible pair produces, and the case that would
        # otherwise dilute the population the decision is read off.
        matchup = self._matchup(stacked=True)
        unrelated = (
            row("a", "QB", "KC", "G1"), row("b", "WR", "SF", "G2"),
        )
        draws = draw_lineup(unrelated, [[0.5] * 14], range(2))
        keys = composition_keys(draws, matchup)
        assert "same-team stack" not in keys
        assert "unstacked (no shared game)" in keys


class TestSweepFiltersAndStrata:
    def _panel(self) -> Panel:
        rows = [*slate(2024, 1), *slate(2024, 2)]
        return Panel.of("half_ppr", "shrinkage_eb", rows)

    def _sweep(self, **kwargs):
        return run_sweep(
            self._panel(), grid=(TailFactors(1.0, 2.0),), seasons=(2024,),
            period="test", matchups_per_week=8, iterations=200, seed=5,
            **kwargs,
        )

    def test_a_matchup_filter_restricts_the_sample(self):
        everything = self._sweep()
        duels = self._sweep(
            duel_share=1.0, matchup_filter=lambda m: m.quarterbacks_duel
        )
        assert duels.matchups <= everything.matchups
        assert duels.matchups > 0

    def test_a_filter_that_rejects_everything_yields_nothing(self):
        empty = self._sweep(matchup_filter=lambda m: False)
        assert empty.matchups == 0
        assert empty.lineups == 0

    def test_a_custom_stratifier_is_used(self):
        result = self._sweep(strata=True, strata_keys=composition_keys)
        strata = result.results[TailFactors(1.0, 2.0)].strata
        assert strata
        # Phase 6C's stratifier says "stacked"/"unstacked"; Phase 6D's does not.
        assert "stacked" not in strata
        assert any(key.startswith("projection") for key in strata)

    def test_the_default_stratifier_is_still_phase_6c_s(self):
        result = self._sweep(strata=True)
        strata = result.results[TailFactors(1.0, 2.0)].strata
        assert {"stacked", "unstacked"} & set(strata)

    def test_every_stratum_is_a_subset_of_the_whole(self):
        result = self._sweep(strata=True, strata_keys=composition_keys)
        outcome = result.results[TailFactors(1.0, 2.0)]
        for metrics in outcome.strata.values():
            assert metrics.n <= outcome.lineup.n

    def test_both_arms_score_the_same_lineups(self):
        # The pairing every standard error in the Phase 6D report rests on.
        # The sampler must not change which matchups survive.
        from nflfp.correlation.sampler import build_sampler as build

        def correlated(members, season, week):
            return build(
                members, mode=CorrelationMode.GAME_ENVIRONMENT, model=model_for()
            )

        independent = self._sweep(collect_series=True)
        correlated_result = self._sweep(
            sampler_for=correlated, collect_series=True
        )
        assert independent.lineups == correlated_result.lineups
        assert independent.matchups == correlated_result.matchups
        factors = TailFactors(1.0, 2.0)
        assert len(
            independent.results[factors].lineup_series["crps"]
        ) == len(correlated_result.results[factors].lineup_series["crps"])


def model_for() -> CorrelationModel:
    """The fitted structure's shape, at roughly the fitted magnitudes.

    The quarterback's team loading is ``sqrt(1 - game^2)`` because that is the
    identification the fit imposes — the shared part of an offence's week *is*
    the quarterback's week — and because anything larger makes the idiosyncratic
    variance negative, which the model refuses.
    """
    game_qb = 0.385
    return CorrelationModel(
        version=CORRELATION_MODEL_VERSION,
        mode=CorrelationMode.GAME_ENVIRONMENT,
        loadings={
            "QB": PositionLoading(
                position="QB", game=game_qb, team=(1.0 - game_qb ** 2) ** 0.5
            ),
            "RB": PositionLoading(position="RB", game=0.03, team=0.04),
            "WR": PositionLoading(position="WR", game=0.18, team=0.16),
            "TE": PositionLoading(position="TE", game=0.13, team=0.17),
        },
        estimation=EstimationReport(
            projection_floor=6.0, rows=0, pairs=0,
            through_season=2024, through_week=1,
        ),
    )


class TestMarginalComparison:
    """The measurement, and the control that makes it readable."""

    def test_correlation_moves_a_marginal_no_more_than_noise_does(self):
        matchups = list(
            synthesise_matchups(
                slate(), season=2024, week=5, seed=31, count=3,
                stack_share=1.0, opponent_share=1.0,
            )
        )
        assert matchups
        against, control = marginal_comparison(
            matchups, model=model_for(), iterations=8_000, seed=101
        )
        # Not "close to zero" — close to what the *same* sampler costs at a
        # different seed. An absolute threshold here would be a guess about
        # Monte Carlo error; this is a measurement of it.
        assert against.max_knot_drift < control.max_knot_drift * 3.0
        assert against.max_mean_drift < control.max_mean_drift * 3.0

    def test_the_control_is_not_trivially_zero(self):
        # If the control were zero the comparison above would be vacuous.
        matchups = list(
            synthesise_matchups(
                slate(), season=2024, week=5, seed=31, count=2, stack_share=1.0,
            )
        )
        _, control = marginal_comparison(
            matchups, model=model_for(), iterations=4_000, seed=101
        )
        assert control.max_knot_drift > 0.0

    def test_it_counts_every_player_in_both_lineups(self):
        matchups = list(
            synthesise_matchups(
                slate(), season=2024, week=5, seed=31, count=2, stack_share=1.0,
            )
        )
        against, _ = marginal_comparison(
            matchups, model=model_for(), iterations=2_000, seed=101
        )
        assert against.players == sum(
            len(m.team_a) + len(m.team_b) for m in matchups
        )

    def test_it_is_deterministic(self):
        matchups = list(
            synthesise_matchups(
                slate(), season=2024, week=5, seed=31, count=2, stack_share=1.0,
            )
        )
        kwargs = {"model": model_for(), "iterations": 2_000, "seed": 101}
        first, _ = marginal_comparison(matchups, **kwargs)
        second, _ = marginal_comparison(matchups, **kwargs)
        assert first.max_knot_drift == pytest.approx(second.max_knot_drift)


class TestQuarterbacksDuel:
    def test_it_is_read_off_the_rows(self):
        duel = SyntheticMatchup(
            season=2024, week=1, index=0,
            team_a=(row("a", "QB", "KC", "G1"),),
            team_b=(row("b", "QB", "MIN", "G1"),),
            stacked=False,
        )
        assert duel.quarterbacks_duel

    def test_the_same_team_is_not_a_duel(self):
        pair = SyntheticMatchup(
            season=2024, week=1, index=0,
            team_a=(row("a", "QB", "KC", "G1"),),
            team_b=(row("b", "QB", "KC", "G1"),),
            stacked=False,
        )
        assert not pair.quarterbacks_duel

    def test_different_games_are_not_a_duel(self):
        pair = SyntheticMatchup(
            season=2024, week=1, index=0,
            team_a=(row("a", "QB", "KC", "G1"),),
            team_b=(row("b", "QB", "MIN", "G2"),),
            stacked=False,
        )
        assert not pair.quarterbacks_duel
