"""The mock draft domain, valuation and engine — no database.

Everything that decides anything in :mod:`nflfp.services.draft` is pure, so
almost the whole feature is testable here. The integration suite adds only what
genuinely needs SQL: that the pool query returns what the assembler expects, and
that the endpoints wire up.
"""

from __future__ import annotations

import dataclasses
import random

import pytest

from nflfp.services.draft import aggregate, evaluate, history, valuation
from nflfp.services.draft.engine import (
    STRATEGIES,
    DraftContext,
    calibrate_availability,
    evaluate_roster,
    simulate_draft,
    survival_table,
)
from nflfp.services.draft.order import DraftOrder
from nflfp.services.draft.pool import assemble_pool
from nflfp.services.draft.settings import (
    DEFAULT_ROSTER,
    RosterRequirement,
    validate_draft_position,
    validate_opponent_skill,
    validate_settings,
)
from nflfp.services.errors import InvalidRequest

from .draft_fixtures import build_pool, make_player, season

SEED = 4242


def ranked_season(year: int, percentile: float):
    """A completed season carrying a stated within-position percentile."""
    return dataclasses.replace(season(year, 200), position_percentile=percentile)


def settings_for(**overrides) -> object:
    base = {
        "teams": 12,
        "rounds": 15,
        "scoring_profile": "ppr",
        "season": 2025,
        "simulations": 60,
        "seed": SEED,
    }
    base.update(overrides)
    return validate_settings(**base)


@pytest.fixture(scope="module")
def pool():
    return build_pool()


@pytest.fixture(scope="module")
def context(pool):
    return DraftContext.build(pool, settings_for())


@pytest.fixture(scope="module")
def availability(context):
    return calibrate_availability(context, drafts=120, seed=SEED)


# ---------------------------------------------------------------------------
# Draft mechanics
# ---------------------------------------------------------------------------


class TestSnakeOrdering:
    def test_odd_rounds_run_forward_and_even_rounds_backward(self):
        order = DraftOrder.build(teams=4, rounds=4)
        by_round = [
            [slot.team for slot in order if slot.round_number == r] for r in (1, 2, 3, 4)
        ]
        assert by_round == [[1, 2, 3, 4], [4, 3, 2, 1], [1, 2, 3, 4], [4, 3, 2, 1]]

    def test_a_linear_draft_never_reverses(self):
        order = DraftOrder.build(teams=4, rounds=3, snake=False)
        assert [slot.team for slot in order if slot.round_number == 2] == [1, 2, 3, 4]

    def test_overall_pick_numbers_are_dense_and_one_based(self):
        order = DraftOrder.build(teams=6, rounds=5)
        assert [slot.overall for slot in order] == list(range(1, 31))
        assert order.total_picks == 30

    def test_pick_in_round_is_not_the_team_number_in_even_rounds(self):
        order = DraftOrder.build(teams=4, rounds=2)
        second = [s for s in order if s.round_number == 2]
        assert [(s.pick_in_round, s.team) for s in second] == [
            (1, 4), (2, 3), (3, 2), (4, 1)
        ]

    def test_every_seat_makes_exactly_one_pick_per_round(self):
        order = DraftOrder.build(teams=10, rounds=7)
        for team in range(1, 11):
            assert len(order.picks_for(team)) == 7

    def test_the_turn_gives_consecutive_picks_to_the_edges(self):
        order = DraftOrder.build(teams=12, rounds=4)
        assert order.picks_for(1)[:2] == (1, 24)
        assert order.picks_for(12)[:2] == (12, 13)

    def test_wait_lengths_are_asymmetric_across_seats(self):
        order = DraftOrder.build(teams=12, rounds=6)
        assert order.wait_lengths(1)[:2] == (23, 1)
        assert order.wait_lengths(6) == (13, 11, 13, 11, 13)

    def test_next_pick_after_the_last_selection_is_none(self):
        order = DraftOrder.build(teams=4, rounds=2)
        last = order.picks_for(2)[-1]
        assert order.next_pick_after(2, last) is None

    @pytest.mark.parametrize("teams", [4, 6, 8, 10, 12, 14, 16, 20])
    def test_the_sum_of_pick_numbers_is_equal_for_every_seat(self, teams):
        """The reason a snake exists, asserted rather than assumed.

        Every seat's pick numbers sum to the same total in an even number of
        rounds. Any seat advantage therefore comes from the *shape* of the value
        curve, not from the ordering — which is what makes the comparison
        chart's differences interpretable.
        """
        order = DraftOrder.build(teams=teams, rounds=6)
        totals = {sum(order.picks_for(t)) for t in range(1, teams + 1)}
        assert len(totals) == 1


class TestSettingsValidation:
    def test_a_draft_too_short_to_start_a_lineup_is_refused(self):
        with pytest.raises(InvalidRequest, match="starting lineup"):
            settings_for(rounds=4)

    def test_a_kicker_slot_is_refused_with_the_reason_and_the_blockers(self):
        with pytest.raises(InvalidRequest) as error:
            settings_for(roster=[{"slot": "QB", "count": 1}, {"slot": "K", "count": 1}])
        message = str(error.value)
        assert "Kicker" in message
        assert "Blocked on:" in message
        assert error.value.field == "roster"

    def test_a_team_defence_slot_is_refused_too(self):
        with pytest.raises(InvalidRequest, match="Team Defense"):
            settings_for(roster=[{"slot": "QB", "count": 1}, {"slot": "DST", "count": 1}])

    def test_an_unknown_slot_names_the_ones_that_exist(self):
        with pytest.raises(InvalidRequest, match="unknown roster slot"):
            settings_for(roster=[{"slot": "SUPERFLEX", "count": 1}])

    def test_roster_order_is_normalised_so_two_spellings_agree(self):
        a = settings_for(roster=[{"slot": "WR", "count": 2}, {"slot": "QB", "count": 1}])
        b = settings_for(roster=[{"slot": "QB", "count": 1}, {"slot": "WR", "count": 2}])
        assert a.roster == b.roster

    def test_duplicate_slots_are_summed_rather_than_dropped(self):
        settings = settings_for(
            roster=[{"slot": "RB", "count": 1}, {"slot": "RB", "count": 1}]
        )
        assert settings.required("RB") == 2

    def test_zero_count_slots_are_dropped(self):
        settings = settings_for(
            roster=[{"slot": "QB", "count": 1}, {"slot": "TE", "count": 0}]
        )
        assert settings.required("TE") == 0
        assert settings.draftable_positions == ("QB",)

    def test_a_flex_slot_makes_its_positions_draftable(self):
        settings = settings_for(
            roster=[{"slot": "QB", "count": 1}, {"slot": "FLEX", "count": 1}]
        )
        assert settings.required("TE") == 0
        assert "TE" in settings.draftable_positions

    @pytest.mark.parametrize("teams", [3, 21, 0, -1])
    def test_implausible_league_sizes_are_refused(self, teams):
        with pytest.raises(InvalidRequest, match="teams"):
            settings_for(teams=teams)

    def test_a_seat_outside_the_league_is_refused(self):
        settings = settings_for(teams=10)
        with pytest.raises(InvalidRequest, match="draft_position"):
            validate_draft_position(11, settings)
        assert validate_draft_position(10, settings) == 10

    def test_starters_and_bench_decompose_the_rounds(self):
        settings = settings_for(rounds=15)
        assert settings.starters == 7
        assert settings.bench == 8
        assert settings.total_picks == 180

    def test_flex_eligible_positions_are_draftable_without_a_dedicated_slot(self):
        settings = settings_for(
            roster=[RosterRequirement("QB", 1), RosterRequirement("FLEX", 2)]
        )
        assert set(settings.draftable_positions) == {"QB", "RB", "WR", "TE"}


