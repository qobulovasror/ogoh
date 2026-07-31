"""add user_keywords table

Revision ID: a1b2c3d4e5f6
Revises: bdebf35264f2
Create Date: 2026-07-31 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'bdebf35264f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'user_keywords',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('keyword', sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('user_id', 'keyword'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('user_keywords')
