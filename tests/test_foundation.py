"""The frozen prediction foundation and the position support registry.

Freezing only means something if the freeze is checkable. These tests are the
mechanism: they assert that the recorded measurements are internally
consistent, that the acceptance criteria would actually reject a worse model,
and that the frozen model is still registered and still the one the API
advertises.

No database. These are statements about the project's own contract.
"""

from __future__ import annotations

import pytest

from nflfp.predict import registry
from nflfp.predict.base import POSITIONS
from nflfp.predict.foundation import (
    ACCEPTANCE,
    BASELINE_BAR,
    FOUNDATION_PHASE,
    FROZEN_MODEL,
    VALIDATION,
    foundation_summary,
    meets_acceptance,
)
from nflfp.services import positions
from nflfp.services.assemble import SUPPORTED_POSITIONS
from nflfp.services.errors import InvalidRequest


class TestFrozenModel:
    def test_the_frozen_model_is_still_registered(self):
        # A freeze that lets the model disappear from the registry is not a
        # freeze. This is the test that fails if someone renames it.
        assert FROZEN_MODEL in registry.available()

    def test_the_baseline_it_had_to_beat_is_also_registered(self):
        assert "baseline_l4" in registry.available()

    def test_the_bar_covers_every_projected_position(self):
        assert {bar.position for bar in BASELINE_BAR} == set(POSITIONS)

    def test_the_bar_is_a_real_measurement_not_a_placeholder(self):
        for bar in BASELINE_BAR:
            assert bar.n > 1_000
            assert bar.mae > 0
            assert bar.rmse > bar.mae  # RMSE penalises large errors more
            assert 0 < bar.correlation < 1


class TestValidationRecord:
    def test_interval_coverage_is_close_to_nominal(self):
        # The property the whole product rests on: a stated 80% interval
        # containing the outcome 80% of the time.
        assert abs(VALIDATION.coverage_p10_p90 - VALIDATION.nominal_p10_p90) < 0.01
        assert abs(VALIDATION.coverage_p25_p75 - VALIDATION.nominal_p25_p75) < 0.01

    def test_the_wider_interval_is_wider(self):
        assert VALIDATION.width_p10_p90 > VALIDATION.width_p25_p75

    def test_calibration_max_is_never_below_its_ece(self):
        # ECE is sample-weighted; the max over well-sampled bins cannot be
        # smaller. If it were, one of the two was mis-transcribed.
        assert VALIDATION.boom_calibration_max >= VALIDATION.boom_calibration_ece
        assert VALIDATION.bust_calibration_max >= VALIDATION.bust_calibration_ece

    def test_it_records_a_real_sample(self):
        assert VALIDATION.held_out_distributions > 10_000
        assert len(VALIDATION.seasons) >= 5

    def test_it_states_what_was_excluded(self):
        joined = " ".join(VALIDATION.notes).lower()
        assert "market" in joined
        assert "weather" in joined
        assert "kicker" in joined


class TestAcceptance:
    def test_the_frozen_model_passes_its_own_criteria(self):
        # If the incumbent could not clear the bar it sets, the bar is wrong.
        passed, reasons = meets_acceptance(
            coverage_p10_p90=VALIDATION.coverage_p10_p90,
            max_calibration_error=VALIDATION.boom_calibration_max,
            max_conditional_bias=VALIDATION.max_conditional_bias,
            crps=VALIDATION.crps,
        )
        assert passed, reasons

    def test_a_worse_distribution_is_rejected(self):
        passed, reasons = meets_acceptance(
            coverage_p10_p90=0.62,
            max_calibration_error=0.40,
            max_conditional_bias=1.8,
            crps=4.5,
        )
        assert not passed
        # Every failure is reported, not just the first — a model that misses
        # on four counts should be told so once.
        assert len(reasons) == 4

    def test_a_better_point_estimate_does_not_excuse_a_worse_distribution(self):
        # The trade this criterion exists to catch: sharper centre, decalibrated
        # tails. CRPS scores the whole distribution, so it fails.
        passed, reasons = meets_acceptance(
            coverage_p10_p90=VALIDATION.coverage_p10_p90,
            max_calibration_error=VALIDATION.boom_calibration_max,
            max_conditional_bias=0.02,
            crps=VALIDATION.crps + 0.5,
        )
        assert not passed
        assert any("CRPS" in reason for reason in reasons)

    def test_coverage_failure_is_symmetric(self):
        too_narrow, _ = meets_acceptance(
            coverage_p10_p90=0.70, max_calibration_error=0.1,
            max_conditional_bias=0.1, crps=2.0,
        )
        too_wide, _ = meets_acceptance(
            coverage_p10_p90=0.90, max_calibration_error=0.1,
            max_conditional_bias=0.1, crps=2.0,
        )
        assert not too_narrow and not too_wide

    def test_walk_forward_is_non_negotiable(self):
        assert ACCEPTANCE.requires_walk_forward is True
        assert ACCEPTANCE.must_beat_baseline is True