# ---------------------------------------------------------------------------
# Valuation
# ---------------------------------------------------------------------------


class TestReplacementLevel:
    def test_dedicated_slots_set_the_baseline_count(self, pool):
        levels = valuation.replacement_levels(pool, settings_for())
        # 12 teams x 1 QB, and no flex may hold a quarterback.
        assert levels["QB"].starters == 12
        assert levels["QB"].flex_share == 0

    def test_flex_slots_are_allocated_to_whoever_offers_more(self, pool):
        levels = valuation.replacement_levels(pool, settings_for())
        allocated = sum(level.flex_share for level in levels.values())
        assert allocated == 12
        # The fixture's receiver board is deep and flat and its back board falls
        # off a cliff at seven, so the flex should go to receivers.
        assert levels["WR"].flex_share > levels["RB"].flex_share

    def test_replacement_is_the_first_player_nobody_has_to_start(self, pool):
        levels = valuation.replacement_levels(pool, settings_for())
        ranked = sorted(pool.by_position("QB"), key=lambda p: -p.season_value)
        assert levels["QB"].value == ranked[12].season_value
        assert levels["QB"].player_id == ranked[12].player_id

    def test_a_flat_position_yields_less_surplus_than_a_steep_one(self, pool):
        levels = valuation.replacement_levels(pool, settings_for())
        best_qb = max(pool.by_position("QB"), key=lambda p: p.season_value)
        best_rb = max(pool.by_position("RB"), key=lambda p: p.season_value)
        # The quarterback out-scores the back outright...
        assert best_qb.season_value > best_rb.season_value
        # ...and is worth less, which is the entire point of the exercise.
        assert valuation.value_over_replacement(
            best_qb, levels
        ) < valuation.value_over_replacement(best_rb, levels)

    def test_a_pool_shallower_than_the_league_falls_back_to_its_last_player(self):
        pool = build_pool(shapes={"QB": [300, 280, 260]})
        levels = valuation.replacement_levels(pool, settings_for())
        assert levels["QB"].value == 260

    def test_a_larger_league_lowers_replacement_level(self, pool):
        small = valuation.replacement_levels(pool, settings_for(teams=8))
        large = valuation.replacement_levels(pool, settings_for(teams=16))
        assert large["RB"].value < small["RB"].value


class TestRosterNeeds:
    def test_dedicated_slots_fill_before_flex(self, pool):
        settings = settings_for()
        roster = [make_player(f"WR{i}", "WR", 200) for i in range(3)]
        needs = valuation.roster_needs(roster, settings, picks_remaining=12)
        # Two receivers start, the third takes the flex.
        assert needs.open_dedicated.get("WR", 0) == 0
        assert needs.open_flex == 0
        assert needs.open_dedicated["RB"] == 2

    def test_an_empty_roster_needs_every_starter(self, pool):
        needs = valuation.roster_needs([], settings_for(), picks_remaining=15)
        assert needs.open_starters == 7

    def test_must_fill_turns_on_when_picks_run_out(self, pool):
        needs = valuation.roster_needs([], settings_for(), picks_remaining=7)
        assert needs.must_fill_starters
        assert not valuation.roster_needs(
            [], settings_for(), picks_remaining=8
        ).must_fill_starters


class TestMarginalValue:
    def test_the_fast_path_and_the_readable_path_agree(self, pool):
        """The engine's scalar form must not drift from the dataclass form."""
        settings = settings_for()
        levels = valuation.replacement_levels(pool, settings)
        roster = [make_player("RB99", "RB", 210.0), make_player("WR99", "WR", 190.0)]
        needs = valuation.roster_needs(roster, settings, picks_remaining=10)

        for candidate in list(pool.players)[:40]:
            slow = valuation.marginal_value(
                candidate, roster, needs, levels, settings, 17
            )
            weakest = min(
                (p.season_value for p in roster if p.position == candidate.position),
                default=None,
            )
            fast = valuation.marginal_value_of(
                season_value=candidate.season_value,
                surplus=valuation.value_over_replacement(candidate, levels),
                open_dedicated=needs.open_dedicated.get(candidate.position, 0),
                open_flex=needs.open_flex,
                flex_eligible=candidate.position in {"RB", "WR", "TE"},
                bench_weight=valuation.bench_weight(roster, candidate.position, 17),
                weakest_held_value=weakest,
            )
            assert slow == fast

    def test_a_starter_is_worth_its_full_surplus(self, pool):
        settings = settings_for()
        levels = valuation.replacement_levels(pool, settings)
        needs = valuation.roster_needs([], settings, picks_remaining=15)
        candidate = pool.by_position("RB")[0]
        value, slot = valuation.marginal_value(
            candidate, [], needs, levels, settings, 17
        )
        assert slot == "starter"
        assert value == pytest.approx(valuation.value_over_replacement(candidate, levels))

    def test_a_bench_player_is_discounted(self, pool):
        settings = settings_for()
        levels = valuation.replacement_levels(pool, settings)
        roster = [
            make_player("QBx", "QB", 330.0),
            make_player("RBa", "RB", 320.0),
            make_player("RBb", "RB", 300.0),
            make_player("WRa", "WR", 300.0),
            make_player("WRb", "WR", 294.0),
            make_player("TEa", "TE", 230.0),
            make_player("WRc", "WR", 288.0),
        ]
        needs = valuation.roster_needs(roster, settings, picks_remaining=8)
        candidate = make_player("RBz", "RB", 262.0)
        value, slot = valuation.marginal_value(
            candidate, roster, needs, levels, settings, 17
        )
        assert slot == "bench"
        assert value < valuation.value_over_replacement(candidate, levels)

    def test_bench_weight_rises_with_the_fragility_of_the_starters(self):
        durable = [make_player("a", "RB", 200, expected_games=16.5)]
        fragile = [make_player("b", "RB", 200, expected_games=11.0)]
        assert valuation.bench_weight(fragile, "RB", 17) > valuation.bench_weight(
            durable, "RB", 17
        )

    def test_a_below_replacement_bench_pick_still_orders(self, pool):
        """Two bad options must not tie at zero — that is how a draft goes wrong."""
        settings = settings_for()
        levels = valuation.replacement_levels(pool, settings)
        roster = [make_player("QBx", "QB", 330.0)]
        needs = valuation.roster_needs(roster, settings, picks_remaining=1)
        worse, _ = valuation.marginal_value(
            make_player("QBz", "QB", 254.0), roster, needs, levels, settings, 17
        )
        better, _ = valuation.marginal_value(
            make_player("QBy", "QB", 290.0), roster, needs, levels, settings, 17
        )
        assert better > worse


