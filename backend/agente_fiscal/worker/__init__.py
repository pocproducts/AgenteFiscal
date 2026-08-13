"""Fase 3 — in-process async worker for the fiscal report pipeline.

Moves the heavy ``PipelineService.run_pipeline`` execution out of the HTTP
request path: a dedicated asyncio task polls ``report_runs`` rows in state
``queued`` and executes them in the background, flipping each row to
``running`` and finally ``done``/``failed``.
"""

from agente_fiscal.worker.runner import ReportRunner, run_loop, start_worker

__all__ = ['ReportRunner', 'run_loop', 'start_worker']
