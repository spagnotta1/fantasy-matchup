"""Lineup slots and lineup validation.

Two things are being defended here.

The first is that the slot rules are **data**. The tests iterate
:data:`~nflfp.services.lineup.LINEUP_SLOTS` rather than hard-coding five
strings, so adding a SUPERFLEX slot or shipping a kicker model is picked up
automatically and any validator that would have ignored it fails here.

The second is that an unsupported slot produces an *explanation*, not a shrug.
"Unknown slot 'K'" reads like a typo; the truth is that no kicker model exists,
and the reason and the blockers already live in the position registry. A test
that only asserted "raises" would pass against either message.
"""

from __future__ import annotations

import pytest

from nflfp.services import lineup
from nflfp.services.errors import InvalidRequest
from nflfp.services.positions import POSITION_SUPPORT, describe


def entries(*pairs: tuple[str, str]) -> list[dict]:
    return [{"player_id": player_id, "slot": slot} for player_id, slot in pairs]


#: A lineup that satisfies STANDARD_FORMAT. Built from the format rather than
#: typed out, so a change to the format changes this with it.
def valid_entries(prefix: str = "p") -> list[dict]:
    built: list[dict] = []
    index = 0
    for requirement in lineup.STANDARD_FORMAT.requirements:
        for _ in range(requirement.count):
            built.append({"player_id": f"{prefix}{index}", "slot": requirement.slot})
            index += 1
    return built


# ---------------------------------------------------------------------------
# The vocabulary
# ---------------------------------------------------------------------------


class TestTheSlotRegistry:
    """The rules are declared once and derived everywhere else."""

    def test_the_five_skill_slots_exist(self):
        assert {"QB", "RB", "WR", "TE", "FLEX"} <= set(lineup.KNOWN_SLOTS)

    def test_flex_accepts_rb_wr_te_and_nothing_else(self):
        flex = lineup.slot("FLEX")
        assert flex is not None
        assert set(flex.eligible_positions) == {"RB", "WR", "TE"}
        # A superflex league is a different *format*, not a wider FLEX.
        assert not flex.accepts("QB")
        assert not flex.accepts("K")

    @pytest.mark.parametrize("code", ["QB", "RB", "WR", "TE"])
    def test_a_single_position_slot_accepts_only_that_position(self, code):
        entry = lineup.slot(code)
        assert entry is not None
        assert entry.eligible_positions == (code,)

    def test_lookup_is_case_and_whitespace_insensitive(self):
        assert lineup.slot("  flex ") is lineup.slot("FLEX")

    def test_an_unknown_slot_resolves_to_none(self):
        assert lineup.slot("SUPERFLEX") is None

    def test_support_is_derived_from_the_position_registry(self):
        # Not restated here. If a kicker model ships, POSITION_SUPPORT changes
        # and the K slot becomes supported with no edit to lineup.py.
        for entry in lineup.LINEUP_SLOTS:
            expected = all(
                (support := describe(position)) is not None and support.is_projected
                for position in entry.eligible_positions
            )
            assert entry.is_supported is expected

    def test_every_projected_position_has_a_slot(self):
        # The extension path in the other direction: a position the engine
        # projects but no slot admits would be unusable in a lineup.
        fillable = {
            position
            for entry in lineup.LINEUP_SLOTS
            for position in entry.eligible_positions
        }
        for support in POSITION_SUPPORT:
            if support.is_projected:
                assert support.position in fillable

    def test_unsupported_slots_are_recognised_rather_than_absent(self):
        # The whole point: refusing K as "unknown" would misrepresent a missing
        # model as a typo.
        for code in ("K", "DST"):
            entry = lineup.slot(code)
            assert entry is not None
            assert not entry.is_supported
            assert entry.unsupported_positions

    def test_supported_slots_are_derived_not_listed(self):
        assert lineup.SUPPORTED_SLOTS == tuple(
            entry.slot for entry in lineup.LINEUP_SLOTS if entry.is_supported
        )
        assert "K" not in lineup.SUPPORTED_SLOTS
        assert "DST" not in lineup.SUPPORTED_SLOTS