class TestOpportunityCost:
    def test_a_certainly_available_player_is_the_whole_expectation(self, pool):
        candidates = list(pool.by_position("WR"))[:5]
        values = {p.player_id: p.season_value for p in candidates}
        survival = dict.fromkeys(values, 1.0)
        expected, best = valuation.expected_best_available(candidates, values, survival)
        assert expected == pytest.approx(max(values.values()))
        assert best == max(candidates, key=lambda p: p.season_value).player_id

    def test_nobody_surviving_is_worth_nothing(self, pool):
        candidates = list(pool.by_position("WR"))[:5]
        values = {p.player_id: p.season_value for p in candidates}
        expected, best = valuation.expected_best_available(
            candidates, values, dict.fromkeys(values, 0.0)
        )
        assert expected == 0.0
        assert best is None

    def test_the_expectation_sits_between_the_best_and_the_worst(self, pool):
        candidates = list(pool.by_position("WR"))[:8]
        values = {p.player_id: p.season_value for p in candidates}
        survival = {pid: 0.5 for pid in values}
        expected, _ = valuation.expected_best_available(candidates, values, survival)
        assert min(values.values()) < expected < max(values.values())

    def test_the_index_form_matches_the_dataclass_form(self, pool):
        from nflfp.services.draft.engine import _expected_best

        candidates = list(pool.by_position("RB"))[:12]
        values_by_id = {p.player_id: p.season_value for p in candidates}
        survival_by_id = {
            p.player_id: 0.2 + 0.05 * i for i, p in enumerate(candidates)
        }
        expected_a, best_a = valuation.expected_best_available(
            candidates, values_by_id, survival_by_id
        )

        indices = list(range(len(candidates)))
        values = [p.season_value for p in candidates]
        survival = [survival_by_id[p.player_id] for p in candidates]
        expected_b, best_b = _expected_best(indices, values, survival)

        assert expected_a == pytest.approx(expected_b)
        assert candidates[best_b].player_id == best_a


class TestTiers:
    def test_tiers_cover_every_player_exactly_once(self, pool):
        players = pool.by_position("WR")
        tiers = valuation.build_tiers(players, limit=30)
        seen = [pid for tier in tiers for pid in tier.player_ids]
        assert len(seen) == len(set(seen)) == 30

    def test_tiers_descend(self, pool):
        tiers = valuation.build_tiers(pool.by_position("RB"))
        for earlier, later in zip(tiers, tiers[1:]):
            assert earlier.bottom_value >= later.top_value

    def test_a_cliff_produces_a_boundary(self):
        players = [make_player(f"p{i}", "RB", v) for i, v in enumerate(
            [300, 298, 296, 294, 180, 178, 176, 174]
        )]
        tiers = valuation.build_tiers(players)
        assert len(tiers) >= 2
        assert tiers[0].player_ids == ("p0", "p1", "p2", "p3")

    def test_a_flat_board_is_one_tier(self):
        players = [make_player(f"p{i}", "WR", 200 - i) for i in range(12)]
        assert len(valuation.build_tiers(players)) == 1

    def test_a_single_player_is_still_a_tier(self):
        assert len(valuation.build_tiers([make_player("p", "TE", 100)])) == 1

    def test_an_empty_board_produces_no_tiers(self):
        assert valuation.build_tiers([]) == ()


class TestScarcity:
    def test_a_cliff_scores_higher_than_a_flat_board(self, pool):
        settings = settings_for()
        levels = valuation.replacement_levels(pool, settings)
        scarcity = valuation.positional_scarcity(list(pool.players), levels)
        assert scarcity["RB"] > scarcity["WR"]

    def test_scarcity_stays_within_bounds(self, pool):
        levels = valuation.replacement_levels(pool, settings_for())
        for value in valuation.positional_scarcity(list(pool.players), levels).values():
            assert 0.0 <= value <= 1.0


class TestConsensusBoard:
    def test_history_weight_moves_the_board(self, pool):
        levels = valuation.replacement_levels(pool, settings_for())
        pure = valuation.consensus_scores(pool, levels, history_weight=0.0)
        mixed = valuation.consensus_scores(pool, levels, history_weight=0.6)
        assert pure != mixed

    def test_with_no_history_weight_the_board_is_value_over_replacement(self, pool):
        levels = valuation.replacement_levels(pool, settings_for())
        scores = valuation.consensus_scores(pool, levels, history_weight=0.0)
        ranked = sorted(scores, key=lambda pid: -scores[pid])
        by_vor = sorted(
            pool.players, key=lambda p: -valuation.value_over_replacement(p, levels)
        )
        assert ranked[:10] == [p.player_id for p in by_vor[:10]]

    def test_a_player_with_no_history_is_scored_neutrally_not_zero(self):
        pool = build_pool(with_history=False)
        levels = valuation.replacement_levels(pool, settings_for())
        scores = valuation.consensus_scores(pool, levels, history_weight=0.5)
        assert len(set(scores.values())) > 1


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------


