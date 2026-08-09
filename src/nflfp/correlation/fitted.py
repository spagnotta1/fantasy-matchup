"""The fitted structure the API serves, written out rather than loaded.

Eight numbers live here as source code, not in a data file the deployment has to
carry. Three reasons, in order of how much they matter:

**A correlation parameter is a modelling claim and belongs under review.**
Changing ``WR.team`` from 0.162 to 0.30 changes every simulated interval in the
product. As code that is a diff someone approves; as a JSON blob in a bucket it
is a config change nobody reads. The values below were fitted by
``scripts/phase6b_backtest.py`` and every one of them is reproducible from
``artifacts/panel_half_ppr.jsonl``.

**The API must never be able to half-load a correlation model.** A file-backed
model introduces a state where the endpoint is up, the artifact is missing, and
the honest answers are either a 503 or a silent fall back to independence. The
second is unacceptable — it would report a correlated simulation that was not
one — and the first is an outage caused by an experimental feature. Neither
happens if the model is an import.

**It is small and it is stable.** Refitting on a new season moves these in the
third decimal; the *shape* is what
:data:`~nflfp.correlation.model.CORRELATION_MODEL_VERSION` tracks, and a refit
that does not change the shape does not change what a stored
``correlation_model_version`` means.

The full estimation record — every measured cell, every residual, the sample
counts — is in ``artifacts/correlation_model_half_ppr.json`` and summarised in
``docs/simulation-readiness.md``. What is carried here is what the sampler
consumes plus enough provenance to identify the fit that produced it.
"""

from __future__ import annotations

import math

from .model import (
    CORRELATION_MODEL_VERSION,
    CorrelationMode,
    CorrelationModel,
    EstimationReport,
    PositionLoading,
)

#: Loading on the shared game factor, by position. Fitted 2019-2025.
_GAME_LOADING: dict[str, float] = {
    "QB": 0.398649,
    "RB": 0.028355,
    "WR": 0.175626,
    "TE": 0.131706,
}

#: Additional loading on the team's offence factor. The quarterback's is
#: **derived**, not fitted: it is the anchor that pins the factor's scale, and
#: writing the rounded value here instead would put it outside the unit disc.
#: See :func:`nflfp.correlation.estimate._anchor`.
_TEAM_LOADING: dict[str, float] = {
    "RB": 0.043911,
    "WR": 0.161649,
    "TE": 0.165880,
}

#: Half-PPR, ``shrinkage_eb``. A structure fitted on one scoring profile does not
#: transfer to another: PPR pays receptions, which changes the shape of every
#: pass-catcher's distribution and therefore the copula correlation measured
#: through it. Serving this one for a PPR request would be an unmeasured claim,
#: so :func:`for_profile` refuses instead.
PROFILE = "half_ppr"
MODEL_NAME = "shrinkage_eb"


def _build() -> CorrelationModel:
    loadings = {
        position: PositionLoading(
            position=position,
            game=game,
            team=(
                _TEAM_LOADING[position]
                if position in _TEAM_LOADING
                else math.sqrt(max(0.0, 1.0 - game ** 2))
            ),
        )
        for position, game in _GAME_LOADING.items()
    }
    return CorrelationModel(
        version=CORRELATION_MODEL_VERSION,
        mode=CorrelationMode.GAME_ENVIRONMENT,
        loadings=loadings,
        profile=PROFILE,
        model_name=MODEL_NAME,
        estimation=EstimationReport(
            projection_floor=6.0,
            rows=18_209,
            pairs=87_491,
            through_season=2025,
            through_week=18,
            weighted_rmse=0.02415,
        ),
    )


#: The fitted structure. Built once at import; the model is frozen and its
#: loadings are read on every iteration of every simulation.
GAME_ENVIRONMENT_V1 = _build()


class ProfileNotFitted(LookupError):
    """No correlation structure has been fitted for a scoring profile."""


def for_profile(profile: str) -> CorrelationModel:
    """The fitted structure for a scoring profile.

    Raises:
        ProfileNotFitted: for any profile but the one that was fitted. Returning
            the half-PPR structure for a PPR request would apply correlations
            measured through one set of marginals to a different set, which is
            an unmeasured claim wearing a measured one's version number.
    """
    if profile != PROFILE:
        raise ProfileNotFitted(
            f"no correlation structure has been fitted for scoring profile "
            f"{profile!r}; one exists for {PROFILE!r} only. Correlations are "
            "measured through each player's own outcome distribution, and those "
            "distributions differ by profile, so the fitted structure does not "
            "transfer. Use correlation_mode=independent, or fit a structure for "
            "this profile with scripts/phase6b_backtest.py."
        )
    return GAME_ENVIRONMENT_V1
