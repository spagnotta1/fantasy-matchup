"""Translating between feature-table columns and scoring components.

The prediction engine predicts *components* and derives points from them with
:func:`nflfp.scoring.points_for`. That requires mapping two naming schemes:

* ``feat_training_dataset`` names its columns for the modelling context —
  ``fumbles_lost_actual``, ``pass_attempts_l4``;
* :data:`nflfp.scoring.COMPONENT_FIELDS` names them for the scoring rules, which
  match nflverse's own stat names — ``fumbles_lost_total``, ``attempts``.

Those are *nearly* the same, which is the dangerous kind of difference. Deriving
one from the other by string manipulation appears to work and silently drops the
handful that do not follow the pattern: a first attempt at this lost
``fumbles_lost_total`` and scored 1,018 player-weeks wrong without erroring.

So the mapping is explicit, and a test asserts it round-trips actual components
back to the actual points already stored in the warehouse.
"""

from __future__ import annotations

from ..scoring import COMPONENT_FIELDS, PROFILES, ScoringRules, points_for

#: scoring component -> column suffix in the feature table.
#: Only entries that differ from the plain component name need listing, but all
#: are spelled out: this table is the contract, and a reader should not have to
#: work out which ones are exceptions.
COMPONENT_TO_COLUMN: dict[str, str] = {
    "passing_yards": "passing_yards",
    "passing_tds": "passing_tds",
    "passing_interceptions": "passing_interceptions",
    "passing_2pt_conversions": "passing_2pt_conversions",
    "rushing_yards": "rushing_yards",
    "rushing_tds": "rushing_tds",
    "rushing_2pt_conversions": "rushing_2pt_conversions",
    "receptions": "receptions",
    "receiving_yards": "receiving_yards",
    "receiving_tds": "receiving_tds",
    "receiving_2pt_conversions": "receiving_2pt_conversions",
    # The one that does not follow the pattern, and the reason this table exists.
    "fumbles_lost_total": "fumbles_lost",
    "special_teams_tds": "special_teams_tds",
}

#: Components with no column in the feature table. They exist only to reproduce
#: nflverse's own `fantasy_points` for the parity regression test, and are not
#: modelled — the profiles anyone plays use `fumbles_lost_total` instead.
UNMAPPED_COMPONENTS = frozenset(
    {"sack_fumbles_lost", "rushing_fumbles_lost", "receiving_fumbles_lost"}
)


def actual_components(row) -> dict[str, float | None]:
    """Extract the realised components from a feature-table row.

    Args:
        row: A mapping from ``feat_training_dataset``.

    Returns:
        Components keyed by :data:`nflfp.scoring.COMPONENT_FIELDS`.
    """
    return {
        component: row.get(f"{column}_actual")
        for component, column in COMPONENT_TO_COLUMN.items()
    }


def score_components(
    components: dict[str, float | None],
    position: str | None = None,
    profiles: dict[str, ScoringRules] | None = None,
) -> dict[str, float]:
    """Score one set of components under every league profile.

    This is what makes a single component projection serve all scoring formats,
    and what keeps `projections` scoring-agnostic while `projection_points`
    carries one row per profile.

    Args:
        components: Predicted or actual component values.
        position: Required for TE-premium profiles.
        profiles: Defaults to every profile except the parity fixture, which is
            a regression test rather than a format anyone plays.

    Returns:
        ``{profile_name: points}``.
    """
    if profiles is None:
        profiles = {
            name: rules
            for name, rules in PROFILES.items()
            if name != "nflverse_parity"
        }
    return {
        name: points_for(components, rules, position=position)
        for name, rules in profiles.items()
    }


def validate_mapping() -> None:
    """Fail loudly if the mapping and the scoring rules have drifted apart.

    Called at import by the tests. A component that is neither mapped nor
    explicitly declared unmapped is a column the model will predict and the
    scorer will silently ignore.
    """
    known = set(COMPONENT_TO_COLUMN) | UNMAPPED_COMPONENTS
    missing = set(COMPONENT_FIELDS) - known
    if missing:
        raise ValueError(
            f"scoring components with no column mapping: {sorted(missing)}"
        )
    extra = set(COMPONENT_TO_COLUMN) - set(COMPONENT_FIELDS)
    if extra:
        raise ValueError(f"mapped components the scorer does not know: {sorted(extra)}")
