"""Conversation deletion tests (CD-1..3) — tombstone semantics.

Covers the no-resurrect contract against the real test Postgres:

- CD-1: delete (tombstone) then the conversation disappears from list/get;
  a second delete reports False (→ 404 honesto).
- CD-2: title patch never creates; upsert refuses a tombstoned conversation.
- CD-3: patch on a missing/deleted conversation returns False (→ 404).

Fixtures follow the suite convention: ``db_reset`` opt-in, real async
Postgres at TEST_DATABASE_URL, row builders from conftest.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from agente_fiscal.db.conversation_repo import (
    conv_uuid,
    delete_conversation,
    list_conversations,
    patch_conversation_title,
    upsert_conversation,
)
from agente_fiscal.db.models import Conversation as ConversationRow

pytestmark = pytest.mark.usefixtures('db_reset')

CONV_ID = 'conv-delete-1'
#: El id persistido es el uuid5 derivado (mismo algoritmo que conv_uuid).
CONV_UUID = str(conv_uuid(CONV_ID))


async def _seed_conversation(session, tenant_id, *, title='Chat de prueba') -> None:
    """Insert a conversation row directly (bypasses repo creation semantics)."""
    row = ConversationRow(
        id=uuid.UUID(CONV_UUID),
        tenant_id=tenant_id,
        title=title,
        status='done',
    )
    session.add(row)
    await session.commit()


# ── CD-1: tombstone delete ─────────────────────────────────────────────────


async def test_delete_tombstones_and_hides_from_list(
    test_session_factory, make_tenant, make_user
) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
        user = await make_user(session, clerk_user_id='user_1')

    async with test_session_factory() as session:
        await _seed_conversation(session, tenant.id)

    # Delete succeeds (owner role → whole tenant).
    async with test_session_factory() as session:
        deleted = await delete_conversation(
            session, tenant.id, CONV_ID, user.id, role='owner'
        )
    assert deleted is True

    # Hides from list/get — never reappears on revalidation.
    async with test_session_factory() as session:
        listed = await list_conversations(session, tenant.id, user.id, role='owner')
        counts = (await session.execute(select(func.count()).select_from(ConversationRow))).scalar_one()
    assert all(c['id'] != CONV_UUID for c in listed if isinstance(c, dict))
    assert counts >= 1  # row retained (tombstone, not hard delete)


async def test_second_delete_reports_not_found(
    test_session_factory, make_tenant, make_user
) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
        user = await make_user(session, clerk_user_id='user_1')

    async with test_session_factory() as session:
        await _seed_conversation(session, tenant.id)
        first = await delete_conversation(session, tenant.id, CONV_ID, user.id, role='owner')
        second = await delete_conversation(session, tenant.id, CONV_ID, user.id, role='owner')
    assert first is True
    assert second is False  # → 404 honesto (CD-1 scenario 2)


async def test_delete_missing_conversation_returns_false(
    test_session_factory, make_tenant, make_user
) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
        user = await make_user(session, clerk_user_id='user_1')

    async with test_session_factory() as session:
        deleted = await delete_conversation(
            session, tenant.id, 'conv-does-not-exist', user.id, role='owner'
        )
    assert deleted is False


# ── CD-2: title save / upsert never resurrect ──────────────────────────────


async def test_patch_title_never_creates_on_missing(
    test_session_factory, make_tenant, make_user
) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
        user = await make_user(session, clerk_user_id='user_1')

    async with test_session_factory() as session:
        updated = await patch_conversation_title(
            session, tenant.id, 'conv-never-existed', 'Título nuevo'
        )
        count = (await session.execute(select(func.count()).select_from(ConversationRow))).scalar_one()
    assert updated is False  # → 404, no create (CD-2)
    assert count == 0


async def test_patch_title_on_deleted_returns_not_found(
    test_session_factory, make_tenant, make_user
) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
        user = await make_user(session, clerk_user_id='user_1')

    async with test_session_factory() as session:
        await _seed_conversation(session, tenant.id)
        deleted = await delete_conversation(session, tenant.id, CONV_ID, user.id, role='owner')
        updated = await patch_conversation_title(
            session, tenant.id, CONV_ID, 'No debe resucitar'
        )
    assert deleted is True
    assert updated is False  # 404, no resurrection (CD-2 scenario 1)


async def test_upsert_refuses_tombstoned_conversation(
    test_session_factory, make_tenant, make_user
) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
        user = await make_user(session, clerk_user_id='user_1')

    async with test_session_factory() as session:
        await _seed_conversation(session, tenant.id)
        await delete_conversation(session, tenant.id, CONV_ID, user.id, role='owner')
        # A new turn tries the stream upsert on the deleted chat → None.
        result = await upsert_conversation(
            session,
            tenant_id=tenant.id,
            user_id=user.id,
            profile_id=None,
            conversation_id=CONV_ID,
            title='Intento de resurrección',
            messages=[{'role': 'user', 'content': 'hola'}],
        )
    assert result is None  # CD-2 scenario 2 — never re-created


# ── CD-3: patch title on real conversation updates only title ──────────────


async def test_patch_title_succeeds_on_live_conversation(
    test_session_factory, make_tenant, make_user
) -> None:
    async with test_session_factory() as session:
        tenant = await make_tenant(session)
        user = await make_user(session, clerk_user_id='user_1')

    async with test_session_factory() as session:
        await _seed_conversation(session, tenant.id, title='Original')
        updated = await patch_conversation_title(
            session, tenant.id, CONV_ID, 'Renombrado'
        )
        listed = await list_conversations(session, tenant.id, user.id, role='owner')
    assert updated is True
    renamed = next((c for c in listed if c['id'] == CONV_UUID), None)
    assert renamed is not None
    assert renamed['title'] == 'Renombrado'