class TestTheFormat:
    def test_the_standard_format_is_the_seven_projectable_starters(self):
        assert lineup.STANDARD_FORMAT.size == 7
        assert lineup.STANDARD_FORMAT.required("RB") == 2
        assert lineup.STANDARD_FORMAT.required("WR") == 2
        assert lineup.STANDARD_FORMAT.required("FLEX") == 1

    def test_the_format_names_no_unsupported_slot(self):
        # A format requiring a slot nothing can fill would make every lineup
        # invalid. Stated as a test so shipping a kicker model has to update
        # both the registry and the format deliberately.
        for requirement in lineup.STANDARD_FORMAT.requirements:
            entry = lineup.slot(requirement.slot)
            assert entry is not None and entry.is_supported

    def test_an_unknown_format_is_refused(self):
        with pytest.raises(InvalidRequest) as caught:
            lineup.lineup_format("superflex")
        assert "unknown lineup format" in str(caught.value)

    def test_none_resolves_to_the_default(self):
        assert lineup.lineup_format(None) is lineup.STANDARD_FORMAT


# ---------------------------------------------------------------------------
# Structural validation — no database
# ---------------------------------------------------------------------------


class TestStructuralValidation:
    def test_a_valid_lineup_normalises(self):
        result = lineup.validate_structure(valid_entries(), side="team_a")
        assert len(result.entries) == lineup.STANDARD_FORMAT.size
        assert result.side == "team_a"
        assert result.slot_of("p0") == "QB"

    def test_slots_and_ids_are_normalised(self):
        result = lineup.validate_structure(
            [{"player_id": " p0 ", "slot": "qb"}]
            + valid_entries()[1:],
            side="team_a",
        )
        assert result.entries[0].player_id == "p0"
        assert result.entries[0].slot == "QB"

    def test_a_missing_required_slot_is_refused(self):
        short = valid_entries()[:-1]  # drop the FLEX
        with pytest.raises(InvalidRequest) as caught:
            lineup.validate_structure(short, side="team_a")
        message = str(caught.value)
        assert "FLEX" in message
        # The message says what a legal lineup looks like, not just that this
        # one is not.
        assert "1xQB" in message and "2xRB" in message

    def test_too_many_of_a_slot_is_refused(self):
        extra = valid_entries() + [{"player_id": "extra", "slot": "QB"}]
        with pytest.raises(InvalidRequest) as caught:
            lineup.validate_structure(extra, side="team_b")
        assert "team_b" in str(caught.value)
        assert "exactly 1 QB" in str(caught.value)

    def test_a_slot_outside_the_format_is_refused(self):
        # A legal slot the format does not start. Distinguished from an unknown
        # slot, because the fix is a different format rather than a typo.
        swapped = valid_entries()[:-1] + [{"player_id": "x", "slot": "WR"}]
        with pytest.raises(InvalidRequest) as caught:
            lineup.validate_structure(swapped, side="team_a")
        assert "WR" in str(caught.value)

    def test_a_duplicate_player_is_refused_not_collapsed(self):
        # Collapsing would silently drop a starter and produce a total that is
        # a player light with nothing to say so.
        duplicated = valid_entries()
        duplicated[2] = {"player_id": duplicated[1]["player_id"], "slot": "RB"}
        with pytest.raises(InvalidRequest) as caught:
            lineup.validate_structure(duplicated, side="team_a")
        assert "more than once" in str(caught.value)

    def test_the_same_player_on_both_sides_is_allowed(self):
        # Two hypothetical lineups are a legitimate what-if. The duplicate rule
        # is per lineup, and league legality is not this engine's business.
        a = lineup.validate_structure(valid_entries("p"), side="team_a")
        b = lineup.validate_structure(valid_entries("p"), side="team_b")
        assert a.player_ids == b.player_ids

    def test_a_blank_player_id_is_refused(self):
        blank = valid_entries()
        blank[0] = {"player_id": "   ", "slot": "QB"}
        with pytest.raises(InvalidRequest) as caught:
            lineup.validate_structure(blank, side="team_a")
        assert "no player id" in str(caught.value)

    def test_an_unknown_slot_is_refused_with_the_known_list(self):
        unknown = valid_entries()
        unknown[0] = {"player_id": "p0", "slot": "SUPERFLEX"}
        with pytest.raises(InvalidRequest) as caught:
            lineup.validate_structure(unknown, side="team_a")
        assert "unknown slot" in str(caught.value)
        assert "FLEX" in str(caught.value)

    def test_the_side_is_always_named(self):
        # With two lineups in one request, "which one?" is the first thing a
        # caller needs and the cheapest thing to forget.
        for side in ("team_a", "team_b"):
            with pytest.raises(InvalidRequest) as caught:
                lineup.validate_structure([], side=side)
            assert side in str(caught.value)
            assert caught.value.field.startswith(side)

    @pytest.mark.parametrize("code", ["K", "DST"])
    def test_an_unsupported_slot_explains_itself(self, code):
        with pytest.raises(InvalidRequest) as caught:
            lineup.validate_structure(
                [{"player_id": "p0", "slot": code}], side="team_a"
            )
        message = str(caught.value)
        support = describe(code)
        assert support is not None
        # The reason and the blockers, read from the position registry rather
        # than restated — so this cannot drift from what /meta/positions says.
        assert support.reason.split(".")[0] in message
        assert support.blocked_on[0] in message
        # And what the caller can do instead.
        assert "FLEX" in message


