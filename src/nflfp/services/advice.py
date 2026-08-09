"""Start/sit and comparison — the only place the app tells a user what to do.

Everything else in this codebase reports. This module recommends, so it is the
module with the most ways to be quietly dishonest, and it is built to close
each of them:

**The recommendation is a probability, not a points comparison.** "Start A, he
is projected for 12.4 and B for 11.8" is the standard advice and it is close to
meaningless: the two distributions overlap almost entirely, and the model's own
mean absolute error is larger than the gap. So the call is made on
``P(A outscores B)``, integrated over the stored outcome curves, and a
half-point edge produces a 52% win probability and an explicit toss-up.

**A toss-up is a real answer.** Below :data:`~nflfp.services.grading.START_SIT_DECISIVE`
no player is named. Manufacturing a preference between two players separated by
less than the noise would be inventing precision, and a user who sees "too close
to call — here is what separates them" is better served than one who sees a
confident pick that is right 51% of the time.

**Correlation is disclosed, not ignored.** The head-to-head integral assumes
independence. Two players in the same game are not independent, and teammates
in the same passing offence are strongly dependent. The comparison detects both
and returns a caveat rather than silently reporting an over-confident number.

**Availability outranks the model.** A player designated Out is not a lower
projection; they are a zero the model does not know about, because the engine
has no fitted injury multiplier. That is surfaced as a hard caveat above the
statistical verdict.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from . import grading
from .distributions import HeadToHead, compare as compare_curves
from .dto import Comparison, ComparisonEntry, PlayerProjection, StartSitAdvice
from .errors import InvalidRequest, NotFound
from .projections import get_projections_for_players

logger = logging.getLogger(__name__)

#: Most players a single comparison may include. Pairwise head-to-heads are
#: quadratic, and beyond a handful the table stops being readable anyway.
MAX_COMPARISON_PLAYERS = 6


def _entry(projection: PlayerProjection, win_probability: float | None = None) -> ComparisonEntry:
    return ComparisonEntry(
        projection=projection,
        expected=projection.points.headline,
        floor=projection.points.floor,
        ceiling=projection.points.ceiling,
        win_probability=win_probability,
    )


def _availability_caveats(projection: PlayerProjection) -> list[str]:
    """Hard caveats that outrank any statistical comparison."""
    caveats: list[str] = []
    injury = projection.injury
    if injury is None:
        return caveats
    name = projection.player.name
    if injury.will_not_play:
        caveats.append(
            f"{name} is listed OUT. The projection does not know that — the "
            "engine has no fitted injury adjustment — so treat this number as "
            "describing a player who will not take the field."
        )
    elif injury.is_questionable_or_worse:
        caveats.append(
            f"{name} is listed {injury.report_status}"
            + (f" ({injury.detail})" if injury.detail else "")
            + ". The projection does not adjust for designation."
        )
    return caveats


def _rationale(
    a: PlayerProjection, b: PlayerProjection, head_to_head: HeadToHead
) -> tuple[str, ...]:
    """Explain a verdict in terms of the things that actually produced it.

    Each line is derived from a stored number, not from a template with a
    plausible-sounding adjective. A recommendation nobody can check is a
    recommendation nobody should follow.
    """
    lines: list[str] = []
    name_a, name_b = a.player.name, b.player.name

    lines.append(
        f"{name_a} outscores {name_b} in {head_to_head.win_probability:.0%} of "
        f"outcomes, with an expected margin of "
        f"{head_to_head.expected_margin:+.1f} points."
    )

    if head_to_head.mean_and_odds_disagree:
        higher = name_a if head_to_head.expected_margin > 0 else name_b
        likelier = name_b if head_to_head.expected_margin > 0 else name_a
        lines.append(
            f"{higher} has the higher projection but {likelier} is more likely "
            "to win the week — the gap is carried by a long ceiling rather than "
            "by the typical outcome."
        )

    floor_a, floor_b = a.points.floor, b.points.floor
    if floor_a is not None and floor_b is not None and abs(floor_a - floor_b) >= 1.5:
        safer = name_a if floor_a > floor_b else name_b
        lines.append(
            f"{safer} has the higher floor ({max(floor_a, floor_b):.1f} vs "
            f"{min(floor_a, floor_b):.1f}) — the choice if you need a safe week."
        )

    ceiling_a, ceiling_b = a.points.ceiling, b.points.ceiling
    if ceiling_a is not None and ceiling_b is not None and abs(ceiling_a - ceiling_b) >= 2.0:
        spikier = name_a if ceiling_a > ceiling_b else name_b
        lines.append(
            f"{spikier} has the higher ceiling ({max(ceiling_a, ceiling_b):.1f} vs "
            f"{min(ceiling_a, ceiling_b):.1f}) — the choice if you need a spike."
        )

    for projection, other_name in ((a, name_b), (b, name_a)):
        matchup = projection.matchup
        if matchup is not None and matchup.grade.graded and matchup.grade.letter:
            lines.append(
                f"{projection.player.name} draws {matchup.opponent}, a "
                f"{matchup.grade.letter} matchup for the position "
                f"(defensive rank {matchup.grade.defense_rank} of "
                f"{grading.DEFENSE_RANKS}, {matchup.grade.sample_games} games)."
            )

    return tuple(lines)


def start_sit(a: PlayerProjection, b: PlayerProjection) -> StartSitAdvice:
    """Compare two projections and make — or decline to make — a call.

    Pure: takes two assembled projections and returns advice. That is what
    makes the thresholds and the toss-up behaviour unit-testable without a
    database, which matters more here than anywhere else in the layer.

    Raises:
        InvalidRequest: if either projection has no usable distribution, since
            a head-to-head probability cannot be computed from a point estimate
            and pretending otherwise is exactly the failure this module exists
            to avoid.
    """
    if a.player.player_id == b.player.player_id:
        raise InvalidRequest("cannot compare a player with themselves")

    curve_a, curve_b = a.points.curve(), b.points.curve()
    if curve_a is None or curve_b is None:
        missing = a.player.name if curve_a is None else b.player.name
        raise InvalidRequest(
            f"no outcome distribution stored for {missing}; a head-to-head "
            "probability needs a distribution, not a point estimate"
        )

    correlated = a.shares_game_with(b)
    head_to_head = compare_curves(curve_a, curve_b, correlated=correlated)
    verdict = grading.start_sit_verdict(head_to_head.win_probability)

    recommended: str | None = None
    if verdict != "toss_up":
        winner = a if head_to_head.win_probability > 0.5 else b
        recommended = winner.player.player_id

    caveats = _availability_caveats(a) + _availability_caveats(b)
    if a.is_teammate_of(b):
        caveats.append(
            "These players share an offence. Their weekly outcomes are "
            "positively correlated through team plays and negatively "
            "correlated through target competition; the head-to-head "
            "probability assumes independence and is more confident than it "
            "should be."
        )
    elif correlated:
        warning = head_to_head.correlation_warning
        if warning:
            caveats.append(warning)

    for projection in (a, b):
        if projection.points.extrapolated:
            caveats.append(
                f"{projection.player.name}'s projection is above anything seen "
                "when the outcome distribution was fitted, so its interval is "
                "an extrapolation."
            )

    return StartSitAdvice(
        a=_entry(a, head_to_head.win_probability),
        b=_entry(b, 1.0 - head_to_head.win_probability),
        win_probability=head_to_head.win_probability,
        expected_margin=head_to_head.expected_margin,
        verdict=verdict,
        recommended=recommended,
        rationale=_rationale(a, b, head_to_head),
        caveats=tuple(caveats),
    )


async def compare_players(
    session: AsyncSession,
    *,
    player_ids: Sequence[str],
    season: int | None = None,
    week: int | None = None,
    scoring_profile: str | None = None,
) -> Comparison:
    """Build an n-way comparison table for a week.

    Entries are ordered best-first by calibrated expectation, and each
    consecutive pair gets a head-to-head call. Consecutive pairs rather than
    all pairs because that is the decision a user is actually making — "is the
    next one down close enough to matter?" — and because a six-player all-pairs
    table has fifteen verdicts nobody reads.

    Raises:
        InvalidRequest: for fewer than two ids, more than
            :data:`MAX_COMPARISON_PLAYERS`, or duplicates.
        NotFound: if no requested player has a published projection.
    """
    unique = list(dict.fromkeys(player_ids))
    if len(unique) < 2:
        raise InvalidRequest(
            "a comparison needs at least two distinct players", field="player_ids"
        )
    if len(unique) > MAX_COMPARISON_PLAYERS:
        raise InvalidRequest(
            f"at most {MAX_COMPARISON_PLAYERS} players may be compared at once",
            field="player_ids",
        )

    projections, window = await get_projections_for_players(
        session,
        player_ids=unique,
        season=season,
        week=week,
        scoring_profile=scoring_profile,
    )
    if not projections:
        raise NotFound(
            "projections", f"{unique} in {window.season}w{window.week}"
        )

    ordered = sorted(
        projections,
        key=lambda p: (
            -(p.points.headline if p.points.headline is not None else float("-inf")),
            p.player.player_id,
        ),
    )

    head_to_head: list[StartSitAdvice] = []
    for upper, lower in zip(ordered, ordered[1:]):
        try:
            head_to_head.append(start_sit(upper, lower))
        except InvalidRequest:
            # One of the pair has no distribution. Skipping the verdict keeps
            # the rest of the table useful, which is better than failing a
            # six-player comparison because one row is thin.
            logger.info(
                "skipping head-to-head %s vs %s: missing distribution",
                upper.player.player_id, lower.player.player_id,
            )

    profile = ordered[0].points.scoring_profile
    return Comparison(
        season=window.season,
        week=window.week,
        scoring_profile=profile,
        entries=tuple(_entry(p) for p in ordered),
        head_to_head=tuple(head_to_head),
    )


async def get_start_sit(
    session: AsyncSession,
    *,
    player_a: str,
    player_b: str,
    season: int | None = None,
    week: int | None = None,
    scoring_profile: str | None = None,
) -> StartSitAdvice:
    """Fetch two projections and make the call.

    Raises:
        NotFound: naming whichever player has no published projection, so the
            caller can tell which of the two ids was the problem.
    """
    if player_a == player_b:
        raise InvalidRequest("cannot compare a player with themselves")

    projections, window = await get_projections_for_players(
        session,
        player_ids=[player_a, player_b],
        season=season,
        week=week,
        scoring_profile=scoring_profile,
    )
    by_id = {p.player.player_id: p for p in projections}
    for player_id in (player_a, player_b):
        if player_id not in by_id:
            raise NotFound("projection", f"{player_id} {window.season}w{window.week}")

    return start_sit(by_id[player_a], by_id[player_b])
