"""Persistence layer.

Public surface for everything above it: engines, sessions, the declarative
base, and the ORM models. Nothing outside this package should import
SQLAlchemy's ``create_engine`` or construct a session directly — routing it all
through here is what makes pooling, TLS and statement timeouts uniform across
the API, the workers and the ETL.
"""

from __future__ import annotations

from .base import Base, TimestampMixin, metadata
from .engine import (
    async_session_scope,
    check_database,
    dispose_async_engine,
    dispose_engines,
    get_async_engine,
    get_async_session_factory,
    get_db_session,
    get_engine,
    get_session_factory,
    session_scope,
)
from .enums import Algorithm, ModelRunStatus, ScoringProfile, SeasonType
from .models import (
    JobRun,
    ModelRun,
    OddsSnapshot,
    PipelineRun,
    PipelineRunDataset,
    Projection,
    ProjectionPoints,
    WeatherForecast,
)

__all__ = [
    # base
    "Base",
    "TimestampMixin",
    "metadata",
    # engine / sessions
    "async_session_scope",
    "check_database",
    "dispose_async_engine",
    "dispose_engines",
    "get_async_engine",
    "get_async_session_factory",
    "get_db_session",
    "get_engine",
    "get_session_factory",
    "session_scope",
    # enums
    "Algorithm",
    "ModelRunStatus",
    "ScoringProfile",
    "SeasonType",
    # models
    "JobRun",
    "ModelRun",
    "OddsSnapshot",
    "PipelineRun",
    "PipelineRunDataset",
    "Projection",
    "ProjectionPoints",
    "WeatherForecast",
]