class TestDraftMechanics:
    def test_a_seat_drafts_exactly_one_player_per_round(self, context, availability):
        draft = simulate_draft(
            context, draft_position=5, availability=availability,
            rng=random.Random(1),
        )
        assert len(draft.picks) == context.settings.rounds
        assert [p.round_number for p in draft.picks] == list(range(1, 16))

    def test_a_seat_only_picks_at_its_own_slots(self, context, availability):
        draft = simulate_draft(
            context, draft_position=7, availability=availability,
            rng=random.Random(2),
        )
        assert [p.overall for p in draft.picks] == list(context.order.picks_for(7))

    def test_no_player_is_drafted_twice(self, context, availability):
        draft = simulate_draft(
            context, draft_position=3, availability=availability,
            rng=random.Random(3),
        )
        ids = [p.player_id for p in draft.picks]
        assert len(ids) == len(set(ids))

    def test_the_calibration_draft_never_repeats_a_player(self, context):
        from nflfp.services.draft.engine import _consensus_draft

        taken = _consensus_draft(context, random.Random(9))
        assert len(taken) == context.order.total_picks
        assert len(set(taken.values())) == context.order.total_picks

    def test_every_finished_roster_can_field_a_legal_lineup(self, context, availability):
        for seat in (1, 6, 12):
            draft = simulate_draft(
                context, draft_position=seat, availability=availability,
                rng=random.Random(seat),
            )
            counts: dict[str, int] = {}
            for pick in draft.picks:
                counts[pick.position] = counts.get(pick.position, 0) + 1
            assert counts.get("QB", 0) >= 1
            assert counts.get("RB", 0) >= 2
            assert counts.get("WR", 0) >= 2
            assert counts.get("TE", 0) >= 1
            assert len(draft.starters) == context.settings.starters

    def test_a_roster_never_exceeds_its_positional_depth_cap(self, context, availability):
        draft = simulate_draft(
            context, draft_position=2, availability=availability,
            rng=random.Random(11),
        )
        counts: dict[str, int] = {}
        for pick in draft.picks:
            counts[pick.position] = counts.get(pick.position, 0) + 1
        for position, held in counts.items():
            assert held <= context.depth_cap[position]

    def test_starters_are_a_subset_of_the_roster(self, context, availability):
        draft = simulate_draft(
            context, draft_position=9, availability=availability,
            rng=random.Random(12),
        )
        assert set(draft.starters) <= {p.player_id for p in draft.picks}

    def test_a_short_draft_still_completes(self, pool, availability):
        settings = settings_for(rounds=7, simulations=50)
        context = DraftContext.build(pool, settings)
        model = calibrate_availability(context, drafts=20, seed=SEED)
        draft = simulate_draft(
            context, draft_position=4, availability=model, rng=random.Random(1)
        )
        assert len(draft.picks) == 7
        assert len(draft.starters) == 7

    def test_a_pool_too_small_for_the_draft_does_not_hang_or_duplicate(self):
        """A real configuration, not an edge case: a deep league on a thin board.

        The draft simply runs out of players. What must not happen is a repeated
        pick, an exception, or a silent forfeit part-way through that leaves the
        remaining rounds unrun — so the assertion is that every pick made is a
        distinct player and the draft terminates.
        """
        thin = build_pool(shapes={"RB": [200 - i for i in range(30)]})
        settings = settings_for(
            teams=12, rounds=15, roster=[{"slot": "RB", "count": 2}]
        )
        context = DraftContext.build(thin, settings)
        model = calibrate_availability(context, drafts=10, seed=SEED)
        draft = simulate_draft(
            context, draft_position=1, availability=model, rng=random.Random(4)
        )
        ids = [p.player_id for p in draft.picks]
        assert len(ids) == len(set(ids))
        assert len(ids) <= settings.rounds

    def test_a_seat_takes_the_best_left_when_every_candidate_is_capped(self, context):
        """The relaxed path: a forfeited pick would corrupt the whole draft."""
        from nflfp.services.draft.engine import _relaxed_choice

        available = [context.index_by_id[p.player_id] for p in context.players[:5]]
        held = {position: 99 for position in context.positions}
        assert _relaxed_choice(available, context.positions, context.depth_cap, held) == 0

    @pytest.mark.parametrize("teams", [4, 8, 12, 14])
    def test_league_sizes_all_produce_full_rosters(self, pool, teams):
        settings = settings_for(teams=teams, rounds=9)
        context = DraftContext.build(pool, settings)
        model = calibrate_availability(context, drafts=20, seed=SEED)
        draft = simulate_draft(
            context, draft_position=teams, availability=model, rng=random.Random(5)
        )
        assert len(draft.picks) == 9


class TestFlexEligibility:
    def test_a_quarterback_never_fills_the_flex(self, pool):
        settings = settings_for()
        context = DraftContext.build(pool, settings)
        roster = [
            make_player("QB_a", "QB", 330.0),
            make_player("QB_b", "QB", 326.0),
            make_player("RB_a", "RB", 320.0),
            make_player("RB_b", "RB", 300.0),
            make_player("WR_a", "WR", 300.0),
            make_player("WR_b", "WR", 294.0),
            make_player("TE_a", "TE", 230.0),
        ]
        starters, _, _ = evaluate_roster(roster, context)
        assert "QB_b" not in starters
        # Six starters, not seven: the flex goes unfilled rather than taking a
        # quarterback, which is the refusal this test exists for.
        assert len(starters) == 6

    def test_the_flex_takes_the_best_remaining_eligible_player(self, pool):
        context = DraftContext.build(pool, settings_for())
        roster = [
            make_player("QB_a", "QB", 330.0),
            make_player("RB_a", "RB", 320.0),
            make_player("RB_b", "RB", 300.0),
            make_player("RB_c", "RB", 285.0),
            make_player("WR_a", "WR", 300.0),
            make_player("WR_b", "WR", 294.0),
            make_player("TE_a", "TE", 230.0),
            make_player("TE_b", "TE", 170.0),
        ]
        starters, _, _ = evaluate_roster(roster, context)
        assert "RB_c" in starters
        assert "TE_b" not in starters

    def test_lineup_value_ignores_the_bench(self, pool):
        context = DraftContext.build(pool, settings_for())
        core = [
            make_player("QB_a", "QB", 330.0),
            make_player("RB_a", "RB", 320.0),
            make_player("RB_b", "RB", 300.0),
            make_player("WR_a", "WR", 300.0),
            make_player("WR_b", "WR", 294.0),
            make_player("TE_a", "TE", 230.0),
            make_player("WR_c", "WR", 288.0),
        ]
        _, lean_points, _ = evaluate_roster(core, context)
        _, fat_points, _ = evaluate_roster(
            core + [make_player("TE_z", "TE", 96.0)], context
        )
        assert lean_points == fat_points


