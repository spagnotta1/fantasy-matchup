"""Tests for reconciling the registry's cadence with Railway.

The registry is the single source of truth for how often anything runs. What
these tests guard is the *last link*: that the cadence declared in
``nflfp.jobs.registry`` is the cadence Railway is actually running.

That link used to be a generated file. ``schedule --emit`` wrote one
``deploy/railway.<job>.json`` per job, a test asserted those files matched the
registry, and the assertion was true and useless — Railway deprecated pointing
a service at a config path outside the repository root, so nothing consumed
them. The schedules could drift freely while the test stayed green.

So the check now runs against what Railway reports. Every test here drives it
through a stub transport: no network, no token, no installed CLI.
"""

from __future__ import annotations

import json

import pytest

from nflfp.jobs.railway import (
    CliTransport,
    DeployedService,
    DesiredService,
    Drift,
    PIPELINE_SCHEDULE,
    PIPELINE_SERVICE,
    RailwayUnavailable,
    apply,
    deployed_services,
    desired_services,
    diff,
    environment_id,
    manual_service_names,
)
from nflfp.jobs.registry import MANUAL, REGISTRY

ENVIRONMENT = "env-1234"


class StubTransport:
    """A Railway that answers from a dict and records what it was told."""

    def __init__(self, services: dict[str, tuple[str | None, str | None]]):
        # name -> (start_command, cron_schedule)
        self._services = services
        self.mutations: list[str] = []

    def status(self) -> dict:
        return {
            "environments": {
                "edges": [
                    {
                        "node": {
                            "id": ENVIRONMENT,
                            "name": "production",
                            "serviceInstances": {
                                "edges": [
                                    {
                                        "node": {
                                            "serviceName": name,
                                            "serviceId": f"id-{name}",
                                            "startCommand": start,
                                            "cronSchedule": cron,
                                        }
                                    }
                                    for name, (start, cron) in self._services.items()
                                ]
                            },
                        }
                    }
                ]
            }
        }

    def graphql(self, document: str) -> dict:
        self.mutations.append(document)
        return {"data": {"serviceInstanceUpdate": True}}


def _correct_deployment() -> dict[str, tuple[str | None, str | None]]:
    """A Railway project that matches the registry exactly."""
    services = {
        service.name: (service.start_command, service.cron_schedule)
        for service in desired_services()
    }
    # Things that legitimately exist beside the cron services.
    services["api"] = ("python -m nflfp.api", None)
    services["Postgres"] = (None, None)
    return services


class TestWhatTheRegistryWants:
    def test_every_scheduled_job_becomes_a_service(self):
        names = {service.name for service in desired_services()}
        for job in REGISTRY.scheduled():
            assert job.service_name in names

    def test_the_warehouse_refresh_is_included_though_it_is_not_a_job(self):
        """`pipeline refresh` is a pipeline entry point, not a registered job.
        It still has a cadence, and a reconciler that silently omitted it would
        let the one service the whole chain depends on drift unwatched."""
        services = {s.name: s for s in desired_services()}
        assert PIPELINE_SERVICE in services
        assert services[PIPELINE_SERVICE].cron_schedule == PIPELINE_SCHEDULE

    def test_the_warehouse_refresh_runs_before_the_feature_build(self):
        """The Tuesday chain in dependency order: a step that overruns must not
        have the next one start against half-loaded data."""
        pipeline_hour = int(PIPELINE_SCHEDULE.split()[1])
        features_hour = int(REGISTRY.get("build_features").schedule.split()[1])
        assert pipeline_hour < features_hour

    def test_a_manual_job_never_becomes_a_scheduled_service(self):
        """`invalidate_cache` on a timer would be a slow leak of the benefit
        the cache exists to provide."""
        names = {service.name for service in desired_services()}
        assert "invalidate-cache" not in names
        assert "backfill-projections" not in names

    def test_service_names_are_kebab_case(self):
        for service in desired_services():
            assert "_" not in service.name, service.name

    def test_job_service_name_round_trips(self):
        assert REGISTRY.get("refresh_odds").service_name == "refresh-odds"
        assert REGISTRY.get("generate_projections").service_name == "generate-projections"

    def test_start_command_matches_the_cli_that_exists(self):
        job = REGISTRY.get("refresh_odds")
        assert job.start_command == "python -m nflfp.jobs run refresh_odds"
        assert job.name in REGISTRY.names()


