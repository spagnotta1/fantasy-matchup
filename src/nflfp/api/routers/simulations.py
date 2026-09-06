"""Matchup simulation — the only endpoint that takes a body.

``POST`` rather than ``GET`` for one reason that is not REST pedantry: two
lineups are fourteen player ids and fourteen slots, which does not fit sensibly
in a query string and would produce a cache key nobody could read. The method
also keeps the response out of the shared cache by construction — the middleware
caches ``GET`` only — which is correct here, because a simulation is cheap to
recompute and its inputs are effectively unique per request.

**Nothing is persisted.** The result is computed and returned inline. No roster
is stored, no simulation is recorded, and no principal is required: the endpoint
is anonymous like every other one, and adding authentication later is a
router-level dependency rather than a change to this signature.

Three properties of the response are contractual:

* ``team_*`` blocks are **derived**, not ``model``. A simulation is a
  calculation performed above the model; labelling its output ``model`` would
  extend the foundation's measured guarantees to a number that was never
  measured against a held-out residual.
* ``assumptions`` is a set of fields, not a paragraph. A client renders a banner
  from ``player_independence`` without string-matching prose, and the day a
  kicker model ships ``kicker_projection_available`` flips on its own.
* ``meta.notices`` carries the caveats — coverage gaps, correlation groups,
  injury designations, extrapolated intervals. A win probability shown without
  them is the dishonest version of this feature.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from ...correlation import CorrelationMode, CorrelationModel
from ...correlation import fitted as fitted_correlation
from ...services import simulation as service
from ...services.catalog import resolve_scoring_profile
from ...services.errors import InvalidRequest
from .. import mappers, schemas
from ..dependencies import DbSession

router = APIRouter(tags=["simulation"])


def _resolve_correlation(
    requested: str, scoring_profile: str | None
) -> tuple[CorrelationMode, CorrelationModel | None]:
    """Turn the request's ``correlation_mode`` into a mode and a structure.

    Resolved here rather than in the service because both failures are request
    errors with remedies a caller can act on, and both must be **refusals**
    rather than fallbacks. Quietly running independently when a caller asked for
    ``game_environment`` would return a response labelled with the mode that ran
    — so the label would be right — while silently answering a different
    question than the one asked, with no signal that it had happened.
    """
    try:
        mode = CorrelationMode(requested)
    except ValueError:
        raise InvalidRequest(
            f"unknown correlation_mode {requested!r}; expected one of "
            f"{', '.join(m.value for m in CorrelationMode)}.",
            field="correlation_mode",
        ) from None

    if mode is CorrelationMode.INDEPENDENT:
        return mode, None

    try:
        return mode, fitted_correlation.for_profile(
            resolve_scoring_profile(scoring_profile)
        )
    except fitted_correlation.ProfileNotFitted as error:
        raise InvalidRequest(str(error), field="correlation_mode") from None


@router.post(
    "/simulations",
    response_model=schemas.Envelope[schemas.MatchupSimulationOut],
    status_code=status.HTTP_200_OK,
    responses={422: {"model": schemas.ErrorOut}, 503: {"model": schemas.ErrorOut}},
    summary="Simulate a head-to-head fantasy matchup",
    description=(
        "Monte Carlo over the **stored** outcome distributions. Each iteration "
        "draws `u ~ U(0,1)` per player and takes the published quantile "
        "function at `u`, sums each side, and records the winner. No model is "
        "invoked, no projection is computed and no uncertainty is invented — "
        "every distribution sampled was calibrated against held-out residuals "
        "by the frozen foundation.\n\n"
        "**Reproducible.** The same lineups against the same published run with "
        "the same seed produce identical numbers. Omitting `seed` uses a fixed "
        "default rather than entropy; the seed used is always echoed in "
        "`simulation.seed`.\n\n"
        "**Independent by default, and says so.** Player outcomes are drawn "
        "independently unless `correlation_mode` asks otherwise. Teammates "
        "divide one offence's plays and opposing players share game script, so "
        "the joint distribution is correlated. Phase 6D measured the cost of "
        "ignoring that at 2,878 held-out lineups: 80% interval coverage 0.7943 "
        "against a nominal 0.800, with correlation moving it past nominal "
        "rather than onto it. See `assumptions.player_independence` "
        "and `meta.notices`.\n\n"
        "**`correlation_mode: game_environment` is experimental.** It applies a "
        "correlation structure fitted on held-out historical outcomes, leaving "
        "every player's own distribution unchanged. It is not the default "
        "because it has not been shown to beat the independent baseline on "
        "held-out matchups — the mode that ran is always reported in "
        "`simulation.correlation_mode`, with the structure's version beside "
        "it.\n\n"
        "**Skill positions only.** Kickers and team defences have no projection "
        "model, so a K or DST slot is refused with the reason and the blockers "
        "rather than silently dropped — a total missing a starter is wrong in a "
        "direction the caller cannot see. `GET /meta/lineup-slots` serves the "
        "slot vocabulary; `GET /meta/positions` explains the gaps.\n\n"
        "Nothing is stored. Rosters, simulation history and authentication are "
        "later phases."
    ),
)
async def simulate_matchup(
    db: DbSession, request: schemas.SimulationIn
) -> schemas.Envelope[schemas.MatchupSimulationOut]:
    mode, correlation_model = _resolve_correlation(
        request.correlation_mode, request.scoring_profile
    )
    result, window = await service.simulate_matchup(
        db,
        team_a=[entry.model_dump() for entry in request.team_a],
        team_b=[entry.model_dump() for entry in request.team_b],
        season=request.season,
        week=request.week,
        scoring_profile=request.scoring_profile,
        iterations=request.simulation_count,
        seed=request.seed,
        correlation_mode=mode,
        correlation_model=correlation_model,
    )
    return schemas.Envelope[schemas.MatchupSimulationOut](
        data=mappers.matchup_simulation(result),
        meta=schemas.MetaOut(
            window=schemas.slate_window_out(window),
            scoring_profile=result.scoring_profile,
            model=mappers.model_ref(result.model),
            notices=list(result.caveats),
        ),
    )