class TestDeterminism:
    def test_the_same_seed_reproduces_the_draft_exactly(self, context, availability):
        a = simulate_draft(
            context, draft_position=6, availability=availability, rng=random.Random(77)
        )
        b = simulate_draft(
            context, draft_position=6, availability=availability, rng=random.Random(77)
        )
        assert [p.player_id for p in a.picks] == [p.player_id for p in b.picks]
        assert a.roster_value == b.roster_value

    def test_a_different_seed_produces_a_different_draft(self, context, availability):
        a = simulate_draft(
            context, draft_position=6, availability=availability, rng=random.Random(1)
        )
        b = simulate_draft(
            context, draft_position=6, availability=availability, rng=random.Random(2)
        )
        assert [p.player_id for p in a.picks] != [p.player_id for p in b.picks]

    def test_calibration_is_reproducible(self, context):
        a = calibrate_availability(context, drafts=30, seed=5)
        b = calibrate_availability(context, drafts=30, seed=5)
        assert a.survival == b.survival

    def test_a_different_calibration_seed_moves_the_curves(self, context):
        a = calibrate_availability(context, drafts=30, seed=5)
        b = calibrate_availability(context, drafts=30, seed=6)
        assert a.survival != b.survival

    def test_the_engine_never_touches_the_global_generator(self, context, availability):
        random.seed(1234)
        before = random.random()
        random.seed(1234)
        simulate_draft(
            context, draft_position=4, availability=availability, rng=random.Random(9)
        )
        assert random.random() == before

    def test_a_seat_analysis_is_reproducible(self, context, availability):
        a = aggregate.analyse_seat(
            context, draft_position=8, availability=availability,
            simulations=30, seed=SEED,
        )
        b = aggregate.analyse_seat(
            context, draft_position=8, availability=availability,
            simulations=30, seed=SEED,
        )
        assert a.roster_value == b.roster_value
        assert [p.player_id for p in a.representative.picks] == [
            p.player_id for p in b.representative.picks
        ]

    def test_precomputing_survival_changes_nothing(self, context, availability):
        table = survival_table(context, availability, context.order.picks_for(3))
        a = simulate_draft(
            context, draft_position=3, availability=availability, rng=random.Random(21)
        )
        b = simulate_draft(
            context, draft_position=3, availability=availability,
            rng=random.Random(21), survival_by_pick=table,
        )
        assert [p.player_id for p in a.picks] == [p.player_id for p in b.picks]

    def test_capturing_a_rationale_does_not_change_the_picks(self, context, availability):
        plain = simulate_draft(
            context, draft_position=5, availability=availability, rng=random.Random(31)
        )
        explained = simulate_draft(
            context, draft_position=5, availability=availability,
            rng=random.Random(31), capture_rationale=True,
        )
        assert [p.player_id for p in plain.picks] == [
            p.player_id for p in explained.picks
        ]
        assert all(p.rationale is not None for p in explained.picks)


class TestAvailabilityModel:
    def test_survival_is_a_probability_and_never_increases(self, context, availability):
        for player in context.players[:40]:
            curve = availability.survival[player.player_id]
            assert all(0.0 <= value <= 1.0 for value in curve)
            assert all(a >= b for a, b in zip(curve[1:], curve[2:]))

    def test_everyone_is_available_before_the_first_pick(self, context, availability):
        for player in context.players:
            assert availability.probability_available(player.player_id, 1) == 1.0

    def test_the_best_players_go_earliest(self, context, availability):
        ranked = sorted(context.players, key=lambda p: -p.season_value)
        top = availability.mean_pick[ranked[0].player_id]
        deep = availability.mean_pick[ranked[80].player_id]
        assert top is not None and deep is not None and top < deep

    def test_no_next_pick_means_no_availability(self, context, availability):
        player = context.players[0].player_id
        assert availability.probability_available(player, None) == 0.0

    def test_an_unknown_player_is_not_available(self, availability):
        assert availability.probability_available("nobody", 5) == 0.0

    def test_the_selected_rate_bounds_the_mean_pick(self, context, availability):
        for player in context.players:
            if availability.selected_rate[player.player_id] == 0.0:
                assert availability.mean_pick[player.player_id] is None
            else:
                assert availability.mean_pick[player.player_id] is not None

    def test_tier_survival_falls_as_the_draft_runs(self, context, availability):
        tier = context.tiers["RB"][0]
        early = aggregate.tier_survival(availability, tier, 2)
        late = aggregate.tier_survival(availability, tier, 60)
        assert early >= late


class TestOpponentModel:
    def test_noise_widens_the_spread_of_selection_points(self, pool):
        quiet = DraftContext.build(pool, settings_for(), noise=0.1)
        loud = DraftContext.build(pool, settings_for(), noise=1.2)
        quiet_model = calibrate_availability(quiet, drafts=60, seed=SEED)
        loud_model = calibrate_availability(loud, drafts=60, seed=SEED)

        def spread(model, ctx):
            top = sorted(ctx.players, key=lambda p: -p.season_value)[:20]
            curves = [model.survival[p.player_id] for p in top]
            # How many picks it takes to go from 90% available to 10%.
            widths = []
            for curve in curves:
                high = next((i for i, v in enumerate(curve) if v <= 0.9), 0)
                low = next((i for i, v in enumerate(curve) if v <= 0.1), len(curve))
                widths.append(low - high)
            return sum(widths) / len(widths)

        assert spread(loud_model, loud) > spread(quiet_model, quiet)

    def test_opponents_fill_their_own_lineups(self, pool):
        """Without a need bonus every opposing roster is one position deep."""
        from nflfp.services.draft.engine import _consensus_draft

        context = DraftContext.build(pool, settings_for(rounds=8))
        taken = _consensus_draft(context, random.Random(3))
        drafted = {pid for pid in taken}
        positions = {
            context.players[context.index_by_id[pid]].position for pid in drafted
        }
        assert positions == {"QB", "RB", "WR", "TE"}


