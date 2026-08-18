"""generated_pdfs_bytes

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-17 10:00:00.000000

Adds ``content_bytes`` (LargeBinary) to ``generated_pdfs`` so PDF binaries
are persisted in the database. ``storage_key`` keeps the filesystem path as
fallback/reference, but the authoritative copy now lives in Postgres.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ── generated_pdfs.content_bytes ────────────────────────────────────────
    op.add_column('generated_pdfs', sa.Column('content_bytes', sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # ── generated_pdfs.content_bytes ────────────────────────────────────────
    op.drop_column('generated_pdfs', 'content_bytes')
