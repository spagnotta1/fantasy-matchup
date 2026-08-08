"""Where every number in a response came from.

This is the API's central contract, and it exists because a fantasy projection
screen mixes three kinds of number that look identical and mean entirely
different things:

``model``
    Produced by the published, frozen model run. A projected point total, its
    distribution, its components. These carry the guarantees in
    :mod:`nflfp.predict.foundation` — measured interval coverage, measured
    calibration, measured conditional bias.

``derived``
    Computed **above** the model from warehouse data the model did not use.
    The matchup grade is the clear case: it comes from a trailing four-game
    aggregate of defensive fantasy points allowed, ranked within position. It
    is real, it is reproducible, and the model has never seen it. Treating it
    as a model output would imply it was validated as one; it was not.

``context``
    Observed facts the model does **not** currently incorporate at all —
    weather, the betting market, injury designations. Layer 3b measured each
    against the baseline's residual and excluded them on the evidence. They are
    shown because a user's judgement is better than nothing, and labelled
    because a user's judgement is not the model's.

Why this is in the schema and not the docs
------------------------------------------
A caveat in an API guide is read once. A field is read every time. Every block
of numbers in a response carries a ``provenance`` discriminator and, where it
applies, ``applied_to_projection`` and ``unapplied_reason`` — so a client that
renders a weather panel next to a projection cannot accidentally imply the
projection accounts for the wind, and a client author who never reads the guide
still has to look at the field name.

It also makes the extension path checkable. When a future model does fit a
weather adjustment, the engine writes ``weather_multiplier``, the business
layer flips ``applied_to_projection`` to ``True``, and the same field a client
was already rendering starts saying something different. No schema version, no
migration for consumers — which is the property that makes "keep the
architecture ready" mean something concrete.
"""

from __future__ import annotations

from enum import Enum


class Provenance(str, Enum):
    """How a block of numbers was produced.

    A ``str`` enum so it serialises as its value and a client can compare it to
    a literal without importing anything.
    """

    #: Output of the published model run, carrying the foundation's guarantees.
    MODEL = "model"

    #: Computed above the model from warehouse data the model did not consume.
    DERIVED = "derived"

    #: Observed and reported; not an input to the projection.
    CONTEXT = "context"

    #: A recorded outcome. Not a prediction at all — what actually happened.
    ACTUAL = "actual"


#: Human-readable legend, served at ``/meta/provenance`` and embedded in the
#: OpenAPI description. Sourced here so the API guide and the field
#: descriptions cannot disagree.
PROVENANCE_LEGEND: dict[str, str] = {
    Provenance.MODEL.value: (
        "Produced by the published model run. Interval coverage, calibration "
        "and conditional bias for these numbers are measured and published at "
        "/meta/model."
    ),
    Provenance.DERIVED.value: (
        "Computed above the model from warehouse data the model did not use — "
        "for example a matchup grade from trailing defensive fantasy points "
        "allowed. Reproducible, but not validated as a prediction."
    ),
    Provenance.CONTEXT.value: (
        "Observed facts the model does not currently incorporate: weather, the "
        "betting market, injury designations. Check applied_to_projection "
        "before implying a projection accounts for any of it."
    ),
    Provenance.ACTUAL.value: (
        "A recorded outcome from a completed game. Not a prediction."
    ),
}
