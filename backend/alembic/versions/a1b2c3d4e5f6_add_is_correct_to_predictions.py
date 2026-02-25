"""add is_correct to predictions

Revision ID: a1b2c3d4e5f6
Revises: 3fa99cd03408
Create Date: 2026-02-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '3fa99cd03408'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('predictions', sa.Column('is_correct', sa.Boolean(), nullable=True))
    # Partial index on unsettled predictions — only includes rows where is_correct IS NULL.
    # Keeps the index small; settled predictions automatically drop out.
    op.create_index(
        'ix_predictions_unsettled',
        'predictions',
        ['fixture_id'],
        unique=False,
        postgresql_where=sa.text('is_correct IS NULL'),
    )


def downgrade() -> None:
    op.drop_index('ix_predictions_unsettled', table_name='predictions')
    op.drop_column('predictions', 'is_correct')
