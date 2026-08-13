"""Telemetry — Sentry initialization shared by the web and worker processes.

The frontend and backend share ONE Sentry project (same DSN); the ``service``
tag separates their event streams. Keep this scheme in sync with
frontend/lib/telemetry.ts.
"""
import sentry_sdk

from agente_fiscal.config import settings


def init_telemetry(service: str = "backend") -> None:
	"""Initialize Sentry once per process. No-op when SENTRY_DSN is empty."""
	if not settings.sentry_dsn:
		return

	sentry_sdk.init(
		dsn=settings.sentry_dsn,
		environment=settings.app_env,
		traces_sample_rate=1.0,
		send_default_pii=False,
		enable_logs=True,
	)
	sentry_sdk.set_tag("service", service)