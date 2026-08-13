"""api_keys scopes and expires_at

Revision ID: 0002
Revises: a3183d34be98
Create Date: 2026-08-13 15:36:10.258074

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = 'a3183d34be98'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'api_keys',
        sa.Column('scopes', postgresql.ARRAY(sa.TEXT()), nullable=True),
    )
    op.add_column(
        'api_keys',
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('api_keys', 'expires_at')
    op.drop_column('api_keys', 'scopes')
