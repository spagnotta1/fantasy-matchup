"""Reconciling the registry's cadence with what Railway is actually running.

Why this module replaced a config generator
--------------------------------------------
Cadence is declared once, in :mod:`nflfp.jobs.registry`. Getting it from there
to Railway used to go through ``schedule --emit``, which wrote one
``deploy/railway.<job>.json`` per job for Railway's config-as-code to pick up.
That chain is broken at its last link: pointing a service at a config file
outside the repository root requires setting ``railwayConfigFile``, and the
Railway API now refuses it —

    Config as Code (railway.json / railway.toml) is deprecated. Use
    Infrastructure as Code (.railway/railway.ts) instead.

The root ``railway.json`` still works, because Railway auto-detects that one
path; it is what the ``api`` service runs on today. But nine files under
``deploy/`` describe services nothing will ever read. A generated file that
looks authoritative and is consumed by nobody is worse than no file, because
the test asserting it matches the registry keeps passing while the deployed
schedule drifts — which is precisely the failure the generator existed to
prevent.

So the last link now checks reality instead of a file. The registry is still
the single source of truth; ``schedule --check`` asks Railway what it is
actually running and reports any disagreement, and ``schedule --apply`` pushes
the registry's answer. A file cannot go stale if nothing generates one.

Why the CLI is the transport
-----------------------------
Talking to ``backboard.railway.com`` directly would need a token managed
separately from the one the developer already has. The ``railway`` CLI is
authenticated on any machine where somebody has run ``railway login``, and it
exposes the same GraphQL endpoint through ``railway api``. Shelling out to it
keeps this module free of a second credential path.

The transport is a protocol rather than a hardcoded ``subprocess`` call so the
reconciler is testable without a network, a token, or an installed CLI — every
test in ``tests/test_jobs.py`` drives it through a stub.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Protocol

from .registry import REGISTRY, Job

logger = logging.getLogger(__name__)

#: The warehouse refresh is not a registered job — it is
#: ``python -m nflfp.pipeline refresh``, a pipeline entry point rather than
#: something in :data:`~nflfp.jobs.registry.REGISTRY`. It still needs a
#: schedule, and it still must not drift, so it is declared here explicitly
#: rather than being quietly absent from every check.
PIPELINE_SERVICE = "pipeline"
PIPELINE_COMMAND = "python -m nflfp.pipeline refresh"
#: Tuesday 12:00 UTC, an hour ahead of the feature build that reads what it
#: loads. The rest of the Tuesday chain is in the registry.
PIPELINE_SCHEDULE = "0 12 * * 2"


class RailwayUnavailable(RuntimeError):
    """The CLI is missing, unauthenticated, or the project is not linked."""


@dataclass(frozen=True)
class DesiredService:
    """What the registry says a service should be running."""

    name: str
    start_command: str
    cron_schedule: str


@dataclass(frozen=True)
class DeployedService:
    """What Railway says a service is running."""

    name: str
    service_id: str
    start_command: str | None
    cron_schedule: str | None


@dataclass(frozen=True)
class Drift:
    """One disagreement between the registry and Railway."""

    service: str
    field: str
    expected: str
    actual: str | None

    def __str__(self) -> str:
        return (
            f"{self.service}: {self.field} is {self.actual!r}, "
            f"registry says {self.expected!r}"
        )


class Transport(Protocol):
    """How this module reaches Railway."""

    def status(self) -> dict:
        """The linked project's state, as ``railway status --json`` returns it."""

    def graphql(self, document: str) -> dict:
        """Execute a GraphQL document and return the parsed response."""


class CliTransport:
    """Reaches Railway through the authenticated ``railway`` CLI.

    Both calls go through the binary rather than an HTTP client so that this
    inherits whatever credential the developer already has — an account login,
    a ``RAILWAY_TOKEN`` in CI, either works without this module knowing which.
    """

    def __init__(self, binary: str = "railway", timeout: int = 180) -> None:
        self._binary = binary
        self._timeout = timeout

    def _run(self, args: list[str], stdin_file: str | None = None) -> str:
        # The *resolved* path, not the bare name. On Windows the CLI installs
        # as an npm shim (`railway.cmd`); `shutil.which` finds it but
        # CreateProcess will not launch a bare `railway`, and the failure
        # arrives as a bare FileNotFoundError that reads like the CLI is
        # missing when it is installed and working.
        executable = shutil.which(self._binary)
        if executable is None:
            raise RailwayUnavailable(
                f"{self._binary!r} is not on PATH. Install the Railway CLI and "
                "run `railway login`, or set RAILWAY_TOKEN."
            )
        try:
            completed = subprocess.run(
                [executable, *args],
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:  # pragma: no cover - network
            raise RailwayUnavailable(f"railway {' '.join(args)} timed out") from exc
        if completed.returncode != 0:
            raise RailwayUnavailable(
                f"railway {' '.join(args)} failed: "
                f"{(completed.stderr or completed.stdout).strip()[:400]}"
            )
        return completed.stdout

    def status(self) -> dict:
        raw = self._run(["status", "--json"])
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RailwayUnavailable(
                "railway status --json did not return JSON; is a project linked?"
            ) from exc

    def graphql(self, document: str) -> dict:
        # Through a file rather than an argument: a cron expression is mostly
        # asterisks and spaces, and passing one through a shell argument is how
        # `30 */6 * * *` arrives at the API as something else.
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".graphql", delete=False, encoding="utf-8"
        )
        try:
            handle.write(document)
            handle.close()
            raw = self._run(["api", "-f", handle.name])
        finally:
            os.unlink(handle.name)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RailwayUnavailable(f"railway api returned non-JSON: {raw[:200]}") from exc
        if payload.get("errors"):
            raise RailwayUnavailable(f"Railway API error: {payload['errors']}")
        return payload