class TestDriftDetection:
    def test_a_matching_project_reports_nothing(self):
        transport = StubTransport(_correct_deployment())
        assert diff(desired_services(), deployed_services(transport), manual_service_names()) == []

    def test_a_changed_cron_is_reported(self):
        """The failure the deleted generator was trying to prevent: somebody
        edits a schedule in the dashboard and the registry no longer describes
        what runs."""
        services = _correct_deployment()
        services["refresh-odds"] = (services["refresh-odds"][0], "0 */4 * * *")
        drifts = diff(
            desired_services(), deployed_services(StubTransport(services)), manual_service_names()
        )
        assert [d.service for d in drifts] == ["refresh-odds"]
        assert drifts[0].field == "cronSchedule"
        assert drifts[0].actual == "0 */4 * * *"
        assert drifts[0].expected == REGISTRY.get("refresh_odds").schedule

    def test_a_changed_start_command_is_reported(self):
        services = _correct_deployment()
        services["warm-cache"] = ("python -m nflfp.jobs run warm_caches", services["warm-cache"][1])
        drifts = diff(
            desired_services(), deployed_services(StubTransport(services)), manual_service_names()
        )
        assert [(d.service, d.field) for d in drifts] == [("warm-cache", "startCommand")]

    def test_a_missing_service_is_reported(self):
        """The state this project was actually in: nine services declared, none
        provisioned, and nothing anywhere saying so."""
        services = _correct_deployment()
        del services["pipeline"]
        drifts = diff(
            desired_services(), deployed_services(StubTransport(services)), manual_service_names()
        )
        assert [(d.service, d.field) for d in drifts] == [("pipeline", "service")]

    def test_a_cron_on_a_manual_job_is_reported(self):
        """The inverse failure: somebody schedules `invalidate_cache`, and the
        cache gets discarded on a timer."""
        services = _correct_deployment()
        services["invalidate-cache"] = (
            "python -m nflfp.jobs run invalidate_cache",
            "0 * * * *",
        )
        drifts = diff(
            desired_services(), deployed_services(StubTransport(services)), manual_service_names()
        )
        assert [(d.service, d.field) for d in drifts] == [("invalidate-cache", "cronSchedule")]

    def test_unrelated_services_are_ignored(self):
        """Postgres and Redis have no cron and are not the registry's business."""
        transport = StubTransport(_correct_deployment())
        assert diff(desired_services(), deployed_services(transport), manual_service_names()) == []

    def test_drift_renders_readably(self):
        drift = Drift("refresh-odds", "cronSchedule", "15 * * * *", "0 */4 * * *")
        rendered = str(drift)
        assert "refresh-odds" in rendered and "15 * * * *" in rendered


