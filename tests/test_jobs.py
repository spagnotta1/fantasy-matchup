"""Tests for the background job system.

The behaviours worth pinning are operational rather than functional: that a
failure is *recorded* rather than lost, that a non-critical failure does not
take the batch down with it, and that schedules stay declarative.
"""

from __future__ import annotations

import pytest

from nflfp.jobs.registry import MANUAL, Job, JobContext, JobOutcome, JobRegistry
from nflfp.jobs import REGISTRY

from .conftest import requires_db


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

class TestJobRegistry:
    def test_expected_jobs_are_registered(self):
        assert set(REGISTRY.names()) == {
            "refresh_odds",
            "refresh_weather",
            "refresh_injuries",
            "build_features",
            "refresh_features",
            "generate_projections",
            "warm_cache",
            "evaluate_model",
            "invalidate_cache",
            "backfill_projections",
        }

    def test_injuries_refresh_daily_not_weekly(self):
        """A practice report lands Wednesday, Thursday and Friday and a
        designation flips on Saturday. On the weekly load those are four days
        stale, and the API states a caveat that has since been lifted."""
        _, _, day_of_month, month, day_of_week = REGISTRY.get(
            "refresh_injuries"
        ).schedule.split()
        assert (day_of_month, month, day_of_week) == ("*", "*", "*")

    def test_the_model_evaluation_runs_after_a_projection_run(self):
        """A check that runs first reports on last week's model."""
        projections_dow = int(REGISTRY.get("generate_projections").schedule.split()[4])
        evaluation_dow = int(REGISTRY.get("evaluate_model").schedule.split()[4])
        assert evaluation_dow > projections_dow

    def test_the_model_evaluation_is_not_critical(self):
        """A drifting model is an operator decision. Failing the batch — or
        rolling back automatically — would hide the drift behind a model that
        has the same problem a week earlier."""
        assert REGISTRY.get("evaluate_model").critical is False

    @pytest.mark.parametrize("job", REGISTRY.all(), ids=lambda j: j.name)
    def test_every_job_declares_a_schedule_and_description(self, job):
        """Cadence lives in the registry, never inside a provider — changing
        how often something runs must not be a change to the code that talks
        to the network."""
        assert job.schedule.strip()
        if job.is_scheduled:
            assert len(job.schedule.split()) == 5, f"{job.name}: not a 5-field cron"
        assert job.description.strip()

    def test_the_projection_job_runs_after_the_feature_build(self):
        """Projecting from feature views that still describe last week
        produces a board that is confidently about the wrong games."""
        # cron fields: minute hour day-of-month month day-of-week
        _, features_hour, _, _, features_dow = REGISTRY.get("build_features").schedule.split()
        _, projection_hour, _, _, projection_dow = (
            REGISTRY.get("generate_projections").schedule.split()
        )
        assert features_dow == projection_dow
        assert int(projection_hour) > int(features_hour)

    def test_the_projection_job_is_critical(self):
        """Everything a user sees is downstream of it. A silent failure means
        an empty board on Thursday, which the API renders correctly and
        unhelpfully as 'projections coming soon'."""
        assert REGISTRY.get("generate_projections").critical is True

    def test_invalidate_cache_is_registered_but_never_scheduled(self):
        """It wants the same run log and CLI as everything else, but a cron
        that periodically threw the cache away would be a slow leak of the
        benefit it exists to provide."""
        job = REGISTRY.get("invalidate_cache")
        assert job.schedule == MANUAL
        assert job.is_scheduled is False
        assert job not in REGISTRY.scheduled()

    def test_backfill_is_registered_but_never_scheduled(self):
        """A catch-up run, not a cadence. Once the history is published the
        weekly job keeps it current, and a cron would spend an hour a week
        rewriting boards for seasons that ended years ago."""
        job = REGISTRY.get("backfill_projections")
        assert job.schedule == MANUAL
        assert job.is_scheduled is False
        assert job not in REGISTRY.scheduled()

    def test_scheduled_returns_only_timed_jobs(self):
        """Counted against the manual jobs rather than a literal, so adding
        one is a one-line registry change rather than a test edit that invites
        bumping the number until it passes."""
        assert all(job.is_scheduled for job in REGISTRY.scheduled())
        manual = [job for job in REGISTRY.all() if job.schedule == MANUAL]
        assert len(REGISTRY.scheduled()) == len(REGISTRY.all()) - len(manual)

    def test_unknown_job_lists_the_valid_names(self):
        with pytest.raises(KeyError, match="registered:"):
            REGISTRY.get("refresh_nonsense")

    def test_duplicate_registration_is_rejected(self):
        registry = JobRegistry()
        job = Job("x", lambda c: JobOutcome(), "* * * * *", "d")
        registry.register(job)
        with pytest.raises(ValueError, match="duplicate"):
            registry.register(Job("x", lambda c: JobOutcome(), "* * * * *", "d"))

    def test_emitted_railway_config_matches_the_registry(self, tmp_path):
        """The registry is the single source of truth for cadence. If the
        generated config could disagree with it, the deployed cron and the
        documented one are two different numbers."""
        from nflfp.jobs.__main__ import main

        assert main(["schedule", "--emit", str(tmp_path)]) == 0

        import json

        emitted = {path.name: json.loads(path.read_text()) for path in tmp_path.glob("*.json")}
        assert len(emitted) == len(REGISTRY.scheduled())

        for job in REGISTRY.scheduled():
            config = emitted[f"railway.{job.name.replace('_', '-')}.json"]
            assert config["deploy"]["cronSchedule"] == job.schedule
            assert config["deploy"]["startCommand"] == f"python -m nflfp.jobs run {job.name}"
            # A cron job that exits 0 is finished, not crashed.
            assert config["deploy"]["restartPolicyType"] == "NEVER"

    def test_a_manual_job_gets_no_cron_service(self, tmp_path):
        from nflfp.jobs.__main__ import main

        main(["schedule", "--emit", str(tmp_path)])
        assert not list(tmp_path.glob("*invalidate*"))

    def test_no_provider_module_hard_codes_a_schedule(self):
        """The whole point of declaring cadence in the registry."""
        import pathlib

        provider_dir = pathlib.Path(__file__).resolve().parents[1] / "src" / "nflfp" / "providers"
        for path in provider_dir.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert "cron" not in source.lower(), f"{path.name} mentions cron"


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