def desired_services(registry=REGISTRY) -> list[DesiredService]:
    """Every service the registry says should exist, in deployment order.

    A manual job is deliberately absent. ``invalidate_cache`` on a timer would
    be a slow leak of the benefit the cache exists to provide, and
    ``backfill_projections`` would spend an hour a week rewriting boards for
    seasons that ended years ago — so a schedule appearing on either is drift,
    not configuration, and :func:`diff` reports it as such.
    """
    services = [
        DesiredService(PIPELINE_SERVICE, PIPELINE_COMMAND, PIPELINE_SCHEDULE)
    ]
    services.extend(
        DesiredService(job.service_name, job.start_command, job.schedule)
        for job in registry.scheduled()
    )
    return services


def manual_service_names(registry=REGISTRY) -> set[str]:
    """Services that must never carry a cron schedule."""
    return {
        job.service_name for job in registry.all() if not job.is_scheduled
    }


def deployed_services(transport: Transport) -> dict[str, DeployedService]:
    """What Railway is running, keyed by service name."""
    status = transport.status()
    environments = status.get("environments", {}).get("edges", [])
    if not environments:
        raise RailwayUnavailable("no environments in railway status; is a project linked?")

    found: dict[str, DeployedService] = {}
    for edge in environments:
        node = edge.get("node", {})
        for instance in node.get("serviceInstances", {}).get("edges", []):
            service = instance.get("node", {})
            name = service.get("serviceName")
            if not name:
                continue
            found[name] = DeployedService(
                name=name,
                service_id=service.get("serviceId", ""),
                start_command=service.get("startCommand"),
                cron_schedule=service.get("cronSchedule"),
            )
    return found


def environment_id(transport: Transport) -> str:
    """The linked environment's id, which every mutation needs."""
    status = transport.status()
    environments = status.get("environments", {}).get("edges", [])
    for edge in environments:
        node = edge.get("node", {})
        if node.get("id"):
            return str(node["id"])
    raise RailwayUnavailable("could not resolve an environment id from railway status")


def diff(
    desired: list[DesiredService],
    deployed: dict[str, DeployedService],
    manual: set[str] | None = None,
) -> list[Drift]:
    """Every way Railway disagrees with the registry.

    Three kinds of disagreement, all of which have bitten this project:

    * a service that should exist and does not — the state the whole system was
      in until it was provisioned by hand;
    * a schedule or start command that has been edited away from the registry,
      which is what the deleted config generator was trying to prevent;
    * a cron on a job the registry says is manual, which would put
      ``invalidate_cache`` on a timer.
    """
    drifts: list[Drift] = []
    for want in desired:
        have = deployed.get(want.name)
        if have is None:
            drifts.append(Drift(want.name, "service", "exists", None))
            continue
        if have.cron_schedule != want.cron_schedule:
            drifts.append(
                Drift(want.name, "cronSchedule", want.cron_schedule, have.cron_schedule)
            )
        if have.start_command != want.start_command:
            drifts.append(
                Drift(want.name, "startCommand", want.start_command, have.start_command)
            )

    for name in sorted(manual or set()):
        have = deployed.get(name)
        if have is not None and have.cron_schedule:
            drifts.append(Drift(name, "cronSchedule", "(manual — none)", have.cron_schedule))

    return drifts


def _mutation(environment: str, service_id: str, service: DesiredService) -> str:
    """The update document, with every value JSON-escaped rather than formatted.

    ``json.dumps`` and not an f-string quote: a start command contains quotes
    of its own (``sh -c "..."``), and a cron expression is mostly characters a
    shell would rather interpret.
    """
    return (
        "mutation { serviceInstanceUpdate("
        f"environmentId: {json.dumps(environment)}, "
        f"serviceId: {json.dumps(service_id)}, "
        "input: { "
        f"startCommand: {json.dumps(service.start_command)}, "
        f"cronSchedule: {json.dumps(service.cron_schedule)}, "
        "restartPolicyType: NEVER"
        " }) }"
    )


def apply(transport: Transport, *, dry_run: bool = False) -> list[Drift]:
    """Push the registry's cadence to Railway. Returns what it changed.

    Idempotent by construction: it diffs first and mutates only the services
    that disagree, so a run against a correct project issues no mutations and
    reports nothing. A service that does not exist is **not** created — this
    reconciles configuration, not infrastructure, because creating a billable
    service is a decision somebody should make deliberately rather than a side
    effect of a cadence change.
    """
    desired = desired_services()
    deployed = deployed_services(transport)
    drifts = diff(desired, deployed, manual_service_names())

    missing = {d.service for d in drifts if d.field == "service"}
    changed = {d.service for d in drifts if d.field != "service"} - missing
    if not changed:
        return drifts

    environment = environment_id(transport)
    by_name = {service.name: service for service in desired}
    for name in sorted(changed):
        if name not in by_name:
            # A manual job carrying a cron. Clearing it is a separate decision:
            # the schedule was put there by somebody, and silently removing it
            # in a routine apply would be this module doing something nobody
            # asked for. Reported by --check, left alone here.
            continue
        if dry_run:
            logger.info("would update %s", name)
            continue
        transport.graphql(_mutation(environment, deployed[name].service_id, by_name[name]))
        logger.info("updated %s", name)
    return drifts
