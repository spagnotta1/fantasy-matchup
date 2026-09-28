"""Trade values over HTTP, against a real warehouse.

The arithmetic is covered in ``test_services_trade``. What is left is that the
week's board, the bye-week lookback and the history panel come back in shapes
the assembler understands, and that the labels travel. Skips without a loaded
warehouse, like the draft suite.
"""

from __future__ import annotations

import pytest

from .conftest import requires_db

pytestmark = [pytest.mark.integration, requires_db]


@pytest.fixture(scope="module")
def payload():
    from fastapi.testclient import TestClient

    from nflfp.api.main import create_app

    with TestClient(create_app()) as client:
        response = client.get("/api/v1/trade/values", params={"scoring_profile": "ppr"})
        assert response.status_code == 200, response.text
        body = response.json()
        if not body["data"]["values"]:
            pytest.skip("no published board for the resolved week")
        return body


def test_is_derived_and_not_applied(payload):
    assert payload["data"]["provenance"] == "derived"
    assert payload["data"]["applied_to_projection"] is False
    assert "not a forecast" in " ".join(payload["meta"]["notices"])


def test_values_are_ordered_and_never_negative(payload):
    values = payload["data"]["values"]
    worth = [v["trade_value"] for v in values]
    assert worth == sorted(worth, reverse=True)
    assert min(worth) >= 0
    assert [v["overall_rank"] for v in values] == list(range(1, len(values) + 1))


def test_every_position_has_a_waiver_level(payload):
    positions = {v["position"] for v in payload["data"]["values"]}
    assert positions <= {r["position"] for r in payload["data"]["replacement"]}


def test_bye_week_rates_come_from_an_earlier_week(payload):
    week = payload["data"]["week"]
    for value in payload["data"]["values"]:
        if value["on_bye"]:
            assert value["rate_week"] < week
        else:
            assert value["rate_week"] == week
