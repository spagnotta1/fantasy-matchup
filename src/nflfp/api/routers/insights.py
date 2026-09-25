"""Planning and accountability views: the track record and strength of schedule.

Both are ``derived``. The track record grades stored ``model`` output against
``actual`` outcomes; strength of schedule applies the defensive-form grade to
every remaining week. Neither feeds a projection, and both say so in their
schemas and notices rather than only here.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from ...predict.foundation import VALIDATION
from ...services import schedule as schedule_service
from ...services import track_record as track_record_service
from .. import mappers, schemas
from ..dependencies import DbSession, SlateQuery

router = APIRouter(tags=["insights"])


def _validation() -> schemas.ValidationRecordOut:
    return schemas.ValidationRecordOut(
        seasons=list(VALIDATION.seasons),
        held_out_distributions=VALIDATION.held_out_distributions,
        coverage_80=VALIDATION.coverage_p10_p90,
        coverage_50=VALIDATION.coverage_p25_p75,
        nominal_80=VALIDATION.nominal_p10_p90,
        nominal_50=VALIDATION.nominal_p25_p75,
        max_conditional_bias=VALIDATION.max_conditional_bias,
    )


@router.get(
    "/track-record",
    response_model=schemas.Envelope[schemas.TrackRecordOut],
    summary="How stored projections fared against what happened",
    description=(
        "Every published run's stored projections, graded against the recorded "
        "outcome of the same player-week: interval coverage against its nominal "
        "rate, mean absolute error, bias, and boom/bust calibration — overall, "
        "by position, by season, by week and by projection band.\n\n"
        "`validation` carries the frozen foundation's walk-forward measurement "
        "beside it. They are different measurements over different sets and "
        "must be presented as such.\n\n"
        "A projected player with no stat line did not play and is excluded, not "
        "counted as zero. `scorecard` is one week's biggest beats and misses "
        "among players projected at least `min_projection` points; it shows the "
        "requested week when it has outcomes, otherwise the latest graded week."
    ),
)
async def track_record(
    db: DbSession,
    season: Annotated[
        int | None, Query(ge=1999, le=2200, description="Restrict to one season. Omit for all.")
    ] = None,
    week: Annotated[
        int | None, Query(ge=1, le=22, description="The scorecard's week within `season`.")
    ] = None,
    scoring_profile: Annotated[str | None, Query(description="League format.")] = None,
) -> schemas.Envelope[schemas.TrackRecordOut]:
    record = await track_record_service.get_track_record(
        db, scoring_profile=scoring_profile, season=season, week=week
    )
    return schemas.Envelope[schemas.TrackRecordOut](
        data=mappers.track_record(record, _validation()),
        meta=schemas.MetaOut(
            scoring_profile=record.scoring_profile, notices=list(record.notices)
        ),
    )


@router.get(
    "/schedule-strength",
    response_model=schemas.Envelope[schemas.ScheduleStrengthOut],
    summary="Every team's remaining schedule for one position, graded on current form",
    description=(
        "For each team, every remaining regular-season opponent from the "
        "selected week, graded against `position` with the same function and "
        "trailing four-game window as the weekly matchup grade. A bye is a cell "
        "with no opponent.\n\n"
        "Each opponent's grade is its form **as of the selected week**, carried "
        "forward to every later meeting. That is current form, not a forecast. "
        "Below three completed games a defence is left ungraded, so early-season "
        "tables are mostly withheld — by design. Provenance: `derived`."
    ),
)
async def schedule_strength(
    db: DbSession,
    slate_query: SlateQuery,
    position: Annotated[str, Query(description="QB, RB, WR or TE.")] = "WR",
) -> schemas.Envelope[schemas.ScheduleStrengthOut]:
    strength = await schedule_service.get_schedule_strength(
        db, position=position, season=slate_query.season, week=slate_query.week
    )
    return schemas.Envelope[schemas.ScheduleStrengthOut](
        data=mappers.schedule_strength(strength),
        meta=schemas.MetaOut(
            window=schemas.slate_window_out(strength.window),
            notices=list(strength.notices),
        ),
    )
