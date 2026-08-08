"""Application configuration.

One `Settings` object is the single source of truth for every tunable in the
application. Nothing else reads `os.environ` directly, with one deliberate
exception: the Postgres DSN is still resolved by :func:`nflfp.pg.dsn`, because
that function already encodes hard-won knowledge (Railway's private-vs-public
URL preference, the `postgres://` -> `postgresql://` rewrite, and the
localhost-vs-managed sslmode default). Duplicating that logic here would be two
places to get it wrong.

Settings are read from the process environment and from a `.env` file if one is
present. Railway injects real environment variables, so `.env` is a local-dev
convenience only.
"""

from __future__ import annotations

import functools
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from . import pg

Environment = Literal["local", "test", "staging", "production"]


class Settings(BaseSettings):
    """Runtime configuration, validated at import time of the first accessor.

    Every field can be overridden by an environment variable of the same name
    (case-insensitive). Fields without a default are required and will fail
    loudly at startup rather than at first use.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- environment ------------------------------------------------------
    environment: Environment = "local"
    debug: bool = False
    log_level: str = "INFO"
    log_json: bool = Field(
        default=False,
        description="Emit structured JSON logs. Enable in deployed environments.",
    )

    # ---- database ---------------------------------------------------------
    database_url_override: str | None = Field(
        default=None,
        description=(
            "Explicit Postgres DSN, mostly for tests and one-off runs against a "
            "copy of production. Normally left unset so nflfp.pg.dsn() resolves "
            "it from DATABASE_URL / NFLFP_PG_URL.\n\n"
            "Deliberately *not* named `database_url`: pydantic-settings would "
            "bind that field to the DATABASE_URL environment variable and hand "
            "back the raw value, bypassing the scheme and sslmode normalisation "
            "in nflfp.pg — which is what makes managed Postgres get TLS. An "
            "override still goes through pg.normalize_dsn() below."
        ),
    )
    db_pool_size: int = Field(default=5, ge=1, le=100)
    db_max_overflow: int = Field(default=10, ge=0, le=100)
    db_pool_timeout: int = Field(default=30, ge=1)
    db_pool_recycle: int = Field(
        default=1800,
        description=(
            "Recycle connections after N seconds. Managed Postgres and the "
            "proxies in front of it drop idle connections; recycling below that "
            "threshold turns a stale-connection error into a no-op."
        ),
    )
    db_echo: bool = False
    db_statement_timeout_ms: int = Field(
        default=15_000,
        ge=0,
        description="Server-side statement timeout for API sessions. 0 disables.",
    )
    db_connect_timeout_seconds: int = Field(
        default=10,
        ge=1,
        le=120,
        description=(
            "How long to wait for a TCP connection to Postgres before giving "
            "up. libpq's default is to wait effectively forever, which turns an "
            "unreachable database into a hung health check rather than a fast "
            "'degraded' — measured at over two minutes before this was set. A "
            "health endpoint that hangs is worse than one that reports failure."
        ),
    )

    # ---- redis / caching (Layer 6) ----------------------------------------
    redis_url: str | None = Field(
        default=None,
        description=(
            "Redis connection URL. Railway injects this when you add a Redis "
            "service and reference it. Unset means no cache, which is a "
            "supported configuration rather than a degraded one."
        ),
    )
    cache_enabled: bool = Field(
        default=True,
        description=(
            "Master switch. Turning it off is the first diagnostic step when a "
            "response looks stale — it must be one variable, not a redeploy."
        ),
    )
    cache_backend: Literal["redis", "memory", "null"] = Field(
        default="redis",
        description=(
            "Resolved through nflfp.cache.build_backend. `redis` with no "
            "REDIS_URL degrades to no cache and says so in the logs; `memory` "
            "is correct only for a single instance, because a namespace bump "
            "from another instance would never reach it."
        ),
    )
    cache_timeout_seconds: float = Field(
        default=0.25,
        gt=0,
        le=5,
        description=(
            "Socket timeout for cache operations. A cache lookup must never be "
            "slower than the query it replaces; without a timeout a stalled "
            "Redis turns every cached endpoint into a hang."
        ),
    )
    cache_epoch_ttl_seconds: float = Field(
        default=10.0,
        ge=0,
        le=300,
        description=(
            "How long an instance may reuse a locally held publish epoch. This "
            "is the upper bound on how long a publish takes to become visible, "
            "traded against re-reading the epoch on every request."
        ),
    )

    # ---- jobs -------------------------------------------------------------
    projection_model: str = Field(
        default="shrinkage_eb",
        description=(
            "Model the scheduled projection job runs. The frozen foundation by "
            "default; a challenger is promoted by changing this after it has "
            "cleared nflfp.predict.foundation.ACCEPTANCE, not before."
        ),
    )
    job_publish_projections: bool = Field(
        default=True,
        description=(
            "Whether the scheduled projection job publishes its run. False "
            "generates and stores without making it live, which is what a "
            "staging environment wants."
        ),
    )

    # ---- external providers ----------------------------------------------
    # Names resolved through nflfp.providers.registry. Setting either to "null"
    # disables that feed without removing the scheduled job, so the job still
    # runs, still logs, and still reports zero records — which is what you want
    # when a provider is having an outage and you need the rest of the pipeline
    # to carry on.
    weather_provider: str = "open_meteo"
    odds_provider: str = "espn"
    provider_timeout_seconds: float = Field(default=20.0, gt=0)
    provider_retry_attempts: int = Field(default=4, ge=1, le=10)
    #: How far ahead to fetch forecasts and markets. One NFL week plus slack.
    provider_horizon_days: int = Field(default=10, ge=1, le=16)

    # ---- domain defaults --------------------------------------------------
    default_scoring_profile: str = "half_ppr"

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        level = value.upper()
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}
        if level not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}, got {value!r}")
        return level

    @field_validator("default_scoring_profile")
    @classmethod
    def _known_scoring_profile(cls, value: str) -> str:
        from .scoring import PROFILES

        if value not in PROFILES:
            raise ValueError(
                f"default_scoring_profile must be one of {sorted(PROFILES)}, got {value!r}"
            )
        return value

    # ---- derived ----------------------------------------------------------
    @property
    def is_deployed(self) -> bool:
        """True outside a developer's machine, where TLS and JSON logs matter."""
        return self.environment in ("staging", "production")

    def resolved_dsn(self) -> str:
        """The normalised libpq DSN, honouring an explicit override.

        Both paths run through :mod:`nflfp.pg`, so an override cannot end up
        with a ``postgres://`` scheme SQLAlchemy rejects or without the
        ``sslmode=require`` a managed host needs.

        Raises:
            nflfp.pg.ConfigError: if neither the override nor any of the
                environment variables understood by :func:`nflfp.pg.dsn` is set.
        """
        if self.database_url_override:
            return pg.normalize_dsn(self.database_url_override)
        return pg.dsn()

    @property
    def sqlalchemy_url(self) -> str:
        """Synchronous SQLAlchemy URL (psycopg 3 driver).

        Used by Alembic, background workers and the ETL — anywhere a blocking
        connection is the simplest correct thing.
        """
        return _with_driver(self.resolved_dsn(), "postgresql+psycopg")

    @property
    def sqlalchemy_async_url(self) -> str:
        """Asynchronous SQLAlchemy URL.

        psycopg 3 ships a native async implementation, so sync and async share
        one driver and one connection-string dialect. That is why the API and
        the workers cannot drift apart on connection semantics.
        """
        return _with_driver(self.resolved_dsn(), "postgresql+psycopg")

    def safe_dsn(self) -> str:
        """The DSN with the password redacted, for logging."""
        return pg.safe_dsn(self.resolved_dsn())


def _with_driver(dsn: str, driver: str) -> str:
    """Rewrite a libpq URL's scheme to a SQLAlchemy dialect+driver."""
    _, _, remainder = dsn.partition("://")
    if not remainder:
        raise ValueError(f"DSN is not a URL: {pg.safe_dsn(dsn)}")
    return f"{driver}://{remainder}"


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton.

    Cached so that validation runs once and so FastAPI can use this directly as
    a dependency. Tests that need to vary the environment should call
    ``get_settings.cache_clear()``.
    """
    return Settings()
