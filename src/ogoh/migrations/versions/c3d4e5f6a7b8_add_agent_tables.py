"""add agent_enabled, agent_usage, agent_query_cache

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-31 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # NOT NULL against a users table with rows: server_default fills the existing
    # ones with false, the same care text_complete needed.
    op.add_column(
        'users',
        sa.Column('agent_enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        'agent_usage',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('count', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('user_id', 'day'),
    )
    op.create_table(
        'agent_query_cache',
        sa.Column('query_hash', sa.String(length=64), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('query_hash'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('agent_query_cache')
    op.drop_table('agent_usage')
    op.drop_column('users', 'agent_enabled')
