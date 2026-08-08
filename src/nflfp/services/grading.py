"""Turning stored numbers into the labels a user reads.

The database stores ``matchup_score`` as a number and never a letter, and
:mod:`nflfp.db.models.projection` says why: "the grade is derived above the
database so the thresholds live in one place." **This module is that one
place.** Nothing else in the codebase may hard-code a grade boundary, a
confidence adjective, or a start/sit cutoff.

Why a grade is a rank percentile
--------------------------------
The honest input to a matchup grade is ``feat_defense_position_rolling`` — a
trailing four-game average of fantasy points allowed to a position, ranked 1-32
within the week, with the window ending at the *previous* week so it is usable
on a Thursday. Rank 1 is the toughest defence.

Converting rank to a 0-100 score makes the grade a **percentile**, which has a
property worth stating plainly: by construction, roughly two and a half teams
hold each grade every week. An "A" therefore means "top few matchups this
week", not "unusually good in absolute terms" — those are different claims and
only one of them is supported by a rank. The magnitude claim is carried
separately by ``fp_allowed_vs_position_l4``, which is why both travel together
in :class:`~nflfp.services.dto.MatchupContext`.

The sample floor
----------------
A rank computed from one game is noise wearing a uniform. Below
:data:`MIN_GAMES_FOR_GRADE` observed games the grade is withheld rather than
softened, and the reason is returned with it. Week 1 has no defensive history
at all, so every Week 1 matchup is ungraded — which is correct, and much better
than a confident letter derived from last season's defence.
"""

from __future__ import annotations

from dataclasses import dataclass

#: NFL teams, and therefore the span of a defensive rank.
DEFENSE_RANKS = 32

#: Games in the trailing window below which a rank is not trustworthy enough to
#: publish as a letter. Three is the point at which one blowout stops dominating
#: a four-game average.
MIN_GAMES_FOR_GRADE = 3

#: The grade ladder, best first. Thirteen rungs over a uniform 0-100 percentile,
#: so each covers 100/13 of the score range and about 2.5 of the 32 defences.
#: ``F`` is the bottom rung and takes no modifier, matching the convention
#: everyone already reads without explanation.
GRADE_LADDER: tuple[str, ...] = (
    "A+", "A", "A-",
    "B+", "B", "B-",
    "C+", "C", "C-",
    "D+", "D", "D-",
    "F",
)


def grade_bands() -> tuple[tuple[str, float], ...]:
    """The ladder as ``(letter, minimum_score)`` pairs, best first.

    Derived rather than written out, so the bands cannot drift apart from
    :data:`GRADE_LADDER` and a reviewer can see at a glance that they are
    uniform. Exposed publicly because the API documents these thresholds and
    the tests assert their shape.
    """
    width = 100.0 / len(GRADE_LADDER)
    return tuple(
        (letter, round((len(GRADE_LADDER) - 1 - index) * width, 6))
        for index, letter in enumerate(GRADE_LADDER)
    )


@dataclass(frozen=True)
class MatchupGrade:
    """A defensive matchup expressed as a percentile, a letter, and a caveat.

    ``graded`` is the field to branch on. When it is ``False`` the letter and
    score are ``None`` and ``reason`` says why — a UI should render "not enough
    data" rather than inventing a neutral C.
    """

    graded: bool
    score: float | None = None
    letter: str | None = None
    defense_rank: int | None = None
    sample_games: int | None = None
    reason: str | None = None

    @property
    def is_favourable(self) -> bool:
        """True for a matchup in the softer half of the league."""
        return self.score is not None and self.score >= 50.0


def score_from_rank(rank: int | None, *, ranks: int = DEFENSE_RANKS) -> float | None:
    """Convert a 1-``ranks`` defensive rank into a 0-100 matchup score.

    Rank 1 is the *toughest* defence and therefore the *worst* matchup, so the
    mapping is inverted. Rank 1 scores 0, rank 32 scores 100.

    Args:
        rank: Defensive rank against the player's position, 1-based.
        ranks: Size of the ranking. Defaults to the 32 NFL teams; parameterised
            only so the maths is testable without pretending the league has
            changed size.

    Returns:
        A score in [0, 100], or ``None`` if the rank is missing or outside the
        expected range — a rank of 0 or 45 is a data bug, and quietly clamping
        it would hide that.
    """
    if rank is None or ranks < 2:
        return None
    if not 1 <= rank <= ranks:
        return None
    return (rank - 1) / (ranks - 1) * 100.0


def letter_grade(score: float | None) -> str | None:
    """The letter for a 0-100 matchup score, or ``None`` if there is no score.

    Scores outside [0, 100] are clamped here rather than rejected, because by
    the time a score reaches this function it has already been validated by
    whatever produced it, and a display helper is the wrong place to raise.
    """
    if score is None:
        return None
    bounded = min(100.0, max(0.0, float(score)))
    for letter, minimum in grade_bands():
        if bounded >= minimum:
            return letter
    return GRADE_LADDER[-1]  # pragma: no cover - the last band's minimum is 0


