"""Memory configuration via environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class MemoryConfig(BaseSettings):
	"""Configuration for Engram memory and Redis cache.

	All vars prefixed with ``MEMORY_``. Loaded from env or .env file.
	"""

	model_config = SettingsConfigDict(env_prefix='MEMORY_')

	engram_url: str = 'http://localhost:7437'
	redis_cache_url: str = 'redis://localhost:6379/0'
	redis_max_mb: int = 25
	engram_timeout: int = 10