class TestOpponentSkill:
    """The levels have to differ in the two ways they claim to differ.

    These are the tests that stop the field quietly getting easier again. The
    feature originally shipped with a noise of 0.35, which put the random term
    some thirty-five times the gap between neighbouring players on the board:
    talent slid several rounds, the user's seat finished first in nearly every
    simulated league, and every draft position scored the same because the board
    never resembled itself twice. Nothing failed. It looked like a working
    simulation that happened to be generous.

    So the properties asserted here are the ones that were false then: that the
    board keeps its order, that a sharper level keeps it tighter, and that the
    seats can still be told apart.
    """

    def test_levels_are_ordered_from_loose_to_tight(self):
        levels = valuation.OPPONENT_SKILLS
        assert [level.name for level in levels] == ["casual", "competitive", "sharp"]
        assert [level.noise for level in levels] == sorted(
            (level.noise for level in levels), reverse=True
        )
        assert [level.history_weight for level in levels] == sorted(
            (level.history_weight for level in levels), reverse=True
        )

    def test_the_default_is_a_real_level(self):
        assert valuation.opponent_skill(None) is valuation.opponent_skill(
            valuation.DEFAULT_OPPONENT_SKILL
        )
        assert valuation.opponent_skill(None).name == "competitive"

    def test_an_unknown_level_is_refused_with_the_options(self):
        with pytest.raises(InvalidRequest) as excinfo:
            validate_opponent_skill("expert")
        assert "expert" in str(excinfo.value)
        assert "sharp" in str(excinfo.value)

    @staticmethod
    def _scatter(pool, noise, history_weight):
        settings = settings_for()
        context = DraftContext.build(
            pool, settings, noise=noise, history_weight=history_weight
        )
        return valuation.board_scatter_ratio(
            context.consensus,
            noise_scale=context.noise_scale,
            drafted=settings.total_picks,
        )

    def test_every_level_keeps_the_board_in_order(self, pool):
        """No shipped level may drown the board in its own randomness."""
        for level in valuation.OPPONENT_SKILLS:
            ratio = self._scatter(pool, level.noise, level.history_weight)
            assert 0 < ratio < valuation.MAX_ORDERLY_SCATTER, (
                f"{level.name} scatters the board by {ratio:.1f}x the gap "
                "between neighbouring players"
            )

    def test_each_level_is_tighter_than_the_one_before(self, pool):
        """The guard on the original defect, as a comparison rather than a bound.

        The ratio divides by the density of one board, so its absolute value is
        not portable between pools — see :func:`board_scatter_ratio`. Ordering
        on a single pool is portable, and it is what the levels claim. A level
        retuned to a plausible-looking noise that happens to sit out of order
        fails here.
        """
        ratios = [
            self._scatter(pool, level.noise, level.history_weight)
            for level in valuation.OPPONENT_SKILLS
        ]
        assert ratios == sorted(ratios, reverse=True), dict(
            zip((level.name for level in valuation.OPPONENT_SKILLS), ratios)
        )

    def test_every_level_is_tighter_than_the_original_default(self, pool):
        """The regression, kept so the reason for the change stays legible.

        The feature shipped at noise 0.35 and history weight 0.35. On a
        full-sized board that put the random term ~36x the gap between
        neighbouring players; the seat under analysis then finished first in 98%
        of simulated leagues and the draft positions could not be told apart.
        Every level must be a real improvement on it, not a rounding.
        """
        original = self._scatter(pool, 0.35, 0.35)
        for level in valuation.OPPONENT_SKILLS:
            assert self._scatter(pool, level.noise, level.history_weight) < original
        # And the sharp end has to be a different regime, not a nudge.
        sharp = valuation.opponent_skill("sharp")
        assert self._scatter(pool, sharp.noise, sharp.history_weight) < original / 2

    def test_a_sharper_level_holds_talent_closer_to_its_board_rank(self, pool):
        """The measurable meaning of "sharp": less slide."""
        settings = settings_for()

        def mean_slide(level):
            context = DraftContext.build(
                pool,
                settings,
                noise=level.noise,
                history_weight=level.history_weight,
            )
            model = calibrate_availability(context, drafts=60, seed=SEED)
            # Where the top of the board actually went, against where it sat.
            drifts = []
            for rank, player in enumerate(context.players[:24], start=1):
                mean = model.mean_pick.get(player.player_id)
                if mean is not None:
                    drifts.append(abs(mean - rank))
            return sum(drifts) / len(drifts)

        casual, competitive, sharp = valuation.OPPONENT_SKILLS
        assert mean_slide(sharp) < mean_slide(competitive) < mean_slide(casual)


class TestSeatAnalysis:
    def test_the_representative_draft_is_the_median_simulation(self, context, availability):
        analysis = aggregate.analyse_seat(
            context, draft_position=4, availability=availability,
            simulations=40, seed=SEED,
        )
        replay = simulate_draft(
            context,
            draft_position=4,
            availability=availability,
            rng=random.Random(f"draft:{SEED}:4:{analysis.representative_index}"),
        )
        assert replay.roster_value == analysis.representative.roster_value
        assert abs(
            analysis.representative.roster_value - analysis.roster_value.median
        ) <= analysis.roster_value.stdev

    def test_round_shares_sum_to_one_per_round(self, context, availability):
        analysis = aggregate.analyse_seat(
            context, draft_position=4, availability=availability,
            simulations=40, seed=SEED,
        )
        by_round: dict[int, float] = {}
        for entry in analysis.round_positions:
            by_round[entry.round_number] = (
                by_round.get(entry.round_number, 0.0) + entry.share
            )
        for share in by_round.values():
            assert share == pytest.approx(1.0)

    def test_the_distribution_is_ordered(self, context, availability):
        analysis = aggregate.analyse_seat(
            context, draft_position=4, availability=availability,
            simulations=40, seed=SEED,
        )
        d = analysis.roster_value
        assert d.minimum <= d.p10 <= d.p25 <= d.median <= d.p75 <= d.p90 <= d.maximum

    def test_standard_error_shrinks_with_more_simulations(self, context, availability):
        few = aggregate.analyse_seat(
            context, draft_position=4, availability=availability,
            simulations=25, seed=SEED, with_insights=False,
        )
        many = aggregate.analyse_seat(
            context, draft_position=4, availability=availability,
            simulations=200, seed=SEED, with_insights=False,
        )
        assert many.roster_value.standard_error < few.roster_value.standard_error

    def test_availability_percentages_are_coherent(self, context, availability):
        analysis = aggregate.analyse_seat(
            context, draft_position=4, availability=availability,
            simulations=30, seed=SEED,
        )
        for entry in analysis.availability:
            assert 0.0 <= entry.next_pick_probability <= 1.0
            assert entry.drafted_before_next_pick == pytest.approx(
                1.0 - entry.next_pick_probability
            ) or entry.next_reference_pick is None
            assert entry.reference_pick in analysis.picks

    def test_insights_are_grounded_in_evidence(self, context, availability):
        analysis = aggregate.analyse_seat(
            context, draft_position=4, availability=availability,
            simulations=40, seed=SEED,
        )
        assert analysis.insights
        for insight in analysis.insights:
            assert insight.evidence
            assert insight.headline and insight.detail

    def test_every_pick_explanation_names_its_numbers(self, context, availability):
        draft = simulate_draft(
            context, draft_position=4, availability=availability,
            rng=random.Random(8), capture_rationale=True,
        )
        for pick in draft.picks:
            text = aggregate.explain_pick(pick.position, pick.name, pick.rationale)
            assert pick.name in text
            assert f"{pick.rationale.marginal_value:.0f}" in text

    def test_an_explanation_of_nothing_is_empty(self):
        assert aggregate.explain_pick("RB", "Nobody", None) == ""


