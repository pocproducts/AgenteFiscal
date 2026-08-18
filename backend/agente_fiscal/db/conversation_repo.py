"""Conversation + message persistence (Postgres) — replaces the Redis stores.

``conversations``/``messages`` rows were already modeled (see
``db/models/business.py``) but nothing wrote them: chat.py persisted only to
Redis and the frontend used a local mock. This module is the SQLAlchemy 2.0
async repository that makes Postgres the source of truth for chat history.

Every function receives an ``AsyncSession`` — callers own the session lifecycle
(mirroring the ``request.app.state.session_factory`` pattern used by
``db_browser_sessions``). Ownership rules mirror the tenant-member roles:
``owner``/``admin`` see and delete every conversation of the tenant, ``member``
only their own.

Also hosts ``insert_generated_pdf``: writes the raw PDF bytes (``content_bytes``)
into ``generated_pdfs`` so a report can be re-served even if the filesystem path
disappeared.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from agente_fiscal.db.models import Conversation, GeneratedPdf, Message

logger = logging.getLogger(__name__)

#: Roles with tenant-wide visibility/ownership.
_ADMIN_ROLES = ('owner', 'admin')


def conv_uuid(conversation_id: str | uuid.UUID) -> uuid.UUID:
	"""UUID canónico de una conversación.

	El frontend envía ids opacos (no-UUID). Para que sigan siendo estables y
	determinísticos se derivan con ``uuid5(NAMESPACE_URL, 'conv:<id>')``; los
	ids que ya son UUID válidos se usan tal cual.
	"""
	try:
		return uuid.UUID(str(conversation_id))
	except (ValueError, TypeError, AttributeError):
		return uuid.uuid5(uuid.NAMESPACE_URL, f'conv:{conversation_id}')


def default_title(messages: Sequence[dict[str, Any]] | None) -> str | None:
	"""Título por defecto: primeros ~60 chars del primer mensaje de usuario."""
	for msg in messages or []:
		content = (msg.get('content') or '').strip()
		if msg.get('role') == 'user' and content:
			return content[:60] + ('...' if len(content) > 60 else '')
	return None


async def upsert_conversation(
	session: AsyncSession,
	tenant_id: uuid.UUID,
	user_id: uuid.UUID | None,
	profile_id: uuid.UUID | None,
	conversation_id: str | uuid.UUID,
	title: str | None,
	messages: Sequence[dict[str, Any]],
	*,
	status: str | None = None,
) -> uuid.UUID:
	"""Crea la conversación si no existe y appenda los mensajes nuevos.

	Idempotente por (role, content): los mensajes ya presentes en la
	conversación no se duplican (el frontend re-envía el historial completo y
	chat.py persiste por turno). ``status`` solo se aplica si se pasa
	explícitamente; en upserts posteriores se conserva el estado vigente.
	Commita la transacción antes de retornar.
	"""
	conv_id = conv_uuid(conversation_id)
	conv = await session.scalar(
		select(Conversation).where(
			Conversation.id == conv_id,
			Conversation.tenant_id == tenant_id,
		)
	)
	if conv is None:
		conv = Conversation(
			id=conv_id,
			tenant_id=tenant_id,
			user_id=user_id,
			profile_id=profile_id,
			title=title or default_title(messages),
			status=status or 'running',
		)
		session.add(conv)
		await session.flush()
		existing: set[tuple[str, str]] = set()
	else:
		if title:
			conv.title = title
		elif conv.title is None:
			conv.title = default_title(messages)
		if status:
			conv.status = status
		rows = await session.execute(
			select(Message.role, Message.parts).where(Message.conversation_id == conv.id)
		)
		existing = {(role, parts.get('content')) for role, parts in rows}

	to_add: list[Message] = []
	for msg in messages or []:
		role = msg.get('role') or ''
		content = msg.get('content') or ''
		if (role, content) in existing:
			continue
		existing.add((role, content))
		to_add.append(
			Message(
				conversation_id=conv.id,
				role=role,
				parts={'content': content, 'role': role},
			)
		)
	session.add_all(to_add)
	await session.commit()
	return conv_id


def _preview(messages: Sequence[tuple[str, str]]) -> str:
	"""Preview: primer contenido de assistant truncado a 120 chars."""
	for role, content in messages:
		if role == 'assistant' and content:
			return content[:120] + ('...' if len(content) > 120 else '')
	return ''


async def list_conversations(
	session: AsyncSession,
	tenant_id: uuid.UUID,
	user_id: uuid.UUID | None,
	role: str,
	limit: int = 50,
) -> list[dict[str, Any]]:
	"""Resúmenes de conversaciones, más recientes primero, listos para JSON.

	Dicts en camelCase (``messageCount``, ``updatedAt``, ``preview``) para que
	el frontend los consuma sin transformación. Filtro de ownership:
	``owner``/``admin`` ven todo el tenant; ``member`` solo sus propias.
	"""
	if role not in _ADMIN_ROLES:
		if user_id is None:
			return []
		stmt = select(Conversation).where(
			Conversation.tenant_id == tenant_id,
			Conversation.user_id == user_id,
		)
	else:
		stmt = select(Conversation).where(Conversation.tenant_id == tenant_id)
	stmt = stmt.order_by(Conversation.updated_at.desc()).limit(limit)
	convs = (await session.execute(stmt)).scalars().all()
	if not convs:
		return []

	rows = await session.execute(
		select(Message.conversation_id, Message.role, Message.parts)
		.where(Message.conversation_id.in_([c.id for c in convs]))
		.order_by(Message.created_at.asc())
	)
	by_conv: dict[uuid.UUID, list[tuple[str, str]]] = {c.id: [] for c in convs}
	for cid, role_msg, parts in rows:
		by_conv[cid].append((role_msg, parts.get('content')))

	return [
		{
			'id': str(c.id),
			'title': c.title or 'Nueva conversación',
			'messageCount': len(by_conv[c.id]),
			'updatedAt': c.updated_at.isoformat() if c.updated_at else None,
			'preview': _preview(by_conv[c.id]),
			'pinned': False,
			'folder': 'Work Projects',
		}
		for c in convs
	]


async def get_conversation(
	session: AsyncSession,
	tenant_id: uuid.UUID,
	conversation_id: str | uuid.UUID,
) -> dict[str, Any] | None:
	"""Conversación completa + mensajes ordenados por ``created_at``.

	Retorna ``None`` si no existe o pertenece a otro tenant.
	"""
	conv_id = conv_uuid(conversation_id)
	conv = await session.scalar(
		select(Conversation).where(
			Conversation.id == conv_id,
			Conversation.tenant_id == tenant_id,
		)
	)
	if conv is None:
		return None
	msgs = (
		await session.execute(
			select(Message)
			.where(Message.conversation_id == conv.id)
			.order_by(Message.created_at.asc())
		)
	).scalars().all()
	return {
		'id': str(conv.id),
		'title': conv.title or '',
		'status': conv.status,
		'createdAt': conv.created_at.isoformat() if conv.created_at else None,
		'updatedAt': conv.updated_at.isoformat() if conv.updated_at else None,
		'messages': [
			{
				'id': str(m.id),
				'role': m.role,
				'content': (m.parts or {}).get('content', ''),
				'parts': m.parts,
				'createdAt': m.created_at.isoformat() if m.created_at else None,
			}
			for m in msgs
		],
	}


async def set_conversation_status(
	session: AsyncSession,
	tenant_id: uuid.UUID,
	conversation_id: str | uuid.UUID,
	status: str,
) -> bool:
	"""Marca el estado de una conversación (``running``/``done``)."""
	conv_id = conv_uuid(conversation_id)
	conv = await session.scalar(
		select(Conversation).where(
			Conversation.id == conv_id,
			Conversation.tenant_id == tenant_id,
		)
	)
	if conv is None:
		return False
	conv.status = status
	await session.commit()
	return True


async def delete_conversation(
	session: AsyncSession,
	tenant_id: uuid.UUID,
	conversation_id: str | uuid.UUID,
	user_id: uuid.UUID | None,
	role: str,
) -> bool:
	"""Hard delete con ownership: owner/admin borran cualquiera del tenant;
	un member solo si la conversación es suya. Retorna si se borró algo."""
	stmt = select(Conversation).where(
		Conversation.id == conv_uuid(conversation_id),
		Conversation.tenant_id == tenant_id,
	)
	if role not in _ADMIN_ROLES:
		if user_id is None:
			return False
		stmt = stmt.where(Conversation.user_id == user_id)
	conv = await session.scalar(stmt)
	if conv is None:
		return False
	await session.delete(conv)
	await session.commit()
	return True


async def delete_all(
	session: AsyncSession,
	tenant_id: uuid.UUID,
	user_id: uuid.UUID | None,
	role: str,
) -> int:
	"""Borra todas las conversaciones del tenant (owner/admin) o solo las
	propias (member). Retorna el count de filas eliminadas."""
	stmt = select(Conversation.id).where(Conversation.tenant_id == tenant_id)
	if role not in _ADMIN_ROLES:
		if user_id is None:
			return 0
		stmt = stmt.where(Conversation.user_id == user_id)
	ids = (await session.execute(stmt)).scalars().all()
	if not ids:
		return 0
	await session.execute(delete(Conversation).where(Conversation.id.in_(ids)))
	await session.commit()
	return len(ids)


async def insert_generated_pdf(
	session: AsyncSession,
	report_run_id: uuid.UUID,
	storage_key: str,
	filename: str,
	data: bytes,
) -> bool:
	"""Persiste los bytes de un PDF en ``generated_pdfs`` (best-effort).

	``storage_key`` queda como referencia del filesystem; ``content_bytes``
	guarda el binario real para servir/renderizar sin depender del disco.
	"""
	if not data:
		return False
	session.add(
		GeneratedPdf(
			report_run_id=report_run_id,
			storage_key=storage_key,
			filename=filename,
			size_bytes=len(data),
			content_bytes=data,
		)
	)
	await session.commit()
	return True


__all__ = [
	'conv_uuid',
	'default_title',
	'delete_all',
	'delete_conversation',
	'get_conversation',
	'insert_generated_pdf',
	'list_conversations',
	'set_conversation_status',
	'upsert_conversation',
]
