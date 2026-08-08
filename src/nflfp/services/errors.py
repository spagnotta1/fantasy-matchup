"""Domain errors raised by the business layer.

These are deliberately **HTTP-free**. The service layer does not know it is
being called by a web API — the same code has to be usable from a worker, a
notebook or a CLI, and a layer that raises ``fastapi.HTTPException`` cannot be.
Layer 5 owns exactly one exception handler that maps each of these onto a
status code, so the mapping lives in one place and every endpoint answers the
same way.

Each error carries structured attributes rather than only a formatted message,
so the API can render a machine-readable body without re-parsing prose.
"""

from __future__ import annotations


class ServiceError(Exception):
    """Base class for every error the business layer raises deliberately.

    Anything *not* deriving from this is a bug, and Layer 5 is expected to turn
    it into a 500 with a logged traceback rather than an apologetic 400.
    """

    #: Stable, machine-readable code. Part of the API contract; do not rename
    #: one of these without treating it as a breaking change.
    code = "service_error"


class NotFound(ServiceError):
    """A requested entity does not exist.

    Args:
        resource: What was being looked up, e.g. ``"player"``.
        identifier: The key that failed to resolve.
    """

    code = "not_found"

    def __init__(self, resource: str, identifier: object) -> None:
        self.resource = resource
        self.identifier = identifier
        super().__init__(f"{resource} not found: {identifier!r}")


class InvalidRequest(ServiceError):
    """The caller asked for something incoherent.

    Distinct from a Pydantic validation failure, which Layer 5 catches before
    a service is ever entered. This is for constraints the API schema cannot
    express — "week 5 of a season that has not started", "compare a player
    with themselves".
    """

    code = "invalid_request"

    def __init__(self, message: str, *, field: str | None = None) -> None:
        self.field = field
        super().__init__(message)


class NoProjectionsPublished(ServiceError):
    """A slate was requested for a week with no published model run.

    Separated from :class:`NotFound` because it is an *operational* state, not
    a client mistake: the week exists, the players exist, and the projection
    job simply has not run or has not been promoted. The API answers 200 with
    an empty, clearly-labelled slate for list endpoints and 404 for a single
    projection, and an operator reading logs can tell the two apart.
    """

    code = "no_projections_published"

    def __init__(self, season: int, week: int, *, scoring_profile: str | None = None) -> None:
        self.season = season
        self.week = week
        self.scoring_profile = scoring_profile
        detail = f" for scoring profile {scoring_profile!r}" if scoring_profile else ""
        super().__init__(f"no published projections for {season} week {week}{detail}")


class DataUnavailable(ServiceError):
    """A required relation is missing from the database.

    This is a real and *recoverable* deployment state, not a corruption. Three
    ordinary situations produce it, and each has a different fix:

    * a fresh deployment where the warehouse has never been built;
    * a ``pipeline full`` publish, which drops ``raw_*`` with ``CASCADE`` and
      takes every dependent materialized view with it until ``build_features``
      runs again;
    * a database that has been migrated but not loaded.

    The remedy is derived from *which* relation is missing, because the wrong
    command is barely better than no command. Without this, the first thing a
    new deployment shows is ``relation "upcoming_games" does not exist``
    surfacing as an unexplained 500 from every endpoint at once — the default
    week resolves against ``upcoming_games``, so nothing works until the
    pipeline has run.
    """

    code = "data_unavailable"

    #: Relation prefix or exact name -> the command that creates it. Checked in
    #: order, most specific first.
    _REMEDIES: tuple[tuple[str, str], ...] = (
        ("feat_", "python -m nflfp.jobs run build_features"),
        ("raw_", "python -m nflfp.pipeline full"),
        ("stg_", "python -m nflfp.pipeline full"),
        ("player_week", "python -m nflfp.pipeline full"),
        ("game_team", "python -m nflfp.pipeline full"),
        ("upcoming_games", "python -m nflfp.pipeline full"),
        ("model_runs", "alembic upgrade head"),
        ("projections", "alembic upgrade head"),
        ("projection_points", "alembic upgrade head"),
    )

    #: Fallback when the relation matches nothing known.
    DEFAULT_REMEDY = "python -m nflfp.pipeline full"

    def __init__(self, relation: str) -> None:
        self.relation = relation
        self.remedy = self._remedy_for(relation)
        super().__init__(
            f"required relation {relation!r} does not exist; run: {self.remedy}"
        )

    @classmethod
    def _remedy_for(cls, relation: str) -> str:
        for prefix, command in cls._REMEDIES:
            if relation == prefix or relation.startswith(prefix):
                return command
        return cls.DEFAULT_REMEDY


#: Kept as an alias: a missing materialized view is by far the most common case
#: and reads better at the call sites that only ever raise it for one.
FeatureLayerUnavailable = DataUnavailable


class UnknownScoringProfile(InvalidRequest):
    """A scoring profile that is not a published league format."""

    code = "unknown_scoring_profile"

    def __init__(self, profile: str, known: tuple[str, ...]) -> None:
        self.profile = profile
        self.known = known
        InvalidRequest.__init__(
            self,
            f"unknown scoring profile {profile!r}; expected one of {list(known)}",
            field="scoring_profile",
        )
