"""report_runs approval columns + waiting_approval status

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-13 17:30:00.000000

Adds the human-in-the-loop approval persistence to ``report_runs``:
  - ``pending_actions`` — high-risk actions awaiting explicit approval
  - ``approved_by`` / ``approved_at`` — approver (Clerk user id) + timestamp
  - ``rejection_reason`` — why a ``waiting_approval`` run was rejected
And widens the ``status`` check constraint with ``'waiting_approval'``.

The status constraint's DB name under the metadata naming convention
(``ck_%(table_name)s_%(constraint_name)s``) is ``ck_report_runs_report_runs_status_check``.
The DROP is ``IF EXISTS`` against both that name and the bare
``report_runs_status_check`` so the migration is idempotent regardless of how
the constraint was named on any given database; the recreate uses the canonical
convention name so metadata ``create_all`` and Alembic agree.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CHECK_NAME = 'ck_report_runs_report_runs_status_check'

#: Name that a pre-fix run of this migration produced by letting the metadata
#: naming convention re-prefix the explicit name. Dropped defensively so the
#: migration stays idempotent against both variants.
_BUGGY_CHECK_NAME = 'ck_report_runs_ck_report_runs_report_runs_status_check'

_LEGACY_ALLOWED = "status IN ('queued', 'running', 'done', 'failed')"
_APPROVAL_ALLOWED = "status IN ('queued', 'running', 'done', 'failed', 'waiting_approval')"


def _recreate_status_check(condition: str) -> None:
    """Drop whichever status constraint name exists, then recreate it."""
    op.execute(
        f'ALTER TABLE report_runs DROP CONSTRAINT IF EXISTS {_CHECK_NAME}'
    )
    op.execute(
        f'ALTER TABLE report_runs DROP CONSTRAINT IF EXISTS {_BUGGY_CHECK_NAME}'
    )
    op.execute(
        'ALTER TABLE report_runs DROP CONSTRAINT IF EXISTS report_runs_status_check'
    )
    # op.f() marks the name as final so the metadata naming convention
    # (ck_%(table_name)s_%(constraint_name)s) does NOT re-prefix it, keeping
    # Alembic's DDL and Base.metadata.create_all() in agreement.
    op.create_check_constraint(
        op.f(_CHECK_NAME), 'report_runs', condition
    )


def upgrade() -> None:
    """Upgrade schema."""
    _recreate_status_check(_APPROVAL_ALLOWED)
    op.add_column(
        'report_runs',
        sa.Column(
            'pending_actions',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        'report_runs',
        sa.Column('approved_by', sa.String(length=255), nullable=True),
    )
    op.add_column(
        'report_runs',
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'report_runs',
        sa.Column('rejection_reason', sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('report_runs', 'rejection_reason')
    op.drop_column('report_runs', 'approved_at')
    op.drop_column('report_runs', 'approved_by')
    op.drop_column('report_runs', 'pending_actions')
    _recreate_status_check(_LEGACY_ALLOWED)