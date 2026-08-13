"""Catalog of high-risk fiscal actions that must not run unattended.

The unattended worker flow (``worker.runner``) never executes an action in
``HIGH_RISK_ACTIONS`` — nor ``'send_email'`` when the client has an email
address — without prior explicit approval through
``POST /v1/report-runs/{id}/approve``. The proposal phase of the pipeline
(``PipelineService.run_proposal``) computes the list of side effects it WOULD
run; the worker parks a ``report_runs`` row in ``waiting_approval`` until a
tenant administrator approves or rejects it.
"""

from __future__ import annotations

#: Fiscal side effects the agent must NEVER run without explicit approval.
#: Reserved today (none are wired to a real integration); they slot in as
#: future pipeline actions behind this same approval gate.
HIGH_RISK_ACTIONS: frozenset[str] = frozenset(
    {'presentar', 'firmar', 'enviar_afip', 'facturar'}
)

#: Every action the pipeline may propose for approval. ``'send_email'`` is the
#: only real side effect in production right now; the ``HIGH_RISK_ACTIONS``
#: entries are the catalog future integrations will target.
VALID_ACTIONS: frozenset[str] = frozenset({'send_email'}) | HIGH_RISK_ACTIONS


class ApprovalRequiredError(RuntimeError):
    """Raised when a high-risk action is needed but no approval is present.

    Guard signal for the proposal/execution boundary: raises before any
    outbound side effect when the unattended flow lacks an explicit approval.
    """


def validate_actions(actions: list[str]) -> None:
    """Raise ``ValueError`` when ``actions`` contains an unknown action.

    Used by the approve endpoint to reject payloads that reference actions
    outside the catalog (422 ``INVALID_APPROVAL``).
    """
    unknown = sorted({a for a in actions if a not in VALID_ACTIONS})
    if unknown:
        raise ValueError(f'unknown action(s): {", ".join(unknown)}')