class TestComparison:
    def test_every_seat_appears_once_in_draft_order(self, context, availability):
        analyses = [
            aggregate.analyse_seat(
                context, draft_position=seat, availability=availability,
                simulations=20, seed=SEED, with_insights=False,
            )
            for seat in range(1, 13)
        ]
        comparison = aggregate.compare_seats(analyses)
        assert [s.draft_position for s in comparison.seats] == list(range(1, 13))

    def test_exactly_one_seat_is_marked_best(self, context, availability):
        analyses = [
            aggregate.analyse_seat(
                context, draft_position=seat, availability=availability,
                simulations=20, seed=SEED, with_insights=False,
            )
            for seat in range(1, 13)
        ]
        comparison = aggregate.compare_seats(analyses)
        assert sum(1 for s in comparison.seats if s.is_best) == 1
        best = next(s for s in comparison.seats if s.is_best)
        assert best.draft_position == comparison.best_position
        assert best.roster_value.mean == max(
            s.roster_value.mean for s in comparison.seats
        )

    def test_percentiles_span_the_seats(self, context, availability):
        analyses = [
            aggregate.analyse_seat(
                context, draft_position=seat, availability=availability,
                simulations=20, seed=SEED, with_insights=False,
            )
            for seat in range(1, 13)
        ]
        comparison = aggregate.compare_seats(analyses)
        percentiles = sorted(s.percentile for s in comparison.seats)
        assert percentiles[0] == 0.0
        assert percentiles[-1] == 1.0

    def test_an_indistinguishable_spread_is_declared(self, context, availability):
        """Identical seats must not be ranked as though they differed."""
        analyses = [
            aggregate.analyse_seat(
                context, draft_position=1, availability=availability,
                simulations=20, seed=SEED, with_insights=False,
            )
        ] * 4
        comparison = aggregate.compare_seats(analyses)
        assert comparison.spread == 0.0
        assert not comparison.spread_is_resolvable


# ---------------------------------------------------------------------------
# Historical evidence and leakage
# ---------------------------------------------------------------------------


class TestHistoricalEvidence:
    def test_a_future_season_is_refused(self):
        with pytest.raises(history.LeakageError, match="2025"):
            history.assert_no_future_seasons([{"season": 2025}], 2025)

    def test_a_season_after_the_draft_is_refused(self):
        with pytest.raises(history.LeakageError):
            history.assert_no_future_seasons([{"season": 2026}], 2025)

    def test_prior_seasons_are_allowed(self):
        history.assert_no_future_seasons([{"season": 2024}, {"season": 2019}], 2025)

    def test_assembling_a_pool_refuses_leaked_rows(self):
        with pytest.raises(history.LeakageError):
            assemble_pool(
                board_rows=[
                    {
                        "player_id": "p1",
                        "position": "RB",
                        "expected_points": 12.0,
                        "team": "AAA",
                    }
                ],
                panel_rows=[
                    {
                        "player_id": "p1",
                        "position": "RB",
                        "season": 2025,
                        "games_played": 17,
                        "total_points": 300.0,
                        "points_per_game": 17.6,
                        "weekly_stdev": 6.0,
                    }
                ],
                game_counts={2025: 17},
                season=2025,
                season_games=17,
                scoring_profile="ppr",
            )

    def test_missing_history_falls_back_to_the_position_prior(self):
        prior = history.AvailabilityPrior("RB", prior_rate=0.8, k=2.0, players=50, seasons=120)
        games, rate, basis = history.expected_games((), prior, season_games=17)
        assert basis == "position_prior"
        assert rate is None
        assert games == pytest.approx(0.8 * 17)

    def test_more_seasons_shrink_less(self):
        prior = history.AvailabilityPrior("RB", prior_rate=0.7, k=2.0, players=50, seasons=120)
        one = history.expected_games((season(2024, 300, 17),), prior, season_games=17)[0]
        many = history.expected_games(
            tuple(season(y, 300, 17) for y in (2024, 2023, 2022, 2021)),
            prior,
            season_games=17,
        )[0]
        assert many > one

    def test_the_prior_is_estimated_from_the_panel_not_assumed(self):
        panel = [
            {"player_id": f"p{p}", "position": "RB", "season": s, "games_played": g}
            for p, games in enumerate([[17, 17, 16], [8, 9, 7], [16, 15, 17]])
            for s, g in zip((2024, 2023, 2022), games)
        ]
        priors = history.estimate_availability_priors(panel, {2024: 17, 2023: 17, 2022: 17})
        assert "RB" in priors
        assert 0.0 < priors["RB"].prior_rate < 1.0
        assert history.MIN_K <= priors["RB"].k <= history.MAX_K
        assert priors["RB"].players == 3

    def test_an_empty_panel_produces_no_priors(self):
        assert history.estimate_availability_priors([], {}) == {}

    def test_availability_is_capped_at_one(self):
        entry = season(2024, 300, 20)
        assert entry.availability == 1.0

    def test_consistency_needs_a_long_enough_season(self):
        short = (season(2024, 60, 4),)
        assert history.coefficient_of_variation(short) is None
        long = (season(2024, 300, 16),)
        assert history.coefficient_of_variation(long) is not None

    def test_the_steadiest_player_gets_the_top_band(self):
        percentiles, labels = history.consistency_bands(
            {"steady": 0.2, "middling": 0.5, "wild": 0.9, "unknown": None}
        )
        assert percentiles["steady"] == 1.0
        assert labels["steady"] == "High"
        assert labels["wild"] == "Low"
        assert "unknown" not in labels

    def test_a_single_measured_player_is_banded_without_dividing_by_zero(self):
        percentiles, labels = history.consistency_bands({"only": 0.4})
        assert percentiles["only"] == 1.0
        assert labels["only"] == "High"

    def test_no_trend_is_reported_from_one_season(self):
        assert history.describe_trend((season(2024, 300),)) == (None, None)

    def test_a_rise_is_named_a_rise(self):
        trend, detail = history.describe_trend(
            (ranked_season(2024, 0.9), ranked_season(2023, 0.4))
        )
        assert trend == "rising"
        assert "2023" in detail

    def test_a_fall_is_named_a_fall(self):
        seasons = (ranked_season(2024, 0.3), ranked_season(2023, 0.8))
        assert history.describe_trend(seasons)[0] == "declining"

    def test_a_small_move_is_steady(self):
        seasons = (ranked_season(2024, 0.60), ranked_season(2023, 0.57))
        assert history.describe_trend(seasons)[0] == "steady"

    def test_ranking_within_position_is_per_season(self):
        rows = [
            {"player_id": "a", "position": "RB", "season": 2024, "total_points": 300},
            {"player_id": "b", "position": "RB", "season": 2024, "total_points": 100},
            {"player_id": "a", "position": "RB", "season": 2023, "total_points": 50},
            {"player_id": "b", "position": "RB", "season": 2023, "total_points": 200},
        ]
        ranked = history.rank_within_position(rows)
        assert ranked[("a", 2024)] == (1, 1.0)
        assert ranked[("b", 2023)] == (1, 1.0)


