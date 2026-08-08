"""Distribution percentiles and calibration metadata.

Widens ``projection_points`` from a three-point summary to a full outcome
distribution, so the future Monte Carlo simulation engine can sample from what
is stored rather than reconstructing a shape from "expected +/- a percentage".

Added:

* ``expected_points`` - the mean of the held-out outcome distribution. This is
  the calibrated headline number; ``predicted_points`` keeps the model's raw
  output for lineage. They differ because shrinkage trades bias for variance,
  and measured conditional bias on the raw value ran to -1.6 points.
* ``p25_points`` / ``p75_points`` - completing P10/P25/P50/P75/P90, with
  ``floor``/``median``/``ceiling`` retained as the P10/P50/P90 names the rest of
  the system already uses. No duplication: each percentile is stored once.
* ``standard_deviation`` - for simulators that want a moment rather than
  quantiles.
* ``calibration_method``, ``distribution_samples``, ``extrapolated`` - how the
  distribution was made, how much data stood behind it, and whether the
  projection exceeded anything seen when fitting. A wide interval from 40
  observations is not the same claim as one from 4,000, and the row should say so.

The ordering CHECK constraints are replaced to cover the full chain
P10 <= P25 <= P50 <= P75 <= P90.

Existing rows keep their values: the new columns are nullable, so historical
projections stay exactly as they were written.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = 'f453f4de885f'
down_revision: str | None = '8bd687fede06'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('projection_points', sa.Column('expected_points', sa.Float(), nullable=True))
    op.add_column('projection_points', sa.Column('p25_points', sa.Float(), nullable=True))
    op.add_column('projection_points', sa.Column('p75_points', sa.Float(), nullable=True))
    op.add_column('projection_points', sa.Column('standard_deviation', sa.Float(), nullable=True))
    op.add_column('projection_points', sa.Column('calibration_method', sa.String(length=48), nullable=True))
    op.add_column('projection_points', sa.Column('distribution_samples', sa.Integer(), nullable=True))
    op.add_column('projection_points', sa.Column('extrapolated', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    # ck_projection_points_floor_le_median and ..._median_le_ceiling are
    # deliberately RETAINED. The new quartile chain is NULL-permissive at
    # every link, so with p25/p75 absent a reversed floor/median/ceiling
    # would satisfy all of it. The direct checks close that gap.
    op.create_check_constraint(op.f('ck_projection_points_p10_le_p25'), 'projection_points', 'floor_points IS NULL OR p25_points IS NULL OR floor_points <= p25_points')
    op.create_check_constraint(op.f('ck_projection_points_p25_le_p50'), 'projection_points', 'p25_points IS NULL OR median_points IS NULL OR p25_points <= median_points')
    op.create_check_constraint(op.f('ck_projection_points_p50_le_p75'), 'projection_points', 'median_points IS NULL OR p75_points IS NULL OR median_points <= p75_points')
    op.create_check_constraint(op.f('ck_projection_points_p75_le_p90'), 'projection_points', 'p75_points IS NULL OR ceiling_points IS NULL OR p75_points <= ceiling_points')
    op.create_check_constraint(op.f('ck_projection_points_standard_deviation_non_negative'), 'projection_points', 'standard_deviation IS NULL OR standard_deviation >= 0')


def downgrade() -> None:
    op.drop_constraint(op.f('ck_projection_points_standard_deviation_non_negative'), 'projection_points', type_='check')
    op.drop_constraint(op.f('ck_projection_points_p75_le_p90'), 'projection_points', type_='check')
    op.drop_constraint(op.f('ck_projection_points_p50_le_p75'), 'projection_points', type_='check')
    op.drop_constraint(op.f('ck_projection_points_p25_le_p50'), 'projection_points', type_='check')
    op.drop_constraint(op.f('ck_projection_points_p10_le_p25'), 'projection_points', type_='check')
    op.drop_column('projection_points', 'extrapolated')
    op.drop_column('projection_points', 'distribution_samples')
    op.drop_column('projection_points', 'calibration_method')
    op.drop_column('projection_points', 'standard_deviation')
    op.drop_column('projection_points', 'p75_points')
    op.drop_column('projection_points', 'p25_points')
    op.drop_column('projection_points', 'expected_points')
