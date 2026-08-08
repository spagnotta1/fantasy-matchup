"""ORM models for application-owned tables.

Importing this package registers every model against
:data:`nflfp.db.base.metadata`. Alembic's ``env.py`` imports it for exactly that
reason: a model that is never imported is invisible to autogenerate, and the
resulting "missing table" bug surfaces only in production.
"""

from __future__ import annotations

from .external import OddsSnapshot, WeatherForecast
from .jobs import JobRun
from .pipeline import PipelineRun, PipelineRunDataset
from .projection import ModelRun, Projection, ProjectionPoints

__all__ = [
    "JobRun",
    "ModelRun",
    "OddsSnapshot",
    "PipelineRun",
    "PipelineRunDataset",
    "Projection",
    "ProjectionPoints",
    "WeatherForecast",
]
