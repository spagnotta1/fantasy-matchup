"""Routers. One module per resource group, all mounted under the API prefix."""

from __future__ import annotations

from . import advice, insights, matchups, meta, players, projections

__all__ = ["advice", "insights", "matchups", "meta", "players", "projections"]
