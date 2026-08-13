"""Fase 3 — in-process async worker for the fiscal report pipeline.

Moves the heavy ``PipelineService`` execution out of the HTTP request path: a
dedicated asyncio task polls ``report_runs`` rows in state ``queued`` and
executes them in the background, flipping each row to ``running`` and finally
``done``/``failed``. Runs whose proposal phase reports pending high-risk
actions are parked in ``waiting_approval`` until an administrator approves or
rejects them (see ``api/routes/report_runs.py``).
"""

from agente_fiscal.worker.runner import ReportRunner, run_loop, start_worker

__all__ = ['ReportRunner', 'run_loop', 'start_worker']
