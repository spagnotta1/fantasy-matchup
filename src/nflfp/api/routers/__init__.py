"""Routers. One module per resource group, all mounted under the API prefix."""

from __future__ import annotations

from . import advice, matchups, meta, players, projections

__all__ = ["advice", "matchups", "meta", "players", "projections"]
