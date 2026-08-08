"""Layer 5 — the REST API.

A thin serialisation of :mod:`nflfp.services`. There is no football in this
package: a route unpacks query parameters, calls exactly one service function,
maps the result onto a schema, and attaches metadata. Anything more than that
is a missing function in the business layer.

The one thing this layer *adds* is provenance. See
:mod:`nflfp.api.provenance` — the API's job is not only to return numbers but
to make clear which of them the model produced, which were derived above it,
and which are context it does not use at all.

Running it::

    uvicorn nflfp.api.main:app --reload
"""

from __future__ import annotations

from .main import API_PREFIX, create_app
from .provenance import PROVENANCE_LEGEND, Provenance

__all__ = ["API_PREFIX", "PROVENANCE_LEGEND", "Provenance", "create_app"]