class TestPoolAssembly:
    def _board(self, **overrides):
        row = {
            "player_id": "p1",
            "player_name": "Player One",
            "position": "RB",
            "team": "AAA",
            "expected_points": 15.0,
            "predicted_points": 99.0,
            "floor_points": 6.0,
            "ceiling_points": 26.0,
            "extrapolated": False,
        }
        row.update(overrides)
        return row

    def test_season_value_is_the_rate_times_the_games(self):
        pool = assemble_pool(
            board_rows=[self._board()],
            panel_rows=[
                {
                    "player_id": "p1",
                    "position": "RB",
                    "season": 2024,
                    "games_played": 17,
                    "total_points": 280.0,
                    "points_per_game": 16.5,
                    "weekly_stdev": 6.0,
                }
            ],
            game_counts={2024: 17},
            season=2025,
            season_games=17,
            scoring_profile="ppr",
        )
        player = pool.players[0]
        assert player.season_value == pytest.approx(
            player.projected_points_per_game * player.expected_games
        )
        assert player.projected_points_per_game == 15.0

    def test_the_biased_predicted_points_are_never_used(self):
        """`predicted_points` is documented as not-for-display; a row without
        `expected_points` is skipped rather than ranked on it."""
        pool = assemble_pool(
            board_rows=[self._board(expected_points=None)],
            panel_rows=[],
            game_counts={},
            season=2025,
            season_games=17,
            scoring_profile="ppr",
        )
        assert pool.players == ()

    def test_a_player_with_no_history_still_makes_the_board(self):
        pool = assemble_pool(
            board_rows=[self._board()],
            panel_rows=[],
            game_counts={},
            season=2025,
            season_games=17,
            scoring_profile="ppr",
        )
        assert len(pool.players) == 1
        assert pool.players[0].historical.availability_basis == "position_prior"
        assert pool.players[0].historical.seasons == ()

    def test_the_board_is_ordered_by_season_value(self):
        pool = assemble_pool(
            board_rows=[
                self._board(player_id="a", expected_points=10.0),
                self._board(player_id="b", expected_points=20.0),
            ],
            panel_rows=[],
            game_counts={},
            season=2025,
            season_games=17,
            scoring_profile="ppr",
        )
        assert [p.player_id for p in pool.players] == ["b", "a"]

    def test_notices_name_the_missing_rookies_and_the_rate_assumption(self):
        pool = assemble_pool(
            board_rows=[self._board()],
            panel_rows=[],
            game_counts={},
            season=2025,
            season_games=17,
            scoring_profile="ppr",
        )
        joined = " ".join(pool.notices)
        assert "rookies" in joined
        assert "per-game rate" in joined

    def test_notices_count_the_players_whose_evidence_is_years_old(self):
        """A stale window is indistinguishable from a fresh one by count alone.

        `games_in_window_l4` counts games *played*, so a player who last
        appeared in 2022 reaches a 2026 board with a full four-game window and
        the shrinkage trusts it exactly as much as last January's. The board
        has to say so.
        """
        panel = [
            {
                "player_id": "p1", "position": "RB", "season": 2022,
                "games_played": 17, "total_points": 200.0,
                "points_per_game": 11.8, "weekly_stdev": 6.0,
            }
        ]
        pool = assemble_pool(
            board_rows=[self._board()],
            panel_rows=panel,
            game_counts={},
            season=2026,
            season_games=17,
            scoring_profile="ppr",
        )
        joined = " ".join(pool.notices)
        assert "last recorded a stat line before 2025" in joined
        assert "4 seasons ago" in joined

    def test_a_current_player_raises_no_staleness_notice(self):
        panel = [
            {
                "player_id": "p1", "position": "RB", "season": 2025,
                "games_played": 17, "total_points": 200.0,
                "points_per_game": 11.8, "weekly_stdev": 6.0,
            }
        ]
        pool = assemble_pool(
            board_rows=[self._board()],
            panel_rows=panel,
            game_counts={},
            season=2026,
            season_games=17,
            scoring_profile="ppr",
        )
        assert "last recorded a stat line" not in " ".join(pool.notices)

    def test_history_and_projection_stay_separable(self):
        """A monstrous historical season must not move the projected rate."""
        pool = assemble_pool(
            board_rows=[self._board()],
            panel_rows=[
                {
                    "player_id": "p1",
                    "position": "RB",
                    "season": 2024,
                    "games_played": 17,
                    "total_points": 9_999.0,
                    "points_per_game": 588.0,
                    "weekly_stdev": 6.0,
                }
            ],
            game_counts={2024: 17},
            season=2025,
            season_games=17,
            scoring_profile="ppr",
        )
        assert pool.players[0].projected_points_per_game == 15.0
        assert pool.players[0].historical.seasons[0].total_points == 9_999.0


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


class TestEvaluation:
    def test_every_strategy_produces_a_legal_roster(self, context, availability):
        for strategy in STRATEGIES:
            draft = simulate_draft(
                context,
                draft_position=4,
                availability=availability,
                rng=random.Random(6),
                strategy=strategy,
            )
            assert len(draft.picks) == context.settings.rounds
            assert len(draft.starters) == context.settings.starters

    def test_an_unknown_strategy_is_refused(self, context, availability):
        with pytest.raises(ValueError, match="unknown draft strategy"):
            simulate_draft(
                context,
                draft_position=4,
                availability=availability,
                rng=random.Random(6),
                strategy="wishful_thinking",
            )

    def test_the_strategy_beats_taking_the_highest_projected_total(
        self, context, availability
    ):
        """On the fixture board, where the answer is knowable by construction.

        The board is built so that receivers are deep and quarterbacks flat, so
        a strategy that reads raw season totals over-drafts quarterbacks and
        under-drafts the positions that are actually scarce. Measured on the
        *simulated* values here rather than on actuals — the fixture has no
        actuals — with the real backtest in `scripts/phase8e_evaluate.py`.
        """
        actual = {p.player_id: p.season_value for p in context.players}
        results = evaluate.compare_strategies(
            context,
            availability=availability,
            actual_points=actual,
            seats=[1, 6, 12],
            simulations=15,
            seed=SEED,
        )
        by_name = {r.strategy: r for r in results}
        assert (
            by_name["value_over_next_available"].mean_actual_points
            > by_name["highest_season_value"].mean_actual_points
        )
        assert (
            by_name["value_over_next_available"].mean_actual_points
            > by_name["random"].mean_actual_points
        )

    def test_projection_accuracy_counts_players_who_never_played(self, context):
        entries = evaluate.projection_accuracy(context.players[:20], {})
        assert entries
        for entry in entries:
            assert entry.mean_actual == 0.0
            assert entry.bias < 0

    def test_availability_calibration_is_close(self, context, availability):
        bins = evaluate.availability_calibration(
            context, availability=availability, seat=4, simulations=15, seed=SEED
        )
        summary = evaluate.summarise_calibration(bins)
        assert summary["expected_calibration_error"] < 0.10

    def test_calibration_of_nothing_is_zero_rather_than_a_crash(self):
        assert evaluate.summarise_calibration([]) == {
            "expected_calibration_error": 0.0,
            "max_calibration_error": 0.0,
        }
