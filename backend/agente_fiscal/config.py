"""Centralized configuration via Pydantic BaseSettings.

Single source of truth for all environment variables.
Sub-models group related config: Redis, credentials, etc.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RedisConfig(BaseSettings):
	"""Redis connection configuration (sync + async).

	Env vars:
	  - ``REDIS_URL`` for async ``RedisStore`` (api/server.py)
	  - ``MEMORY_REDIS_CACHE_URL`` for sync cache (memory/client.py)
	  - ``MEMORY_REDIS_MAX_MB`` memory limit for cache writes
	"""

	model_config = SettingsConfigDict(extra='ignore')

	url: str = Field(default='redis://localhost:6379/0', alias='REDIS_URL')
	cache_url: str = Field(default='redis://localhost:6379/0', alias='MEMORY_REDIS_CACHE_URL')
	max_mb: int = Field(default=25, alias='MEMORY_REDIS_MAX_MB')


class DatabaseConfig(BaseSettings):
	"""PostgreSQL connection settings (Neon).

	Env vars:
	  - ``DATABASE_URL`` — pooled URL; used by the application async engine
	  - ``DATABASE_URL_UNPOOLED`` — direct URL; used by Alembic migrations
	    (transaction poolers break the prepared-statement protocol)
	"""

	model_config = SettingsConfigDict(env_file='.env', extra='ignore')

	url: str = Field(default='', alias='DATABASE_URL')
	url_unpooled: str = Field(default='', alias='DATABASE_URL_UNPOOLED')


class Credentials(BaseSettings):
	"""Estudio contable credentials and API keys.

	Env vars:
	  - ``ESTUDIO_CUIT`` — CUIT del estudio (representante legal)
	  - ``ESTUDIO_CLAVE_FISCAL`` — clave fiscal del estudio
	  - ``COMPOSIO_API_KEY`` — API key de Composio (browser automation)
	"""

	model_config = SettingsConfigDict(extra='ignore')

	cuit: str = Field(default='20324837796', alias='ESTUDIO_CUIT')
	clave_fiscal: str = Field(default='', alias='ESTUDIO_CLAVE_FISCAL')
	composio_api_key: str = Field(default='', alias='COMPOSIO_API_KEY')


class AppSettings(BaseSettings):
	"""Top-level application settings.

	Loads from ``.env`` file automatically. Aggregates all sub-configs.

	Note:
		``Credentials`` fields are flattened here because pydantic-settings v2
		does **not** resolve env vars in nested ``BaseSettings`` models by
		default. The ``credentials`` property recreates the nested object for
		backward compatibility with existing callers.
	"""

	model_config = SettingsConfigDict(
		env_file='.env',
		extra='ignore',
		# pydantic-settings 2.15+ JSON-decodes complex fields at source level,
		# which would crash on comma-separated values like CORS_ORIGINS.
		enable_decoding=False,
	)

	redis: RedisConfig = RedisConfig()
	database: DatabaseConfig = DatabaseConfig()

	# ── CORS origins (comma-separated env var) ───────────────────────────
	cors_origins: list[str] = Field(
		default=['http://localhost:3000', 'http://localhost:3001'],
		alias='CORS_ORIGINS',
		description='Comma-separated list of allowed CORS origins',
	)

	@field_validator('cors_origins', mode='before')
	@classmethod
	def _parse_cors_origins(cls, v: str | list[str]) -> list[str]:
		"""Parse comma-separated string into list, or pass list through."""
		if isinstance(v, str):
			return [origin.strip() for origin in v.split(',') if origin.strip()]
		return v

	# ── Flattened credentials ──────────────────────────────────────────
	cuit: str = Field(default='20324837796', alias='ESTUDIO_CUIT')
	clave_fiscal: str = Field(default='', alias='ESTUDIO_CLAVE_FISCAL')
	composio_api_key: str = Field(default='', alias='COMPOSIO_API_KEY')

	# ── Clerk (JWT auth) ────────────────────────────────────────────────
	clerk_secret_key: str = Field(default='', alias='CLERK_SECRET_KEY')
	clerk_domain: str = Field(default='', alias='CLERK_DOMAIN')

	# ── Sentry (error/performance monitoring) ─────────────────────────────
	sentry_dsn: str = Field(default='', alias='SENTRY_DSN')
	app_env: str = Field(default='development', alias='APP_ENV')

	# ── Resend (email delivery — adapters/resend_email.py) ───────────────
	resend_api_key: str = Field(default='', alias='RESEND_API_KEY')
	email_from: str = Field(
		default='',
		alias='EMAIL_FROM',
		description='Remitente verificado en Resend, ej. "Estudio Contable <reportes@tudominio.com>"',
	)

	# ── Memory (Engram retention) ───────────────────────────────────────
	memory_enabled: bool = Field(
		default=True,
		alias='MEMORY_ENABLED',
		description='If False, fully disables Engram/Redis memory (no-op memory client)',
	)

	@property
	def credentials(self) -> Credentials:
		"""Recreate ``Credentials`` from flattened fields.

		Uses ``model_construct`` to bypass ``BaseSettings.__init__``, which
		would otherwise try to re-read env vars and potentially override
		the explicit values.
		"""
		return Credentials.model_construct(
			cuit=self.cuit,
			clave_fiscal=self.clave_fiscal,
			composio_api_key=self.composio_api_key,
		)


@lru_cache
def get_settings() -> AppSettings:
	"""Return cached AppSettings singleton.

	LRU-cached so repeated calls don't re-parse env vars.
	Use ``monkeypatch`` in tests to override individual fields.
	"""
	return AppSettings()


# Module-level shared singleton (imported by telemetry.py and others).
settings = get_settings()


# ── Shared constants ──────────────────────────────────────────────────────────────

CERT_DIR = Path('.certificados-arca')
CERT_PATH = CERT_DIR / 'produccion.crt'
KEY_PATH = CERT_DIR / 'produccion.key'
REPRESENTANTE_CUIT = get_settings().credentials.cuit