@requires_db
@pytest.mark.integration
class TestRunner:
    """Runs against the real database — the run log is the thing under test."""

    def _registry(self, job: Job) -> JobRegistry:
        registry = JobRegistry()
        registry.register(job)
        return registry

    def test_successful_run_is_recorded(self):
        from nflfp.jobs.runner import run_job

        registry = self._registry(
            Job("t_ok", lambda c: JobOutcome(records=7, detail={"a": 1}), "* * * * *", "d")
        )
        run = run_job("t_ok", registry=registry)
        assert run.status == "ok"
        assert run.records_written == 7
        assert run.detail == {"a": 1}
        assert run.finished_at is not None
        assert run.trigger == "manual"

    def test_failure_is_recorded_rather_than_lost(self):
        """The run log is written on its own transaction precisely so that a
        failing job cannot roll back the record of its own failure."""
        from nflfp.jobs.runner import run_job

        def explode(_context: JobContext) -> JobOutcome:
            raise RuntimeError("provider exploded")

        registry = self._registry(Job("t_fail", explode, "* * * * *", "d"))
        run = run_job("t_fail", registry=registry)
        assert run.status == "failed"
        assert "provider exploded" in run.error
        assert run.finished_at is not None

    def test_critical_failure_propagates(self):
        from nflfp.jobs.runner import run_job

        def explode(_context: JobContext) -> JobOutcome:
            raise RuntimeError("boom")

        registry = self._registry(
            Job("t_critical", explode, "* * * * *", "d", critical=True)
        )
        with pytest.raises(RuntimeError, match="boom"):
            run_job("t_critical", registry=registry)

    def test_skipped_run_records_its_reason(self):
        from nflfp.jobs.runner import run_job

        registry = self._registry(
            Job(
                "t_skip",
                lambda c: JobOutcome(skipped=True, skip_reason="no games in range"),
                "* * * * *",
                "d",
            )
        )
        run = run_job("t_skip", registry=registry)
        assert run.status == "skipped"
        assert run.detail["skip_reason"] == "no games in range"

    def test_non_critical_failure_does_not_stop_the_batch(self):
        """An odds provider outage must not stop the feature build from running
        on data already in the warehouse."""
        from nflfp.jobs.runner import run_all

        def explode(_context: JobContext) -> JobOutcome:
            raise RuntimeError("provider down")

        registry = JobRegistry()
        registry.register(Job("t_bad", explode, "* * * * *", "d", critical=False))
        registry.register(Job("t_good", lambda c: JobOutcome(records=3), "* * * * *", "d"))

        runs = run_all(registry=registry)
        assert [r.status for r in runs] == ["failed", "ok"]
        assert runs[1].records_written == 3

    def test_options_reach_the_job(self):
        from nflfp.jobs.runner import run_job

        seen = {}

        def capture(context: JobContext) -> JobOutcome:
            seen.update(context.options)
            return JobOutcome()

        registry = self._registry(Job("t_opts", capture, "* * * * *", "d"))
        run_job("t_opts", options={"horizon_days": 3}, registry=registry)
        assert seen == {"horizon_days": 3}

    def test_last_successful_run_supports_failure_recovery(self):
        from nflfp.jobs.runner import last_successful_run, run_job

        registry = self._registry(
            Job("t_recover", lambda c: JobOutcome(records=1), "* * * * *", "d")
        )
        run_job("t_recover", registry=registry)
        found = last_successful_run("t_recover")
        assert found is not None and found.status == "ok"
