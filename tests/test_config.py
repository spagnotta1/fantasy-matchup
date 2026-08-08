"""Unit tests for :mod:`nflfp.config`."""

from __future__ import annotations

import pytest

from nflfp import pg
from nflfp.config import Settings, get_settings


def test_defaults_are_local_and_safe(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    settings = Settings()
    assert settings.environment == "local"
    assert settings.is_deployed is False
    assert settings.db_pool_size >= 1


def test_sqlalchemy_url_uses_psycopg_driver(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    settings = Settings()
    assert settings.sqlalchemy_url.startswith("postgresql+psycopg://")
    # Sync and async deliberately share a driver, so pooling and TLS behaviour
    # cannot diverge between the API and the workers.
    assert settings.sqlalchemy_async_url == settings.sqlalchemy_url


def test_railway_postgres_scheme_is_normalised(monkeypatch):
    """Railway hands out `postgres://`, which libpq and SQLAlchemy both reject."""
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@db.railway.internal:5432/railway")
    settings = Settings()
    assert settings.sqlalchemy_url.startswith("postgresql+psycopg://")
    # Managed hosts must get TLS; pg.dsn() is what decides that, and config
    # must not have lost it in translation.
    assert "sslmode=require" in settings.sqlalchemy_url


def test_localhost_does_not_demand_tls(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:55432/nflfp")
    assert "sslmode=disable" in Settings().sqlalchemy_url


def test_safe_dsn_redacts_password(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:supersecret@localhost:5432/db")
    safe = Settings().safe_dsn()
    assert "supersecret" not in safe
    assert "***" in safe


def test_explicit_database_url_overrides_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/from_env")
    settings = Settings(database_url_override="postgresql://u:p@localhost:5432/explicit")
    assert "explicit" in settings.resolved_dsn()


def test_missing_dsn_raises_config_error(monkeypatch):
    for key in ("DATABASE_URL", "NFLFP_PG_URL", "DATABASE_PUBLIC_URL"):
        monkeypatch.delenv(key, raising=False)
    # A .env file in the repo would satisfy this; construct without one.
    settings = Settings(_env_file=None)
    with pytest.raises(pg.ConfigError):
        settings.resolved_dsn()


def test_invalid_log_level_rejected():
    with pytest.raises(ValueError, match="log_level"):
        Settings(log_level="chatty")


def test_unknown_scoring_profile_rejected():
    with pytest.raises(ValueError, match="default_scoring_profile"):
        Settings(default_scoring_profile="superflex_ppr")


def test_default_scoring_profile_exists_in_scoring_module():
    from nflfp.scoring import PROFILES

    assert Settings.model_fields["default_scoring_profile"].default in PROFILES


def test_get_settings_is_cached(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/db")
    assert get_settings() is get_settings()
