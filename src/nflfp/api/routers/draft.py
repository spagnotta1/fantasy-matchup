"""Mock draft — league configuration in, simulated draft outcomes out.

``POST`` for the two analysis endpoints, for the same reason the simulation
endpoint uses it: a league configuration is a nested object with a roster
specification inside it, which does not fit sensibly in a query string and would
produce a cache key nobody could read. The method also keeps these responses out
of the shared cache by construction — the middleware caches ``GET`` only — which
is right here, because the input space is effectively unbounded and a cached
draft would evict things people actually re-read.

``GET /mock-draft/config`` is the exception and *is* cached: it is the same
answer for everybody until a projection run publishes.

**Nothing is persisted.** No draft, no roster, no league, no user. A result is
reproducible from the settings, the published run, the historical panel and the
seed, all four of which come back in the response, so there is nothing a stored
copy would provide that recomputation does not.

Four properties of these responses are contractual:

* Every simulated number is ``derived``. A draft outcome is computed above the
  model, over a pool the model never ranked, against opponents it knows nothing
  about. Calling any of it ``model`` would lend it the foundation's measured
  guarantees.
* ``best_position`` is the **highest simulated value**, not a recommendation
  and not a prediction. ``spread_is_resolvable`` says whether the ranking
  survives the simulation's own error, and a client that draws an arrow at a
  winner without reading it is misreporting the result.
* ``meta.notices`` carries the methodology's limits — the week 1 rate, the
  availability estimate, the absent rookies, the unvalidated opponent model.
  A draft board shown without them is the dishonest version of this feature.
* A K or DST roster slot is **refused** with the reason and the blockers rather
  than silently dropped, exactly as the lineup endpoints refuse them.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from ...services import positions as position_registry
from ...services.catalog import scoring_profiles
from ...services.draft import service
from ...services.draft.valuation import DEFAULT_OPPONENT_SKILL, OPPONENT_SKILLS
from .. import mappers, schemas
from ..dependencies import DbSession

router = APIRouter(tags=["mock-draft"], prefix="/mock-draft")


@router.get(
    "/config",
    response_model=schemas.Envelope[schemas.DraftConfigOut],
    summary="What a valid mock draft request looks like",
    description=(
        "Bounds, defaults and the seasons that can actually be drafted. A "
        "client builds its configuration form from this rather than from "
        "hard-coded constants, which is what keeps the form's validation and "
        "the server's from drifting apart.\n\n"
        "`draftable_seasons` lists seasons with a published **week 1** board, "
        "and that is the only constraint on what can be drafted. A season "
        "with a schedule but no published run would render as an empty "
        "screen with no explanation, so it is not offered.\n\n"
        "An **upcoming** season qualifies. The frozen model projects a week "
        "from a trailing four-game usage window, and a week 1 window is the "
        "tail of the previous season — which is exactly what a manager has "
        "on draft day. `feat_preseason_slate` assembles those rows from the "
        "coming season's schedule and rosters, so `python -m nflfp.predict "
        "project --season <year> --week 1 --publish` makes next season "
        "draftable without a new model and without an invented number. What "
        "it cannot supply is rookies: no completed games means no window, so "
        "the incoming class is absent from the board and `pool.rookies_absent` "
        "says so.\n\n"
        "`opponent_skills` describes how well the other managers can be made "
        "to draft, and each level carries the two things that were measured "
        "about it: how far the board scatters, and what a good draft is worth "
        "against it. A client should offer the choice rather than defaulting "
        "it silently — it changes the answer more than any other setting."
    ),
)
async def draft_config(db: DbSession) -> schemas.Envelope[schemas.DraftConfigOut]:
    limits = service.limits()
    seasons = await service.draftable_seasons(db)
    return schemas.Envelope[schemas.DraftConfigOut](
        data=schemas.DraftConfigOut(
            limits=schemas.DraftLimitsOut(
                min_teams=limits.min_teams,
                max_teams=limits.max_teams,
                min_rounds=limits.min_rounds,
                max_rounds=limits.max_rounds,
                min_simulations=limits.min_simulations,
                max_simulations=limits.max_simulations,
                default_simulations=limits.default_simulations,
                max_total_drafts=service.MAX_TOTAL_DRAFTS,
                default_seed=limits.default_seed,
                draft_formats=list(limits.draft_formats),
                opponent_skills=[
                    mappers.opponent_skill(
                        level, is_default=level.name == DEFAULT_OPPONENT_SKILL
                    )
                    for level in OPPONENT_SKILLS
                ],
                default_roster=[
                    schemas.RosterSlotIn(slot=r.slot, count=r.count)
                    for r in limits.default_roster
                ],
                scoring_profiles=list(scoring_profiles()),
            ),
            draftable_seasons=list(seasons),
            draftable_positions=list(position_registry.PROJECTED_POSITIONS),
            unavailable_positions=[
                entry
                for entry in position_registry.support_summary()
                if not entry["projected"]
            ],
        ),
        meta=schemas.MetaOut(
            notices=[
                "Season value is a published week 1 projection read as a "
                "per-game rate, multiplied by an estimate of games played. "
                "There is no season-long projection in this system and none is "
                "invented here.",
            ]
            if seasons
            else [
                "No season has a published week 1 board, so no draft can be "
                "simulated yet. Run the projection job for week 1 of a "
                "completed season.",
            ]
        ),
    )


@router.post(
    "/analyze",
    response_model=schemas.Envelope[schemas.DraftAnalysisOut],
    status_code=status.HTTP_200_OK,
    responses={422: {"model": schemas.ErrorOut}, 503: {"model": schemas.ErrorOut}},
    summary="Simulate one draft position",
    description=(
        "Runs many complete drafts from one seat and returns the distribution "
        "of rosters it built, one representative roster with the reasoning "
        "behind every pick, the strategy findings the simulations support, and "
        "per-player availability at that seat's own picks.\n\n"
        "**The roster returned is the median simulation, never the best.** The "
        "best of ten thousand drafts happened because the board fell kindly, "
        "and presenting it as 'your roster' would promise an outcome most "
        "drafts do not produce.\n\n"
        "**Reproducible.** The same settings against the same published run "
        "with the same seed produce identical numbers. Omitting `seed` uses a "
        "fixed default rather than entropy; the seed used is always echoed.\n\n"
        "**Every pick's explanation is derived from the calculation.** "
        "`rationale` carries the marginal value, the expected value of "
        "waiting, the survival probability at the next pick and the runner-up "
        "margin — the actual numbers the engine compared — and the sentence is "
        "assembled from them.\n\n"
        "**Opposing managers are simulated, and the model is an assumption.** "
        "This repository holds no average-draft-position data, so the "
        "consensus board driving the other seats is a stated behavioural model "
        "that has not been validated against real drafts. Its two parameters "
        "are request fields so that a conclusion's sensitivity to them can be "
        "checked.\n\n"
        "**`opponent_skill` decides how hard the room is, and it moves this "
        "result more than anything else on the request.** A roster simulated "
        "against a casual room is not evidence about a sharp one: the same "
        "seat and seed that finish first in nine drafts of ten against "
        "`casual` finish mid-table against `sharp`, because talent stops "
        "sliding. Set it to the league you are actually in."
    ),
)
async def analyze_draft_position(
    db: DbSession, request: schemas.DraftAnalysisIn
) -> schemas.Envelope[schemas.DraftAnalysisOut]:
    analysis = await service.analyse_draft_position(
        db,
        draft_position=request.draft_position,
        teams=request.teams,
        rounds=request.rounds,
        season=request.season,
        scoring_profile=request.scoring_profile,
        roster=[entry.model_dump() for entry in request.roster]
        if request.roster
        else None,
        draft_format=request.draft_format,
        simulations=request.simulations,
        seed=request.seed,
        opponent_skill=request.opponent_skill,
        history_weight=request.history_weight,
        noise=request.noise,
    )
    return schemas.Envelope[schemas.DraftAnalysisOut](
        data=mappers.draft_analysis(analysis, analysis.history),
        meta=schemas.MetaOut(
            scoring_profile=analysis.settings.scoring_profile,
            model=mappers.model_ref(analysis.model),
            notices=list(analysis.notices),
        ),
    )


@router.post(
    "/compare",
    response_model=schemas.Envelope[schemas.DraftComparisonOut],
    status_code=status.HTTP_200_OK,
    responses={422: {"model": schemas.ErrorOut}, 503: {"model": schemas.ErrorOut}},
    summary="Compare every draft position",
    description=(
        "Simulates all seats against one shared player pool and one shared "
        "availability calibration, and ranks them by mean simulated roster "
        "value.\n\n"
        "**Read `spread_is_resolvable` before reading the ranking.** It says "
        "whether the gap between the best and worst seat exceeds the Monte "
        "Carlo error on the means it is computed from. When it is false the "
        "order is noise, and the response says so in `meta.notices` rather "
        "than leaving a client to draw a winner out of it.\n\n"
        "`detail` carries each seat's full analysis, so clicking a draft "
        "position to inspect its simulated roster costs no second request.\n\n"
        "Total simulated drafts are `teams x simulations`, and a request above "
        "the per-request cap is refused with the arithmetic rather than "
        "silently truncated. `methodology.elapsed_seconds` reports what it "
        "actually cost."
    ),
)
async def compare_draft_positions(
    db: DbSession, request: schemas.DraftSettingsIn
) -> schemas.Envelope[schemas.DraftComparisonOut]:
    comparison = await service.compare_draft_positions(
        db,
        teams=request.teams,
        rounds=request.rounds,
        season=request.season,
        scoring_profile=request.scoring_profile,
        roster=[entry.model_dump() for entry in request.roster]
        if request.roster
        else None,
        draft_format=request.draft_format,
        simulations=request.simulations,
        seed=request.seed,
        opponent_skill=request.opponent_skill,
        history_weight=request.history_weight,
        noise=request.noise,
    )
    return schemas.Envelope[schemas.DraftComparisonOut](
        data=mappers.draft_comparison(comparison, comparison.history),
        meta=schemas.MetaOut(
            scoring_profile=comparison.settings.scoring_profile,
            model=mappers.model_ref(comparison.model),
            notices=list(comparison.notices),
        ),
    )