def grade_matchup(
    *,
    defense_rank: int | None,
    sample_games: int | None,
    stored_score: float | None = None,
) -> MatchupGrade:
    """Grade a defensive matchup, or explain why it cannot be graded.

    Args:
        defense_rank: Opponent's rank against this player's position, 1-32,
            from ``feat_defense_position_rolling``.
        sample_games: Games behind that rank (``games_in_window``).
        stored_score: A ``projections.matchup_score`` written by the prediction
            engine, if one exists. Takes precedence over the rank, because a
            model that computed its own matchup number knows more about what it
            actually used than this module can infer. In practice the current
            engine leaves it ``NULL`` — market and matchup adjustments were
            measured and dropped in Layer 3b — so the rank path is the live one.

    Returns:
        A :class:`MatchupGrade`, always; failure is a value, not an exception,
        because an ungraded matchup is a normal state on a Week 1 slate.
    """
    if stored_score is not None:
        return MatchupGrade(
            graded=True,
            score=float(stored_score),
            letter=letter_grade(stored_score),
            defense_rank=defense_rank,
            sample_games=sample_games,
        )

    if defense_rank is None:
        return MatchupGrade(
            graded=False,
            sample_games=sample_games,
            reason="no defensive ranking available for this opponent and position",
        )

    if sample_games is not None and sample_games < MIN_GAMES_FOR_GRADE:
        return MatchupGrade(
            graded=False,
            defense_rank=defense_rank,
            sample_games=sample_games,
            reason=(
                f"only {sample_games} game(s) of defensive history; "
                f"{MIN_GAMES_FOR_GRADE} needed before a rank means anything"
            ),
        )

    score = score_from_rank(defense_rank)
    if score is None:
        return MatchupGrade(
            graded=False,
            defense_rank=defense_rank,
            sample_games=sample_games,
            reason=f"defensive rank {defense_rank} is outside 1-{DEFENSE_RANKS}",
        )

    return MatchupGrade(
        graded=True,
        score=score,
        letter=letter_grade(score),
        defense_rank=defense_rank,
        sample_games=sample_games,
    )


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------

#: ``ProjectionPoints.confidence`` measures **how much information the model
#: had**, not how good the projection is — a confidently-projected bad player is
#: still a bad player. The adjectives below are chosen to describe evidence
#: rather than quality for that reason.
CONFIDENCE_BANDS: tuple[tuple[str, float], ...] = (
    ("high", 0.70),
    ("moderate", 0.45),
    ("low", 0.20),
    ("very_low", 0.0),
)


def confidence_label(confidence: float | None, *, extrapolated: bool = False) -> str:
    """Describe how much evidence stands behind a projection.

    Args:
        confidence: Stored 0-1 confidence, or ``None``.
        extrapolated: True when the projection exceeded anything seen while
            fitting the residual distribution. That caps the label regardless of
            the stored number: an interval nobody has observed is not a
            high-confidence interval, whatever the model's own bookkeeping says.
    """
    if confidence is None:
        return "unknown"
    label = next(
        (name for name, minimum in CONFIDENCE_BANDS if confidence >= minimum),
        "very_low",
    )
    if extrapolated and label in ("high", "moderate"):
        return "moderate" if label == "high" else "low"
    return label


# ---------------------------------------------------------------------------
# Start / sit
# ---------------------------------------------------------------------------

#: Win probability above which a start/sit call is stated rather than hedged.
#: 0.58 is not arbitrary: below it the edge is smaller than the week-to-week
#: noise the distributions themselves report, so a confident recommendation
#: would be claiming precision the model does not have.
START_SIT_DECISIVE = 0.58

#: Above this, the call is one-sided enough to say so without qualification.
START_SIT_CLEAR = 0.68


def start_sit_verdict(win_probability: float) -> str:
    """Classify a head-to-head win probability into a recommendation strength.

    Returns one of ``"clear"``, ``"lean"``, ``"toss_up"`` — always from the
    perspective of the first player. The caller decides which name goes with
    it; this function only decides how strongly to speak.
    """
    if not 0.0 <= win_probability <= 1.0:
        raise ValueError(f"win_probability must be in [0, 1], got {win_probability}")
    edge = abs(win_probability - 0.5) + 0.5
    if edge >= START_SIT_CLEAR:
        return "clear"
    if edge >= START_SIT_DECISIVE:
        return "lean"
    return "toss_up"


# ---------------------------------------------------------------------------
# Player archetype
# ---------------------------------------------------------------------------

#: Ratio of interquartile spread to median above which a player is "volatile".
#: Derived from the shape the exploration found: tight ends bust below five
#: points 48.5% of the time against 10.1% for running backs, so a single
#: points-based threshold would label an entire position and say nothing.
#: A *relative* spread compares a player to their own projection instead.
VOLATILITY_RATIO = 1.15


def outcome_shape(
    *, p25: float | None, median: float | None, p75: float | None
) -> str:
    """Label the shape of a projected outcome distribution.

    ``"volatile"`` when the interquartile range is wide relative to the median
    — a boom/bust profile that a tournament lineup wants and a cash lineup does
    not. ``"steady"`` otherwise, ``"unknown"`` when the quartiles are missing.

    A median at or below zero makes the ratio meaningless, so those are
    reported as ``"volatile"`` on the grounds that a player projected for
    nothing is, definitionally, all variance.
    """
    if p25 is None or p75 is None or median is None:
        return "unknown"
    if median <= 0:
        return "volatile"
    return "volatile" if (p75 - p25) / median >= VOLATILITY_RATIO else "steady"