# ---------------------------------------------------------------------------
# Eligibility — needs positions
# ---------------------------------------------------------------------------


class TestEligibility:
    def positions(self, **overrides) -> dict[str, str]:
        by_player = {}
        for entry in valid_entries():
            slot_entry = lineup.slot(entry["slot"])
            assert slot_entry is not None
            by_player[entry["player_id"]] = slot_entry.eligible_positions[0]
        by_player.update(overrides)
        return by_player

    def test_a_correct_lineup_passes(self):
        built = lineup.validate_structure(valid_entries(), side="team_a")
        lineup.validate_eligibility(built, self.positions())

    @pytest.mark.parametrize("position", ["RB", "WR", "TE"])
    def test_flex_accepts_every_eligible_position(self, position):
        built = lineup.validate_structure(valid_entries(), side="team_a")
        flex_id = built.entries[-1].player_id
        lineup.validate_eligibility(built, self.positions(**{flex_id: position}))

    def test_a_quarterback_in_the_flex_is_refused(self):
        built = lineup.validate_structure(valid_entries(), side="team_a")
        flex_id = built.entries[-1].player_id
        with pytest.raises(InvalidRequest) as caught:
            lineup.validate_eligibility(built, self.positions(**{flex_id: "QB"}))
        message = str(caught.value)
        # Player, position, slot and what the slot accepts — all four, because
        # any three of them leaves the caller guessing.
        assert flex_id in message and "QB" in message and "Flex" in message
        assert "'RB', 'WR', 'TE'" in message

    def test_a_receiver_in_the_quarterback_slot_is_refused(self):
        built = lineup.validate_structure(valid_entries(), side="team_b")
        qb_id = built.entries[0].player_id
        with pytest.raises(InvalidRequest) as caught:
            lineup.validate_eligibility(built, self.positions(**{qb_id: "WR"}))
        assert "team_b" in str(caught.value)

    @pytest.mark.parametrize("position", ["K", "DST"])
    def test_an_unprojected_position_in_a_flex_explains_the_gap(self, position):
        # The same gap wearing a different label: a kicker submitted in a FLEX
        # gets the kicker explanation, not a generic eligibility refusal.
        built = lineup.validate_structure(valid_entries(), side="team_a")
        flex_id = built.entries[-1].player_id
        with pytest.raises(InvalidRequest) as caught:
            lineup.validate_eligibility(built, self.positions(**{flex_id: position}))
        support = describe(position)
        assert support is not None
        assert support.blocked_on[0] in str(caught.value)

    def test_an_unknown_position_is_refused_rather_than_assumed(self):
        built = lineup.validate_structure(valid_entries(), side="team_a")
        missing = dict(self.positions())
        del missing[built.entries[0].player_id]
        with pytest.raises(InvalidRequest) as caught:
            lineup.validate_eligibility(built, missing)
        assert "unknown position" in str(caught.value)


# ---------------------------------------------------------------------------
# The capability listing
# ---------------------------------------------------------------------------


class TestSummaries:
    def test_the_slot_summary_covers_every_slot(self):
        summary = lineup.slot_summary()
        assert [entry["slot"] for entry in summary] == list(lineup.KNOWN_SLOTS)

    def test_the_slot_summary_is_json_serialisable(self):
        import json

        json.dumps(lineup.slot_summary())
        json.dumps(lineup.format_summary())

    def test_unsupported_slots_carry_their_unsupported_positions(self):
        by_slot = {entry["slot"]: entry for entry in lineup.slot_summary()}
        assert by_slot["K"]["supported"] is False
        assert by_slot["K"]["unsupported_positions"] == ["K"]
        assert by_slot["FLEX"]["supported"] is True
        assert by_slot["FLEX"]["unsupported_positions"] == []

    def test_the_format_summary_reports_the_size(self):
        summary = lineup.format_summary()
        assert summary[0]["name"] == "standard_skill"
        assert summary[0]["size"] == 7
