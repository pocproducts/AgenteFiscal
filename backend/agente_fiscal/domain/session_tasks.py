"""Canonical agent-session task templates ("Acciones") for persisted telemetry.

AST-3: the ``tasks`` JSONB column of every ``agent_sessions`` row carries the
"Acciones" list the UI renders. ``consultaarca`` uses the canonical 7-task
template below (labels mirrored from ``SUBTASK_TEMPLATES['consultaarca']`` in
``backend/ai/tools/agent-execution.ts`` — the TS-side sync is P1b). Browser
rows get generic ``Acción N`` entries counted from the provider Usage API
``event_count`` when Composio answers (ADR-7); without a provider count the
list stays empty and the page renders a dash.
"""

from __future__ import annotations

from typing import Any

#: Canonical consultaarca "Acciones" labels, ordered task-0..task-6 (AST-3).
CONSULTAARCA_TASKS: tuple[str, ...] = (
	'Authenticating with ARCA gateway',
	'Fetching taxpayer profile',
	'Retrieving tax obligations',
	'Validating response schema',
	'Consulting payment obligations',
	'Cross-checking due dates',
	'Formatting output',
)

#: Per-tool canonical templates. Tools without a template (browser tools, other
#: engines) fall back to ``count``-driven generic entries — see
#: :func:`build_session_tasks`.
DEFAULT_TASKS_BY_TOOL: dict[str, tuple[str, ...]] = {
	'consultaarca': CONSULTAARCA_TASKS,
}


def build_session_tasks(
	tool: str,
	status: str,
	*,
	count: int | None = None,
) -> list[dict[str, str]]:
	"""Build the persisted ``tasks`` JSONB (Acciones) list for a session row.

	Args:
		tool: ``ToolSpec.tool_key`` of the run.
		status: Final row status — ``completed`` on success, ``error`` on a
		    failed run; every task entry carries the same final status (AST-3).
		count: Provider action count (Composio Usage API ``event_count``,
		    ADR-7). Only used by tools without a canonical template.

	Returns:
		For ``consultaarca``: the 7 canonical labels as
		``{'task': 'task-0..6', 'label': <label>, 'status': <status>}``.
		For other tools: ``count`` generic ``Acción N`` entries, or ``[]``
		when no provider count is available.
	"""
	labels = DEFAULT_TASKS_BY_TOOL.get(tool)
	if labels is not None:
		return [
			{'task': f'task-{i}', 'label': label, 'status': status}
			for i, label in enumerate(labels)
		]
	if not count:
		return []
	return [
		{'task': f'task-{i}', 'label': f'Acción {i + 1}', 'status': status}
		for i in range(count)
	]


__all__ = ['CONSULTAARCA_TASKS', 'DEFAULT_TASKS_BY_TOOL', 'build_session_tasks']