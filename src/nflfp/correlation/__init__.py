"""Phase 6B — the dependency structure over Layer 3b's projections.

This package answers one question and nothing else: **do player outcomes in the
same game move together enough to change a matchup simulation, and can that be
measured rather than assumed?**

It is deliberately a layer *above* the frozen prediction foundation. Nothing in
here fits a projection, changes a marginal distribution, or touches
:mod:`nflfp.predict`. A correlation model is a joint structure bolted onto
marginals that were already measured and published; if it ever starts moving a
player's expected points it has stopped being a correlation model and become a
second, unvalidated projection model. :mod:`nflfp.correlation.sampler` enforces
that boundary, and ``tests/test_correlation_marginals.py`` measures it.

The modules, in the order the work was done::

    panel      leakage-free historical panel: for every player-week, the
               projection a deployment would actually have had, its stored
               distribution, and what happened
    estimate   the empirical part — PIT-transform the panel's outcomes and fit
               a latent-factor correlation structure to them
    model      the fitted structure, versioned and serialisable
    sampler    IndependentSampler / CorrelatedSampler behind one interface
    evaluate   matchup-level backtest and the metrics that decide the question
"""

from .model import (
    CORRELATION_MODEL_VERSION,
    NULL_MODEL,
    CorrelationMode,
    CorrelationModel,
    PositionLoading,
)
from .sampler import (
    CorrelatedSampler,
    IndependentSampler,
    RosterMember,
    Sampler,
    build_sampler,
)

__all__ = [
    "CORRELATION_MODEL_VERSION",
    "NULL_MODEL",
    "CorrelatedSampler",
    "CorrelationMode",
    "CorrelationModel",
    "IndependentSampler",
    "PositionLoading",
    "RosterMember",
    "Sampler",
    "build_sampler",
]