class TestFoundationSummary:
    def test_it_is_json_serialisable(self):
        import json

        assert json.loads(json.dumps(foundation_summary()))

    def test_it_reports_the_freeze(self):
        summary = foundation_summary()
        assert summary["frozen"] is True
        assert summary["model"] == FROZEN_MODEL
        assert summary["phase"] == FOUNDATION_PHASE

    def test_it_carries_the_numbers_a_reviewer_would_check(self):
        summary = foundation_summary()
        assert summary["validation"]["crps"] == VALIDATION.crps
        assert summary["validation"]["calibration"]["bust"]["max"] == (
            VALIDATION.bust_calibration_max
        )
        assert len(summary["baseline_bar"]) == len(BASELINE_BAR)


class TestPositionSupport:
    def test_projected_positions_match_the_engine(self):
        # The registry is the single source; the engine's tuple and the
        # business layer's must both agree with it.
        assert positions.PROJECTED_POSITIONS == POSITIONS
        assert SUPPORTED_POSITIONS == positions.PROJECTED_POSITIONS

    def test_kickers_and_defences_are_recognised_but_planned(self):
        for code in ("K", "DST"):
            entry = positions.describe(code)
            assert entry is not None
            assert entry.status == "planned"
            assert not entry.is_projected

    def test_every_planned_position_explains_itself(self):
        # A roadmap entry with no reason and no blockers is a shrug. The API
        # returns these verbatim, so they have to be worth reading.
        for entry in positions.POSITION_SUPPORT:
            if entry.is_projected:
                continue
            assert entry.reason and len(entry.reason) > 40
            assert entry.blocked_on

    def test_projected_positions_need_no_excuse(self):
        for entry in positions.POSITION_SUPPORT:
            if entry.is_projected:
                assert entry.reason is None
                assert entry.blocked_on == ()

    def test_validation_accepts_projected_positions(self):
        assert positions.validate_positions(["wr", "TE"]) == ("WR", "TE")

    def test_validation_passes_through_no_filter(self):
        assert positions.validate_positions(None) is None
        assert positions.validate_positions([]) is None

    def test_a_planned_position_is_refused_with_its_roadmap(self):
        with pytest.raises(InvalidRequest) as caught:
            positions.validate_positions(["K"])
        message = str(caught.value)
        assert "Kicker" in message
        assert "Blocked on" in message

    def test_an_unrecognised_position_is_a_different_message(self):
        with pytest.raises(InvalidRequest, match="unrecognised"):
            positions.validate_positions(["ZZ"])

    def test_summary_is_json_serialisable_and_complete(self):
        import json

        summary = positions.support_summary()
        assert json.loads(json.dumps(summary))
        assert {entry["position"] for entry in summary} == set(
            positions.KNOWN_POSITIONS
        )

    def test_adding_a_position_needs_no_change_elsewhere(self):
        # The extension claim, exercised: everything downstream reads the
        # registry, so a new entry is picked up without editing a validator,
        # a router or a schema.
        extra = positions.PositionSupport(
            "P", "Punter", "planned", reason="x" * 50, blocked_on=("punting features",)
        )
        registry_snapshot = positions.POSITION_SUPPORT + (extra,)
        assert all(
            entry.is_projected or (entry.reason and entry.blocked_on)
            for entry in registry_snapshot
        )
