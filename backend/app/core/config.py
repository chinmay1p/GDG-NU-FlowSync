import os
from dataclasses import dataclass
from functools import lru_cache
from typing import List


def _parse_csv(value: str | None) -> List[str]:
	if not value:
		return []
	return [item.strip().rstrip('/') for item in value.split(',') if item.strip()]


@dataclass(frozen=True)
class Settings:
	cors_allow_origins: List[str]
	cors_allow_origin_regex: str


@lru_cache
def get_settings() -> Settings:
	default_origins = [
	 'http://localhost:5173',
	 'http://localhost:3000',
	 'http://127.0.0.1:5173',
	 'http://127.0.0.1:3000',
	]
	additional_origins = _parse_csv(os.getenv('CORS_ALLOW_ORIGINS'))
	all_origins: list[str] = []
	for origin in [*default_origins, *additional_origins]:
		if not origin:
			continue
		clean = origin.rstrip('/')
		if clean not in all_origins:
			all_origins.append(clean)

	cors_regex = os.getenv('CORS_ALLOW_ORIGIN_REGEX', r'https?://(localhost|127\.0\.0\.1)(:\d+)?')
	return Settings(cors_allow_origins=all_origins, cors_allow_origin_regex=cors_regex)