class TestApply:
    def test_applying_a_correct_project_issues_no_mutations(self):
        """Idempotent: the reconciler diffs first and touches only what
        disagrees, so a routine run against a correct project is a no-op."""
        transport = StubTransport(_correct_deployment())
        assert apply(transport) == []
        assert transport.mutations == []

    def test_applying_fixes_only_the_service_that_drifted(self):
        services = _correct_deployment()
        services["refresh-odds"] = (services["refresh-odds"][0], "0 */4 * * *")
        transport = StubTransport(services)

        apply(transport)

        assert len(transport.mutations) == 1
        document = transport.mutations[0]
        assert "id-refresh-odds" in document
        assert ENVIRONMENT in document
        assert REGISTRY.get("refresh_odds").schedule in document

    def test_a_dry_run_changes_nothing(self):
        services = _correct_deployment()
        services["refresh-odds"] = (services["refresh-odds"][0], "0 */4 * * *")
        transport = StubTransport(services)

        drifts = apply(transport, dry_run=True)

        assert drifts and transport.mutations == []

    def test_apply_never_creates_a_missing_service(self):
        """Provisioning a billable service is a decision somebody should make,
        not a side effect of changing a cadence."""
        services = _correct_deployment()
        del services["pipeline"]
        transport = StubTransport(services)

        drifts = apply(transport)

        assert any(d.field == "service" for d in drifts)
        assert transport.mutations == []

    def test_apply_never_clears_a_cron_from_a_manual_job(self):
        """Reported by --check, left alone here: the schedule was put there by
        somebody, and removing it in a routine apply would be this tool doing
        something nobody asked for."""
        services = _correct_deployment()
        services["invalidate-cache"] = (
            "python -m nflfp.jobs run invalidate_cache",
            "0 * * * *",
        )
        transport = StubTransport(services)

        drifts = apply(transport)

        assert any(d.service == "invalidate-cache" for d in drifts)
        assert transport.mutations == []

    def test_the_mutation_escapes_its_values(self):
        """A start command carries quotes of its own and a cron expression is
        mostly asterisks. Both are JSON-encoded rather than interpolated, or
        `30 */6 * * *` arrives at the API as something else."""
        services = _correct_deployment()
        services["refresh-weather"] = (None, None)
        transport = StubTransport(services)

        apply(transport)

        document = transport.mutations[0]
        # The document must parse as GraphQL-ish with a quoted cron intact.
        assert json.dumps(REGISTRY.get("refresh_weather").schedule) in document
        assert "restartPolicyType: NEVER" in document


class TestTransportFailures:
    def test_a_project_with_no_environments_is_an_error_not_an_empty_diff(self):
        """An empty answer must never read as 'nothing is deployed and that is
        fine' — that is how a broken credential becomes a silent all-clear."""

        class Empty:
            def status(self):
                return {"environments": {"edges": []}}

            def graphql(self, document):  # pragma: no cover - never reached
                raise AssertionError

        with pytest.raises(RailwayUnavailable):
            deployed_services(Empty())

    def test_environment_id_is_required(self):
        class NoId:
            def status(self):
                return {"environments": {"edges": [{"node": {"serviceInstances": {"edges": []}}}]}}

            def graphql(self, document):  # pragma: no cover - never reached
                raise AssertionError

        with pytest.raises(RailwayUnavailable):
            environment_id(NoId())

    def test_a_missing_cli_names_what_to_do(self):
        transport = CliTransport(binary="railway-does-not-exist")
        with pytest.raises(RailwayUnavailable, match="railway login"):
            transport.status()


class TestTheCli:
    def test_check_exits_non_zero_on_drift(self, capsys):
        from nflfp.jobs.__main__ import main

        services = _correct_deployment()
        services["refresh-odds"] = (services["refresh-odds"][0], "0 */4 * * *")

        import argparse

        from nflfp.jobs.__main__ import cmd_schedule

        args = argparse.Namespace(
            check=True, apply=False, dry_run=False, transport=StubTransport(services)
        )
        assert cmd_schedule(args) == 1
        assert "refresh-odds" in capsys.readouterr().out

    def test_check_exits_zero_when_they_agree(self, capsys):
        import argparse

        from nflfp.jobs.__main__ import cmd_schedule

        args = argparse.Namespace(
            check=True, apply=False, dry_run=False, transport=StubTransport(_correct_deployment())
        )
        assert cmd_schedule(args) == 0
        assert "agree" in capsys.readouterr().out

    def test_bare_schedule_still_prints_the_cadences(self, capsys):
        import argparse

        from nflfp.jobs.__main__ import cmd_schedule

        args = argparse.Namespace(check=False, apply=False, dry_run=False, transport=None)
        assert cmd_schedule(args) == 0
        out = capsys.readouterr().out
        assert "refresh-odds" in out
        assert MANUAL in out or "invalidate_cache" in out
