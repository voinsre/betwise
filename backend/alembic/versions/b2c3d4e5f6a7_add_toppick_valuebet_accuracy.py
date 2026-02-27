"""add top-pick and value-bet accuracy columns to model_accuracy

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-02-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('model_accuracy', sa.Column('top_pick_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('model_accuracy', sa.Column('top_pick_correct', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('model_accuracy', sa.Column('top_pick_accuracy_pct', sa.Float(), nullable=False, server_default='0'))
    op.add_column('model_accuracy', sa.Column('value_bet_count', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('model_accuracy', sa.Column('value_bet_correct', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('model_accuracy', sa.Column('value_bet_accuracy_pct', sa.Float(), nullable=False, server_default='0'))


def downgrade() -> None:
    op.drop_column('model_accuracy', 'value_bet_accuracy_pct')
    op.drop_column('model_accuracy', 'value_bet_correct')
    op.drop_column('model_accuracy', 'value_bet_count')
    op.drop_column('model_accuracy', 'top_pick_accuracy_pct')
    op.drop_column('model_accuracy', 'top_pick_correct')
    op.drop_column('model_accuracy', 'top_pick_count')
